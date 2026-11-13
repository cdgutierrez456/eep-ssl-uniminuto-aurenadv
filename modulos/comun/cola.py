"""Cola local de respaldo: ningún evento se pierde y publicar() nunca bloquea.

Cada evento se escribe primero en un archivo JSONL (uno por estación) y un
hilo en segundo plano lo envía a la API. Si la API no responde, el evento se
queda en el archivo y se reintenta con espera creciente; también sobrevive a
un reinicio del módulo, porque la cola vive en disco.

Limitación conocida: se asume un solo proceso por estación. Dos procesos de
la misma estación escribiendo el mismo archivo a la vez no están soportados.
"""

import atexit
import json
import logging
import os
import threading
import time
from pathlib import Path

import httpx

from .config import obtener_config

log = logging.getLogger(__name__)

ESPERA_MINIMA_S = 1.0
ESPERA_MAXIMA_S = 60.0
TIEMPO_LIMITE_HTTP_S = 5.0


class ColaEventos:
    """Cola persistente de una estación, con su hilo de envío."""

    def __init__(self, ruta: Path):
        self.ruta = ruta
        self.ruta_rechazados = ruta.with_name(ruta.stem + ".rechazados.jsonl")
        self._candado = threading.Lock()
        self._hay_trabajo = threading.Event()
        self._hilo: threading.Thread | None = None
        self.ruta.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ escritura

    def encolar(self, evento: dict) -> None:
        """Escribe el evento en disco y despierta al hilo de envío."""
        linea = json.dumps(evento, ensure_ascii=False)
        with self._candado:
            with open(self.ruta, "a", encoding="utf-8") as archivo:
                archivo.write(linea + "\n")
        self._asegurar_hilo()
        self._hay_trabajo.set()

    def pendientes(self) -> list[dict]:
        """Eventos que siguen en la cola, en orden de publicación."""
        with self._candado:
            return self._leer()

    def _leer(self) -> list[dict]:
        if not self.ruta.exists():
            return []
        eventos = []
        with open(self.ruta, encoding="utf-8") as archivo:
            for numero, linea in enumerate(archivo, start=1):
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    eventos.append(json.loads(linea))
                except json.JSONDecodeError:
                    log.warning("Línea %d de la cola %s está dañada; se omite", numero, self.ruta.name)
        return eventos

    def _quitar(self, id_evento: str) -> None:
        """Saca un evento de la cola reescribiendo el archivo de forma atómica."""
        with self._candado:
            restantes = [e for e in self._leer() if e.get("id") != id_evento]
            temporal = self.ruta.with_suffix(".tmp")
            with open(temporal, "w", encoding="utf-8") as archivo:
                for evento in restantes:
                    archivo.write(json.dumps(evento, ensure_ascii=False) + "\n")
            os.replace(temporal, self.ruta)

    def _apartar_rechazado(self, evento: dict, motivo: str) -> None:
        """Guarda aparte un evento que la API rechazó: reintentarlo no sirve."""
        with open(self.ruta_rechazados, "a", encoding="utf-8") as archivo:
            archivo.write(json.dumps({"motivo": motivo, "evento": evento}, ensure_ascii=False) + "\n")
        self._quitar(evento["id"])

    # ---------------------------------------------------------------- envío

    def _asegurar_hilo(self) -> None:
        with self._candado:
            if self._hilo is None or not self._hilo.is_alive():
                self._hilo = threading.Thread(
                    target=self._ciclo, name=f"cola-{self.ruta.stem}", daemon=True
                )
                self._hilo.start()

    def _ciclo(self) -> None:
        """Envía los pendientes en orden; ante un fallo espera cada vez más."""
        espera = ESPERA_MINIMA_S
        avisado = False
        with httpx.Client(timeout=TIEMPO_LIMITE_HTTP_S) as cliente:
            while True:
                pendientes = self.pendientes()
                if not pendientes:
                    self._hay_trabajo.clear()
                    # Segunda mirada para no dormirse con un evento recién encolado
                    if not self.pendientes():
                        self._hay_trabajo.wait()
                    continue

                evento = pendientes[0]
                url = obtener_config().api_url + "/api/eventos"
                try:
                    respuesta = cliente.post(url, json=evento)
                except httpx.HTTPError as error:
                    fallo = f"sin conexión ({type(error).__name__})"
                else:
                    if respuesta.is_success or respuesta.status_code == 409:
                        self._quitar(evento["id"])
                        if avisado:
                            log.info("La API volvió a responder; vaciando la cola de %s", self.ruta.stem)
                        espera, avisado = ESPERA_MINIMA_S, False
                        continue
                    if respuesta.status_code == 422:
                        log.error(
                            "La API rechazó el evento %s (422): %s. Se aparta en %s",
                            evento.get("id"), respuesta.text[:300], self.ruta_rechazados.name,
                        )
                        self._apartar_rechazado(evento, respuesta.text)
                        continue
                    fallo = f"respuesta HTTP {respuesta.status_code}"

                log.warning(
                    "No se pudo enviar a %s: %s. %d evento(s) en cola; reintento en %.0f s",
                    url, fallo, len(pendientes), espera,
                )
                avisado = True
                time.sleep(espera)
                espera = min(espera * 2, ESPERA_MAXIMA_S)


# ------------------------------------------------------- registro de colas

_colas: dict[Path, ColaEventos] = {}
_candado_colas = threading.Lock()


def obtener_cola(estacion: str) -> ColaEventos:
    """Devuelve la cola de la estación (una por archivo), creándola si hace falta."""
    ruta = (obtener_config().carpeta_cola / f"{estacion}.jsonl").resolve()
    with _candado_colas:
        if ruta not in _colas:
            _colas[ruta] = ColaEventos(ruta)
        return _colas[ruta]


def eventos_pendientes(estacion: str | None = None) -> int:
    """Cantidad de eventos aún sin entregar (de una estación o de todas las usadas)."""
    if estacion is not None:
        return len(obtener_cola(estacion).pendientes())
    with _candado_colas:
        colas = list(_colas.values())
    return sum(len(cola.pendientes()) for cola in colas)


def esperar_envios(tiempo_limite_s: float = 5.0) -> bool:
    """Espera a que las colas se vacíen. Devuelve True si quedaron vacías.

    Útil antes de cerrar un módulo o un script corto: el hilo de envío es
    de fondo y muere con el proceso. Lo que no alcance a salir sigue en disco
    y se envía en el próximo arranque de la estación.
    """
    limite = time.monotonic() + tiempo_limite_s
    while time.monotonic() < limite:
        if eventos_pendientes() == 0:
            return True
        time.sleep(0.05)
    return eventos_pendientes() == 0


@atexit.register
def _al_salir() -> None:
    """Da un par de segundos para entregar lo pendiente al cerrar el proceso."""
    if _colas and not esperar_envios(2.0):
        log.warning(
            "Quedan %d evento(s) en la cola local; se enviarán en el próximo arranque",
            eventos_pendientes(),
        )
