"""Publicación de los eventos de la zona, con sus fotos.

Todo sale por ``modulos.comun`` (``publicar`` y ``subir_medio``):

- ``estado_zona`` se publica en el acto y como urgente: de él depende la alarma.
- ``ingreso_zona`` lleva la foto del momento en que la persona entró; ``casi_accidente``, la
  del momento en que estuvo más cerca. Difuminar, guardar y subir la foto se hace en un hilo
  aparte para no frenar la vista en vivo.

Privacidad: los fotogramas se conservan en memoria tal como llegan de la cámara y solo salen
por ``imagen_para_guardar``, que difumina los rostros antes de dibujar encima.
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

import cv2
import numpy as np

from modulos.comun import eventos_pendientes, publicar, subir_medio
from modulos.comun.config import leer_entorno
from modulos.comun.eventos import ZONA_HORARIA

from . import __version__
from .config.ajustes import ESTACION
from .interfaz.dibujo import Caja, imagen_para_guardar
from .nucleo.estados import Resultado, VistaPersona
from .nucleo.eventos import EventoZona
from .nucleo.zona import Zona

log = logging.getLogger(__name__)

INTERVALO_REVISION_COLA_S = 0.5  # cada cuánto se mira si la plataforma está recibiendo


@dataclass(frozen=True)
class Foto:
    """Un momento que puede terminar adjunto a un evento. Vive solo en memoria hasta entonces."""

    frame: np.ndarray  # imagen original de la cámara, sin difuminar
    persona: VistaPersona
    caja: Caja | None
    estado: str  # estado de la zona en ese momento


def guardar_imagen(imagen: np.ndarray, ruta: Path) -> Path:
    """Escribe una imagen (ya difuminada) en disco; funciona también con tildes en la ruta."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    correcto, datos = cv2.imencode(ruta.suffix, imagen, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not correcto:
        raise OSError(f"No se pudo codificar la imagen {ruta}")
    datos.tofile(str(ruta))
    return ruta


class Publicador:
    """Lleva los eventos de la zona a la plataforma y guarda las fotos que los acompañan.

    Con ``con_plataforma=False`` no publica ni guarda nada: solo cuenta, para el panel.
    """

    def __init__(self, con_plataforma: bool = True, carpeta: Path | None = None) -> None:
        self.con_plataforma = con_plataforma
        self.carpeta = carpeta or leer_entorno().carpeta_cola / ESTACION / "capturas"
        self.ingresos = 0
        self.casi_accidentes = 0
        self._entradas: dict[int, Foto] = {}  # por persona: el momento en que se confirmó dentro
        self._minimos: dict[int, Foto] = {}  # por persona: el momento en que estuvo más cerca
        self._hilo = ThreadPoolExecutor(max_workers=1, thread_name_prefix="publicar-zona")
        self._en_cola = 0
        self._revisado = float("-inf")

    # ------------------------------------------------------------------ #
    @property
    def en_cola(self) -> int:
        """Eventos que la plataforma todavía no recibió (se mira el disco a lo sumo dos veces por segundo)."""
        if not self.con_plataforma:
            return 0
        ahora = time.monotonic()
        if ahora - self._revisado >= INTERVALO_REVISION_COLA_S:
            self._revisado = ahora
            self._en_cola = eventos_pendientes(ESTACION)
        return self._en_cola

    @property
    def plataforma_recibe(self) -> bool:
        """True si los eventos están llegando: la alarma de la plataforma puede sonar."""
        return self.con_plataforma and self.en_cola == 0

    # ------------------------------------------------------------------ #
    def procesar(self, resultado: Resultado, frame: np.ndarray, zona: Zona,
                 cajas: Mapping[int, Caja] | None = None) -> None:
        """Atiende lo que dejó un fotograma: guarda en memoria los momentos de foto y publica los eventos."""
        cajas = cajas or {}
        estado = resultado.estado.estado
        copia: np.ndarray | None = None  # una sola copia del fotograma, aunque la usen varias personas
        for persona in resultado.personas:
            if persona.heredada_de is not None:  # el tracker le cambió el id: sus fotos pasan al nuevo
                for fotos in (self._entradas, self._minimos):
                    if persona.heredada_de in fotos:
                        fotos.setdefault(persona.persona_id, fotos.pop(persona.heredada_de))
            if persona.entro_a_peligro or persona.nuevo_minimo:
                if copia is None:
                    copia = frame.copy()
                foto = Foto(copia, persona, cajas.get(persona.persona_id), estado)
                if persona.entro_a_peligro:
                    self._entradas[persona.persona_id] = foto
                if persona.nuevo_minimo:
                    self._minimos[persona.persona_id] = foto
        self.publicar(resultado.eventos, zona)
        # Solo se conservan las fotos de quien sigue en un acercamiento: las de quien ya no se
        # sigue, o volvió a quedar libre sin que saliera un evento, no van a hacer falta
        en_curso = {persona.persona_id for persona in resultado.personas
                    if persona.estado != "libre" or persona.nivel != "libre"}
        for fotos in (self._entradas, self._minimos):
            for persona_id in [clave for clave in fotos if clave not in en_curso]:
                del fotos[persona_id]

    def publicar(self, eventos: Iterable[EventoZona], zona: Zona) -> None:
        """Publica los eventos: el estado de la zona en el acto; los de cada persona, con su foto."""
        for evento in eventos:
            if evento.tipo == "estado_zona":
                if self.con_plataforma:
                    publicar(ESTACION, evento.tipo, evento.datos, evento.severidad, urgente=True,
                             modulo_version=__version__)
                continue
            foto = None
            if evento.tipo == "ingreso_zona":
                self.ingresos += 1
                foto = self._entradas.pop(evento.persona_id, None)
            elif evento.tipo == "casi_accidente":
                self.casi_accidentes += 1
                foto = self._minimos.pop(evento.persona_id, None)
            log.info("Zona '%s': %s %s", zona.zona_id, evento.tipo, evento.datos)
            if self.con_plataforma:
                self._hilo.submit(self._publicar_con_foto, evento, foto, zona).add_done_callback(self._avisar_si_falla)

    def cerrar(self) -> None:
        """Espera a que terminen las publicaciones pendientes."""
        self._hilo.shutdown(wait=True)

    # ------------------------------------------------------------------ #
    def _publicar_con_foto(self, evento: EventoZona, foto: Foto | None, zona: Zona) -> dict:
        adjuntos = None
        if foto is not None:
            # La foto sale de la vista en vivo: se difumina y después se dibujan la zona y la persona
            imagen = imagen_para_guardar(foto.frame, zona, [foto.persona], {foto.persona.persona_id: foto.caja}
                                         if foto.caja else None, foto.estado)
            marca = datetime.now(ZONA_HORARIA).strftime("%Y%m%d-%H%M%S")
            ruta = guardar_imagen(imagen, self.carpeta / f"{evento.tipo}-{marca}-{uuid.uuid4().hex[:8]}.jpg")
            adjuntos = [{"tipo": "imagen", "ruta": subir_medio(ruta)}]
        return publicar(ESTACION, evento.tipo, evento.datos, evento.severidad, adjuntos=adjuntos,
                        modulo_version=__version__)

    @staticmethod
    def _avisar_si_falla(futuro: Future) -> None:
        if not futuro.cancelled() and futuro.exception() is not None:
            log.error("No se pudo publicar un evento de zona", exc_info=futuro.exception())
