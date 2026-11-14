"""Panel lateral con la marca Auren y composición de la pantalla completa.

El texto se dibuja con Pillow y no con OpenCV porque las fuentes de OpenCV no tienen
tildes ni eñes. El panel solo se vuelve a dibujar cuando cambia lo que muestra.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..nucleo.angulos import AngulosCuerpo
from ..nucleo.mensajes import linea_fija, mensaje_de_puntaje
from ..nucleo.reba import SEGMENTOS, ResultadoReba
from ..nucleo.tecnica import Tecnica
from . import marca

ANCHO_PANEL_BASE = 560  # píxeles del panel en una pantalla de 1080 de alto
ALTO_FRANJA_BASE = 157  # franjas sobre y bajo el video: lo que sobra de un video 16:9
INSTRUCCION_POR_DEFECTO = "Levanta la caja del piso a la mesa"


def _rutas_de_fuente(negrita: bool) -> list[Path]:
    if sys.platform == "win32":
        carpeta = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        nombres = ("segoeuib.ttf", "arialbd.ttf") if negrita else ("segoeui.ttf", "arial.ttf")
        return [carpeta / nombre for nombre in nombres]
    nombres = ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf") if negrita else ("DejaVuSans.ttf", "LiberationSans-Regular.ttf")
    carpetas = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation",
                "/usr/share/fonts/TTF", "/usr/share/fonts/dejavu", "/Library/Fonts")
    return [Path(carpeta) / nombre for carpeta in carpetas for nombre in nombres]


def cargar_fuente(tamano: int, negrita: bool = False) -> ImageFont.ImageFont:
    """Fuente sin serifas del sistema; si no hay ninguna, la que trae Pillow (también con tildes)."""
    for ruta in _rutas_de_fuente(negrita):
        if ruta.is_file():
            try:
                return ImageFont.truetype(str(ruta), tamano)
            except OSError:
                continue
    return ImageFont.load_default(tamano)


@dataclass
class EstadoPanel:
    """Todo lo que el panel muestra en un momento dado."""

    resultado: ResultadoReba | None = None
    angulos: AngulosCuerpo | None = None
    hay_persona: bool = False
    config: dict[str, Any] = field(default_factory=dict)
    instruccion: str = INSTRUCCION_POR_DEFECTO
    aviso: str | None = None  # por ejemplo "Cámara desconectada, reconectando…"
    fuente: str = ""  # "Cámara 1", "Video"…
    fps: float = 0.0
    # Franja sobre el video: visitante e intento a la izquierda, estado a la derecha
    superior: tuple[str, str] = ("", "")
    # Franja bajo el video: resultado o comparación de intentos, y debajo los segmentos que cambiaron
    inferior: tuple[str, str, str] = ("", "", "")
    neutra: tuple[float, float] | None = None  # (tronco, cuello) neutros de la persona; None = sin calibrar
    color_inferior: tuple[int, int, int] | None = None  # color del acento de la franja inferior (RGB)
    titulo_reba: str = "Puntaje REBA"  # "Resultado del intento N" mientras se muestra un intento terminado
    tecnica: Tecnica | None = None  # espalda y rodillas a mostrar; None = las del fotograma en vivo
    pista: str | None = None  # pista contextual tras un intento; va después de las correcciones
    qr_url: str | None = None  # dirección del pasaporte del visitante; None = sin QR

    def clave(self) -> tuple:
        """Resumen de lo visible, redondeado: si no cambia, no hace falta volver a dibujar."""
        r, a = self.resultado, self.angulos
        return (
            self.hay_persona, self.instruccion, self.aviso, self.fuente, round(self.fps),
            None if a is None else (a.lado, tuple(None if v is None else round(v) for v in a.como_dict().values())),
            None if r is None else (r.puntaje, tuple(r.segmentos.values()), r.carga, r.agarre, r.actividad,
                                    r.ajustes_aplicados, r.asumidos),
            self.config.get("peso_carga_kg"), self.config.get("agarre"),
            None if self.neutra is None else tuple(round(v) for v in self.neutra),
            self.titulo_reba, self.pista,
            None if self.tecnica is None else (self.tecnica.texto_espalda(), self.tecnica.texto_piernas()),
        )

    def clave_franjas(self) -> tuple:
        return (self.superior, self.inferior, self.color_inferior, self.qr_url)


class Panel:
    """Dibuja el panel lateral. ``render`` devuelve una imagen BGR de ``ancho`` x ``alto``."""

    def __init__(self, ancho: int, alto: int) -> None:
        self.ancho, self.alto = ancho, alto
        self.e = alto / 1080  # escala respecto al diseño base
        self._fuentes: dict[tuple[int, bool], ImageFont.ImageFont] = {}
        self._clave: tuple | None = None
        self._imagen: np.ndarray | None = None

    def _f(self, tamano: int, negrita: bool = False) -> ImageFont.ImageFont:
        llave = (tamano, negrita)
        if llave not in self._fuentes:
            self._fuentes[llave] = cargar_fuente(max(8, round(tamano * self.e)), negrita)
        return self._fuentes[llave]

    def _p(self, valor: float) -> int:
        return round(valor * self.e)

    def render(self, estado: EstadoPanel) -> np.ndarray:
        clave = estado.clave()
        if clave != self._clave or self._imagen is None:
            self._imagen = cv2.cvtColor(np.asarray(self._dibujar(estado)), cv2.COLOR_RGB2BGR)
            self._clave = clave
        return self._imagen

    # ------------------------------------------------------------------ #
    def _dibujar(self, estado: EstadoPanel) -> Image.Image:
        p, f = self._p, self._f
        imagen = Image.new("RGB", (self.ancho, self.alto), marca.DEEP)
        d = ImageDraw.Draw(imagen)
        margen = p(36)
        derecha = self.ancho - margen
        r = estado.resultado

        # Encabezado: la lima solo como acento
        d.rectangle((margen, p(40), margen + p(6), p(68)), fill=marca.LIMA)
        d.text((margen + p(20), p(54)), "ERGONOMÍA · REBA", font=f(22, True), fill=marca.MARFIL, anchor="lm")
        if estado.fuente:
            d.text((derecha, p(54)), estado.fuente, font=f(16), fill=marca.MARFIL_TENUE, anchor="rm")

        # 1. REBA: el puntaje y lo que el método dice de la postura. El mensaje habla de la
        # tarea, no de la persona, y por eso va en marfil; el color queda solo en el distintivo.
        d.text((margen, p(100)), estado.titulo_reba, font=f(18), fill=marca.MARFIL_TENUE, anchor="lm")
        if estado.angulos is not None:
            d.text((derecha, p(100)), f"Lado {estado.angulos.lado}", font=f(15), fill=marca.MARFIL_TENUE, anchor="rm")
        if r is not None and r.completo:
            mensaje = mensaje_de_puntaje(r.puntaje)
            numero = str(r.puntaje)
            d.text((margen, p(160)), numero, font=f(104, True), fill=marca.MARFIL, anchor="lm")
            x = margen + d.textlength(numero, font=f(104, True)) + p(22)
            lineas = self._partir(d, mensaje.panel, f(18), derecha - x)[:4]
            arriba = p(160) - (len(lineas) - 1) * p(12)
            for i, linea in enumerate(lineas):
                d.text((x, arriba + i * p(24)), linea, font=f(18), fill=marca.MARFIL, anchor="lm")
            ancho_texto = d.textlength(mensaje.etiqueta, font=f(21, True))
            d.rounded_rectangle((margen, p(212), margen + ancho_texto + p(32), p(252)), radius=p(20),
                                fill=marca.COLOR_DE_NIVEL[r.nivel])
            d.text((margen + p(16), p(232)), mensaje.etiqueta, font=f(21, True), fill=marca.NEGRO, anchor="lm")
        else:
            d.text((margen, p(160)), "—", font=f(104, True), fill=marca.MARFIL_TENUE, anchor="lm")
            if not estado.hay_persona:
                motivo = ["Ubícate de lado,", "con el cuerpo completo en cuadro"]
            else:
                faltan = ", ".join(marca.NOMBRE_DE_SEGMENTO[s].lower() for s in (r.no_estimados if r else ()))
                motivo = ["No se ve el cuerpo completo", f"Falta: {faltan}" if faltan else ""]
            for i, linea in enumerate(motivo):
                d.text((margen + p(110), p(148 + i * 26)), linea, font=f(18), fill=marca.MARFIL, anchor="lm")
        # Línea fija, siempre visible bajo el puntaje: qué es y qué no es REBA
        for i, linea in enumerate(self._partir(d, linea_fija(), f(14), derecha - margen)[:2]):
            d.text((margen, p(274 + i * 19)), linea, font=f(14), fill=marca.MARFIL_TENUE, anchor="lm")

        # 2. Técnica de levantamiento: espalda y rodillas, lo que el visitante sí puede cambiar
        y = p(310)
        d.line((margen, y, derecha, y), fill=marca.DEEP_CLARO, width=max(1, p(2)))
        tecnica = estado.tecnica or self._tecnica(estado)
        if tecnica is not None:
            filas = [(marca.COLOR_DE_ESPALDA[tecnica.nivel], f"Flexión de espalda {tecnica.texto_espalda()}"),
                     (marca.GRIS if tecnica.rodillas is None else marca.color_de_piernas(tecnica.piernas_bien),
                      tecnica.texto_piernas())]
        else:
            filas = [(marca.GRIS, "Flexión de espalda: no estimada"), (marca.GRIS, "Rodillas: no estimadas")]
        for i, (color, texto) in enumerate(filas):
            cy, radio = p(336 + i * 28), p(7)
            d.ellipse((margen, cy - radio, margen + 2 * radio, cy + radio), fill=color)
            d.text((margen + p(26), cy), texto, font=f(19),
                   fill=marca.MARFIL if tecnica is not None else marca.MARFIL_TENUE, anchor="lm")

        # 3. Tabla de segmentos REBA
        y = p(392)
        d.line((margen, y, derecha, y), fill=marca.DEEP_CLARO, width=max(1, p(2)))
        x_angulo, x_puntaje = self.ancho - p(170), derecha - p(24)
        d.text((margen, y + p(22)), "Segmento", font=f(15), fill=marca.MARFIL_TENUE, anchor="lm")
        d.text((x_angulo, y + p(22)), "Ángulo", font=f(15), fill=marca.MARFIL_TENUE, anchor="rm")
        d.text((x_puntaje, y + p(22)), "Puntaje", font=f(15), fill=marca.MARFIL_TENUE, anchor="mm")
        angulos = estado.angulos.como_dict() if estado.angulos is not None else {}
        for i, segmento in enumerate(SEGMENTOS):
            cy = y + p(58 + i * 46)
            puntaje = r.segmentos.get(segmento) if r is not None else None
            angulo = angulos.get(segmento)
            estimado = puntaje is not None
            d.text((margen, cy), marca.NOMBRE_DE_SEGMENTO[segmento], font=f(23),
                   fill=marca.MARFIL if estimado else marca.MARFIL_TENUE, anchor="lm")
            nota = None
            if not estimado and estado.hay_persona:
                nota = "no estimado"
            elif segmento == "muneca" and estimado:
                nota = "estimación de baja confianza"
            if nota:
                d.text((margen, cy + p(20)), nota, font=f(12), fill=marca.MARFIL_TENUE, anchor="lm")
            d.text((x_angulo, cy), f"{angulo:.0f}°" if estimado and angulo is not None else "—",
                   font=f(23), fill=marca.MARFIL if estimado else marca.MARFIL_TENUE, anchor="rm")
            radio = p(19)
            d.ellipse((x_puntaje - radio, cy - radio, x_puntaje + radio, cy + radio),
                      fill=marca.color_de_segmento(puntaje))
            d.text((x_puntaje, cy), str(puntaje) if estimado else "–", font=f(21, True), fill=marca.NEGRO, anchor="mm")

        # 4. Condiciones de la tarea y lo que no se evalúa
        y = y + p(58 + len(SEGMENTOS) * 46) - p(16)
        d.line((margen, y, derecha, y), fill=marca.DEEP_CLARO, width=max(1, p(2)))
        peso, agarre = estado.config.get("peso_carga_kg"), estado.config.get("agarre")
        if peso is not None and agarre is not None:
            texto = f"Carga {peso:g} kg · Agarre {agarre}"
            if r is not None:
                texto = f"Carga {peso:g} kg (+{r.carga}) · Agarre {agarre} (+{r.agarre})"
            d.text((margen, y + p(24)), texto, font=f(18), fill=marca.MARFIL, anchor="lm")
        notas = []
        if r is not None and (r.segmentos.get("piernas") or 0) >= 3:
            notas.append("REBA suma 2 a las piernas por rodillas a más de 60°")
        notas.append("Torsión e inclinación lateral: no evaluado")
        if estado.neutra is not None:
            notas.append(f"Postura neutra de pie: tronco {estado.neutra[0]:.0f}°, cuello {estado.neutra[1]:.0f}°")
        elif estado.hay_persona and estado.config.get("postura_neutra", True):
            notas.append("Postura neutra sin calibrar: ángulos sin corregir")
        if r is not None and r.ajustes_aplicados:
            notas.append("Brazo −1: persona inclinada, brazo a favor de gravedad")
        if r is not None and r.completo and "muneca" in r.asumidos:
            notas.append("Muñeca no estimada: se asume el mínimo (1)")
        for i, nota in enumerate(notas[:5]):
            d.text((margen, y + p(48 + i * 19)), nota, font=f(14), fill=marca.MARFIL_TENUE, anchor="lm")

        # Instrucción o aviso. Tras un intento: primero las correcciones y, si cabe, la pista.
        arriba, abajo = self.alto - p(226), self.alto - p(76)
        d.rounded_rectangle((margen, arriba, derecha, abajo), radius=p(14), fill=marca.NEGRO)
        es_aviso = bool(estado.aviso)
        d.rectangle((margen, arriba + p(18), margen + p(6), abajo - p(18)),
                    fill=marca.AMARILLO if es_aviso else marca.LIMA)
        x_texto, ancho_texto = margen + p(30), derecha - margen - p(56)
        principal = estado.aviso or estado.instruccion
        pista = None if es_aviso else estado.pista
        if pista:
            principales = self._partir(d, principal, f(22, True), ancho_texto)
            secundarias = self._partir(d, pista, f(16), ancho_texto)
            alto_total = len(principales) * p(28) + p(8) + len(secundarias) * p(21)
            if alto_total > (abajo - arriba) - p(20):
                pista = None  # no cabe todo: mandan las correcciones
        if pista:
            tope = (arriba + abajo) / 2 - alto_total / 2
            for i, linea in enumerate(principales):
                d.text((x_texto, tope + p(14) + i * p(28)), linea, font=f(22, True), fill=marca.MARFIL, anchor="lm")
            tope += len(principales) * p(28) + p(8)
            for i, linea in enumerate(secundarias):
                d.text((x_texto, tope + p(10) + i * p(21)), linea, font=f(16), fill=marca.MARFIL, anchor="lm")
        else:
            lineas = self._partir(d, principal, f(25, True), ancho_texto)[:4]
            centro = (arriba + abajo) / 2 - (len(lineas) - 1) * p(16)
            for i, linea in enumerate(lineas):
                d.text((x_texto, centro + i * p(32)), linea, font=f(25, True),
                       fill=marca.AMARILLO if es_aviso else marca.MARFIL, anchor="lm")

        # Pie: todo resultado es un borrador
        d.text((margen, self.alto - p(40)), "Borrador — validar en campo", font=f(16), fill=marca.MARFIL_TENUE, anchor="lm")
        if estado.fps:
            d.text((derecha, self.alto - p(40)), f"{estado.fps:.0f} fps", font=f(16), fill=marca.MARFIL_TENUE, anchor="rm")
        return imagen

    @staticmethod
    def _tecnica(estado: EstadoPanel) -> Tecnica | None:
        """Espalda y rodillas del fotograma en vivo; None si no se ve el tronco."""
        if estado.angulos is None or estado.angulos.tronco is None:
            return None
        return Tecnica(estado.angulos.tronco, estado.angulos.piernas)

    @staticmethod
    def _partir(d: ImageDraw.ImageDraw, texto: str, fuente: ImageFont.ImageFont, ancho: float) -> list[str]:
        """Parte un texto en líneas que caben en ``ancho`` píxeles."""
        lineas: list[str] = []
        for palabra in texto.split():
            candidata = f"{lineas[-1]} {palabra}" if lineas else palabra
            if lineas and d.textlength(candidata, font=fuente) <= ancho:
                lineas[-1] = candidata
            else:
                lineas.append(palabra)
        return lineas or [""]


class Pantalla:
    """Compone la pantalla completa: video a la izquierda y panel a la derecha."""

    def __init__(self, ancho: int = 1920, alto: int = 1080) -> None:
        self.ancho, self.alto = ancho, alto
        self.ancho_panel = round(ANCHO_PANEL_BASE * alto / 1080)
        self.ancho_video = ancho - self.ancho_panel
        self.alto_franja = round(ALTO_FRANJA_BASE * alto / 1080)
        self.panel = Panel(self.ancho_panel, alto)
        self._clave_franjas: tuple | None = None
        self._qr: tuple[str, Image.Image] | None = None  # último QR generado, por dirección
        self._franjas: tuple[np.ndarray, np.ndarray] | None = None

    def _dibujar_franjas(self, estado: EstadoPanel) -> tuple[np.ndarray, np.ndarray]:
        """Franjas de texto sobre y bajo el video (con Pillow, por las tildes)."""
        e = self.alto / 1080
        f, p = self.panel._f, (lambda valor: round(valor * e))
        tamano = (self.ancho_video, self.alto_franja)
        centro = self.alto_franja / 2

        superior = Image.new("RGB", tamano, marca.NEGRO)
        d = ImageDraw.Draw(superior)
        d.text((p(40), centro), estado.superior[0], font=f(26), fill=marca.MARFIL, anchor="lm")
        d.text((self.ancho_video - p(40), centro), estado.superior[1], font=f(26, True), fill=marca.MARFIL, anchor="rm")

        inferior = Image.new("RGB", tamano, marca.NEGRO)
        d = ImageDraw.Draw(inferior)
        principal, secundaria, detalle = estado.inferior
        ancho_texto = self.ancho_video - p(110)
        if estado.qr_url:
            # QR hacia el pasaporte del visitante, a la derecha de la franja
            lado = self.alto_franja - 2 * p(14)
            x_qr = self.ancho_video - p(40) - lado
            inferior.paste(self._imagen_qr(estado.qr_url, lado), (x_qr, p(14)))
            d.text((x_qr - p(18), centro - p(14)), "Tu reporte", font=f(24, True), fill=marca.MARFIL, anchor="rm")
            d.text((x_qr - p(18), centro + p(16)), "Escanea el código", font=f(17), fill=marca.MARFIL_TENUE, anchor="rm")
            ancho_texto = x_qr - p(18) - p(220) - p(70)
        if principal:
            d.rectangle((p(40), p(22), p(48), self.alto_franja - p(22)), fill=estado.color_inferior or marca.MARFIL_TENUE)
            d.text((p(70), p(40)), principal, font=f(36, True), fill=marca.MARFIL, anchor="lm")
            d.text((p(70), p(88)), secundaria, font=f(25), fill=marca.MARFIL, anchor="lm")
            # La línea del REBA se achica si no cabe, para no cortar los segmentos que cambiaron
            tamano_detalle = next((t for t in (18, 16, 14, 12) if d.textlength(detalle, font=f(t)) <= ancho_texto), 12)
            d.text((p(70), p(126)), detalle, font=f(tamano_detalle), fill=marca.MARFIL_TENUE, anchor="lm")
        return tuple(cv2.cvtColor(np.asarray(imagen), cv2.COLOR_RGB2BGR) for imagen in (superior, inferior))

    def _imagen_qr(self, url: str, lado: int) -> Image.Image:
        """Código QR de ``url`` en los colores de la marca (negro Auren sobre marfil), de ``lado`` píxeles."""
        if self._qr is None or self._qr[0] != url or self._qr[1].width != lado:
            import qrcode  # solo se carga si hay una URL pública configurada

            codigo = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
            codigo.add_data(url)
            codigo.make(fit=True)
            imagen = codigo.make_image(fill_color=marca.NEGRO, back_color=marca.MARFIL).convert("RGB")
            self._qr = (url, imagen.resize((lado, lado), Image.NEAREST))
        return self._qr[1]

    def componer(self, vista: np.ndarray | None, estado: EstadoPanel) -> np.ndarray:
        """``vista`` es el fotograma ya con el esqueleto (o None si no hay imagen)."""
        lienzo = np.empty((self.alto, self.ancho, 3), np.uint8)
        lienzo[:, : self.ancho_video] = marca.bgr(marca.NEGRO)
        if estado.clave_franjas() != self._clave_franjas or self._franjas is None:
            self._franjas = self._dibujar_franjas(estado)
            self._clave_franjas = estado.clave_franjas()
        alto_video = self.alto - 2 * self.alto_franja
        if vista is not None:
            alto, ancho = vista.shape[:2]
            escala = min(self.ancho_video / ancho, alto_video / alto)
            nuevo = (max(1, round(ancho * escala)), max(1, round(alto * escala)))
            if nuevo != (ancho, alto):
                vista = cv2.resize(vista, nuevo, interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_LINEAR)
            x, y = (self.ancho_video - nuevo[0]) // 2, (self.alto - nuevo[1]) // 2
            lienzo[y : y + nuevo[1], x : x + nuevo[0]] = vista
        lienzo[: self.alto_franja, : self.ancho_video] = self._franjas[0]
        lienzo[self.alto - self.alto_franja :, : self.ancho_video] = self._franjas[1]
        lienzo[:, self.ancho_video :] = self.panel.render(estado)
        return lienzo
