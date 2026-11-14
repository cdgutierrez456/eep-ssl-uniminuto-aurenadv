"""Matriz IPEVR en Excel: una hoja con estilo Auren, marcada siempre como borrador.

La hoja lleva el aviso de borrador y la fecha, la miniatura de la foto (difuminada y con
las cajas numeradas), una fila por peligro y las notas al pie. La columna "Requisito
legal" queda siempre vacía: la completa el profesional, la IA no cita normas.
"""

from __future__ import annotations

import io
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image as ImagenExcel
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from modulos.comun.eventos import ZONA_HORARIA

from .esquema import CATEGORIAS, JERARQUIA
from .imagen import codificar_jpeg, miniatura
from .valoracion import RUTA_PARAMETROS, _leer, datos_del_nivel

NOMBRE_HOJA = "Matriz IPEVR"
TITULO = "Matriz de identificación de peligros, evaluación y valoración de riesgos (IPEVR)"
AVISO_BORRADOR = "BORRADOR — Generado con IA. Debe ser validado en campo por un profesional de SST."
NOTA_REQUISITO_LEGAL = "A completar por el profesional"
LEMA = "Borrador generado con IA. La IA propone, el profesional de SST decide."

# Marca Auren
DEEP = "12343B"
NEGRO = "111414"
MARFIL = "F2F1EA"
LIMA = "C8F169"
LINEA = "C5CBC6"

# (clave, título, grupo, ancho en caracteres)
COLUMNAS: tuple[tuple[str, str, str, int], ...] = (
    ("n", "N.º", "Identificación", 6),
    ("proceso", "Proceso", "Identificación", 18),
    ("zona", "Zona / lugar", "Identificación", 18),
    ("actividad", "Actividad", "Identificación", 20),
    ("tarea", "Tarea", "Identificación", 20),
    ("rutinaria", "Rutinaria (sí/no)", "Identificación", 11),
    ("descripcion", "Descripción del peligro", "Peligro", 44),
    ("clasificacion", "Clasificación", "Peligro", 26),
    ("efectos", "Efectos posibles", "Peligro", 30),
    ("control_fuente", "Fuente", "Controles existentes", 18),
    ("control_medio", "Medio", "Controles existentes", 18),
    ("control_individuo", "Individuo", "Controles existentes", 18),
    ("nd", "ND", "Evaluación del riesgo", 7),
    ("ne", "NE", "Evaluación del riesgo", 7),
    ("np", "NP", "Evaluación del riesgo", 7),
    ("interpretacion_np", "Interpretación NP", "Evaluación del riesgo", 15),
    ("nc", "NC", "Evaluación del riesgo", 7),
    ("nr", "NR", "Evaluación del riesgo", 8),
    ("interpretacion_nr", "Interpretación NR", "Evaluación del riesgo", 34),
    ("aceptabilidad", "Aceptabilidad del riesgo", "Valoración del riesgo", 24),
    ("expuestos", "N.º de expuestos", "Criterios para establecer controles", 11),
    ("peor_consecuencia", "Peor consecuencia", "Criterios para establecer controles", 24),
    ("requisito_legal", "Requisito legal", "Criterios para establecer controles", 22),
    ("eliminacion", "Eliminación", "Medidas de intervención", 28),
    ("sustitucion", "Sustitución", "Medidas de intervención", 28),
    ("ingenieria", "Controles de ingeniería", "Medidas de intervención", 32),
    ("administrativos", "Controles administrativos", "Medidas de intervención", 32),
    ("epp", "EPP", "Medidas de intervención", 26),
    ("confianza", "Confianza de la IA", "Análisis de la IA", 16),
    ("evidencia", "Evidencia visible", "Análisis de la IA", 44),
)
_CENTRADAS = {"n", "rutinaria", "nd", "ne", "np", "interpretacion_np", "nc", "nr", "aceptabilidad",
              "expuestos", "confianza"}
_CON_COLOR_DE_NIVEL = {"interpretacion_nr", "aceptabilidad"}
_CONFIANZA = {"alta": "Alta", "media": "Media", "baja": "Baja — posible, verificar"}

FILA_TITULO, FILA_AVISO, FILA_FECHA = 1, 2, 3
FILA_BLOQUE, FILAS_DEL_BLOQUE = 5, 8          # miniatura y datos generales
FILA_GRUPOS = FILA_BLOQUE + FILAS_DEL_BLOQUE + 1
FILA_ENCABEZADOS = FILA_GRUPOS + 1
FILA_DATOS = FILA_ENCABEZADOS + 1
ALTO_FILA_BLOQUE_PT = 40
COLUMNA_DATOS_GENERALES = 7                   # a la derecha de la miniatura
COLUMNAS_DATOS_GENERALES = 6
MINIATURA_ANCHO_PX, MINIATURA_ALTO_PX = 640, 415   # tamaño con que se ve en la hoja
MINIATURA_DETALLE = 2                         # se incrusta al doble, para que aguante el zoom y la impresión
ALTO_LINEA_PT = 13.0


def titulos_de_columnas() -> list[str]:
    """Títulos de las columnas de la matriz, en orden."""
    return [titulo for _, titulo, _, _ in COLUMNAS]


def columna_de(clave: str) -> int:
    """Número de columna (desde 1) de una clave de ``COLUMNAS``."""
    return next(indice for indice, (nombre, *_) in enumerate(COLUMNAS, start=1) if nombre == clave)


def generar_excel(
    ruta: str | Path,
    peligros: list[dict],
    *,
    descripcion_general: str = "",
    advertencias: Iterable[str] = (),
    contexto: dict | None = None,
    imagen: np.ndarray | None = None,
    fecha: datetime | None = None,
    inspeccion_id: str = "",
    parametros: dict | None = None,
) -> Path:
    """Escribe la matriz IPEVR en ``ruta`` y devuelve la ruta.

    ``peligros`` viene de ``valorar_peligros``. ``contexto`` trae los campos opcionales
    que llena la persona (``proceso``, ``zona``, ``actividad``, ``tarea``, ``rutinaria``);
    los que falten quedan en blanco. ``imagen`` es la foto ya difuminada y anotada.
    """
    parametros = parametros if parametros is not None else _leer(RUTA_PARAMETROS)
    contexto = contexto or {}
    fecha = fecha or datetime.now(ZONA_HORARIA)
    ultima = len(COLUMNAS)

    libro = Workbook()
    hoja = libro.active
    hoja.title = NOMBRE_HOJA
    libro.properties.title = TITULO
    libro.properties.creator = "Auren Advisory · SST en vivo"
    hoja.sheet_view.showGridLines = False
    hoja.sheet_view.zoomScale = 90
    for indice, (_, _, _, ancho) in enumerate(COLUMNAS, start=1):
        hoja.column_dimensions[get_column_letter(indice)].width = ancho

    _encabezado(hoja, fecha, inspeccion_id, ultima)
    _bloque_general(hoja, descripcion_general, list(advertencias), contexto, len(peligros), imagen)
    _encabezados_de_tabla(hoja)
    fila = FILA_DATOS
    for peligro in peligros:
        _fila_de_peligro(hoja, fila, peligro, contexto, parametros)
        fila += 1
    _notas(hoja, fila + 1, parametros, ultima)

    hoja.page_setup.orientation = "landscape"
    hoja.page_setup.fitToWidth = 1
    hoja.page_setup.fitToHeight = 0
    hoja.sheet_properties.pageSetUpPr.fitToPage = True
    hoja.print_title_rows = f"{FILA_GRUPOS}:{FILA_ENCABEZADOS}"

    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    libro.save(ruta)
    return ruta


# --------------------------------------------------------------------------- #
# Partes de la hoja
# --------------------------------------------------------------------------- #
def _relleno(color: str) -> PatternFill:
    return PatternFill("solid", start_color=color, end_color=color)


def _encabezado(hoja, fecha: datetime, inspeccion_id: str, ultima: int) -> None:
    """Título, aviso de borrador y fecha, a todo el ancho de la tabla."""
    lima = Side(style="medium", color=LIMA)
    filas = (
        (FILA_TITULO, TITULO, DEEP, Font(bold=True, size=15, color=MARFIL), 30),
        (FILA_AVISO, AVISO_BORRADOR, NEGRO, Font(bold=True, size=12, color=MARFIL), 26),
        (FILA_FECHA, _linea_de_fecha(fecha, inspeccion_id), MARFIL, Font(size=10, color=NEGRO), 20),
    )
    for fila, texto, fondo, fuente, alto in filas:
        hoja.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=ultima)
        celda = hoja.cell(row=fila, column=1, value=texto)
        celda.font = fuente
        celda.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        hoja.row_dimensions[fila].height = alto
        for columna in range(1, ultima + 1):
            hoja.cell(row=fila, column=columna).fill = _relleno(fondo)
            if fila == FILA_AVISO:  # el único acento lima de la hoja: la línea bajo el aviso
                hoja.cell(row=fila, column=columna).border = Border(bottom=lima)


def _linea_de_fecha(fecha: datetime, inspeccion_id: str) -> str:
    texto = f"Fecha: {fecha.strftime('%d/%m/%Y %H:%M')}"
    return f"{texto}   ·   Inspección: {inspeccion_id}" if inspeccion_id else texto


def _bloque_general(hoja, descripcion_general: str, advertencias: list[str], contexto: dict,
                    cantidad: int, imagen: np.ndarray | None) -> None:
    """Miniatura de la foto a la izquierda y datos generales de la inspección a la derecha."""
    for desplazamiento in range(FILAS_DEL_BLOQUE):
        hoja.row_dimensions[FILA_BLOQUE + desplazamiento].height = ALTO_FILA_BLOQUE_PT

    if imagen is not None:
        mini = miniatura(imagen, MINIATURA_ANCHO_PX * MINIATURA_DETALLE, MINIATURA_ALTO_PX * MINIATURA_DETALLE)
        alto, ancho = mini.shape[:2]
        escala = min(MINIATURA_ANCHO_PX / ancho, MINIATURA_ALTO_PX / alto)
        dibujo = ImagenExcel(io.BytesIO(codificar_jpeg(mini, 88)))
        dibujo.width, dibujo.height = round(ancho * escala), round(alto * escala)
        dibujo.anchor = f"A{FILA_BLOQUE}"
        hoja.add_image(dibujo)

    lineas = (
        ("Escena", descripcion_general),
        ("Proceso", contexto.get("proceso")),
        ("Zona / lugar", contexto.get("zona")),
        ("Actividad", contexto.get("actividad")),
        ("Tarea", contexto.get("tarea")),
        ("Rutinaria", _si_no(contexto.get("rutinaria"))),
        ("Advertencias de la imagen", "; ".join(advertencias)),
        ("Peligros en la matriz", str(cantidad)),
    )
    negrita = InlineFont(b=True, color=DEEP, sz=10)
    normal = InlineFont(color=NEGRO, sz=10)
    fin = COLUMNA_DATOS_GENERALES + COLUMNAS_DATOS_GENERALES - 1
    for desplazamiento, (rotulo, valor) in enumerate(lineas):
        fila = FILA_BLOQUE + desplazamiento
        hoja.merge_cells(start_row=fila, start_column=COLUMNA_DATOS_GENERALES, end_row=fila, end_column=fin)
        celda = hoja.cell(row=fila, column=COLUMNA_DATOS_GENERALES)
        celda.value = CellRichText(TextBlock(negrita, f"{rotulo}: "), TextBlock(normal, _texto(valor)))
        celda.alignment = Alignment(vertical="center", wrap_text=True)


def _encabezados_de_tabla(hoja) -> None:
    """Fila de grupos (celdas combinadas) y fila de títulos de columna, en Auren Deep con texto marfil."""
    borde = Border(left=Side(style="thin", color=MARFIL), right=Side(style="thin", color=MARFIL),
                   top=Side(style="thin", color=MARFIL), bottom=Side(style="thin", color=MARFIL))
    inicio = 1
    for indice, (_, titulo, grupo, _) in enumerate(COLUMNAS, start=1):
        for fila, texto, tamano in ((FILA_GRUPOS, None, 10), (FILA_ENCABEZADOS, titulo, 10)):
            celda = hoja.cell(row=fila, column=indice, value=texto)
            celda.fill = _relleno(DEEP)
            celda.font = Font(bold=True, size=tamano, color=MARFIL)
            celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            celda.border = borde
        es_ultima_del_grupo = indice == len(COLUMNAS) or COLUMNAS[indice][2] != grupo
        if es_ultima_del_grupo:
            hoja.cell(row=FILA_GRUPOS, column=inicio, value=grupo)
            if indice > inicio:
                hoja.merge_cells(start_row=FILA_GRUPOS, start_column=inicio, end_row=FILA_GRUPOS, end_column=indice)
            inicio = indice + 1
    # Al combinar, las celdas interiores pierden el estilo: se les vuelve a dar el fondo
    for indice in range(1, len(COLUMNAS) + 1):
        hoja.cell(row=FILA_GRUPOS, column=indice).fill = _relleno(DEEP)
    hoja.row_dimensions[FILA_GRUPOS].height = 22
    hoja.row_dimensions[FILA_ENCABEZADOS].height = 34


def _fila_de_peligro(hoja, fila: int, peligro: dict, contexto: dict, parametros: dict) -> None:
    valoracion = peligro["valoracion"]
    nivel = datos_del_nivel(valoracion["nivel_riesgo"], parametros)
    controles_existentes = peligro.get("controles_existentes") or {}
    controles_propuestos = peligro.get("controles_propuestos") or {}
    clasificacion = peligro.get("clasificacion") or {}

    valores: dict[str, Any] = {
        "n": peligro["n"],
        "proceso": _texto(contexto.get("proceso")),
        "zona": _texto(contexto.get("zona")),
        "actividad": _texto(contexto.get("actividad")),
        "tarea": _texto(contexto.get("tarea")),
        "rutinaria": _si_no(contexto.get("rutinaria")),
        "descripcion": peligro["descripcion"],
        "clasificacion": _clasificacion(clasificacion),
        "efectos": peligro.get("efectos_posibles", ""),
        "control_fuente": controles_existentes.get("fuente", ""),
        "control_medio": controles_existentes.get("medio", ""),
        "control_individuo": controles_existentes.get("individuo", ""),
        # Sin valor numérico de deficiencia se escribe su nombre y NP y NR quedan en blanco
        "nd": valoracion["nd"] if valoracion["nd"] is not None
              else parametros["nivel_deficiencia"][valoracion["deficiencia"]]["etiqueta"],
        "ne": valoracion["ne"],
        "np": valoracion["np"],
        "interpretacion_np": valoracion["interpretacion_np"],
        "nc": valoracion["nc"],
        "nr": valoracion["nr"],
        "interpretacion_nr": f"{valoracion['nivel_riesgo']} — {valoracion['significado']}",
        "aceptabilidad": valoracion["aceptabilidad"],
        "expuestos": peligro.get("expuestos"),
        "peor_consecuencia": peligro.get("peor_consecuencia", ""),
        "requisito_legal": None,  # siempre vacío: lo completa el profesional
        "confianza": _CONFIANZA.get(peligro.get("confianza"), ""),
        "evidencia": peligro.get("evidencia_visible", ""),
    }
    for jerarquia in JERARQUIA:
        valores[jerarquia] = _lista(controles_propuestos.get(jerarquia) or [])

    linea = Side(style="thin", color=LINEA)
    for indice, (clave, _, _, _) in enumerate(COLUMNAS, start=1):
        valor = valores[clave]
        celda = hoja.cell(row=fila, column=indice, value=valor if valor != "" else None)
        celda.font = Font(size=10, color=NEGRO)
        celda.border = Border(left=linea, right=linea, top=linea, bottom=linea)
        celda.alignment = Alignment(horizontal="center" if clave in _CENTRADAS else "left",
                                    vertical="top", wrap_text=True)
        if clave in _CON_COLOR_DE_NIVEL:
            celda.fill = _relleno(nivel["color"].lstrip("#"))
            celda.font = Font(size=10, bold=True, color=nivel["color_texto"].lstrip("#"))
        if clave == "requisito_legal":
            celda.comment = Comment(NOTA_REQUISITO_LEGAL, "Auren · SST en vivo")
    hoja.row_dimensions[fila].height = _alto_de_fila(valores)


def _alto_de_fila(valores: dict[str, Any]) -> float:
    """Alto de la fila para que quepa la celda con más renglones (Excel no lo ajusta solo al abrir)."""
    renglones = 1
    for clave, _, _, ancho in COLUMNAS:
        texto = _texto(valores.get(clave))
        if not texto:
            continue
        # Caracteres por renglón: algo menos que el ancho, porque el corte es por palabras
        # (y las celdas en negrita ocupan más)
        por_renglon = max(1, int(ancho * (0.8 if clave in _CON_COLOR_DE_NIVEL else 0.92)))
        renglones = max(renglones, sum(max(1, math.ceil(len(parrafo) / por_renglon))
                                       for parrafo in texto.split("\n")))
    return max(30.0, renglones * ALTO_LINEA_PT + 8)


def _notas(hoja, fila: int, parametros: dict, ultima: int) -> None:
    niveles = ", ".join(f"{tramo['id']} ({tramo['rango']})" for tramo in parametros["nivel_riesgo"])
    notas = [
        (parametros.get("sin_valor_de_deficiencia") or {}).get("nota"),
        f"Requisito legal: {NOTA_REQUISITO_LEGAL.lower()}. La IA no cita normas ni artículos.",
        "La frecuencia de la tarea, el número de expuestos y los controles existentes los aportó la persona; "
        "la foto no los muestra.",
        f"NP = ND x NE. NR = NP x NC. Niveles de riesgo: {niveles}.",
        LEMA,
    ]
    hoja.cell(row=fila, column=1, value="Notas").font = Font(bold=True, size=10, color=DEEP)
    for nota in (texto for texto in notas if texto):
        fila += 1
        hoja.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=min(ultima, 12))
        celda = hoja.cell(row=fila, column=1, value=nota)
        celda.font = Font(size=9, color=NEGRO, bold=nota == LEMA)
        celda.alignment = Alignment(vertical="center", wrap_text=True)


# --------------------------------------------------------------------------- #
# Textos
# --------------------------------------------------------------------------- #
def _texto(valor: Any) -> str:
    return str(valor).strip() if valor is not None else ""


def _si_no(valor: Any) -> str:
    if valor is None or valor == "":
        return ""
    return "Sí" if valor else "No"


def _clasificacion(clasificacion: dict) -> str:
    categoria = CATEGORIAS.get(clasificacion.get("categoria"), _texto(clasificacion.get("categoria")))
    subcategoria = _texto(clasificacion.get("subcategoria"))
    return f"{categoria} – {subcategoria}" if subcategoria else categoria


def _lista(textos: list[str]) -> str:
    if len(textos) <= 1:
        return "".join(textos)
    return "\n".join(f"• {texto}" for texto in textos)
