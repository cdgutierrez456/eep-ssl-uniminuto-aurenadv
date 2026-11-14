"""Clasificación de una persona frente a la zona: libre, advertencia o peligro, con histéresis.

La histéresis evita que alguien parado justo en un límite cambie de nivel con cada temblor
de la detección: para subir de nivel basta cruzar el límite, pero para bajar hay que
alejarse un poco más.
"""

from __future__ import annotations

from enum import IntEnum

from .zona import Medida, Zona


class Nivel(IntEnum):
    """Niveles de riesgo, ordenados: se pueden comparar con ``<`` y ``>``."""

    LIBRE = 0
    ADVERTENCIA = 1
    PELIGRO = 2

    @property
    def nombre(self) -> str:
        """Como viaja en los eventos: ``libre``, ``advertencia`` o ``peligro``."""
        return self.name.lower()


def clasificar(medida: Medida, zona: Zona, confirmado: Nivel = Nivel.LIBRE) -> Nivel:
    """Nivel de una persona en este fotograma, según dónde está y en qué nivel venía.

    - PELIGRO: uno de sus pies está dentro de la zona. Si ya estaba en peligro, lo sigue
      estando hasta alejarse del borde más de ``histeresis`` × margen.
    - ADVERTENCIA: su pie más cercano está a menos del margen. Si ya estaba en advertencia
      o en peligro, lo sigue estando hasta alejarse más de margen × (1 + ``histeresis``).
    - LIBRE: en cualquier otro caso.

    ``confirmado`` es el nivel en que la persona ya está (con antirrebote), no el del
    fotograma anterior.
    """
    if medida.dentro:
        return Nivel.PELIGRO
    distancia = zona.distancia(medida)
    if confirmado is Nivel.PELIGRO and distancia <= zona.margen * zona.histeresis:
        return Nivel.PELIGRO
    limite = zona.margen * (1.0 + zona.histeresis) if confirmado >= Nivel.ADVERTENCIA else zona.margen
    return Nivel.ADVERTENCIA if distancia < limite else Nivel.LIBRE
