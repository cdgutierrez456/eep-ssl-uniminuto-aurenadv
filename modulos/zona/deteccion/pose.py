"""Detector de personas con pose y seguimiento (único archivo del módulo que usa Ultralytics).

YOLO-pose nano preentrenado, de la misma familia que el resto del proyecto (YOLO26), con el
tracking integrado de Ultralytics: cada persona conserva un id de un fotograma al siguiente.
El modelo no se versiona; se baja una vez con ``python -m herramientas.descargar_modelos``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

import numpy as np

from .personas import Persona

log = logging.getLogger(__name__)

RUTA_MODELO = Path(__file__).resolve().parents[1] / "modelos" / "yolo26n-pose.pt"
CLASE_PERSONA = 0


class ModeloNoDisponible(RuntimeError):
    """El detector no se pudo cargar. El mensaje es para mostrárselo al operador."""


class Detector(Protocol):
    """Lo que la estación necesita de un detector (el real o uno simulado en las pruebas)."""

    descripcion: str

    def detectar(self, frame: np.ndarray, confianza: float) -> list[Persona]: ...

    def cerrar(self) -> None: ...


class DetectorPose:
    """YOLO-pose con seguimiento. ``detectar`` debe llamarse con fotogramas consecutivos de una misma cámara."""

    def __init__(self, ruta: Path = RUTA_MODELO, dispositivo: str | int = "cpu", imgsz: int = 640,
                 tracker: str = "bytetrack.yaml") -> None:
        ruta = Path(ruta)
        if not ruta.is_file():
            raise ModeloNoDisponible(
                f"falta el modelo {ruta.name}. Bájalo una vez, con internet: python -m herramientas.descargar_modelos")
        try:
            from ultralytics import YOLO
        except ImportError as error:
            raise ModeloNoDisponible(
                f"falta instalar las dependencias del módulo ({error.name}); ver modulos/zona/README.md") from None
        try:
            self._modelo = YOLO(str(ruta))
        except Exception as error:  # pesos dañados o de otra versión
            raise ModeloNoDisponible(f"no se pudo leer {ruta.name} ({type(error).__name__}: {error})") from None
        if self._modelo.task != "pose":
            raise ModeloNoDisponible(f"{ruta.name} no es un modelo de pose (es de '{self._modelo.task}')")
        self.dispositivo = dispositivo
        self._ajustes = dict(imgsz=imgsz, tracker=tracker, device=dispositivo, classes=[CLASE_PERSONA],
                             persist=True, verbose=False)
        self.descripcion = f"{ruta.stem} en {'CPU' if dispositivo == 'cpu' else 'GPU'}"
        try:
            # Primera inferencia en frío: carga el modelo y el tracker antes de abrir la ventana
            self.detectar(np.zeros((480, 640, 3), dtype=np.uint8), 0.5)
        except Exception as error:
            raise ModeloNoDisponible(f"el modelo no pudo procesar una imagen ({type(error).__name__}: {error})") from None
        self.reiniciar()

    def detectar(self, frame: np.ndarray, confianza: float = 0.4) -> list[Persona]:
        """Personas del fotograma BGR, cada una con su id de seguimiento, su caja y sus 17 puntos."""
        resultado = self._modelo.track(frame, conf=confianza, **self._ajustes)[0]
        cajas = resultado.boxes
        if cajas is None or len(cajas) == 0:
            return []
        ids = cajas.id.tolist() if cajas.id is not None else [None] * len(cajas)
        puntos = resultado.keypoints.data.tolist() if resultado.keypoints is not None else [[]] * len(cajas)
        return [
            Persona(
                persona_id=None if identificador is None else int(identificador),
                caja=tuple(float(valor) for valor in caja),
                confianza=float(confianza_caja),
                puntos=tuple((float(x), float(y), float(c)) for x, y, c in puntos_persona),
            )
            for identificador, caja, confianza_caja, puntos_persona
            in zip(ids, cajas.xyxy.tolist(), cajas.conf.tolist(), puntos)
        ]

    def reiniciar(self) -> None:
        """Olvida a las personas que venía siguiendo (al cambiar de cámara o de video)."""
        predictor = getattr(self._modelo, "predictor", None)
        for seguidor in getattr(predictor, "trackers", None) or []:
            reiniciar = getattr(seguidor, "reset", None)
            if callable(reiniciar):
                reiniciar()

    def cerrar(self) -> None:
        self._modelo = None
