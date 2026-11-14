"""Las personas que entrega el detector y sus puntos de apoyo. Sin dependencias: se prueba solo.

El punto de apoyo es dónde la persona toca el piso, que es lo que se compara con la zona:
sus tobillos si se ven bien y, si no, el punto medio del borde inferior de su caja.
"""

from __future__ import annotations

from dataclasses import dataclass

Punto = tuple[float, float]

# Índices de los puntos de pose de COCO que usa el módulo
TOBILLO_IZQUIERDO, TOBILLO_DERECHO = 15, 16


@dataclass(frozen=True)
class Persona:
    """Una persona en un fotograma, en píxeles de la imagen."""

    persona_id: int | None  # id del tracker; None si todavía no le asignó uno
    caja: tuple[float, float, float, float]  # x1, y1, x2, y2
    confianza: float
    puntos: tuple[tuple[float, float, float], ...] = ()  # 17 puntos de COCO como (x, y, confianza)

    def tobillos(self, confianza_minima: float) -> tuple[Punto, ...]:
        """Los tobillos que el modelo ve con confianza suficiente (ninguno, uno o los dos)."""
        return tuple((self.puntos[i][0], self.puntos[i][1]) for i in (TOBILLO_IZQUIERDO, TOBILLO_DERECHO)
                     if i < len(self.puntos) and self.puntos[i][2] >= confianza_minima)

    def base_de_la_caja(self) -> Punto:
        """Punto medio del borde inferior de la caja: donde se supone que pisa si no se ven los tobillos."""
        x1, _, x2, y2 = self.caja
        return ((x1 + x2) / 2.0, y2)


def puntos_de_apoyo(persona: Persona, confianza_punto: float = 0.5) -> tuple[Punto, ...]:
    """Dónde toca el piso la persona: sus tobillos fiables o, si no hay ninguno, la base de su caja."""
    return persona.tobillos(confianza_punto) or (persona.base_de_la_caja(),)
