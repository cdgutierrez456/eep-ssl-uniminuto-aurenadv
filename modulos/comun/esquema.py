"""Validación de eventos contra contrato/evento.schema.json."""

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from .config import obtener_config


class EventoInvalido(ValueError):
    """El evento no cumple el contrato. El mensaje dice qué campo falla."""


@lru_cache(maxsize=4)
def _validador(ruta: Path) -> Draft202012Validator:
    """Carga el esquema una sola vez por ruta."""
    with open(ruta, encoding="utf-8") as archivo:
        esquema = json.load(archivo)
    Draft202012Validator.check_schema(esquema)
    return Draft202012Validator(esquema)


def errores_de(evento: object) -> list[str]:
    """Devuelve la lista de errores legibles del evento (vacía si es válido)."""
    validador = _validador(obtener_config().ruta_esquema)
    errores = []
    for error in sorted(validador.iter_errors(evento), key=lambda e: list(e.absolute_path)):
        campo = "/".join(str(parte) for parte in error.absolute_path) or "(sobre)"
        errores.append(f"{campo}: {error.message}")
    return errores


def validar_evento(evento: object) -> None:
    """Lanza EventoInvalido si el evento no cumple el contrato."""
    errores = errores_de(evento)
    if errores:
        raise EventoInvalido("Evento inválido: " + "; ".join(errores))
