"""Detectores YOLO de los perfiles de EPP (único archivo del módulo que usa Ultralytics)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

DIR_MODELOS = Path(__file__).parent / "modelos"


class ModeloNoDisponible(RuntimeError):
    """El modelo de un perfil no se pudo cargar. El mensaje es para mostrar al operador."""


class Detector:
    """Un modelo cargado. ``clases`` son las que sabe detectar, en el orden del modelo."""

    def __init__(self, ruta: Path, ajustes: dict[str, Any]) -> None:
        if not ruta.is_file():
            raise ModeloNoDisponible(f"no existe el archivo de pesos {ruta.name} en {DIR_MODELOS.as_posix()}")
        try:
            import torch
            from ultralytics import YOLO
        except ImportError as error:
            raise ModeloNoDisponible(
                f"falta instalar las dependencias del módulo ({error.name}); ver modulos/epp/README.md"
            ) from None
        try:
            self._modelo = YOLO(str(ruta))
        except Exception as error:  # pesos dañados o de otra versión
            raise ModeloNoDisponible(f"no se pudo leer {ruta.name} ({type(error).__name__}: {error})") from None
        self.ruta = ruta
        self.clases: list[str] = [self._modelo.names[i] for i in sorted(self._modelo.names)]
        self._dispositivo = 0 if torch.cuda.is_available() else "cpu"
        self._ajustes = dict(conf=ajustes.get("umbral_previo", 0.25), imgsz=ajustes.get("imgsz", 640),
                             max_det=ajustes.get("max_det", 50))
        # Primera inferencia en frío: carga el modelo en la GPU antes de abrir la ventana
        self.detectar(np.zeros((480, 640, 3), dtype=np.uint8))

    def detectar(self, frame: np.ndarray) -> list[dict[str, Any]]:
        """Detecciones del frame BGR con cajas normalizadas ``[x1, y1, x2, y2]`` en 0-1."""
        resultado = self._modelo.predict(frame, device=self._dispositivo, verbose=False, **self._ajustes)[0]
        cajas = resultado.boxes
        return [
            {"clase": self._modelo.names[int(clase)], "confianza": float(confianza), "caja": [float(v) for v in caja]}
            for caja, clase, confianza in zip(cajas.xyxyn.tolist(), cajas.cls.tolist(), cajas.conf.tolist())
        ]


def cargar_detectores(perfiles: dict[str, Any]) -> tuple[dict[str, Detector], dict[str, str]]:
    """Carga el modelo de cada perfil. Devuelve ``(detectores, errores)`` por nombre de perfil.

    Un modelo que falla no impide usar los demás perfiles.
    """
    detectores: dict[str, Detector] = {}
    errores: dict[str, str] = {}
    for nombre, perfil in perfiles["perfiles"].items():
        try:
            detectores[nombre] = Detector(DIR_MODELOS / perfil["modelo"], perfiles.get("detector") or {})
            log.info("Perfil '%s': modelo %s cargado (%s)", nombre, perfil["modelo"], ", ".join(detectores[nombre].clases))
        except ModeloNoDisponible as error:
            errores[nombre] = str(error)
            log.error("Perfil '%s' no disponible: %s", nombre, error)
    return detectores, errores
