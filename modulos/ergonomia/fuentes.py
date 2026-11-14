"""Fuente de fotogramas desde un archivo de video, con la misma forma que la cámara.

Sirve para desarrollar y probar sin estar frente a la cámara (``--video ruta.mp4``).
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np


class FuenteVideo:
    """Lee un archivo de video al ritmo de sus fps. Misma interfaz que ``modulos.comun.Camara``."""

    def __init__(self, ruta: Path, repetir: bool = False, tiempo_real: bool = True) -> None:
        self.ruta = Path(ruta)
        if not self.ruta.is_file():
            raise FileNotFoundError(f"No existe el video: {self.ruta}")
        self._captura = cv2.VideoCapture(str(self.ruta))  # cv2 no acepta Path
        if not self._captura.isOpened():
            raise OSError(f"No se pudo abrir el video: {self.ruta}")
        self.fps = self._captura.get(cv2.CAP_PROP_FPS) or 30.0
        self.repetir = repetir
        self.tiempo_real = tiempo_real
        self.terminada = False
        self.cuadro = 0
        self._siguiente = time.monotonic()

    conectada = True
    mensaje = None

    @property
    def fps_reales(self) -> float:
        return self.fps

    @property
    def marca_ms(self) -> int:
        """Tiempo del último fotograma dentro del video, en milisegundos."""
        return round(self.cuadro * 1000.0 / self.fps)

    def leer(self) -> np.ndarray | None:
        if self.terminada:
            return None
        correcto, frame = self._captura.read()
        if not correcto and self.repetir and self.cuadro:
            self._captura.set(cv2.CAP_PROP_POS_FRAMES, 0)
            correcto, frame = self._captura.read()
        if not correcto or frame is None:
            self.terminada = True
            return None
        self.cuadro += 1
        if self.tiempo_real:  # espera lo necesario para no reproducir más rápido que el original
            espera = self._siguiente - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            self._siguiente = max(self._siguiente + 1.0 / self.fps, time.monotonic())
        return frame

    def cerrar(self) -> None:
        self._captura.release()
