"""Servicio HTTP del inspector: API, escenas preparadas, configuración remota y publicación del evento.

Ninguna prueba llama a la API de Claude: el analizador usa el cliente simulado.
"""

import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from herramientas import precalcular_escenas
from modulos.comun import esperar_envios, validar_evento
from modulos.comun.config import RAIZ_REPO
from modulos.inspector.analisis import Analizador, CacheDeAnalisis, RegistroDeCostos
from modulos.inspector.configuracion import (
    Ajustes,
    ajustes_con_config,
    capacidades,
    config_por_defecto,
    puerto_del_servicio,
    validar_config,
)
from modulos.inspector.ejemplo import leer_ejemplo
from modulos.inspector.nucleo.esquema import normalizar_analisis
from modulos.inspector.nucleo.excel import AVISO_BORRADOR, FILA_AVISO, FILA_DATOS, LEMA, columna_de
from modulos.inspector.nucleo.imagen import AUREN_DEEP, codificar_jpeg, decodificar
from modulos.inspector.preparadas import guardar_resultado, leer_escena, listar_escenas
from modulos.inspector.servicio.app import crear_app
from modulos.inspector.servicio.publicacion import datos_del_evento

from .test_analisis import ClienteSimulado, Reloj, error_de_estado, respuesta
from .test_imagen import pixeles_de_color

FOTO = codificar_jpeg(np.full((900, 1200, 3), 120, np.uint8))
RESPUESTAS = leer_ejemplo("respuestas_bodega.json")
ANALISIS = normalizar_analisis(leer_ejemplo("analisis_bodega.json"), 1568, 1176)


def escena_en(carpeta, identificador="bodega", con_resultado=True, nombre="Bodega del stand"):
    destino = carpeta / identificador
    destino.mkdir(parents=True)
    (destino / "foto.jpg").write_bytes(FOTO)
    (destino / "escena.json").write_text(json.dumps({"id": identificador, "nombre": nombre}, ensure_ascii=False),
                                         encoding="utf-8")
    if con_resultado:
        guardar_resultado(identificador, ANALISIS, carpeta, modelo="claude-sonnet-5-5")
    return destino


class Servicio:
    """El servicio armado sobre carpetas temporales, con cliente de Claude simulado."""

    def __init__(self, tmp_path, *respuestas, config=None, publicar_eventos=False):
        self.reloj = Reloj()
        self.claude = ClienteSimulado(*respuestas, reloj=self.reloj)
        self.carpeta = tmp_path / "inspector"
        self.escenas = tmp_path / "escenas"
        self.escenas.mkdir(exist_ok=True)
        self.config = config_por_defecto(Ajustes())
        self.config.update(config or {})
        analizador = Analizador(Ajustes(), cliente=self.claude, cache=CacheDeAnalisis(self.carpeta / "cache"),
                                registro=RegistroDeCostos(self.carpeta / "costos.csv"), dormir=self.reloj.dormir,
                                reloj=self.reloj)
        self.http = TestClient(crear_app(Ajustes(), analizador=analizador, carpeta=self.carpeta,
                                         carpeta_escenas=self.escenas, config=lambda: self.config,
                                         publicar_eventos=publicar_eventos))

    def analizar(self, foto=FOTO, **campos):
        archivos = {"foto": ("foto.jpg", foto, "image/jpeg")} if foto is not None else None
        return self.http.post("/analizar", files=archivos, data=campos)

    def valorar(self, inspeccion_id, cuerpo=RESPUESTAS):
        return self.http.post(f"/valorar/{inspeccion_id}", json=cuerpo)


@pytest.fixture
def servicio(tmp_path, monkeypatch):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-de-prueba")
    monkeypatch.delenv("INSPECTOR_SOLO_ESCENAS", raising=False)
    return lambda *respuestas, **opciones: Servicio(tmp_path, *respuestas, **opciones)


# --------------------------------------------------------------------------- #
# POST /analizar
# --------------------------------------------------------------------------- #
def test_analizar_devuelve_la_inspeccion_con_sus_peligros(servicio):
    s = servicio(respuesta())
    r = s.analizar(escena="Bodega de prueba", sesion_id="V-0142")

    assert r.status_code == 200
    cuerpo = r.json()
    assert len(cuerpo["inspeccion_id"]) == 12
    assert (cuerpo["origen"], cuerpo["modelo"], cuerpo["borrador"]) == ("ia", "claude-sonnet-5-5", True)
    assert cuerpo["aviso"] == LEMA
    assert cuerpo["descripcion_general"].startswith("Bodega de almacenamiento")
    assert cuerpo["url_imagen"] == f"/imagen/{cuerpo['inspeccion_id']}"
    assert (cuerpo["ancho"], cuerpo["alto"]) == (1200, 900)
    assert [p["n"] for p in cuerpo["peligros"]] == [1, 2, 3, 4, 5, 6]
    primero = cuerpo["peligros"][0]
    assert primero["clasificacion"] == {"categoria": "condiciones_de_seguridad", "subcategoria": "trabajo en alturas",
                                        "nombre": "Condiciones de seguridad"}
    assert all(0 <= valor <= 1 for valor in primero["ubicacion"])
    assert primero["posible"] is False and cuerpo["peligros"][5]["posible"] is True  # confianza baja
    assert set(primero["controles_propuestos"]) == {"eliminacion", "sustitucion", "ingenieria", "administrativos", "epp"}
    # A Claude le llegó la foto ya reducida y con lo que dice la configuración
    assert "1200 x 900 píxeles" in s.claude.solicitudes[0]["messages"][0]["content"][1]["text"]


def test_la_imagen_de_la_inspeccion_viene_anotada_y_la_limpia_no(servicio):
    s = servicio(respuesta())
    inspeccion_id = s.analizar().json()["inspeccion_id"]

    anotada = s.http.get(f"/imagen/{inspeccion_id}")
    limpia = s.http.get(f"/imagen/{inspeccion_id}", params={"limpia": 1})
    assert anotada.status_code == limpia.status_code == 200
    assert anotada.headers["content-type"] == "image/jpeg"
    assert pixeles_de_color(decodificar(anotada.content), AUREN_DEEP, 25) > 1000   # las etiquetas numeradas
    assert pixeles_de_color(decodificar(limpia.content), AUREN_DEEP, 25) == 0
    assert decodificar(limpia.content).shape == (900, 1200, 3)


def test_la_foto_se_difumina_antes_de_enviarla_y_de_guardarla(servicio, monkeypatch):
    """Lo que sale a la nube y lo que queda en disco pasó por difuminar_rostros."""
    from modulos.inspector.nucleo import imagen as modulo_imagen

    monkeypatch.setattr(modulo_imagen, "difuminar_rostros", lambda frame: np.full_like(frame, 200))
    s = servicio(respuesta())
    inspeccion_id = s.analizar().json()["inspeccion_id"]

    import base64
    enviada = decodificar(base64.standard_b64decode(
        s.claude.solicitudes[0]["messages"][0]["content"][0]["source"]["data"]))
    guardada = decodificar(s.http.get(f"/imagen/{inspeccion_id}", params={"limpia": 1}).content)
    assert abs(int(enviada.mean()) - 200) <= 2 and abs(int(guardada.mean()) - 200) <= 2  # no el gris 120 original
    # Y en la carpeta de la inspección no queda ninguna copia del original
    for archivo in (s.carpeta / "inspecciones" / inspeccion_id).glob("*.jpg"):
        assert abs(int(decodificar(archivo.read_bytes())[:40, -40:].mean()) - 200) <= 3, archivo.name


def test_la_misma_foto_sale_de_la_cache(servicio):
    s = servicio(respuesta())
    primero, segundo = s.analizar().json(), s.analizar().json()
    assert (primero["origen"], segundo["origen"]) == ("ia", "cache")
    assert len(s.claude.solicitudes) == 1
    assert primero["inspeccion_id"] != segundo["inspeccion_id"]  # cada visita es una inspección distinta


@pytest.mark.parametrize("archivo, mensaje", [(b"esto no es una foto", "No se pudo leer la imagen"),
                                              (codificar_jpeg(np.zeros((100, 100, 3), np.uint8)), "muy pequeña")])
def test_una_foto_que_no_sirve_se_rechaza_sin_gastar_una_llamada(servicio, archivo, mensaje):
    s = servicio(respuesta())
    r = s.analizar(archivo)
    assert r.status_code == 422 and r.json()["error"] == "imagen_invalida" and mensaje in r.json()["mensaje"]
    assert s.claude.solicitudes == []


def test_sin_foto_ni_escena_se_pide_una(servicio):
    r = servicio().analizar(None)
    assert r.status_code == 422 and r.json()["error"] == "sin_foto"


# --------------------------------------------------------------------------- #
# Fallos del análisis y escenas preparadas
# --------------------------------------------------------------------------- #
def test_un_rechazo_ofrece_otra_toma_o_una_escena_preparada(servicio):
    s = servicio(respuesta(texto="", stop_reason="refusal", categoria="general_harms"))
    escena_en(s.escenas)
    r = s.analizar()

    assert r.status_code == 422
    cuerpo = r.json()
    assert cuerpo["error"] == "rechazo"
    assert cuerpo["mensaje"] == "No pudimos analizar esta foto. Intenta con otra toma o usa una escena preparada."
    assert cuerpo["escenas_preparadas"] == [{"id": "bodega", "nombre": "Bodega del stand",
                                            "url_imagen": "/escenas/bodega/imagen"}]
    filas = RegistroDeCostos(s.carpeta / "costos.csv").leer()
    assert [fila["resultado"] for fila in filas] == ["rechazo"]


def test_sin_internet_la_respuesta_trae_el_mensaje_y_las_escenas(servicio):
    import anthropic
    from .test_analisis import SOLICITUD_HTTP

    s = servicio(anthropic.APIConnectionError(request=SOLICITUD_HTTP), anthropic.APIConnectionError(request=SOLICITUD_HTTP))
    escena_en(s.escenas)
    r = s.analizar()
    assert r.status_code == 503
    assert r.json()["error"] == "sin_conexion" and "escena preparada" in r.json()["mensaje"]
    assert [escena["id"] for escena in r.json()["escenas_preparadas"]] == ["bodega"]


def test_una_falla_del_servicio_de_ia_no_tumba_el_servicio(servicio):
    import anthropic

    s = servicio(error_de_estado(anthropic.InternalServerError, 500), error_de_estado(anthropic.InternalServerError, 500),
                 respuesta())
    assert s.analizar().status_code == 503
    assert s.analizar().status_code == 200  # el siguiente intento sí funciona


def test_las_escenas_preparadas_se_listan_solo_si_ya_tienen_resultado(servicio):
    s = servicio()
    escena_en(s.escenas, "bodega")
    escena_en(s.escenas, "taller", con_resultado=False)
    (s.escenas / "notas.txt").write_text("no es una escena", encoding="utf-8")

    assert s.http.get("/escenas").json() == [{"id": "bodega", "nombre": "Bodega del stand",
                                             "url_imagen": "/escenas/bodega/imagen"}]
    imagen = s.http.get("/escenas/bodega/imagen")
    assert imagen.status_code == 200 and decodificar(imagen.content).shape == (675, 900, 3)
    assert s.http.get("/escenas/no_existe/imagen").status_code == 404
    assert s.http.get("/escenas/..%2F..%2Fcola/imagen").status_code == 404


def test_una_escena_preparada_no_llama_a_la_ia_y_funciona_de_punta_a_punta(servicio):
    s = servicio()  # sin respuestas: si llamara a Claude, fallaría
    escena_en(s.escenas)

    r = s.analizar(None, escena_preparada="bodega")
    assert r.status_code == 200
    cuerpo = r.json()
    assert (cuerpo["origen"], cuerpo["duracion_s"]) == ("escena_preparada", 0.0)
    assert len(cuerpo["peligros"]) == 6 and s.claude.solicitudes == []

    valorada = s.valorar(cuerpo["inspeccion_id"])
    assert valorada.status_code == 200 and len(valorada.json()["peligros"]) == 5
    assert s.http.get(valorada.json()["url_excel"]).status_code == 200


def test_una_escena_que_no_existe_o_sin_precalcular(servicio):
    s = servicio()
    escena_en(s.escenas, "taller", con_resultado=False)
    for identificador in ("no_existe", "taller", "../cola"):
        r = s.analizar(None, escena_preparada=identificador)
        assert r.status_code == 404 and r.json()["error"] == "escena_no_existe", identificador


def test_el_modo_solo_escenas_no_llama_a_la_ia(servicio):
    s = servicio(respuesta(), config={"solo_escenas_preparadas": True})
    escena_en(s.escenas)

    r = s.analizar()
    assert r.status_code == 503 and r.json()["error"] == "solo_escenas"
    assert r.json()["mensaje"] == "El análisis con IA está apagado en este momento. Usa una escena preparada."
    assert s.claude.solicitudes == []
    assert s.analizar(None, escena_preparada="bodega").status_code == 200
    assert s.http.get("/salud").json()["ia_disponible"] is False


# --------------------------------------------------------------------------- #
# POST /valorar, GET /excel y GET /imagen
# --------------------------------------------------------------------------- #
def test_valorar_calcula_el_riesgo_y_deja_el_excel(servicio):
    s = servicio(respuesta())
    inspeccion_id = s.analizar().json()["inspeccion_id"]
    r = s.valorar(inspeccion_id)

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["borrador"] is True and cuerpo["aviso"] == LEMA
    assert [p["n"] for p in cuerpo["peligros"]] == [1, 2, 3, 4, 5] and cuerpo["descartados"] == 1
    assert [p["valoracion"]["nivel_riesgo"] for p in cuerpo["peligros"]] == ["I", "II", "II", "III", "IV"]
    assert [p["valoracion"]["nr"] for p in cuerpo["peligros"]] == [1080, 200, 240, 50, None]
    assert cuerpo["resumen"] == {"peor_nivel": "I", "severidad": "critica",
                                 "por_nivel": {"I": 1, "II": 2, "III": 1, "IV": 1}}
    assert cuerpo["url_excel"] == f"/excel/{inspeccion_id}" and cuerpo["url_imagen"] == f"/imagen/{inspeccion_id}"
    assert (cuerpo["publicado"], cuerpo["evento_id"]) == (False, None)  # este servicio de prueba no publica

    excel = s.http.get(cuerpo["url_excel"])
    assert excel.status_code == 200
    assert f"matriz-ipevr-{inspeccion_id}.xlsx" in excel.headers["content-disposition"]
    hoja = load_workbook(io.BytesIO(excel.content)).active
    assert hoja.cell(row=FILA_AVISO, column=1).value == AVISO_BORRADOR
    assert [hoja.cell(row=FILA_DATOS + i, column=1).value for i in range(6)] == [1, 2, 3, 4, 5, None]
    assert hoja.cell(row=FILA_DATOS, column=columna_de("proceso")).value == "Almacenamiento"
    assert all(hoja.cell(row=FILA_DATOS + i, column=columna_de("requisito_legal")).value is None for i in range(5))
    assert len(hoja._images) == 1


def test_despues_de_valorar_la_imagen_solo_marca_los_peligros_que_quedaron(servicio):
    s = servicio(respuesta())
    inspeccion_id = s.analizar().json()["inspeccion_id"]
    antes = pixeles_de_color(decodificar(s.http.get(f"/imagen/{inspeccion_id}").content), AUREN_DEEP, 25)
    solo_uno = {"peligros": [{"n": 1, "frecuencia": "continua"}] + [{"n": n, "descartado": True} for n in range(2, 7)]}
    assert s.valorar(inspeccion_id, solo_uno).status_code == 200
    despues = pixeles_de_color(decodificar(s.http.get(f"/imagen/{inspeccion_id}").content), AUREN_DEEP, 25)
    assert 0 < despues < antes / 3  # de seis etiquetas a una


def test_se_puede_corregir_y_volver_a_valorar(servicio):
    s = servicio(respuesta())
    inspeccion_id = s.analizar().json()["inspeccion_id"]
    assert len(s.valorar(inspeccion_id).json()["peligros"]) == 5
    todos = {"peligros": [{"n": n, "frecuencia": "ocasional", "expuestos": 3} for n in range(1, 7)]}
    assert len(s.valorar(inspeccion_id, todos).json()["peligros"]) == 6


def test_descartar_todos_los_peligros_deja_una_matriz_vacia(servicio):
    s = servicio(respuesta())
    inspeccion_id = s.analizar().json()["inspeccion_id"]
    r = s.valorar(inspeccion_id, {"peligros": [{"n": n, "descartado": True} for n in range(1, 7)]})
    assert r.status_code == 200
    assert r.json()["peligros"] == [] and r.json()["resumen"]["peor_nivel"] is None
    assert r.json()["resumen"]["severidad"] == "info"
    assert s.http.get(r.json()["url_excel"]).status_code == 200


@pytest.mark.parametrize(
    "cuerpo, pista",
    [
        ({"peligros": []}, "Falta la respuesta"),
        ({}, "lista"),
        ({"peligros": [{"n": n} for n in range(1, 7)]}, "Falta la frecuencia"),
        ({"peligros": [{"n": n, "frecuencia": "diaria"} for n in range(1, 7)]}, "Peligro 1"),
    ],
)
def test_respuestas_incompletas_se_rechazan_con_un_mensaje_claro(servicio, cuerpo, pista):
    s = servicio(respuesta())
    inspeccion_id = s.analizar().json()["inspeccion_id"]
    r = s.valorar(inspeccion_id, cuerpo)
    assert r.status_code == 422 and r.json()["error"] == "respuestas_invalidas" and pista in r.json()["mensaje"]
    assert s.http.get(f"/excel/{inspeccion_id}").status_code == 404  # aún no hay matriz


@pytest.mark.parametrize("identificador", ["abcdef123456", "no-es-un-id", "..%2F..%2Fsecreto"])
def test_una_inspeccion_que_no_existe(servicio, identificador):
    s = servicio()
    assert s.valorar(identificador).status_code == 404
    assert s.http.get(f"/excel/{identificador}").status_code == 404
    assert s.http.get(f"/imagen/{identificador}").status_code == 404


# --------------------------------------------------------------------------- #
# GET /salud, /opciones y la interfaz
# --------------------------------------------------------------------------- #
def test_salud_no_revela_la_clave_y_trae_el_costo_promedio(servicio, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-clave-secreta-del-stand")
    s = servicio(respuesta())
    s.analizar()
    r = s.http.get("/salud")

    assert r.status_code == 200 and "sk-ant" not in r.text
    cuerpo = r.json()
    assert (cuerpo["estado"], cuerpo["modulo"], cuerpo["modelo"]) == ("ok", "inspector", "claude-sonnet-5-5")
    assert cuerpo["hay_clave"] is True and cuerpo["ia_disponible"] is True
    assert cuerpo["fotos_analizadas"] == 1 and cuerpo["costo_promedio_por_foto_usd"] == pytest.approx(0.021)


def test_salud_sin_clave(servicio, monkeypatch):
    s = servicio()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    cuerpo = s.http.get("/salud").json()
    assert cuerpo["hay_clave"] is False and cuerpo["ia_disponible"] is False


def test_ninguna_respuesta_del_servicio_lleva_la_clave(servicio, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-clave-secreta-del-stand")
    s = servicio(respuesta())
    analizada = s.analizar()
    valorada = s.valorar(analizada.json()["inspeccion_id"])
    for r in (analizada, valorada, s.http.get("/salud"), s.http.get("/opciones"), s.http.get("/escenas"), s.http.get("/")):
        assert "sk-ant" not in r.text


def test_opciones_trae_lo_necesario_para_pintar_los_formularios(servicio):
    cuerpo = servicio().http.get("/opciones").json()
    assert [f["id"] for f in cuerpo["frecuencias"]] == ["continua", "frecuente", "ocasional", "esporadica"]
    assert [c["id"] for c in cuerpo["controles_existentes"]] == ["ninguno", "senalizacion", "procedimiento", "epp",
                                                                 "proteccion_maquina"]
    assert [n["id"] for n in cuerpo["niveles_deficiencia"]] == ["muy_alto", "alto", "medio", "bajo"]
    assert [c["id"] for c in cuerpo["consecuencias"]] == ["mortal", "muy_grave", "grave", "leve"]
    assert [n["id"] for n in cuerpo["niveles_riesgo"]] == ["I", "II", "III", "IV"]
    assert all(n["color"].startswith("#") for n in cuerpo["niveles_riesgo"])
    assert len(cuerpo["categorias"]) == 7 and cuerpo["aviso"] == LEMA


def test_la_interfaz_provisional_muestra_siempre_el_aviso_de_borrador(servicio):
    r = servicio().http.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    pagina = r.text
    assert "<footer>Borrador generado con IA. La IA propone, el profesional de SST decide.</footer>" in pagina
    assert 'capture="environment"' in pagina and "Tomar foto" in pagina          # cámara trasera
    assert "Usar una escena preparada" in pagina and "Descargar matriz en Excel" in pagina
    for paso in ("Revisando la imagen…", "Identificando peligros…", "Proponiendo controles…"):
        assert paso in pagina
    assert "Posible — verificar" in pagina
    assert "#12343B" in pagina and "#F2F1EA" in pagina and "#C8F169" in pagina   # marca Auren
    assert "innerHTML" not in pagina  # los textos del análisis entran como texto, nunca como HTML
    assert "ANTHROPIC" not in pagina and "api.anthropic.com" not in pagina       # el navegador nunca llama a Claude


# --------------------------------------------------------------------------- #
# Configuración remota
# --------------------------------------------------------------------------- #
def test_la_configuracion_remota_cambia_el_modelo_y_el_maximo_de_peligros(servicio):
    s = servicio(respuesta(), config={"modelo": "claude-opus-5-5", "max_peligros": 3, "tiempo_maximo_s": 30})
    cuerpo = s.analizar().json()
    solicitud = s.claude.solicitudes[0]
    assert solicitud["model"] == "claude-opus-5-5" and solicitud["timeout"] == 30
    assert "como máximo 3 peligros" in solicitud["messages"][0]["content"][1]["text"]
    assert len(cuerpo["peligros"]) == 3 and cuerpo["modelo"] == "claude-opus-5-5"
    assert s.http.get("/salud").json()["modelo"] == "claude-opus-5-5"


def test_validar_config_completa_con_el_env_y_rechaza_lo_que_no_sirve():
    base = config_por_defecto(Ajustes())
    assert base == {"modelo": "claude-sonnet-5-5", "max_peligros": 6, "tiempo_maximo_s": 60.0,
                    "solo_escenas_preparadas": False}
    assert validar_config({}, base) == base
    assert validar_config({"max_peligros": 4, "solo_escenas_preparadas": True}, base) == {
        **base, "max_peligros": 4, "solo_escenas_preparadas": True}
    for mala in ({"modelo": "gpt-x"}, {"max_peligros": 0}, {"max_peligros": 13}, {"tiempo_maximo_s": 5},
                 {"otro_campo": 1}, {"solo_escenas_preparadas": "si"}, [], "texto"):
        with pytest.raises(ValueError):
            validar_config(mala, base)
    ajustes = ajustes_con_config(Ajustes(), validar_config({"modelo": "claude-opus-5-5", "tiempo_maximo_s": 45}, base))
    assert (ajustes.modelo, ajustes.tiempo_maximo_s, ajustes.max_peligros) == ("claude-opus-5-5", 45.0, 6)


def test_el_esquema_de_configuracion_del_contrato_coincide_con_lo_que_valida_el_modulo():
    esquema = json.loads((RAIZ_REPO / "contrato" / "config_inspector.schema.json").read_text(encoding="utf-8"))
    assert set(esquema["properties"]) == set(config_por_defecto(Ajustes()))
    assert esquema["additionalProperties"] is False


def test_solo_escenas_y_puerto_desde_el_entorno(monkeypatch):
    monkeypatch.setenv("INSPECTOR_SOLO_ESCENAS", "1")
    monkeypatch.setenv("INSPECTOR_PUERTO", "8123")
    assert config_por_defecto(Ajustes())["solo_escenas_preparadas"] is True
    assert puerto_del_servicio() == 8123
    monkeypatch.setenv("INSPECTOR_PUERTO", "ochenta")
    assert puerto_del_servicio() == 8010


def test_las_capacidades_listan_modelos_y_escenas(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-de-prueba")
    escena_en(tmp_path, "bodega")
    declaradas = capacidades(listar_escenas(tmp_path, solo_listas=True))
    assert [m["id"] for m in declaradas["modelos"]] == ["claude-sonnet-5-5", "claude-opus-5-5"]
    assert declaradas["escenas_preparadas"] == [{"id": "bodega", "nombre": "Bodega del stand"}]
    assert declaradas["ia_disponible"] is True and "sk-ant" not in json.dumps(declaradas)


# --------------------------------------------------------------------------- #
# Publicación del evento inspeccion_foto, con el receptor de prueba
# --------------------------------------------------------------------------- #
def eventos_de(receptor, inspeccion_id: str) -> list[dict]:
    """Eventos inspeccion_foto de una inspección que llegaron al receptor.

    Se filtra por inspección porque la cola de otra prueba (la que deja la plataforma
    apagada) puede entregar su evento pendiente al receptor de esta.
    """
    import httpx

    return [evento for evento in httpx.get(receptor.url + "/api/eventos").json()
            if evento["tipo"] == "inspeccion_foto" and evento["datos"].get("inspeccion_id") == inspeccion_id]


def test_de_punta_a_punta_foto_peligros_exposicion_excel_y_evento(servicio, entorno):
    import httpx

    entorno.encender()
    s = servicio(respuesta(), publicar_eventos=True)
    analizada = s.analizar(sesion_id="V-0157").json()
    valorada = s.valorar(analizada["inspeccion_id"]).json()

    assert valorada["publicado"] is True and valorada["evento_id"]
    assert esperar_envios(10)
    (evento,) = eventos_de(entorno, analizada["inspeccion_id"])
    validar_evento(evento)
    assert evento["id"] == valorada["evento_id"]
    assert (evento["estacion"], evento["severidad"], evento["sesion_id"]) == ("inspector", "critica", "V-0157")
    datos = evento["datos"]
    assert datos["inspeccion_id"] == analizada["inspeccion_id"]
    assert (datos["borrador"], datos["origen_analisis"], datos["modelo"]) == (True, "ia", "claude-sonnet-5-5")
    assert datos["peligros_descartados"] == 1
    assert datos["contexto"] == {"proceso": "Almacenamiento", "zona": "Bodega de producto terminado",
                                 "actividad": "Almacenamiento y despacho", "tarea": "Ubicar cajas en la estantería",
                                 "rutinaria": True}
    assert [p["nivel_preliminar"] for p in datos["peligros"]] == ["muy_alto", "alto", "alto", "medio", "bajo"]
    primero = datos["peligros"][0]
    assert primero["peligro"].startswith("Trabajador sobre escalera de tijera")
    assert primero["clasificacion"] == "condiciones_de_seguridad" and primero["subclasificacion"] == "trabajo en alturas"
    assert primero["valoracion"] == {"nd": 6, "ne": 3, "np": 18, "interpretacion_np": "Alto", "nc": 60, "nr": 1080,
                                     "nivel_riesgo": "I", "aceptabilidad": "No aceptable"}
    assert primero["controles_propuestos"][0] == primero["controles_por_jerarquia"]["eliminacion"][0]
    assert (primero["exposicion"], primero["expuestos"]) == ("frecuente", 2)
    assert datos["peligros"][4]["valoracion"]["nr"] is None  # deficiencia baja

    # Los dos archivos llegaron a la plataforma y son los del evento
    imagen, excel = evento["adjuntos"]
    assert (imagen["tipo"], excel["tipo"]) == ("imagen", "excel") and datos["url_excel"] == excel["ruta"]
    assert excel["ruta"].endswith(".xlsx") and imagen["ruta"].endswith(".jpg")
    foto = httpx.get(f"{entorno.url}/{imagen['ruta']}")
    libro = httpx.get(f"{entorno.url}/{excel['ruta']}")
    assert foto.status_code == libro.status_code == 200
    assert pixeles_de_color(decodificar(foto.content), AUREN_DEEP, 25) > 1000  # es la foto anotada
    assert load_workbook(io.BytesIO(libro.content)).active.cell(row=FILA_AVISO, column=1).value == AVISO_BORRADOR

    # Corregir y volver a generar no publica la inspección dos veces
    otra_vez = s.valorar(analizada["inspeccion_id"]).json()
    assert otra_vez["publicado"] is False and otra_vez["evento_id"] == valorada["evento_id"]
    assert esperar_envios(10)
    assert len(eventos_de(entorno, analizada["inspeccion_id"])) == 1


def test_sin_plataforma_la_persona_recibe_su_excel_y_el_evento_queda_en_cola(servicio, entorno):
    from modulos.comun import eventos_pendientes

    s = servicio(respuesta(), publicar_eventos=True)  # el receptor está apagado
    valorada = s.valorar(s.analizar().json()["inspeccion_id"]).json()
    assert valorada["publicado"] is True and s.http.get(valorada["url_excel"]).status_code == 200
    assert eventos_pendientes("inspector") == 1


def test_una_matriz_sin_peligros_tambien_publica_un_evento_valido(servicio, entorno):
    import httpx

    entorno.encender()
    s = servicio(respuesta(), publicar_eventos=True)
    inspeccion_id = s.analizar().json()["inspeccion_id"]
    s.valorar(inspeccion_id, {"peligros": [{"n": n, "descartado": True} for n in range(1, 7)]})
    assert esperar_envios(10)
    (evento,) = eventos_de(entorno, inspeccion_id)
    assert evento["severidad"] == "info" and evento["datos"]["peligros"] == []
    assert evento["datos"]["peligros_descartados"] == 6 and "sesion_id" not in evento


def test_los_datos_del_evento_omiten_lo_que_la_persona_no_lleno():
    from modulos.inspector.nucleo.matriz import valorar_peligros

    valorados = valorar_peligros(ANALISIS["peligros"][:1], [{"n": 1, "frecuencia": "continua"}])
    inspeccion = {"id": "abc123abc123", "origen": "escena_preparada", "modelo": None, "escena": None,
                  "analisis": ANALISIS}
    datos = datos_del_evento(inspeccion, valorados, 5, {"proceso": "  ", "rutinaria": None}, "media/x.xlsx")
    assert "contexto" not in datos and "modelo" not in datos and "expuestos" not in datos["peligros"][0]
    assert datos["escena"] == ANALISIS["descripcion_general"] and datos["origen_analisis"] == "escena_preparada"


# --------------------------------------------------------------------------- #
# Herramienta: precalcular escenas
# --------------------------------------------------------------------------- #
def test_precalcular_escenas_analiza_las_que_faltan_y_difumina_las_fotos_sueltas(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    escenas = tmp_path / "escenas"
    escena_en(escenas, "bodega")                        # ya tiene resultado
    escena_en(escenas, "taller", con_resultado=False)   # le falta
    (escenas / "Zona de Soldadura 2.jpg").write_bytes(FOTO)  # foto suelta, recién tomada
    reloj = Reloj()
    claude = ClienteSimulado(respuesta(), respuesta(), reloj=reloj)
    analizador = Analizador(Ajustes(), cliente=claude, dormir=reloj.dormir, reloj=reloj)

    codigo = precalcular_escenas.main(["--carpeta", str(escenas)], analizador=analizador)

    assert codigo == 0 and len(claude.solicitudes) == 2  # taller y la foto suelta; bodega no se repite
    assert not (escenas / "Zona de Soldadura 2.jpg").exists()  # el original sin difuminar no se queda
    nueva = leer_escena("zona_de_soldadura_2", escenas)
    assert nueva["nombre"] == "Zona de soldadura 2" and len(nueva["resultado"]["analisis"]["peligros"]) == 6
    assert leer_escena("taller", escenas)["resultado"]["modelo"] == "claude-sonnet-5-5"
    assert [e["id"] for e in listar_escenas(escenas, solo_listas=True)] == ["bodega", "taller", "zona_de_soldadura_2"]
    salida = capsys.readouterr().out
    assert "bodega: ya tiene resultado" in salida and "Escenas analizadas: 2" in salida

    # Con --forzar y --solo se repite una escena concreta
    claude.pendientes.append(respuesta())
    assert precalcular_escenas.main(["--carpeta", str(escenas), "--forzar", "--solo", "bodega"], analizador=analizador) == 0
    assert len(claude.solicitudes) == 3


def test_precalcular_escenas_avisa_si_una_falla(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    escenas = tmp_path / "escenas"
    escena_en(escenas, "taller", con_resultado=False)
    reloj = Reloj()
    claude = ClienteSimulado(respuesta(texto="", stop_reason="refusal"), reloj=reloj)
    codigo = precalcular_escenas.main(["--carpeta", str(escenas)],
                                      analizador=Analizador(Ajustes(), cliente=claude, dormir=reloj.dormir, reloj=reloj))
    assert codigo == 1 and "No pudimos analizar esta foto" in capsys.readouterr().out
    assert leer_escena("taller", escenas)["resultado"] is None
