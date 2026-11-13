"""Utilidades compartidas de las pruebas."""

import socket
import threading
import time

import httpx
import pytest
import uvicorn

from herramientas.receptor_prueba.app import crear_app


def puerto_libre() -> int:
    """Pide al sistema un puerto TCP que no esté en uso."""
    with socket.socket() as enchufe:
        enchufe.bind(("127.0.0.1", 0))
        return enchufe.getsockname()[1]


class ReceptorEnHilo:
    """Levanta el receptor de prueba real (uvicorn) en un hilo."""

    def __init__(self, puerto: int, carpeta_datos):
        self.url = f"http://127.0.0.1:{puerto}"
        configuracion = uvicorn.Config(
            crear_app(carpeta_datos), host="127.0.0.1", port=puerto, log_level="warning"
        )
        self._servidor = uvicorn.Server(configuracion)
        self._hilo = threading.Thread(target=self._servidor.run, daemon=True)

    def encender(self) -> None:
        self._hilo.start()
        limite = time.monotonic() + 10
        while time.monotonic() < limite:
            try:
                if httpx.get(self.url + "/api/salud", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.1)
        raise RuntimeError("El receptor de prueba no arrancó")

    def apagar(self) -> None:
        self._servidor.should_exit = True
        self._hilo.join(timeout=10)


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Apunta el cliente a un puerto libre y a una carpeta de cola temporal.

    El receptor queda creado pero APAGADO: cada prueba decide cuándo encenderlo.
    """
    puerto = puerto_libre()
    monkeypatch.setenv("API_URL", f"http://127.0.0.1:{puerto}")
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    monkeypatch.setenv("DISPOSITIVO", "pc-pruebas")
    receptor = ReceptorEnHilo(puerto, tmp_path / "receptor")
    yield receptor
    receptor.apagar() if receptor._hilo.is_alive() else None
