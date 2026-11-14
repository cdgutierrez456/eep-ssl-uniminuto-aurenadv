"""Genera la matriz IPEVR y la foto anotada de ejemplo, sin IA y sin internet.

    python -m modulos.inspector.ejemplo

Usa una escena dibujada (no es una foto real) y los datos de ``ejemplos/``: sirve para
ver el Excel y la anotación tal como salen del núcleo. Deja los archivos en
CARPETA_COLA/inspector/ejemplo/.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from modulos.comun import difuminar_rostros
from modulos.comun.config import leer_entorno

from .nucleo.esquema import normalizar_analisis
from .nucleo.excel import generar_excel
from .nucleo.imagen import anotar, guardar_jpeg
from .nucleo.matriz import valorar_peligros

CARPETA_EJEMPLOS = Path(__file__).resolve().parent / "ejemplos"
ANCHO, ALTO = 1568, 1176


def leer_ejemplo(nombre: str) -> dict:
    """Lee un JSON de la carpeta ``ejemplos/``."""
    return json.loads((CARPETA_EJEMPLOS / nombre).read_text(encoding="utf-8"))


def escena_dibujada() -> np.ndarray:
    """Bodega esquemática de 1568 x 1176 px que coincide con las cajas de ``analisis_bodega.json``."""
    pared, piso, metal, carton, borde = (203, 208, 206), (150, 156, 154), (96, 92, 84), (120, 165, 198), (60, 62, 60)
    frame = np.full((ALTO, ANCHO, 3), pared, np.uint8)
    cv2.rectangle(frame, (0, 830), (ANCHO, ALTO), piso, cv2.FILLED)

    # Estantería a la izquierda, con cajas que sobresalen arriba
    for x in (80, 510):
        cv2.rectangle(frame, (x, 180), (x + 14, 860), metal, cv2.FILLED)
    for y in (200, 420, 640, 846):
        cv2.rectangle(frame, (80, y), (524, y + 14), metal, cv2.FILLED)
    for x, y, ancho, alto in ((110, 96, 130, 104), (236, 84, 120, 116), (352, 100, 140, 100),
                              (120, 320, 150, 100), (300, 300, 170, 120), (130, 540, 180, 100), (340, 530, 140, 110)):
        cv2.rectangle(frame, (x, y), (x + ancho, y + alto), carton, cv2.FILLED)
        cv2.rectangle(frame, (x, y), (x + ancho, y + alto), borde, 2)

    # Escalera de tijera con una persona que levanta una caja sobre la cabeza
    cv2.line(frame, (780, 330), (670, 940), metal, 12)
    cv2.line(frame, (780, 330), (890, 940), metal, 12)
    for paso in range(1, 6):
        y = 330 + paso * 100
        mitad = 18 * paso
        cv2.line(frame, (780 - mitad, y), (780 + mitad, y), metal, 8)
    cv2.rectangle(frame, (740, 300), (826, 560), (88, 70, 52), cv2.FILLED)      # cuerpo
    cv2.circle(frame, (783, 262), 34, (150, 170, 196), cv2.FILLED)              # cabeza
    cv2.line(frame, (750, 320), (730, 200), (88, 70, 52), 18)                   # brazos arriba
    cv2.line(frame, (816, 320), (850, 200), (88, 70, 52), 18)
    cv2.rectangle(frame, (712, 112), (872, 204), carton, cv2.FILLED)
    cv2.rectangle(frame, (712, 112), (872, 204), borde, 2)

    # Cables sueltos sobre el piso del pasillo
    for desfase, color in ((0, (40, 40, 44)), (26, (30, 60, 150))):
        puntos = [(x, int(1030 + desfase + 34 * np.sin(x / 70))) for x in range(430, 1160, 10)]
        cv2.polylines(frame, [np.array(puntos, np.int32)], False, color, 7, cv2.LINE_AA)

    # Extintor de pared tapado por cajas
    cv2.rectangle(frame, (1320, 520), (1410, 560), (60, 60, 190), cv2.FILLED)
    cv2.rectangle(frame, (1340, 560), (1392, 720), (50, 50, 200), cv2.FILLED)
    for x, y, ancho, alto in ((1235, 690, 150, 210), (1370, 640, 135, 260)):
        cv2.rectangle(frame, (x, y), (x + ancho, y + alto), carton, cv2.FILLED)
        cv2.rectangle(frame, (x, y), (x + ancho, y + alto), borde, 2)

    # Mancha en el piso (el peligro dudoso)
    cv2.ellipse(frame, (1085, 920), (110, 34), 0, 0, 360, (176, 182, 180), cv2.FILLED)

    cv2.putText(frame, "Escena de ejemplo (dibujada)", (1010, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (90, 94, 92), 2,
                cv2.LINE_AA)
    return frame


def generar_ejemplo(carpeta: str | Path | None = None, fecha: datetime | None = None) -> dict[str, Path]:
    """Genera la foto anotada y el Excel de ejemplo. Devuelve sus rutas."""
    carpeta = Path(carpeta) if carpeta else leer_entorno().carpeta_cola / "inspector" / "ejemplo"
    analisis = normalizar_analisis(leer_ejemplo("analisis_bodega.json"), ANCHO, ALTO)
    respuestas = leer_ejemplo("respuestas_bodega.json")
    valorados = valorar_peligros(analisis["peligros"], respuestas["peligros"])

    # Siempre en este orden: primero difuminar, después dibujar las cajas
    anotada = anotar(difuminar_rostros(escena_dibujada()), valorados)
    ruta_imagen = guardar_jpeg(anotada, carpeta / "foto_anotada_ejemplo.jpg")
    ruta_excel = generar_excel(
        carpeta / "matriz_ipevr_ejemplo.xlsx",
        valorados,
        descripcion_general=analisis["descripcion_general"],
        advertencias=analisis["advertencias"],
        contexto=respuestas["contexto"],
        imagen=anotada,
        fecha=fecha,
        inspeccion_id="ejemplo",
    )
    return {"imagen": ruta_imagen, "excel": ruta_excel}


if __name__ == "__main__":
    for nombre, ruta in generar_ejemplo().items():
        print(f"{nombre}: {ruta.resolve()}")
