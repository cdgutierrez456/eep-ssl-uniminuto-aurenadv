"""Puntos de apoyo, elección del dispositivo y el detector real (si el modelo está en el equipo)."""

import numpy as np
import pytest

from modulos.zona.deteccion import dispositivo as modulo_dispositivo
from modulos.zona.deteccion.dispositivo import gpu_libre, resolver_dispositivo
from modulos.zona.deteccion.personas import Persona, puntos_de_apoyo
from modulos.zona.deteccion.pose import RUTA_MODELO, DetectorPose, ModeloNoDisponible

from .utilidades import persona_en


# ------------------------------------------------------------ puntos de apoyo
def test_con_los_dos_tobillos_a_la_vista_el_apoyo_son_los_tobillos():
    persona = persona_en(1, 300.0, 400.0)
    assert puntos_de_apoyo(persona, 0.5) == ((294.0, 400.0), (306.0, 400.0))


def test_con_un_solo_tobillo_fiable_se_usa_ese():
    puntos = list(persona_en(1, 300.0, 400.0).puntos)
    puntos[15] = (294.0, 400.0, 0.2)            # el izquierdo queda tapado
    persona = Persona(1, (270.0, 225.0, 330.0, 405.0), 0.9, tuple(puntos))
    assert puntos_de_apoyo(persona, 0.5) == ((306.0, 400.0),)


def test_sin_tobillos_fiables_el_apoyo_es_el_punto_medio_del_borde_inferior_de_la_caja():
    persona = persona_en(1, 300.0, 400.0, confianza_tobillos=0.3)
    assert puntos_de_apoyo(persona, 0.5) == ((300.0, 405.0),)
    assert puntos_de_apoyo(persona, 0.25) == ((294.0, 400.0), (306.0, 400.0))   # el umbral es configurable
    sin_pose = Persona(None, (100.0, 50.0, 180.0, 300.0), 0.8)                  # un detector que no da puntos
    assert puntos_de_apoyo(sin_pose) == ((140.0, 300.0),)


# ----------------------------------------------------------------- dispositivo
@pytest.fixture
def gpu(monkeypatch):
    """Simula una GPU: ``gpu(uso, memoria)`` fija lo que diría nvidia-smi; ``gpu(None)`` lo deja sin responder."""
    monkeypatch.setattr(modulo_dispositivo, "_cuda_disponible", lambda: True)

    def fijar(uso=None, memoria=0.1):
        monkeypatch.setattr(modulo_dispositivo, "estado_de_gpu", lambda: None if uso is None else (uso, memoria))
    return fijar


def test_por_defecto_y_con_cpu_siempre_cpu(gpu):
    gpu(0.0)
    assert resolver_dispositivo(None)[0] == "cpu"
    assert resolver_dispositivo("cpu")[0] == "cpu"
    assert resolver_dispositivo(" CPU ")[0] == "cpu"


def test_auto_usa_la_gpu_solo_si_esta_libre(gpu):
    gpu(3.0, 0.07)
    dispositivo, motivo = resolver_dispositivo("auto")
    assert dispositivo == 0 and "libre" in motivo

    gpu(96.0, 0.4)                               # otra sesión está entrenando
    dispositivo, motivo = resolver_dispositivo("auto")
    assert dispositivo == "cpu" and "ocupada" in motivo and "96 %" in motivo

    gpu(5.0, 0.8)                                # poco uso, pero la memoria está tomada
    assert resolver_dispositivo("auto")[0] == "cpu"

    gpu(None)                                    # nvidia-smi no responde: ante la duda, CPU
    assert resolver_dispositivo("auto")[0] == "cpu"
    assert gpu_libre() == (False, "nvidia-smi no responde")


def test_gpu_pedida_a_mano_no_mira_si_esta_libre(gpu):
    gpu(96.0, 0.9)
    assert resolver_dispositivo("gpu")[0] == 0
    assert resolver_dispositivo("cuda")[0] == 0
    assert resolver_dispositivo("1")[0] == 1


def test_sin_gpu_o_con_un_valor_raro_se_usa_cpu(gpu, monkeypatch):
    gpu(0.0)
    assert resolver_dispositivo("turbo")[0] == "cpu"
    monkeypatch.setattr(modulo_dispositivo, "_cuda_disponible", lambda: False)
    for pedido in ("auto", "gpu", "0"):
        dispositivo, motivo = resolver_dispositivo(pedido)
        assert dispositivo == "cpu" and "no ve ninguna GPU" in motivo


# ------------------------------------------------------------------- detector
def test_si_falta_el_modelo_el_error_dice_como_bajarlo(tmp_path):
    with pytest.raises(ModeloNoDisponible, match="python -m herramientas.descargar_modelos"):
        DetectorPose(tmp_path / "yolo26n-pose.pt")


def test_el_detector_real_carga_y_procesa_una_imagen_sin_personas():
    """Comprueba que el modelo descargado, Ultralytics y lap siguen entendiéndose en este equipo."""
    if not RUTA_MODELO.is_file():
        pytest.skip("el modelo de pose no está en este equipo (python -m herramientas.descargar_modelos)")
    pytest.importorskip("ultralytics")
    pytest.importorskip("lap")
    detector = DetectorPose(dispositivo="cpu")
    assert detector.descripcion == "yolo26n-pose en CPU"
    piso = np.full((360, 640, 3), 128, dtype=np.uint8)
    assert detector.detectar(piso, 0.4) == []
    assert detector.detectar(piso, 0.4) == []    # el seguimiento conserva su estado entre fotogramas sin fallar
    detector.reiniciar()
    detector.cerrar()
