"""Une los peligros propuestos por la IA con las respuestas de la persona y los valora.

La persona decide: descarta los peligros que no considere válidos, ajusta la deficiencia
y la consecuencia propuestas, y aporta lo que la foto no muestra (frecuencia de la
tarea, número de expuestos y controles que existen hoy).
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

from .valoracion import RUTA_PARAMETROS, _leer, valorar

COLUMNAS_DE_CONTROLES = ("fuente", "medio", "individuo")
SIN_CONTROL = "Ninguno"


class RespuestasInvalidas(ValueError):
    """Las respuestas de exposición no corresponden a los peligros o están incompletas."""


def repartir_controles_existentes(marcados: Iterable[str] | None, otros: str | None = "",
                                  parametros: dict | None = None) -> dict[str, str]:
    """Reparte los controles que existen hoy en las columnas fuente, medio e individuo.

    ``marcados`` son las casillas elegidas (claves de ``controles_existentes`` en los
    parámetros) y ``otros`` el texto libre. Si la persona no respondió nada, las tres
    columnas quedan en blanco; si respondió, las que no tengan control dicen "Ninguno".
    """
    parametros = parametros if parametros is not None else _leer(RUTA_PARAMETROS)
    opciones = parametros["controles_existentes"]
    marcados = list(marcados or [])
    columnas: dict[str, list[str]] = {columna: [] for columna in COLUMNAS_DE_CONTROLES}
    for clave in marcados:
        if clave not in opciones:
            raise RespuestasInvalidas(
                f"'{clave}' no es un control existente. Opciones: {', '.join(opciones)}")
        columna = opciones[clave].get("columna")
        if columna:
            columnas[columna].append(opciones[clave]["etiqueta"])
    otros = (otros or "").strip()
    if otros:
        columnas[parametros.get("columna_de_otros_controles") or "medio"].append(otros)
    if not marcados and not otros:
        return {columna: "" for columna in COLUMNAS_DE_CONTROLES}
    return {columna: ", ".join(textos) if textos else SIN_CONTROL for columna, textos in columnas.items()}


def valorar_peligros(peligros: list[dict], respuestas: list[dict], parametros: dict | None = None) -> list[dict]:
    """Aplica las respuestas de la persona a los peligros y valora los que quedan.

    ``peligros`` viene de ``normalizar_analisis``. Cada respuesta es un diccionario con:

    - ``n``: número del peligro al que responde (obligatorio).
    - ``descartado``: ``True`` si la persona no lo considera válido.
    - ``frecuencia``: continua, frecuente, ocasional o esporadica (obligatoria si no se descarta).
    - ``expuestos``: número de personas que hacen la tarea (opcional).
    - ``controles_existentes``: casillas marcadas; ``otros_controles``: texto libre (opcionales).
    - ``nivel_deficiencia`` y ``consecuencia``: ajustes a lo propuesto por la IA (opcionales).

    Devuelve los peligros no descartados, renumerados desde 1 (``n_original`` conserva el
    número con el que salieron del análisis), con su exposición y su ``valoracion``.
    Lanza RespuestasInvalidas si falta una respuesta o hay un valor que no existe.
    """
    parametros = parametros if parametros is not None else _leer(RUTA_PARAMETROS)
    por_numero = _respuestas_por_numero(peligros, respuestas)

    valorados = []
    for peligro in peligros:
        respuesta = por_numero[peligro["n"]]
        if respuesta.get("descartado"):
            continue
        frecuencia = respuesta.get("frecuencia")
        if not frecuencia:
            raise RespuestasInvalidas(f"Falta la frecuencia de la tarea del peligro {peligro['n']}")
        deficiencia = respuesta.get("nivel_deficiencia") or peligro["nivel_deficiencia_propuesto"]
        consecuencia = respuesta.get("consecuencia") or peligro["consecuencia_propuesta"]
        try:
            valoracion = valorar(deficiencia, frecuencia, consecuencia, parametros)
        except ValueError as error:
            raise RespuestasInvalidas(f"Peligro {peligro['n']}: {error}") from error

        valorado = copy.deepcopy(peligro)
        valorado.update({
            "n": len(valorados) + 1,
            "n_original": peligro["n"],
            "exposicion": frecuencia,
            "expuestos": _expuestos(respuesta.get("expuestos"), peligro["n"]),
            "controles_existentes": repartir_controles_existentes(
                respuesta.get("controles_existentes"), respuesta.get("otros_controles"), parametros),
            "nivel_deficiencia": deficiencia,
            "consecuencia": consecuencia,
            "ajustado": {
                "nivel_deficiencia": deficiencia != peligro["nivel_deficiencia_propuesto"],
                "consecuencia": consecuencia != peligro["consecuencia_propuesta"],
            },
            "valoracion": valoracion.como_dict(),
        })
        valorados.append(valorado)
    return valorados


def _respuestas_por_numero(peligros: list[dict], respuestas: Any) -> dict[int, dict]:
    if not isinstance(respuestas, list):
        raise RespuestasInvalidas("Las respuestas deben ser una lista, una por peligro")
    numeros = {peligro["n"] for peligro in peligros}
    por_numero: dict[int, dict] = {}
    for respuesta in respuestas:
        numero = respuesta.get("n") if isinstance(respuesta, dict) else None
        if numero not in numeros:
            raise RespuestasInvalidas(f"Hay una respuesta para un peligro que no existe: {numero!r}")
        if numero in por_numero:
            raise RespuestasInvalidas(f"Hay más de una respuesta para el peligro {numero}")
        por_numero[numero] = respuesta
    faltan = sorted(numeros - set(por_numero))
    if faltan:
        raise RespuestasInvalidas("Falta la respuesta de los peligros: " + ", ".join(str(n) for n in faltan))
    return por_numero


def _expuestos(valor: Any, numero: int) -> int | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
        raise RespuestasInvalidas(f"Peligro {numero}: el número de expuestos debe ser un entero mayor que cero")
    return valor
