"""Análisis de una foto con Claude: una llamada, salida JSON validada contra el esquema.

La foto llega ya preparada (orientada, con los rostros difuminados y del tamaño que se
envía): este módulo no la guarda ni la modifica. La salida del modelo se pide con salidas
estructuradas (``output_config.format``) y se vuelve a validar en local; si no cumple, se
reintenta una vez. La clave de la API solo se lee del entorno y nunca se registra.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import anthropic
import numpy as np

from modulos.comun.eventos import ZONA_HORARIA

from ..configuracion import Ajustes, hay_clave, leer_prompt
from ..nucleo.esquema import AnalisisInvalido, esquema_para_api, normalizar_analisis
from ..nucleo.imagen import codificar_jpeg
from . import costos
from .cache import CacheDeAnalisis
from .costos import RegistroDeCostos, costo_usd

log = logging.getLogger(__name__)

MENSAJE_RECHAZO = "No pudimos analizar esta foto. Intenta con otra toma o usa una escena preparada."

# Mensajes para la persona, por código de error. Ninguno menciona detalles técnicos ni la clave.
MENSAJES = {
    "sin_clave": "El análisis con IA no está configurado en este equipo. Usa una escena preparada.",
    "sin_conexion": "No hay conexión a internet para analizar la foto. Intenta de nuevo o usa una escena preparada.",
    "tiempo_agotado": "El análisis tardó más de lo esperado. Intenta de nuevo o usa una escena preparada.",
    "rechazo": MENSAJE_RECHAZO,
    "limite": "El servicio de análisis está ocupado. Espera unos segundos e intenta de nuevo, o usa una escena preparada.",
    "servicio": "El servicio de análisis no está disponible en este momento. Intenta de nuevo o usa una escena preparada.",
    "respuesta_invalida": "El análisis no salió bien esta vez. Intenta de nuevo o usa una escena preparada.",
    "solicitud": "No se pudo analizar la foto por un problema de configuración. Avisa al equipo del stand o usa una "
                 "escena preparada.",
}
CALIDAD_JPEG = 90
TIEMPO_MINIMO_POR_INTENTO_S = 3.0


class ErrorDeAnalisis(Exception):
    """El análisis no se pudo completar.

    ``codigo`` dice qué pasó (clave de ``MENSAJES``), ``mensaje`` es el texto para la
    persona y ``detalle`` es técnico, solo para el log.
    """

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(MENSAJES[codigo])
        self.codigo = codigo
        self.mensaje = MENSAJES[codigo]
        self.detalle = detalle


@dataclass(frozen=True)
class ResultadoAnalisis:
    """Análisis de una foto, en la forma interna del módulo, con lo que costó obtenerlo."""

    analisis: dict
    origen: str                  # "ia" o "cache"
    analisis_id: str
    modelo: str
    esfuerzo: str
    prompt: str
    ancho: int
    alto: int
    tokens_entrada: int
    tokens_salida: int
    costo_usd: float | None      # None si el modelo no tiene precio configurado
    duracion_s: float
    intentos: int


class Analizador:
    """Analiza fotos con Claude, con caché por foto y registro de costos.

    ``cliente`` es un cliente de Anthropic (o uno simulado con ``messages.create``); si no
    se pasa, se crea con la clave del entorno la primera vez que hace falta.
    """

    def __init__(self, ajustes: Ajustes | None = None, *, cliente: Any = None,
                 cache: CacheDeAnalisis | None = None, registro: RegistroDeCostos | None = None,
                 dormir: Callable[[float], None] = time.sleep,
                 reloj: Callable[[], float] = time.monotonic) -> None:
        self.ajustes = ajustes or Ajustes.desde_entorno()
        self._cliente = cliente
        self._cache = cache
        self._registro = registro
        self._dormir = dormir
        self._reloj = reloj

    # ------------------------------------------------------------------ #
    def analizar(self, frame: np.ndarray, *, hash_foto: str | None = None, analisis_id: str | None = None,
                 ajustes: Ajustes | None = None, usar_cache: bool = True) -> ResultadoAnalisis:
        """Devuelve los peligros visibles en ``frame`` (ya difuminado y del tamaño que se envía).

        ``hash_foto`` es la huella de la foto original: con ella, una foto ya analizada con
        los mismos ajustes sale de la caché sin llamar a la API. Lanza ErrorDeAnalisis si
        no hay clave, no hay conexión, se agota el tiempo, el modelo declina la foto o la
        salida no cumple el esquema después de un reintento.
        """
        ajustes = ajustes or self.ajustes
        analisis_id = analisis_id or uuid.uuid4().hex[:12]
        alto, ancho = frame.shape[:2]
        inicio = self._reloj()

        clave = None
        if self._cache is not None and hash_foto:
            clave = self._cache.clave(hash_foto, modelo=ajustes.modelo, esfuerzo=ajustes.esfuerzo,
                                      prompt=ajustes.prompt, max_peligros=ajustes.max_peligros,
                                      ancho=ancho, alto=alto)
            guardado = self._cache.leer(clave) if usar_cache else None
            if guardado and isinstance(guardado.get("analisis"), dict):
                self._registrar(analisis_id, 0, ajustes, ancho, alto, resultado=costos.CACHE,
                                peligros=len(guardado["analisis"].get("peligros", [])),
                                detalle=f"analizada el {guardado.get('fecha', '?')}")
                return ResultadoAnalisis(
                    analisis=guardado["analisis"], origen="cache", analisis_id=analisis_id,
                    modelo=ajustes.modelo, esfuerzo=ajustes.esfuerzo, prompt=ajustes.prompt,
                    ancho=ancho, alto=alto, tokens_entrada=0, tokens_salida=0, costo_usd=0.0,
                    duracion_s=round(self._reloj() - inicio, 2), intentos=0)

        cliente = self._obtener_cliente()
        solicitud = self._solicitud(frame, ajustes)
        limite = inicio + ajustes.tiempo_maximo_s
        entrada_total = salida_total = 0
        costo_total: float | None = 0.0
        ultimo: ErrorDeAnalisis | None = None

        for intento in range(1, ajustes.intentos + 1):
            restante = limite - self._reloj()
            if restante < TIEMPO_MINIMO_POR_INTENTO_S:
                raise ultimo or ErrorDeAnalisis("tiempo_agotado", "sin tiempo para otro intento")
            inicio_intento = self._reloj()
            try:
                respuesta = cliente.messages.create(**solicitud, timeout=restante)
            except anthropic.APIError as error:
                codigo, reintentable, detalle = _clasificar(error)
                ultimo = ErrorDeAnalisis(codigo, detalle)
                self._registrar(analisis_id, intento, ajustes, ancho, alto, resultado=costos.ERROR,
                                duracion=self._reloj() - inicio_intento, detalle=f"{codigo}: {detalle}")
                if not reintentable or intento == ajustes.intentos:
                    raise ultimo from error
                espera = min(max(ajustes.espera_reintento_s, _espera_pedida(error)), limite - self._reloj())
                if espera > 0:
                    self._dormir(espera)
                continue

            entrada, salida, costo = _uso(respuesta, ajustes.modelo)
            entrada_total += entrada
            salida_total += salida
            costo_total = None if costo is None or costo_total is None else costo_total + costo
            duracion = self._reloj() - inicio_intento

            if respuesta.stop_reason == "refusal":
                detalle = f"categoría: {getattr(getattr(respuesta, 'stop_details', None), 'category', None) or '?'}"
                self._registrar(analisis_id, intento, ajustes, ancho, alto, entrada, salida, costo, duracion,
                                costos.RECHAZO, detalle=detalle)
                raise ErrorDeAnalisis("rechazo", detalle)  # la misma foto volvería a declinarse: no se reintenta

            try:
                analisis = normalizar_analisis(_json_de(respuesta), ancho, alto, ajustes.max_peligros)
            except AnalisisInvalido as error:
                ultimo = ErrorDeAnalisis("respuesta_invalida", str(error))
                self._registrar(analisis_id, intento, ajustes, ancho, alto, entrada, salida, costo, duracion,
                                costos.INVALIDO, detalle=str(error)[:300])
                continue

            self._registrar(analisis_id, intento, ajustes, ancho, alto, entrada, salida, costo, duracion,
                            costos.OK, peligros=len(analisis["peligros"]))
            resultado = ResultadoAnalisis(
                analisis=analisis, origen="ia", analisis_id=analisis_id, modelo=ajustes.modelo,
                esfuerzo=ajustes.esfuerzo, prompt=ajustes.prompt, ancho=ancho, alto=alto,
                tokens_entrada=entrada_total, tokens_salida=salida_total,
                costo_usd=None if costo_total is None else round(costo_total, 6),
                duracion_s=round(self._reloj() - inicio, 2), intentos=intento)
            if clave is not None:
                self._cache.guardar(clave, {
                    "analisis": analisis, "modelo": ajustes.modelo, "esfuerzo": ajustes.esfuerzo,
                    "prompt": ajustes.prompt, "ancho": ancho, "alto": alto,
                    "tokens_entrada": entrada_total, "tokens_salida": salida_total,
                    "costo_usd": resultado.costo_usd, "duracion_s": resultado.duracion_s,
                    "fecha": datetime.now(ZONA_HORARIA).isoformat(timespec="seconds"),
                })
            return resultado

        raise ultimo or ErrorDeAnalisis("respuesta_invalida")

    # ------------------------------------------------------------------ #
    def _obtener_cliente(self) -> Any:
        if self._cliente is None:
            if not hay_clave():
                log.warning("No hay clave de la API (ANTHROPIC_API_KEY) en el entorno: no se puede analizar con IA")
                raise ErrorDeAnalisis("sin_clave", "ANTHROPIC_API_KEY no está definida")
            # Sin reintentos automáticos del SDK: los maneja este módulo, dentro del tiempo máximo
            self._cliente = anthropic.Anthropic(max_retries=0)
        return self._cliente

    def _solicitud(self, frame: np.ndarray, ajustes: Ajustes) -> dict:
        """Parámetros de ``messages.create``: prompt del sistema, la foto y el esquema de salida."""
        alto, ancho = frame.shape[:2]
        imagen = base64.standard_b64encode(codificar_jpeg(frame, CALIDAD_JPEG)).decode("ascii")
        instruccion = (
            f"Analiza esta foto de un lugar de trabajo y devuelve los peligros que se ven. "
            f"La imagen mide {ancho} x {alto} píxeles: las cajas van en esos píxeles. "
            f"Devuelve como máximo {ajustes.max_peligros} peligros, del más grave al menos grave."
        )
        return {
            "model": ajustes.modelo,
            "max_tokens": ajustes.max_tokens,
            "system": leer_prompt(ajustes.prompt),
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": imagen}},
                    {"type": "text", "text": instruccion},
                ],
            }],
            # El razonamiento del modelo se regula con el esfuerzo; el formato obliga a cumplir el esquema
            "output_config": {
                "effort": ajustes.esfuerzo,
                "format": {"type": "json_schema", "schema": esquema_para_api()},
            },
        }

    def _registrar(self, analisis_id: str, intento: int, ajustes: Ajustes, ancho: int, alto: int,
                   entrada: int = 0, salida: int = 0, costo: float | None = 0.0, duracion: float = 0.0,
                   resultado: str = costos.OK, peligros: int | str = "", detalle: str = "") -> None:
        if self._registro is None:
            return
        self._registro.registrar(
            analisis_id=analisis_id, intento=intento, modelo=ajustes.modelo, esfuerzo=ajustes.esfuerzo,
            ancho=ancho, alto=alto, tokens_entrada=entrada, tokens_salida=salida,
            costo_usd="" if costo is None else f"{costo:.6f}", duracion_s=f"{duracion:.2f}",
            resultado=resultado, peligros=peligros, detalle=detalle)


# --------------------------------------------------------------------------- #
# Lectura de la respuesta y de los errores
# --------------------------------------------------------------------------- #
def _uso(respuesta: Any, modelo: str) -> tuple[int, int, float | None]:
    """Tokens de entrada y de salida de la respuesta y su costo estimado."""
    uso = getattr(respuesta, "usage", None)
    lectura = getattr(uso, "cache_read_input_tokens", 0) or 0
    escritura = getattr(uso, "cache_creation_input_tokens", 0) or 0
    entrada = (getattr(uso, "input_tokens", 0) or 0) + lectura + escritura
    salida = getattr(uso, "output_tokens", 0) or 0
    costo = costo_usd(modelo, entrada - lectura - escritura, salida, lectura_cache=lectura, escritura_cache=escritura)
    return entrada, salida, costo


def _json_de(respuesta: Any) -> Any:
    """El JSON que escribió el modelo. Lanza AnalisisInvalido si no hay texto o no es JSON completo."""
    if respuesta.stop_reason == "max_tokens":
        raise AnalisisInvalido("La respuesta se cortó antes de terminar (max_tokens)")
    texto = "".join(bloque.text for bloque in respuesta.content if getattr(bloque, "type", None) == "text")
    if not texto.strip():
        raise AnalisisInvalido("La respuesta no trae texto")
    try:
        return json.loads(texto)
    except ValueError as error:
        raise AnalisisInvalido(f"La respuesta no es un JSON válido: {error}") from error


def _clasificar(error: anthropic.APIError) -> tuple[str, bool, str]:
    """(código para la persona, si vale la pena reintentar, detalle para el log)."""
    detalle = type(error).__name__
    if isinstance(error, anthropic.APITimeoutError):
        return "tiempo_agotado", True, detalle
    if isinstance(error, anthropic.APIConnectionError):
        return "sin_conexion", True, detalle
    if isinstance(error, anthropic.APIStatusError):
        detalle = f"{detalle} {error.status_code}: {str(error.message)[:200]}"
        if isinstance(error, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return "sin_clave", False, detalle
        if isinstance(error, anthropic.RateLimitError):
            return "limite", True, detalle
        if error.status_code >= 500 or error.status_code in (408, 409):
            return "servicio", True, detalle
        return "solicitud", False, detalle
    return "servicio", False, detalle


def _espera_pedida(error: anthropic.APIError) -> float:
    """Segundos que el servicio pide esperar antes de reintentar (cabecera retry-after), o 0."""
    respuesta = getattr(error, "response", None)
    try:
        return float(respuesta.headers.get("retry-after", 0)) if respuesta is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
