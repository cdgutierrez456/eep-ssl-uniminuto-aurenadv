"""Unión de los peligros propuestos con las respuestas de la persona."""

import copy

import pytest

from modulos.inspector.ejemplo import ALTO, ANCHO, leer_ejemplo
from modulos.inspector.nucleo.esquema import normalizar_analisis
from modulos.inspector.nucleo.matriz import RespuestasInvalidas, repartir_controles_existentes, valorar_peligros


@pytest.fixture
def peligros() -> list[dict]:
    return normalizar_analisis(leer_ejemplo("analisis_bodega.json"), ANCHO, ALTO)["peligros"]


@pytest.fixture
def respuestas() -> list[dict]:
    return leer_ejemplo("respuestas_bodega.json")["peligros"]


def test_el_ejemplo_queda_valorado_sin_el_peligro_descartado(peligros, respuestas):
    valorados = valorar_peligros(peligros, respuestas)

    assert [peligro["n"] for peligro in valorados] == [1, 2, 3, 4, 5]
    assert [peligro["n_original"] for peligro in valorados] == [1, 2, 3, 4, 5]
    assert [peligro["valoracion"]["nivel_riesgo"] for peligro in valorados] == ["I", "II", "II", "III", "IV"]
    assert [peligro["valoracion"]["nr"] for peligro in valorados] == [1080, 200, 240, 50, None]
    assert [peligro["exposicion"] for peligro in valorados] == [
        "frecuente", "continua", "ocasional", "esporadica", "ocasional"]
    assert [peligro["expuestos"] for peligro in valorados] == [2, 6, 6, 4, 2]
    # Lo que propuso la IA sigue ahí: descripción, evidencia, controles, ubicación
    assert valorados[0]["descripcion"].startswith("Trabajador sobre escalera")
    assert valorados[0]["controles_propuestos"]["epp"] == ["Casco con barbuquejo", "Calzado de seguridad antideslizante"]
    assert valorados[0]["ubicacion"] == peligros[0]["ubicacion"]


def test_al_descartar_un_peligro_los_demas_se_renumeran(peligros, respuestas):
    respuestas[1] = {"n": 2, "descartado": True}
    valorados = valorar_peligros(peligros, respuestas)
    assert [(peligro["n"], peligro["n_original"]) for peligro in valorados] == [(1, 1), (2, 3), (3, 4), (4, 5)]


def test_si_se_descartan_todos_no_queda_ninguno(peligros):
    assert valorar_peligros(peligros, [{"n": n, "descartado": True} for n in range(1, 7)]) == []


def test_la_persona_puede_ajustar_la_deficiencia_y_la_consecuencia(peligros, respuestas):
    respuestas[0].update(nivel_deficiencia="muy_alto", consecuencia="mortal")
    valorados = valorar_peligros(peligros, respuestas)

    assert valorados[0]["nivel_deficiencia"] == "muy_alto" and valorados[0]["consecuencia"] == "mortal"
    assert valorados[0]["ajustado"] == {"nivel_deficiencia": True, "consecuencia": True}
    assert valorados[0]["valoracion"]["nr"] == 10 * 3 * 100
    # El peligro 5 del ejemplo ajusta solo la deficiencia; el 2 no ajusta nada
    assert valorados[4]["ajustado"] == {"nivel_deficiencia": True, "consecuencia": False}
    assert valorados[1]["ajustado"] == {"nivel_deficiencia": False, "consecuencia": False}
    assert valorados[1]["nivel_deficiencia"] == peligros[1]["nivel_deficiencia_propuesto"]
    # Lo propuesto por la IA no se pierde
    assert valorados[0]["nivel_deficiencia_propuesto"] == "alto"


def test_no_modifica_los_peligros_ni_las_respuestas(peligros, respuestas):
    peligros_antes, respuestas_antes = copy.deepcopy(peligros), copy.deepcopy(respuestas)
    valorados = valorar_peligros(peligros, respuestas)
    valorados[0]["controles_propuestos"]["epp"].append("otro")
    assert peligros == peligros_antes and respuestas == respuestas_antes


def test_el_numero_de_expuestos_es_opcional(peligros, respuestas):
    respuestas[0].pop("expuestos")
    respuestas[1]["expuestos"] = None
    valorados = valorar_peligros(peligros, respuestas)
    assert valorados[0]["expuestos"] is None and valorados[1]["expuestos"] is None


@pytest.mark.parametrize(
    "cambio, mensaje",
    [
        (lambda r: r.pop(0), "Falta la respuesta de los peligros: 1"),
        (lambda r: r[0].pop("frecuencia"), "Falta la frecuencia de la tarea del peligro 1"),
        (lambda r: r[0].update(frecuencia="diaria"), "Peligro 1"),
        (lambda r: r[0].update(nivel_deficiencia="critico"), "Peligro 1"),
        (lambda r: r[0].update(consecuencia="fatal"), "Peligro 1"),
        (lambda r: r.append({"n": 9, "descartado": True}), "no existe"),
        (lambda r: r.append({"n": 1, "frecuencia": "continua"}), "más de una respuesta"),
        (lambda r: r.append({"frecuencia": "continua"}), "no existe"),
        (lambda r: r[0].update(expuestos=0), "expuestos"),
        (lambda r: r[0].update(expuestos="3"), "expuestos"),
        (lambda r: r[0].update(expuestos=True), "expuestos"),
        (lambda r: r[0].update(controles_existentes=["casco"]), "no es un control existente"),
    ],
)
def test_respuestas_incompletas_o_con_valores_que_no_existen(peligros, respuestas, cambio, mensaje):
    cambio(respuestas)
    with pytest.raises(RespuestasInvalidas, match=mensaje):
        valorar_peligros(peligros, respuestas)


def test_las_respuestas_deben_ser_una_lista(peligros):
    with pytest.raises(RespuestasInvalidas):
        valorar_peligros(peligros, {"1": {"frecuencia": "continua"}})


# --------------------------------------------------------------------------- #
# Controles existentes: fuente, medio, individuo
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "marcados, otros, esperado",
    [
        (["epp"], "", {"fuente": "Ninguno", "medio": "Ninguno", "individuo": "EPP"}),
        (["proteccion_maquina"], "", {"fuente": "Protección en la máquina", "medio": "Ninguno", "individuo": "Ninguno"}),
        (["senalizacion", "procedimiento", "epp"], "",
         {"fuente": "Ninguno", "medio": "Señalización", "individuo": "Procedimiento, EPP"}),
        (["ninguno"], "", {"fuente": "Ninguno", "medio": "Ninguno", "individuo": "Ninguno"}),
        (["ninguno", "epp"], "", {"fuente": "Ninguno", "medio": "Ninguno", "individuo": "EPP"}),
        ([], "Inspección mensual de estanterías",
         {"fuente": "Ninguno", "medio": "Inspección mensual de estanterías", "individuo": "Ninguno"}),
        (["senalizacion"], " Demarcación del piso ",
         {"fuente": "Ninguno", "medio": "Señalización, Demarcación del piso", "individuo": "Ninguno"}),
        ([], "", {"fuente": "", "medio": "", "individuo": ""}),     # sin respuesta: en blanco, no "Ninguno"
        (None, None, {"fuente": "", "medio": "", "individuo": ""}),
    ],
)
def test_reparto_de_controles_existentes(marcados, otros, esperado):
    assert repartir_controles_existentes(marcados, otros) == esperado


def test_los_controles_existentes_llegan_a_cada_peligro(peligros, respuestas):
    valorados = valorar_peligros(peligros, respuestas)
    assert valorados[0]["controles_existentes"] == {"fuente": "Ninguno", "medio": "Ninguno", "individuo": "EPP"}
    assert valorados[1]["controles_existentes"] == {"fuente": "Ninguno", "medio": "Ninguno", "individuo": "Ninguno"}
    assert valorados[3]["controles_existentes"]["medio"] == "Inspección mensual de estanterías"
