"""Configuración del módulo EPP: perfil activo y elementos requeridos por perfil.

La forma está en contrato/config_epp.schema.json::

    {"perfil_activo": "industria",
     "perfiles": {"industria": {"elementos_requeridos": ["casco", "gafas"]},
                  "alimentos": {"elementos_requeridos": ["cofia", "gafas", "tapabocas"]}}}

Funciones puras: reciben la configuración candidata y las capacidades del módulo
(qué perfiles hay y qué sabe detectar cada modelo) y devuelven la configuración
normalizada o la rechazan.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

RUTA_ESQUEMA = Path(__file__).resolve().parents[3] / "contrato" / "config_epp.schema.json"


class ConfigRechazada(ValueError):
    """La configuración no se puede aplicar; se mantiene la anterior."""


@lru_cache(maxsize=1)
def _validador() -> Draft202012Validator:
    with open(RUTA_ESQUEMA, encoding="utf-8") as archivo:
        return Draft202012Validator(json.load(archivo))


def capacidades_de(perfiles: dict[str, Any], detectables: dict[str, list[str]]) -> dict[str, Any]:
    """Capacidades que el módulo registra en la plataforma.

    ``detectables`` trae, por perfil disponible, los elementos que su modelo cargado
    sabe detectar. Un perfil cuyo modelo no cargó no aparece.
    """
    from .perfiles import nombre_visible

    return {
        "perfiles": {
            nombre: {
                "nombre": perfiles["perfiles"][nombre]["nombre"],
                "elementos": [{"id": e, "nombre": nombre_visible(perfiles, nombre, e)} for e in elementos],
            }
            for nombre, elementos in detectables.items()
        }
    }


def config_por_defecto(perfiles: dict[str, Any], capacidades: dict[str, Any]) -> dict[str, Any]:
    """Configuración inicial sacada de perfiles.yaml, limitada a los perfiles disponibles."""
    disponibles = capacidades["perfiles"]
    if not disponibles:
        raise ConfigRechazada("No hay ningún perfil disponible")
    activo = perfiles["perfil_por_defecto"]
    if activo not in disponibles:
        activo = next(iter(disponibles))
    return {
        "perfil_activo": activo,
        "perfiles": {
            nombre: {"elementos_requeridos": [
                e for e in perfiles["perfiles"][nombre]["elementos_requeridos"] if e in _ids(disponibles[nombre])
            ]}
            for nombre in disponibles
        },
    }


def _ids(capacidad_perfil: dict[str, Any]) -> list[str]:
    return [elemento["id"] for elemento in capacidad_perfil["elementos"]]


def validar_config(
    candidata: Any, capacidades: dict[str, Any], por_defecto: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Normaliza una configuración y devuelve ``(config, advertencias)``.

    - Forma inválida o ``perfil_activo`` que no existe: ``ConfigRechazada``.
    - Elemento que el modelo del perfil no sabe detectar: se ignora, con advertencia.
    - Perfil desconocido (que no es el activo): se ignora, con advertencia.
    - Perfil disponible que la configuración no menciona: toma sus valores por defecto.
    """
    errores = sorted(_validador().iter_errors(candidata), key=lambda e: list(e.absolute_path))
    if errores:
        detalle = "; ".join(
            f"{'/'.join(str(p) for p in e.absolute_path) or '(raíz)'}: {e.message}" for e in errores
        )
        raise ConfigRechazada(f"Configuración mal formada: {detalle}")

    disponibles = capacidades["perfiles"]
    activo = candidata["perfil_activo"]
    if activo not in disponibles:
        raise ConfigRechazada(
            f"El perfil '{activo}' no existe o su modelo no está disponible (hay: {', '.join(disponibles) or 'ninguno'})"
        )

    advertencias: list[str] = []
    recibidos = candidata.get("perfiles", {})
    for nombre in recibidos:
        if nombre not in disponibles:
            advertencias.append(f"Se ignora el perfil desconocido '{nombre}'")

    perfiles_salida: dict[str, Any] = {}
    for nombre, capacidad in disponibles.items():
        if nombre not in recibidos:
            perfiles_salida[nombre] = {"elementos_requeridos": list(por_defecto["perfiles"][nombre]["elementos_requeridos"])}
            continue
        conocidos = _ids(capacidad)
        requeridos: list[str] = []
        for elemento in recibidos[nombre]["elementos_requeridos"]:
            if elemento not in conocidos:
                advertencias.append(
                    f"Se ignora '{elemento}' en el perfil '{nombre}': su modelo no sabe detectarlo"
                )
            elif elemento not in requeridos:
                requeridos.append(elemento)
        # El orden de los requeridos sigue el de las capacidades, para que sea estable
        perfiles_salida[nombre] = {"elementos_requeridos": [e for e in conocidos if e in requeridos]}

    return {"perfil_activo": activo, "perfiles": perfiles_salida}, advertencias
