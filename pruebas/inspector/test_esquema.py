"""Esquema de la salida del modelo: validación, versión para la API y forma interna."""

import copy
import json

import pytest
from jsonschema import Draft202012Validator

from modulos.comun.config import RAIZ_REPO
from modulos.inspector.ejemplo import ALTO, ANCHO, leer_ejemplo
from modulos.inspector.nucleo.esquema import (
    CATEGORIAS,
    JERARQUIA,
    AnalisisInvalido,
    cargar_esquema,
    esquema_para_api,
    normalizar_analisis,
    validar_analisis,
)

NO_ADMITIDAS = {"$schema", "$id", "$comment", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                "multipleOf", "minLength", "maxLength", "maxItems"}


@pytest.fixture
def analisis() -> dict:
    return leer_ejemplo("analisis_bodega.json")


def objetos(nodo, ruta="(raíz)"):
    """Recorre el esquema y entrega cada subesquema de tipo objeto con su ruta."""
    if isinstance(nodo, dict):
        if nodo.get("type") == "object":
            yield ruta, nodo
        for clave, valor in nodo.items():
            yield from objetos(valor, f"{ruta}/{clave}")
    elif isinstance(nodo, list):
        for indice, valor in enumerate(nodo):
            yield from objetos(valor, f"{ruta}/{indice}")


def palabras_clave(nodo):
    """Palabras clave usadas en el esquema, sin contar los nombres de propiedades y definiciones."""
    if isinstance(nodo, list):
        for valor in nodo:
            yield from palabras_clave(valor)
    elif isinstance(nodo, dict):
        for clave, valor in nodo.items():
            yield clave
            if clave in ("properties", "$defs") and isinstance(valor, dict):
                for definicion in valor.values():
                    yield from palabras_clave(definicion)
            else:
                yield from palabras_clave(valor)


# --------------------------------------------------------------------------- #
# El esquema
# --------------------------------------------------------------------------- #
def test_el_esquema_es_un_json_schema_valido_y_el_ejemplo_lo_cumple(analisis):
    Draft202012Validator.check_schema(cargar_esquema())
    validar_analisis(analisis)


def test_todo_objeto_es_cerrado_y_todas_sus_propiedades_son_obligatorias():
    """Lo exigen las salidas estructuradas de la API: additionalProperties false y nada opcional."""
    encontrados = list(objetos(cargar_esquema()))
    assert len(encontrados) == 4  # raíz, peligro, caja y controles
    for ruta, objeto in encontrados:
        assert objeto["additionalProperties"] is False, ruta
        assert set(objeto["required"]) == set(objeto["properties"]), ruta


def test_las_categorias_son_las_del_contrato_de_eventos():
    esquema = cargar_esquema()
    contrato = json.loads((RAIZ_REPO / "contrato" / "evento.schema.json").read_text(encoding="utf-8"))
    del_contrato = contrato["$defs"]["datos_inspeccion_foto"]["properties"]["peligros"]["items"]["properties"][
        "clasificacion"]["enum"]
    del_modelo = esquema["$defs"]["peligro"]["properties"]["categoria"]["enum"]
    assert del_modelo == del_contrato
    assert list(CATEGORIAS) == del_contrato


def test_los_controles_siguen_la_jerarquia():
    controles = cargar_esquema()["$defs"]["controles"]
    assert tuple(controles["properties"]) == JERARQUIA == (
        "eliminacion", "sustitucion", "ingenieria", "administrativos", "epp")


def test_la_version_para_la_api_no_lleva_restricciones_que_la_api_rechaza():
    original = cargar_esquema()
    para_api = esquema_para_api()

    assert NO_ADMITIDAS & set(palabras_clave(original))  # el esquema completo sí las usa
    assert not NO_ADMITIDAS & set(palabras_clave(para_api))
    # Lo demás se conserva: mismos objetos, propiedades, obligatorios y enumerados
    assert [ruta for ruta, _ in objetos(para_api)] == [ruta for ruta, _ in objetos(original)]
    for (_, limpio), (_, completo) in zip(objetos(para_api), objetos(original)):
        assert list(limpio["properties"]) == list(completo["properties"])
        assert limpio["required"] == completo["required"]
        assert limpio["additionalProperties"] is False
    assert para_api["$defs"]["peligro"]["properties"]["confianza"]["enum"] == ["alta", "media", "baja"]
    assert list(para_api["$defs"]["caja"]["properties"]) == ["x1", "y1", "x2", "y2"]
    assert para_api["properties"]["descripcion_general"]["description"]
    Draft202012Validator.check_schema(para_api)


def test_la_version_para_la_api_no_modifica_el_esquema_original():
    antes = cargar_esquema()
    esquema_para_api()
    assert cargar_esquema() == antes
    assert "minLength" in cargar_esquema()["properties"]["descripcion_general"]


def test_la_version_para_la_api_no_confunde_una_propiedad_con_una_palabra_clave():
    esquema = {"type": "object", "properties": {"minimum": {"type": "integer", "minimum": 0}}, "minItems": 3}
    assert esquema_para_api(esquema) == {"type": "object", "properties": {"minimum": {"type": "integer"}}}
    assert esquema_para_api({"type": "array", "minItems": 1}) == {"type": "array", "minItems": 1}


# --------------------------------------------------------------------------- #
# Validación
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "romper, pista",
    [
        (lambda a: a.pop("descripcion_general"), "descripcion_general"),
        (lambda a: a["peligros"][0].pop("evidencia_visible"), "evidencia_visible"),
        (lambda a: a["peligros"][0].update(requisito_legal="Resolución 0000"), "requisito_legal"),
        (lambda a: a["peligros"][0].update(exposicion="continua"), "exposicion"),
        (lambda a: a["peligros"][0].update(categoria="ergonomico"), "categoria"),
        (lambda a: a["peligros"][0].update(confianza="muy alta"), "confianza"),
        (lambda a: a["peligros"][1].update(nivel_deficiencia_propuesto="critico"), "nivel_deficiencia_propuesto"),
        (lambda a: a["peligros"][1].update(consecuencia_propuesta="fatal"), "consecuencia_propuesta"),
        (lambda a: a["peligros"][0]["ubicacion_px"].update(x2=0.5), "ubicacion_px"),
        (lambda a: a["peligros"][0]["ubicacion_px"].pop("y2"), "ubicacion_px"),
        (lambda a: a["peligros"][0]["controles_propuestos"].pop("epp"), "controles_propuestos"),
        (lambda a: a["peligros"][0]["controles_propuestos"].update(otros=[]), "controles_propuestos"),
        (lambda a: a["peligros"][0].update(descripcion=""), "descripcion"),
        (lambda a: a.update(advertencias="imagen oscura"), "advertencias"),
    ],
)
def test_una_salida_que_no_cumple_el_esquema_se_rechaza(analisis, romper, pista):
    romper(analisis)
    with pytest.raises(AnalisisInvalido, match=pista):
        validar_analisis(analisis)
    with pytest.raises(AnalisisInvalido):
        normalizar_analisis(analisis, ANCHO, ALTO)


def test_un_analisis_sin_peligros_es_valido():
    normalizado = normalizar_analisis({"descripcion_general": "Oficina vacía", "advertencias": [], "peligros": []},
                                      800, 600)
    assert normalizado == {"descripcion_general": "Oficina vacía", "advertencias": [], "peligros": []}


@pytest.mark.parametrize("basura", [None, [], "texto", 7])
def test_algo_que_no_es_un_objeto_se_rechaza(basura):
    with pytest.raises(AnalisisInvalido):
        normalizar_analisis(basura, 800, 600)


# --------------------------------------------------------------------------- #
# Forma interna
# --------------------------------------------------------------------------- #
def test_la_forma_interna_numera_los_peligros_y_pasa_las_cajas_a_0_1(analisis):
    normalizado = normalizar_analisis(analisis, ANCHO, ALTO)

    assert [peligro["n"] for peligro in normalizado["peligros"]] == [1, 2, 3, 4, 5, 6]
    primero = normalizado["peligros"][0]
    assert primero["ubicacion"] == [round(640 / 1568, 4), round(100 / 1176, 4), round(920 / 1568, 4),
                                    round(950 / 1176, 4)]
    assert primero["clasificacion"] == {"categoria": "condiciones_de_seguridad", "subcategoria": "trabajo en alturas"}
    assert primero["nivel_deficiencia_propuesto"] == "alto" and primero["consecuencia_propuesta"] == "muy_grave"
    assert list(primero["controles_propuestos"]) == list(JERARQUIA)
    assert "ubicacion_px" not in primero and "categoria" not in primero
    assert normalizado["descripcion_general"].startswith("Bodega de almacenamiento")
    assert normalizado["advertencias"] == analisis["advertencias"]


def test_las_cajas_quedan_ordenadas_dentro_de_la_imagen_y_con_area(analisis):
    analisis["peligros"][0]["ubicacion_px"] = {"x1": 900, "y1": 500, "x2": 300, "y2": 100}   # esquinas al revés
    analisis["peligros"][1]["ubicacion_px"] = {"x1": 1400, "y1": 1000, "x2": 2000, "y2": 1500}  # se sale
    analisis["peligros"][2]["ubicacion_px"] = {"x1": 700, "y1": 400, "x2": 700, "y2": 400}   # un punto
    analisis["peligros"][3]["ubicacion_px"] = {"x1": 1568, "y1": 1176, "x2": 1568, "y2": 1176}  # punto en la esquina
    cajas = [peligro["ubicacion"] for peligro in normalizar_analisis(analisis, ANCHO, ALTO)["peligros"]]

    assert cajas[0] == [round(300 / 1568, 4), round(100 / 1176, 4), round(900 / 1568, 4), round(500 / 1176, 4)]
    assert cajas[1] == [round(1400 / 1568, 4), round(1000 / 1176, 4), 1.0, 1.0]
    for x1, y1, x2, y2 in cajas:
        assert 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1
        assert x2 - x1 >= 0.0199 and y2 - y1 >= 0.0199


def test_una_caja_con_coordenadas_negativas_se_recorta_en_vez_de_rechazarse(analisis):
    """No vale un reintento (tiempo y dinero) por una caja que se sale un poco de la imagen."""
    analisis["peligros"][0]["ubicacion_px"] = {"x1": -40, "y1": -10, "x2": 400, "y2": 300}
    caja = normalizar_analisis(analisis, ANCHO, ALTO)["peligros"][0]["ubicacion"]
    assert caja == [0.0, 0.0, round(400 / 1568, 4), round(300 / 1176, 4)]


def test_si_el_modelo_devuelve_peligros_de_mas_se_conservan_los_primeros(analisis):
    analisis["peligros"] = analisis["peligros"] * 3  # 18 peligros
    assert len(normalizar_analisis(analisis, ANCHO, ALTO)["peligros"]) == 6
    assert len(normalizar_analisis(analisis, ANCHO, ALTO, max_peligros=12)["peligros"]) == 12


def test_se_conservan_solo_los_primeros_peligros_hasta_el_maximo(analisis):
    normalizado = normalizar_analisis(analisis, ANCHO, ALTO, max_peligros=3)
    assert [peligro["n"] for peligro in normalizado["peligros"]] == [1, 2, 3]
    assert normalizado["peligros"][2]["descripcion"].startswith("Extintor obstruido")
    assert len(normalizar_analisis(analisis, ANCHO, ALTO)["peligros"]) == 6  # el máximo por defecto es 6


def test_los_enumerados_se_aceptan_con_otra_capitalizacion(analisis):
    analisis["peligros"][0].update(confianza="Alta", categoria="Condiciones_De_Seguridad",
                                   nivel_deficiencia_propuesto=" ALTO ", consecuencia_propuesta="Muy_grave")
    original = copy.deepcopy(analisis)
    primero = normalizar_analisis(analisis, ANCHO, ALTO)["peligros"][0]
    assert primero["confianza"] == "alta"
    assert primero["clasificacion"]["categoria"] == "condiciones_de_seguridad"
    assert (primero["nivel_deficiencia_propuesto"], primero["consecuencia_propuesta"]) == ("alto", "muy_grave")
    assert analisis == original  # no modifica lo que recibió


def test_se_limpian_espacios_y_controles_vacios(analisis):
    analisis["peligros"][0]["descripcion"] = "  Trabajador sobre escalera  "
    analisis["peligros"][0]["controles_propuestos"]["epp"] = ["  Casco  ", "", "   "]
    analisis["advertencias"] = [" imagen oscura ", ""]
    normalizado = normalizar_analisis(analisis, ANCHO, ALTO)
    assert normalizado["peligros"][0]["descripcion"] == "Trabajador sobre escalera"
    assert normalizado["peligros"][0]["controles_propuestos"]["epp"] == ["Casco"]
    assert normalizado["advertencias"] == ["imagen oscura"]


def test_el_tamano_de_la_imagen_debe_ser_positivo(analisis):
    with pytest.raises(ValueError):
        normalizar_analisis(analisis, 0, 600)
