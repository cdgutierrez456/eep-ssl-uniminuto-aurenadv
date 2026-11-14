"""Calibrador de la zona: une la detección de la cinta, el editor, la imagen de referencia y la configuración.

Atiende dos caminos que terminan en lo mismo, una ``zona_peligro`` guardada en la configuración:

- **Remoto** (la plataforma): el operador pulsa "Detectar zona" y la plataforma escribe
  ``solicitud_deteccion``. ``atender`` lo ve, detecta la cinta sobre el fotograma actual, sube
  una imagen de referencia nueva y responde en ``zona_propuesta``. La zona solo se activa
  cuando la persona la confirma en el editor de la plataforma, que la guarda como ``zona_peligro``.
- **Local** (la ventana de la estación, de respaldo): tecla para detectar, mouse para editar
  y tecla para guardar.

No abre ventanas ni lee la cámara: quien lo usa le pasa los fotogramas, las teclas y el mouse.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from modulos.comun import registrar_capacidades

from ..config.ajustes import CAPACIDADES, MODULO, zona_desde_config
from ..config.almacen import AlmacenConfig
from ..interfaz.marca import AMARILLO, MARFIL_TENUE, ROJO
from ..nucleo.geometria import desnormalizar
from .cinta import DeteccionCinta, RangoHSV, detectar_cinta
from .editor import EditorPoligono
from .referencia import Referencia, tomar_referencia
from .vista import dibujar_vertices, rellenar_poligono

log = logging.getLogger(__name__)

TECLA_ENTER, TECLA_ESC, TECLA_RETROCESO = 13, 27, 8
CUADROS_ANTES_DE_LA_REFERENCIA = 15  # la cámara necesita unos fotogramas para ajustar su exposición
AYUDA = "D detectar cinta  ·  E editar con el mouse  ·  G guardar  ·  M medidas reales  ·  R nueva imagen de referencia"
AYUDA_EDICION = ("Clic: agregar o agarrar un vértice  ·  Arrastrar: moverlo  ·  Clic derecho: quitarlo  ·  "
                 "C borrar todos  ·  G guardar  ·  Esc cancelar")
PREGUNTAS_DE_MEDIDA = ("Ancho real en metros (lado del vértice 1 al 2)", "Largo real en metros (lado del vértice 2 al 3)")


def _decimal(valor: float) -> str:
    return f"{valor:.2f}".replace(".", ",")


class Calibrador:
    """Estado de la calibración en curso. Llámese ``atender`` una vez por fotograma."""

    def __init__(self, almacen: AlmacenConfig, carpeta_referencia: Path | None = None) -> None:
        self.almacen = almacen
        self.editor: EditorPoligono | None = None
        self.editando = False
        self.referencia: Referencia | None = None
        self.deteccion: DeteccionCinta | None = None  # la última, para mostrar su máscara
        self.mensaje = ""  # último aviso para quien calibra
        self.medidas_en_curso: list[str] | None = None  # lo tecleado al pedir las medidas reales
        self._solicitud_atendida: str | None = None
        self._carpeta_referencia = carpeta_referencia

    # ----------------------------------------------------------- referencia
    def tomar_referencia(self, frame: np.ndarray) -> Referencia:
        """Toma la imagen de referencia (rostros difuminados), la sube y la reporta en las capacidades."""
        self.referencia = tomar_referencia(frame, subir=self.almacen.con_plataforma, carpeta=self._carpeta_referencia)
        if self.almacen.con_plataforma:
            registrar_capacidades(MODULO, {**CAPACIDADES, "imagen_referencia": self.referencia.para_capacidades()})
        return self.referencia

    # --------------------------------------------------------------- remoto
    def atender(self, frame: np.ndarray, config: Mapping[str, Any]) -> bool:
        """Atiende un pedido remoto de detección, si hay uno pendiente. Devuelve si lo hizo.

        Está pendiente cuando ``solicitud_deteccion`` no es null y no coincide con la
        ``solicitud`` que ya respondió ``zona_propuesta``.
        """
        solicitud = config.get("solicitud_deteccion")
        atendida = (config.get("zona_propuesta") or {}).get("solicitud")
        if not solicitud or solicitud in (atendida, self._solicitud_atendida):
            return False
        self._solicitud_atendida = solicitud
        deteccion = self.detectar(frame, config)
        referencia = self.tomar_referencia(frame)
        propuesta = {
            "solicitud": solicitud,
            "poligono": [list(vertice) for vertice in deteccion.poligono] if deteccion.poligono else None,
            "es_cuadrilatero": deteccion.es_cuadrilatero,
            "mensaje": deteccion.mensaje,
            "imagen_referencia": referencia.ruta,
        }
        self.almacen.actualizar({**config, "zona_propuesta": propuesta})
        log.info("Detección remota de la zona (%s): %s", solicitud, deteccion.mensaje)
        return True

    # ---------------------------------------------------------------- local
    def detectar(self, frame: np.ndarray, config: Mapping[str, Any]) -> DeteccionCinta:
        """Busca la cinta en el fotograma con el rango de color de la configuración."""
        self.deteccion = detectar_cinta(frame, RangoHSV.desde_config(config.get("cinta_hsv")))
        self.mensaje = self.deteccion.mensaje
        return self.deteccion

    def detectar_local(self, frame: np.ndarray, config: Mapping[str, Any]) -> DeteccionCinta:
        """Tecla de detectar: deja la propuesta en el editor, lista para corregir y guardar."""
        deteccion = self.detectar(frame, config)
        editor = self._editor_para(frame.shape[1], frame.shape[0])
        if deteccion.encontrada:
            editor.cargar(deteccion.poligono)
            editor.modificado = True  # es una propuesta nueva, todavía sin guardar
            self.editando = True
        return deteccion

    def editar(self, config: Mapping[str, Any], ancho: int, alto: int) -> None:
        """Entra a la edición con la propuesta pendiente, la zona activa o un polígono vacío."""
        editor = self._editor_para(ancho, alto)
        propuesta = (config.get("zona_propuesta") or {}).get("poligono")
        editor.cargar(propuesta or config.get("zona_peligro"))
        self.editando = True
        self.mensaje = "Editando la zona. Guarda con G para activarla."

    def cancelar(self) -> None:
        self.editando = False
        self.medidas_en_curso = None
        self.mensaje = "Edición cancelada: la zona activa no cambió."

    def guardar(self, config: Mapping[str, Any]) -> bool:
        """Confirma el polígono del editor como ``zona_peligro``. Devuelve si quedó guardada."""
        if self.editor is None or not self.editando:
            self.mensaje = "No hay nada que guardar: detecta la cinta (D) o edita la zona (E)."
            return False
        if not self.editor.valido:
            self.mensaje = "La zona necesita al menos tres vértices que encierren un área."
            return False
        nueva = {
            **config,
            "zona_peligro": self.editor.normalizado(),
            "zona_propuesta": None,
            "solicitud_deteccion": None,
            "imagen_referencia": self.referencia.ruta if self.referencia else config.get("imagen_referencia"),
        }
        try:
            llego = self.almacen.actualizar(nueva)
        except ValueError as error:
            self.mensaje = f"No se pudo guardar la zona: {error}"
            return False
        self.editando = False
        self.editor.modificado = False
        self.mensaje = "Zona guardada y activa." if llego or not self.almacen.con_plataforma else (
            "Zona guardada en la estación; se subirá a la plataforma cuando responda.")
        return True

    def guardar_medidas(self, config: Mapping[str, Any], ancho_m: float | None, largo_m: float | None) -> bool:
        """Guarda las medidas reales del rectángulo (None o 0 las quita: la zona vuelve a medir en píxeles)."""
        rectangulo = {"ancho_m": ancho_m, "largo_m": largo_m} if ancho_m and largo_m else None
        try:
            self.almacen.actualizar({**config, "rectangulo_real": rectangulo})
        except ValueError as error:
            self.mensaje = f"Medidas no válidas: {error}"
            return False
        self.mensaje = (f"Medidas guardadas: {_decimal(ancho_m)} × {_decimal(largo_m)} m." if rectangulo
                        else "Medidas quitadas: la zona mide en píxeles.")
        return True

    # ------------------------------------------------------ teclado y mouse
    def tecla(self, tecla: int, frame: np.ndarray | None, config: Mapping[str, Any]) -> bool:
        """Procesa una tecla. Devuelve True si era de la calibración (y ya no le toca a nadie más)."""
        if self.medidas_en_curso is not None:
            self._tecla_de_medida(tecla, config)
            return True
        letra = chr(tecla).lower() if 32 <= tecla < 127 else ""
        if letra == "d" and frame is not None:
            self.detectar_local(frame, config)
        elif letra == "e" and frame is not None:
            if self.editando:
                self.cancelar()
            else:
                self.editar(config, frame.shape[1], frame.shape[0])
        elif letra == "g" or (tecla == TECLA_ENTER and self.editando):
            self.guardar(config)
        elif letra == "c" and self.editando and self.editor is not None:
            self.editor.limpiar()
            self.mensaje = "Vértices borrados. Haz clic para marcar la zona."
        elif letra == "m":
            self.medidas_en_curso = [""]
            self.mensaje = ""
        elif letra == "r" and frame is not None:
            referencia = self.tomar_referencia(frame)
            self.mensaje = ("Imagen de referencia actualizada." if referencia.ruta or not self.almacen.con_plataforma
                            else "Imagen de referencia guardada en la estación; la plataforma no respondió.")
        elif tecla == TECLA_ESC and self.editando:
            self.cancelar()
        else:
            return False
        return True

    def mouse(self, evento: int, x: float, y: float) -> None:
        """Evento de mouse de OpenCV, con (x, y) ya en píxeles de la imagen de la cámara."""
        if not self.editando or self.editor is None or self.medidas_en_curso is not None:
            return
        if evento == cv2.EVENT_LBUTTONDOWN:
            self.editor.presionar(x, y)
        elif evento == cv2.EVENT_MOUSEMOVE:
            self.editor.mover(x, y)
        elif evento == cv2.EVENT_LBUTTONUP:
            self.editor.soltar()
        elif evento == cv2.EVENT_RBUTTONDOWN:
            self.editor.borrar(x, y)

    # ---------------------------------------------------------------- vista
    def dibujar(self, vista: np.ndarray, config: Mapping[str, Any]) -> None:
        """Dibuja sobre la vista la zona activa, la propuesta remota pendiente y, si se edita, el editor."""
        alto, ancho = vista.shape[:2]
        activa = config.get("zona_peligro")
        if activa:
            rellenar_poligono(vista, desnormalizar(activa, ancho, alto), ROJO, 0.12 if self.editando else 0.3)
        if self.editando and self.editor is not None:
            self.editor.redimensionar(ancho, alto)
            dibujar_vertices(vista, self.editor.vertices, AMARILLO, self.editor.agarrado)
            return
        propuesta = (config.get("zona_propuesta") or {}).get("poligono")
        if propuesta:
            dibujar_vertices(vista, desnormalizar(propuesta, ancho, alto), MARFIL_TENUE, radio=5, rotular_lados=False)

    def estado(self, config: Mapping[str, Any], ancho: int, alto: int) -> str:
        """Una línea sobre la zona vigente: si hay, cuántos vértices tiene y en qué mide."""
        zona = zona_desde_config(config, ancho, alto)
        if zona is None:
            return "Sin zona todavía: detecta la cinta (D) o márcala a mano (E)."
        if zona.en_metros:
            medidas = config["rectangulo_real"]
            return (f"Zona activa de {len(zona.poligono)} vértices. Mide en metros "
                    f"({_decimal(medidas['ancho_m'])} × {_decimal(medidas['largo_m'])} m).")
        return f"Zona activa de {len(zona.poligono)} vértices. Mide en píxeles: {zona.motivo_sin_metros}."

    def ayuda(self) -> str:
        """Texto de teclas o la pregunta en curso, para la barra inferior."""
        if self.medidas_en_curso is not None:
            paso = len(self.medidas_en_curso) - 1
            return f"{PREGUNTAS_DE_MEDIDA[paso]}: {self.medidas_en_curso[-1]}_   (Enter confirma, vacío quita las medidas, Esc cancela)"
        return AYUDA_EDICION if self.editando else AYUDA

    # ------------------------------------------------------------- internos
    def _editor_para(self, ancho: int, alto: int) -> EditorPoligono:
        if self.editor is None:
            self.editor = EditorPoligono(ancho, alto)
        else:
            self.editor.redimensionar(ancho, alto)
        return self.editor

    def _tecla_de_medida(self, tecla: int, config: Mapping[str, Any]) -> None:
        """Teclado mientras se piden las medidas reales: dígitos, coma o punto, retroceso, Enter y Esc."""
        entradas = self.medidas_en_curso
        if tecla == TECLA_ESC:
            self.medidas_en_curso = None
            self.mensaje = "Medidas sin cambios."
        elif tecla == TECLA_RETROCESO:
            entradas[-1] = entradas[-1][:-1]
        elif tecla == TECLA_ENTER:
            if len(entradas) < len(PREGUNTAS_DE_MEDIDA) and entradas[-1]:
                entradas.append("")
                return
            self.medidas_en_curso = None
            try:
                valores = [float(entrada.replace(",", ".")) for entrada in entradas if entrada]
            except ValueError:
                self.mensaje = "Medidas no válidas: escribe números, por ejemplo 1,5."
                return
            completas = len(valores) == len(PREGUNTAS_DE_MEDIDA)
            self.guardar_medidas(config, valores[0] if completas else None, valores[1] if completas else None)
        elif 32 <= tecla < 127 and (chr(tecla).isdigit() or chr(tecla) in ".,") and len(entradas[-1]) < 6:
            entradas[-1] += chr(tecla)
