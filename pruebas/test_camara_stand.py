"""Pruebas de la cámara del stand, con una cámara simulada (sin hardware)."""

import cv2
import numpy as np
import pytest

from modulos.comun import camara_stand
from modulos.comun.camara_stand import MENSAJE_DESCONECTADA, ConfigCamara, conectar_camara


class CapturaFalsa:
    """Imita cv2.VideoCapture. ``disponibles`` dice qué índices existen en cada momento."""

    disponibles: set[int] = set()
    no_soportadas: set[int] = set()
    abiertas: list["CapturaFalsa"] = []

    def __init__(self, indice, backend=None):
        self.indice = indice
        self.abierta = indice in self.disponibles
        self.propiedades: dict[int, float] = {}
        self.orden: list[int] = []
        self.liberada = False
        CapturaFalsa.abiertas.append(self)

    def isOpened(self):
        return self.abierta

    def set(self, propiedad, valor):
        if propiedad in self.no_soportadas:
            return False
        self.propiedades[propiedad] = valor
        self.orden.append(propiedad)
        return True

    def get(self, propiedad):
        return 30.0 if propiedad == cv2.CAP_PROP_FPS else self.propiedades.get(propiedad, 0.0)

    def read(self):
        if not self.abierta or self.indice not in self.disponibles:
            return False, None
        ancho = int(self.propiedades.get(cv2.CAP_PROP_FRAME_WIDTH, 640))
        alto = int(self.propiedades.get(cv2.CAP_PROP_FRAME_HEIGHT, 480))
        return True, np.zeros((alto, ancho, 3), np.uint8)

    def release(self):
        self.liberada = True
        self.abierta = False


@pytest.fixture
def camaras(monkeypatch):
    CapturaFalsa.disponibles = {1}
    CapturaFalsa.no_soportadas = set()
    CapturaFalsa.abiertas = []
    monkeypatch.setattr(camara_stand.cv2, "VideoCapture", CapturaFalsa)
    return CapturaFalsa


def test_abre_con_los_valores_por_defecto_del_stand(camaras):
    camara = conectar_camara(ConfigCamara(indice=1))
    assert camara.conectada and camara.mensaje is None
    assert camara.indice == 1 and camara.resolucion == (1280, 720)
    p = camaras.abiertas[-1].propiedades
    assert p[cv2.CAP_PROP_FOURCC] == cv2.VideoWriter_fourcc(*"MJPG")
    assert p[cv2.CAP_PROP_FPS] == 30
    assert p[cv2.CAP_PROP_AUTOFOCUS] == 0 and p[cv2.CAP_PROP_FOCUS] == 0
    assert cv2.CAP_PROP_EXPOSURE not in p  # exposición automática si no se configura
    assert camara.leer().shape == (720, 1280, 3)


def test_exposicion_fija_desde_configuracion(camaras):
    conectar_camara(ConfigCamara(indice=1, exposicion=-6))
    assert camaras.abiertas[-1].propiedades[cv2.CAP_PROP_EXPOSURE] == -6


def test_propiedad_no_soportada_se_informa_y_sigue(camaras, caplog):
    camaras.no_soportadas = {cv2.CAP_PROP_AUTOFOCUS, cv2.CAP_PROP_FOCUS}
    with caplog.at_level("INFO"):
        camara = conectar_camara(ConfigCamara(indice=1))
    assert camara.conectada and camara.leer() is not None
    assert "no soporta 'autofoco apagado'" in caplog.text


def test_camara_ausente_no_lanza_y_queda_reintentando(camaras):
    camara = conectar_camara(ConfigCamara(indice=3, reintento_s=0))
    assert not camara.conectada and camara.mensaje == MENSAJE_DESCONECTADA
    assert camara.leer() is None
    camaras.disponibles = {3}  # la conectan
    assert camara.leer() is not None and camara.conectada


def test_desconexion_y_reconexion_sin_cerrar_el_programa(camaras, caplog):
    camara = conectar_camara(ConfigCamara(indice=1, reintento_s=0))
    assert camara.leer() is not None
    camaras.disponibles = set()  # la desconectan
    lecturas = [camara.leer() for _ in range(camara_stand.FALLOS_PARA_DESCONECTAR)]
    assert all(lectura is None for lectura in lecturas)
    assert not camara.conectada and camara.mensaje == MENSAJE_DESCONECTADA
    assert MENSAJE_DESCONECTADA in caplog.text
    assert camara.leer() is None  # sigue desconectada: reintenta y no lanza
    camaras.disponibles = {1}  # vuelve
    assert camara.leer() is not None
    assert camara.conectada and camara.mensaje is None


def test_un_fallo_suelto_no_la_da_por_desconectada(camaras):
    camara = conectar_camara(ConfigCamara(indice=1))
    camaras.disponibles = set()
    assert camara.leer() is None
    camaras.disponibles = {1}
    assert camara.leer() is not None and camara.conectada


def test_respeta_el_tiempo_entre_reintentos(camaras):
    camara = conectar_camara(ConfigCamara(indice=3, reintento_s=60))
    intentos = len(camaras.abiertas)
    camaras.disponibles = {3}
    assert camara.leer() is None  # aún no toca reintentar
    assert len(camaras.abiertas) == intentos


def test_seleccion_por_nombre(camaras, monkeypatch):
    monkeypatch.setattr(camara_stand, "nombres_de_camaras", lambda: ["Integrated Camera", "Logitech C920"])
    camara = conectar_camara(ConfigCamara(nombre="logitech"))
    assert camara.conectada and camara.indice == 1


def test_nombre_repetido_usa_la_primera_y_avisa(camaras, monkeypatch, caplog):
    monkeypatch.setattr(camara_stand, "nombres_de_camaras", lambda: ["Integrada", "Logitech C920", "Logitech C920"])
    camara = conectar_camara(ConfigCamara(nombre="Logitech C920"))
    assert camara.indice == 1
    assert "elige por índice" in caplog.text


def test_nombre_no_encontrado_cae_al_indice(camaras, monkeypatch):
    monkeypatch.setattr(camara_stand, "nombres_de_camaras", lambda: [])
    camara = conectar_camara(ConfigCamara(indice=1, nombre="Logitech"))
    assert camara.conectada and camara.indice == 1


def test_config_desde_entorno(monkeypatch):
    for nombre, valor in {"PRUEBA_CAMARA": "2", "PRUEBA_CAMARA_ANCHO": "1920", "PRUEBA_CAMARA_ALTO": "1080",
                          "PRUEBA_CAMARA_FPS": "15", "PRUEBA_CAMARA_AUTOFOCO": "1",
                          "PRUEBA_CAMARA_EXPOSICION": "-5", "PRUEBA_CAMARA_ENFOQUE": ""}.items():
        monkeypatch.setenv(nombre, valor)
    config = ConfigCamara.desde_entorno("PRUEBA")
    assert (config.indice, config.nombre) == (2, None)
    assert (config.ancho, config.alto, config.fps) == (1920, 1080, 15)
    assert config.autofoco is True and config.exposicion == -5 and config.enfoque == 0.0


def test_config_desde_entorno_sin_variables_usa_los_valores_del_stand(monkeypatch):
    for sufijo in ("", "_ANCHO", "_ALTO", "_FPS", "_AUTOFOCO", "_ENFOQUE", "_EXPOSICION"):
        monkeypatch.delenv(f"VACIO_CAMARA{sufijo}", raising=False)
    assert ConfigCamara.desde_entorno("VACIO") == ConfigCamara()
    assert ConfigCamara() == ConfigCamara(indice=0, ancho=1280, alto=720, fps=30, formato="MJPG", autofoco=False)


def test_camara_por_nombre_desde_entorno_y_con_camara(monkeypatch):
    monkeypatch.setenv("OTRA_CAMARA", "Logitech BRIO")
    assert ConfigCamara.desde_entorno("OTRA").nombre == "Logitech BRIO"
    base = ConfigCamara(indice=1)
    assert base.con_camara(None) == base and base.con_camara("  ") == base
    assert base.con_camara(2).indice == 2 and base.con_camara("3").indice == 3
    assert base.con_camara("C920").nombre == "C920"


def test_el_formato_se_pide_despues_de_los_fps(camaras):
    """Medido con una Logitech: fijar los fps después de MJPG la devuelve a YUY2 (10 fps en 720p)."""
    conectar_camara(ConfigCamara(indice=1))
    orden = camaras.abiertas[-1].orden
    assert orden.index(cv2.CAP_PROP_FOURCC) > orden.index(cv2.CAP_PROP_FPS)
    assert orden.index(cv2.CAP_PROP_FOURCC) > orden.index(cv2.CAP_PROP_FRAME_HEIGHT)
