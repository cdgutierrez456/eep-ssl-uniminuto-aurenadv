"""Configuración de los logs de los módulos (mensajes en español)."""

import logging
import os

_FORMATO = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def configurar_logs() -> None:
    """Conecta el logger ``modulos`` a la consola si nadie lo ha configurado.

    El nivel se controla con la variable de entorno ``LOG_NIVEL`` (por defecto INFO).
    Si la aplicación ya puso sus propios manejadores, no se toca nada.
    """
    registrador = logging.getLogger("modulos")
    if registrador.handlers:
        return
    manejador = logging.StreamHandler()
    manejador.setFormatter(logging.Formatter(_FORMATO, datefmt="%H:%M:%S"))
    registrador.addHandler(manejador)
    registrador.setLevel(os.getenv("LOG_NIVEL", "INFO").upper())
    registrador.propagate = False
