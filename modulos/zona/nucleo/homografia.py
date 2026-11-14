"""Homografía imagen → piso: convierte píxeles de la imagen en metros sobre el piso.

Con cuatro puntos de la imagen cuya posición real se conoce (las esquinas del rectángulo de
cinta, de medidas conocidas) se obtiene la transformación proyectiva que lleva cualquier
punto del piso visto en la imagen a su posición en metros.

Solo vale para puntos que están sobre el piso. Un punto elevado (una rodilla, una mano) cae
en un lugar equivocado: por eso el punto de apoyo de una persona son sus tobillos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .geometria import Punto, es_convexo

# Por debajo de esta razón entre valores singulares, los cuatro puntos no definen una homografía
RAZON_MINIMA = 1e-8


class HomografiaInvalida(ValueError):
    """Los puntos dados no definen una homografía. El mensaje dice por qué."""


@dataclass(frozen=True)
class Homografia:
    """Transformación proyectiva entre dos planos, definida por cuatro pares de puntos."""

    matriz: tuple[tuple[float, float, float], ...]  # 3 x 3
    origen: tuple[Punto, ...]  # los cuatro puntos de partida
    destino: tuple[Punto, ...]  # adónde va cada uno

    def aplicar(self, punto: Punto) -> Punto | None:
        """Lleva un punto del plano de origen al de destino.

        Devuelve None si el punto queda en el horizonte o más allá: ahí la cámara no ve piso
        y no hay nada que medir.
        """
        x, y = punto
        (a, b, c), (d, e, f), (g, h, i) = self.matriz
        w = g * x + h * y + i
        if w <= 1e-9:
            return None
        return ((a * x + b * y + c) / w, (d * x + e * y + f) / w)

    def inversa(self) -> "Homografia":
        """La transformación contraria (por ejemplo, piso → imagen, para dibujar)."""
        return homografia_entre(self.destino, self.origen)


def _normalizador(puntos: np.ndarray) -> np.ndarray:
    """Matriz que centra los puntos y los lleva a una escala cercana a 1.

    Sin esto, mezclar píxeles (cientos) con metros (unidades) le quita precisión al cálculo.
    """
    centro = puntos.mean(axis=0)
    radio = float(np.sqrt(((puntos - centro) ** 2).sum(axis=1)).mean())
    if radio <= 0.0:
        raise HomografiaInvalida("los cuatro puntos coinciden")
    escala = math.sqrt(2.0) / radio
    return np.array([[escala, 0.0, -escala * centro[0]], [0.0, escala, -escala * centro[1]], [0.0, 0.0, 1.0]])


def _en_homogeneas(puntos: np.ndarray) -> np.ndarray:
    return np.hstack([puntos, np.ones((len(puntos), 1))])


def homografia_entre(origen: Sequence[Punto], destino: Sequence[Punto]) -> Homografia:
    """Homografía que lleva cada uno de los cuatro puntos de ``origen`` a su par en ``destino``.

    Lanza ``HomografiaInvalida`` si no son cuatro, si tres están alineados o si la
    correspondencia es imposible.
    """
    if len(origen) != 4 or len(destino) != 4:
        raise HomografiaInvalida("se necesitan exactamente cuatro puntos de cada lado")
    p = np.asarray(origen, dtype=float)
    q = np.asarray(destino, dtype=float)
    if not (np.isfinite(p).all() and np.isfinite(q).all()):
        raise HomografiaInvalida("hay coordenadas que no son números")
    t_origen, t_destino = _normalizador(p), _normalizador(q)
    pn = (_en_homogeneas(p) @ t_origen.T)[:, :2]
    qn = (_en_homogeneas(q) @ t_destino.T)[:, :2]

    # Dos ecuaciones por par de puntos; la solución es el vector que anula el sistema
    filas = []
    for (x, y), (u, v) in zip(pn, qn):
        filas.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y, -u])
        filas.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y, -v])
    _, valores, vt = np.linalg.svd(np.asarray(filas))
    if valores[-1] <= RAZON_MINIMA * valores[0]:
        raise HomografiaInvalida("tres de los cuatro puntos están alineados")
    matriz = np.linalg.inv(t_destino) @ vt[-1].reshape(3, 3) @ t_origen

    # La matriz vale salvo un factor: se deja con el divisor positivo sobre los puntos de origen
    divisores = _en_homogeneas(p) @ matriz[2]
    if not ((divisores > 0).all() or (divisores < 0).all()):
        raise HomografiaInvalida("la figura cruza el horizonte: no puede ser la imagen de un rectángulo")
    matriz = matriz / divisores.mean()
    proyectados = _en_homogeneas(p) @ matriz.T
    proyectados = proyectados[:, :2] / proyectados[:, 2:3]
    if not np.allclose(proyectados, q, rtol=1e-6, atol=1e-6 * max(1.0, float(np.abs(q).max()))):
        raise HomografiaInvalida("los puntos no admiten una transformación proyectiva")
    return Homografia(
        matriz=tuple(tuple(float(valor) for valor in fila) for fila in matriz),
        origen=tuple((float(x), float(y)) for x, y in p),
        destino=tuple((float(x), float(y)) for x, y in q),
    )


def homografia_de_rectangulo(cuadrilatero: Sequence[Punto], ancho_m: float, largo_m: float) -> Homografia:
    """Homografía imagen → piso a partir del rectángulo de cinta visto en la imagen.

    ``cuadrilatero`` son sus cuatro esquinas en la imagen, en orden. El lado que va de la
    primera esquina a la segunda mide ``ancho_m`` y el que va de la segunda a la tercera mide
    ``largo_m``. En el piso, la primera esquina queda en el origen (0, 0), la segunda en
    (ancho_m, 0), la tercera en (ancho_m, largo_m) y la cuarta en (0, largo_m).
    """
    if len(cuadrilatero) != 4:
        raise HomografiaInvalida("la zona debe tener exactamente cuatro vértices para medir en metros")
    if not (ancho_m > 0 and largo_m > 0):
        raise HomografiaInvalida("las medidas reales del rectángulo deben ser mayores que cero")
    if not es_convexo(cuadrilatero):
        raise HomografiaInvalida("el cuadrilátero tiene un vértice hundido o sus lados se cruzan")
    rectangulo = ((0.0, 0.0), (float(ancho_m), 0.0), (float(ancho_m), float(largo_m)), (0.0, float(largo_m)))
    return homografia_entre(cuadrilatero, rectangulo)
