"""Texto con tildes sobre imágenes de OpenCV.

``cv2.putText`` no sabe escribir á, é, ñ ni ¿: el texto se dibuja con Pillow sobre el
recorte de la imagen que ocupa, con la fuente del sistema (Segoe UI en Windows, DejaVu en
Linux) o la de respaldo de Pillow.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .marca import MARFIL, Color

_cache: dict[tuple[int, bool], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _rutas_de_fuente(negrita: bool) -> list[Path]:
    if sys.platform == "win32":
        nombres = ("segoeuib.ttf", "arialbd.ttf") if negrita else ("segoeui.ttf", "arial.ttf")
        return [Path("C:/Windows/Fonts") / nombre for nombre in nombres]
    nombres = (("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf") if negrita
               else ("DejaVuSans.ttf", "LiberationSans-Regular.ttf"))
    carpetas = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/TTF")
    return [Path(carpeta) / nombre for carpeta in carpetas for nombre in nombres]


def fuente(tamano: int, negrita: bool = False):
    """Fuente del sistema en ese tamaño; se carga una sola vez."""
    clave = (tamano, negrita)
    if clave not in _cache:
        for ruta in _rutas_de_fuente(negrita):
            try:
                _cache[clave] = ImageFont.truetype(str(ruta), tamano)
                break
            except OSError:
                continue
        else:
            _cache[clave] = ImageFont.load_default(tamano)
    return _cache[clave]


def medir(texto: str, tamano: int, negrita: bool = False) -> tuple[int, int]:
    """Ancho y alto en píxeles que ocupa el texto."""
    izquierda, arriba, derecha, abajo = fuente(tamano, negrita).getbbox(texto)
    return derecha - izquierda, abajo - arriba


def escribir(imagen: np.ndarray, texto: str, x: int, y: int, tamano: int = 24, color: Color = MARFIL,
             negrita: bool = False, fondo: Color | None = None, relleno: int = 6) -> tuple[int, int]:
    """Escribe ``texto`` sobre la imagen BGR con su esquina superior izquierda en (x, y).

    ``color`` y ``fondo`` van en RGB. Con ``fondo`` pinta un recuadro detrás, con ``relleno``
    píxeles de aire. Modifica la imagen y devuelve el ancho y el alto de lo que ocupó.
    """
    if not texto:
        return 0, 0
    tipo = fuente(tamano, negrita)
    izquierda, arriba, derecha, abajo = tipo.getbbox(texto)
    aire = relleno if fondo is not None else 0
    ancho, alto = derecha - izquierda + 2 * aire, abajo - arriba + 2 * aire
    alto_imagen, ancho_imagen = imagen.shape[:2]
    x0, y0 = max(0, min(int(x), ancho_imagen - 1)), max(0, min(int(y), alto_imagen - 1))
    x1, y1 = min(ancho_imagen, x0 + ancho), min(alto_imagen, y0 + alto)
    if x1 <= x0 or y1 <= y0:
        return 0, 0
    recorte = Image.fromarray(imagen[y0:y1, x0:x1, ::-1])  # BGR → RGB
    dibujo = ImageDraw.Draw(recorte)
    if fondo is not None:
        dibujo.rectangle((0, 0, recorte.width, recorte.height), fill=fondo)
    dibujo.text((aire - izquierda, aire - arriba), texto, font=tipo, fill=color)
    imagen[y0:y1, x0:x1] = np.asarray(recorte)[:, :, ::-1]
    return ancho, alto
