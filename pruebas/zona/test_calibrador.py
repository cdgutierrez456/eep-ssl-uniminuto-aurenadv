"""Calibrador: el camino local (teclas y mouse) y el remoto (pedido de la plataforma) hasta una zona guardada."""

import time

import cv2
import httpx
import numpy as np
import pytest

from modulos.zona.calibracion import referencia as modulo_referencia
from modulos.zona.calibracion.calibrador import TECLA_ENTER, TECLA_ESC, Calibrador
from modulos.zona.calibracion.cinta import SIN_CINTA
from modulos.zona.calibracion.herramienta import ALTO_BARRA, ALTO_PIE, componer
from modulos.zona.config import AlmacenConfig, zona_desde_config

from .escenas import crear_escena

SOLICITUD = "2026-11-14T10:02:11-05:00"


@pytest.fixture
def escena():
    return crear_escena()


@pytest.fixture
def local(tmp_path, monkeypatch):
    """Calibrador sin plataforma, con su cola en una carpeta temporal."""
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    almacen = AlmacenConfig(con_plataforma=False)
    yield Calibrador(almacen)
    almacen.detener()


@pytest.fixture
def remoto(entorno, monkeypatch):
    """Calibrador conectado al receptor de prueba (encendido), que hace de plataforma."""
    monkeypatch.setenv("CONFIG_INTERVALO_S", "0.2")
    entorno.encender()
    almacen = AlmacenConfig(con_plataforma=True)
    yield Calibrador(almacen), entorno
    almacen.detener()


def teclear(calibrador, texto, frame=None):
    for letra in texto:
        calibrador.tecla(ord(letra), frame, calibrador.almacen.valor)


def esperar(condicion, segundos=5.0):
    """Espera a que la configuración remota llegue al módulo (consulta cada 0,2 s en estas pruebas)."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.05)
    return False


def poner_config(receptor, config) -> httpx.Response:
    return httpx.put(receptor.url + "/api/modulos/zona/config", json=config, timeout=5)


def pedir_deteccion(receptor) -> None:
    """Lo que hace el botón "Detectar zona": lee la configuración, cambia un campo y la escribe completa.

    Un PUT reemplaza todo el documento, así que mandar solo ``solicitud_deteccion`` borraría la zona.
    El editor solo aparece cuando el módulo ya subió su configuración (el GET deja de dar 404).
    """
    assert esperar(lambda: httpx.get(receptor.url + "/api/modulos/zona/config", timeout=2).status_code == 200)
    assert poner_config(receptor, {**leer(receptor, "config"), "solicitud_deteccion": SOLICITUD}).status_code == 200


def leer(receptor, recurso):
    return httpx.get(f"{receptor.url}/api/modulos/zona/{recurso}", timeout=5).json()


# --------------------------------------------------------------- camino local
def test_detectar_editar_y_guardar_desde_la_estacion(local, escena):
    frame = escena.imagen
    assert local.estado(local.almacen.valor, 1280, 720).startswith("Sin zona todavía")

    assert local.tecla(ord("d"), frame, local.almacen.valor)        # D: detecta la cinta
    assert local.editando and local.editor.es_cuadrilatero
    assert "rectángulo" in local.mensaje
    assert local.almacen.valor["zona_peligro"] is None              # todavía es solo una propuesta

    # Corrige una esquina con el mouse: la agarra, la arrastra y la suelta
    x, y = local.editor.vertices[2]
    local.mouse(cv2.EVENT_LBUTTONDOWN, x + 3, y - 2)
    local.mouse(cv2.EVENT_MOUSEMOVE, x + 20, y + 10)
    local.mouse(cv2.EVENT_LBUTTONUP, x + 20, y + 10)
    assert local.editor.vertices[2] == (x + 20, y + 10)

    assert local.tecla(ord("g"), frame, local.almacen.valor)        # G: guarda
    config = local.almacen.valor
    assert not local.editando and local.mensaje == "Zona guardada y activa."
    assert len(config["zona_peligro"]) == 4
    assert config["zona_peligro"][2] == pytest.approx([(x + 20) / 1280, (y + 10) / 720], abs=1e-4)
    assert config["zona_propuesta"] is None and config["solicitud_deteccion"] is None
    assert "Mide en píxeles" in local.estado(config, 1280, 720)


def test_las_medidas_reales_se_teclean_y_la_zona_pasa_a_medir_en_metros(local, escena):
    teclear(local, "dg", escena.imagen)
    teclear(local, "m")
    assert "Ancho real" in local.ayuda()
    teclear(local, "1,5")
    local.tecla(TECLA_ENTER, None, local.almacen.valor)
    assert "Largo real" in local.ayuda()
    teclear(local, "1x.0")                                          # la x no es un número: se ignora
    local.tecla(TECLA_ENTER, None, local.almacen.valor)

    config = local.almacen.valor
    assert config["rectangulo_real"] == {"ancho_m": 1.5, "largo_m": 1.0}
    assert local.mensaje == "Medidas guardadas: 1,50 × 1,00 m."
    zona = zona_desde_config(config, 1280, 720)
    assert zona.en_metros
    assert "Mide en metros (1,50 × 1,00 m)" in local.estado(config, 1280, 720)
    # Con las medidas de la escena (1,5 × 1 m), la homografía recupera sus proporciones reales
    cerca_izquierda, cerca_derecha = escena.esquinas[0], escena.esquinas[1]
    assert np.hypot(*np.subtract(zona.homografia.aplicar(cerca_izquierda),
                                 zona.homografia.aplicar(cerca_derecha))) == pytest.approx(1.5, abs=0.03)


def test_dejar_las_medidas_vacias_las_quita(local, escena):
    teclear(local, "dg", escena.imagen)
    local.guardar_medidas(local.almacen.valor, 1.5, 1.0)
    teclear(local, "m")
    local.tecla(TECLA_ENTER, None, local.almacen.valor)             # Enter sin escribir nada
    assert local.almacen.valor["rectangulo_real"] is None
    assert "píxeles" in local.mensaje


def test_esc_cancela_la_pregunta_de_medidas_y_la_edicion_sin_cambiar_la_zona(local, escena):
    teclear(local, "dg", escena.imagen)
    guardada = local.almacen.valor["zona_peligro"]

    teclear(local, "m12")
    assert local.tecla(TECLA_ESC, None, local.almacen.valor)
    assert local.medidas_en_curso is None and local.almacen.valor["rectangulo_real"] is None

    teclear(local, "ec", escena.imagen)                             # E: edita; C: borra los vértices
    assert local.editando and local.editor.vertices == []
    assert local.tecla(TECLA_ESC, escena.imagen, local.almacen.valor)
    assert not local.editando
    assert local.almacen.valor["zona_peligro"] == guardada


def test_marcar_la_zona_a_mano_cuando_no_hay_cinta(local):
    frame = crear_escena(con_cinta=False, distractor=None).imagen
    teclear(local, "d", frame)
    assert not local.editando and local.mensaje == SIN_CINTA

    teclear(local, "e", frame)                                      # la marca a mano con cuatro clics
    for x, y in [(400, 250), (850, 250), (900, 480), (360, 480)]:
        local.mouse(cv2.EVENT_LBUTTONDOWN, x, y)
        local.mouse(cv2.EVENT_LBUTTONUP, x, y)
    local.mouse(cv2.EVENT_RBUTTONDOWN, 900, 480)                    # se arrepiente de uno y lo quita
    assert len(local.editor.vertices) == 3
    teclear(local, "g", frame)
    assert len(local.almacen.valor["zona_peligro"]) == 3


def test_no_se_guarda_una_zona_que_no_encierra_area(local, escena):
    teclear(local, "g", escena.imagen)                              # sin haber detectado ni editado
    assert "No hay nada que guardar" in local.mensaje
    teclear(local, "e", escena.imagen)
    local.mouse(cv2.EVENT_LBUTTONDOWN, 100, 100)
    local.mouse(cv2.EVENT_LBUTTONUP, 100, 100)
    assert not local.guardar(local.almacen.valor)
    assert "al menos tres vértices" in local.mensaje
    assert local.almacen.valor["zona_peligro"] is None


def test_las_teclas_que_no_son_de_calibracion_se_dejan_pasar(local, escena):
    assert not local.tecla(ord("q"), escena.imagen, local.almacen.valor)
    assert not local.tecla(TECLA_ESC, escena.imagen, local.almacen.valor)   # Esc fuera de la edición: salir
    assert not local.tecla(ord("c"), escena.imagen, local.almacen.valor)    # C solo borra dentro de la edición


def test_el_mouse_no_hace_nada_fuera_de_la_edicion(local, escena):
    local.mouse(cv2.EVENT_LBUTTONDOWN, 100, 100)
    assert local.editor is None


# ------------------------------------------------------- imagen de referencia
def test_la_imagen_de_referencia_se_difumina_antes_de_guardarse(local, escena, monkeypatch):
    vistos = []

    def difuminar_espia(frame):
        vistos.append(frame)
        return np.zeros_like(frame)     # lo que devuelva el difuminado es lo único que puede llegar al disco

    monkeypatch.setattr(modulo_referencia, "difuminar_rostros", difuminar_espia)
    referencia = local.tomar_referencia(escena.imagen)

    assert vistos and vistos[0] is escena.imagen
    assert referencia.ruta is None and referencia.para_capacidades() is None     # sin plataforma no se sube
    assert (referencia.ancho, referencia.alto) == (1280, 720)
    assert referencia.timestamp.endswith("-05:00")
    guardada = cv2.imdecode(np.fromfile(str(referencia.ruta_local), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert guardada.shape == escena.imagen.shape and int(guardada.max()) == 0


def test_en_el_equipo_solo_queda_la_imagen_de_referencia_mas_reciente(local, escena):
    primera = local.tomar_referencia(escena.imagen)
    segunda = local.tomar_referencia(escena.imagen)
    assert primera.ruta_local == segunda.ruta_local
    assert [archivo.name for archivo in segunda.ruta_local.parent.iterdir()] == ["referencia.jpg"]


# -------------------------------------------------------------- camino remoto
def test_al_arrancar_el_modulo_sube_la_imagen_de_referencia_y_la_reporta_en_sus_capacidades(remoto, escena):
    calibrador, receptor = remoto
    referencia = calibrador.tomar_referencia(escena.imagen)

    assert referencia.ruta.startswith("media/")
    capacidades = leer(receptor, "capacidades")
    assert capacidades["imagen_referencia"] == {"ruta": referencia.ruta, "ancho": 1280, "alto": 720,
                                                "timestamp": referencia.timestamp}
    assert [zona["id"] for zona in capacidades["zonas"]] == ["piso"]
    assert httpx.get(f"{receptor.url}/{referencia.ruta}", timeout=5).status_code == 200   # la plataforma la sirve


def test_pedido_remoto_de_deteccion_propuesta_y_confirmacion(remoto, escena):
    calibrador, receptor = remoto
    frame = escena.imagen
    assert not calibrador.atender(frame, calibrador.almacen.valor)      # sin pedido no hace nada

    # El operador pulsa "Detectar zona": la plataforma escribe solicitud_deteccion
    pedir_deteccion(receptor)
    assert esperar(lambda: calibrador.almacen.valor["solicitud_deteccion"] == SOLICITUD)
    assert calibrador.atender(frame, calibrador.almacen.valor)

    # El módulo respondió en zona_propuesta, con una imagen de referencia nueva; la zona aún no está activa
    en_plataforma = leer(receptor, "config")
    propuesta = en_plataforma["zona_propuesta"]
    assert propuesta["solicitud"] == SOLICITUD and propuesta["es_cuadrilatero"] is True
    assert len(propuesta["poligono"]) == 4 and "rectángulo" in propuesta["mensaje"]
    assert propuesta["imagen_referencia"] == leer(receptor, "capacidades")["imagen_referencia"]["ruta"]
    assert en_plataforma["zona_peligro"] is None
    assert zona_desde_config(calibrador.almacen.valor, 1280, 720) is None

    # El mismo pedido no se atiende dos veces
    assert not calibrador.atender(frame, calibrador.almacen.valor)
    assert esperar(lambda: (calibrador.almacen.valor["zona_propuesta"] or {}).get("solicitud") == SOLICITUD)
    assert not Calibrador(calibrador.almacen).atender(frame, calibrador.almacen.valor)   # ni tras reiniciar

    # La persona confirma en el editor: la plataforma guarda zona_peligro y limpia la propuesta
    confirmada = {**en_plataforma, "zona_peligro": propuesta["poligono"], "zona_propuesta": None,
                  "solicitud_deteccion": None, "rectangulo_real": {"ancho_m": 1.5, "largo_m": 1.0},
                  "imagen_referencia": propuesta["imagen_referencia"]}
    assert poner_config(receptor, confirmada).status_code == 200
    assert esperar(lambda: calibrador.almacen.valor["zona_peligro"] is not None)
    zona = zona_desde_config(calibrador.almacen.valor, 1280, 720)
    assert zona.en_metros and len(zona.poligono) == 4
    assert not calibrador.atender(frame, calibrador.almacen.valor)


def test_si_no_encuentra_la_cinta_la_propuesta_lo_dice(remoto):
    calibrador, receptor = remoto
    frame = crear_escena(con_cinta=False, distractor=None).imagen
    pedir_deteccion(receptor)
    assert esperar(lambda: calibrador.almacen.valor["solicitud_deteccion"] == SOLICITUD)
    assert calibrador.atender(frame, calibrador.almacen.valor)

    propuesta = leer(receptor, "config")["zona_propuesta"]
    assert propuesta["poligono"] is None and propuesta["es_cuadrilatero"] is False
    assert propuesta["mensaje"] == SIN_CINTA and propuesta["solicitud"] == SOLICITUD


def test_guardar_desde_la_estacion_sube_la_zona_a_la_plataforma(remoto, escena):
    calibrador, receptor = remoto
    calibrador.tomar_referencia(escena.imagen)
    teclear(calibrador, "dg", escena.imagen)

    en_plataforma = leer(receptor, "config")
    assert len(en_plataforma["zona_peligro"]) == 4
    assert en_plataforma["imagen_referencia"] == calibrador.referencia.ruta
    assert calibrador.mensaje == "Zona guardada y activa."


def test_la_plataforma_rechaza_una_zona_que_no_cumple_el_esquema(remoto):
    _, receptor = remoto
    respuesta = poner_config(receptor, {"zona_peligro": [[0.1, 0.1], [0.5, 0.5]]})
    assert respuesta.status_code == 422


def test_sin_respuesta_de_la_plataforma_la_zona_queda_en_la_estacion(entorno, escena, monkeypatch):
    monkeypatch.setenv("CONFIG_INTERVALO_S", "0.2")
    almacen = AlmacenConfig(con_plataforma=True)        # el receptor está apagado
    try:
        calibrador = Calibrador(almacen)
        referencia = calibrador.tomar_referencia(escena.imagen)
        assert referencia.ruta is None and referencia.ruta_local.is_file()   # no llegó, pero quedó en el equipo
        teclear(calibrador, "dg", escena.imagen)
        assert len(almacen.valor["zona_peligro"]) == 4
        assert "se subirá a la plataforma" in calibrador.mensaje

        entorno.encender()                              # la plataforma vuelve: la zona sube sola
        assert esperar(lambda: httpx.get(entorno.url + "/api/modulos/zona/config", timeout=2).status_code == 200)
        assert esperar(lambda: leer(entorno, "config").get("zona_peligro") is not None)
    finally:
        almacen.detener()


# ----------------------------------------------------------------------- vista
def test_la_pantalla_de_calibracion_se_compone_con_o_sin_imagen(local, escena):
    config = local.almacen.valor
    vista = escena.imagen.copy()
    teclear(local, "d", escena.imagen)
    local.dibujar(vista, config)
    assert not np.array_equal(vista, escena.imagen)                 # dibujó el editor encima
    pantalla = componer(vista, local, config, "Imagen")
    assert pantalla.shape == (ALTO_BARRA + 720 + ALTO_PIE, 1280, 3)
    sin_camara = componer(None, local, config, "Cámara 1", aviso="Cámara desconectada, reconectando…")
    assert sin_camara.shape == (ALTO_BARRA + 720 + ALTO_PIE, 1280, 3)
