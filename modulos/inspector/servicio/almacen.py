"""Inspecciones en curso: una carpeta por inspección en CARPETA_COLA/inspector/inspecciones/.

Cada carpeta guarda la foto (siempre ya difuminada), las fotos anotadas, el análisis y,
cuando la persona responde, la valoración y el Excel. Quedan en disco para que un
reinicio del servicio no pierda una inspección a medio hacer.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

from modulos.comun.eventos import ZONA_HORARIA

from ..nucleo.imagen import anotar, guardar_jpeg

log = logging.getLogger(__name__)

FOTO, ANOTADA, FINAL, EXCEL, DATOS = "foto.jpg", "anotada.jpg", "final.jpg", "matriz.xlsx", "inspeccion.json"
_ID_VALIDO = re.compile(r"^[a-f0-9]{12}$")


class Almacen:
    """Guarda y recupera inspecciones por su id."""

    def __init__(self, carpeta: str | Path) -> None:
        self.carpeta = Path(carpeta)
        self._cerrojo = threading.Lock()

    def ruta(self, inspeccion_id: str, nombre: str) -> Path:
        return self.carpeta / inspeccion_id / nombre

    def crear(self, frame: np.ndarray, analisis: dict, **datos) -> dict:
        """Crea la inspección con su foto (ya difuminada) y la foto anotada con todos los peligros."""
        inspeccion_id = uuid.uuid4().hex[:12]
        guardar_jpeg(frame, self.ruta(inspeccion_id, FOTO))
        guardar_jpeg(anotar(frame, analisis["peligros"]), self.ruta(inspeccion_id, ANOTADA))
        alto, ancho = frame.shape[:2]
        inspeccion = {
            "id": inspeccion_id,
            "fecha": datetime.now(ZONA_HORARIA).isoformat(timespec="seconds"),
            "ancho": ancho, "alto": alto,
            "analisis": analisis,
            "valoracion": None,
            "evento_id": None,
            **datos,
        }
        self.guardar(inspeccion)
        return inspeccion

    def guardar(self, inspeccion: dict) -> None:
        ruta = self.ruta(inspeccion["id"], DATOS)
        with self._cerrojo:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            temporal = ruta.with_suffix(".tmp")
            temporal.write_text(json.dumps(inspeccion, ensure_ascii=False, indent=1), encoding="utf-8")
            temporal.replace(ruta)

    def leer(self, inspeccion_id: str) -> dict | None:
        """La inspección, o ``None`` si el id no existe o no tiene forma de id."""
        if not isinstance(inspeccion_id, str) or not _ID_VALIDO.match(inspeccion_id):
            return None
        ruta = self.ruta(inspeccion_id, DATOS)
        if not ruta.is_file():
            return None
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            log.warning("No se pudo leer la inspección %s: %s", inspeccion_id, error)
            return None
