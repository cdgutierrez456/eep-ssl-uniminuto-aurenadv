"""Suavizado de puntos clave con el filtro One Euro (Casiez, Roussel y Vogel, 2012).

Quita el temblor cuando la persona está quieta y casi no añade retraso cuando se mueve:
el corte del filtro sube con la velocidad. Puro, sin dependencias.
"""

from __future__ import annotations

import math
from typing import Mapping

from .angulos import Punto


def _alfa(frecuencia_corte: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * frecuencia_corte)
    return 1.0 / (1.0 + tau / dt)


class FiltroOneEuro:
    """Filtro One Euro para una sola señal."""

    def __init__(self, corte_minimo: float = 1.5, beta: float = 0.02, corte_derivada: float = 1.0) -> None:
        self.corte_minimo = corte_minimo  # Hz; más bajo = más suave en reposo
        self.beta = beta  # cuánto se abre el filtro con la velocidad
        self.corte_derivada = corte_derivada
        self._valor: float | None = None
        self._derivada = 0.0
        self._tiempo = 0.0

    def filtrar(self, valor: float, tiempo_s: float) -> float:
        if self._valor is None or tiempo_s <= self._tiempo:
            self._valor, self._derivada, self._tiempo = valor, 0.0, tiempo_s
            return valor
        dt = tiempo_s - self._tiempo
        derivada = (valor - self._valor) / dt
        self._derivada += _alfa(self.corte_derivada, dt) * (derivada - self._derivada)
        corte = self.corte_minimo + self.beta * abs(self._derivada)
        self._valor += _alfa(corte, dt) * (valor - self._valor)
        self._tiempo = tiempo_s
        return self._valor


class SuavizadorPuntos:
    """Aplica un One Euro a las coordenadas de cada punto clave. La visibilidad no se toca."""

    def __init__(self, corte_minimo: float = 1.5, beta: float = 0.02) -> None:
        self._parametros = (corte_minimo, beta)
        self._filtros: dict[str, tuple[FiltroOneEuro, FiltroOneEuro]] = {}

    def filtrar(self, puntos: Mapping[str, Punto], tiempo_s: float) -> dict[str, Punto]:
        salida = {}
        for nombre, punto in puntos.items():
            if nombre not in self._filtros:
                self._filtros[nombre] = (FiltroOneEuro(*self._parametros), FiltroOneEuro(*self._parametros))
            en_x, en_y = self._filtros[nombre]
            salida[nombre] = Punto(en_x.filtrar(punto.x, tiempo_s), en_y.filtrar(punto.y, tiempo_s), punto.visibilidad)
        return salida

    def reiniciar(self) -> None:
        """Olvida el historial (por ejemplo, cuando la persona sale del cuadro)."""
        self._filtros.clear()
