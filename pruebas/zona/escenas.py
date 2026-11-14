"""Escenas sintéticas del piso del stand, para probar la detección de la cinta sin cámara.

Una cámara simulada (alta e inclinada hacia abajo) mira un piso beige con un rectángulo de
cinta amarilla y negra, con perspectiva, ruido, iluminación despareja y, si se pide, un
objeto amarillo macizo que no es la zona.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

BEIGE = (170, 200, 220)  # BGR
AMARILLO_CINTA = (25, 200, 240)
AMARILLO_OBJETO = (10, 215, 250)
NEGRO_CINTA = (32, 32, 32)
GRIS_MAQUINA = (120, 120, 125)


@dataclass
class Escena:
    imagen: np.ndarray  # BGR
    esquinas: list[tuple[float, float]]  # esquinas exteriores de la cinta en la imagen; vacía si no hay cinta


class Camara:
    """Cámara simulada: a ``altura`` metros, ``distancia`` metros antes del origen, inclinada hacia abajo."""

    def __init__(self, ancho: int, alto: int, altura: float, distancia: float, inclinacion: float,
                 centro_x: float) -> None:
        angulo = math.radians(inclinacion)
        self.posicion = np.array([centro_x, -distancia, altura])
        self.rotacion = np.array([
            [1.0, 0.0, 0.0],
            [0.0, -math.sin(angulo), -math.cos(angulo)],
            [0.0, math.cos(angulo), -math.sin(angulo)],
        ])
        self.focal = 0.7 * ancho
        self.centro = (ancho / 2, alto / 2)

    def proyectar(self, x_m: float, y_m: float) -> tuple[float, float]:
        x, y, z = self.rotacion @ (np.array([x_m, y_m, 0.0]) - self.posicion)
        return (self.focal * x / z + self.centro[0], self.focal * y / z + self.centro[1])

    def poligono(self, puntos_m) -> np.ndarray:
        return np.array([self.proyectar(x, y) for x, y in puntos_m], dtype=np.float32).round().astype(np.int32)


def _girar(puntos, centro, grados):
    angulo = math.radians(grados)
    coseno, seno = math.cos(angulo), math.sin(angulo)
    return [(centro[0] + (x - centro[0]) * coseno - (y - centro[1]) * seno,
             centro[1] + (x - centro[0]) * seno + (y - centro[1]) * coseno) for x, y in puntos]


def crear_escena(
    ancho: int = 1280,
    alto: int = 720,
    *,
    rectangulo: tuple[float, float] = (1.5, 1.0),  # ancho y largo de la zona en metros
    cinta_m: float = 0.05,
    con_cinta: bool = True,
    franjas: bool = True,
    distractor: tuple[float, float, float] | None = (2.2, 0.1, 0.6),  # x, y y lado en metros
    maquina: bool = False,
    giro: float = 0.0,  # grados que la zona está girada sobre el piso
    ruido: float = 8.0,
    altura: float = 2.0,
    distancia: float = 1.5,
    inclinacion: float = 50.0,
    semilla: int = 0,
) -> Escena:
    """Arma la escena. Devuelve la imagen y dónde quedaron las esquinas exteriores de la cinta."""
    generador = np.random.default_rng(semilla)
    ancho_m, largo_m = rectangulo
    centro = (ancho_m / 2, largo_m / 2)
    camara = Camara(ancho, alto, altura, distancia, inclinacion, centro[0])
    imagen = np.full((alto, ancho, 3), BEIGE, dtype=np.uint8)

    esquinas: list[tuple[float, float]] = []
    if con_cinta:
        exterior = _girar([(0, 0), (ancho_m, 0), (ancho_m, largo_m), (0, largo_m)], centro, giro)
        interior = _girar([(cinta_m, cinta_m), (ancho_m - cinta_m, cinta_m),
                           (ancho_m - cinta_m, largo_m - cinta_m), (cinta_m, largo_m - cinta_m)], centro, giro)
        marco = np.zeros((alto, ancho), dtype=np.uint8)
        cv2.fillPoly(marco, [camara.poligono(exterior)], 255)
        cv2.fillPoly(marco, [camara.poligono(interior)], 0)
        imagen[marco > 0] = AMARILLO_CINTA
        if franjas:  # franjas negras a 45°, tan anchas como las amarillas (una cada 10 cm), en los cuatro lados
            negras = np.zeros((alto, ancho), dtype=np.uint8)
            y0, y1 = -0.1, largo_m + 0.1
            corte = -largo_m - 0.2  # cada franja es la banda corte <= x - y <= corte + 0,05
            while corte < ancho_m + 0.2:
                franja = [(corte + y0, y0), (corte + 0.05 + y0, y0), (corte + 0.05 + y1, y1), (corte + y1, y1)]
                cv2.fillPoly(negras, [camara.poligono(_girar(franja, centro, giro))], 255)
                corte += 0.10
            imagen[(marco > 0) & (negras > 0)] = NEGRO_CINTA
        esquinas = [camara.proyectar(x, y) for x, y in exterior]

    if maquina:  # una caja gris dentro de la zona
        lado = min(ancho_m, largo_m) * 0.35
        caja = [(centro[0] - lado / 2, centro[1] - lado / 2), (centro[0] + lado / 2, centro[1] - lado / 2),
                (centro[0] + lado / 2, centro[1] + lado / 2), (centro[0] - lado / 2, centro[1] + lado / 2)]
        cv2.fillPoly(imagen, [camara.poligono(caja)], GRIS_MAQUINA)

    if distractor is not None:  # un objeto amarillo macizo fuera de la zona
        x, y, lado = distractor
        cv2.fillPoly(imagen, [camara.poligono([(x, y), (x + lado, y), (x + lado, y + lado), (x, y + lado)])],
                     AMARILLO_OBJETO)

    # Iluminación despareja de izquierda a derecha, desenfoque leve de la lente y ruido del sensor
    rampa = np.linspace(0.86, 1.08, ancho, dtype=np.float32)[None, :, None]
    resultado = cv2.GaussianBlur(imagen, (3, 3), 0).astype(np.float32) * rampa
    if ruido > 0:
        resultado += generador.normal(0.0, ruido, resultado.shape).astype(np.float32)
    return Escena(np.clip(resultado, 0, 255).astype(np.uint8), esquinas)
