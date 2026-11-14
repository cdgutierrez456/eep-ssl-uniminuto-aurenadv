"""Configuración del módulo de zona: ajustes del equipo (.env) y configuración operativa (remota)."""

from .ajustes import (
    CAPACIDADES,
    ESTACION,
    MODULO,
    RUTA_POR_DEFECTO,
    ZONA_PISO,
    AjustesLocales,
    parametros_desde,
    validar_config,
    zona_desde_config,
)
from .almacen import AlmacenConfig

__all__ = [
    "MODULO",
    "ESTACION",
    "ZONA_PISO",
    "CAPACIDADES",
    "RUTA_POR_DEFECTO",
    "AjustesLocales",
    "AlmacenConfig",
    "validar_config",
    "zona_desde_config",
    "parametros_desde",
]
