"""Dibujo de la calibración: la zona, la propuesta, los vértices editables y el diagnóstico de la cinta."""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

from ..interfaz.marca import AMARILLO, DEEP, MARFIL, NEGRO, ROJO, Color, bgr
from ..interfaz.texto import escribir
from ..nucleo.geometria import Punto, desnormalizar
from .cinta import DeteccionCinta, RangoHSV, mascara_de_amarillo

NOMBRE_DE_LADO = ("ancho", "largo")  # los dos primeros lados de un cuadrilátero: lo que mide rectangulo_real


def _enteros(poligono: Sequence[Punto]) -> np.ndarray:
    return np.array(poligono, dtype=np.float32).round().astype(np.int32)


def rellenar_poligono(imagen: np.ndarray, poligono: Sequence[Punto], color: Color, opacidad: float = 0.3,
                      grosor: int = 2) -> None:
    """Pinta el polígono (en píxeles) translúcido, con su borde. Modifica la imagen."""
    if len(poligono) < 3:
        return
    puntos = _enteros(poligono)
    x, y, ancho, alto = cv2.boundingRect(puntos)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(imagen.shape[1], x + ancho), min(imagen.shape[0], y + alto)
    if x1 > x0 and y1 > y0 and opacidad > 0:
        recorte = imagen[y0:y1, x0:x1]
        capa = recorte.copy()
        cv2.fillPoly(capa, [puntos - (x0, y0)], bgr(color))
        cv2.addWeighted(capa, opacidad, recorte, 1.0 - opacidad, 0.0, dst=recorte)
    cv2.polylines(imagen, [puntos], True, bgr(color), grosor, cv2.LINE_AA)


def dibujar_vertices(imagen: np.ndarray, poligono: Sequence[Punto], color: Color, agarrado: int | None = None,
                     radio: int = 9, rotular_lados: bool = True) -> None:
    """Dibuja el contorno con sus vértices numerados; en un cuadrilátero rotula el ancho y el largo."""
    if not poligono:
        return
    puntos = _enteros(poligono)
    if len(puntos) >= 2:
        cv2.polylines(imagen, [puntos], len(puntos) >= 3, bgr(color), 2, cv2.LINE_AA)
    for indice, (x, y) in enumerate(puntos):
        relleno = MARFIL if indice == agarrado else color
        cv2.circle(imagen, (int(x), int(y)), radio + 2, bgr(NEGRO), -1, cv2.LINE_AA)
        cv2.circle(imagen, (int(x), int(y)), radio, bgr(relleno), -1, cv2.LINE_AA)
        escribir(imagen, str(indice + 1), int(x) + radio + 4, int(y) - radio - 18, 20, MARFIL, negrita=True, fondo=DEEP, relleno=3)
    if rotular_lados and len(puntos) == 4:
        for lado, nombre in enumerate(NOMBRE_DE_LADO):
            (x0, y0), (x1, y1) = puntos[lado], puntos[lado + 1]
            escribir(imagen, nombre, int((x0 + x1) / 2) - 22, int((y0 + y1) / 2) - 12, 18, NEGRO, negrita=True,
                     fondo=MARFIL, relleno=3)


def resaltar_amarillo(vista: np.ndarray, rango: RangoHSV) -> None:
    """Deja en blanco lo que la detección toma por amarillo: sirve para ajustar el rango de color."""
    escala = min(1.0, 640 / vista.shape[1])
    reducida = cv2.resize(vista, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA) if escala < 1 else vista
    mascara = cv2.resize(mascara_de_amarillo(reducida, rango), (vista.shape[1], vista.shape[0]),
                         interpolation=cv2.INTER_NEAREST)
    vista[mascara > 0] = (vista[mascara > 0] * 0.25 + 255 * 0.75).astype(np.uint8)


def imagen_de_diagnostico(imagen: np.ndarray, deteccion: DeteccionCinta, ancho_panel: int = 640) -> np.ndarray:
    """Dos paneles lado a lado: la imagen con el polígono propuesto y la máscara de amarillo.

    Sirve para entender por qué la detección encontró (o no) la cinta y ajustar el rango de color.
    """
    alto, ancho = imagen.shape[:2]
    escala = ancho_panel / ancho
    tamano = (ancho_panel, round(alto * escala))
    izquierda = cv2.resize(imagen, tamano, interpolation=cv2.INTER_AREA)
    derecha = cv2.cvtColor(cv2.resize(deteccion.mascara, tamano, interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
    if deteccion.poligono:
        poligono = desnormalizar(deteccion.poligono, tamano[0], tamano[1])
        rellenar_poligono(izquierda, poligono, ROJO, 0.25)
        dibujar_vertices(izquierda, poligono, AMARILLO, radio=6)
        cv2.polylines(derecha, [_enteros(poligono)], True, bgr(ROJO), 2, cv2.LINE_AA)
    escribir(izquierda, "Imagen y polígono propuesto", 10, 10, 18, MARFIL, negrita=True, fondo=DEEP)
    escribir(derecha, "Máscara de amarillo (franjas ya unidas)", 10, 10, 18, MARFIL, negrita=True, fondo=DEEP)
    franja = np.full((44, 2 * ancho_panel, 3), bgr(DEEP), dtype=np.uint8)
    escribir(franja, deteccion.mensaje, 10, 10, 17, MARFIL)
    return np.vstack([np.hstack([izquierda, derecha]), franja])
