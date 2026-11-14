"""Publicación de un levantamiento: fotograma crítico (difuminado) y evento ``evaluacion_reba``.

Todo sale por ``modulos.comun`` (``subir_medio`` y ``publicar``). El trabajo se hace en un
hilo aparte para que difuminar, guardar y subir no congelen la vista en vivo.

Privacidad: el fotograma crítico sale de la vista en vivo, así que pasa por
``imagen_para_guardar`` (rostros difuminados y, después, el esqueleto) antes de tocar el disco.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from modulos.comun import publicar, subir_medio
from modulos.comun.config import leer_entorno

from . import __version__
from .interfaz.dibujo import imagen_para_guardar
from .nucleo.angulos import AngulosCuerpo, Punto
from .nucleo.intentos import Intento
from .nucleo.reba import SEGMENTOS

log = logging.getLogger(__name__)

ESTACION = "ergonomia"
# Lo que una cámara lateral 2D no mide de forma fiable: no suma al puntaje y se declara
NO_EVALUADO = ["torsion", "inclinacion_lateral", "abduccion"]


@dataclass(frozen=True)
class Critico:
    """Lo que se conserva del fotograma crítico de un levantamiento."""

    frame: np.ndarray  # imagen original de la cámara (sin difuminar: solo vive en memoria)
    puntos: Mapping[str, Punto]
    angulos: AngulosCuerpo
    neutra: tuple[float, float] | None = None  # (tronco, cuello) neutros usados; None = sin calibrar


def datos_evaluacion(intento: Intento, angulos: AngulosCuerpo, config: Mapping[str, Any],
                     neutra: tuple[float, float] | None = None) -> dict[str, Any]:
    """Arma ``datos`` del evento ``evaluacion_reba`` a partir de un intento evaluado."""
    r = intento.resultado
    datos = {
        "puntaje": r.puntaje,
        "nivel": r.nivel,
        # Solo los ángulos estimados: un segmento sin estimar no lleva número
        "angulos": {s: round(a, 1) for s, a in angulos.como_dict().items() if a is not None},
        "duracion_s": round(intento.duracion_s, 1),
        "puntajes": {
            **{s: p for s, p in r.segmentos.items() if p is not None},
            "tabla_a": r.tabla_a, "carga": r.carga, "puntaje_a": r.puntaje_a,
            "tabla_b": r.tabla_b, "agarre": r.agarre, "puntaje_b": r.puntaje_b,
            "tabla_c": r.tabla_c, "actividad": r.actividad,
        },
        "lado": angulos.lado,
        "intento": intento.numero,
        "segmentos_no_estimados": [s for s in SEGMENTOS if s in r.no_estimados],
        "segmentos_asumidos": list(r.asumidos),
        "ajustes_aplicados": list(r.ajustes_aplicados),
        "no_evaluado": list(NO_EVALUADO),
        "peso_carga_kg": config["peso_carga_kg"],
        "agarre": config["agarre"],
    }
    if intento.desde_piso is not None:
        datos["desde_piso"] = intento.desde_piso
    tecnica = intento.tecnica
    datos["tecnica"] = {"espalda_max": round(tecnica.espalda, 1), "nivel_espalda": tecnica.nivel}
    if tecnica.rodillas is not None:
        datos["tecnica"].update(rodillas_max=round(tecnica.rodillas, 1), piernas=tecnica.piernas)
    if neutra is not None:
        # Los ángulos de tronco, cuello y brazo ya van medidos desde esta postura neutra
        datos["postura_neutra"] = {"tronco": round(neutra[0], 1), "cuello": round(neutra[1], 1)}
    return datos


def guardar_imagen(imagen: np.ndarray, ruta: Path) -> Path:
    """Escribe una imagen (ya difuminada) en disco; funciona también con tildes en la ruta."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    correcto, datos = cv2.imencode(ruta.suffix, imagen, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not correcto:
        raise OSError(f"No se pudo codificar la imagen {ruta}")
    datos.tofile(str(ruta))
    return ruta


@dataclass(frozen=True)
class Publicado:
    """Resultado de publicar un levantamiento."""

    evento: dict
    ruta_imagen: Path  # copia local del fotograma crítico (difuminado, con esqueleto)
    ruta_medio: str  # la ruta que devolvió subir_medio


class Publicador:
    """Publica los levantamientos en segundo plano, de a uno y en orden."""

    def __init__(self, carpeta: Path | None = None) -> None:
        self.carpeta = carpeta or leer_entorno().carpeta_cola / ESTACION / "capturas"
        self._hilo = ThreadPoolExecutor(max_workers=1, thread_name_prefix="publicar-ergonomia")

    def publicar_levantamiento(self, critico: Critico, intento: Intento, sesion_id: str | None,
                               config: Mapping[str, Any]) -> Future:
        """Encola la publicación y vuelve de inmediato. El futuro entrega un ``Publicado``."""
        futuro = self._hilo.submit(self._publicar, critico, intento, sesion_id, dict(config))
        futuro.add_done_callback(self._avisar_si_falla)
        return futuro

    def cerrar(self) -> None:
        """Espera a que terminen las publicaciones pendientes."""
        self._hilo.shutdown(wait=True)

    # ------------------------------------------------------------------ #
    def _publicar(self, critico: Critico, intento: Intento, sesion_id: str | None,
                  config: dict[str, Any]) -> Publicado:
        r = intento.resultado
        imagen = imagen_para_guardar(critico.frame, critico.puntos, critico.angulos.lado, r.segmentos,
                                     critico.angulos.como_dict())
        nombre = f"reba-{sesion_id or 'sin-numero'}-{intento.numero:02d}-{uuid.uuid4().hex[:8]}.jpg"
        ruta_imagen = guardar_imagen(imagen, self.carpeta / nombre)
        ruta_medio = subir_medio(ruta_imagen)
        evento = publicar(
            ESTACION, "evaluacion_reba", datos_evaluacion(intento, critico.angulos, config, critico.neutra),
            severidad=r.severidad, sesion_id=sesion_id,
            adjuntos=[{"tipo": "imagen", "ruta": ruta_medio}], modulo_version=__version__,
        )
        return Publicado(evento, ruta_imagen, ruta_medio)

    @staticmethod
    def _avisar_si_falla(futuro: Future) -> None:
        if not futuro.cancelled() and futuro.exception() is not None:
            log.error("No se pudo publicar el levantamiento", exc_info=futuro.exception())
