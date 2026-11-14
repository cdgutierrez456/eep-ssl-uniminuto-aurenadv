"""Pantalla de la estación de zona: aviso grande de estado, la cámara en vivo y un panel con marca Auren.

Base en Auren Deep con texto marfil; la lima es solo un acento pequeño. El aviso de estado usa
los colores de seguridad (rojo para peligro, amarillo para advertencia), no la lima.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ..nucleo.eventos import EstadoZona
from .marca import AMARILLO, DEEP, DEEP_CLARO, LIMA, MARFIL, MARFIL_TENUE, NEGRO, ROJO, Color, bgr
from .texto import escribir, medir

# Texto y colores del aviso grande: (fondo, color del texto, título, subtítulo)
AVISOS: dict[str, tuple[Color, Color, str, str]] = {
    "libre": (DEEP_CLARO, MARFIL, "ZONA DESPEJADA", "Nadie cerca de la zona de peligro"),
    "advertencia": (AMARILLO, NEGRO, "PRECAUCIÓN", "Persona cerca de la zona de peligro"),
    "peligro": (ROJO, (255, 255, 255), "PELIGRO", "Persona en la zona de peligro"),
    "sin_zona": (DEEP_CLARO, MARFIL_TENUE, "SIN ZONA DEFINIDA", "Detecta la cinta (D) o marca la zona a mano (E)"),
}
NOTA = "Demostración. No reemplaza una protección física de la máquina."


@dataclass
class EstadoPantalla:
    """Todo lo que la pantalla muestra en un fotograma."""

    estado: EstadoZona | None = None  # None: todavía no hay zona
    zona: str = ""  # una línea sobre la zona vigente (vértices, metros o píxeles)
    mensaje: str = ""  # último aviso para el operador
    ayuda: str = ""  # teclas
    fuente: str = "Cámara"
    fps: float = 0.0
    dispositivo: str = ""
    plataforma: str = ""  # en línea, sin conexión (con eventos en cola) o sin plataforma
    ingresos: int = 0
    casi_accidentes: int = 0
    sonido_local: bool = False
    ocultas: int = 0  # personas que se dejaron de ver dentro de la zona y se siguen contando


def envolver(texto: str, tamano: int, ancho: int, negrita: bool = False) -> list[str]:
    """Parte el texto en líneas que quepan en ``ancho`` píxeles."""
    lineas, actual = [], ""
    for palabra in texto.split():
        candidata = f"{actual} {palabra}".strip()
        if actual and medir(candidata, tamano, negrita)[0] > ancho:
            lineas.append(actual)
            actual = palabra
        else:
            actual = candidata
    return lineas + [actual] if actual else lineas


class Pantalla:
    """Compone la pantalla y sabe convertir un clic sobre ella en un punto de la imagen de la cámara."""

    def __init__(self, ancho: int = 1920, alto: int = 1080) -> None:
        self.ancho, self.alto = ancho, alto
        self.e = alto / 1080.0  # todo el diseño se escala desde 1080 píxeles de alto
        self.ancho_panel = self._px(440)
        self.alto_aviso = self._px(150)
        self.alto_pie = self._px(86)
        self._video = (0, self.alto_aviso, 1.0)  # x, y y escala con que se dibujó la cámara por última vez
        # El texto se dibuja con Pillow, que es lento: cada parte se guarda y solo se rehace si cambia
        self._partes: dict[str, tuple[tuple, np.ndarray]] = {}
        # Fondo ya pintado: copiarlo es mucho más rápido que rellenar un lienzo nuevo en cada fotograma
        self._fondo = np.full((alto, ancho, 3), bgr(DEEP), dtype=np.uint8)

    def _px(self, valor: float) -> int:
        return max(1, round(valor * self.e))

    # ------------------------------------------------------------------ #
    def a_imagen(self, x: float, y: float) -> tuple[float, float]:
        """De un punto de la pantalla al punto de la imagen de la cámara que hay debajo."""
        x0, y0, escala = self._video
        return ((x - x0) / escala, (y - y0) / escala)

    def componer(self, vista: np.ndarray | None, e: EstadoPantalla) -> np.ndarray:
        """Arma la pantalla completa. ``vista`` es la imagen de la cámara ya dibujada, o None si no hay."""
        lienzo = self._fondo.copy()
        ancho_video = self.ancho - self.ancho_panel
        clave = e.estado.estado if e.estado is not None else "sin_zona"
        fondo = AVISOS[clave][0]

        # Aviso grande de estado, con el color de seguridad
        lienzo[:self.alto_aviso, :ancho_video] = self._parte("aviso", (clave,), lambda: self._aviso(clave, ancho_video))

        # La cámara, ajustada al espacio que queda entre el aviso y el pie
        alto_video = self.alto - self.alto_aviso - self.alto_pie
        if vista is not None:
            escala = min(ancho_video / vista.shape[1], alto_video / vista.shape[0])
            tamano = (max(1, round(vista.shape[1] * escala)), max(1, round(vista.shape[0] * escala)))
            x0 = (ancho_video - tamano[0]) // 2
            y0 = self.alto_aviso + (alto_video - tamano[1]) // 2
            lienzo[y0:y0 + tamano[1], x0:x0 + tamano[0]] = cv2.resize(
                vista, tamano, interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_LINEAR)
            self._video = (x0, y0, escala)
            if clave in ("advertencia", "peligro"):  # marco del color del estado alrededor de la cámara
                cv2.rectangle(lienzo, (x0, y0), (x0 + tamano[0] - 1, y0 + tamano[1] - 1), bgr(fondo), self._px(10))

        # Pie: aviso para el operador y teclas
        lienzo[self.alto - self.alto_pie:, :ancho_video] = self._parte(
            "pie", (e.mensaje, e.ayuda), lambda: self._pie(e, ancho_video))

        # Panel lateral: se rehace cuando cambia algo de lo que muestra (los fps, redondeados)
        datos = (e.estado, e.zona, e.fuente, round(e.fps), e.dispositivo, e.plataforma, e.ingresos,
                 e.casi_accidentes, e.sonido_local, e.ocultas)
        lienzo[:, ancho_video:] = self._parte("panel", datos, lambda: self._panel(e))
        return lienzo

    # ------------------------------------------------------------------ #
    def _parte(self, nombre: str, clave: tuple, pintar) -> np.ndarray:
        """Devuelve la parte ya pintada si no cambió lo que muestra; si cambió, la pinta de nuevo."""
        guardada = self._partes.get(nombre)
        if guardada is None or guardada[0] != clave:
            guardada = self._partes[nombre] = (clave, pintar())
        return guardada[1]

    def _aviso(self, clave: str, ancho: int) -> np.ndarray:
        fondo, color, titulo, subtitulo = AVISOS[clave]
        parte = np.full((self.alto_aviso, ancho, 3), bgr(fondo), dtype=np.uint8)
        escribir(parte, titulo, self._px(40), self._px(22), self._px(64), color, negrita=True)
        escribir(parte, subtitulo, self._px(42), self._px(100), self._px(28), color)
        return parte

    def _pie(self, e: EstadoPantalla, ancho: int) -> np.ndarray:
        parte = np.full((self.alto_pie, ancho, 3), bgr(DEEP), dtype=np.uint8)
        escribir(parte, e.mensaje, self._px(40), self._px(12), self._px(22), MARFIL, negrita=True)
        escribir(parte, e.ayuda, self._px(40), self._px(48), self._px(16), MARFIL_TENUE)
        return parte

    def _panel(self, e: EstadoPantalla) -> np.ndarray:
        lienzo = np.full((self.alto, self.ancho_panel, 3), bgr(DEEP), dtype=np.uint8)
        x0 = 0
        x = x0 + self._px(32)
        ancho = self.ancho_panel - self._px(64)
        cv2.line(lienzo, (x0, 0), (x0, self.alto), bgr(DEEP_CLARO), 1)
        escribir(lienzo, "Zona de peligro", x, self._px(34), self._px(34), MARFIL, negrita=True)
        lienzo[self._px(88):self._px(92), x:x + self._px(72)] = bgr(LIMA)  # acento de marca, pequeño

        y = self._px(124)
        en_peligro = e.estado.personas_peligro if e.estado else 0
        en_advertencia = e.estado.personas_advertencia if e.estado else 0
        y = self._cifra(lienzo, x, y, en_peligro, "en la zona de peligro", ROJO if en_peligro else MARFIL)
        if e.ocultas:
            escribir(lienzo, f"{e.ocultas} sin verse: se asume que sigue dentro", x, y - self._px(14), self._px(16), MARFIL_TENUE)
            y += self._px(14)
        y = self._cifra(lienzo, x, y, en_advertencia, "en la franja de advertencia", AMARILLO if en_advertencia else MARFIL)

        y = self._separador(lienzo, x, y, ancho, "En esta sesión")
        y = self._dato(lienzo, x, y, "Ingresos a la zona", str(e.ingresos))
        y = self._dato(lienzo, x, y, "Casi-accidentes", str(e.casi_accidentes))

        y = self._separador(lienzo, x, y, ancho, "Zona")
        for linea in envolver(e.zona, self._px(17), ancho):
            escribir(lienzo, linea, x, y, self._px(17), MARFIL)
            y += self._px(26)

        y = self._separador(lienzo, x, y + self._px(4), ancho, "Estación")
        y = self._dato(lienzo, x, y, e.fuente, f"{e.fps:.0f} fps")
        y = self._dato(lienzo, x, y, "Detección", e.dispositivo)
        y = self._dato(lienzo, x, y, "Plataforma", e.plataforma)
        y = self._dato(lienzo, x, y, "Sonido local (S)", "encendido" if e.sonido_local else "apagado")

        y_nota = self.alto - self._px(70)
        for linea in envolver(NOTA, self._px(15), ancho):
            escribir(lienzo, linea, x, y_nota, self._px(15), MARFIL_TENUE)
            y_nota += self._px(22)
        return lienzo

    def _cifra(self, lienzo: np.ndarray, x: int, y: int, valor: int, rotulo: str, color: Color) -> int:
        ancho_numero, _ = escribir(lienzo, str(valor), x, y, self._px(76), color, negrita=True)
        escribir(lienzo, "persona" if valor == 1 else "personas", x + ancho_numero + self._px(16), y + self._px(18),
                 self._px(22), MARFIL)
        escribir(lienzo, rotulo, x + ancho_numero + self._px(16), y + self._px(48), self._px(18), MARFIL_TENUE)
        return y + self._px(108)

    def _separador(self, lienzo: np.ndarray, x: int, y: int, ancho: int, titulo: str) -> int:
        cv2.line(lienzo, (x, y), (x + ancho, y), bgr(DEEP_CLARO), 1)
        escribir(lienzo, titulo.upper(), x, y + self._px(14), self._px(14), MARFIL_TENUE, negrita=True)
        return y + self._px(46)

    def _dato(self, lienzo: np.ndarray, x: int, y: int, rotulo: str, valor: str) -> int:
        escribir(lienzo, rotulo, x, y, self._px(17), MARFIL_TENUE)
        ancho_valor, _ = medir(valor, self._px(17), True)
        escribir(lienzo, valor, self.ancho_panel - self._px(32) - ancho_valor, y, self._px(17), MARFIL, negrita=True)
        return y + self._px(30)
