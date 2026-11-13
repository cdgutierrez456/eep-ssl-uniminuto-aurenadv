"""Construcción y publicación de eventos."""

import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from .cola import obtener_cola
from .config import obtener_config
from .esquema import validar_evento

log = logging.getLogger(__name__)

VERSION_ESQUEMA = 1
VERSION_MODULO = "0.1.0"
ZONA_HORARIA = ZoneInfo("America/Bogota")


def construir_evento(
    estacion: str,
    tipo: str,
    datos: dict,
    severidad: str = "info",
    sesion_id: str | None = None,
    adjuntos: list[dict] | None = None,
    *,
    modulo_version: str | None = None,
) -> dict:
    """Arma el sobre común y lo valida contra el contrato.

    Lanza EventoInvalido (un ValueError) si el evento no cumple el esquema.
    """
    evento = {
        "id": str(uuid.uuid4()),
        "version_esquema": VERSION_ESQUEMA,
        "estacion": estacion,
        "tipo": tipo,
        "timestamp": datetime.now(ZONA_HORARIA).isoformat(timespec="seconds"),
        "severidad": severidad,
        "datos": datos,
        "origen": {
            "dispositivo": obtener_config().dispositivo,
            "modulo_version": modulo_version or VERSION_MODULO,
        },
    }
    if sesion_id is not None:
        evento["sesion_id"] = sesion_id
    if adjuntos:
        evento["adjuntos"] = adjuntos
    validar_evento(evento)
    return evento


def publicar(
    estacion: str,
    tipo: str,
    datos: dict,
    severidad: str = "info",
    sesion_id: str | None = None,
    adjuntos: list[dict] | None = None,
    *,
    modulo_version: str | None = None,
) -> dict:
    """Publica un evento en la plataforma sin bloquear al módulo.

    El evento se valida, se escribe en la cola local en disco y se retorna de
    inmediato; un hilo en segundo plano lo envía a {API_URL}/api/eventos y lo
    reintenta con espera creciente si la API no responde. Devuelve el sobre.

    Lanza EventoInvalido si el evento no cumple el contrato: es un error del
    módulo que publica y debe corregirse en el código, no reintentarse.
    """
    evento = construir_evento(
        estacion, tipo, datos, severidad, sesion_id, adjuntos, modulo_version=modulo_version
    )
    obtener_cola(estacion).encolar(evento)
    log.info("Evento %s/%s publicado (severidad %s, id %s)", estacion, tipo, severidad, evento["id"][:8])
    return evento
