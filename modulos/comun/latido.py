"""Latido: cada módulo avisa cada 30 s que sigue vivo (evento estado_modulo)."""

import logging
import threading

import httpx

from .config import obtener_config
from .eventos import construir_evento

log = logging.getLogger(__name__)

INTERVALO_LATIDO_S = 30.0


class Latido:
    """Hilo de latido de un módulo.

    El módulo puede cambiar ``estado`` y ``mensaje`` en cualquier momento
    (por ejemplo a "error" si pierde la cámara); el siguiente latido lo informa.
    """

    def __init__(self, estacion: str, modulo: str, intervalo_s: float = INTERVALO_LATIDO_S):
        self.estacion = estacion
        self.modulo = modulo
        self.intervalo_s = intervalo_s
        self.estado = "activo"
        self.mensaje: str | None = None
        self._detener = threading.Event()
        self._con_conexion = True
        self._hilo = threading.Thread(target=self._ciclo, name=f"latido-{modulo}", daemon=True)

    def iniciar(self) -> "Latido":
        self._hilo.start()
        log.info("Latido de '%s' iniciado (cada %.0f s)", self.modulo, self.intervalo_s)
        return self

    def detener(self) -> None:
        self._detener.set()

    def _ciclo(self) -> None:
        with httpx.Client(timeout=3.0) as cliente:
            while not self._detener.is_set():
                self._latir(cliente)
                self._detener.wait(self.intervalo_s)

    def _latir(self, cliente: httpx.Client) -> None:
        """Envía un latido directo, sin cola: un latido viejo no le sirve a nadie."""
        datos = {"modulo": self.modulo, "estado": self.estado}
        if self.mensaje:
            datos["mensaje"] = self.mensaje
        severidad = "alta" if self.estado == "error" else "info"
        try:
            evento = construir_evento(self.estacion, "estado_modulo", datos, severidad)
            cliente.post(obtener_config().api_url + "/api/eventos", json=evento).raise_for_status()
        except httpx.HTTPError as error:
            if self._con_conexion:
                log.warning("Latido de '%s' sin respuesta de la API (%s)", self.modulo, type(error).__name__)
            self._con_conexion = False
        except Exception:
            log.exception("Error inesperado en el latido de '%s'", self.modulo)
        else:
            if not self._con_conexion:
                log.info("Latido de '%s' restablecido", self.modulo)
            self._con_conexion = True


def iniciar_latido(estacion: str, modulo: str, intervalo_s: float = INTERVALO_LATIDO_S) -> Latido:
    """Arranca el hilo que publica estado_modulo cada 30 s y devuelve su control."""
    return Latido(estacion, modulo, intervalo_s).iniciar()
