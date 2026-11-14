"""Ajustes del inspector, leídos del .env (nunca claves ni valores fijos en el código).

La clave de la API no pasa por aquí: el cliente de Claude la toma de ANTHROPIC_API_KEY
y este módulo solo sabe decir si está o no.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path

from modulos.comun.config import leer_entorno

log = logging.getLogger(__name__)

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
