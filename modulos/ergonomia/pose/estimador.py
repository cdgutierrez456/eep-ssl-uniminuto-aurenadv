"""Interfaz que cumple cualquier estimador de pose del módulo.

Hoy la implementa MediaPipe (``mediapipe_pose.py``). Para cambiar a otro modelo (por
ejemplo YOLO-pose) basta con otra clase que devuelva los mismos nombres de puntos.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from ..nucleo.angulos import Punto


class EstimadorPose(ABC):
    """Convierte un fotograma en los puntos clave de una persona."""

    @abstractmethod
    def estimar(self, frame_bgr: np.ndarray, marca_ms: int) -> dict[str, Punto] | None:
        """Puntos clave de la persona principal, en píxeles del fotograma, o None si no hay nadie.

        ``marca_ms`` es el tiempo del fotograma en milisegundos y debe crecer en cada llamada.
        Los nombres son los de ``nucleo.angulos``: ``nariz`` y, con sufijo ``_izquierdo`` o
        ``_derecho`` (los de la persona, no los de la imagen), ``oreja``, ``hombro``, ``codo``,
        ``muneca``, ``indice``, ``menique``, ``cadera``, ``rodilla``, ``tobillo``, ``talon`` y
        ``punta_pie``.
        """

    def cerrar(self) -> None:
        """Libera el modelo. Por defecto no hace nada."""
