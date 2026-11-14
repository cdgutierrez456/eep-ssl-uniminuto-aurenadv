"""Esquema de la salida del modelo: validación, versión para la API y forma interna.

El archivo ``esquemas/analisis.schema.json`` es la fuente de verdad de lo que el modelo
debe devolver. Aquí se usa de tres maneras:

- ``esquema_para_api()``: el mismo esquema sin las restricciones que las salidas
  estructuradas de la API no admiten (mínimos, máximos, longitudes).
- ``validar_analisis()``: validación completa en local, con esas restricciones.
- ``normalizar_analisis()``: valida y pasa la salida a la forma interna del módulo, con
  las cajas de 0 a 1 y los peligros numerados.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

RUTA_ESQUEMA = Path(__file__).resolve().parents[1] / "esquemas" / "analisis.schema.json"

CATEGORIAS = {
    "biologico": "Biológico",
    "fisico": "Físico",
    "quimico": "Químico",
    "psicosocial": "Psicosocial",
    "biomecanico": "Biomecánico",
    "condiciones_de_seguridad": "Condiciones de seguridad",
    "fenomenos_naturales": "Fenómenos naturales",
}
CONFIANZAS = ("alta", "media", "baja")
JERARQUIA = ("eliminacion", "sustitucion", "ingenieria", "administrativos", "epp")
MAX_PELIGROS_POR_DEFECTO = 6

# Palabras clave que las salidas estructuradas de la API no admiten o que no le aportan
_NO_ADMITIDAS_POR_LA_API = {
    "$schema", "$id", "$comment",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "maxItems",
}
# Claves cuyos hijos son nombres (de propiedades o definiciones), no palabras clave
_MAPAS_DE_NOMBRES = {"properties", "$defs", "definitions"}
_CAMPOS_ENUMERADOS = ("confianza", "categoria", "nivel_deficiencia_propuesto", "consecuencia_propuesta")
_LADO_MINIMO_DE_CAJA = 0.02  # una caja degenerada se abre hasta el 2 % de la imagen


class AnalisisInvalido(ValueError):
    """La salida del modelo no cumple el esquema."""


@lru_cache(maxsize=1)
def _esquema() -> dict:
    return json.loads(RUTA_ESQUEMA.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _validador() -> Draft202012Validator:
    esquema = _esquema()
    Draft202012Validator.check_schema(esquema)
    return Draft202012Validator(esquema)


def cargar_esquema() -> dict:
    """Esquema completo de la salida del modelo (copia que se puede modificar)."""
    return copy.deepcopy(_esquema())


def esquema_para_api(esquema: dict | None = None) -> dict:
    """El esquema tal como se envía en ``output_config.format``.

    Quita las restricciones que la API rechaza (mínimos, máximos, longitudes y el máximo
    de elementos); ``minItems`` solo se conserva si vale 0 o 1. Esas restricciones se
    siguen comprobando en local con ``validar_analisis``.
    """
    return _limpiar(esquema if esquema is not None else _esquema())


def _limpiar(nodo: Any) -> Any:
    if isinstance(nodo, list):
        return [_limpiar(elemento) for elemento in nodo]
    if not isinstance(nodo, dict):
        return nodo
    limpio = {}
    for clave, valor in nodo.items():
        if clave in _NO_ADMITIDAS_POR_LA_API:
            continue
        if clave == "minItems" and valor not in (0, 1):
            continue
        if clave in _MAPAS_DE_NOMBRES and isinstance(valor, dict):
            limpio[clave] = {nombre: _limpiar(definicion) for nombre, definicion in valor.items()}
        else:
            limpio[clave] = _limpiar(valor)
    return limpio


def validar_analisis(datos: Any) -> None:
    """Valida la salida del modelo contra el esquema completo. Lanza AnalisisInvalido."""
    errores = sorted(_validador().iter_errors(datos), key=lambda error: list(error.absolute_path))
    if not errores:
        return
    detalles = []
    for error in errores[:5]:
        lugar = "/".join(str(parte) for parte in error.absolute_path) or "(raíz)"
        detalles.append(f"{lugar}: {error.message}")
    if len(errores) > 5:
        detalles.append(f"… y {len(errores) - 5} más")
    raise AnalisisInvalido("La salida del modelo no cumple el esquema. " + "; ".join(detalles))


# --------------------------------------------------------------------------- #
# Forma interna
# --------------------------------------------------------------------------- #
def normalizar_analisis(datos: Any, ancho: int, alto: int,
                        max_peligros: int = MAX_PELIGROS_POR_DEFECTO) -> dict:
    """Valida la salida del modelo y la pasa a la forma interna del módulo.

    ``ancho`` y ``alto`` son los de la imagen que se envió al modelo: sus cajas vienen en
    esos píxeles y aquí se pasan a 0–1. Los peligros quedan numerados desde 1 y, si el
    modelo devolvió más de ``max_peligros``, se conservan los primeros (los pidió del más
    grave al menos grave). Lanza AnalisisInvalido si la salida no cumple el esquema.
    """
    if ancho <= 0 or alto <= 0:
        raise ValueError("El ancho y el alto de la imagen deben ser mayores que cero")
    datos = _con_enumerados_en_minusculas(datos)
    validar_analisis(datos)

    peligros = []
    for numero, peligro in enumerate(datos["peligros"][:max(0, max_peligros)], start=1):
        peligros.append({
            "n": numero,
            "descripcion": peligro["descripcion"].strip(),
            "clasificacion": {
                "categoria": peligro["categoria"],
                "subcategoria": peligro["subcategoria"].strip(),
            },
            "evidencia_visible": peligro["evidencia_visible"].strip(),
            "ubicacion": _caja_normalizada(peligro["ubicacion_px"], ancho, alto),
            "confianza": peligro["confianza"],
            "efectos_posibles": peligro["efectos_posibles"].strip(),
            "peor_consecuencia": peligro["peor_consecuencia"].strip(),
            "nivel_deficiencia_propuesto": peligro["nivel_deficiencia_propuesto"],
            "explicacion_deficiencia": peligro["explicacion_deficiencia"].strip(),
            "consecuencia_propuesta": peligro["consecuencia_propuesta"],
            "explicacion_consecuencia": peligro["explicacion_consecuencia"].strip(),
            "controles_propuestos": {
                nivel: _sin_vacios(peligro["controles_propuestos"][nivel]) for nivel in JERARQUIA
            },
        })
    return {
        "descripcion_general": datos["descripcion_general"].strip(),
        "advertencias": _sin_vacios(datos["advertencias"]),
        "peligros": peligros,
    }


def _con_enumerados_en_minusculas(datos: Any) -> Any:
    """La API no garantiza las mayúsculas de los valores enumerados: se comparan en minúsculas."""
    if not isinstance(datos, dict) or not isinstance(datos.get("peligros"), list):
        return datos
    datos = copy.deepcopy(datos)
    for peligro in datos["peligros"]:
        if not isinstance(peligro, dict):
            continue
        for campo in _CAMPOS_ENUMERADOS:
            if isinstance(peligro.get(campo), str):
                peligro[campo] = peligro[campo].strip().lower()
    return datos


def _sin_vacios(textos: list[str]) -> list[str]:
    return [texto.strip() for texto in textos if texto.strip()]


def _caja_normalizada(caja: dict, ancho: int, alto: int) -> list[float]:
    """Caja en píxeles -> [x1, y1, x2, y2] de 0 a 1, ordenada, dentro de la imagen y con área."""
    x1, x2 = sorted((caja["x1"] / ancho, caja["x2"] / ancho))
    y1, y2 = sorted((caja["y1"] / alto, caja["y2"] / alto))
    x1, x2 = _con_lado_minimo(min(max(x1, 0.0), 1.0), min(max(x2, 0.0), 1.0))
    y1, y2 = _con_lado_minimo(min(max(y1, 0.0), 1.0), min(max(y2, 0.0), 1.0))
    return [round(valor, 4) for valor in (x1, y1, x2, y2)]


def _con_lado_minimo(inicio: float, fin: float) -> tuple[float, float]:
    if fin - inicio >= _LADO_MINIMO_DE_CAJA:
        return inicio, fin
    centro = (inicio + fin) / 2
    inicio = min(max(centro - _LADO_MINIMO_DE_CAJA / 2, 0.0), 1.0 - _LADO_MINIMO_DE_CAJA)
    return inicio, inicio + _LADO_MINIMO_DE_CAJA
