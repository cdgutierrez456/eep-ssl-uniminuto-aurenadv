"""Escenas preparadas: las fotos de las escenas del stand con su análisis ya calculado.

Son la salida cuando no hay internet o la API falla: la tablet ofrece "Usar escena
preparada" y el resultado sale de aquí, sin llamar a la IA. Cada escena es una carpeta de
``modulos/inspector/escenas/``::

    escenas/<id>/foto.jpg         la foto, ya con los rostros difuminados
    escenas/<id>/escena.json      nombre para mostrar y, si la foto no es propia, fuente y licencia
    escenas/<id>/resultado.json   el análisis precalculado (lo escribe herramientas/precalcular_escenas.py)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from modulos.comun.eventos import ZONA_HORARIA

log = logging.getLogger(__name__)

CARPETA_ESCENAS = Path(__file__).resolve().parent / "escenas"
NOMBRE_FOTO, NOMBRE_ESCENA, NOMBRE_RESULTADO = "foto.jpg", "escena.json", "resultado.json"
_ID_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def id_valido(identificador: Any) -> bool:
    """Si el texto sirve como id de escena (minúsculas, números, guiones; nada de rutas)."""
    return isinstance(identificador, str) and bool(_ID_VALIDO.match(identificador))


def _leer_json(ruta: Path) -> dict:
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        log.warning("No se pudo leer %s: %s", ruta, error)
        return {}
    return contenido if isinstance(contenido, dict) else {}


def leer_escena(identificador: str, carpeta: Path | None = None) -> dict | None:
    """La escena con su ruta de foto y, si ya se precalculó, su análisis. ``None`` si no existe."""
    if not id_valido(identificador):
        return None
    base = (carpeta or CARPETA_ESCENAS) / identificador
    if not (base / NOMBRE_FOTO).is_file():
        return None
    datos = _leer_json(base / NOMBRE_ESCENA) if (base / NOMBRE_ESCENA).is_file() else {}
    resultado = _leer_json(base / NOMBRE_RESULTADO) if (base / NOMBRE_RESULTADO).is_file() else {}
    return {
        "id": identificador,
        "nombre": datos.get("nombre") or identificador.replace("_", " ").replace("-", " ").capitalize(),
        "fuente": datos.get("fuente"),
        "ruta_foto": base / NOMBRE_FOTO,
        "resultado": resultado if isinstance(resultado.get("analisis"), dict) else None,
    }


def listar_escenas(carpeta: Path | None = None, solo_listas: bool = False) -> list[dict]:
    """Las escenas de la carpeta, por orden de id. ``solo_listas`` deja las que ya tienen análisis."""
    base = carpeta or CARPETA_ESCENAS
    if not base.is_dir():
        return []
    escenas = [leer_escena(ruta.name, base) for ruta in sorted(base.iterdir()) if ruta.is_dir()]
    return [escena for escena in escenas if escena and (escena["resultado"] or not solo_listas)]


def guardar_resultado(identificador: str, analisis: dict, carpeta: Path | None = None, **datos: Any) -> Path:
    """Guarda el análisis precalculado de una escena (con modelo, costo y lo que se quiera anotar)."""
    if not id_valido(identificador):
        raise ValueError(f"'{identificador}' no es un id de escena válido")
    ruta = (carpeta or CARPETA_ESCENAS) / identificador / NOMBRE_RESULTADO
    contenido = {"analisis": analisis, "fecha": datetime.now(ZONA_HORARIA).isoformat(timespec="seconds"), **datos}
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return ruta
