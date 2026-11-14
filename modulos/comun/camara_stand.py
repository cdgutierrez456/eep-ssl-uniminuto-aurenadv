"""Cámara del stand: abrirla desde configuración y que se reconecte sola.

Pensada para las webcams USB Logitech externas de las demos. Uso típico::

    from modulos.comun import ConfigCamara, conectar_camara

    camara = conectar_camara(ConfigCamara.desde_entorno("ERGONOMIA"))
    while True:
        frame = camara.leer()
        if frame is None:            # desconectada: reintenta sola, sin cerrar el programa
            mostrar(camara.mensaje)  # "Cámara desconectada, reconectando…"
            continue
        ...

La cámara se elige por **índice** (lo normal) o por nombre de dispositivo. El índice depende
del puerto USB: cada cámara debe conectarse siempre al mismo puerto. Para ver qué índice
tiene cada una, con vista previa: ``python -m herramientas.listar_camaras``.

No reemplaza a ``modulos.comun.camaras.abrir_camara(indice)``, que sigue igual.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np

from . import config as _config  # noqa: F401  (al importarlo se carga el .env)

log = logging.getLogger(__name__)

MENSAJE_DESCONECTADA = "Cámara desconectada, reconectando…"
FALLOS_PARA_DESCONECTAR = 5  # lecturas fallidas seguidas antes de darla por desconectada


def _backend() -> int:
    """DirectShow en Windows y V4L2 en Linux."""
    if sys.platform == "win32":
        return cv2.CAP_DSHOW
    if sys.platform.startswith("linux"):
        return cv2.CAP_V4L2
    return cv2.CAP_ANY


def _numero(texto: str | None, por_defecto, tipo=float):
    """Convierte una variable de entorno; vacía o inválida devuelve el valor por defecto."""
    if texto is None or not texto.strip():
        return por_defecto
    try:
        return tipo(texto.strip())
    except ValueError:
        log.warning("Valor de cámara inválido en el entorno: %r; se usa %r", texto, por_defecto)
        return por_defecto


@dataclass(frozen=True)
class ConfigCamara:
    """Cómo abrir una cámara. Todo tiene un valor por defecto pensado para una Logitech USB."""

    indice: int = 0  # la integrada del portátil suele ser la 0
    nombre: str | None = None  # si se indica, se busca por nombre (ver nombres_de_camaras)
    ancho: int = 1280
    alto: int = 720
    fps: int = 30
    formato: str = "MJPG"  # comprimido: permite dos cámaras en el mismo concentrador USB
    autofoco: bool = False
    enfoque: float | None = 0.0  # valor fijo con el autofoco apagado (0 = infinito); None = no tocar
    exposicion: float | None = None  # None = automática; en DirectShow suele ir de -11 a -1
    reintento_s: float = 1.0  # espera entre intentos de reconexión

    @classmethod
    def desde_entorno(cls, prefijo: str, **por_defecto) -> "ConfigCamara":
        """Lee la configuración del .env con el prefijo del módulo (por ejemplo ``ERGONOMIA``).

        Variables: ``{PREFIJO}_CAMARA`` (índice o nombre), ``_CAMARA_ANCHO``, ``_CAMARA_ALTO``,
        ``_CAMARA_FPS``, ``_CAMARA_AUTOFOCO`` (0/1), ``_CAMARA_ENFOQUE`` y ``_CAMARA_EXPOSICION``
        (vacías = no tocar). Lo que no esté en el entorno sale de ``por_defecto`` o de la clase.
        """
        base = cls(**por_defecto)

        def leer(sufijo: str) -> str | None:
            return os.getenv(f"{prefijo}_CAMARA{sufijo}")

        return replace(
            base.con_camara(leer("")),
            ancho=_numero(leer("_ANCHO"), base.ancho, int),
            alto=_numero(leer("_ALTO"), base.alto, int),
            fps=_numero(leer("_FPS"), base.fps, int),
            autofoco=bool(_numero(leer("_AUTOFOCO"), int(base.autofoco), int)),
            enfoque=_numero(leer("_ENFOQUE"), base.enfoque),
            exposicion=_numero(leer("_EXPOSICION"), base.exposicion),
        )

    def con_camara(self, camara: int | str | None) -> "ConfigCamara":
        """Copia con otra cámara: un entero (o texto numérico) es un índice; otro texto, un nombre."""
        if camara is None or (isinstance(camara, str) and not camara.strip()):
            return self
        texto = str(camara).strip()
        if texto.isdigit():
            return replace(self, indice=int(texto), nombre=None)
        return replace(self, nombre=texto)


# --------------------------------------------------------------------------- #
# Nombres de dispositivo
# --------------------------------------------------------------------------- #
def nombres_de_camaras() -> list[str | None]:
    """Nombres de las cámaras según el sistema, en el orden más probable de sus índices.

    En Linux la posición coincide con el índice (``/dev/videoN``; None donde no hay). En
    Windows el orden es orientativo: OpenCV no informa los nombres y el sistema los lista
    sin garantizar que coincidan con el índice de DirectShow. Por eso la selección fiable
    es por índice, confirmada con la vista previa de ``herramientas.listar_camaras``.
    Devuelve una lista vacía si el sistema no permite consultarlos.
    """
    try:
        if sys.platform.startswith("linux"):
            nombres: dict[int, str] = {}
            for carpeta in Path("/sys/class/video4linux").glob("video*"):
                numero = carpeta.name.removeprefix("video")
                if numero.isdigit():
                    nombres[int(numero)] = (carpeta / "name").read_text(encoding="utf-8").strip()
            return [nombres.get(i) for i in range(max(nombres) + 1)] if nombres else []
        if sys.platform == "win32":
            orden = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                     "Get-CimInstance Win32_PnPEntity | "
                     "Where-Object { $_.PNPClass -in 'Camera','Image' -and $_.Status -eq 'OK' } | "
                     "ForEach-Object { $_.Name }")
            salida = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", orden],
                capture_output=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.decode("utf-8", errors="replace")
            return [linea.strip() for linea in salida.splitlines() if linea.strip()]
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        log.debug("No se pudieron consultar los nombres de las cámaras: %s", error)
    return []


def _indice_por_nombre(nombre: str) -> int | None:
    """Índice de la primera cámara cuyo nombre contiene ``nombre`` (sin distinguir mayúsculas)."""
    coincidencias = [i for i, n in enumerate(nombres_de_camaras()) if n and nombre.lower() in n.lower()]
    if not coincidencias:
        return None
    if len(coincidencias) > 1:
        log.warning("Hay %d cámaras llamadas '%s'; se usa la primera (índice %d). "
                    "Con cámaras del mismo modelo, elige por índice.", len(coincidencias), nombre, coincidencias[0])
    return coincidencias[0]


# --------------------------------------------------------------------------- #
# Cámara con reconexión
# --------------------------------------------------------------------------- #
class Camara:
    """Cámara abierta desde un ``ConfigCamara``. Se crea con ``conectar_camara``.

    ``leer()`` devuelve el fotograma o None si en ese momento no hay imagen; nunca lanza ni
    bloquea más que un intento de apertura. Si la cámara se desconecta, ``conectada`` pasa a
    False, ``mensaje`` dice "Cámara desconectada, reconectando…" y cada ``reintento_s``
    segundos se intenta abrirla de nuevo.
    """

    def __init__(self, config: ConfigCamara) -> None:
        self.config = config
        self.indice: int | None = None  # índice realmente abierto
        self.resolucion: tuple[int, int] | None = None  # (ancho, alto) reales
        self.fps_informados: float | None = None  # los que dice el controlador
        self._captura: cv2.VideoCapture | None = None
        self._fallos = 0
        self._ultimo_intento = float("-inf")
        self._marcas: deque[float] = deque(maxlen=30)
        self._aviso_dado = False

    # ------------------------------------------------------------------ #
    @property
    def conectada(self) -> bool:
        return self._captura is not None

    @property
    def mensaje(self) -> str | None:
        """Texto para mostrar en pantalla cuando no hay cámara; None si está conectada."""
        return None if self.conectada else MENSAJE_DESCONECTADA

    @property
    def fps_reales(self) -> float:
        """Cuadros por segundo medidos sobre las últimas lecturas (0 si aún no hay datos)."""
        if len(self._marcas) < 2 or self._marcas[-1] == self._marcas[0]:
            return 0.0
        return (len(self._marcas) - 1) / (self._marcas[-1] - self._marcas[0])

    def leer(self) -> np.ndarray | None:
        """Fotograma más reciente (BGR), o None si la cámara no está entregando imagen."""
        if self._captura is None:
            if time.monotonic() - self._ultimo_intento < self.config.reintento_s:
                return None
            if not self.abrir():
                return None
        correcto, frame = self._captura.read()
        if correcto and frame is not None:
            self._fallos = 0
            self._marcas.append(time.monotonic())
            return frame
        self._fallos += 1
        if self._fallos >= FALLOS_PARA_DESCONECTAR:
            log.warning(MENSAJE_DESCONECTADA)
            self._soltar()
        return None

    def abrir(self) -> bool:
        """Intenta abrir y configurar la cámara. Devuelve si quedó entregando imagen."""
        self._ultimo_intento = time.monotonic()
        self._soltar()
        indice = self.config.indice
        if self.config.nombre:
            encontrado = _indice_por_nombre(self.config.nombre)
            if encontrado is None:
                self._avisar("No se encontró una cámara llamada '%s'; se intenta con el índice %d",
                             self.config.nombre, indice)
            else:
                indice = encontrado
        captura = cv2.VideoCapture(indice, _backend())
        if not captura.isOpened():
            captura.release()
            self._avisar("No se pudo abrir la cámara %d; se reintentará", indice)
            return False
        self._configurar(captura)
        correcto, frame = captura.read()
        if not correcto or frame is None:
            captura.release()
            self._avisar("La cámara %d abrió pero no entrega imagen; se reintentará", indice)
            return False
        self._captura, self.indice, self._fallos, self._aviso_dado = captura, indice, 0, False
        self._marcas.clear()
        self.resolucion = (frame.shape[1], frame.shape[0])
        self.fps_informados = captura.get(cv2.CAP_PROP_FPS) or None
        log.info("Cámara %d abierta: %dx%d a %s fps (pedido: %dx%d a %d fps, %s)", indice, *self.resolucion,
                 f"{self.fps_informados:.0f}" if self.fps_informados else "?", self.config.ancho,
                 self.config.alto, self.config.fps, self.config.formato)
        if self.resolucion != (self.config.ancho, self.config.alto):
            log.warning("La cámara %d no dio la resolución pedida: entrega %dx%d", indice, *self.resolucion)
        return True

    def cerrar(self) -> None:
        self._soltar()

    # ------------------------------------------------------------------ #
    def _configurar(self, captura: cv2.VideoCapture) -> None:
        c = self.config
        # El orden importa (medido con una Logitech en DirectShow): el formato va de ÚLTIMO.
        # Fijar los fps después de MJPG devuelve la cámara a YUY2, que en 720p solo da 10 fps.
        self._fijar(captura, cv2.CAP_PROP_FRAME_WIDTH, c.ancho, "ancho")
        self._fijar(captura, cv2.CAP_PROP_FRAME_HEIGHT, c.alto, "alto")
        self._fijar(captura, cv2.CAP_PROP_FPS, c.fps, "fps")
        if c.formato:
            self._fijar(captura, cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*c.formato), f"formato {c.formato}")
            codigo = int(captura.get(cv2.CAP_PROP_FOURCC))
            real = "".join(chr((codigo >> 8 * i) & 0xFF) for i in range(4))
            if real.isprintable() and real.strip("\x00") and real != c.formato:
                log.warning("La cámara quedó en formato %s y no en %s: puede entregar menos fps", real, c.formato)
        self._fijar(captura, cv2.CAP_PROP_BUFFERSIZE, 1, "búfer de 1 cuadro")  # siempre el más reciente
        self._fijar(captura, cv2.CAP_PROP_AUTOFOCUS, 1 if c.autofoco else 0,
                    "autofoco " + ("encendido" if c.autofoco else "apagado"))
        if not c.autofoco and c.enfoque is not None:
            self._fijar(captura, cv2.CAP_PROP_FOCUS, c.enfoque, f"enfoque fijo en {c.enfoque:g}")
        if c.exposicion is not None:
            # 0.25 es "manual" en V4L2; DirectShow pasa a manual al fijar el valor
            if _backend() == cv2.CAP_V4L2:
                self._fijar(captura, cv2.CAP_PROP_AUTO_EXPOSURE, 0.25, "exposición manual")
            self._fijar(captura, cv2.CAP_PROP_EXPOSURE, c.exposicion, f"exposición fija en {c.exposicion:g}")

    def _fijar(self, captura: cv2.VideoCapture, propiedad: int, valor: float, descripcion: str) -> None:
        """Fija una propiedad; si la cámara no la soporta, lo dice en el log y sigue."""
        try:
            aceptada = captura.set(propiedad, valor)
        except cv2.error:
            aceptada = False
        if not aceptada:
            log.info("La cámara no soporta '%s'; se continúa sin eso", descripcion)

    def _avisar(self, mensaje: str, *valores) -> None:
        """Advierte una vez por desconexión, no en cada reintento."""
        if not self._aviso_dado:
            log.warning(mensaje, *valores)
            self._aviso_dado = True

    def _soltar(self) -> None:
        if self._captura is not None:
            self._captura.release()
            self._captura = None


def conectar_camara(config: ConfigCamara | None = None) -> Camara:
    """Abre la cámara del stand según ``config`` y devuelve su control.

    Nunca lanza: si la cámara no está, devuelve una ``Camara`` desconectada que seguirá
    intentando abrirla en cada ``leer()``.
    """
    camara = Camara(config or ConfigCamara())
    camara.abrir()
    return camara
