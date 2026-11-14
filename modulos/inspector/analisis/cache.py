"""Caché de análisis por foto: la misma foto no se analiza dos veces.

La clave sale del contenido de la foto (su hash) y de lo que cambia el resultado: modelo,
prompt, esfuerzo, tamaño de imagen y máximo de peligros. Cambiar cualquiera de ellos
vuelve a analizar.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def hash_de_foto(datos: bytes) -> str:
    """Huella de la foto tal como llegó (SHA-256 en hexadecimal)."""
    return hashlib.sha256(datos).hexdigest()


class CacheDeAnalisis:
    """Análisis guardados en disco, un JSON por foto y combinación de ajustes."""

    def __init__(self, carpeta: str | Path) -> None:
        self.carpeta = Path(carpeta)

    @staticmethod
    def clave(hash_foto: str, **ajustes: Any) -> str:
        """Clave de la entrada: la huella de la foto más los ajustes que cambian el resultado."""
        texto = json.dumps({"foto": hash_foto, **ajustes}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:40]

    def _ruta(self, clave: str) -> Path:
        return self.carpeta / f"{clave}.json"

    def leer(self, clave: str) -> dict | None:
        """El contenido guardado, o ``None`` si no hay o el archivo no sirve."""
        ruta = self._ruta(clave)
        if not ruta.is_file():
            return None
        try:
            contenido = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            log.warning("La entrada de caché %s no sirve (%s); se vuelve a analizar", ruta.name, error)
            return None
        return contenido if isinstance(contenido, dict) else None

    def guardar(self, clave: str, contenido: dict) -> None:
        """Guarda la entrada. Un fallo al escribir no interrumpe el análisis."""
        try:
            self.carpeta.mkdir(parents=True, exist_ok=True)
            temporal = self._ruta(clave).with_suffix(".tmp")
            temporal.write_text(json.dumps(contenido, ensure_ascii=False, indent=1), encoding="utf-8")
            temporal.replace(self._ruta(clave))
        except OSError as error:
            log.warning("No se pudo guardar el análisis en la caché: %s", error)
