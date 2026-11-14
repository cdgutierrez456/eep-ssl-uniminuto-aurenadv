"""Visitas: cuándo publicar una verificación para no saturar la plataforma.

Una «visita» empieza cuando aparece una persona y termina cuando no hay nadie durante
unos segundos. Dentro de una visita se publica UN evento cuando el veredicto se
mantiene igual durante un tiempo; si después cambia y vuelve a mantenerse, se publica
otra vez. Lógica pura: el reloj entra como parámetro, así se prueba sin cámara.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Firma = tuple[bool, tuple[str, ...]]


@dataclass(frozen=True)
class Novedad:
    """Lo que pasó en este cuadro."""

    publicar: bool = False          # el veredicto quedó estable y aún no se había publicado
    visita_iniciada: bool = False
    visita_terminada: bool = False


class SeguidorDeVisitas:
    """Decide en cada cuadro si hay que publicar el veredicto de la persona principal."""

    def __init__(self, segundos_estable: float = 2.0, segundos_sin_persona: float = 3.0) -> None:
        self.segundos_estable = segundos_estable
        self.segundos_sin_persona = segundos_sin_persona
        self.en_visita = False
        self.numero_visita = 0
        self._ultima_vez_vista = 0.0
        self._candidata: Firma | None = None
        self._desde = 0.0
        self._publicada: Firma | None = None

    def reiniciar_veredicto(self) -> None:
        """Olvida el veredicto en curso y el publicado (cambió la configuración).

        La visita sigue: quien está frente a la cámara se vuelve a evaluar con la
        configuración nueva y, cuando su veredicto se estabilice, se publica de nuevo.
        """
        self._candidata = None
        self._publicada = None

    def actualizar(self, ahora: float, persona: dict[str, Any] | None) -> Novedad:
        """Avanza un cuadro. ``persona`` es el veredicto suavizado de la persona principal o None."""
        if persona is None:
            if self.en_visita and ahora - self._ultima_vez_vista >= self.segundos_sin_persona:
                self.en_visita = False
                self._candidata = None
                self._publicada = None
                return Novedad(visita_terminada=True)
            return Novedad()

        iniciada = not self.en_visita
        if iniciada:
            self.en_visita = True
            self.numero_visita += 1
        self._ultima_vez_vista = ahora

        firma: Firma = (bool(persona["cumple"]), tuple(persona["faltantes"]))
        if firma != self._candidata:
            self._candidata = firma
            self._desde = ahora
            return Novedad(visita_iniciada=iniciada)
        if firma != self._publicada and ahora - self._desde >= self.segundos_estable:
            self._publicada = firma
            return Novedad(publicar=True, visita_iniciada=iniciada)
        return Novedad(visita_iniciada=iniciada)
