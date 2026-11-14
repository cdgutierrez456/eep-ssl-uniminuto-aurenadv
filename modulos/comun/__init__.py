"""Cliente compartido de los módulos SST en vivo.

Es la única puerta de salida hacia la plataforma: ningún módulo hace HTTP
directo a la API. Uso típico::

    from modulos.comun import publicar, iniciar_latido, subir_medio, difuminar_rostros
    from modulos.comun import registrar_capacidades, obtener_config, actualizar_config

    iniciar_latido("ergonomia", "ergonomia")
    ruta = subir_medio("captura.jpg")
    publicar("ergonomia", "evaluacion_reba", {"puntaje": 9, "nivel": "alto"},
             severidad="alta", adjuntos=[{"tipo": "imagen", "ruta": ruta}])
"""

from .registro import configurar_logs

configurar_logs()

from .camaras import abrir_camara, listar_camaras  # noqa: E402
from .cola import esperar_envios, eventos_pendientes  # noqa: E402
from .config_remota import (  # noqa: E402
    ConfigRemota,
    actualizar_config,
    obtener_config,
    registrar_capacidades,
)
from .esquema import EventoInvalido, validar_evento  # noqa: E402
from .eventos import construir_evento, publicar  # noqa: E402
from .latido import Latido, iniciar_latido  # noqa: E402
from .medios import subir_medio  # noqa: E402
from .rostros import difuminar_rostros  # noqa: E402

__version__ = "0.1.0"

__all__ = [
    "publicar",
    "construir_evento",
    "iniciar_latido",
    "Latido",
    "subir_medio",
    "difuminar_rostros",
    "abrir_camara",
    "listar_camaras",
    "registrar_capacidades",
    "obtener_config",
    "actualizar_config",
    "ConfigRemota",
    "validar_evento",
    "EventoInvalido",
    "esperar_envios",
    "eventos_pendientes",
    "configurar_logs",
]
