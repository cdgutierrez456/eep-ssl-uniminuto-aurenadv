"""La estación de zona de punta a punta, con un detector simulado y un video sintético contra el receptor de prueba."""

import json

import httpx
import numpy as np
import pytest

from modulos.zona import estacion as modulo_estacion
from modulos.zona.config import AjustesLocales, validar_config
from modulos.zona.deteccion import pose as modulo_pose
from modulos.zona.estacion import Estacion, analizar_argumentos

from .utilidades import ALTO, ANCHO, FPS, DetectorSimulado, ausente, escribir_video, quieto, tramo

# Zona de (200, 150) a (400, 300) en un video de 640 x 360
ZONA = [[200 / ANCHO, 150 / ALTO], [400 / ANCHO, 150 / ALTO], [400 / ANCHO, 300 / ALTO], [200 / ANCHO, 300 / ALTO]]
LEJOS, DENTRO = (40.0, 225.0), (300.0, 225.0)
LEJOS_DERECHA, CERCA_DERECHA = (600.0, 225.0), (440.0, 225.0)


def sembrar_config(tmp_path, **cambios) -> dict:
    """Deja la configuración de la zona en la caché del equipo: la estación arranca ya con ella."""
    config = validar_config({"zona_peligro": ZONA, "margen_advertencia_px": 60, **cambios})
    carpeta = tmp_path / "cola" / "config"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "zona.json").write_text(json.dumps(config), encoding="utf-8")
    return config


def estacion_de_prueba(tmp_path, recorridos, *extra) -> tuple[Estacion, DetectorSimulado]:
    cuadros = max(len(recorrido) for recorrido in recorridos.values())
    video = escribir_video(tmp_path / "video.mp4", cuadros)
    detector = DetectorSimulado(recorridos)
    opciones = analizar_argumentos(["--video", str(video), "--sin-ventana", *extra])
    return Estacion(opciones, AjustesLocales.desde_entorno(), detector), detector


def eventos_de_zona(receptor) -> list[dict]:
    return httpx.get(receptor.url + "/api/eventos", params={"estacion": "zona", "limite": 1000}, timeout=5).json()


def test_la_estacion_publica_estados_ingreso_con_foto_y_casi_accidente(entorno, tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_INTERVALO_S", "0.2")
    entorno.encender()
    sembrar_config(tmp_path)
    # La 1 entra a la zona, se queda 6 s y sale. La 2 se acerca por el otro lado y se va sin entrar.
    persona_1 = quieto(LEJOS, 0.5) + tramo(LEJOS, DENTRO, 1) + quieto(DENTRO, 6) + tramo(DENTRO, LEJOS, 1) + quieto(LEJOS, 1.5)
    persona_2 = (ausente(1.5) + quieto(LEJOS_DERECHA, 0.5) + tramo(LEJOS_DERECHA, CERCA_DERECHA, 0.5)
                 + quieto(CERCA_DERECHA, 1) + tramo(CERCA_DERECHA, LEJOS_DERECHA, 0.5) + quieto(LEJOS_DERECHA, 3))
    estacion, detector = estacion_de_prueba(tmp_path, {1: persona_1, 2: persona_2})

    assert estacion.ejecutar() == 0
    assert detector.cerrado and estacion.cuadros == len(persona_1)
    assert set(detector.confianzas) == {0.4}                    # la confianza del detector sale de la configuración

    eventos = eventos_de_zona(entorno)
    estados = [(e["datos"]["estado"], e["datos"]["personas_peligro"], e["datos"]["personas_advertencia"])
               for e in eventos if e["tipo"] == "estado_zona" and not e["datos"].get("refresco")]
    assert estados == [("libre", 0, 0), ("advertencia", 0, 1), ("peligro", 1, 0), ("peligro", 1, 1),
                       ("peligro", 1, 0), ("advertencia", 0, 1), ("libre", 0, 0)]
    assert any(e["datos"].get("refresco") for e in eventos if e["tipo"] == "estado_zona")   # más de 2 s sin cambios
    assert all(e["severidad"] == {"libre": "info", "advertencia": "media", "peligro": "alta"}[e["datos"]["estado"]]
               for e in eventos if e["tipo"] == "estado_zona")

    (ingreso,) = [e for e in eventos if e["tipo"] == "ingreso_zona"]
    assert ingreso["datos"]["zona_id"] == "piso" and ingreso["datos"]["alarma_activada"] is True
    assert ingreso["datos"]["duracion_s"] == pytest.approx(6.9, abs=0.3)
    (casi,) = [e for e in eventos if e["tipo"] == "casi_accidente"]
    assert casi["datos"]["distancia_min_px"] == pytest.approx(34.0, abs=1.5)      # el tobillo más cercano, a 434
    for evento in (ingreso, casi):                              # los dos traen su foto, y el receptor la tiene
        (adjunto,) = evento["adjuntos"]
        assert adjunto["tipo"] == "imagen" and adjunto["ruta"].startswith("media/")
        assert (tmp_path / "receptor" / adjunto["ruta"]).is_file()
        assert evento["severidad"] == "alta" and evento["origen"]["modulo_version"] == "0.1.0"

    # Latido, capacidades con la imagen de referencia y contadores del panel
    assert any(e["tipo"] == "estado_modulo" and e["datos"] == {"modulo": "zona", "estado": "activo"} for e in eventos)
    capacidades = httpx.get(entorno.url + "/api/modulos/zona/capacidades", timeout=5).json()
    assert capacidades["imagen_referencia"]["ancho"] == ANCHO
    assert (estacion.publicador.ingresos, estacion.publicador.casi_accidentes) == (1, 1)


def test_sin_plataforma_la_estacion_vigila_y_cuenta_pero_no_publica(tmp_path, monkeypatch):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    monkeypatch.setenv("API_URL", "http://127.0.0.1:9")        # si intentara publicar, fallaría
    sembrar_config(tmp_path)
    estacion, _ = estacion_de_prueba(tmp_path, {1: quieto(DENTRO, 1) + quieto(LEJOS, 1)}, "--sin-plataforma")
    assert estacion.ejecutar() == 0
    assert estacion.publicador.ingresos == 1
    assert not (tmp_path / "cola" / "zona.jsonl").exists()      # nada se encoló
    assert not (tmp_path / "cola" / "zona" / "capturas").exists()


def test_sin_zona_la_estacion_corre_y_no_publica_estados(tmp_path, monkeypatch):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    estacion, detector = estacion_de_prueba(tmp_path, {1: quieto(DENTRO, 1)}, "--sin-plataforma")
    assert estacion.ejecutar() == 0
    assert estacion.monitor is None and detector.cuadro == FPS
    assert (estacion.publicador.ingresos, estacion.publicador.casi_accidentes) == (0, 0)


def test_la_captura_final_se_guarda_difuminada_con_la_pantalla_completa(tmp_path, monkeypatch):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    monkeypatch.setenv("ZONA_PANTALLA_ANCHO", "1280")
    monkeypatch.setenv("ZONA_PANTALLA_ALTO", "720")
    sembrar_config(tmp_path)
    captura = tmp_path / "salida" / "pantalla.png"
    estacion, _ = estacion_de_prueba(tmp_path, {1: quieto(DENTRO, 1)}, "--sin-plataforma", "--captura", str(captura))
    difuminados = []
    original = modulo_estacion.imagen_para_guardar
    monkeypatch.setattr(modulo_estacion, "imagen_para_guardar",
                        lambda *a, **k: difuminados.append(1) or original(*a, **k))
    estacion.ejecutar()
    assert captura.is_file() and difuminados == [1]


# ------------------------------------------------- cambios de zona en caliente
@pytest.fixture
def suelta(tmp_path, monkeypatch):
    """Una estación sin plataforma a la que se le pasan los fotogramas a mano, sin video ni ventana."""
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    opciones = analizar_argumentos(["--sin-ventana", "--sin-plataforma"])
    estacion = Estacion(opciones, AjustesLocales.desde_entorno(), DetectorSimulado({1: quieto(DENTRO, 20)}))
    yield estacion
    estacion.almacen.detener()
    estacion.publicador.cerrar()


def test_cambiar_la_zona_cierra_la_vigilancia_anterior_y_empieza_otra(suelta):
    frame = np.zeros((ALTO, ANCHO, 3), dtype=np.uint8)
    config = validar_config({"zona_peligro": ZONA})
    for i in range(15):
        resultado, _ = suelta.procesar(frame, i / FPS, config)
    assert resultado.estado.estado == "peligro"
    primera = suelta.monitor

    lejos = validar_config({"zona_peligro": [[0.8, 0.1], [0.95, 0.1], [0.95, 0.3], [0.8, 0.3]]})
    resultado, _ = suelta.procesar(frame, 0.6, lejos)
    assert suelta.monitor is not primera and suelta.monitor.zona.poligono[0] == pytest.approx((512.0, 36.0))
    assert suelta.publicador.ingresos == 1                     # el ingreso abierto se cerró con la zona anterior
    assert resultado.estado.estado == "libre"

    resultado, _ = suelta.procesar(frame, 0.7, validar_config({}))      # se borra la zona
    assert suelta.monitor is None and resultado is None


def test_cambiar_solo_los_tiempos_no_reinicia_la_vigilancia(suelta):
    frame = np.zeros((ALTO, ANCHO, 3), dtype=np.uint8)
    config = validar_config({"zona_peligro": ZONA})
    for i in range(15):
        suelta.procesar(frame, i / FPS, config)
    monitor = suelta.monitor
    resultado, _ = suelta.procesar(frame, 0.55, validar_config({"zona_peligro": ZONA,
                                                               "deteccion": {"antirrebote_s": 1.0, "radio_reasociacion_px": 150}}))
    assert suelta.monitor is monitor and resultado.estado.estado == "peligro"    # la persona sigue contada
    assert monitor.parametros.antirrebote_s == 1.0 and monitor.parametros.radio_reasociacion_px == 150


def test_las_personas_sin_id_del_tracker_se_ignoran(suelta, monkeypatch):
    frame = np.zeros((ALTO, ANCHO, 3), dtype=np.uint8)
    monkeypatch.setattr(suelta.detector, "recorridos", {None: quieto(DENTRO, 20)})
    for i in range(15):
        resultado, personas = suelta.procesar(frame, i / FPS, validar_config({"zona_peligro": ZONA}))
    assert len(personas) == 1 and resultado.personas == () and resultado.estado.estado == "libre"


# ------------------------------------------------------------------- arranque
def test_sin_el_modelo_la_estacion_no_arranca_y_dice_como_bajarlo(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    monkeypatch.setattr(modulo_estacion, "RUTA_MODELO", tmp_path / "no-esta.pt")
    monkeypatch.setattr(modulo_pose, "RUTA_MODELO", tmp_path / "no-esta.pt")
    assert modulo_estacion.main(["--sin-ventana", "--sin-plataforma", "--dispositivo", "cpu"]) == 1
    assert "python -m herramientas.descargar_modelos" in caplog.text


def test_ajustes_de_deteccion_desde_el_entorno(monkeypatch):
    monkeypatch.setenv("ZONA_DISPOSITIVO", "AUTO")
    monkeypatch.setenv("ZONA_IMGSZ", "480")
    monkeypatch.setenv("ZONA_MODELO", "otros/pesos-pose.pt")
    ajustes = AjustesLocales.desde_entorno()
    assert (ajustes.dispositivo, ajustes.imgsz, ajustes.modelo.name) == ("auto", 480, "pesos-pose.pt")
    monkeypatch.delenv("ZONA_DISPOSITIVO")
    monkeypatch.delenv("ZONA_MODELO")
    por_defecto = AjustesLocales.desde_entorno()
    assert por_defecto.dispositivo == "cpu" and por_defecto.modelo is None
