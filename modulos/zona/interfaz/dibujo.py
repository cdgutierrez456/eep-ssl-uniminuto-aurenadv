"""Dibujo sobre la imagen de la cámara: la zona, la franja de advertencia y las personas.

Colores de seguridad (NTC 1461): rojo para la zona de peligro, amarillo para la franja de
advertencia y verde para quien está fuera de las dos.

Privacidad: ``imagen_para_guardar`` es el único camino por el que un fotograma sale hacia un
archivo o un evento. Primero difumina los rostros y después dibuja encima.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Mapping, Sequence

import cv2
import numpy as np

from modulos.comun import difuminar_rostros

from ..deteccion.personas import Persona, puntos_de_apoyo
from ..nucleo.estados import VistaPersona
from ..nucleo.geometria import Punto
from ..nucleo.zona import Zona
from .marca import AMARILLO, COLOR_DE_ESTADO, GRIS, NEGRO, ROJO, Color, bgr

LADO_MAXIMO_DE_TRABAJO = 900  # la franja se calcula sobre una trama de a lo sumo este tamaño
Caja = tuple[float, float, float, float]


def _enteros(puntos: Sequence[Punto] | np.ndarray) -> np.ndarray:
    return np.asarray(puntos, dtype=np.float32).round().astype(np.int32)


def _borde_a_distancia(poligono: Sequence[Punto], margen: float, ampliar: bool = False) -> np.ndarray | None:
    """Contorno de todos los puntos que están a ``margen`` o menos del polígono (N x 2, en su misma unidad).

    Vale para cualquier forma de zona: se pinta el polígono en una trama y se toma lo que queda
    a menos de ``margen`` según la transformada de distancia. La trama se reduce si la figura es
    muy grande; con ``ampliar`` también se agranda si es pequeña (para polígonos en metros).
    """
    puntos = np.asarray(poligono, dtype=np.float64)
    minimo, maximo = puntos.min(axis=0) - margen, puntos.max(axis=0) + margen
    escala = LADO_MAXIMO_DE_TRABAJO / float((maximo - minimo).max())
    if not ampliar:
        escala = min(1.0, escala)
    ancho, alto = (np.ceil((maximo - minimo) * escala).astype(int) + 3).tolist()
    trama = np.full((alto, ancho), 255, dtype=np.uint8)
    cv2.fillPoly(trama, [_enteros((puntos - minimo) * escala + 1)], 0)
    cerca = (cv2.distanceTransform(trama, cv2.DIST_L2, 5) <= margen * escala).astype(np.uint8)
    contornos, _ = cv2.findContours(cerca, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return None
    contorno = max(contornos, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    return (contorno - 1) / escala + minimo


@lru_cache(maxsize=8)
def contorno_de_franja(zona: Zona) -> np.ndarray | None:
    """Borde exterior de la franja de advertencia, en píxeles de la imagen (N x 2). None si no hay franja.

    Si la zona mide en metros, la franja se calcula sobre el piso y se lleva a la imagen: se ve
    más ancha cerca de la cámara y más angosta lejos, como es en realidad.
    """
    if zona.margen <= 0:
        return None
    if not zona.en_metros:
        return _borde_a_distancia(zona.poligono, zona.margen_px)
    en_piso = _borde_a_distancia(zona.poligono_m, zona.margen_m, ampliar=True)
    if en_piso is None:
        return None
    a_imagen = zona.homografia.inversa()
    en_imagen = [punto for punto in (a_imagen.aplicar((float(x), float(y))) for x, y in en_piso) if punto is not None]
    return np.asarray(en_imagen, dtype=np.float64) if len(en_imagen) >= 3 else None


def _mezclar(imagen: np.ndarray, poligonos: list[np.ndarray], color: Color, opacidad: float) -> None:
    """Pinta translúcido lo que encierran los polígonos (con la regla par-impar: dos anidados dan un anillo)."""
    todos = np.vstack(poligonos)
    x, y, ancho, alto = cv2.boundingRect(todos)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(imagen.shape[1], x + ancho), min(imagen.shape[0], y + alto)
    if x1 <= x0 or y1 <= y0 or opacidad <= 0:
        return
    recorte = imagen[y0:y1, x0:x1]
    capa = recorte.copy()
    cv2.fillPoly(capa, [poligono - (x0, y0) for poligono in poligonos], bgr(color))
    cv2.addWeighted(capa, opacidad, recorte, 1.0 - opacidad, 0.0, dst=recorte)


def dibujar_zona(imagen: np.ndarray, zona: Zona, estado: str = "libre") -> None:
    """Zona de peligro en rojo translúcido y franja de advertencia en amarillo. Se intensifican con el estado."""
    poligono = _enteros(zona.poligono)
    franja = contorno_de_franja(zona)
    if franja is not None:
        borde = _enteros(franja)
        _mezclar(imagen, [borde, poligono], AMARILLO, 0.32 if estado == "advertencia" else 0.16)
        cv2.polylines(imagen, [borde], True, bgr(AMARILLO), 2, cv2.LINE_AA)
    _mezclar(imagen, [poligono], ROJO, 0.5 if estado == "peligro" else 0.3)
    cv2.polylines(imagen, [poligono], True, bgr(ROJO), 3, cv2.LINE_AA)


def dibujar_persona(imagen: np.ndarray, persona: VistaPersona, caja: Caja | None = None) -> None:
    """Puntos de apoyo de la persona con el color de su estado; si se dejó de ver, solo el contorno."""
    color = COLOR_DE_ESTADO.get(persona.estado, GRIS)
    if caja is not None and persona.presente:
        x1, y1, x2, y2 = (int(round(valor)) for valor in caja)
        cv2.rectangle(imagen, (x1, y1), (x2, y2), bgr(color), 2, cv2.LINE_AA)
    for x, y in persona.puntos:
        centro = (int(round(x)), int(round(y)))
        cv2.circle(imagen, centro, 13, bgr(NEGRO), -1 if persona.presente else 3, cv2.LINE_AA)
        cv2.circle(imagen, centro, 10, bgr(color), -1 if persona.presente else 3, cv2.LINE_AA)


def dibujar_personas(imagen: np.ndarray, personas: Sequence[VistaPersona], cajas: Mapping[int, Caja] | None = None) -> None:
    for persona in personas:
        dibujar_persona(imagen, persona, (cajas or {}).get(persona.persona_id))


def dibujar_detecciones(imagen: np.ndarray, personas: Sequence[Persona], confianza_punto: float = 0.5) -> None:
    """Puntos de apoyo de las personas detectadas, en gris: se ven, pero todavía no hay zona contra la cual medirlas."""
    for persona in personas:
        for x, y in puntos_de_apoyo(persona, confianza_punto):
            centro = (int(round(x)), int(round(y)))
            cv2.circle(imagen, centro, 13, bgr(NEGRO), -1, cv2.LINE_AA)
            cv2.circle(imagen, centro, 10, bgr(GRIS), -1, cv2.LINE_AA)


def imagen_para_guardar(frame: np.ndarray, zona: Zona | None, personas: Sequence[VistaPersona] = (),
                        cajas: Mapping[int, Caja] | None = None, estado: str = "libre") -> np.ndarray:
    """La imagen que puede salir de la estación: rostros difuminados y, DESPUÉS, la zona y las personas."""
    imagen = difuminar_rostros(frame)
    if zona is not None:
        dibujar_zona(imagen, zona, estado)
    dibujar_personas(imagen, personas, cajas)
    return imagen
