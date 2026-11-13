"""Demostración: python -m modulos.comun

Publica tres eventos de ejemplo contra la API configurada en API_URL.
Sirve para comprobar que el cliente y el receptor de prueba se entienden.
"""

import logging

from . import esperar_envios, eventos_pendientes, publicar
from .config import obtener_config

log = logging.getLogger("modulos.comun.demo")


def main() -> None:
    log.info("Publicando 3 eventos de ejemplo en %s", obtener_config().api_url)
    publicar(
        "ergonomia", "evaluacion_reba",
        {
            "puntaje": 9, "nivel": "alto", "duracion_s": 6.4,
            "angulos": {"tronco": 62.5, "cuello": 24.0, "brazo": 71.3,
                        "antebrazo": 48.9, "muneca": 17.2, "piernas": 35.0},
        },
        severidad="alta", sesion_id="V-0142",
    )
    publicar(
        "epp", "verificacion_epp",
        {
            "perfil": "alturas", "requeridos": ["casco", "arnes", "guantes", "botas"],
            "detectados": ["casco", "guantes", "botas"], "faltantes": ["arnes"], "cumple": False,
        },
        severidad="media", sesion_id="V-0142",
    )
    publicar(
        "zona", "ingreso_zona",
        {"zona_id": "prensa-1", "duracion_s": 2.8, "alarma_activada": True},
        severidad="media",
    )
    if esperar_envios(5.0):
        log.info("Los 3 eventos fueron entregados")
    else:
        log.warning(
            "%d evento(s) quedaron en la cola local; se enviarán cuando la API responda",
            eventos_pendientes(),
        )


if __name__ == "__main__":
    main()
