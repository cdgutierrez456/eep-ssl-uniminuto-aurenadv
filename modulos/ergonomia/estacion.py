"""Bucle principal de la estación de ergonomía: cámara → pose → ángulos → REBA → pantalla.

Privacidad: lo que se muestra en la ventana es un espejo en vivo y no se difumina. Lo que
sale de ahí (el fotograma crítico de cada levantamiento, las capturas) pasa por
``imagen_para_guardar``, que difumina los rostros antes de dibujar encima.
"""

from __future__ import annotations

import argparse
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from modulos.comun import esperar_envios, iniciar_latido, obtener_config, registrar_capacidades
from modulos.comun.camara_stand import MENSAJE_DESCONECTADA, conectar_camara

from .config import CAPACIDADES, RUTA_POR_DEFECTO, AjustesLocales, condiciones_desde, validar_config
from .flujo import TECLA_ESC, Flujo
from .fuentes import FuenteVideo
from .interfaz.dibujo import dibujar_esqueleto, imagen_para_guardar
from .interfaz.panel import EstadoPanel, Pantalla
from .nucleo.angulos import AngulosCuerpo, Punto, calcular_angulos, direccion_frente, elegir_lado
from .nucleo.neutra import PosturaNeutra
from .nucleo.reba import ResultadoReba, calcular_reba
from .nucleo.suavizado import SuavizadorPuntos
from .pose.estimador import EstimadorPose
from .publicacion import Publicador

log = logging.getLogger(__name__)

MODULO = "ergonomia"
ESTACION = "ergonomia"
VENTANA = "Auren SST - Ergonomia REBA"
MARGEN_CAMBIO_DE_LADO = 0.15  # cuánto más visible debe ser el otro lado para cambiar
VOTOS_DE_FRENTE = 15  # fotogramas recientes que deciden, por mayoría, hacia dónde mira la persona
MS_PARA_OLVIDAR_A_LA_PERSONA = 2000  # sin verla este tiempo, la siguiente persona se calibra de nuevo


class Analisis:
    """Resultado de analizar un fotograma."""

    def __init__(self, puntos: dict[str, Punto] | None, angulos: AngulosCuerpo | None,
                 resultado: ResultadoReba | None, neutra: tuple[float, float] | None = None) -> None:
        self.puntos, self.angulos, self.resultado = puntos, angulos, resultado
        # (tronco, cuello) neutros con que se corrigieron los ángulos; None si aún no hay calibración
        self.neutra = neutra

    @property
    def hay_persona(self) -> bool:
        return self.puntos is not None


class Analizador:
    """Pose → puntos suavizados → ángulos → REBA. Sin pantalla ni cámara: se puede probar solo."""

    def __init__(self, estimador: EstimadorPose, umbral_visibilidad: float = 0.5) -> None:
        self.estimador = estimador
        self.umbral_visibilidad = umbral_visibilidad
        self._suavizador = SuavizadorPuntos()
        self._lado: str | None = None
        self._frentes: deque[int] = deque(maxlen=VOTOS_DE_FRENTE)
        self.neutra = PosturaNeutra()
        self._ausente_desde_ms: int | None = None

    def analizar(self, frame: np.ndarray, marca_ms: int, config: dict[str, Any]) -> Analisis:
        puntos = self.estimador.estimar(frame, marca_ms)
        if puntos is None:
            self._suavizador.reiniciar()
            self._lado = None
            self._frentes.clear()
            if self._ausente_desde_ms is None:
                self._ausente_desde_ms = marca_ms
            elif marca_ms - self._ausente_desde_ms >= MS_PARA_OLVIDAR_A_LA_PERSONA:
                self.neutra.reiniciar()  # quien llegue después es otra persona
            return Analisis(None, None, None)
        self._ausente_desde_ms = None
        puntos = self._suavizador.filtrar(puntos, marca_ms / 1000.0)
        if config["lado"] == "auto":
            self._lado = elegir_lado(puntos, self._lado, MARGEN_CAMBIO_DE_LADO)
        else:
            self._lado = config["lado"]
        # El frente se decide por mayoría de los últimos fotogramas: un fotograma dudoso no
        # puede convertir una flexión en extensión
        voto = direccion_frente(puntos, self._lado, self.umbral_visibilidad)
        if voto is not None:
            self._frentes.append(voto)
        frente = (1 if sum(self._frentes) >= 0 else -1) if self._frentes else None
        angulos = calcular_angulos(puntos, lado=self._lado, frente=frente,
                                   umbral_visibilidad=self.umbral_visibilidad)
        # Postura neutra: tronco y cuello se miden desde la postura de pie de esta persona
        neutra = None
        if config.get("postura_neutra", True):
            if angulos.frente is not None:
                self.neutra.actualizar(marca_ms / 1000.0, angulos.tronco, angulos.cuello, angulos.piernas)
            if self.neutra.calibrada:
                neutra = (self.neutra.tronco, self.neutra.cuello)
                angulos = angulos.con_neutro(*neutra)
        resultado = calcular_reba(angulos.para_reba(), condiciones_desde(config))
        return Analisis(puntos, angulos, resultado, neutra)


class Estacion:
    """Une la fuente de video, el analizador, el flujo de la demo y la pantalla."""

    def __init__(self, opciones: argparse.Namespace, ajustes: AjustesLocales | None = None,
                 estimador: EstimadorPose | None = None) -> None:
        self.opciones = opciones
        self.ajustes = ajustes or AjustesLocales.desde_entorno()
        if estimador is None:
            from .pose.mediapipe_pose import EstimadorMediaPipe  # MediaPipe solo se carga si hace falta
            estimador = EstimadorMediaPipe(dispositivo=self.ajustes.dispositivo)
        self.analizador = Analizador(estimador, self.ajustes.umbral_visibilidad)
        self.pantalla = Pantalla(self.ajustes.ancho_pantalla, self.ajustes.alto_pantalla)
        self.con_plataforma = not opciones.sin_plataforma
        self.flujo = Flujo(Publicador() if self.con_plataforma else None,
                           self.ajustes.segundos_resultado, self.ajustes.segundos_nueva_visita)
        self._config_remota = None
        self._config = validar_config({})
        self._camara_vigente: Any = None
        self._latido = None
        self.fuente = None

    # ------------------------------------------------------------------ #
    def _iniciar_plataforma(self) -> None:
        if not self.con_plataforma:
            log.info("Sin plataforma: configuración local por defecto y sin publicar eventos")
            return
        registrar_capacidades(MODULO, CAPACIDADES)
        self._config_remota = obtener_config(MODULO, RUTA_POR_DEFECTO, validar=validar_config)
        self._latido = iniciar_latido(ESTACION, MODULO)

    def _config_vigente(self) -> dict[str, Any]:
        """La configuración se relee en cada fotograma: un cambio remoto se aplica en vivo."""
        if self._config_remota is not None:
            self._config = self._config_remota.valor
        return self._config

    def _abrir_fuente(self, config: dict[str, Any]):
        if self.opciones.video:
            return FuenteVideo(self.opciones.video, repetir=self.opciones.repetir,
                               tiempo_real=not self.opciones.sin_ventana)
        self._camara_vigente = config["camara"]
        return conectar_camara(self.ajustes.camara.con_camara(config["camara"]))

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
    def ejecutar(self) -> int:
        self._iniciar_plataforma()
        config = self._config_vigente()
        self.fuente = self._abrir_fuente(config)
        con_ventana = not self.opciones.sin_ventana
        if con_ventana:
            cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
            self._pantalla_completa(self.ajustes.pantalla_completa and not self.opciones.ventana)
        inicio = time.monotonic()
        cuadros = 0
        t = 0.0
        ultimo: tuple[np.ndarray, Analisis] | None = None
        try:
            while True:
                config = self._config_vigente()
                if not self.opciones.video and config["camara"] != self._camara_vigente:
                    log.info("Cambio de cámara por configuración: %s", config["camara"])
                    self.fuente.cerrar()
                    self.fuente = self._abrir_fuente(config)
                frame = self.fuente.leer()
                estado = EstadoPanel(config=config, fuente=self._nombre_fuente(), fps=self.fuente.fps_reales)
                vista = None
                if frame is None:
                    if getattr(self.fuente, "terminada", False):
                        break
                    if not self.fuente.conectada:
                        estado.aviso = MENSAJE_DESCONECTADA
                    self._informar_latido(self.fuente.conectada)
                else:
                    self._informar_latido(True)
                    marca_ms = (self.fuente.marca_ms if self.opciones.video
                                else round((time.monotonic() - inicio) * 1000))
                    t = marca_ms / 1000.0
                    analisis = self.analizador.analizar(frame, marca_ms, config)
                    self.flujo.procesar(t, frame, analisis, config)
                    ultimo = (frame, analisis)
                    cuadros += 1
                    estado.hay_persona = analisis.hay_persona
                    estado.angulos, estado.resultado = analisis.angulos, analisis.resultado
                    estado.neutra = analisis.neutra
                    # Vista en vivo: espejo en pantalla, sin difuminar; no se guarda ni se envía
                    vista = frame.copy()
                    if analisis.hay_persona:
                        dibujar_esqueleto(vista, analisis.puntos, analisis.angulos.lado,
                                          analisis.resultado.segmentos, analisis.angulos.como_dict())
                self._textos(estado, t, config)
                if con_ventana:
                    cv2.imshow(VENTANA, self.pantalla.componer(vista, estado))
                    tecla = cv2.waitKey(1 if frame is not None else 50) & 0xFF
                    if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                        break
                    if tecla != 0xFF and not self.flujo.tecla(tecla):
                        if tecla in (ord("q"), ord("Q"), TECLA_ESC):
                            break
                        if tecla in (ord("f"), ord("F")):
                            completa = (cv2.getWindowProperty(VENTANA, cv2.WND_PROP_FULLSCREEN)
                                        == cv2.WINDOW_FULLSCREEN)
                            self._pantalla_completa(not completa)
                elif frame is None:
                    time.sleep(0.05)
                if self.opciones.max_cuadros and cuadros >= self.opciones.max_cuadros:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self._cerrar(con_ventana)
        duracion = time.monotonic() - inicio
        log.info("Procesados %d cuadros en %.1f s (%.1f por segundo); %d intentos en la última visita",
                 cuadros, duracion, cuadros / duracion if duracion else 0, len(self.flujo.visita.intentos))
        if self.opciones.captura and ultimo is not None:
            self._guardar_captura(self.opciones.captura, *ultimo, t, config)
        return 0

    def _textos(self, estado: EstadoPanel, t: float, config: dict[str, Any]) -> None:
        estado.instruccion = self.flujo.instruccion(t, config)
        estado.pista = self.flujo.pista(t)
        # Al terminar un intento, el panel muestra su resultado (no la postura de pie en vivo)
        reciente = self.flujo.resultado_reciente(t)
        if reciente is not None:
            intento, angulos, neutra = reciente
            estado.resultado, estado.angulos, estado.neutra = intento.resultado, angulos, neutra
            estado.tecnica = intento.tecnica
            estado.titulo_reba = f"Resultado del intento {intento.numero}"
            estado.hay_persona = True
        estado.superior = self.flujo.superior(config)
        estado.inferior, estado.color_inferior = self.flujo.inferior()

    def _cerrar(self, con_ventana: bool) -> None:
        self.fuente.cerrar()
        self.analizador.estimador.cerrar()
        if self.flujo.publicador is not None:
            self.flujo.publicador.cerrar()  # termina de publicar lo pendiente
            if not esperar_envios(5.0):
                log.warning("Quedaron eventos en la cola local; se enviarán al volver la plataforma")
        if self._latido is not None:
            self._latido.detener()
        if self._config_remota is not None:
            self._config_remota.detener()
        if con_ventana:
            cv2.destroyAllWindows()

    def _pantalla_completa(self, activar: bool) -> None:
        cv2.setWindowProperty(VENTANA, cv2.WND_PROP_FULLSCREEN,
                              cv2.WINDOW_FULLSCREEN if activar else cv2.WINDOW_NORMAL)

    def _guardar_captura(self, ruta: Path, frame: np.ndarray, analisis: Analisis, t: float,
                         config: dict[str, Any]) -> None:
        """Guarda la pantalla del último fotograma. Sale del espejo, así que va con rostros difuminados."""
        segmentos = analisis.resultado.segmentos if analisis.resultado else {}
        lado = analisis.angulos.lado if analisis.angulos else "derecho"
        angulos = analisis.angulos.como_dict() if analisis.angulos else None
        imagen = imagen_para_guardar(frame, analisis.puntos, lado, segmentos, angulos)
        estado = EstadoPanel(resultado=analisis.resultado, angulos=analisis.angulos,
                             hay_persona=analisis.hay_persona, config=config, fuente=self._nombre_fuente(),
                             neutra=analisis.neutra)
        self._textos(estado, t, config)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        correcto, datos = cv2.imencode(ruta.suffix or ".png", self.pantalla.componer(imagen, estado))
        if not correcto:
            raise OSError(f"No se pudo codificar la captura {ruta}")
        datos.tofile(str(ruta))  # así también funcionan las rutas con tildes en Windows
        log.info("Captura guardada (rostros difuminados): %s", ruta.as_posix())


def analizar_argumentos(argumentos: list[str] | None = None) -> argparse.Namespace:
    analizador = argparse.ArgumentParser(
        prog="python -m modulos.ergonomia",
        description=("Evaluación ergonómica REBA en vivo. Teclas: barra espaciadora inicia o termina el "
                     "levantamiento; dígitos y Enter, número de visitante; N nueva visita; F pantalla "
                     "completa; Q o Esc salir."),
    )
    analizador.add_argument("--video", type=Path, help="procesa un archivo de video en lugar de la cámara")
    analizador.add_argument("--repetir", action="store_true", help="con --video, vuelve a empezar al terminar")
    analizador.add_argument("--ventana", action="store_true", help="abre en ventana, no a pantalla completa")
    analizador.add_argument("--sin-plataforma", action="store_true",
                            help="no consulta la configuración remota ni publica eventos")
    analizador.add_argument("--sin-ventana", action="store_true", help="procesa sin mostrar nada (para pruebas)")
    analizador.add_argument("--max-cuadros", type=int, default=0, help="termina después de N fotogramas")
    analizador.add_argument("--captura", type=Path,
                            help="al terminar, guarda la pantalla del último fotograma (rostros difuminados)")
    return analizador.parse_args(argumentos)


def main(argumentos: list[str] | None = None) -> int:
    return Estacion(analizar_argumentos(argumentos)).ejecutar()
