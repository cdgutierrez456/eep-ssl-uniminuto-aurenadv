"""Piezas simuladas para probar la estación sin cámara ni modelo: un detector con guion y un video sintético."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from modulos.zona.deteccion.personas import Persona

ANCHO, ALTO, FPS = 640, 360, 30


def persona_en(persona_id: int | None, x: float, y: float, confianza_tobillos: float = 0.9) -> Persona:
    """Una persona de pie con los tobillos en (x ± 6, y) y una caja de 60 x 180 píxeles sobre ellos."""
    puntos = [(0.0, 0.0, 0.0)] * 17
    puntos[15] = (x - 6.0, y, confianza_tobillos)
    puntos[16] = (x + 6.0, y, confianza_tobillos)
    return Persona(persona_id, (x - 30.0, y - 175.0, x + 30.0, y + 5.0), 0.9, tuple(puntos))


class DetectorSimulado:
    """Detector con guion: en cada llamada devuelve a las personas que le tocan a ese fotograma.

    ``recorridos`` trae, por id de persona, su posición (x, y) en cada fotograma, o None si
    en ese fotograma no se ve.
    """

    descripcion = "detector simulado"

    def __init__(self, recorridos: dict[int, list[tuple[float, float] | None]]) -> None:
        self.recorridos = recorridos
        self.cuadro = 0
        self.confianzas: list[float] = []
        self.cerrado = False

    def detectar(self, frame: np.ndarray, confianza: float) -> list[Persona]:
        personas = [persona_en(persona_id, *recorrido[self.cuadro])
                    for persona_id, recorrido in self.recorridos.items()
                    if self.cuadro < len(recorrido) and recorrido[self.cuadro] is not None]
        self.cuadro += 1
        self.confianzas.append(confianza)
        return personas

    def cerrar(self) -> None:
        self.cerrado = True


def quieto(punto, segundos):
    return [punto] * round(segundos * FPS)


def tramo(desde, hasta, segundos):
    pasos = round(segundos * FPS)
    return [(desde[0] + (hasta[0] - desde[0]) * i / pasos, desde[1] + (hasta[1] - desde[1]) * i / pasos)
            for i in range(1, pasos + 1)]


def ausente(segundos):
    return [None] * round(segundos * FPS)


def escribir_video(ruta: Path, cuadros: int, ancho: int = ANCHO, alto: int = ALTO, fps: int = FPS) -> Path:
    """Video sintético: un piso gris con el número de fotograma codificado en el brillo (sin personas ni rostros)."""
    escritor = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"mp4v"), fps, (ancho, alto))
    assert escritor.isOpened(), "OpenCV no pudo crear el video de prueba"
    for i in range(cuadros):
        escritor.write(np.full((alto, ancho, 3), 60 + i % 120, dtype=np.uint8))
    escritor.release()
    return ruta
