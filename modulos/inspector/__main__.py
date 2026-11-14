"""Punto de entrada: python -m modulos.inspector

Levanta el servicio HTTP del inspector en la PC del stand. La tablet abre
http://<ip-de-la-pc>:8010 en la red local.
"""

from __future__ import annotations

import functools
import logging
import socket
import sys

import uvicorn

from modulos.comun import iniciar_latido, obtener_config, registrar_capacidades

from .configuracion import (
    ESTACION,
    MODULO,
    Ajustes,
    capacidades,
    config_por_defecto,
    hay_clave,
    puerto_del_servicio,
    validar_config,
)
from .preparadas import listar_escenas
from .servicio.app import crear_app

log = logging.getLogger("modulos.inspector")


def ip_local() -> str:
    """La dirección de este equipo en la red local (para decirle a la tablet a dónde entrar)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as enchufe:
            enchufe.connect(("10.255.255.255", 1))  # no envía nada: solo elige la interfaz de salida
            return enchufe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> int:
    ajustes = Ajustes.desde_entorno()
    puerto = puerto_del_servicio()
    escenas = listar_escenas(solo_listas=True)
    por_defecto = config_por_defecto(ajustes)

    latido = iniciar_latido(ESTACION, MODULO)
    if not hay_clave():
        latido.mensaje = "Sin clave de IA: solo escenas preparadas"
        log.warning("No hay ANTHROPIC_API_KEY en el .env: el inspector solo ofrecerá escenas preparadas")
    registrar_capacidades(MODULO, capacidades(escenas))
    config = obtener_config(MODULO, por_defecto, validar=functools.partial(validar_config, base=por_defecto))

    app = crear_app(ajustes, config=lambda: config.valor)
    log.info("Inspector listo: %d escenas preparadas, modelo %s", len(escenas), ajustes.modelo)
    log.info("Interfaz de tablet: http://%s:%d  (en esta PC: http://localhost:%d)", ip_local(), puerto, puerto)
    try:
        uvicorn.run(app, host="0.0.0.0", port=puerto, log_level="warning")
    finally:
        config.detener()
        latido.detener()
    return 0


if __name__ == "__main__":
    sys.exit(main())
