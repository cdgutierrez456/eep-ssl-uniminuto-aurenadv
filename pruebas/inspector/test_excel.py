"""Matriz IPEVR en Excel: columnas, aviso de borrador, requisito legal vacío y estilo."""

import copy
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

from modulos.inspector.ejemplo import ALTO, ANCHO, generar_ejemplo, leer_ejemplo
from modulos.inspector.nucleo.esquema import normalizar_analisis
from modulos.inspector.nucleo.excel import (
    AVISO_BORRADOR,
    COLUMNAS,
    DEEP,
    FILA_AVISO,
    FILA_BLOQUE,
    FILA_DATOS,
    FILA_ENCABEZADOS,
    FILA_FECHA,
    FILA_GRUPOS,
    FILA_TITULO,
    LEMA,
    LIMA,
    MARFIL,
    NOMBRE_HOJA,
    NOTA_REQUISITO_LEGAL,
    columna_de,
    generar_excel,
    titulos_de_columnas,
)
from modulos.inspector.nucleo.matriz import valorar_peligros
from modulos.inspector.nucleo.valoracion import datos_del_nivel

FECHA = datetime(2026, 11, 14, 10, 32, tzinfo=ZoneInfo("America/Bogota"))
NOTA_ND_BAJO = "ND bajo: la metodología no asigna valor numérico; el peligro se considera aceptable (nivel IV)"

# Las columnas que debe tener la matriz, en orden
TITULOS = [
    "N.º", "Proceso", "Zona / lugar", "Actividad", "Tarea", "Rutinaria (sí/no)",
    "Descripción del peligro", "Clasificación", "Efectos posibles",
    "Fuente", "Medio", "Individuo",
    "ND", "NE", "NP", "Interpretación NP", "NC", "NR", "Interpretación NR",
    "Aceptabilidad del riesgo",
    "N.º de expuestos", "Peor consecuencia", "Requisito legal",
    "Eliminación", "Sustitución", "Controles de ingeniería", "Controles administrativos", "EPP",
    "Confianza de la IA", "Evidencia visible",
]


def color(objeto) -> str:
    """Últimos seis caracteres del color (openpyxl le antepone la transparencia)."""
    return (objeto.rgb or "")[-6:].upper() if objeto is not None and isinstance(objeto.rgb, str) else ""


@pytest.fixture(scope="module")
def valorados() -> list[dict]:
    analisis = normalizar_analisis(leer_ejemplo("analisis_bodega.json"), ANCHO, ALTO)
    return valorar_peligros(analisis["peligros"], leer_ejemplo("respuestas_bodega.json")["peligros"])


@pytest.fixture(scope="module")
def hoja(tmp_path_factory):
    """La hoja del Excel de ejemplo, leída de vuelta."""
    rutas = generar_ejemplo(tmp_path_factory.mktemp("ejemplo"), FECHA)
    libro = load_workbook(rutas["excel"])
    assert libro.sheetnames == [NOMBRE_HOJA]
    return libro[NOMBRE_HOJA]


def fila_de_datos(hoja, numero: int) -> dict:
    """Valores de la fila del peligro ``numero``, por clave de columna."""
    fila = FILA_DATOS + numero - 1
    return {clave: hoja.cell(row=fila, column=indice).value for indice, (clave, *_) in enumerate(COLUMNAS, start=1)}


def textos_de_la_columna_a(hoja) -> list[str]:
    return [celda.value for celda in hoja["A"] if isinstance(celda.value, str)]


# --------------------------------------------------------------------------- #
# Encabezado y aviso de borrador
# --------------------------------------------------------------------------- #
def test_el_aviso_de_borrador_y_la_fecha_encabezan_la_hoja(hoja):
    assert AVISO_BORRADOR == "BORRADOR — Generado con IA. Debe ser validado en campo por un profesional de SST."
    assert hoja.cell(row=FILA_TITULO, column=1).value.startswith("Matriz de identificación de peligros")
    assert hoja.cell(row=FILA_AVISO, column=1).value == AVISO_BORRADOR
    assert hoja.cell(row=FILA_FECHA, column=1).value == "Fecha: 14/11/2026 10:32   ·   Inspección: ejemplo"
    assert (FILA_TITULO, FILA_AVISO, FILA_FECHA) == (1, 2, 3)


def test_el_aviso_va_en_negrita_sobre_fondo_oscuro(hoja):
    aviso = hoja.cell(row=FILA_AVISO, column=1)
    assert aviso.font.bold and color(aviso.font.color) == MARFIL
    assert color(aviso.fill.start_color) == "111414"


def test_el_lema_cierra_las_notas(hoja):
    assert LEMA == "Borrador generado con IA. La IA propone, el profesional de SST decide."
    assert textos_de_la_columna_a(hoja)[-1] == LEMA


# --------------------------------------------------------------------------- #
# Columnas
# --------------------------------------------------------------------------- #
def test_las_columnas_son_las_de_una_matriz_ipevr(hoja):
    assert titulos_de_columnas() == TITULOS
    encabezados = [hoja.cell(row=FILA_ENCABEZADOS, column=indice).value for indice in range(1, len(TITULOS) + 1)]
    assert encabezados == TITULOS
    assert hoja.cell(row=FILA_ENCABEZADOS, column=len(TITULOS) + 1).value is None  # no hay columnas de más


def test_los_grupos_de_columnas(hoja):
    grupos = [hoja.cell(row=FILA_GRUPOS, column=indice).value for indice in range(1, len(COLUMNAS) + 1)]
    assert [grupo for grupo in grupos if grupo] == [
        "Identificación", "Peligro", "Controles existentes", "Evaluación del riesgo", "Valoración del riesgo",
        "Criterios para establecer controles", "Medidas de intervención", "Análisis de la IA",
    ]
    # Cada grupo empieza sobre su primera columna
    assert grupos[columna_de("control_fuente") - 1] == "Controles existentes"
    assert grupos[columna_de("nd") - 1] == "Evaluación del riesgo"
    assert grupos[columna_de("eliminacion") - 1] == "Medidas de intervención"


def test_los_encabezados_van_en_auren_deep_con_texto_marfil(hoja):
    for fila in (FILA_GRUPOS, FILA_ENCABEZADOS):
        for indice in range(1, len(COLUMNAS) + 1):
            celda = hoja.cell(row=fila, column=indice)
            if isinstance(celda, MergedCell):  # al leer, solo la primera celda de un grupo trae estilo
                continue
            assert color(celda.fill.start_color) == DEEP, celda.coordinate
            assert celda.font.bold and color(celda.font.color) == MARFIL, celda.coordinate
    assert (DEEP, MARFIL) == ("12343B", "F2F1EA")
    assert color(hoja.cell(row=FILA_TITULO, column=1).fill.start_color) == DEEP


def test_el_lima_es_solo_un_acento(hoja):
    """Ni fondos ni textos en lima: solo la línea bajo el aviso de borrador."""
    lineas_lima = 0
    for fila in hoja.iter_rows():
        for celda in fila:
            assert color(celda.fill.start_color) != LIMA, celda.coordinate
            assert color(celda.font.color) != LIMA, celda.coordinate
            if color(celda.border.bottom.color) == LIMA:
                lineas_lima += 1
                assert celda.row == FILA_AVISO
    assert lineas_lima == len(COLUMNAS)


# --------------------------------------------------------------------------- #
# Filas
# --------------------------------------------------------------------------- #
def test_hay_una_fila_por_peligro_no_descartado(hoja, valorados):
    assert len(valorados) == 5
    numeros = [hoja.cell(row=FILA_DATOS + i, column=1).value for i in range(len(valorados))]
    assert numeros == [1, 2, 3, 4, 5]
    assert hoja.cell(row=FILA_DATOS + len(valorados), column=1).value is None
    assert not any("derrame" in (fila_de_datos(hoja, n)["descripcion"] or "") for n in range(1, 6))


def test_la_fila_del_primer_peligro(hoja):
    fila = fila_de_datos(hoja, 1)
    assert fila["proceso"] == "Almacenamiento" and fila["zona"] == "Bodega de producto terminado"
    assert fila["actividad"] == "Almacenamiento y despacho" and fila["tarea"] == "Ubicar cajas en la estantería"
    assert fila["rutinaria"] == "Sí"
    assert fila["descripcion"] == "Trabajador sobre escalera de tijera manipulando cajas sobre el nivel de los hombros"
    assert fila["clasificacion"] == "Condiciones de seguridad – trabajo en alturas"
    assert fila["efectos"] == "Fracturas, traumas y contusiones por caída a distinto nivel"
    assert (fila["control_fuente"], fila["control_medio"], fila["control_individuo"]) == ("Ninguno", "Ninguno", "EPP")
    assert (fila["nd"], fila["ne"], fila["np"], fila["interpretacion_np"]) == (6, 3, 18, "Alto")
    assert (fila["nc"], fila["nr"]) == (60, 1080)
    assert fila["interpretacion_nr"].startswith("I — Situación crítica")
    assert fila["aceptabilidad"] == "No aceptable"
    assert fila["expuestos"] == 2
    assert fila["peor_consecuencia"] == "Trauma craneoencefálico por caída"
    assert fila["eliminacion"] == "Ubicar la mercancía de alta rotación en niveles alcanzables desde el piso"
    assert fila["administrativos"] == ("• Definir un procedimiento de trabajo seguro para tareas en altura\n"
                                       "• Asignar un ayudante que sostenga la escalera y reciba la carga")
    assert fila["epp"] == "• Casco con barbuquejo\n• Calzado de seguridad antideslizante"
    assert fila["confianza"] == "Alta"
    assert fila["evidencia"].startswith("La persona está en los peldaños superiores")


def test_los_niveles_de_riesgo_del_ejemplo(hoja):
    niveles = [fila_de_datos(hoja, n)["interpretacion_nr"].split(" — ")[0] for n in range(1, 6)]
    assert niveles == ["I", "II", "II", "III", "IV"]
    aceptabilidad = [fila_de_datos(hoja, n)["aceptabilidad"] for n in range(1, 6)]
    assert aceptabilidad == ["No aceptable", "No aceptable o aceptable con control específico",
                             "No aceptable o aceptable con control específico", "Mejorable", "Aceptable"]


def test_el_nivel_de_riesgo_se_distingue_por_color(hoja):
    for numero, nivel in enumerate(["I", "II", "II", "III", "IV"], start=1):
        esperado = datos_del_nivel(nivel)["color"].lstrip("#").upper()
        for clave in ("interpretacion_nr", "aceptabilidad"):
            celda = hoja.cell(row=FILA_DATOS + numero - 1, column=columna_de(clave))
            assert color(celda.fill.start_color) == esperado, celda.coordinate


def test_con_deficiencia_baja_np_y_nr_quedan_en_blanco_y_el_nivel_es_iv(hoja):
    fila = fila_de_datos(hoja, 5)
    assert fila["nd"] == "Bajo"
    assert fila["np"] is None and fila["interpretacion_np"] is None and fila["nr"] is None
    assert (fila["ne"], fila["nc"]) == (2, 25)
    assert fila["interpretacion_nr"].startswith("IV — ")
    assert fila["aceptabilidad"] == "Aceptable"


def test_la_nota_al_pie_de_la_deficiencia_baja(hoja):
    assert NOTA_ND_BAJO in textos_de_la_columna_a(hoja)


# --------------------------------------------------------------------------- #
# Requisito legal: siempre vacío
# --------------------------------------------------------------------------- #
def test_el_requisito_legal_queda_vacio_con_la_nota_para_el_profesional(hoja, valorados):
    assert NOTA_REQUISITO_LEGAL == "A completar por el profesional"
    columna = columna_de("requisito_legal")
    assert hoja.cell(row=FILA_ENCABEZADOS, column=columna).value == "Requisito legal"
    for desplazamiento in range(len(valorados)):
        celda = hoja.cell(row=FILA_DATOS + desplazamiento, column=columna)
        assert celda.value is None, celda.coordinate
        assert celda.comment is not None and celda.comment.text == NOTA_REQUISITO_LEGAL, celda.coordinate
    assert any(texto.startswith("Requisito legal: a completar por el profesional")
               for texto in textos_de_la_columna_a(hoja))


def test_el_requisito_legal_queda_vacio_aunque_los_datos_traigan_uno(tmp_path, valorados):
    """Si un peligro llegara con una norma (el modelo no debe darla), no se escribe en la matriz."""
    con_norma = copy.deepcopy(valorados)
    for peligro in con_norma:
        peligro["requisito_legal"] = "Resolución 0000 de 2000"
        peligro["normas"] = ["Artículo 1"]
    ruta = generar_excel(tmp_path / "matriz.xlsx", con_norma, fecha=FECHA)
    hoja = load_workbook(ruta)[NOMBRE_HOJA]

    columna = columna_de("requisito_legal")
    assert all(hoja.cell(row=FILA_DATOS + i, column=columna).value is None for i in range(len(con_norma)))
    for fila in hoja.iter_rows():
        for celda in fila:
            assert "Resolución 0000" not in str(celda.value or ""), celda.coordinate
            assert "Artículo 1" not in str(celda.value or ""), celda.coordinate


# --------------------------------------------------------------------------- #
# Miniatura y datos generales
# --------------------------------------------------------------------------- #
def test_la_miniatura_de_la_foto_va_incrustada(hoja):
    assert len(hoja._images) == 1
    dibujo = hoja._images[0]
    assert dibujo.anchor._from.row == FILA_BLOQUE - 1 and dibujo.anchor._from.col == 0
    # Tamaño con que se ve en la hoja (viene en EMU: 9525 por píxel)
    ancho_px, alto_px = dibujo.anchor.ext.width / 9525, dibujo.anchor.ext.height / 9525
    assert ancho_px <= 640.5 and alto_px <= 415.5
    assert abs(ancho_px / alto_px - 4 / 3) < 0.01  # sin deformar la foto
    # Va incrustada con más detalle del que se muestra, para que aguante el zoom
    assert dibujo.width > ancho_px * 1.5


def test_los_datos_generales_acompanan_a_la_miniatura(hoja):
    lineas = [hoja.cell(row=FILA_BLOQUE + i, column=7).value for i in range(8)]
    assert lineas[0].startswith("Escena: Bodega de almacenamiento con estantería metálica")
    assert lineas[1:6] == ["Proceso: Almacenamiento", "Zona / lugar: Bodega de producto terminado",
                           "Actividad: Almacenamiento y despacho", "Tarea: Ubicar cajas en la estantería",
                           "Rutinaria: Sí"]
    assert lineas[6] == ("Advertencias de la imagen: No se ve la parte alta de la estantería; "
                         "Iluminación desigual hacia el fondo")
    assert lineas[7] == "Peligros en la matriz: 5"


def test_sin_contexto_ni_imagen_los_campos_quedan_en_blanco(tmp_path, valorados):
    ruta = generar_excel(tmp_path / "sin contexto ñ" / "matriz.xlsx", valorados, fecha=FECHA)
    hoja = load_workbook(ruta)[NOMBRE_HOJA]

    assert len(hoja._images) == 0
    assert hoja.cell(row=FILA_AVISO, column=1).value == AVISO_BORRADOR
    assert hoja.cell(row=FILA_FECHA, column=1).value == "Fecha: 14/11/2026 10:32"
    for numero in range(1, len(valorados) + 1):
        fila = fila_de_datos(hoja, numero)
        assert [fila[clave] for clave in ("proceso", "zona", "actividad", "tarea", "rutinaria")] == [None] * 5
        assert fila["descripcion"]
    assert hoja.cell(row=FILA_BLOQUE + 1, column=7).value == "Proceso: "


def test_rutinaria_no_y_expuestos_sin_dato(tmp_path, valorados):
    peligros = copy.deepcopy(valorados[:1])
    peligros[0]["expuestos"] = None
    peligros[0]["controles_existentes"] = {"fuente": "", "medio": "", "individuo": ""}
    ruta = generar_excel(tmp_path / "matriz.xlsx", peligros, contexto={"rutinaria": False}, fecha=FECHA)
    fila = fila_de_datos(load_workbook(ruta)[NOMBRE_HOJA], 1)
    assert fila["rutinaria"] == "No" and fila["expuestos"] is None
    assert (fila["control_fuente"], fila["control_medio"], fila["control_individuo"]) == (None, None, None)


def test_una_matriz_sin_peligros_conserva_encabezados_y_notas(tmp_path):
    ruta = generar_excel(tmp_path / "vacia.xlsx", [], descripcion_general="Oficina sin peligros visibles",
                         imagen=np.full((600, 800, 3), 120, np.uint8), fecha=FECHA)
    hoja = load_workbook(ruta)[NOMBRE_HOJA]
    assert hoja.cell(row=FILA_AVISO, column=1).value == AVISO_BORRADOR
    assert hoja.cell(row=FILA_ENCABEZADOS, column=1).value == "N.º"
    assert hoja.cell(row=FILA_DATOS, column=1).value is None
    assert hoja.cell(row=FILA_BLOQUE + 7, column=7).value == "Peligros en la matriz: 0"
    assert LEMA in textos_de_la_columna_a(hoja) and NOTA_ND_BAJO in textos_de_la_columna_a(hoja)
    assert len(hoja._images) == 1


def test_la_confianza_baja_se_marca_como_posible(tmp_path, valorados):
    peligros = copy.deepcopy(valorados[:1])
    peligros[0]["confianza"] = "baja"
    ruta = generar_excel(tmp_path / "matriz.xlsx", peligros, fecha=FECHA)
    assert fila_de_datos(load_workbook(ruta)[NOMBRE_HOJA], 1)["confianza"] == "Baja — posible, verificar"
