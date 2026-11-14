"""Subida de medios (imágenes, PDF) a la plataforma."""

import logging
import mimetypes
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import httpx

from .config import leer_entorno
from .eventos import ZONA_HORARIA

log = logging.getLogger(__name__)

TIEMPO_LIMITE_SUBIDA_S = 10.0


def subir_medio(ruta_archivo: str | Path) -> str:
    """Sube un archivo a {API_URL}/api/medios y devuelve la ``ruta`` para adjuntos.

    Si la subida falla, copia el archivo a la carpeta local de respaldo
    (CARPETA_COLA/medios_pendientes/AAAA-MM-DD/) y devuelve esa ruta local,
    para que el módulo siga trabajando y el archivo no se pierda.

    Recordatorio: toda imagen debe pasar por difuminar_rostros() antes de guardarse.
    """
    ruta_archivo = Path(ruta_archivo)
    if not ruta_archivo.is_file():
        raise FileNotFoundError(f"No existe el archivo a subir: {ruta_archivo}")

    config = leer_entorno()
    tipo_mime = mimetypes.guess_type(ruta_archivo.name)[0] or "application/octet-stream"
    try:
        with open(ruta_archivo, "rb") as archivo:
            respuesta = httpx.post(
                config.api_url + "/api/medios",
                files={"archivo": (ruta_archivo.name, archivo, tipo_mime)},
                timeout=TIEMPO_LIMITE_SUBIDA_S,
            )
        respuesta.raise_for_status()
        ruta = respuesta.json()["ruta"]
        log.info("Medio %s subido como %s", ruta_archivo.name, ruta)
        return ruta
    except (httpx.HTTPError, KeyError, ValueError) as error:
        fecha = datetime.now(ZONA_HORARIA).strftime("%Y-%m-%d")
        carpeta = config.carpeta_cola / "medios_pendientes" / fecha
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / f"{uuid.uuid4().hex[:8]}-{ruta_archivo.name}"
        shutil.copy2(ruta_archivo, destino)
        log.warning(
            "No se pudo subir %s (%s). Se guardó en %s",
            ruta_archivo.name, type(error).__name__, destino.as_posix(),
        )
        return destino.as_posix()
