"""Colores de la marca Auren y colores de seguridad de la zona. Sin dependencias.

Los colores están en RGB; ``bgr()`` los pasa al orden de OpenCV. La lima es solo acento
(máximo ~10 % de la pantalla) y nunca va como texto sobre marfil.

Excepción de marca: la alarma usa los colores de seguridad de la NTC 1461 (rojo para
peligro, amarillo para advertencia, verde para condición segura), no la lima.
"""

from __future__ import annotations

Color = tuple[int, int, int]

DEEP: Color = (0x12, 0x34, 0x3B)
NEGRO: Color = (0x11, 0x14, 0x14)
MARFIL: Color = (0xF2, 0xF1, 0xEA)
LIMA: Color = (0xC8, 0xF1, 0x69)
MARFIL_TENUE: Color = (0x9F, 0xAE, 0xAC)  # marfil apagado sobre Deep, para texto secundario
DEEP_CLARO: Color = (0x1D, 0x47, 0x50)  # líneas y separadores sobre Deep

ROJO: Color = (0xE0, 0x2B, 0x20)  # peligro
AMARILLO: Color = (0xF9, 0xC8, 0x0E)  # advertencia
VERDE: Color = (0x2E, 0xA8, 0x62)  # condición segura
GRIS: Color = (0x82, 0x8C, 0x8C)

COLOR_DE_ESTADO: dict[str, Color] = {"libre": VERDE, "advertencia": AMARILLO, "peligro": ROJO}


def bgr(color: Color) -> Color:
    return (color[2], color[1], color[0])
