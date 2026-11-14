"""Los eventos que produce la zona, listos para ``modulos.comun.publicar``.

Aquí solo se arma el contenido (``datos`` y ``severidad``) de cada tipo; publicar es cosa de
la estación. Los tres tipos están en ``contrato/evento.schema.json``:

- ``estado_zona``: el estado de la zona cambió (o se repite, con ``refresco``).
- ``ingreso_zona``: una persona estuvo dentro de la zona de peligro y salió.
- ``casi_accidente``: una persona entró a la franja de advertencia y se fue sin pisar la zona.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

SEVERIDAD_DE_ESTADO = {"libre": "info", "advertencia": "media", "peligro": "alta"}
SEVERIDAD_INGRESO = "alta"
SEVERIDAD_CASI_ACCIDENTE = "alta"


@dataclass(frozen=True)
class EstadoZona:
    """Estado de la zona en un momento: el peor nivel entre las personas, y cuántas hay en cada uno."""

    estado: str = "libre"  # libre, advertencia o peligro
    personas_peligro: int = 0
    personas_advertencia: int = 0


@dataclass(frozen=True)
class Textos:
    """Palabras con que se describe un casi-accidente; cambian entre la zona de piso y la de mano."""

    quien: str = "Una persona"
    lugar: str = "la zona de peligro"


@dataclass(frozen=True)
class EventoZona:
    """Un evento por publicar: ``publicar("zona", tipo, datos, severidad=severidad)``."""

    tipo: str
    datos: dict[str, Any]
    severidad: str
    persona_id: int | None = None  # a quién corresponde, para adjuntarle su foto; None en estado_zona
    urgente: bool = False  # debe salir de inmediato: de él depende la alarma


def _decimal(valor: float, decimales: int = 2) -> str:
    """Número con coma decimal, como se escribe en español."""
    return f"{valor:.{decimales}f}".replace(".", ",")


def evento_estado_zona(zona_id: str, estado: EstadoZona, refresco: bool = False) -> EventoZona:
    """``estado_zona``. Con ``refresco`` repite el estado vigente para mantener viva la alarma."""
    datos: dict[str, Any] = {
        "zona_id": zona_id,
        "estado": estado.estado,
        "personas_peligro": estado.personas_peligro,
        "personas_advertencia": estado.personas_advertencia,
    }
    if refresco:
        datos["refresco"] = True
    return EventoZona("estado_zona", datos, SEVERIDAD_DE_ESTADO[estado.estado], urgente=True)


def evento_ingreso_zona(zona_id: str, duracion_s: float, alarma_activada: bool,
                        persona_id: int | None = None) -> EventoZona:
    """``ingreso_zona``: cuánto estuvo la persona dentro de la zona y si la alarma llegó a activarse."""
    datos = {"zona_id": zona_id, "duracion_s": round(max(0.0, duracion_s), 1),
             "alarma_activada": bool(alarma_activada)}
    return EventoZona("ingreso_zona", datos, SEVERIDAD_INGRESO, persona_id)


def descripcion_casi_accidente(distancia_m: float | None, textos: Textos = Textos()) -> str:
    """Frase del casi-accidente. Solo menciona metros si la zona mide en metros."""
    if distancia_m is None:
        return f"{textos.quien} se acercó a {textos.lugar} hasta la franja de advertencia y se retiró sin entrar."
    if distancia_m <= 0.005:  # tocó el borde sin llegar a quedarse dentro
        return f"{textos.quien} alcanzó el borde de {textos.lugar} y se retiró sin llegar a entrar."
    return f"{textos.quien} se acercó a {_decimal(distancia_m)} m de {textos.lugar} y se retiró sin entrar."


def evento_casi_accidente(zona_id: str, distancia_min_px: float, distancia_min_m: float | None = None,
                          persona_id: int | None = None, textos: Textos = Textos()) -> EventoZona:
    """``casi_accidente`` con la distancia mínima alcanzada: en píxeles siempre, en metros si se puede."""
    en_metros = distancia_min_m is not None and math.isfinite(distancia_min_m)
    datos: dict[str, Any] = {
        "zona_id": zona_id,
        "descripcion": descripcion_casi_accidente(distancia_min_m if en_metros else None, textos),
    }
    if math.isfinite(distancia_min_px):
        datos["distancia_min_px"] = round(max(0.0, distancia_min_px), 1)
    if en_metros:
        datos["distancia_min_m"] = round(max(0.0, distancia_min_m), 2)
    return EventoZona("casi_accidente", datos, SEVERIDAD_CASI_ACCIDENTE, persona_id)
