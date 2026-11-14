"""Maquetación del reporte en una página A4 con fpdf2 (se instala con pip, sin dependencias del sistema).

Usa las fuentes básicas de PDF (Helvetica): no hay que instalar ni incrustar ninguna fuente,
así que funciona igual en Windows y en Linux. Esas fuentes solo traen Latin-1 (tildes, eñes,
grados y el punto medio incluidos); los pocos signos que no están (flechas, rayas largas) se
reemplazan en ``latin1``.

El contenido debe caber en una página: si no cabe, se vuelve a maquetar con letra más pequeña.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from ..interfaz import marca
from ..nucleo.intentos import TEXTO_DE_NIVEL
from .contenido import ContenidoReporte, DatosReporte, armar_contenido

log = logging.getLogger(__name__)

ANCHO, ALTO, MARGEN = 210.0, 297.0, 14.0
UTIL = ANCHO - 2 * MARGEN
Y_PIE = 280.0  # el contenido termina antes de aquí; debajo va el pie
ESCALAS = (1.0, 0.93, 0.87, 0.81)  # tamaños de letra a probar hasta que quepa en una página
GRIS = (95, 105, 104)
LINEA = (208, 212, 208)
COLOR_DE_PIERNAS = {"bien": marca.VERDE, "intermedio": marca.AMARILLO, "mal": marca.ROJO, "": marca.GRIS}

_REEMPLAZOS = {"→": "a", "—": "-", "–": "-", "−": "-", "…": "...", "≥": ">=", "≤": "<=",
               "“": '"', "”": '"', "‘": "'", "’": "'", "•": "·"}


def latin1(texto: str) -> str:
    """Deja el texto en Latin-1, que es lo que admiten las fuentes básicas de PDF."""
    for signo, reemplazo in _REEMPLAZOS.items():
        texto = texto.replace(signo, reemplazo)
    return texto.encode("latin-1", "replace").decode("latin-1")


@dataclass(frozen=True)
class ReporteGenerado:
    """Resultado de generar el PDF."""

    ruta: Path
    paginas: int
    escala: float  # 1.0 = tamaño de letra normal; menos si hubo que achicar para que cupiera
    desborde: bool  # True si ni con la letra más pequeña cupo todo sobre el pie


class _Hoja:
    """Dibuja el contenido en una página. ``k`` escala los tamaños de letra."""

    def __init__(self, contenido: ContenidoReporte, k: float) -> None:
        self.c, self.k = contenido, k
        self.pdf = FPDF(orientation="P", unit="mm", format="A4")
        self.pdf.set_auto_page_break(False)
        self.pdf.set_margins(MARGEN, MARGEN, MARGEN)
        self.pdf.c_margin = 0  # sin sangría dentro de las celdas: todo alinea con el margen
        self.pdf.set_title(latin1(f"{contenido.titulo} {contenido.reporte_id}"))
        self.pdf.set_author("Auren Advisory")
        self.pdf.set_creator("SST en vivo")
        self.pdf.add_page()
        self.y = 0.0

    # ------------------------------------------------------------------ #
    # Utilidades de dibujo
    # ------------------------------------------------------------------ #
    def _alto(self, tam: float) -> float:
        return tam * self.k * 0.3528 * 1.28

    def _fuente(self, tam: float, estilo: str = "", color: tuple = marca.NEGRO) -> None:
        self.pdf.set_font("Helvetica", estilo, tam * self.k)
        self.pdf.set_text_color(*color)

    def texto(self, x: float, y: float, s: str, tam: float, estilo: str = "", color: tuple = marca.NEGRO,
              ancho: float = 0, alinear: str = "L", alto: float | None = None) -> None:
        self._fuente(tam, estilo, color)
        self.pdf.set_xy(x, y)
        s = latin1(s)
        self.pdf.cell(ancho or self.pdf.get_string_width(s) + 1, alto or self._alto(tam), s, align=alinear)

    def parrafo(self, x: float, y: float, ancho: float, s: str, tam: float, estilo: str = "",
                color: tuple = marca.NEGRO, alinear: str = "L") -> float:
        """Texto en varias líneas. Devuelve la y donde termina."""
        self._fuente(tam, estilo, color)
        self.pdf.set_xy(x, y)
        self.pdf.multi_cell(ancho, self._alto(tam), latin1(s), align=alinear, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        return self.pdf.get_y()

    def chip(self, x: float, y: float, s: str, color: tuple, tam: float = 8.5, alto: float = 6.2) -> float:
        """Distintivo de color con texto negro. Devuelve su ancho."""
        self._fuente(tam, "B")
        s = latin1(s)
        ancho = self.pdf.get_string_width(s) + 5.5
        self.pdf.set_fill_color(*color)
        self.pdf.rect(x, y, ancho, alto, style="F", round_corners=True, corner_radius=alto / 2)
        self.pdf.set_xy(x, y)
        self.pdf.cell(ancho, alto, s, align="C")
        return ancho

    def punto(self, x: float, y_centro: float, color: tuple, radio: float = 1.2) -> None:
        self.pdf.set_fill_color(*color)
        self.pdf.ellipse(x, y_centro - radio, 2 * radio, 2 * radio, style="F")

    def linea(self, x1: float, y: float, x2: float, color: tuple = LINEA, grosor: float = 0.2) -> None:
        self.pdf.set_draw_color(*color)
        self.pdf.set_line_width(grosor)
        self.pdf.line(x1, y, x2, y)

    def seccion(self, titulo: str) -> None:
        """Título de sección con una línea fina debajo."""
        self.y += 2.6 * self.k
        self.texto(MARGEN, self.y, titulo, 9.6, "B", marca.DEEP)
        self.y += self._alto(9.6) + 0.4
        self.linea(MARGEN, self.y, ANCHO - MARGEN, marca.DEEP, 0.3)
        self.y += 1.6

    # ------------------------------------------------------------------ #
    # Bloques
    # ------------------------------------------------------------------ #
    def encabezado(self) -> None:
        c, pdf = self.c, self.pdf
        pdf.set_fill_color(*marca.DEEP)
        pdf.rect(0, 0, ANCHO, 24, style="F")
        pdf.set_fill_color(*marca.LIMA)  # la lima solo como acento
        pdf.rect(MARGEN, 6.5, 1.4, 11, style="F")
        self.texto(MARGEN + 3.5, 6, c.titulo, 15, "B", marca.MARFIL)
        self.texto(MARGEN + 3.5, 13.2, c.marca, 8.5, "", marca.MARFIL)
        derecha, ancho = ANCHO - MARGEN - 80, 80
        self.texto(derecha, 5.6, c.reporte_id, 9.5, "B", marca.MARFIL, ancho, "R")
        self.texto(derecha, 10.6, c.subtitulo, 8.5, "", marca.MARFIL, ancho, "R")
        self.texto(derecha, 15.2, c.fecha, 8.5, "", marca.MARFIL, ancho, "R")
        self.y = 28.5

    def resultado(self) -> None:
        """Fotograma crítico a la izquierda y tarjeta del puntaje a la derecha."""
        c, pdf, y0, alto = self.c, self.pdf, self.y, 56.0
        ancho_imagen = alto * 16 / 9
        if c.ruta_imagen is not None and Path(c.ruta_imagen).is_file():
            pdf.image(str(c.ruta_imagen), x=MARGEN, y=y0, w=ancho_imagen, h=alto, keep_aspect_ratio=True)
        else:
            pdf.set_fill_color(*LINEA)
            pdf.rect(MARGEN, y0, ancho_imagen, alto, style="F")
            self.texto(MARGEN, y0 + alto / 2 - 2, "Imagen no disponible", 8.5, "", GRIS, ancho_imagen, "C")

        x_tarjeta = MARGEN + ancho_imagen + 4
        ancho_tarjeta = ANCHO - MARGEN - x_tarjeta
        pdf.set_fill_color(*marca.MARFIL)
        pdf.rect(x_tarjeta, y0, ancho_tarjeta, alto, style="F")
        x, ancho = x_tarjeta + 4, ancho_tarjeta - 8
        self.texto(x, y0 + 2.6, "Puntaje REBA", 7.5, "", GRIS)
        numero = str(c.puntaje)
        self._fuente(34, "B")
        ancho_numero = pdf.get_string_width(numero)
        self.texto(x, y0 + 6.2, numero, 34, "B", marca.NEGRO, alto=13)
        self.texto(x + ancho_numero + 1.5, y0 + 12.6, "de 15", 9, "", GRIS)
        self.chip(x, y0 + 21.2, c.etiqueta, marca.COLOR_DE_NIVEL[c.nivel])
        self.texto(x, y0 + 29.2, c.accion, 8.5, "B")
        self.parrafo(x, y0 + 33.6, ancho, c.mensaje, 8)
        # Técnica de levantamiento: lo que la persona sí puede cambiar
        (espalda, nivel), (rodillas, piernas) = c.tecnica
        self.punto(x, y0 + 47.6, marca.COLOR_DE_ESPALDA[nivel])
        self.texto(x + 4, y0 + 45.8, espalda, 8)
        self.punto(x, y0 + 51.9, COLOR_DE_PIERNAS[piernas])
        self.texto(x + 4, y0 + 50.1, rodillas, 8)

        self.y = y0 + alto + 1.8
        self.texto(MARGEN, self.y, c.condiciones, 8, "", GRIS)
        self.y += self._alto(8) + 0.3

    def tablas(self) -> None:
        """Ángulos y puntajes por segmento a la izquierda; el cálculo del REBA a la derecha."""
        c, pdf = self.c, self.pdf
        self.seccion("Ángulos y puntajes por segmento")
        y0, fila = self.y, max(4.3, 5.1 * self.k)
        x, columnas = MARGEN, (30.0, 18.0, 20.0, 40.0)
        encabezados = ("Segmento", "Ángulo", "Puntaje", "Observación")
        alineados = ("L", "R", "C", "L")
        cx = x
        for ancho, titulo, alinear in zip(columnas, encabezados, alineados):
            self.texto(cx, y0, titulo, 7.5, "", GRIS, ancho, alinear, fila)
            cx += ancho
        for i, segmento in enumerate(c.segmentos):
            y = y0 + (i + 1) * fila
            self.linea(x, y, x + sum(columnas))
            estimado = segmento.puntaje is not None
            self.texto(x, y, segmento.nombre, 9, "", marca.NEGRO if estimado else GRIS, columnas[0], "L", fila)
            self.texto(x + columnas[0], y, segmento.angulo, 9, "", marca.NEGRO if estimado else GRIS,
                       columnas[1], "R", fila)
            centro = x + columnas[0] + columnas[1] + columnas[2] / 2
            self.punto(centro - 2.1, y + fila / 2, marca.color_de_segmento(segmento.puntaje), 2.1)
            self.texto(centro - 5, y, str(segmento.puntaje) if estimado else "-", 8, "B", marca.NEGRO, 10, "C", fila)
            self.texto(x + sum(columnas[:3]) + 2, y, segmento.nota, 7.5, "", GRIS, columnas[3] - 2, "L", fila)
        alto_total = (len(c.segmentos) + 1) * fila

        x2, ancho2 = MARGEN + sum(columnas) + 4, UTIL - sum(columnas) - 4
        fila2 = alto_total / len(c.calculo)
        for i, (nombre, valor) in enumerate(c.calculo):
            y = y0 + i * fila2
            destacado = nombre.startswith(("Puntaje", "REBA"))
            if nombre.startswith("REBA"):
                pdf.set_fill_color(*marca.MARFIL)
                pdf.rect(x2, y, ancho2, fila2, style="F")
            elif i:
                self.linea(x2, y, x2 + ancho2)
            self.texto(x2 + 1.5, y, nombre, 8, "B" if destacado else "", marca.NEGRO, ancho2 - 16, "L", fila2)
            self.texto(x2 + ancho2 - 15.5, y, valor, 8.5, "B", marca.NEGRO, 14, "R", fila2)
        self.y = y0 + alto_total + 0.6

    def significado(self) -> None:
        s = self.c.significado
        self.seccion(s["titulo"])
        ancho = self.chip(MARGEN, self.y, s["etiqueta"], marca.COLOR_DE_NIVEL[self.c.nivel])
        self.texto(MARGEN + ancho + 2.5, self.y + 0.7, s["accion"], 9, "B")
        self.y += 6.2 + 1.6
        self.y = self.parrafo(MARGEN, self.y, UTIL, s["ampliado"], 8.8) + 0.9
        self.y = self.parrafo(MARGEN, self.y, UTIL, s["linea_fija"], 8, "I", GRIS)
        if "cierre" in s:
            self.y = self.parrafo(MARGEN, self.y + 0.9, UTIL, s["cierre"], 8.8, "B", marca.DEEP)

    def comparacion(self) -> None:
        c = self.c
        if not c.comparacion:
            return
        self.seccion("Comparación de intentos")
        fila = max(4.0, 4.6 * self.k)
        columnas = (34.0, 22.0, 44.0, 42.0, 40.0)
        x = MARGEN
        for ancho, titulo in zip(columnas, ("Intento", "REBA", "Nivel de riesgo", "Flexión de espalda", "Rodillas")):
            self.texto(x, self.y, titulo, 7.5, "", GRIS, ancho, "L", fila)
            x += ancho
        self.y += fila
        for intento in c.comparacion:
            self.linea(MARGEN, self.y, MARGEN + sum(columnas))
            valores = (intento.intento, str(intento.puntaje), TEXTO_DE_NIVEL[intento.nivel].capitalize(),
                       intento.espalda, intento.rodillas)
            x = MARGEN
            for i, (ancho, valor) in enumerate(zip(columnas, valores)):
                if i == 1:
                    self.punto(x + 1, self.y + fila / 2, marca.COLOR_DE_NIVEL[intento.nivel], 1.3)
                    self.texto(x + 4.2, self.y, valor, 8.8, "B", marca.NEGRO, ancho - 4.2, "L", fila)
                else:
                    self.texto(x, self.y, valor, 8.8, "", marca.NEGRO, ancho, "L", fila)
                x += ancho
            self.y += fila
        if c.lectura:
            self.y = self.parrafo(MARGEN, self.y + 1.0, UTIL, c.lectura, 8.8, "B", marca.DEEP)

    def recomendaciones(self) -> None:
        c = self.c
        self.seccion("Recomendaciones")
        for texto in c.recomendaciones:
            self.punto(MARGEN + 0.6, self.y + self._alto(8.8) / 2, marca.DEEP, 0.8)
            self.y = self.parrafo(MARGEN + 4, self.y, UTIL - 4, texto, 8.8) + 0.7
        if c.pista:
            self.y = self.parrafo(MARGEN, self.y + 0.3, UTIL, c.pista, 8.5, "I", GRIS)

    def notas(self) -> None:
        self.seccion("Cómo se midió")
        self.y = self.parrafo(MARGEN, self.y, UTIL, " ".join(self.c.notas), 7.6, "", GRIS)

    def pie(self) -> None:
        c = self.c
        self.linea(MARGEN, Y_PIE + 1.2, ANCHO - MARGEN)
        self._fuente(7 / self.k, "", GRIS)  # el pie no se achica: es obligatorio y debe leerse
        self.pdf.set_xy(MARGEN, Y_PIE + 2.6)
        self.pdf.multi_cell(UTIL, 3.2, latin1(c.pie), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        y = self.pdf.get_y() + 0.8
        self.texto(MARGEN, y, c.borrador, 7 / self.k, "B", marca.DEEP)
        self.texto(ANCHO - MARGEN - 60, y, c.reporte_id, 7 / self.k, "", GRIS, 60, "R")

    def dibujar(self) -> "_Hoja":
        self.encabezado()
        self.resultado()
        self.tablas()
        self.significado()
        self.comparacion()
        self.recomendaciones()
        self.notas()
        self.pie()
        return self

    @property
    def desborde(self) -> bool:
        return self.y > Y_PIE - 0.5


def generar_reporte(datos: DatosReporte | ContenidoReporte, ruta: Path) -> ReporteGenerado:
    """Genera el PDF de una página en ``ruta`` y devuelve cómo quedó.

    Acepta los datos del intento o un contenido ya armado. Si el contenido no cabe con la
    letra normal, prueba tamaños más pequeños; el pie obligatorio nunca se achica.
    """
    contenido = datos if isinstance(datos, ContenidoReporte) else armar_contenido(datos)
    hoja = None
    for k in ESCALAS:
        hoja = _Hoja(contenido, k).dibujar()
        if not hoja.desborde:
            break
    if hoja.desborde:
        log.warning("El reporte %s no cabe en una página ni con la letra más pequeña", contenido.reporte_id)
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(bytes(hoja.pdf.output()))  # así también funcionan las rutas con tildes en Windows
    return ReporteGenerado(ruta, hoja.pdf.page_no(), hoja.k, hoja.desborde)
