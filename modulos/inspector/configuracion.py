"""Ajustes del inspector, leídos del .env (nunca claves ni valores fijos en el código).

La clave de la API no pasa por aquí: el cliente de Claude la toma de ANTHROPIC_API_KEY
y este módulo solo sabe decir si está o no.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from modulos.comun.config import RAIZ_REPO, leer_entorno

log = logging.getLogger(__name__)

MODULO = ESTACION = "inspector"
PUERTO_POR_DEFECTO = 8010
RUTA_ESQUEMA_CONFIG = RAIZ_REPO / "contrato" / "config_inspector.schema.json"

MODELOS = {
    "claude-sonnet-5-5": "Sonnet 5.5 (rápido, por defecto)",
    "claude-opus-5-5": "Opus 5.5 (mayor calidad)",
}
ESFUERZOS = ("low", "medium", "high", "xhigh", "max")
PROMPT_POR_DEFECTO = "sistema_v1"
CARPETA_PROMPTS = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True)
class Ajustes:
    """Cómo se analiza una foto."""

    modelo: str = "claude-sonnet-5-5"
    esfuerzo: str = "medium"
    max_peligros: int = 6
    tiempo_maximo_s: float = 60.0
    lado_max: int = 1568          # 2576 = alta resolución
    prompt: str = PROMPT_POR_DEFECTO
    max_tokens: int = 16000       # incluye el razonamiento del modelo, que no se ve
    intentos: int = 2             # el primero y un reintento
    espera_reintento_s: float = 2.0

    def __post_init__(self) -> None:
        if self.esfuerzo not in ESFUERZOS:
            raise ValueError(f"Esfuerzo '{self.esfuerzo}' no válido. Opciones: {', '.join(ESFUERZOS)}")
        if not 1 <= self.max_peligros <= 12:
            raise ValueError("El máximo de peligros debe estar entre 1 y 12")
        if self.tiempo_maximo_s <= 0:
            raise ValueError("El tiempo máximo debe ser mayor que cero")
        if not 200 <= self.lado_max <= 2576:
            raise ValueError("El lado máximo de la imagen debe estar entre 200 y 2576 px")
        if not self.modelo.strip():
            raise ValueError("Falta el modelo")

    def con(self, **cambios) -> "Ajustes":
        """Copia con algunos valores cambiados (valida de nuevo)."""
        return replace(self, **cambios)

    @classmethod
    def desde_entorno(cls) -> "Ajustes":
        """Lee los ajustes de las variables INSPECTOR_*. Un valor que no sirve se ignora con un aviso."""
        ajustes = cls()
        lecturas = (
            ("INSPECTOR_MODELO", "modelo", str),
            ("INSPECTOR_ESFUERZO", "esfuerzo", lambda texto: texto.lower()),
            ("INSPECTOR_MAX_PELIGROS", "max_peligros", int),
            ("INSPECTOR_TIEMPO_MAXIMO_S", "tiempo_maximo_s", float),
            ("INSPECTOR_IMAGEN_LADO_MAX", "lado_max", int),
            ("INSPECTOR_PROMPT", "prompt", _prompt_existente),
        )
        for variable, campo, convertir in lecturas:
            texto = (os.getenv(variable) or "").strip()
            if not texto:
                continue
            try:
                ajustes = ajustes.con(**{campo: convertir(texto)})
            except ValueError as error:
                log.warning("%s=%r no sirve (%s); se usa %r", variable, texto, error, getattr(ajustes, campo))
        return ajustes


def _prompt_existente(nombre: str) -> str:
    """El nombre del prompt, si su archivo existe en ``prompts/``."""
    if not (CARPETA_PROMPTS / f"{nombre}.md").is_file():
        raise ValueError(f"no existe prompts/{nombre}.md")
    return nombre


# --------------------------------------------------------------------------- #
# Servicio y configuración remota
# --------------------------------------------------------------------------- #
def _booleano(texto: str | None) -> bool:
    return (texto or "").strip().lower() in ("1", "true", "si", "sí", "on")


def puerto_del_servicio() -> int:
    """Puerto del servicio HTTP (INSPECTOR_PUERTO, 8010 por defecto)."""
    try:
        return int(os.getenv("INSPECTOR_PUERTO") or PUERTO_POR_DEFECTO)
    except ValueError:
        log.warning("INSPECTOR_PUERTO no es un número; se usa %d", PUERTO_POR_DEFECTO)
        return PUERTO_POR_DEFECTO


def config_por_defecto(ajustes: Ajustes | None = None) -> dict:
    """Configuración operativa inicial, tomada del .env. Es lo que el operador puede cambiar en vivo."""
    ajustes = ajustes or Ajustes.desde_entorno()
    return {
        "modelo": ajustes.modelo,
        "max_peligros": ajustes.max_peligros,
        "tiempo_maximo_s": ajustes.tiempo_maximo_s,
        "solo_escenas_preparadas": _booleano(os.getenv("INSPECTOR_SOLO_ESCENAS")),
    }


@lru_cache(maxsize=1)
def _validador_de_config() -> Draft202012Validator:
    return Draft202012Validator(json.loads(RUTA_ESQUEMA_CONFIG.read_text(encoding="utf-8")))


def validar_config(config: Any, base: dict | None = None) -> dict:
    """Valida una configuración remota y la completa con ``base`` (la del .env).

    Es el validador de ``modulos.comun.obtener_config``: lanza ValueError si la
    configuración no cumple ``contrato/config_inspector.schema.json`` o pide un modelo
    que el módulo no conoce, y entonces se conserva la anterior.
    """
    if not isinstance(config, dict):
        raise ValueError("la configuración debe ser un objeto JSON")
    errores = [f"{'/'.join(str(p) for p in error.absolute_path) or '(raíz)'}: {error.message}"
               for error in _validador_de_config().iter_errors(config)]
    if errores:
        raise ValueError("; ".join(errores[:3]))
    completa = {**(base if base is not None else config_por_defecto()), **config}
    if completa["modelo"] not in MODELOS:
        raise ValueError(f"modelo '{completa['modelo']}' desconocido. Opciones: {', '.join(MODELOS)}")
    return completa


def ajustes_con_config(ajustes: Ajustes, config: dict) -> Ajustes:
    """Los ajustes de análisis con lo que diga la configuración operativa."""
    return ajustes.con(modelo=config["modelo"], max_peligros=int(config["max_peligros"]),
                       tiempo_maximo_s=float(config["tiempo_maximo_s"]))


def capacidades(escenas: list[dict]) -> dict:
    """Lo que el módulo le cuenta a la plataforma para que pinte sus controles."""
    return {
        "modelos": [{"id": identificador, "nombre": nombre} for identificador, nombre in MODELOS.items()],
        "max_peligros": {"minimo": 1, "maximo": 12},
        "tiempo_maximo_s": {"minimo": 10, "maximo": 180},
        "ia_disponible": hay_clave(),
        "escenas_preparadas": [{"id": escena["id"], "nombre": escena["nombre"]} for escena in escenas],
    }


def hay_clave() -> bool:
    """Si la clave de la API está configurada en este equipo. Nunca devuelve ni registra la clave."""
    return bool((os.getenv("ANTHROPIC_API_KEY") or "").strip())


def leer_prompt(nombre: str = PROMPT_POR_DEFECTO) -> str:
    """Texto del prompt del sistema ``prompts/<nombre>.md``."""
    ruta = CARPETA_PROMPTS / f"{nombre}.md"
    if not ruta.is_file():
        raise ValueError(f"No existe el prompt '{nombre}' en {CARPETA_PROMPTS}")
    return ruta.read_text(encoding="utf-8").strip()


def carpeta_de_datos() -> Path:
    """Carpeta de trabajo del inspector (caché, costos, inspecciones): CARPETA_COLA/inspector."""
    return leer_entorno().carpeta_cola / "inspector"
