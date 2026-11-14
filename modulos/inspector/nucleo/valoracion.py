"""Valoración del riesgo de un peligro: función pura, sin IA y sin entradas ni salidas.

Con el nivel de deficiencia (ND), el de exposición (NE) y el de consecuencia (NC) calcula
la probabilidad (NP = ND x NE) y el riesgo (NR = NP x NC), y los interpreta con los
parámetros de ``config/parametros_valoracion.json``, que se pueden editar sin tocar código.

La deficiencia y la consecuencia las propone la IA y las puede ajustar la persona; la
exposición la pone siempre la persona, porque la foto no la muestra.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

RUTA_PARAMETROS = Path(__file__).resolve().parents[1] / "config" / "parametros_valoracion.json"

SEVERIDAD_SIN_PELIGROS = "info"


class ParametrosInvalidos(ValueError):
    """El archivo de parámetros de valoración no tiene la forma esperada."""


@dataclass(frozen=True)
class Valoracion:
    """Resultado de valorar un peligro.

    ``nd``, ``np`` y ``nr`` son ``None`` cuando la deficiencia no tiene valor numérico
    (deficiencia baja): el peligro pasa directo al nivel de riesgo que indiquen los
    parámetros y ``nota`` explica por qué.
    """

    deficiencia: str
    nd: int | None
    exposicion: str
    ne: int
    np: int | None
    interpretacion_np: str | None
    consecuencia: str
    nc: int
    nr: int | None
    nivel_riesgo: str
    significado: str
    aceptabilidad: str
    nivel_preliminar: str
    severidad: str
    nota: str | None = None

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Parámetros
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=8)
def _leer(ruta: Path) -> dict:
    try:
        parametros = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ParametrosInvalidos(f"No se pudieron leer los parámetros de valoración ({ruta}): {error}") from error
    validar_parametros(parametros)
    return parametros


def cargar_parametros(ruta: str | Path | None = None) -> dict:
    """Lee y valida los parámetros de valoración. Devuelve una copia que se puede modificar."""
    return copy.deepcopy(_leer(Path(ruta) if ruta else RUTA_PARAMETROS))


def validar_parametros(parametros: Any) -> None:
    """Comprueba la forma de los parámetros. Lanza ParametrosInvalidos si falta algo."""
    if not isinstance(parametros, dict):
        raise ParametrosInvalidos("Los parámetros de valoración deben ser un objeto JSON")
    for escala, admite_sin_valor in (("nivel_deficiencia", True), ("nivel_exposicion", False),
                                     ("nivel_consecuencia", False)):
        niveles = parametros.get(escala)
        if not isinstance(niveles, dict) or not niveles:
            raise ParametrosInvalidos(f"Falta la escala '{escala}' en los parámetros de valoración")
        for nombre, nivel in niveles.items():
            valor = nivel.get("valor") if isinstance(nivel, dict) else None
            if valor is None and admite_sin_valor and isinstance(nivel, dict):
                continue
            if not _es_numero(valor) or valor <= 0:
                raise ParametrosInvalidos(f"'{escala}.{nombre}.valor' debe ser un número mayor que cero")
    for escala, campos in (("nivel_probabilidad", ("id", "etiqueta")),
                           ("nivel_riesgo", ("id", "aceptabilidad", "significado", "nivel_preliminar", "severidad"))):
        tramos = parametros.get(escala)
        if not isinstance(tramos, list) or not tramos:
            raise ParametrosInvalidos(f"Falta la lista de tramos '{escala}' en los parámetros de valoración")
        for tramo in tramos:
            if not isinstance(tramo, dict) or not _es_numero(tramo.get("desde")):
                raise ParametrosInvalidos(f"Cada tramo de '{escala}' necesita un número en 'desde'")
            faltan = [campo for campo in campos if not tramo.get(campo)]
            if faltan:
                raise ParametrosInvalidos(f"A un tramo de '{escala}' le falta: {', '.join(faltan)}")
    sin_valor = parametros.get("sin_valor_de_deficiencia")
    if any(nivel.get("valor") is None for nivel in parametros["nivel_deficiencia"].values()):
        ids = {tramo["id"] for tramo in parametros["nivel_riesgo"]}
        if not isinstance(sin_valor, dict) or sin_valor.get("nivel_riesgo") not in ids:
            raise ParametrosInvalidos(
                "Hay una deficiencia sin valor: 'sin_valor_de_deficiencia.nivel_riesgo' debe ser un nivel de riesgo")


def _es_numero(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _tramos_de_mayor_a_menor(tramos: list[dict]) -> list[dict]:
    return sorted(tramos, key=lambda tramo: tramo["desde"], reverse=True)


def _tramo(valor: float, tramos: list[dict]) -> dict:
    """Tramo de mayor 'desde' que el valor alcanza; el más bajo recoge lo que no llegue a ninguno."""
    ordenados = _tramos_de_mayor_a_menor(tramos)
    for tramo in ordenados:
        if valor >= tramo["desde"]:
            return tramo
    return ordenados[-1]


def _nivel(escala: str, clave: str, parametros: dict) -> dict:
    niveles = parametros[escala]
    if clave not in niveles:
        raise ValueError(f"'{clave}' no es un valor de {escala}. Opciones: {', '.join(niveles)}")
    return niveles[clave]


# --------------------------------------------------------------------------- #
# Valoración
# --------------------------------------------------------------------------- #
def valorar(deficiencia: str, exposicion: str, consecuencia: str, parametros: dict | None = None) -> Valoracion:
    """Valora un peligro a partir de sus tres niveles.

    ``deficiencia``: muy_alto, alto, medio o bajo. ``exposicion``: continua, frecuente,
    ocasional o esporadica. ``consecuencia``: mortal, muy_grave, grave o leve.
    Lanza ValueError si alguno no existe en los parámetros.
    """
    parametros = parametros if parametros is not None else _leer(RUTA_PARAMETROS)
    nd = _nivel("nivel_deficiencia", deficiencia, parametros)["valor"]
    ne = _nivel("nivel_exposicion", exposicion, parametros)["valor"]
    nc = _nivel("nivel_consecuencia", consecuencia, parametros)["valor"]

    if nd is None:
        # Deficiencia sin valor numérico: no hay NP ni NR; va directo al nivel indicado
        sin_valor = parametros["sin_valor_de_deficiencia"]
        riesgo = next(tramo for tramo in parametros["nivel_riesgo"] if tramo["id"] == sin_valor["nivel_riesgo"])
        np_, interpretacion_np, nr, nota = None, None, None, sin_valor.get("nota")
    else:
        np_ = nd * ne
        interpretacion_np = _tramo(np_, parametros["nivel_probabilidad"])["etiqueta"]
        nr = np_ * nc
        riesgo = _tramo(nr, parametros["nivel_riesgo"])
        nota = None

    return Valoracion(
        deficiencia=deficiencia, nd=nd,
        exposicion=exposicion, ne=ne,
        np=np_, interpretacion_np=interpretacion_np,
        consecuencia=consecuencia, nc=nc,
        nr=nr,
        nivel_riesgo=riesgo["id"],
        significado=riesgo["significado"],
        aceptabilidad=riesgo["aceptabilidad"],
        nivel_preliminar=riesgo["nivel_preliminar"],
        severidad=riesgo["severidad"],
        nota=nota,
    )


def peor_nivel(niveles: Iterable[str], parametros: dict | None = None) -> str | None:
    """El nivel de riesgo más grave de una lista (por ejemplo ``"I"``). ``None`` si está vacía."""
    parametros = parametros if parametros is not None else _leer(RUTA_PARAMETROS)
    presentes = set(niveles)
    for tramo in _tramos_de_mayor_a_menor(parametros["nivel_riesgo"]):
        if tramo["id"] in presentes:
            return tramo["id"]
    return None


def severidad_del_evento(niveles: Iterable[str], parametros: dict | None = None) -> str:
    """Severidad del evento ``inspeccion_foto``: la del peor peligro; ``info`` si no hay peligros."""
    parametros = parametros if parametros is not None else _leer(RUTA_PARAMETROS)
    peor = peor_nivel(niveles, parametros)
    if peor is None:
        return SEVERIDAD_SIN_PELIGROS
    return next(tramo["severidad"] for tramo in parametros["nivel_riesgo"] if tramo["id"] == peor)


def datos_del_nivel(nivel_riesgo: str, parametros: dict | None = None) -> dict:
    """Tramo completo de un nivel de riesgo (colores, rango, aceptabilidad…)."""
    parametros = parametros if parametros is not None else _leer(RUTA_PARAMETROS)
    for tramo in parametros["nivel_riesgo"]:
        if tramo["id"] == nivel_riesgo:
            return tramo
    raise ValueError(f"'{nivel_riesgo}' no es un nivel de riesgo")
