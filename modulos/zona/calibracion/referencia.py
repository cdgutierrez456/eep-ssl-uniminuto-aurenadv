"""Imagen de referencia: la foto de la cámara sobre la que se dibuja y se edita la zona.

El módulo la toma al arrancar y cada vez que calibra, la sube a la plataforma y reporta su
ruta en sus capacidades, para que el editor de la plataforma dibuje la zona encima.

Privacidad: sale de la vista en vivo hacia un archivo y hacia la plataforma, así que pasa
por ``difuminar_rostros`` antes de tocar el disco.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from modulos.comun import difuminar_rostros, subir_medio
from modulos.comun.config import leer_entorno
from modulos.comun.eventos import ZONA_HORARIA

log = logging.getLogger(__name__)

NOMBRE_ARCHIVO = "referencia.jpg"  # siempre el mismo: en el equipo solo queda la más reciente


@dataclass(frozen=True)
class Referencia:
    """Una imagen de referencia ya guardada."""

    ruta_local: Path  # copia en este equipo (rostros difuminados)
    ruta: str | None  # ruta del medio en la plataforma; None si no se subió
    ancho: int
    alto: int
    timestamp: str  # ISO 8601, hora de Bogotá

    def para_capacidades(self) -> dict[str, Any] | None:
        """Como va en las capacidades del módulo. None si la plataforma no la tiene."""
        if self.ruta is None:
            return None
        return {"ruta": self.ruta, "ancho": self.ancho, "alto": self.alto, "timestamp": self.timestamp}


def carpeta_de_referencia() -> Path:
    return leer_entorno().carpeta_cola / "zona" / "referencia"


def tomar_referencia(frame: np.ndarray, subir: bool = True, carpeta: Path | None = None) -> Referencia:
    """Difumina los rostros del fotograma, lo guarda y, si ``subir``, lo manda a la plataforma.

    Si la plataforma no responde, ``ruta`` queda en None: la copia de respaldo que deja
    ``subir_medio`` es un archivo de este equipo y a la plataforma no le sirve.
    """
    imagen = difuminar_rostros(frame)
    carpeta = carpeta or carpeta_de_referencia()
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_local = carpeta / NOMBRE_ARCHIVO
    correcto, datos = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not correcto:
        raise OSError(f"No se pudo codificar la imagen de referencia {ruta_local}")
    datos.tofile(str(ruta_local))  # así también funcionan las rutas con tildes en Windows

    ruta = None
    if subir:
        subida = subir_medio(ruta_local)
        if "medios_pendientes" in Path(subida).parts:
            log.warning("La imagen de referencia no llegó a la plataforma; el editor remoto no la verá todavía")
        else:
            ruta = subida
    alto, ancho = imagen.shape[:2]
    return Referencia(ruta_local, ruta, ancho, alto, datetime.now(ZONA_HORARIA).isoformat(timespec="seconds"))
