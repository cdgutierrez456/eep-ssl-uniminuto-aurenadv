"""Configuración del módulo: .env para lo local y configuración remota para lo operativo."""

from .ajustes import (
    AGARRES,
    CAPACIDADES,
    LADOS,
    MODOS_DETECCION,
    RUTA_POR_DEFECTO,
    AjustesLocales,
    condiciones_desde,
    umbrales_desde,
    validar_config,
)

__all__ = [
    "AjustesLocales",
    "validar_config",
    "condiciones_desde",
    "umbrales_desde",
    "CAPACIDADES",
    "RUTA_POR_DEFECTO",
    "AGARRES",
    "MODOS_DETECCION",
    "LADOS",
]
