"""Configuración por archivo .env (nunca claves ni rutas fijas en el código)."""

import os
import socket
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

# Carga el .env buscándolo desde la carpeta actual hacia arriba.
# Las variables ya definidas en el entorno tienen prioridad sobre el archivo.
load_dotenv(find_dotenv(usecwd=True))

RAIZ_REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Configuracion:
    """Valores de configuración vigentes al momento de leerlos."""

    api_url: str
    dispositivo: str
    carpeta_cola: Path
    ruta_esquema: Path


def obtener_config() -> Configuracion:
    """Lee la configuración desde las variables de entorno.

    Se lee en cada llamada (no se guarda en caché) para que un cambio de
    entorno, por ejemplo en las pruebas, tenga efecto inmediato.
    """
    return Configuracion(
        api_url=os.getenv("API_URL", "http://localhost:8000").rstrip("/"),
        dispositivo=os.getenv("DISPOSITIVO") or socket.gethostname(),
        carpeta_cola=Path(os.getenv("CARPETA_COLA", "cola")),
        ruta_esquema=Path(
            os.getenv("RUTA_ESQUEMA") or RAIZ_REPO / "contrato" / "evento.schema.json"
        ),
    )
