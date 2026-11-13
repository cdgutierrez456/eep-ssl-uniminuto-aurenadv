"""Difuminado de rostros para toda imagen guardada o mostrada.

Detector principal: YuNet (OpenCV), liviano, corre en CPU y sin internet; el
modelo ONNX está versionado en modulos/comun/modelos/. Si el modelo falta o
la versión de OpenCV no lo soporta, se usa la cascada Haar que viene con OpenCV.
"""

import logging
import threading
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

RUTA_MODELO = Path(__file__).parent / "modelos" / "face_detection_yunet_2023mar.onnx"
UMBRAL_CONFIANZA = 0.6
MARGEN = 0.20  # el recuadro se agranda 20 % por lado para cubrir frente y mentón

_candado = threading.Lock()  # los detectores de OpenCV no son seguros entre hilos
_yunet = None
_haar = None
_listo = False


def _preparar() -> None:
    """Carga el detector una sola vez."""
    global _yunet, _haar, _listo
    if _listo:
        return
    try:
        # Se lee el modelo a memoria: cv2 no abre rutas con tildes en Windows
        contenido = np.fromfile(str(RUTA_MODELO), dtype=np.uint8)
        _yunet = cv2.FaceDetectorYN.create("onnx", contenido, np.empty(0, np.uint8), (320, 320), UMBRAL_CONFIANZA)
    except Exception as error:  # modelo ausente o OpenCV sin FaceDetectorYN
        log.warning("No se pudo cargar YuNet (%s); se usa la cascada Haar, menos precisa", error)
        _haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    _listo = True


def detectar_rostros(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Devuelve los rostros del frame BGR como recuadros (x, y, ancho, alto)."""
    alto, ancho = frame.shape[:2]
    with _candado:
        _preparar()
        if _yunet is not None:
            _yunet.setInputSize((ancho, alto))
            _, caras = _yunet.detect(frame)
            if caras is None:
                return []
            return [tuple(int(v) for v in cara[:4]) for cara in caras]
        gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return [tuple(int(v) for v in cara) for cara in _haar.detectMultiScale(gris, 1.1, 5)]


def difuminar_rostros(frame: np.ndarray) -> np.ndarray:
    """Devuelve una copia del frame de OpenCV (BGR) con los rostros difuminados.

    El frame original no se modifica. Úsese antes de guardar, subir o mostrar
    cualquier imagen.
    """
    salida = frame.copy()
    alto, ancho = salida.shape[:2]
    for x, y, w, h in detectar_rostros(frame):
        x0 = max(0, int(x - w * MARGEN))
        y0 = max(0, int(y - h * MARGEN))
        x1 = min(ancho, int(x + w * (1 + MARGEN)))
        y1 = min(alto, int(y + h * (1 + MARGEN)))
        if x1 <= x0 or y1 <= y0:
            continue
        region = salida[y0:y1, x0:x1]
        # Núcleo proporcional al rostro (impar) para que no sea reconocible
        nucleo = max(31, (max(x1 - x0, y1 - y0) // 2) | 1)
        salida[y0:y1, x0:x1] = cv2.GaussianBlur(region, (nucleo, nucleo), 0)
    return salida
