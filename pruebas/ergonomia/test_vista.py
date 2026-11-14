"""Pruebas de la Fase 2 sin cámara ni MediaPipe: suavizado, configuración, análisis y pantalla."""

import json
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from modulos.ergonomia.config import RUTA_POR_DEFECTO, condiciones_desde, validar_config
from modulos.ergonomia.estacion import Analizador
from modulos.ergonomia.interfaz import marca
from modulos.ergonomia.interfaz.dibujo import dibujar_esqueleto, imagen_para_guardar
from modulos.ergonomia.interfaz.panel import EstadoPanel, Pantalla
from modulos.ergonomia.nucleo.angulos import Punto, elegir_lado
from modulos.ergonomia.nucleo.suavizado import FiltroOneEuro, SuavizadorPuntos
from modulos.ergonomia.pose.estimador import EstimadorPose

from .test_angulos import postura

ESQUEMA_CONFIG = Path(__file__).resolve().parents[2] / "contrato" / "config_ergonomia.schema.json"


# --------------------------------------------------------------------------- #
# Suavizado
# --------------------------------------------------------------------------- #
def test_one_euro_reduce_el_temblor_en_reposo():
    filtro = FiltroOneEuro()
    ruido = [100 + (3 if i % 2 else -3) for i in range(60)]
    salida = [filtro.filtrar(valor, i / 30) for i, valor in enumerate(ruido)]
    assert max(salida[30:]) - min(salida[30:]) < 2.0  # la entrada oscila 6 px


def test_one_euro_sigue_un_movimiento_rapido():
    filtro = FiltroOneEuro()
    salida = [filtro.filtrar(i * 20.0, i / 30) for i in range(60)]  # 600 px por segundo
    assert abs(salida[-1] - 59 * 20.0) < 40


def test_suavizador_conserva_visibilidad_y_se_reinicia():
    suavizador = SuavizadorPuntos()
    suavizador.filtrar({"nariz": Punto(0, 0, 0.9)}, 0.0)
    intermedio = suavizador.filtrar({"nariz": Punto(100, 100, 0.4)}, 1 / 30)["nariz"]
    assert 0 < intermedio.x < 100 and intermedio.visibilidad == 0.4
    suavizador.reiniciar()
    assert suavizador.filtrar({"nariz": Punto(100, 100, 0.4)}, 2 / 30)["nariz"].x == 100


def test_lado_con_histeresis_no_salta_por_poca_diferencia():
    puntos = {**postura(lado="izquierdo", vis=0.80), **postura(lado="derecho", vis=0.85)}
    assert elegir_lado(puntos) == "derecho"
    assert elegir_lado(puntos, actual="izquierdo", margen=0.15) == "izquierdo"
    puntos = {**postura(lado="izquierdo", vis=0.5), **postura(lado="derecho", vis=0.9)}
    assert elegir_lado(puntos, actual="izquierdo", margen=0.15) == "derecho"


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
def test_config_por_defecto_es_valida_y_cumple_el_esquema():
    por_defecto = json.loads(RUTA_POR_DEFECTO.read_text(encoding="utf-8"))
    assert validar_config({}) == por_defecto == validar_config(por_defecto)
    esquema = json.loads(ESQUEMA_CONFIG.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(esquema).iter_errors(por_defecto)) == []
    assert set(esquema["properties"]) == set(por_defecto)
    assert por_defecto["peso_carga_kg"] == 5 and por_defecto["modo_deteccion"] == "auto"


def test_config_parcial_conserva_el_resto_y_descarta_lo_desconocido():
    config = validar_config({"peso_carga_kg": 12, "actividad": {"repetitiva": True, "otra": 1}, "inventada": 3})
    assert config["peso_carga_kg"] == 12 and config["agarre"] == "bueno"
    assert config["actividad"] == {"estatica": False, "repetitiva": True, "cambios_rapidos": False}
    assert "inventada" not in config


@pytest.mark.parametrize("mala", [
    [], {"peso_carga_kg": -1}, {"peso_carga_kg": "5"}, {"peso_carga_kg": True}, {"agarre": "firme"},
    {"modo_deteccion": "magia"}, {"lado": "centro"}, {"golpe_o_fuerza_brusca": 1}, {"camara": -1},
    {"camara": ""}, {"actividad": []}, {"actividad": {"estatica": "si"}}, {"umbral_tronco_inclinado": 120},
])
def test_config_invalida_se_rechaza(mala):
    with pytest.raises(ValueError):
        validar_config(mala)


def test_condiciones_desde_la_config():
    c = condiciones_desde(validar_config({
        "peso_carga_kg": 12, "agarre": "malo", "golpe_o_fuerza_brusca": True,
        "actividad": {"cambios_rapidos": True}, "ajuste_brazo_inclinada": False, "umbral_tronco_inclinado": 30,
    }))
    assert (c.peso_carga_kg, c.agarre, c.golpe_o_fuerza_brusca) == (12, "malo", True)
    assert (c.actividad_estatica, c.actividad_repetitiva, c.actividad_cambios_rapidos) == (False, False, True)
    assert c.ajuste_brazo_inclinada is False and c.umbral_tronco_inclinado == 30
    assert not c.torsion_tronco and not c.brazo_abducido_o_rotado  # no medibles en 2D: no suman


# --------------------------------------------------------------------------- #
# Análisis con un estimador simulado
# --------------------------------------------------------------------------- #
class EstimadorFijo(EstimadorPose):
    def __init__(self, puntos):
        self.puntos = puntos

    def estimar(self, frame_bgr, marca_ms):
        return self.puntos


FRAME = np.zeros((720, 1280, 3), np.uint8)


def test_analizador_espalda_doblada_da_riesgo_alto():
    puntos = postura(tronco=75, cuello=25, rodilla=10, brazo=75, codo=10)
    analisis = Analizador(EstimadorFijo(puntos)).analizar(FRAME, 0, validar_config({}))
    assert analisis.hay_persona and analisis.angulos.lado == "derecho"
    r = analisis.resultado
    assert r.segmentos["tronco"] == 4 and r.ajustes_aplicados == ("brazo_persona_inclinada",)
    assert r.completo and r.puntaje >= 4


def test_analizador_aplica_la_configuracion_en_cada_fotograma():
    analizador = Analizador(EstimadorFijo(postura(tronco=40, rodilla=40, brazo=50, codo=70)))
    liviano = analizador.analizar(FRAME, 0, validar_config({"peso_carga_kg": 2}))
    pesado = analizador.analizar(FRAME, 33, validar_config({"peso_carga_kg": 15, "agarre": "malo"}))
    assert (liviano.resultado.carga, pesado.resultado.carga) == (0, 2)
    assert pesado.resultado.puntaje > liviano.resultado.puntaje


def test_analizador_respeta_el_lado_configurado():
    puntos = {**postura(lado="izquierdo", vis=0.9), **postura(lado="derecho", vis=0.6)}
    analizador = Analizador(EstimadorFijo(puntos))
    assert analizador.analizar(FRAME, 0, validar_config({})).angulos.lado == "izquierdo"
    assert analizador.analizar(FRAME, 33, validar_config({"lado": "derecho"})).angulos.lado == "derecho"


def test_analizador_sin_persona():
    analisis = Analizador(EstimadorFijo(None)).analizar(FRAME, 0, validar_config({}))
    assert not analisis.hay_persona and analisis.resultado is None


def test_segmento_poco_visible_no_se_puntua():
    puntos = postura(tronco=30)
    puntos["tobillo_derecho"] = puntos["tobillo_derecho"]._replace(visibilidad=0.1)
    r = Analizador(EstimadorFijo(puntos)).analizar(FRAME, 0, validar_config({})).resultado
    assert r.segmentos["piernas"] is None and r.puntaje is None


# --------------------------------------------------------------------------- #
# Dibujo y pantalla
# --------------------------------------------------------------------------- #
def test_color_de_segmento():
    assert marca.color_de_segmento(None) == marca.GRIS
    assert [marca.color_de_segmento(p) for p in (1, 2, 3, 4, 6)] == [
        marca.VERDE, marca.AMARILLO, marca.NARANJA, marca.ROJO, marca.ROJO]


def _hay_color(imagen: np.ndarray, color_rgb) -> bool:
    return bool((imagen == np.array(marca.bgr(color_rgb), np.uint8)).all(axis=2).any())


def test_esqueleto_usa_el_color_de_cada_segmento():
    frame = np.zeros((720, 1280, 3), np.uint8)
    segmentos = {"tronco": 4, "cuello": 1, "piernas": 2, "brazo": 3, "antebrazo": 1, "muneca": None}
    dibujar_esqueleto(frame, postura(tronco=30, rodilla=40, brazo=50, codo=70), "derecho", segmentos)
    for color in (marca.ROJO, marca.VERDE, marca.AMARILLO, marca.GRIS):
        assert _hay_color(frame, color)


def test_imagen_para_guardar_difumina_antes_de_dibujar(monkeypatch):
    from modulos.ergonomia.interfaz import dibujo

    orden = []
    monkeypatch.setattr(dibujo, "difuminar_rostros", lambda f: (orden.append("difuminar"), f.copy())[1])
    original = dibujo.dibujar_esqueleto
    monkeypatch.setattr(dibujo, "dibujar_esqueleto", lambda *a, **k: (orden.append("dibujar"), original(*a, **k))[1])
    frame = np.zeros((720, 1280, 3), np.uint8)
    salida = imagen_para_guardar(frame, postura(), "derecho", {"tronco": 1})
    assert orden == ["difuminar", "dibujar"]
    assert not frame.any() and salida.any()  # el original no se toca


def test_pantalla_compone_video_y_panel_con_la_marca():
    pantalla = Pantalla(1920, 1080)
    analisis = Analizador(EstimadorFijo(postura(tronco=70, rodilla=10, brazo=70, codo=10))).analizar(
        FRAME, 0, validar_config({}))
    estado = EstadoPanel(resultado=analisis.resultado, angulos=analisis.angulos, hay_persona=True,
                         config=validar_config({}), fuente="Video")
    lienzo = pantalla.componer(np.full((720, 1280, 3), 200, np.uint8), estado)
    assert lienzo.shape == (1080, 1920, 3)
    panel = lienzo[:, pantalla.ancho_video:]
    video = lienzo[:, :pantalla.ancho_video]
    assert tuple(panel[5, 5]) == marca.bgr(marca.DEEP)  # fondo Auren Deep
    assert tuple(video[5, 5]) == marca.bgr(marca.NEGRO)  # franja sobre el video
    assert tuple(video[540, 680]) == (200, 200, 200)  # el video, centrado
    lima = (panel == np.array(marca.bgr(marca.LIMA), np.uint8)).all(axis=2).mean()
    assert 0 < lima < 0.10  # la lima es solo acento


def test_pantalla_sin_imagen_muestra_el_aviso_de_camara():
    pantalla = Pantalla(1280, 720)
    normal = pantalla.componer(None, EstadoPanel(config=validar_config({})))
    aviso = pantalla.componer(None, EstadoPanel(config=validar_config({}), aviso="Cámara desconectada, reconectando…"))
    assert normal.shape == aviso.shape == (720, 1280, 3)
    assert _hay_color(aviso, marca.AMARILLO) and not _hay_color(normal, marca.AMARILLO)


def test_el_panel_solo_se_redibuja_si_cambia_lo_visible():
    pantalla = Pantalla(1280, 720)
    estado = EstadoPanel(config=validar_config({}), fps=29.6)
    primera = pantalla.panel.render(estado)
    assert pantalla.panel.render(EstadoPanel(config=validar_config({}), fps=30.2)) is primera
    assert pantalla.panel.render(EstadoPanel(config=validar_config({"peso_carga_kg": 9}))) is not primera


def test_el_frente_se_decide_por_mayoria_y_no_salta_con_un_fotograma_dudoso():
    de_pie = postura(tronco=5)
    agachado = postura(tronco=100)  # sin pie visible y con la cabeza colgando: señal invertida
    agachado["talon_derecho"] = agachado["talon_derecho"]._replace(visibilidad=0.0)
    oreja = agachado["oreja_derecho"]
    agachado["nariz"] = Punto(oreja.x - 40, oreja.y + 10)
    estimador = EstimadorFijo(de_pie)
    analizador = Analizador(estimador)
    for i in range(5):
        analizador.analizar(FRAME, i * 33, validar_config({}))
    estimador.puntos = agachado
    # El suavizado tarda unos fotogramas en llegar a la postura nueva
    for i in range(5, 40):
        analisis = analizador.analizar(FRAME, i * 33, validar_config({}))
        assert analisis.angulos.frente == 1 and analisis.angulos.tronco > 0
    assert analisis.angulos.tronco == pytest.approx(100, abs=2)
    assert analisis.resultado.segmentos["tronco"] == 4


def _region(imagen: np.ndarray, pantalla: Pantalla, desde: int, hasta: int) -> np.ndarray:
    """Franja horizontal del panel entre dos alturas del diseño base (1080 de alto)."""
    escala = pantalla.alto / 1080
    return imagen[round(desde * escala): round(hasta * escala)]


def _panel_de(pose: dict, pantalla: Pantalla, **estado):
    analisis = Analizador(EstimadorFijo(postura(**pose))).analizar(FRAME, 0, validar_config({}))
    datos = EstadoPanel(resultado=analisis.resultado, angulos=analisis.angulos, hay_persona=True,
                        config=validar_config({}), **estado)
    return pantalla.panel.render(datos), analisis


DOBLADA_ALTA = dict(tronco=98, cuello=-15, rodilla=35, brazo=97, codo=11)


def test_el_panel_muestra_la_tecnica_junto_al_reba_sin_cambiarlo():
    """Espalda doblada: el indicador de espalda sale en rojo. Sentadilla: en amarillo y las
    rodillas en verde, aunque el REBA de las piernas suba."""
    pantalla = Pantalla(1920, 1080)
    doblada, analisis_doblada = _panel_de(dict(tronco=98, rodilla=23, brazo=97, codo=11), pantalla)
    sentadilla, analisis_sentadilla = _panel_de(dict(tronco=40, cuello=5, rodilla=140, brazo=60, codo=10), pantalla)
    tecnica_doblada, tecnica_sentadilla = (_region(i, pantalla, 318, 386) for i in (doblada, sentadilla))
    assert _hay_color(tecnica_doblada, marca.ROJO) and not _hay_color(tecnica_doblada, marca.VERDE)
    assert _hay_color(tecnica_sentadilla, marca.AMARILLO) and _hay_color(tecnica_sentadilla, marca.VERDE)
    assert not _hay_color(tecnica_sentadilla, marca.ROJO)
    # El REBA sigue ahí, sin tocar: en la sentadilla las piernas puntúan 3
    assert analisis_sentadilla.resultado.segmentos["piernas"] == 3
    assert analisis_doblada.resultado.segmentos["tronco"] == 4


def test_el_distintivo_lleva_el_color_del_nivel_y_el_mensaje_va_en_marfil():
    pantalla = Pantalla(1920, 1080)
    panel, analisis = _panel_de(DOBLADA_ALTA, pantalla)
    assert analisis.resultado.nivel == "alto"
    distintivo = _region(panel, pantalla, 212, 252)
    assert _hay_color(distintivo, marca.NARANJA)  # el color del nivel queda en el distintivo
    mensaje = _region(panel, pantalla, 110, 206)[:, round(140 * pantalla.alto / 1080):]  # a la derecha del número
    assert _hay_color(mensaje, marca.MARFIL)
    for color in (marca.ROJO, marca.NARANJA, marca.AMARILLO):
        assert not _hay_color(mensaje, color)  # el mensaje no va en el color del riesgo
    # La línea fija sobre qué es REBA está siempre, también sin nadie en cuadro
    vacio = pantalla.panel.render(EstadoPanel(config=validar_config({})))
    assert _hay_color(_region(vacio, pantalla, 264, 302), marca.MARFIL_TENUE)
    assert _hay_color(_region(panel, pantalla, 264, 302), marca.MARFIL_TENUE)


def test_la_pista_va_despues_de_las_correcciones_y_si_no_cabe_mandan_las_correcciones():
    pantalla = Pantalla(1920, 1080)
    correccion = "Espalda doblada 98°. En el siguiente intento, flexiona las rodillas"
    pista = ("Desde el piso, incluso con buena técnica, el riesgo rara vez baja de medio. "
             "Lo que más lo reduce es elevar la carga.")

    def recuadro(**estado):
        panel, _ = _panel_de(DOBLADA_ALTA, pantalla, **estado)
        return _region(panel, pantalla, 854, 1004).copy()

    solo = recuadro(instruccion=correccion)
    con_pista = recuadro(instruccion=correccion, pista=pista)
    assert (solo != con_pista).any()  # la pista se dibuja
    # Con una pista demasiado larga para el recuadro, se muestran solo las correcciones
    con_pista_enorme = recuadro(instruccion=correccion, pista=pista * 4)
    assert (con_pista_enorme == solo).all()
    # Un aviso (cámara desconectada) tiene prioridad sobre todo
    aviso = recuadro(instruccion=correccion, pista=pista, aviso="Cámara desconectada, reconectando…")
    assert _hay_color(aviso, marca.AMARILLO) and (aviso != con_pista).any()


def test_el_resultado_de_un_intento_cambia_el_titulo_y_la_tecnica_mostrada():
    from modulos.ergonomia.nucleo.tecnica import Tecnica

    pantalla = Pantalla(1920, 1080)
    en_vivo, _ = _panel_de(DOBLADA_ALTA, pantalla)
    en_vivo = en_vivo.copy()
    resultado, _ = _panel_de(DOBLADA_ALTA, pantalla, titulo_reba="Resultado del intento 2", tecnica=Tecnica(40, 120))
    assert (_region(en_vivo, pantalla, 86, 114) != _region(resultado, pantalla, 86, 114)).any()  # el título
    tecnica = _region(resultado, pantalla, 318, 386)
    assert _hay_color(tecnica, marca.AMARILLO) and _hay_color(tecnica, marca.VERDE) and not _hay_color(tecnica, marca.ROJO)
