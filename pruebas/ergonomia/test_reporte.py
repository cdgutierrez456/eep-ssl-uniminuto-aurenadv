"""Reporte PDF: recomendaciones por reglas, contenido, maquetación en una página, publicación y QR."""

from datetime import datetime
from zoneinfo import ZoneInfo

import cv2
import httpx
import numpy as np
import pytest

from modulos.comun import esperar_envios, validar_evento
from modulos.ergonomia.config import AjustesLocales, validar_config
from modulos.ergonomia.estacion import Analizador
from modulos.ergonomia.flujo import TECLA_ENTER, Flujo
from modulos.ergonomia.interfaz.panel import EstadoPanel, Pantalla
from modulos.ergonomia.nucleo.angulos import AngulosCuerpo
from modulos.ergonomia.nucleo.intentos import Visita
from modulos.ergonomia.nucleo.mensajes import cierre_varios_intentos, linea_fija, mensaje_de_nivel
from modulos.ergonomia.nucleo.reba import Condiciones, calcular_reba
from modulos.ergonomia.nucleo.recomendaciones import cargar_reglas, recomendar
from modulos.ergonomia.publicacion import Critico, Publicador, id_de_reporte
from modulos.ergonomia.reporte import DatosReporte, armar_contenido
from modulos.ergonomia.reporte.contenido import BORRADOR, PIE, numero

from .test_angulos import postura
from .test_flujo import DE_PIE, ESPALDA_DOBLADA, SENTADILLA, Simulacion
from .test_vista import EstimadorFijo

FECHA = datetime(2026, 11, 14, 10, 32, tzinfo=ZoneInfo("America/Bogota"))
CONFIG = validar_config({})
FRAME = np.full((720, 1280, 3), 120, np.uint8)

DOBLADA = {"tronco": 102, "cuello": -35, "piernas": 31, "brazo": 107, "antebrazo": 16, "muneca": 29, "brazo_vertical": 4}
SEMI = {"tronco": 60, "cuello": -22, "piernas": 103, "brazo": 82, "antebrazo": 14, "muneca": 20, "brazo_vertical": 30}
PROFUNDA = {"tronco": 48, "cuello": -19, "piernas": 139, "brazo": 59, "antebrazo": 31, "muneca": None, "brazo_vertical": 12}
ANGULOS = AngulosCuerpo("derecho", 1, tronco=102, cuello=-35, piernas=31, brazo=107, antebrazo=16, muneca=29)


def datos_de(*posturas: dict, sesion_id="V-0142", condiciones: Condiciones | None = None, neutra=(-13.0, 27.0),
             desde_piso=True, **extra) -> DatosReporte:
    """Datos de reporte para el último de una serie de intentos."""
    visita = Visita(sesion_id)
    for angulos in posturas:
        intento = visita.registrar(calcular_reba(angulos, condiciones), 2.04, angulos["tronco"], angulos["piernas"],
                                   desde_piso)
    numero_de_intento = f"{intento.numero:02d}"
    return DatosReporte(f"REBA-0142-{numero_de_intento}", FECHA, intento, ANGULOS, tuple(visita.intentos), sesion_id,
                        neutra, **extra)


# --------------------------------------------------------------------------- #
# Recomendaciones por reglas escritas
# --------------------------------------------------------------------------- #
def test_de_dos_a_cuatro_recomendaciones_empezando_por_el_segmento_de_mayor_puntaje():
    recomendaciones = recomendar(calcular_reba(DOBLADA))
    assert 2 <= len(recomendaciones) <= 4
    assert recomendaciones[0].startswith("La espalda se dobló más de 60°. Flexiona las rodillas y mantén la espalda recta")
    assert recomendaciones[1].startswith("Acerca la carga al cuerpo")  # brazo 3, después del tronco 4
    assert len(set(recomendaciones)) == len(recomendaciones)


def test_tronco_alto_recomienda_flexionar_las_rodillas_y_mantener_la_espalda_recta():
    resultado = calcular_reba({"tronco": 40, "cuello": 5, "piernas": 5, "brazo": 10, "antebrazo": 80, "muneca": 5})
    assert resultado.segmentos["tronco"] == 3
    assert recomendar(resultado)[0].startswith("Flexiona las rodillas y mantén la espalda recta")


def test_a_quien_ya_flexiono_las_rodillas_no_se_le_pide_flexionarlas():
    resultado = calcular_reba(PROFUNDA)
    assert resultado.segmentos["tronco"] == 3 and resultado.segmentos["piernas"] == 3
    recomendaciones = recomendar(resultado)
    assert recomendaciones[0].startswith("Mantén la espalda recta al subir con la carga")
    assert recomendaciones[1].startswith("Agacharse a fondo carga las rodillas")
    assert not any("Flexiona las rodillas" in texto for texto in recomendaciones)


def test_la_carga_y_el_agarre_van_primero_cambiar_la_tarea_pesa_mas_que_la_tecnica():
    resultado = calcular_reba(DOBLADA, Condiciones(peso_carga_kg=12, agarre="malo"))
    recomendaciones = recomendar(resultado)
    assert recomendaciones[0].startswith("La carga supera los 10 kg")
    assert recomendaciones[1].startswith("El agarre es deficiente")
    assert len(recomendaciones) == 4


def test_postura_casi_neutra_se_completa_con_recomendaciones_generales():
    resultado = calcular_reba({"tronco": 0, "cuello": 5, "piernas": 0, "brazo": 0, "antebrazo": 80, "muneca": 0})
    assert recomendar(resultado) == cargar_reglas()["generales"][:2]


def test_un_segmento_no_estimado_no_genera_recomendacion():
    resultado = calcular_reba({**DOBLADA, "muneca": None})
    assert not any("muñecas" in texto for texto in recomendar(resultado, maximo=10))
    con_muneca = recomendar(calcular_reba(DOBLADA), maximo=10)
    assert any("muñecas" in texto for texto in con_muneca)


def test_las_reglas_estan_en_un_archivo_de_datos_y_no_culpan_a_la_persona():
    reglas = cargar_reglas()
    textos = [regla[clave] for lista in (*reglas["segmentos"].values(), reglas["carga"], reglas["agarre"])
              for regla in lista for clave in ("texto", "texto_con_rodillas_flexionadas") if clave in regla]
    textos += reglas["generales"]
    assert set(reglas["segmentos"]) == {"tronco", "cuello", "piernas", "brazo", "antebrazo", "muneca"}
    for texto in textos:
        assert texto.strip() and not any(r in texto.lower() for r in ("mal hecho", "lo hiciste mal", "tu culpa", "error tuyo"))


# --------------------------------------------------------------------------- #
# Contenido del reporte
# --------------------------------------------------------------------------- #
def test_pie_obligatorio():
    contenido = armar_contenido(datos_de(DOBLADA))
    assert contenido.pie == PIE == (
        "Estimación automática con visión artificial. Debe ser validada por un profesional de SST. "
        "Método REBA (Hignett & McAtamney, 2000). Torsión e inclinación lateral no evaluadas.")
    assert contenido.borrador == BORRADOR == "Borrador — validar en campo"


def test_encabezado_y_resultado():
    contenido = armar_contenido(datos_de(DOBLADA))
    assert contenido.titulo == "Evaluación ergonómica REBA" and contenido.reporte_id == "REBA-0142-01"
    assert contenido.subtitulo == "Visitante V-0142 · Intento 1" and contenido.fecha == "14/11/2026 10:32"
    assert (contenido.puntaje, contenido.nivel) == (9, "alto")
    assert contenido.etiqueta == "Riesgo alto · intervenir pronto"
    assert contenido.accion == "Es necesario intervenir pronto."
    assert contenido.mensaje == "Si esta postura se repite en un trabajo, la tarea debe modificarse pronto."
    assert contenido.tecnica == (("Flexión de espalda 102° · alta", "alta"), ("Rodillas 31° · poco flexionadas", "intermedio"))
    assert contenido.condiciones == "Carga 5 kg · Agarre bueno · Lado derecho · Duración 2,0 s · Carga en el piso"
    sin_numero = armar_contenido(datos_de(DOBLADA, sesion_id=None, desde_piso=False))
    assert sin_numero.subtitulo == "Sin número de visitante · Intento 1"
    assert sin_numero.condiciones.endswith("· Carga elevada")


def test_tabla_de_angulos_y_puntajes_por_segmento_y_calculo():
    contenido = armar_contenido(datos_de(DOBLADA))
    filas = {fila.nombre: fila for fila in contenido.segmentos}
    assert list(filas) == ["Tronco", "Cuello", "Piernas", "Brazo", "Antebrazo", "Muñeca"]
    assert (filas["Tronco"].angulo, filas["Tronco"].puntaje) == ("102°", 4)
    assert (filas["Brazo"].puntaje, filas["Brazo"].nota) == (3, "se resta 1: persona inclinada")
    assert filas["Muñeca"].nota == "estimación de baja confianza"
    r = datos_de(DOBLADA).intento.resultado
    assert dict(contenido.calculo) == {
        "Tabla A (cuello, tronco, piernas)": str(r.tabla_a), "Carga o fuerza": "+1", "Puntaje A": str(r.puntaje_a),
        "Tabla B (brazo, antebrazo, muñeca)": str(r.tabla_b), "Agarre": "+0", "Puntaje B": str(r.puntaje_b),
        "Tabla C": str(r.tabla_c), "Actividad": "+0", "REBA final": "9",
    }
    assert contenido.calculo[-1] == ("REBA final", "9")


def test_notas_la_tolerancia_de_erguido_va_siempre_explicita():
    notas = armar_contenido(datos_de(DOBLADA)).notas
    assert notas[0] == "Postura erguida con tolerancia de ±5°."
    assert "Tronco y cuello medidos desde la postura de pie de la persona (tronco -13°, cuello 27°)." in notas
    assert "Brazo: se resta 1 por persona inclinada con el brazo a favor de la gravedad." in notas
    assert "No evaluado y por eso no suma: torsión, inclinación lateral y abducción." in notas
    assert any("fotograma crítico" in nota and "0,3 s" in nota for nota in notas)
    assert not any("Muñeca no estimada" in nota for nota in notas)
    sin_calibrar = armar_contenido(datos_de(DOBLADA, neutra=None)).notas
    assert "Postura de pie sin calibrar: ángulos sin corregir." in sin_calibrar


def test_muneca_no_estimada_se_declara_como_cota_inferior_solo_cuando_aplica():
    contenido = armar_contenido(datos_de(PROFUNDA))
    assert "Muñeca no estimada: se asume el mínimo (1); el puntaje final es una cota inferior." in contenido.notas
    muneca = contenido.segmentos[-1]
    assert (muneca.angulo, muneca.puntaje, muneca.nota) == ("—", None, "no estimado: se asume 1")
    # Sin el ajuste del brazo, su nota no aparece
    sin_ajuste = armar_contenido(datos_de({**DOBLADA, "tronco": 30, "brazo": 30}))
    assert not any(nota.startswith("Brazo:") for nota in sin_ajuste.notas)


@pytest.mark.parametrize("postura_, nivel", [(DOBLADA, "alto"), ({**DOBLADA, "tronco": 30, "brazo": 30, "cuello": 5}, "medio")])
def test_seccion_que_significa_este_resultado(postura_, nivel):
    contenido = armar_contenido(datos_de(postura_))
    mensaje = mensaje_de_nivel(nivel)
    assert contenido.nivel == nivel
    assert contenido.significado == {
        "titulo": "Qué significa este resultado", "etiqueta": mensaje.etiqueta, "accion": mensaje.accion,
        "ampliado": mensaje.ampliado, "linea_fija": linea_fija(),
    }


def test_con_un_solo_intento_no_hay_comparacion_ni_cierre():
    contenido = armar_contenido(datos_de(DOBLADA))
    assert contenido.comparacion == () and contenido.lectura is None
    assert "cierre" not in contenido.significado


def test_con_varios_intentos_va_la_comparacion_y_el_cierre_sobre_redisenar_la_tarea():
    contenido = armar_contenido(datos_de(DOBLADA, SEMI))
    assert contenido.significado["cierre"] == cierre_varios_intentos()
    assert [(f.intento, f.espalda, f.rodillas) for f in contenido.comparacion] == [
        ("Intento 1", "102°", "31°"), ("Intento 2", "60°", "103°")]
    assert [f.puntaje for f in contenido.comparacion] == [i.puntaje for i in datos_de(DOBLADA, SEMI).intentos]
    assert contenido.lectura.startswith("Espalda 42° más recta")
    assert contenido.subtitulo.endswith("Intento 2")


def test_la_comparacion_muestra_como_mucho_los_tres_ultimos_intentos():
    contenido = armar_contenido(datos_de(DOBLADA, SEMI, DOBLADA, SEMI, PROFUNDA))
    assert [f.intento for f in contenido.comparacion] == ["Intento 3", "Intento 4", "Intento 5"]


def test_pista_contextual_en_el_reporte():
    assert armar_contenido(datos_de(DOBLADA)).pista.startswith("Desde el piso, incluso con buena técnica")
    assert armar_contenido(datos_de(DOBLADA, desde_piso=None)).pista is None
    elevada = armar_contenido(datos_de(DOBLADA, {**DOBLADA, "tronco": 15, "brazo": 30, "cuello": 5}, desde_piso=False))
    assert elevada.pista == "Elevar la carga es un control de ingeniería: cambia la tarea, no solo la técnica."


def test_numero_con_coma_decimal():
    assert numero(2.04) == "2,0" and numero(0.3) == "0,3" and numero(12.345, 2) == "12,35"


def test_id_de_reporte():
    assert id_de_reporte("V-0142", 1) == "REBA-0142-01"
    assert id_de_reporte("V-12345", 12) == "REBA-12345-12"
    sin_numero = id_de_reporte(None, 2)
    assert sin_numero.startswith("REBA-") and sin_numero.endswith("-02") and len(sin_numero) == 14
    assert id_de_reporte(None, 2) != sin_numero  # al azar: dos reportes sin visitante no chocan
    # Una visita sin número conserva su código en todos sus reportes; el número de visitante manda
    assert id_de_reporte(None, 1, "7F3A9C") == "REBA-7F3A9C-01" and id_de_reporte(None, 2, "7F3A9C") == "REBA-7F3A9C-02"
    assert id_de_reporte("V-0142", 1, "7F3A9C") == "REBA-0142-01"
    assert Visita().codigo != Visita().codigo and len(Visita().codigo) == 6


# --------------------------------------------------------------------------- #
# Maquetación: una página, sin desbordes
# --------------------------------------------------------------------------- #
def _imagen_de_prueba(tmp_path):
    ruta = tmp_path / "critico.jpg"
    cv2.imwrite(str(ruta), np.full((720, 1280, 3), 90, np.uint8))
    return ruta


def test_el_pdf_cabe_en_una_pagina_en_el_caso_mas_cargado(tmp_path):
    pytest.importorskip("fpdf")
    from modulos.ergonomia.reporte.pdf import generar_reporte

    datos = datos_de(DOBLADA, SEMI, DOBLADA, PROFUNDA, condiciones=Condiciones(peso_carga_kg=12, agarre="malo"),
                     peso_carga_kg=12, agarre="malo", ruta_imagen=_imagen_de_prueba(tmp_path))
    contenido = armar_contenido(datos)
    assert len(contenido.recomendaciones) == 4 and len(contenido.comparacion) == 3 and contenido.pista
    assert "cierre" in contenido.significado and any("Muñeca no estimada" in n for n in contenido.notas)
    generado = generar_reporte(datos, tmp_path / "reporte.pdf")
    assert generado.paginas == 1 and not generado.desborde and generado.escala == 1.0
    crudo = generado.ruta.read_bytes()
    assert crudo.startswith(b"%PDF-") and len(crudo) > 5000
    assert crudo.count(b"/Type /Page\n") + crudo.count(b"/Type /Page ") + crudo.count(b"/Type /Page>") <= 1


def test_el_pdf_se_genera_sin_imagen_y_sin_numero_de_visitante(tmp_path):
    pytest.importorskip("fpdf")
    from modulos.ergonomia.reporte.pdf import generar_reporte

    generado = generar_reporte(datos_de(DOBLADA, sesion_id=None), tmp_path / "carpeta nueva" / "reporte sin número.pdf")
    assert generado.ruta.is_file() and generado.paginas == 1 and not generado.desborde


def test_si_no_cabe_se_achica_la_letra_y_si_ni_asi_cabe_se_avisa(tmp_path):
    pytest.importorskip("fpdf")
    from dataclasses import replace

    from modulos.ergonomia.reporte.pdf import generar_reporte

    contenido = armar_contenido(datos_de(DOBLADA, SEMI, PROFUNDA))
    # Se agregan recomendaciones hasta que deje de caber con la letra normal
    achicado = None
    for extra in range(1, 40):
        largo = replace(contenido, recomendaciones=contenido.recomendaciones + contenido.recomendaciones[:1] * extra)
        generado = generar_reporte(largo, tmp_path / "largo.pdf")
        if generado.escala < 1.0:
            achicado = generado
            break
    assert achicado is not None and achicado.paginas == 1 and not achicado.desborde
    enorme = replace(contenido, recomendaciones=contenido.recomendaciones * 12)
    desbordado = generar_reporte(enorme, tmp_path / "enorme.pdf")
    assert desbordado.paginas == 1 and desbordado.desborde  # se genera igual, pero queda avisado


def test_los_signos_que_no_estan_en_las_fuentes_basicas_se_reemplazan():
    pytest.importorskip("fpdf")
    from modulos.ergonomia.reporte.pdf import latin1

    assert latin1("Borrador — validar en campo") == "Borrador - validar en campo"
    assert latin1("Intento 1 → Intento 2 · 60° ±5 ñ á") == "Intento 1 a Intento 2 · 60° ±5 ñ á"
    assert latin1("Brazo −1…") == "Brazo -1..."
    latin1("日本").encode("latin-1")  # lo desconocido se sustituye, no rompe el PDF


# --------------------------------------------------------------------------- #
# Publicación: PDF subido y evento reporte_generado
# --------------------------------------------------------------------------- #
def test_publica_reporte_generado_con_su_pdf(entorno, tmp_path):
    pytest.importorskip("fpdf")
    entorno.encender()
    analisis = Analizador(EstimadorFijo(postura(**ESPALDA_DOBLADA))).analizar(FRAME, 0, CONFIG)
    visita = Visita("V-0142")
    intento = visita.registrar(analisis.resultado, 2.3, 95, 35, True)
    publicador = Publicador(tmp_path / "capturas")
    critico = Critico(FRAME, analisis.puntos, analisis.angulos, (0.0, 0.0))
    publicado = publicador.publicar_levantamiento(critico, intento, "V-0142", CONFIG, tuple(visita.intentos)).result(30)
    publicador.cerrar()
    assert esperar_envios(10)

    evaluacion, reporte = httpx.get(entorno.url + "/api/eventos").json()  # primero la evaluación, luego el reporte
    assert (evaluacion["tipo"], reporte["tipo"]) == ("evaluacion_reba", "reporte_generado")
    assert reporte == publicado.evento_reporte
    validar_evento(reporte)
    assert (reporte["estacion"], reporte["severidad"], reporte["sesion_id"]) == ("ergonomia", "info", "V-0142")
    datos = reporte["datos"]
    assert datos["reporte_id"] == "REBA-0142-01" and datos["intento"] == 1
    assert datos["evaluacion_id"] == evaluacion["id"]  # el reporte dice de qué evaluación es
    assert reporte["adjuntos"] == [{"tipo": "pdf", "ruta": datos["url_reporte"]}]
    assert datos["url_reporte"].startswith("media/") and datos["url_reporte"].endswith(".pdf")
    en_el_receptor = tmp_path / "receptor" / datos["url_reporte"]
    assert en_el_receptor.read_bytes().startswith(b"%PDF-")  # el archivo llegó
    assert publicado.ruta_pdf.parent == tmp_path / "reportes" and publicado.ruta_pdf.is_file()


def test_si_el_reporte_falla_la_evaluacion_se_publica_igual(entorno, tmp_path, monkeypatch, caplog):
    entorno.encender()
    analisis = Analizador(EstimadorFijo(postura(**ESPALDA_DOBLADA))).analizar(FRAME, 0, CONFIG)
    intento = Visita().registrar(analisis.resultado, 2.0)
    publicador = Publicador(tmp_path / "capturas")
    monkeypatch.setattr(publicador, "_publicar_reporte", lambda *a, **k: (_ for _ in ()).throw(OSError("disco lleno")))
    publicado = publicador.publicar_levantamiento(Critico(FRAME, analisis.puntos, analisis.angulos), intento, None,
                                                  CONFIG).result(30)
    publicador.cerrar()
    assert esperar_envios(10)
    assert publicado.evento_reporte is None and publicado.ruta_pdf is None
    assert [e["tipo"] for e in httpx.get(entorno.url + "/api/eventos").json()] == ["evaluacion_reba"]
    assert "No se pudo generar o publicar el reporte PDF" in caplog.text


def test_cada_intento_de_la_visita_tiene_su_reporte_y_el_segundo_trae_la_comparacion(entorno, tmp_path, monkeypatch):
    pytest.importorskip("fpdf")
    from modulos.ergonomia.reporte import pdf

    contenidos = []
    original = pdf.generar_reporte
    monkeypatch.setattr(pdf, "generar_reporte",
                        lambda datos, ruta: (contenidos.append(armar_contenido(datos)), original(datos, ruta))[1])
    entorno.encender()
    publicador = Publicador(tmp_path / "capturas")
    flujo = Flujo(publicador)
    sim = Simulacion(flujo)
    for tecla in "142":
        flujo.tecla(ord(tecla))
    flujo.tecla(TECLA_ENTER)
    sim.levantar(ESPALDA_DOBLADA)
    sim.levantar(SENTADILLA)
    publicador.cerrar()
    assert esperar_envios(10)
    reportes = [e for e in httpx.get(entorno.url + "/api/eventos").json() if e["tipo"] == "reporte_generado"]
    assert [r["datos"]["reporte_id"] for r in reportes] == ["REBA-0142-01", "REBA-0142-02"]
    assert all(r["sesion_id"] == "V-0142" for r in reportes)
    assert [len(c.comparacion) for c in contenidos] == [0, 2]
    assert "cierre" not in contenidos[0].significado and "cierre" in contenidos[1].significado


# --------------------------------------------------------------------------- #
# QR hacia el pasaporte del visitante
# --------------------------------------------------------------------------- #
def test_la_url_publica_sale_del_entorno(monkeypatch):
    monkeypatch.setenv("BASE_URL_PUBLICA", " https://sst.aurenadv.com/ ")
    assert AjustesLocales.desde_entorno().base_url_publica == "https://sst.aurenadv.com"
    monkeypatch.setenv("BASE_URL_PUBLICA", "")
    assert AjustesLocales.desde_entorno().base_url_publica is None
    monkeypatch.delenv("BASE_URL_PUBLICA")
    assert AjustesLocales.desde_entorno().base_url_publica is None


def test_solo_hay_qr_con_url_publica_numero_de_visitante_y_al_menos_un_intento():
    base = "https://sst.aurenadv.com"
    flujo = Flujo()
    sim = Simulacion(flujo)
    assert flujo.url_del_pasaporte(base) is None  # sin número de visitante
    for tecla in "142":
        flujo.tecla(ord(tecla))
    flujo.tecla(TECLA_ENTER)
    assert flujo.url_del_pasaporte(base) is None  # con número pero sin intentos: aún no hay reporte
    sim.levantar(ESPALDA_DOBLADA)
    assert flujo.url_del_pasaporte(base) == "https://sst.aurenadv.com/r/V-0142"
    assert flujo.url_del_pasaporte(base + "/") == "https://sst.aurenadv.com/r/V-0142"
    assert flujo.url_del_pasaporte(None) is None and flujo.url_del_pasaporte("") is None  # sin URL pública, sin QR
    sin_numero = Flujo()
    Simulacion(sin_numero).levantar(ESPALDA_DOBLADA)
    assert sin_numero.url_del_pasaporte(base) is None


def test_la_pantalla_dibuja_el_qr_solo_si_hay_direccion():
    pytest.importorskip("qrcode")
    pantalla = Pantalla(1920, 1080)
    textos = dict(config=CONFIG, inferior=("Flexión de espalda: 95° · alta", "Rodillas 35° · poco flexionadas", "REBA"))
    franja = slice(pantalla.alto - pantalla.alto_franja, pantalla.alto)
    sin_qr = pantalla.componer(None, EstadoPanel(**textos))[franja, : pantalla.ancho_video].copy()
    con_qr = pantalla.componer(None, EstadoPanel(**textos, qr_url="https://sst.aurenadv.com/r/V-0142"))[
        franja, : pantalla.ancho_video].copy()
    derecha = slice(pantalla.ancho_video - pantalla.alto_franja - 40, pantalla.ancho_video)
    assert (sin_qr[:, derecha] != con_qr[:, derecha]).any()
    marfil = (con_qr[:, derecha] == np.array((0xEA, 0xF1, 0xF2), np.uint8)).all(axis=2).mean()
    assert marfil > 0.2  # el fondo del código, en marfil
    assert (sin_qr[:, :600] == con_qr[:, :600]).all()  # el texto de la izquierda no cambia
    # Otra dirección da otro código
    otro = pantalla.componer(None, EstadoPanel(**textos, qr_url="https://sst.aurenadv.com/r/V-0007"))[
        franja, : pantalla.ancho_video]
    assert (otro[:, derecha] != con_qr[:, derecha]).any()


def test_una_visita_sin_numero_usa_el_mismo_codigo_en_todos_sus_reportes(entorno, tmp_path):
    pytest.importorskip("fpdf")
    entorno.encender()
    publicador = Publicador(tmp_path / "capturas")
    flujo = Flujo(publicador)
    sim = Simulacion(flujo)
    sim.levantar(ESPALDA_DOBLADA)
    sim.levantar(SENTADILLA)
    publicador.cerrar()
    assert esperar_envios(10)
    reportes = [e for e in httpx.get(entorno.url + "/api/eventos").json() if e["tipo"] == "reporte_generado"]
    codigo = flujo.visita.codigo
    assert [r["datos"]["reporte_id"] for r in reportes] == [f"REBA-{codigo}-01", f"REBA-{codigo}-02"]
    assert all("sesion_id" not in r for r in reportes)
