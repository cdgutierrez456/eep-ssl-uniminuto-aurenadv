"""Valoración del riesgo: todas las combinaciones de ND, NE y NC y sus interpretaciones."""

import itertools
import json

import pytest

from modulos.inspector.nucleo.valoracion import (
    ParametrosInvalidos,
    Valoracion,
    cargar_parametros,
    datos_del_nivel,
    peor_nivel,
    severidad_del_evento,
    valorar,
)

ND = {"muy_alto": 10, "alto": 6, "medio": 2, "bajo": None}
NE = {"continua": 4, "frecuente": 3, "ocasional": 2, "esporadica": 1}
NC = {"mortal": 100, "muy_grave": 60, "grave": 25, "leve": 10}

# Los rangos tal como se acordaron (cerrados, no por umbral): sirven para comprobar que
# ningún producto real cae en un hueco entre rangos.
RANGOS_NP = {"Muy alto": (24, 40), "Alto": (10, 20), "Medio": (6, 8), "Bajo": (2, 4)}
RANGOS_NR = {"I": (600, 4000), "II": (150, 500), "III": (40, 120), "IV": (20, 20)}
ACEPTABILIDAD = {
    "I": "No aceptable",
    "II": "No aceptable o aceptable con control específico",
    "III": "Mejorable",
    "IV": "Aceptable",
}
NIVEL_PRELIMINAR = {"I": "muy_alto", "II": "alto", "III": "medio", "IV": "bajo"}
SEVERIDAD = {"I": "critica", "II": "alta", "III": "media", "IV": "baja"}
NOTA_ND_BAJO = "ND bajo: la metodología no asigna valor numérico; el peligro se considera aceptable (nivel IV)"

COMBINACIONES = list(itertools.product(ND, NE, NC))


def en_rango(valor: int, rangos: dict) -> str:
    """Nombre del único rango cerrado que contiene el valor."""
    encontrados = [nombre for nombre, (minimo, maximo) in rangos.items() if minimo <= valor <= maximo]
    assert len(encontrados) == 1, f"{valor} no cae en exactamente un rango: {encontrados}"
    return encontrados[0]


def test_son_las_64_combinaciones():
    assert len(COMBINACIONES) == 4 * 4 * 4


@pytest.mark.parametrize("deficiencia, exposicion, consecuencia", COMBINACIONES)
def test_cada_combinacion_de_nd_ne_y_nc(deficiencia, exposicion, consecuencia):
    valoracion = valorar(deficiencia, exposicion, consecuencia)

    assert (valoracion.deficiencia, valoracion.exposicion, valoracion.consecuencia) == (
        deficiencia, exposicion, consecuencia)
    assert valoracion.nd == ND[deficiencia]
    assert valoracion.ne == NE[exposicion]
    assert valoracion.nc == NC[consecuencia]

    if ND[deficiencia] is None:
        # Deficiencia baja: sin NP ni NR, directo a nivel IV
        assert valoracion.np is None and valoracion.interpretacion_np is None and valoracion.nr is None
        assert valoracion.nivel_riesgo == "IV"
        assert valoracion.nota == NOTA_ND_BAJO
    else:
        np_esperado = ND[deficiencia] * NE[exposicion]
        nr_esperado = np_esperado * NC[consecuencia]
        assert valoracion.np == np_esperado
        assert valoracion.interpretacion_np == en_rango(np_esperado, RANGOS_NP)
        assert valoracion.nr == nr_esperado
        assert valoracion.nivel_riesgo == en_rango(nr_esperado, RANGOS_NR)
        assert valoracion.nota is None

    assert valoracion.aceptabilidad == ACEPTABILIDAD[valoracion.nivel_riesgo]
    assert valoracion.nivel_preliminar == NIVEL_PRELIMINAR[valoracion.nivel_riesgo]
    assert valoracion.severidad == SEVERIDAD[valoracion.nivel_riesgo]
    assert valoracion.significado


@pytest.mark.parametrize(
    "deficiencia, exposicion, consecuencia, np_, interpretacion_np, nr, nivel",
    [
        ("muy_alto", "continua", "mortal", 40, "Muy alto", 4000, "I"),
        ("alto", "frecuente", "muy_grave", 18, "Alto", 1080, "I"),
        ("alto", "esporadica", "mortal", 6, "Medio", 600, "I"),        # límite inferior de I
        ("muy_alto", "ocasional", "grave", 20, "Alto", 500, "II"),      # límite superior de II
        ("alto", "esporadica", "grave", 6, "Medio", 150, "II"),         # límite inferior de II
        ("alto", "ocasional", "leve", 12, "Alto", 120, "III"),          # límite superior de III
        ("medio", "ocasional", "leve", 4, "Bajo", 40, "III"),           # límite inferior de III
        ("medio", "esporadica", "leve", 2, "Bajo", 20, "IV"),
        ("alto", "continua", "leve", 24, "Muy alto", 240, "II"),        # límite inferior de NP muy alto
    ],
)
def test_casos_conocidos_y_limites_de_rango(deficiencia, exposicion, consecuencia, np_, interpretacion_np, nr, nivel):
    valoracion = valorar(deficiencia, exposicion, consecuencia)
    assert (valoracion.np, valoracion.interpretacion_np, valoracion.nr, valoracion.nivel_riesgo) == (
        np_, interpretacion_np, nr, nivel)


def test_deficiencia_baja_es_nivel_iv_aceptable_aunque_la_consecuencia_sea_mortal():
    valoracion = valorar("bajo", "continua", "mortal")
    assert valoracion.nd is None and valoracion.np is None and valoracion.nr is None
    assert (valoracion.nivel_riesgo, valoracion.aceptabilidad) == ("IV", "Aceptable")
    assert (valoracion.nivel_preliminar, valoracion.severidad) == ("bajo", "baja")
    assert (valoracion.ne, valoracion.nc) == (4, 100)  # lo que respondió la persona se conserva


@pytest.mark.parametrize(
    "escala, clave, valor, combinacion, nr, nivel",
    [
        ("nivel_consecuencia", "leve", 13, ("medio", "esporadica", "leve"), 26, "IV"),      # hueco 21–39
        ("nivel_consecuencia", "leve", 65, ("medio", "esporadica", "leve"), 130, "III"),    # hueco 121–149
        ("nivel_consecuencia", "leve", 30, ("alto", "frecuente", "leve"), 540, "II"),       # hueco 501–599
        ("nivel_consecuencia", "mortal", 200, ("muy_alto", "continua", "mortal"), 8000, "I"),  # sobre el máximo
    ],
)
def test_un_valor_en_un_hueco_entre_rangos_se_clasifica_por_umbral_inferior(escala, clave, valor, combinacion, nr,
                                                                           nivel):
    parametros = cargar_parametros()
    parametros[escala][clave]["valor"] = valor
    valoracion = valorar(*combinacion, parametros)
    assert (valoracion.nr, valoracion.nivel_riesgo) == (nr, nivel)


@pytest.mark.parametrize("argumentos", [("altisimo", "continua", "grave"), ("alto", "diaria", "grave"),
                                        ("alto", "continua", "fatal"), ("Alto", "continua", "grave")])
def test_un_nivel_que_no_existe_es_un_error(argumentos):
    with pytest.raises(ValueError):
        valorar(*argumentos)


def test_los_parametros_se_pueden_editar_sin_tocar_codigo(tmp_path):
    parametros = cargar_parametros()
    parametros["nivel_deficiencia"]["medio"]["valor"] = 4
    parametros["nivel_riesgo"][2]["aceptabilidad"] = "Aceptable con seguimiento"
    ruta = tmp_path / "parametros.json"
    ruta.write_text(json.dumps(parametros, ensure_ascii=False), encoding="utf-8")

    valoracion = valorar("medio", "ocasional", "leve", cargar_parametros(ruta))
    assert (valoracion.nd, valoracion.np, valoracion.nr, valoracion.nivel_riesgo) == (4, 8, 80, "III")
    assert valoracion.aceptabilidad == "Aceptable con seguimiento"
    # El archivo por defecto no cambió
    assert valorar("medio", "ocasional", "leve").nd == 2


def test_cargar_parametros_devuelve_una_copia():
    cargar_parametros()["nivel_exposicion"]["continua"]["valor"] = 99
    assert valorar("alto", "continua", "leve").ne == 4


@pytest.mark.parametrize(
    "romper",
    [
        lambda p: p.pop("nivel_riesgo"),
        lambda p: p["nivel_exposicion"]["continua"].update(valor=None),
        lambda p: p["nivel_consecuencia"]["leve"].update(valor="diez"),
        lambda p: p["nivel_probabilidad"][0].pop("desde"),
        lambda p: p["nivel_riesgo"][0].pop("aceptabilidad"),
        lambda p: p["sin_valor_de_deficiencia"].update(nivel_riesgo="V"),
    ],
)
def test_parametros_incompletos_se_rechazan(tmp_path, romper):
    parametros = cargar_parametros()
    romper(parametros)
    ruta = tmp_path / "parametros.json"
    ruta.write_text(json.dumps(parametros, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ParametrosInvalidos):
        cargar_parametros(ruta)


def test_parametros_que_no_existen_o_no_son_json(tmp_path):
    with pytest.raises(ParametrosInvalidos):
        cargar_parametros(tmp_path / "no_existe.json")
    ruta = tmp_path / "roto.json"
    ruta.write_text("{ esto no es json", encoding="utf-8")
    with pytest.raises(ParametrosInvalidos):
        cargar_parametros(ruta)


def test_peor_nivel_y_severidad_del_evento():
    assert peor_nivel(["III", "I", "IV"]) == "I"
    assert peor_nivel(["IV", "III"]) == "III"
    assert peor_nivel([]) is None
    assert severidad_del_evento(["IV", "II", "III"]) == "alta"
    assert severidad_del_evento(["I"]) == "critica"
    assert severidad_del_evento(["IV"]) == "baja"
    assert severidad_del_evento([]) == "info"


def test_datos_del_nivel_traen_color_y_rango():
    nivel = datos_del_nivel("II")
    assert nivel["rango"] == "150 a 500" and nivel["color"].startswith("#") and nivel["color_texto"].startswith("#")
    with pytest.raises(ValueError):
        datos_del_nivel("V")


def test_la_valoracion_se_convierte_a_diccionario():
    valoracion = valorar("alto", "frecuente", "grave")
    assert isinstance(valoracion, Valoracion)
    assert valoracion.como_dict() == {
        "deficiencia": "alto", "nd": 6,
        "exposicion": "frecuente", "ne": 3,
        "np": 18, "interpretacion_np": "Alto",
        "consecuencia": "grave", "nc": 25,
        "nr": 450,
        "nivel_riesgo": "II",
        "significado": "Corregir y aplicar medidas de control cuanto antes.",
        "aceptabilidad": "No aceptable o aceptable con control específico",
        "nivel_preliminar": "alto",
        "severidad": "alta",
        "nota": None,
    }
