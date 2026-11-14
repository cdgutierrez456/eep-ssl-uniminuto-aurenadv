"""Configuración remota de los módulos: la plataforma manda y el módulo consulta.

Tres utilidades genéricas (sirven a cualquier módulo, no solo a EPP):

- ``registrar_capacidades(modulo, capacidades)``: le cuenta a la plataforma qué sabe
  hacer el módulo (PUT /api/modulos/{modulo}/capacidades).
- ``obtener_config(modulo, ...)``: arranca un hilo de fondo que consulta
  GET /api/modulos/{modulo}/config cada pocos segundos y avisa cuando cambia.
- ``actualizar_config(modulo, config)``: el módulo cambia su propia configuración
  (por ejemplo, por teclado) y la sube con PUT /api/modulos/{modulo}/config.

El módulo nunca expone un servidor y nunca se queda esperando a la plataforma: si no
responde, sigue con la última configuración válida guardada en disco y, si no hay
ninguna, con su archivo local por defecto.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

import httpx

from .config import leer_entorno

log = logging.getLogger(__name__)

TIEMPO_LIMITE_S = 3.0
INTERVALO_POR_DEFECTO_S = 3.0

Config = dict[str, Any]
Validador = Callable[[Any], Config]
AlCambiar = Callable[[Config], None]

_cerrojo = threading.Lock()
_activas: dict[str, "ConfigRemota"] = {}
_capacidades_pendientes: dict[str, Any] = {}


def _url(modulo: str, recurso: str) -> str:
    return f"{leer_entorno().api_url}/api/modulos/{modulo}/{recurso}"


def _intervalo_del_entorno() -> float:
    try:
        return max(0.2, float(os.getenv("CONFIG_INTERVALO_S", INTERVALO_POR_DEFECTO_S)))
    except ValueError:
        return INTERVALO_POR_DEFECTO_S


# --------------------------------------------------------------------------- #
# Capacidades
# --------------------------------------------------------------------------- #
def registrar_capacidades(modulo: str, capacidades: Any) -> bool:
    """Registra en la plataforma lo que el módulo sabe hacer. Devuelve si llegó.

    Si la plataforma no responde no es un error: queda pendiente y el hilo de
    ``obtener_config`` del mismo módulo lo reintenta cuando la plataforma vuelva.
    """
    try:
        httpx.put(_url(modulo, "capacidades"), json=capacidades, timeout=TIEMPO_LIMITE_S).raise_for_status()
    except httpx.HTTPError as error:
        with _cerrojo:
            _capacidades_pendientes[modulo] = capacidades
        log.warning("No se pudieron registrar las capacidades de '%s' (%s); se reintentará",
                    modulo, type(error).__name__)
        return False
    with _cerrojo:
        _capacidades_pendientes.pop(modulo, None)
    log.info("Capacidades de '%s' registradas en la plataforma", modulo)
    return True


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
class ConfigRemota:
    """Configuración viva de un módulo. Se crea con ``obtener_config``.

    - ``valor``: copia de la configuración vigente (nunca bloquea).
    - ``fuente``: de dónde salió: ``"plataforma"``, ``"cache"``, ``"defecto"`` o ``"local"``.
    - ``al_cambiar(funcion)``: registra un aviso; la función recibe la configuración
      nueva y se llama desde el hilo de fondo (o desde quien llame a ``actualizar_config``).
    - ``detener()``: para el hilo.
    """

    def __init__(self, modulo: str, por_defecto: Config | str | Path, validar: Validador | None,
                 intervalo_s: float | None) -> None:
        self.modulo = modulo
        self._validar = validar or (lambda config: config)
        self._intervalo_s = intervalo_s if intervalo_s is not None else _intervalo_del_entorno()
        self._avisos: list[AlCambiar] = []
        self._cerrojo = threading.RLock()
        self._parar = threading.Event()
        self._subida_pendiente = False
        self._plataforma_responde: bool | None = None
        self._ultima_recibida: Any = None  # lo último que mandó la plataforma, tal cual llegó
        self._ruta_cache = leer_entorno().carpeta_cola / "config" / f"{modulo}.json"
        self._valor, self.fuente = self._valor_inicial(por_defecto)
        self._hilo = threading.Thread(target=self._bucle, name=f"config-{modulo}", daemon=True)

    # ------------------------------------------------------------------ #
    @property
    def valor(self) -> Config:
        with self._cerrojo:
            return copy.deepcopy(self._valor)

    def al_cambiar(self, funcion: AlCambiar) -> None:
        with self._cerrojo:
            self._avisos.append(funcion)

    def detener(self) -> None:
        self._parar.set()
        if self._hilo.is_alive() and threading.current_thread() is not self._hilo:
            self._hilo.join(timeout=TIEMPO_LIMITE_S + 2)
        with _cerrojo:
            if _activas.get(self.modulo) is self:
                del _activas[self.modulo]

    # ------------------------------------------------------------------ #
    def _valor_inicial(self, por_defecto: Config | str | Path) -> tuple[Config, str]:
        """Caché local si existe y es válida; si no, la configuración por defecto."""
        if self._ruta_cache.is_file():
            try:
                en_cache = json.loads(self._ruta_cache.read_text(encoding="utf-8"))
                return self._validar(en_cache), "cache"
            except (OSError, ValueError) as error:
                log.warning("La caché de configuración de '%s' no sirve (%s); se usa la configuración por defecto",
                            self.modulo, error)
        if isinstance(por_defecto, (str, Path)):
            por_defecto = json.loads(Path(por_defecto).read_text(encoding="utf-8"))
        return self._validar(copy.deepcopy(por_defecto)), "defecto"

    def _guardar_cache(self, config: Config) -> None:
        try:
            self._ruta_cache.parent.mkdir(parents=True, exist_ok=True)
            temporal = self._ruta_cache.with_suffix(".tmp")
            temporal.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
            temporal.replace(self._ruta_cache)
        except OSError as error:
            log.warning("No se pudo guardar la caché de configuración de '%s': %s", self.modulo, error)

    def _aplicar(self, candidata: Any, fuente: str) -> bool:
        """Valida y aplica una configuración. Devuelve si quedó aplicada (aunque no cambie nada).

        Una configuración que el validador rechaza no se aplica: se conserva la anterior.
        """
        try:
            nueva = self._validar(copy.deepcopy(candidata))
        except ValueError as error:
            log.warning("Configuración de '%s' rechazada (%s): %s. Se conserva la anterior.",
                        self.modulo, fuente, error)
            return False
        with self._cerrojo:
            cambio = nueva != self._valor
            if cambio:
                self._valor = nueva
            self.fuente = fuente
            avisos = list(self._avisos) if cambio else []
        if cambio:
            self._guardar_cache(nueva)
            log.info("Configuración de '%s' actualizada desde %s", self.modulo, fuente)
        for aviso in avisos:
            try:
                aviso(copy.deepcopy(nueva))
            except Exception:  # un aviso que falla no puede tumbar el hilo de configuración
                log.exception("Falló un aviso de cambio de configuración de '%s'", self.modulo)
        return True

    def _aplicar_local(self, config: Config) -> bool:
        """Cambio hecho por el propio módulo: se aplica ya y se sube en cuanto se pueda."""
        if not self._aplicar(config, "local"):
            return False
        with self._cerrojo:
            self._subida_pendiente = True
        return self._subir()

    def _subir(self) -> bool:
        try:
            httpx.put(_url(self.modulo, "config"), json=self.valor, timeout=TIEMPO_LIMITE_S).raise_for_status()
        except httpx.HTTPError:
            return False
        with self._cerrojo:
            self._subida_pendiente = False
        return True

    # ------------------------------------------------------------------ #
    def _bucle(self) -> None:
        while not self._parar.is_set():
            self._consultar()
            self._parar.wait(self._intervalo_s)

    def _consultar(self) -> None:
        """Una vuelta: capacidades pendientes, subida pendiente y lectura de la plataforma."""
        try:
            with _cerrojo:
                capacidades = _capacidades_pendientes.get(self.modulo)
            if capacidades is not None:
                registrar_capacidades(self.modulo, capacidades)
            # Un cambio local que no llegó a la plataforma tiene prioridad sobre lo que ella tenga
            if self._subida_pendiente:
                if not self._subir():
                    raise httpx.ConnectError("la subida pendiente no llegó")
                self._marcar_respuesta(True)
                return
            respuesta = httpx.get(_url(self.modulo, "config"), timeout=TIEMPO_LIMITE_S)
            if respuesta.status_code == 404:
                # La plataforma aún no tiene configuración de este módulo: se le entrega la vigente
                self._marcar_respuesta(True)
                self._subir()
                return
            respuesta.raise_for_status()
            self._marcar_respuesta(True)
            recibida = respuesta.json()
            # Sin cambios en la plataforma no hay nada que revalidar (ni advertencias que repetir)
            if recibida != self._ultima_recibida:
                self._ultima_recibida = recibida
                self._aplicar(recibida, "plataforma")
        except (httpx.HTTPError, ValueError):
            self._marcar_respuesta(False)

    def _marcar_respuesta(self, responde: bool) -> None:
        """Deja en el log solo las transiciones, no cada consulta fallida."""
        if responde == self._plataforma_responde:
            return
        self._plataforma_responde = responde
        if responde:
            log.info("La plataforma responde: configuración de '%s' en línea", self.modulo)
        else:
            log.warning("La plataforma no responde: '%s' sigue con la configuración de %s",
                        self.modulo, self.fuente)


def obtener_config(
    modulo: str,
    por_defecto: Config | str | Path,
    validar: Validador | None = None,
    al_cambiar: AlCambiar | None = None,
    intervalo_s: float | None = None,
) -> ConfigRemota:
    """Arranca la consulta periódica de la configuración del módulo y la devuelve viva.

    No bloquea: el valor inicial sale de la caché local (última configuración válida) o,
    si no hay, de ``por_defecto`` (un diccionario o la ruta de un JSON). Después un hilo
    consulta la plataforma cada ``intervalo_s`` segundos (variable CONFIG_INTERVALO_S,
    3 s si no se indica).

    ``validar`` recibe la configuración candidata y devuelve la normalizada, o lanza
    ``ValueError`` para rechazarla (se conserva la anterior). ``al_cambiar`` se llama con
    la configuración nueva cada vez que cambia.

    Una sola por módulo: una segunda llamada detiene la anterior.
    """
    with _cerrojo:
        anterior = _activas.get(modulo)
    if anterior is not None:
        anterior.detener()
    config = ConfigRemota(modulo, por_defecto, validar, intervalo_s)
    if al_cambiar is not None:
        config.al_cambiar(al_cambiar)
    with _cerrojo:
        _activas[modulo] = config
    config._hilo.start()
    return config


def actualizar_config(modulo: str, config: Config) -> bool:
    """Cambia la configuración del módulo desde el propio módulo. Devuelve si llegó a la plataforma.

    Si el módulo tiene una ``obtener_config`` activa, el cambio se valida, se aplica de
    inmediato (con sus avisos) y, si la plataforma no responde, se sube más tarde. Una
    configuración que el validador rechaza lanza ``ValueError`` y no cambia nada.
    """
    with _cerrojo:
        activa = _activas.get(modulo)
    if activa is not None:
        activa._validar(copy.deepcopy(config))  # que el error le llegue a quien llama
        return activa._aplicar_local(config)
    try:
        httpx.put(_url(modulo, "config"), json=config, timeout=TIEMPO_LIMITE_S).raise_for_status()
    except httpx.HTTPError as error:
        log.warning("No se pudo subir la configuración de '%s' (%s)", modulo, type(error).__name__)
        return False
    return True
