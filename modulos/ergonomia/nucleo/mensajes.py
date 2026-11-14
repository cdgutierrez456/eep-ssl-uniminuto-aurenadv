"""Qué significa un puntaje REBA: los textos del panel y del reporte.

REBA no califica si la persona levantó "bien" o "mal". Estima el riesgo de una postura si
forma parte de un trabajo y qué tan urgente es intervenir **la tarea**. Por eso los mensajes
hablan de la postura y de la tarea, nunca de la persona, y cada nivel lleva el nivel de
acción que da el método (Hignett y McAtamney, 2000).

Los textos viven en ``mensajes_reba.json``, fuera del código. Puro, sin dependencias.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .reba import nivel_de_riesgo

RUTA_MENSAJES = Path(__file__).with_name("mensajes_reba.json")
PUNTAJE_MINIMO_PARA_PISTA_DESDE_PISO = 4  # desde riesgo medio


@lru_cache(maxsize=1)
def cargar_mensajes() -> dict:
    """Lee los textos del archivo de datos (una sola vez)."""
    return json.loads(RUTA_MENSAJES.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class MensajeNivel:
    """Lo que se dice de un nivel de riesgo REBA."""

    nivel: str  # insignificante, bajo, medio, alto o muy_alto
    etiqueta: str  # texto corto para el distintivo: "Riesgo alto · intervenir pronto"
    panel: str  # mensaje principal del panel
    accion: str  # nivel de acción según el método
    ampliado: str  # texto para el reporte PDF


def mensaje_de_nivel(nivel: str) -> MensajeNivel:
    """Textos de un nivel de riesgo."""
    try:
        return MensajeNivel(nivel=nivel, **cargar_mensajes()["niveles"][nivel])
    except KeyError:
        raise ValueError(f"Nivel REBA desconocido: {nivel!r}") from None


def mensaje_de_puntaje(puntaje: int) -> MensajeNivel:
    """Textos del nivel que corresponde a un puntaje REBA de 1 a 15."""
    return mensaje_de_nivel(nivel_de_riesgo(puntaje))


def linea_fija() -> str:
    """La línea que siempre acompaña al puntaje: qué es y qué no es REBA."""
    return cargar_mensajes()["linea_fija"]


def cierre_varios_intentos() -> str:
    """Cierre del reporte cuando la visita tuvo varios intentos."""
    return cargar_mensajes()["cierre_varios_intentos"]


def pista_contextual(puntaje: int, desde_piso: bool | None, puntaje_anterior: int | None = None) -> str | None:
    """Pista para mostrar al terminar un levantamiento, o None si no aplica ninguna.

    - Empezó desde el piso y el REBA es 4 o más: desde el piso el riesgo rara vez baja de medio.
    - No empezó desde el piso y el REBA bajó respecto al intento anterior: elevar la carga es
      un control de ingeniería.

    ``desde_piso`` en None (no se pudo saber) no da pista.
    """
    pistas = cargar_mensajes()["pistas"]
    if desde_piso is True and puntaje >= PUNTAJE_MINIMO_PARA_PISTA_DESDE_PISO:
        return pistas["desde_piso"]
    if desde_piso is False and puntaje_anterior is not None and puntaje < puntaje_anterior:
        return pistas["carga_elevada"]
    return None


def seccion_que_significa(puntaje: int, varios_intentos: bool = False) -> dict[str, str]:
    """Contenido de la sección "Qué significa este resultado" del reporte PDF.

    Trae ``titulo``, ``etiqueta``, ``accion``, ``ampliado`` y ``linea_fija``; con varios
    intentos en la visita, también ``cierre``.
    """
    mensaje = mensaje_de_puntaje(puntaje)
    seccion = {
        "titulo": "Qué significa este resultado",
        "etiqueta": mensaje.etiqueta,
        "accion": mensaje.accion,
        "ampliado": mensaje.ampliado,
        "linea_fija": linea_fija(),
    }
    if varios_intentos:
        seccion["cierre"] = cierre_varios_intentos()
    return seccion
