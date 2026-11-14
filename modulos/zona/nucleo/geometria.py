"""Geometría plana del módulo de zona: puntos, segmentos y polígonos. Sin dependencias.

Las funciones no saben de cámaras: trabajan en el sistema de coordenadas que reciban
(píxeles de la imagen o metros del piso) y devuelven distancias en esa misma unidad.
Un polígono es una secuencia de vértices ``(x, y)`` en orden, sin repetir el primero al final.
"""

from __future__ import annotations

import math
from typing import Iterator, Sequence

Punto = tuple[float, float]
Poligono = Sequence[Punto]

TOLERANCIA = 1e-9


def _lados(poligono: Poligono) -> Iterator[tuple[Punto, Punto]]:
    """Lados del polígono como pares de vértices, incluido el que cierra la figura."""
    cantidad = len(poligono)
    for i in range(cantidad):
        yield poligono[i], poligono[(i + 1) % cantidad]


def area_con_signo(poligono: Poligono) -> float:
    """Área por la fórmula del cordón. El signo indica el sentido en que giran los vértices."""
    return 0.5 * sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in _lados(poligono))


def area(poligono: Poligono) -> float:
    return abs(area_con_signo(poligono))


def es_poligono_valido(poligono: Poligono) -> bool:
    """Al menos tres vértices y un área que no sea nula (no todos alineados)."""
    return len(poligono) >= 3 and area(poligono) > TOLERANCIA


def es_convexo(poligono: Poligono) -> bool:
    """True si el polígono no tiene entrantes: todos sus giros van en el mismo sentido.

    Pensada para cuadriláteros: descarta los que tienen un vértice hundido y los que se
    cruzan en forma de moño, que no pueden ser la imagen de un rectángulo.
    """
    if not es_poligono_valido(poligono):
        return False
    cantidad = len(poligono)
    sentido = 0
    for i in range(cantidad):
        (ax, ay), (bx, by), (cx, cy) = poligono[i], poligono[(i + 1) % cantidad], poligono[(i + 2) % cantidad]
        giro = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(giro) <= TOLERANCIA:
            continue  # tres vértices alineados no rompen la convexidad
        if sentido and (giro > 0) != (sentido > 0):
            return False
        sentido = 1 if giro > 0 else -1
    return sentido != 0


def distancia_a_segmento(punto: Punto, a: Punto, b: Punto) -> float:
    """Distancia del punto al segmento ``a``-``b`` (a su punto más cercano, no a la recta)."""
    (px, py), (ax, ay), (bx, by) = punto, a, b
    dx, dy = bx - ax, by - ay
    largo_cuadrado = dx * dx + dy * dy
    if largo_cuadrado <= 0.0:  # el segmento es un punto
        return math.hypot(px - ax, py - ay)
    avance = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / largo_cuadrado))
    return math.hypot(px - (ax + avance * dx), py - (ay + avance * dy))


def distancia_al_borde(punto: Punto, poligono: Poligono) -> float:
    """Distancia del punto al lado más cercano del polígono, esté dentro o fuera."""
    return min(distancia_a_segmento(punto, a, b) for a, b in _lados(poligono))


def punto_en_poligono(punto: Punto, poligono: Poligono) -> bool:
    """True si el punto está dentro del polígono. Un punto sobre el borde cuenta como dentro.

    Regla par-impar: se cuenta cuántos lados cruza una semirrecta horizontal que sale del
    punto. Sirve para polígonos con entrantes.
    """
    if len(poligono) < 3:
        return False
    if distancia_al_borde(punto, poligono) <= TOLERANCIA:
        return True
    x, y = punto
    dentro = False
    for (x1, y1), (x2, y2) in _lados(poligono):
        if (y1 > y) != (y2 > y):  # el lado cruza la altura del punto
            x_cruce = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cruce:
                dentro = not dentro
    return dentro


def distancia_a_poligono(punto: Punto, poligono: Poligono) -> float:
    """Cuánto le falta al punto para tocar el polígono: 0 si está dentro o en el borde."""
    if punto_en_poligono(punto, poligono):
        return 0.0
    return distancia_al_borde(punto, poligono)


def desnormalizar(poligono: Poligono, ancho: float, alto: float) -> tuple[Punto, ...]:
    """De coordenadas normalizadas (0 a 1 sobre la imagen) a píxeles."""
    return tuple((float(x) * ancho, float(y) * alto) for x, y in poligono)


def normalizar(poligono: Poligono, ancho: float, alto: float) -> tuple[Punto, ...]:
    """De píxeles a coordenadas normalizadas (0 a 1 sobre la imagen)."""
    return tuple((float(x) / ancho, float(y) / alto) for x, y in poligono)
