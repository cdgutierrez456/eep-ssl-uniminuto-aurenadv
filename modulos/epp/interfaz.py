"""Dibujo de la estación de EPP: cajas sobre la imagen y panel lateral con marca Auren.

Colores: Auren Deep de fondo, marfil para el texto y lima solo como acento (la marca
de «cumple»). Las cajas usan verde y rojo porque son señal de seguridad, no decoración.
El panel se dibuja con Pillow (tildes y tipografía) y se guarda en caché: solo se
vuelve a pintar cuando cambia lo que muestra.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Marca Auren (RGB para Pillow)
DEEP = (0x12, 0x34, 0x3B)
NEGRO = (0x11, 0x14, 0x14)
MARFIL = (0xF2, 0xF1, 0xEA)
LIMA = (0xC8, 0xF1, 0x69)
TENUE = (0x9D, 0xAC, 0xAA)      # marfil al 60 % sobre Deep
BORDE = (0x2C, 0x4A, 0x50)
ROJO = (0xE5, 0x60, 0x4D)
VERDE = (0x4C, 0xC3, 0x8A)


def _bgr(color: tuple[int, int, int]) -> tuple[int, int, int]:
    return color[2], color[1], color[0]


ANCHO_LIENZO, ALTO_LIENZO = 1600, 900
ANCHO_PANEL = 420
ANCHO_VIDEO = ANCHO_LIENZO - ANCHO_PANEL
MARGEN = 30

_FUENTES = {
    False: ["C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"],
    True: ["C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
}
_cache_fuentes: dict[tuple[int, bool], Any] = {}


def fuente(tamano: int, negrita: bool = False):
    """Fuente del sistema (Segoe UI en Windows, DejaVu en Linux) o la de respaldo de Pillow."""
    clave = (tamano, negrita)
    if clave not in _cache_fuentes:
        for ruta in _FUENTES[negrita]:
            try:
                _cache_fuentes[clave] = ImageFont.truetype(ruta, tamano)
                break
            except OSError:
                continue
        else:
            _cache_fuentes[clave] = ImageFont.load_default(tamano)
    return _cache_fuentes[clave]


def _fuente_que_quepa(texto: str, ancho: int, tamano: int, negrita: bool = True):
    while tamano > 14 and fuente(tamano, negrita).getlength(texto) > ancho:
        tamano -= 2
    return fuente(tamano, negrita)


# --------------------------------------------------------------------------- #
# Cajas sobre la imagen
# --------------------------------------------------------------------------- #
def dibujar_cajas(frame: np.ndarray, cuadro: Any, reglas: dict[str, Any]) -> None:
    """Dibuja sobre ``frame`` (se modifica) las personas y los elementos detectados.

    La persona principal va en verde si cumple y en rojo si le falta algo; las demás,
    en gris (no cuentan). Los elementos van en verde y las clases negativas en rojo.
    En una imagen que se guarda, llamar DESPUÉS de difuminar los rostros.
    """
    alto, ancho = frame.shape[:2]
    escala = max(0.5, ancho / 1280)
    grosor = max(1, round(2 * escala))
    negativas = set(reglas["clases_negativas"].values())

    def rectangulo(caja, color, grueso, etiqueta=None):
        x1, y1, x2, y2 = (int(caja[0] * ancho), int(caja[1] * alto), int(caja[2] * ancho), int(caja[3] * alto))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, grueso, cv2.LINE_AA)
        if etiqueta:
            tamano = 0.55 * escala
            (w, h), base = cv2.getTextSize(etiqueta, cv2.FONT_HERSHEY_SIMPLEX, tamano, grosor)
            arriba = max(0, y1 - h - base - 6)
            cv2.rectangle(frame, (x1, arriba), (x1 + w + 10, arriba + h + base + 6), color, -1)
            cv2.putText(frame, etiqueta, (x1 + 5, arriba + h + 3), cv2.FONT_HERSHEY_SIMPLEX, tamano,
                        _bgr(NEGRO), grosor, cv2.LINE_AA)

    for persona in cuadro.otras:
        rectangulo(persona["caja"], _bgr(TENUE), grosor)
    if cuadro.principal is not None and not cuadro.principal.get("inferida"):
        color = _bgr(VERDE) if cuadro.principal["cumple"] else _bgr(ROJO)
        rectangulo(cuadro.principal["caja"], color, grosor * 2)
    for deteccion in cuadro.detecciones:
        clase = deteccion["clase"]
        if clase == reglas["clase_persona"]:
            continue
        color = _bgr(ROJO) if clase in negativas else _bgr(VERDE)
        rectangulo(deteccion["caja"], color, grosor, f"{clase.replace('_', ' ')} {deteccion['confianza']:.2f}")


# --------------------------------------------------------------------------- #
# Panel lateral
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EstadoPanel:
    """Todo lo que muestra el panel. Si no cambia, el panel no se vuelve a pintar."""

    perfil: str
    elementos: tuple[tuple[str, str], ...]      # (nombre visible, "si" | "no" | "pendiente")
    veredicto: str                              # "cumple" | "no_cumple" | "verificando" | "nadie"
    faltantes: tuple[str, ...] = ()
    sesion: str | None = None
    entrada: str | None = None                  # dígitos que se están tecleando, o None
    aviso: str | None = None
    fuente_config: str = "defecto"
    teclas: tuple[tuple[str, str, bool], ...] = ()   # (tecla, perfil, disponible)


_FUENTE_CONFIG = {"plataforma": "Configuración: plataforma", "cache": "Configuración: última guardada",
                  "defecto": "Configuración: por defecto", "local": "Configuración: cambiada aquí"}


def _marca(dibujo: ImageDraw.ImageDraw, x: int, y: int, estado: str) -> None:
    """Marca de 30 px: visto (lima), equis (rojo) o círculo vacío (sin evaluar)."""
    if estado == "si":
        dibujo.line([(x + 3, y + 16), (x + 11, y + 24), (x + 27, y + 6)], fill=LIMA, width=5, joint="curve")
    elif estado == "no":
        dibujo.line([(x + 5, y + 5), (x + 25, y + 25)], fill=ROJO, width=5)
        dibujo.line([(x + 25, y + 5), (x + 5, y + 25)], fill=ROJO, width=5)
    else:
        dibujo.ellipse([x + 5, y + 5, x + 25, y + 25], outline=TENUE, width=2)


class Panel:
    """Panel lateral con el perfil, los elementos requeridos y el veredicto."""

    def __init__(self, ancho: int = ANCHO_PANEL, alto: int = ALTO_LIENZO) -> None:
        self.ancho, self.alto = ancho, alto
        self._estado: EstadoPanel | None = None
        self._imagen: np.ndarray | None = None

    def imagen(self, estado: EstadoPanel) -> np.ndarray:
        if estado != self._estado or self._imagen is None:
            self._estado = estado
            self._imagen = cv2.cvtColor(np.asarray(self._pintar(estado)), cv2.COLOR_RGB2BGR)
        return self._imagen

    def _pintar(self, e: EstadoPanel) -> Image.Image:
        lienzo = Image.new("RGB", (self.ancho, self.alto), DEEP)
        d = ImageDraw.Draw(lienzo)
        x, util = MARGEN, self.ancho - 2 * MARGEN

        d.text((x, 34), "SST EN VIVO  ·  AUREN", font=fuente(15, True), fill=TENUE)
        d.text((x, 58), "Verificación de EPP", font=fuente(28, True), fill=MARFIL)
        d.line([(x, 112), (self.ancho - MARGEN, 112)], fill=BORDE, width=1)

        d.text((x, 134), "PERFIL", font=fuente(14, True), fill=TENUE)
        d.text((x, 154), e.perfil, font=_fuente_que_quepa(e.perfil, util, 36), fill=MARFIL)

        d.text((x, 232), "ELEMENTOS REQUERIDOS", font=fuente(14, True), fill=TENUE)
        y = 264
        if not e.elementos:
            d.text((x, y), "Ninguno", font=fuente(24), fill=TENUE)
        for nombre, estado in e.elementos:
            _marca(d, x, y, estado)
            d.text((x + 46, y - 3), nombre, font=_fuente_que_quepa(nombre, util - 46, 26, False), fill=MARFIL)
            y += 50

        # Veredicto
        y = max(y + 30, 540)
        if e.veredicto == "cumple":
            d.rectangle([x, y, x + 8, y + 86], fill=LIMA)
            d.text((x + 28, y - 4), "CUMPLE", font=_fuente_que_quepa("CUMPLE", util - 28, 72), fill=MARFIL)
        elif e.veredicto == "no_cumple":
            d.rectangle([x, y, self.ancho - MARGEN, y + 86], fill=ROJO)
            tipo = _fuente_que_quepa("NO CUMPLE", util - 32, 60)
            d.text((x + 16, y + 43), "NO CUMPLE", font=tipo, fill=NEGRO, anchor="lm")
            if e.faltantes:
                texto = "Falta: " + ", ".join(e.faltantes)
                d.text((x, y + 100), texto, font=_fuente_que_quepa(texto, util, 24, False), fill=MARFIL)
        elif e.veredicto == "verificando":
            d.text((x, y + 14), "Verificando…", font=fuente(40, True), fill=MARFIL)
        else:
            d.text((x, y + 6), "Acércate", font=fuente(40, True), fill=TENUE)
            d.text((x, y + 54), "a la cámara", font=fuente(40, True), fill=TENUE)

        # Visitante
        y = self.alto - 196
        d.line([(x, y - 16), (self.ancho - MARGEN, y - 16)], fill=BORDE, width=1)
        if e.entrada is not None:
            d.text((x, y), "Número de visitante:", font=fuente(18), fill=TENUE)
            d.text((x, y + 24), (e.entrada or "") + "_", font=fuente(30, True), fill=MARFIL)
            d.text((x, y + 64), "Enter confirma  ·  Esc cancela", font=fuente(15), fill=TENUE)
        else:
            d.text((x, y), "VISITANTE", font=fuente(14, True), fill=TENUE)
            d.text((x, y + 20), e.sesion or "Sin número", font=fuente(26, True), fill=MARFIL if e.sesion else TENUE)
            if e.aviso:
                d.text((x, y + 62), e.aviso, font=_fuente_que_quepa(e.aviso, util, 17, False), fill=MARFIL)

        # Pie: teclas y aviso de borrador
        y = self.alto - 98
        teclas = "   ".join(f"{t} {n}" if ok else f"{t} {n} (no disponible)" for t, n, ok in e.teclas)
        d.text((x, y), teclas, font=_fuente_que_quepa(teclas, util, 15, False), fill=TENUE)
        d.text((x, y + 22), "V visitante   F pantalla completa   Q salir", font=fuente(15), fill=TENUE)
        d.text((x, y + 48), "Borrador: validar en campo", font=fuente(15, True), fill=MARFIL)
        d.text((x, y + 68), _FUENTE_CONFIG.get(e.fuente_config, ""), font=fuente(13), fill=TENUE)
        return lienzo


# --------------------------------------------------------------------------- #
# Composición
# --------------------------------------------------------------------------- #
def componer(frame: np.ndarray | None, panel: np.ndarray, mensaje: tuple[str, str] | None = None) -> np.ndarray:
    """Lienzo completo: video a la izquierda (sin deformar) y panel a la derecha.

    Con ``mensaje`` (título, detalle) y sin frame muestra un aviso en lugar del video.
    """
    lienzo = np.empty((ALTO_LIENZO, ANCHO_LIENZO, 3), dtype=np.uint8)
    lienzo[:, :ANCHO_VIDEO] = _bgr(NEGRO)
    lienzo[:, ANCHO_VIDEO:] = panel
    if frame is not None:
        alto, ancho = frame.shape[:2]
        factor = min(ANCHO_VIDEO / ancho, ALTO_LIENZO / alto)
        nuevo = cv2.resize(frame, (int(ancho * factor), int(alto * factor)), interpolation=cv2.INTER_LINEAR)
        y = (ALTO_LIENZO - nuevo.shape[0]) // 2
        x = (ANCHO_VIDEO - nuevo.shape[1]) // 2
        lienzo[y:y + nuevo.shape[0], x:x + nuevo.shape[1]] = nuevo
    elif mensaje:
        aviso = Image.new("RGB", (ANCHO_VIDEO, ALTO_LIENZO), NEGRO)
        d = ImageDraw.Draw(aviso)
        d.text((ANCHO_VIDEO // 2, ALTO_LIENZO // 2 - 30), mensaje[0], font=fuente(44, True), fill=MARFIL, anchor="mm")
        d.text((ANCHO_VIDEO // 2, ALTO_LIENZO // 2 + 30), mensaje[1], font=fuente(22), fill=TENUE, anchor="mm")
        lienzo[:, :ANCHO_VIDEO] = cv2.cvtColor(np.asarray(aviso), cv2.COLOR_RGB2BGR)
    return lienzo


def guardar_foto(ruta: Path, frame: np.ndarray) -> None:
    """Escribe el frame como JPG (admite rutas con tildes en Windows)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    correcto, datos = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not correcto:
        raise OSError(f"No se pudo codificar la imagen {ruta.name}")
    ruta.write_bytes(datos.tobytes())
