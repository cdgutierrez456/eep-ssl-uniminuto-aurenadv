"""Dónde vive la configuración de la zona: en la plataforma o, sin ella, en un archivo local.

Con plataforma usa ``obtener_config`` y ``actualizar_config`` de ``modulos.comun``: la
plataforma manda, el módulo consulta, y un cambio hecho en la estación se sube. Sin
plataforma (``--sin-plataforma``) guarda la configuración en el mismo archivo de caché que
usa ``modulos.comun`` (``CARPETA_COLA/config/zona.json``), para que la zona marcada no se
pierda al cerrar y siga ahí cuando la estación vuelva a correr con plataforma.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from typing import Any

from modulos.comun import actualizar_config, obtener_config
from modulos.comun.config import leer_entorno

from .ajustes import MODULO, RUTA_POR_DEFECTO, validar_config

log = logging.getLogger(__name__)


class AlmacenConfig:
    """Configuración vigente de la zona. ``valor`` nunca bloquea."""

    def __init__(self, con_plataforma: bool = True) -> None:
        self.con_plataforma = con_plataforma
        self._remota = None
        self._cerrojo = threading.Lock()
        self._ruta_local = leer_entorno().carpeta_cola / "config" / f"{MODULO}.json"
        self._valor: dict[str, Any] = {}
        if con_plataforma:
            self._remota = obtener_config(MODULO, RUTA_POR_DEFECTO, validar=validar_config)
        else:
            self._valor = self._leer_local()

    @property
    def valor(self) -> dict[str, Any]:
        """Copia de la configuración vigente, ya validada."""
        if self._remota is not None:
            return self._remota.valor
        with self._cerrojo:
            return copy.deepcopy(self._valor)

    @property
    def fuente(self) -> str:
        """De dónde salió: ``plataforma``, ``cache``, ``defecto`` o ``local``."""
        return self._remota.fuente if self._remota is not None else "local"

    def actualizar(self, config: dict[str, Any]) -> bool:
        """Aplica un cambio hecho en la estación. Devuelve si quedó guardado donde corresponde.

        Con plataforma, True significa que le llegó (si no responde, queda aplicado en la
        estación y se sube después). Lanza ``ValueError`` si la configuración no es válida.
        """
        if self._remota is not None:
            return actualizar_config(MODULO, config)
        nueva = validar_config(config)
        with self._cerrojo:
            self._valor = nueva
        return self._guardar_local(nueva)

    def detener(self) -> None:
        if self._remota is not None:
            self._remota.detener()

    # ------------------------------------------------------------------ #
    def _leer_local(self) -> dict[str, Any]:
        if self._ruta_local.is_file():
            try:
                return validar_config(json.loads(self._ruta_local.read_text(encoding="utf-8")))
            except (OSError, ValueError) as error:
                log.warning("La configuración local de zona no sirve (%s); se usa la configuración por defecto", error)
        return validar_config({})

    def _guardar_local(self, config: dict[str, Any]) -> bool:
        try:
            self._ruta_local.parent.mkdir(parents=True, exist_ok=True)
            temporal = self._ruta_local.with_suffix(".tmp")
            temporal.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
            temporal.replace(self._ruta_local)
            return True
        except OSError as error:
            log.warning("No se pudo guardar la configuración local de zona: %s", error)
            return False
