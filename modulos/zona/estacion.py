"""Bucle principal de la estación de zona: cámara → personas → zona → pantalla y eventos.

Privacidad: lo que se muestra en la ventana es un espejo en vivo y no se difumina. Lo que
sale de ahí (las fotos de los eventos, la imagen de referencia, las capturas) pasa por
``imagen_para_guardar`` o ``tomar_referencia``, que difuminan los rostros antes de dibujar.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from modulos.comun import conectar_camara, esperar_envios, iniciar_latido
from modulos.comun.camara_stand import MENSAJE_DESCONECTADA

from .calibracion.calibrador import CUADROS_ANTES_DE_LA_REFERENCIA, TECLA_ESC, Calibrador
from .calibracion.cinta import RangoHSV
from .calibracion.vista import resaltar_amarillo
from .config import ESTACION, MODULO, AjustesLocales, AlmacenConfig, parametros_desde, zona_desde_config
from .deteccion.dispositivo import resolver_dispositivo
from .deteccion.personas import Persona, puntos_de_apoyo
from .deteccion.pose import RUTA_MODELO, Detector, DetectorPose, ModeloNoDisponible
from .fuentes import FuenteVideo
from .interfaz.dibujo import dibujar_detecciones, dibujar_personas, dibujar_zona, imagen_para_guardar
from .interfaz.panel import EstadoPantalla, Pantalla
from .interfaz.sonido import SonidoLocal
from .nucleo.estados import MonitorZona, Resultado
from .nucleo.eventos import EstadoZona
from .publicacion import Publicador

log = logging.getLogger(__name__)

VENTANA = "Auren SST - Zona de peligro"
AYUDA_GENERAL = "  ·  V ver máscara  ·  S sonido local  ·  F pantalla completa  ·  Q salir"
SUAVIZADO_FPS = 0.1  # peso del último fotograma en el promedio de fps que muestra el panel


def _clave_de_zona(config: Mapping[str, Any], ancho: int, alto: int) -> str:
    """Todo lo que, si cambia, obliga a rehacer la zona (y con ella la vigilancia)."""
    return json.dumps([config["zona_peligro"], config["rectangulo_real"], config["margen_advertencia_m"],
                       config["margen_advertencia_px"], config["deteccion"]["histeresis"], ancho, alto])


class Estacion:
    """Une la fuente de video, el detector, la vigilancia de la zona, la calibración y la pantalla."""

    def __init__(self, opciones: argparse.Namespace, ajustes: AjustesLocales | None = None,
                 detector: Detector | None = None) -> None:
        self.opciones = opciones
        self.ajustes = ajustes or AjustesLocales.desde_entorno()
        self.con_plataforma = not opciones.sin_plataforma
        if detector is None:
            dispositivo, motivo = resolver_dispositivo(opciones.dispositivo or self.ajustes.dispositivo)
            log.info("Detección de personas en %s", motivo)
            detector = DetectorPose(self.ajustes.modelo or RUTA_MODELO, dispositivo, self.ajustes.imgsz)
        self.detector = detector
        self.almacen = AlmacenConfig(self.con_plataforma)
        self.calibrador = Calibrador(self.almacen)
        self.publicador = Publicador(self.con_plataforma)
        self.pantalla = Pantalla(self.ajustes.ancho_pantalla, self.ajustes.alto_pantalla)
        self.sonido = SonidoLocal()
        self.monitor: MonitorZona | None = None
        self.fuente = None
        self.cuadros = 0
        self.fps = 0.0  # fotogramas procesados por segundo (promedio reciente)
        self.ms_deteccion = 0.0  # promedio del tiempo del detector por fotograma
        self._fps_en_pantalla = 0.0  # el que muestra el panel: se renueva dos veces por segundo, no en cada cuadro
        self._t_fps_en_pantalla = float("-inf")
        self._clave_zona: str | None = None
        self._latido = None
        self._ver_mascara = False

    # ------------------------------------------------------------------ #
    def _abrir_fuente(self):
        if self.opciones.video:
            return FuenteVideo(self.opciones.video, repetir=self.opciones.repetir,
                               tiempo_real=not self.opciones.sin_ventana)
        return conectar_camara(self.ajustes.camara)

    def _nombre_fuente(self) -> str:
        if self.opciones.video:
            return "Video"
        indice = getattr(self.fuente, "indice", None)
        return f"Cámara {indice}" if indice is not None else "Cámara"

    def _informar_latido(self, conectada: bool) -> None:
        if self._latido is None:
            return
        self._latido.estado = "activo" if conectada else "error"
        self._latido.mensaje = None if conectada else MENSAJE_DESCONECTADA

    # ------------------------------------------------------------------ #
    def _actualizar_zona(self, config: Mapping[str, Any], ancho: int, alto: int, t: float) -> None:
        """Rehace la vigilancia si cambió la zona; si solo cambiaron los tiempos, los aplica en vivo."""
        clave = _clave_de_zona(config, ancho, alto)
        if clave == self._clave_zona:
            if self.monitor is not None:
                self.monitor.parametros = parametros_desde(config)
            return
        self._clave_zona = clave
        self._cerrar_monitor(t)
        try:
            zona = zona_desde_config(config, ancho, alto)
        except ValueError as error:  # una zona que en píxeles queda sin área
            log.warning("La zona de la configuración no sirve: %s", error)
            zona = None
        if zona is not None:
            self.monitor = MonitorZona(zona, parametros_desde(config))
            log.info("Zona activa: %d vértices, mide en %s%s", len(zona.poligono),
                     "metros" if zona.en_metros else "píxeles",
                     "" if zona.en_metros else f" ({zona.motivo_sin_metros})")

    def _cerrar_monitor(self, t: float) -> None:
        """Cierra la vigilancia vigente: sus eventos pendientes salen y la zona queda en libre."""
        if self.monitor is not None:
            self.publicador.publicar(self.monitor.cerrar(t), self.monitor.zona)
            self.monitor = None

    def procesar(self, frame: np.ndarray, t: float, config: Mapping[str, Any]) -> tuple[Resultado | None, list[Persona]]:
        """Un fotograma: detecta a las personas, las mide contra la zona y publica lo que resulte."""
        alto, ancho = frame.shape[:2]
        self._actualizar_zona(config, ancho, alto, t)
        inicio = time.perf_counter()
        deteccion = config["deteccion"]
        personas = self.detector.detectar(frame, deteccion["confianza_persona"])
        self.ms_deteccion += ((time.perf_counter() - inicio) * 1000.0 - self.ms_deteccion) * (
            1.0 if self.cuadros == 0 else SUAVIZADO_FPS)
        if self.monitor is None:
            self.sonido.actualizar("libre", False)
            return None, personas
        observaciones = {persona.persona_id: puntos_de_apoyo(persona, deteccion["confianza_punto"])
                         for persona in personas if persona.persona_id is not None}
        # La alarma "está activa" si la plataforma está recibiendo los eventos o si la estación pita
        alarma_activa = self.publicador.plataforma_recibe or self.sonido.sonando
        resultado = self.monitor.actualizar(t, observaciones, alarma_activa)
        cajas = {persona.persona_id: persona.caja for persona in personas if persona.persona_id is not None}
        self.publicador.procesar(resultado, frame, self.monitor.zona, cajas)
        self.sonido.actualizar(resultado.estado.estado, bool(config["sonido_local"]))
        return resultado, personas

    def _dibujar(self, vista: np.ndarray, resultado: Resultado | None, personas: list[Persona],
                 config: Mapping[str, Any]) -> None:
        """Dibuja sobre la vista en vivo la zona, las personas y, si se está calibrando, el editor."""
        if self._ver_mascara:
            resaltar_amarillo(vista, RangoHSV.desde_config(config.get("cinta_hsv")))
        if self.monitor is not None and resultado is not None and not self.calibrador.editando:
            dibujar_zona(vista, self.monitor.zona, resultado.estado.estado)
            cajas = {persona.persona_id: persona.caja for persona in personas if persona.persona_id is not None}
            dibujar_personas(vista, resultado.personas, cajas)
        else:  # sin zona o editándola: se muestra a quién ve el detector, sin estado
            dibujar_detecciones(vista, personas, config["deteccion"]["confianza_punto"])
        if self.calibrador.editando or self.monitor is None:
            self.calibrador.dibujar(vista, config)
        elif (config.get("zona_propuesta") or {}).get("poligono"):
            self.calibrador.dibujar(vista, {**config, "zona_peligro": None})  # solo la propuesta pendiente

    def _estado_de_pantalla(self, resultado: Resultado | None, config: Mapping[str, Any], tamano: tuple[int, int],
                            aviso: str | None = None) -> EstadoPantalla:
        if not self.con_plataforma:
            plataforma = "sin plataforma"
        elif self.publicador.en_cola:
            plataforma = f"sin conexión ({self.publicador.en_cola} en cola)"
        else:
            plataforma = "en línea" if self.almacen.fuente in ("plataforma", "local") else "sin respuesta"
        estado = resultado.estado if resultado is not None else (EstadoZona() if self.monitor is not None else None)
        return EstadoPantalla(
            estado=estado,
            zona=self.calibrador.estado(config, *tamano),
            mensaje=aviso or self.calibrador.mensaje,
            ayuda=self.calibrador.ayuda() + ("" if self.calibrador.medidas_en_curso is not None else AYUDA_GENERAL),
            fuente=self._nombre_fuente(),
            fps=self._fps_en_pantalla,
            dispositivo=self.detector.descripcion,
            plataforma=plataforma,
            ingresos=self.publicador.ingresos,
            casi_accidentes=self.publicador.casi_accidentes,
            sonido_local=bool(config["sonido_local"]),
            ocultas=sum(1 for persona in resultado.personas if not persona.presente and persona.estado == "peligro")
            if resultado is not None else 0,
        )

    # ------------------------------------------------------------------ #
    def ejecutar(self) -> int:
        if self.con_plataforma:
            self._latido = iniciar_latido(ESTACION, MODULO)
        else:
            log.info("Sin plataforma: la zona se guarda en este equipo y no se publican eventos")
        self.fuente = self._abrir_fuente()
        con_ventana = not self.opciones.sin_ventana
        if con_ventana:
            cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
            self._pantalla_completa(self.ajustes.pantalla_completa and not self.opciones.ventana)
            cv2.setMouseCallback(VENTANA, lambda evento, x, y, *_: self.calibrador.mouse(
                evento, *self.pantalla.a_imagen(x, y)))
        inicio = time.monotonic()
        anterior = inicio
        t = 0.0
        tamano = (1280, 720)
        ultimo: tuple[np.ndarray, Resultado | None, list[Persona]] | None = None
        config = self.almacen.valor
        try:
            while True:
                config = self.almacen.valor  # se relee en cada fotograma: un cambio remoto se aplica en vivo
                frame = self.fuente.leer()
                vista, aviso, resultado = None, None, None
                if frame is None:
                    if getattr(self.fuente, "terminada", False):
                        break
                    aviso = MENSAJE_DESCONECTADA if not self.fuente.conectada else None
                    self._informar_latido(self.fuente.conectada)
                else:
                    self._informar_latido(True)
                    t = self.fuente.marca_s if self.opciones.video else time.monotonic() - inicio
                    tamano = (frame.shape[1], frame.shape[0])
                    if self.cuadros == (0 if self.opciones.video else CUADROS_ANTES_DE_LA_REFERENCIA):
                        self.calibrador.tomar_referencia(frame)
                    self.calibrador.atender(frame, config)
                    resultado, personas = self.procesar(frame, t, config)
                    ultimo = (frame, resultado, personas)
                    self.cuadros += 1
                    vista = frame.copy()  # espejo en vivo: no se difumina porque no se guarda ni se envía
                    self._dibujar(vista, resultado, personas, config)
                pantalla = self.pantalla.componer(vista, self._estado_de_pantalla(resultado, config, tamano, aviso))
                if con_ventana:
                    cv2.imshow(VENTANA, pantalla)
                    tecla = cv2.waitKey(1 if frame is not None else 50) & 0xFF
                    if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                        break
                    if tecla != 0xFF and not self.calibrador.tecla(tecla, frame, config) and self._tecla(tecla, config):
                        break
                elif frame is None:
                    time.sleep(0.05)
                ahora = time.monotonic()
                if frame is not None and ahora > anterior:
                    self.fps += (1.0 / (ahora - anterior) - self.fps) * (1.0 if self.cuadros == 1 else SUAVIZADO_FPS)
                if ahora - self._t_fps_en_pantalla >= 0.5:
                    self._fps_en_pantalla, self._t_fps_en_pantalla = self.fps, ahora
                anterior = ahora
                if self.opciones.max_cuadros and self.cuadros >= self.opciones.max_cuadros:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self._cerrar(t, con_ventana)
        duracion = time.monotonic() - inicio
        log.info("Procesados %d cuadros en %.1f s (%.1f por segundo; detección %.0f ms por cuadro, %s). "
                 "%d ingresos y %d casi-accidentes", self.cuadros, duracion, self.cuadros / duracion if duracion else 0,
                 self.ms_deteccion, self.detector.descripcion, self.publicador.ingresos, self.publicador.casi_accidentes)
        if self.opciones.captura and ultimo is not None:
            self._guardar_captura(self.opciones.captura, *ultimo, config)
        return 0

    def _tecla(self, tecla: int, config: Mapping[str, Any]) -> bool:
        """Teclas de la estación (las de calibración ya pasaron). Devuelve True si hay que salir."""
        if tecla in (ord("q"), ord("Q"), TECLA_ESC):
            return True
        if tecla in (ord("v"), ord("V")):
            self._ver_mascara = not self._ver_mascara
        elif tecla in (ord("f"), ord("F")):
            completa = cv2.getWindowProperty(VENTANA, cv2.WND_PROP_FULLSCREEN) == cv2.WINDOW_FULLSCREEN
            self._pantalla_completa(not completa)
        elif tecla in (ord("s"), ord("S")):
            try:
                self.almacen.actualizar({**config, "sonido_local": not config["sonido_local"]})
            except ValueError as error:
                log.warning("No se pudo cambiar el sonido local: %s", error)
        return False

    def _cerrar(self, t: float, con_ventana: bool) -> None:
        self._cerrar_monitor(t)  # deja la zona en libre: ninguna alarma se queda encendida
        self.sonido.cerrar()
        if self.fuente is not None:
            self.fuente.cerrar()
        self.detector.cerrar()
        self.publicador.cerrar()  # termina de publicar lo pendiente
        if self.con_plataforma and not esperar_envios(5.0):
            log.warning("Quedaron eventos en la cola local; se enviarán al volver la plataforma")
        if self._latido is not None:
            self._latido.detener()
        self.almacen.detener()
        if con_ventana:
            cv2.destroyAllWindows()

    def _pantalla_completa(self, activar: bool) -> None:
        cv2.setWindowProperty(VENTANA, cv2.WND_PROP_FULLSCREEN,
                              cv2.WINDOW_FULLSCREEN if activar else cv2.WINDOW_NORMAL)

    def _guardar_captura(self, ruta: Path, frame: np.ndarray, resultado: Resultado | None, personas: list[Persona],
                         config: Mapping[str, Any]) -> None:
        """Guarda la pantalla del último fotograma. Sale del espejo, así que va con rostros difuminados."""
        zona = zona_desde_config(config, frame.shape[1], frame.shape[0])
        cajas = {persona.persona_id: persona.caja for persona in personas if persona.persona_id is not None}
        imagen = imagen_para_guardar(frame, zona, resultado.personas if resultado else (), cajas,
                                     resultado.estado.estado if resultado else "libre")
        estado = self._estado_de_pantalla(resultado, config, (frame.shape[1], frame.shape[0]))
        ruta.parent.mkdir(parents=True, exist_ok=True)
        correcto, datos = cv2.imencode(ruta.suffix or ".png", self.pantalla.componer(imagen, estado))
        if not correcto:
            raise OSError(f"No se pudo codificar la captura {ruta}")
        datos.tofile(str(ruta))  # así también funcionan las rutas con tildes en Windows
        log.info("Captura guardada (rostros difuminados): %s", ruta.as_posix())


def analizar_argumentos(argumentos: list[str] | None = None) -> argparse.Namespace:
    analizador = argparse.ArgumentParser(
        prog="python -m modulos.zona",
        description=("Zona de peligro en vivo. Teclas: D detecta la cinta; E edita la zona con el mouse; G guarda; "
                     "M medidas reales; R nueva imagen de referencia; V ver la máscara de amarillo; S sonido local; "
                     "F pantalla completa; Q o Esc salir."),
    )
    analizador.add_argument("--video", type=Path, help="procesa un archivo de video en lugar de la cámara")
    analizador.add_argument("--repetir", action="store_true", help="con --video, vuelve a empezar al terminar")
    analizador.add_argument("--ventana", action="store_true", help="abre en ventana, no a pantalla completa")
    analizador.add_argument("--sin-plataforma", action="store_true",
                            help="no consulta la plataforma ni publica eventos: la zona se guarda en este equipo")
    analizador.add_argument("--dispositivo",
                            help="cpu, auto (GPU si está libre) o gpu; por defecto, ZONA_DISPOSITIVO del .env")
    analizador.add_argument("--sin-ventana", action="store_true", help="procesa sin mostrar nada (para pruebas)")
    analizador.add_argument("--max-cuadros", type=int, default=0, help="termina después de N fotogramas")
    analizador.add_argument("--captura", type=Path,
                            help="al terminar, guarda la pantalla del último fotograma (rostros difuminados)")
    return analizador.parse_args(argumentos)


def main(argumentos: list[str] | None = None) -> int:
    opciones = analizar_argumentos(argumentos)
    try:
        estacion = Estacion(opciones)
    except ModeloNoDisponible as error:
        log.error("No se puede arrancar la estación de zona: %s", error)
        return 1
    return estacion.ejecutar()
