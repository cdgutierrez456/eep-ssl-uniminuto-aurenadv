"""Estimador de pose con MediaPipe Pose Landmarker, en CPU.

El modelo (``pose_landmarker_full.task``, unos 9 MB) no va en git. Se descarga una vez::

    python -m modulos.ergonomia.pose.mediapipe_pose

y queda en ``modulos/ergonomia/modelos/``. Después el módulo funciona sin internet.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from ..nucleo.angulos import Punto
from .estimador import EstimadorPose

log = logging.getLogger(__name__)

CARPETA_MODELOS = Path(__file__).resolve().parents[1] / "modelos"
RUTA_MODELO = CARPETA_MODELOS / "pose_landmarker_full.task"
URL_MODELO = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
              "pose_landmarker_full/float16/latest/pose_landmarker_full.task")

# Índices de los 33 puntos de MediaPipe Pose que usa el módulo
INDICES = {
    "nariz": 0,
    "oreja_izquierdo": 7, "oreja_derecho": 8,
    "hombro_izquierdo": 11, "hombro_derecho": 12,
    "codo_izquierdo": 13, "codo_derecho": 14,
    "muneca_izquierdo": 15, "muneca_derecho": 16,
    "menique_izquierdo": 17, "menique_derecho": 18,
    "indice_izquierdo": 19, "indice_derecho": 20,
    "cadera_izquierdo": 23, "cadera_derecho": 24,
    "rodilla_izquierdo": 25, "rodilla_derecho": 26,
    "tobillo_izquierdo": 27, "tobillo_derecho": 28,
    "talon_izquierdo": 29, "talon_derecho": 30,
    "punta_pie_izquierdo": 31, "punta_pie_derecho": 32,
}


def descargar_modelo(ruta: Path = RUTA_MODELO) -> Path:
    """Descarga el modelo de pose si no está. Es el único paso que necesita internet."""
    if ruta.is_file():
        return ruta
    import httpx

    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".descarga")
    log.info("Descargando el modelo de pose a %s", ruta.as_posix())
    with httpx.stream("GET", URL_MODELO, timeout=60.0, follow_redirects=True) as respuesta:
        respuesta.raise_for_status()
        with open(temporal, "wb") as archivo:
            for bloque in respuesta.iter_bytes():
                archivo.write(bloque)
    temporal.replace(ruta)
    return ruta


class EstimadorMediaPipe(EstimadorPose):
    """Pose Landmarker en modo video (usa el seguimiento entre fotogramas)."""

    def __init__(self, ruta_modelo: Path = RUTA_MODELO, dispositivo: str = "cpu",
                 confianza_minima: float = 0.5) -> None:
        # Se importa aquí para que el resto del módulo (y sus pruebas) no dependa de MediaPipe
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        if not ruta_modelo.is_file():
            raise FileNotFoundError(
                f"Falta el modelo de pose en {ruta_modelo.as_posix()}. "
                "Descárgalo una vez con: python -m modulos.ergonomia.pose.mediapipe_pose"
            )
        if dispositivo.lower() == "gpu":
            delegado = BaseOptions.Delegate.GPU
        else:
            if dispositivo.lower() != "cpu":
                log.warning("Dispositivo '%s' desconocido para MediaPipe; se usa CPU", dispositivo)
            delegado = BaseOptions.Delegate.CPU
        self._mp = mp
        # El modelo se pasa en memoria: así no importa si la ruta tiene tildes o espacios
        opciones = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=ruta_modelo.read_bytes(), delegate=delegado),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=confianza_minima,
            min_pose_presence_confidence=confianza_minima,
            min_tracking_confidence=confianza_minima,
        )
        self._detector = vision.PoseLandmarker.create_from_options(opciones)
        self._ultima_marca = -1
        log.info("Estimador de pose MediaPipe listo (%s)", dispositivo.lower())

    def estimar(self, frame_bgr: np.ndarray, marca_ms: int) -> dict[str, Punto] | None:
        marca_ms = max(int(marca_ms), self._ultima_marca + 1)  # MediaPipe exige marcas crecientes
        self._ultima_marca = marca_ms
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        imagen = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        resultado = self._detector.detect_for_video(imagen, marca_ms)
        if not resultado.pose_landmarks:
            return None
        puntos = resultado.pose_landmarks[0]
        alto, ancho = frame_bgr.shape[:2]
        # MediaPipe da coordenadas normalizadas; se pasan a píxeles para no deformar los ángulos
        return {nombre: Punto(puntos[i].x * ancho, puntos[i].y * alto, float(puntos[i].visibility or 0.0))
                for nombre, i in INDICES.items()}

    def cerrar(self) -> None:
        self._detector.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"Modelo de pose en {descargar_modelo().as_posix()}")
