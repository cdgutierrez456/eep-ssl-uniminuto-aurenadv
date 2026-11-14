"""Dibujo del esqueleto sobre el fotograma, con cada segmento coloreado por su riesgo.

Regla de privacidad: sobre la vista en vivo se dibuja directo. Para una imagen que se va a
guardar o enviar se usa ``imagen_para_guardar``, que difumina los rostros **antes** de dibujar.
"""

from __future__ import annotations

from typing import Mapping

import cv2
import numpy as np

from modulos.comun.rostros import difuminar_rostros

from ..nucleo.angulos import Punto
from . import marca

# Tramos que forman cada segmento REBA (nombres de puntos sin el sufijo del lado)
TRAMOS: dict[str, tuple[tuple[str, str], ...]] = {
    "tronco": (("cadera", "hombro"),),
    "cuello": (("hombro", "oreja"),),
    "piernas": (("cadera", "rodilla"), ("rodilla", "tobillo")),
    "brazo": (("hombro", "codo"),),
    "antebrazo": (("codo", "muneca"),),
    "muneca": (("muneca", "mano"),),
}
# Articulación junto a la que se escribe el ángulo de cada segmento
ANCLA_DE_ANGULO = {"tronco": "cadera", "cuello": "hombro", "piernas": "rodilla",
                   "brazo": "codo", "antebrazo": "muneca"}
VISIBILIDAD_MINIMA_PARA_DIBUJAR = 0.15


def _puntos_del_lado(puntos: Mapping[str, Punto], lado: str) -> dict[str, Punto]:
    """Puntos del lado evaluado, sin sufijo, más ``mano`` (punto medio de índice y meñique)."""
    sufijo = f"_{lado}"
    del_lado = {n.removesuffix(sufijo): p for n, p in puntos.items() if n.endswith(sufijo)}
    indice, menique = del_lado.get("indice"), del_lado.get("menique")
    if indice is not None and menique is not None:
        del_lado["mano"] = Punto((indice.x + menique.x) / 2, (indice.y + menique.y) / 2,
                                 min(indice.visibilidad, menique.visibilidad))
    return del_lado


def dibujar_esqueleto(frame: np.ndarray, puntos: Mapping[str, Punto], lado: str,
                      segmentos: Mapping[str, int | None], angulos: Mapping[str, float | None] | None = None) -> None:
    """Dibuja sobre ``frame`` (lo modifica) el esqueleto del lado evaluado.

    Cada segmento va en verde, amarillo o rojo según su puntaje, y en gris si no se pudo
    estimar. Junto a cada articulación va su ángulo en grados.
    """
    alto = frame.shape[0]
    grosor = max(3, round(alto / 120))
    del_lado = _puntos_del_lado(puntos, lado)

    def pixel(nombre: str) -> tuple[int, int] | None:
        punto = del_lado.get(nombre)
        if punto is None or punto.visibilidad < VISIBILIDAD_MINIMA_PARA_DIBUJAR:
            return None
        return int(round(punto.x)), int(round(punto.y))

    tramos = []
    for segmento, pares in TRAMOS.items():
        puntaje = segmentos.get(segmento)
        color = marca.bgr(marca.color_de_segmento(puntaje))
        for desde, hasta in pares:
            a, b = pixel(desde), pixel(hasta)
            if a is not None and b is not None:
                tramos.append((a, b, color, grosor if puntaje is not None else max(2, grosor // 2)))
    # Primero el borde oscuro de todos los tramos y luego el color, para que no se tapen
    for a, b, _, ancho in tramos:
        cv2.line(frame, a, b, marca.bgr(marca.NEGRO), ancho + 4, cv2.LINE_AA)
    for a, b, color, ancho in tramos:
        cv2.line(frame, a, b, color, ancho, cv2.LINE_AA)
    for nombre in ("oreja", "hombro", "codo", "muneca", "cadera", "rodilla", "tobillo"):
        centro = pixel(nombre)
        if centro is not None:
            cv2.circle(frame, centro, grosor + 2, marca.bgr(marca.NEGRO), -1, cv2.LINE_AA)
            cv2.circle(frame, centro, grosor, marca.bgr(marca.MARFIL), -1, cv2.LINE_AA)

    if angulos:
        escala = alto / 900
        for segmento, ancla in ANCLA_DE_ANGULO.items():
            valor, centro = angulos.get(segmento), pixel(ancla)
            if valor is None or centro is None or segmentos.get(segmento) is None:
                continue
            texto = f"{valor:.0f}"
            posicion = (centro[0] + grosor * 3, centro[1] - grosor * 2)
            cv2.putText(frame, texto, posicion, cv2.FONT_HERSHEY_SIMPLEX, escala, marca.bgr(marca.NEGRO),
                        max(4, round(5 * escala)), cv2.LINE_AA)
            cv2.putText(frame, texto, posicion, cv2.FONT_HERSHEY_SIMPLEX, escala, marca.bgr(marca.MARFIL),
                        max(1, round(2 * escala)), cv2.LINE_AA)


def imagen_para_guardar(frame: np.ndarray, puntos: Mapping[str, Punto] | None, lado: str,
                        segmentos: Mapping[str, int | None],
                        angulos: Mapping[str, float | None] | None = None) -> np.ndarray:
    """Copia del fotograma lista para guardar o enviar: rostros difuminados y, después, el esqueleto."""
    imagen = difuminar_rostros(frame)
    if puntos:
        dibujar_esqueleto(imagen, puntos, lado, segmentos, angulos)
    return imagen
