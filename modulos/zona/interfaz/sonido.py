"""Pitido local de la estación. Opcional y apagado por defecto: el sonido principal está en la plataforma.

En advertencia, un pitido lento; en peligro, uno rápido. Usa ``winsound`` de Windows, que no
necesita instalar nada; en otros sistemas no suena y lo dice una vez en el log.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

try:
    import winsound
except ImportError:  # Linux, macOS
    winsound = None

# Por estado: frecuencia (Hz), duración del pitido (ms) y silencio hasta el siguiente (s)
PITIDOS = {"advertencia": (880, 180, 0.9), "peligro": (1320, 140, 0.16)}


class SonidoLocal:
    """Hilo que pita según el estado de la zona mientras esté habilitado."""

    def __init__(self) -> None:
        self.disponible = winsound is not None
        self._estado = "libre"
        self._habilitado = False
        self._cambio = threading.Event()
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._avisado = False

    @property
    def sonando(self) -> bool:
        """True si en este momento hay pitido: está habilitado, se puede y la zona no está libre."""
        return self.disponible and self._habilitado and self._estado in PITIDOS

    def actualizar(self, estado: str, habilitado: bool) -> None:
        """Informa el estado de la zona y si el sonido local está habilitado en la configuración."""
        if habilitado and not self.disponible and not self._avisado:
            log.warning("El sonido local no está disponible en este sistema; la alarma suena en la plataforma")
            self._avisado = True
        if (estado, habilitado) == (self._estado, self._habilitado):
            return
        self._estado, self._habilitado = estado, habilitado
        if self.sonando and (self._hilo is None or not self._hilo.is_alive()):
            self._hilo = threading.Thread(target=self._ciclo, name="sonido-zona", daemon=True)
            self._hilo.start()
        self._cambio.set()

    def cerrar(self) -> None:
        self._parar.set()
        self._cambio.set()

    def _ciclo(self) -> None:
        while not self._parar.is_set():
            self._cambio.clear()
            if not self.sonando:
                self._cambio.wait()
                continue
            frecuencia, duracion_ms, silencio_s = PITIDOS[self._estado]
            try:
                winsound.Beep(frecuencia, duracion_ms)
            except RuntimeError:  # sin dispositivo de audio
                self.disponible = False
                log.warning("No hay dispositivo de audio: el sonido local queda apagado")
                return
            self._cambio.wait(silencio_s)
