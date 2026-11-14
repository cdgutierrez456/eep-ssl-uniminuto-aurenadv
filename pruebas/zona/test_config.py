"""Configuración de la zona: validación, valores por defecto, esquema del contrato y almacén local."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from modulos.zona.config import AjustesLocales, AlmacenConfig, parametros_desde, validar_config, zona_desde_config
from modulos.zona.config.ajustes import RUTA_POR_DEFECTO

RUTA_ESQUEMA = Path(__file__).resolve().parents[2] / "contrato" / "config_zona.schema.json"
CUADRADO = [[0.3, 0.4], [0.7, 0.4], [0.7, 0.8], [0.3, 0.8]]
COMPLETA = {
    "zona_peligro": CUADRADO,
    "rectangulo_real": {"ancho_m": 1.5, "largo_m": 1.0},
    "margen_advertencia_m": 0.6,
    "margen_advertencia_px": 90,
    "imagen_referencia": "media/2026-11-14/ab12cd34.jpg",
    "solicitud_deteccion": "2026-11-14T10:02:11-05:00",
    "zona_propuesta": {"solicitud": "2026-11-14T10:02:11-05:00", "poligono": CUADRADO, "es_cuadrilatero": True,
                       "mensaje": "Se encontró el rectángulo de cinta.", "imagen_referencia": "media/2026-11-14/ef56.jpg"},
    "deteccion": {"confianza_persona": 0.5, "antirrebote_s": 0.2, "segundos_perdida_peligro": 6},
    "cinta_hsv": {"h_min": 15, "h_max": 40},
    "sonido_local": True,
}


@pytest.fixture(scope="module")
def esquema() -> Draft202012Validator:
    contenido = json.loads(RUTA_ESQUEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(contenido)
    return Draft202012Validator(contenido)


# ------------------------------------------------------------------ por defecto
def test_la_configuracion_vacia_da_los_valores_por_defecto():
    config = validar_config({})
    assert config == json.loads(RUTA_POR_DEFECTO.read_text(encoding="utf-8"))
    assert config["zona_peligro"] is None                       # sin zona no se vigila nada
    assert config["margen_advertencia_m"] == 0.5
    assert config["sonido_local"] is False
    assert config["deteccion"]["antirrebote_s"] == 0.3
    assert config["deteccion"]["segundos_perdida_peligro"] == 4.0


def test_lo_que_el_modulo_aplica_y_sube_cumple_el_esquema_del_contrato(esquema):
    for candidata in ({}, COMPLETA, {"zona_peligro": CUADRADO}, {"zona_propuesta": {"poligono": None, "mensaje": "No"}}):
        errores = [error.message for error in esquema.iter_errors(validar_config(candidata))]
        assert errores == []


def test_en_una_configuracion_parcial_lo_que_falta_vuelve_a_su_valor_por_defecto(esquema):
    # Es válida, pero no es una mezcla: quien escribe debe mandar el documento completo o pierde lo demás
    parcial = {"solicitud_deteccion": "2026-11-14T10:02:11-05:00"}
    assert list(esquema.iter_errors(parcial)) == []
    config = validar_config(parcial)
    assert config["solicitud_deteccion"] == parcial["solicitud_deteccion"]
    assert config["margen_advertencia_px"] == 80 and config["zona_peligro"] is None


def test_una_configuracion_completa_se_conserva():
    config = validar_config(COMPLETA)
    assert config["zona_peligro"] == CUADRADO
    assert config["rectangulo_real"] == {"ancho_m": 1.5, "largo_m": 1.0}
    assert config["zona_propuesta"] == COMPLETA["zona_propuesta"]
    assert config["sonido_local"] is True
    # Los grupos se mezclan con sus valores por defecto
    assert config["deteccion"] == {"confianza_persona": 0.5, "confianza_punto": 0.5, "antirrebote_s": 0.2,
                                   "histeresis": 0.2, "segundos_perdida": 1.0, "segundos_perdida_peligro": 6,
                                   "radio_reasociacion_m": 0.5, "radio_reasociacion_px": 80}
    assert config["cinta_hsv"] == {"h_min": 15, "h_max": 40, "s_min": 80, "v_min": 80}


def test_las_claves_desconocidas_se_descartan():
    config = validar_config({"zona_peligro": CUADRADO, "color_favorito": "lima", "deteccion": {"otra": 1},
                             "zona_mano": {"habilitada": True}})   # la zona de mano no se implementó
    assert "color_favorito" not in config and "otra" not in config["deteccion"] and "zona_mano" not in config


def test_los_vertices_se_recortan_a_la_imagen_y_se_redondean():
    config = validar_config({"zona_peligro": [[-0.2, 0.1], [1.4, 0.123456789], [0.5, 2.0]]})
    assert config["zona_peligro"] == [[0.0, 0.1], [1.0, 0.12346], [0.5, 1.0]]


def test_la_propuesta_sin_cinta_lleva_poligono_nulo():
    config = validar_config({"zona_propuesta": {"solicitud": "s1", "poligono": None, "mensaje": "No se encontró"}})
    assert config["zona_propuesta"] == {"solicitud": "s1", "poligono": None, "es_cuadrilatero": False,
                                        "mensaje": "No se encontró", "imagen_referencia": None}


def test_es_cuadrilatero_lo_calcula_el_modulo():
    triangulo = [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]]
    config = validar_config({"zona_propuesta": {"poligono": triangulo, "es_cuadrilatero": True, "mensaje": ""}})
    assert config["zona_propuesta"]["es_cuadrilatero"] is False


# -------------------------------------------------------------------- rechazos
@pytest.mark.parametrize("candidata", [
    "no soy un objeto",
    {"zona_peligro": [[0.1, 0.1], [0.5, 0.5]]},                             # dos vértices
    {"zona_peligro": [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]},                 # alineados
    {"zona_peligro": [[0.1, 0.1], [0.9, 0.1], ["x", 0.9]]},                 # vértice que no es número
    {"zona_peligro": [[0.1, 0.1, 0.3], [0.9, 0.1], [0.5, 0.9]]},            # vértice de tres coordenadas
    {"zona_peligro": "todo el piso"},
    {"rectangulo_real": {"ancho_m": 1.5}},                                  # falta el largo
    {"rectangulo_real": {"ancho_m": 1.5, "largo_m": 0}},
    {"rectangulo_real": {"ancho_m": -1, "largo_m": 1}},
    {"rectangulo_real": [1.5, 1.0]},
    {"margen_advertencia_m": -0.1},
    {"margen_advertencia_m": "medio metro"},
    {"margen_advertencia_px": 5000},
    {"imagen_referencia": 42},
    {"solicitud_deteccion": ""},
    {"zona_propuesta": "una zona"},
    {"zona_propuesta": {"poligono": [[0.1, 0.1], [0.2, 0.2]], "mensaje": ""}},
    {"deteccion": {"confianza_persona": 1.5}},
    {"deteccion": {"antirrebote_s": -1}},
    {"deteccion": {"segundos_perdida_peligro": True}},
    {"deteccion": "rápida"},
    {"cinta_hsv": {"h_min": 200}},
    {"cinta_hsv": {"h_min": 40, "h_max": 20}},
    {"cinta_hsv": {"s_min": 80.5}},
    {"sonido_local": "si"},
])
def test_una_configuracion_invalida_se_rechaza_entera(candidata):
    with pytest.raises(ValueError):
        validar_config(candidata)


def test_el_esquema_rechaza_lo_mismo_que_el_modulo(esquema):
    for invalida in ({"zona_peligro": [[0.1, 0.1], [0.5, 0.5]]}, {"zona_peligro": [[0.1, 0.1], [1.5, 0.1], [0.5, 0.9]]},
                     {"rectangulo_real": {"ancho_m": 1.5}}, {"sonido_local": "si"}, {"clave_nueva": 1},
                     {"cinta_hsv": {"h_min": 200}}, {"deteccion": {"histeresis": 2}}):
        assert list(esquema.iter_errors(invalida)) != []


# ------------------------------------------------------- de la config al núcleo
def test_sin_zona_marcada_no_hay_nada_que_vigilar():
    assert zona_desde_config(validar_config({}), 1280, 720) is None


def test_zona_en_pixeles_desde_la_configuracion():
    config = validar_config({"zona_peligro": CUADRADO, "margen_advertencia_px": 90, "deteccion": {"histeresis": 0.3}})
    zona = zona_desde_config(config, 1280, 720)
    assert zona.zona_id == "piso" and not zona.en_metros
    assert zona.margen == 90 and zona.histeresis == 0.3
    assert zona.poligono[0] == pytest.approx((384.0, 288.0))


def test_zona_en_metros_desde_la_configuracion():
    zona = zona_desde_config(validar_config(COMPLETA), 1280, 720)
    assert zona.en_metros and zona.margen == 0.6
    # El lado 1-2 mide ancho_m y el lado 2-3 mide largo_m
    assert zona.homografia.aplicar(zona.poligono[1]) == pytest.approx((1.5, 0.0), abs=1e-6)
    assert zona.homografia.aplicar(zona.poligono[2]) == pytest.approx((1.5, 1.0), abs=1e-6)


def test_parametros_de_la_maquina_de_estados_desde_la_configuracion():
    parametros = parametros_desde(validar_config(COMPLETA))
    assert (parametros.antirrebote_s, parametros.segundos_perdida, parametros.segundos_perdida_peligro) == (0.2, 1.0, 6.0)
    assert (parametros.radio_reasociacion_m, parametros.radio_reasociacion_px) == (0.5, 80.0)
    assert parametros.intervalo_refresco_s == 2.0   # el refresco no es configurable: la plataforma cuenta con él
    cambiado = parametros_desde(validar_config({"deteccion": {"radio_reasociacion_m": 0.8, "radio_reasociacion_px": 120}}))
    assert (cambiado.radio_reasociacion_m, cambiado.radio_reasociacion_px) == (0.8, 120.0)


# ----------------------------------------------------------------- ajustes .env
def test_ajustes_locales_desde_el_entorno(monkeypatch):
    monkeypatch.setenv("ZONA_CAMARA", "2")
    monkeypatch.setenv("ZONA_CAMARA_ANCHO", "1920")
    monkeypatch.setenv("ZONA_PANTALLA_COMPLETA", "0")
    monkeypatch.setenv("ZONA_PANTALLA_ANCHO", "no es un número")
    ajustes = AjustesLocales.desde_entorno()
    assert ajustes.camara.indice == 2 and ajustes.camara.ancho == 1920 and ajustes.camara.formato == "MJPG"
    assert ajustes.pantalla_completa is False
    assert ajustes.ancho_pantalla == 1920 and ajustes.alto_pantalla == 1080


# ------------------------------------------------------------ almacén sin plataforma
def test_sin_plataforma_la_zona_se_guarda_en_el_equipo_y_sobrevive_al_reinicio(tmp_path, monkeypatch):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    almacen = AlmacenConfig(con_plataforma=False)
    assert almacen.fuente == "local" and almacen.valor["zona_peligro"] is None

    assert almacen.actualizar({**almacen.valor, "zona_peligro": CUADRADO, "color_favorito": "lima"})
    assert almacen.valor["zona_peligro"] == CUADRADO and "color_favorito" not in almacen.valor
    assert (tmp_path / "cola" / "config" / "zona.json").is_file()

    otro = AlmacenConfig(con_plataforma=False)      # la estación se cierra y vuelve a abrir
    assert otro.valor["zona_peligro"] == CUADRADO
    almacen.detener()
    otro.detener()


def test_el_almacen_local_rechaza_una_configuracion_invalida_y_conserva_la_anterior(tmp_path, monkeypatch):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    almacen = AlmacenConfig(con_plataforma=False)
    almacen.actualizar({"zona_peligro": CUADRADO})
    with pytest.raises(ValueError):
        almacen.actualizar({"zona_peligro": [[0.1, 0.1], [0.2, 0.2]]})
    assert almacen.valor["zona_peligro"] == CUADRADO


def test_un_archivo_local_danado_no_impide_arrancar(tmp_path, monkeypatch):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    carpeta = tmp_path / "cola" / "config"
    carpeta.mkdir(parents=True)
    (carpeta / "zona.json").write_text("{ esto no es json", encoding="utf-8")
    assert AlmacenConfig(con_plataforma=False).valor == validar_config({})
