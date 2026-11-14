"""Colores de la marca Auren y de los niveles de riesgo. Sin dependencias.

Los colores están en RGB; ``bgr()`` los pasa al orden de OpenCV. La lima es solo acento
(máximo ~10 % de la pantalla) y nunca va como texto sobre marfil.
"""

from __future__ import annotations

Color = tuple[int, int, int]

DEEP: Color = (0x12, 0x34, 0x3B)
NEGRO: Color = (0x11, 0x14, 0x14)
MARFIL: Color = (0xF2, 0xF1, 0xEA)
LIMA: Color = (0xC8, 0xF1, 0x69)
MARFIL_TENUE: Color = (0x9F, 0xAE, 0xAC)  # marfil apagado sobre Deep, para texto secundario
DEEP_CLARO: Color = (0x1D, 0x47, 0x50)  # líneas y separadores sobre Deep

VERDE: Color = (0x58, 0xC4, 0x78)
AMARILLO: Color = (0xF0, 0xC4, 0x3C)
NARANJA: Color = (0xF0, 0x8C, 0x32)
ROJO: Color = (0xE4, 0x54, 0x46)
GRIS: Color = (0x82, 0x8C, 0x8C)

COLOR_DE_NIVEL: dict[str, Color] = {
    "insignificante": VERDE,
    "bajo": VERDE,
    "medio": AMARILLO,
    "alto": NARANJA,
    "muy_alto": ROJO,
}

NOMBRE_DE_NIVEL: dict[str, str] = {
    "insignificante": "Riesgo insignificante",
    "bajo": "Riesgo bajo",
    "medio": "Riesgo medio",
    "alto": "Riesgo alto",
    "muy_alto": "Riesgo muy alto",
}

NOMBRE_DE_SEGMENTO: dict[str, str] = {
    "tronco": "Tronco",
    "cuello": "Cuello",
    "piernas": "Piernas",
    "brazo": "Brazo",
    "antebrazo": "Antebrazo",
    "muneca": "Muñeca",
}


COLOR_DE_ESPALDA: dict[str, Color] = {"baja": VERDE, "media": AMARILLO, "alta": ROJO}


def color_de_segmento(puntaje: int | None) -> Color:
    """Color de un segmento por su puntaje REBA: 1 verde, 2 amarillo, 3 naranja, 4 o más rojo;
    sin estimar, gris."""
    if puntaje is None:
        return GRIS
    return VERDE if puntaje <= 1 else AMARILLO if puntaje == 2 else NARANJA if puntaje == 3 else ROJO


def color_de_piernas(bien: bool | None) -> Color:
    """Color del uso de las piernas en la técnica: bien verde, mal rojo, intermedio amarillo."""
    return AMARILLO if bien is None else VERDE if bien else ROJO


def bgr(color: Color) -> Color:
    return (color[2], color[1], color[0])
