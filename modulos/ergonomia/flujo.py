"""Flujo de la demo: levantamientos, intentos de la visita, teclas y textos de la pantalla.

Une la máquina de estados, la visita y la publicación, sin cámara ni ventana: recibe el
análisis de cada fotograma y las teclas, y dice qué mostrar. Así se prueba con secuencias
simuladas.

Teclas:

- **Barra espaciadora**: inicia o termina el levantamiento (modo manual, o para forzarlo en auto).
- **Dígitos y Enter**: número de visitante (``sesion_id``). Retroceso corrige y Esc cancela.
- **N**: nueva visita sin número (reinicia los intentos).
"""

from __future__ import annotations

import logging
from concurrent.futures import Future
from typing import Any, Mapping

import numpy as np

from .config import umbrales_desde
from .interfaz import marca
from .nucleo.angulos import AngulosCuerpo
from .nucleo.intentos import Intento, Visita, normalizar_sesion, sugerir_correcciones
from .nucleo.levantamiento import Estado, MaquinaLevantamiento, Muestra
from .nucleo.mensajes import pista_contextual
from .publicacion import Critico, Publicador

log = logging.getLogger(__name__)

TECLA_ENTER, TECLA_RETROCESO, TECLA_ESC, TECLA_ESPACIO = 13, 8, 27, 32
MAXIMO_DE_DIGITOS = 6


class Flujo:
    """Estado de la demo entre fotogramas."""

    def __init__(self, publicador: Publicador | None = None, segundos_resultado: float = 8.0,
                 segundos_nueva_visita: float = 20.0) -> None:
        self.publicador = publicador  # None = no se publica (modo sin plataforma)
        self.segundos_resultado = segundos_resultado
        self.segundos_nueva_visita = segundos_nueva_visita
        self.maquina = MaquinaLevantamiento()
        self.visita = Visita()
        self.entrada: str | None = None  # dígitos del número de visitante mientras se teclea
        self.publicaciones: list[Future] = []
        self._pulsacion = False
        self._hay_persona = False
        self._falta_calibrar = False
        self._ultimo_critico: Critico | None = None  # fotograma crítico del último intento
        self._sin_persona_desde: float | None = None
        self._resultado_en: float | None = None  # cuándo terminó el último intento
        self._descartado_en: float | None = None  # cuándo se descartó un levantamiento sin evaluar

    # ------------------------------------------------------------------ #
    # Teclas
    # ------------------------------------------------------------------ #
    def tecla(self, codigo: int) -> bool:
        """Procesa una tecla. Devuelve True si la usó (y entonces no debe cerrar el programa)."""
        if ord("0") <= codigo <= ord("9"):
            self.entrada = ((self.entrada or "") + chr(codigo))[:MAXIMO_DE_DIGITOS]
            return True
        if self.entrada is not None:
            if codigo == TECLA_ENTER:
                self._fijar_visitante(normalizar_sesion(self.entrada))
                self.entrada = None
                return True
            if codigo == TECLA_RETROCESO:
                self.entrada = self.entrada[:-1]
                return True
            if codigo == TECLA_ESC:
                self.entrada = None
                return True
        if codigo == TECLA_ESPACIO:
            self._pulsacion = True
            return True
        if codigo in (ord("n"), ord("N")):
            self.visita = Visita()
            self._resultado_en = None
            log.info("Nueva visita sin número")
            return True
        return False

    def _fijar_visitante(self, sesion_id: str | None) -> None:
        if sesion_id is None:
            return
        if self.visita.sesion_id is None and self.visita.intentos:
            # Hizo intentos antes de dar su número: se le asigna a la visita en curso
            self.visita.sesion_id = sesion_id
        elif self.visita.sesion_id != sesion_id:
            self.visita = Visita(sesion_id)
            self._resultado_en = None
        log.info("Visitante %s", sesion_id)

    # ------------------------------------------------------------------ #
    # Fotogramas
    # ------------------------------------------------------------------ #
    def procesar(self, t: float, frame: np.ndarray, analisis, config: Mapping[str, Any]) -> Intento | None:
        """Avanza con el análisis de un fotograma. Devuelve el intento si acaba de terminar uno."""
        self.maquina.umbrales = umbrales_desde(config)  # los umbrales remotos se aplican en vivo
        self._hay_persona = analisis.hay_persona
        self._falta_calibrar = (analisis.hay_persona and analisis.neutra is None
                                and config.get("postura_neutra", True))
        muestra = Muestra(t=t, hay_persona=analisis.hay_persona)
        if analisis.hay_persona:
            angulos, resultado, lado = analisis.angulos, analisis.resultado, analisis.angulos.lado
            muestra.tronco, muestra.rodilla = angulos.tronco, angulos.piernas
            muestra.muneca_y = analisis.puntos[f"muneca_{lado}"].y
            muestra.rodilla_y = analisis.puntos[f"rodilla_{lado}"].y
            muestra.cadera_y = analisis.puntos[f"cadera_{lado}"].y
            if resultado.completo:
                muestra.puntaje = resultado.puntaje
                muestra.carga = (Critico(frame, analisis.puntos, angulos, analisis.neutra), resultado)
            self._sin_persona_desde = None
        elif self._sin_persona_desde is None:
            self._sin_persona_desde = t

        pulsacion, self._pulsacion = self._pulsacion, False
        levantamiento = self.maquina.actualizar(muestra, pulsacion, config["modo_deteccion"])

        if (self._sin_persona_desde is not None and not self.visita.vacia
                and self.maquina.estado is not Estado.LEVANTANDO
                and t - self._sin_persona_desde >= self.segundos_nueva_visita):
            log.info("Sin nadie en cuadro: termina la visita %s", self.visita.sesion_id or "sin número")
            self.visita = Visita()
            self._resultado_en = None

        if levantamiento is None:
            return None
        if levantamiento.puntaje is None:
            log.warning("Levantamiento de %.1f s sin evaluar: no se vio el cuerpo completo",
                        levantamiento.duracion_s)
            self._descartado_en = t
            return None
        critico, resultado = levantamiento.critico
        intento = self.visita.registrar(resultado, levantamiento.duracion_s, levantamiento.tronco_maximo,
                                        levantamiento.rodilla_maxima, levantamiento.desde_piso)
        self._ultimo_critico = critico
        self._resultado_en, self._descartado_en = t, None
        segmentos = " ".join(f"{nombre[:3]}={puntaje}" for nombre, puntaje in resultado.segmentos.items())
        log.info("%s · espalda %d° (%s) · rodillas %s° · %s · %s · neutra %s (%.1f s, fin %s)%s", intento.resumen(),
                 intento.espalda, intento.tecnica.nivel, intento.rodillas,
                 {True: "desde el piso", False: "carga elevada", None: "altura sin determinar"}[intento.desde_piso],
                 segmentos, "sin calibrar" if critico.neutra is None else "%.0f°/%.0f°" % critico.neutra,
                 intento.duracion_s, levantamiento.motivo_fin,
                 "" if levantamiento.sostenido else " [máximo de un solo fotograma: el puntaje no se sostuvo]")
        if self.publicador is not None:
            self.publicaciones.append(
                self.publicador.publicar_levantamiento(critico, intento, self.visita.sesion_id, config))
        return intento

    # ------------------------------------------------------------------ #
    # Textos de la pantalla
    # ------------------------------------------------------------------ #
    def superior(self, config: Mapping[str, Any]) -> tuple[str, str]:
        """Franja sobre el video: visitante e intento a la izquierda, estado a la derecha."""
        siguiente = len(self.visita.intentos) + 1
        if self.entrada is not None:
            izquierda = f"Número de visitante: {self.entrada}_   (Enter confirma, Esc cancela)"
        elif self.visita.sesion_id:
            izquierda = f"Visitante {self.visita.sesion_id} · Intento {siguiente}"
        else:
            izquierda = f"Sin número de visitante · Intento {siguiente}"
        estado = self.maquina.estado
        if estado is Estado.LEVANTANDO:
            derecha = f"Levantando · {self.maquina.segundos_levantando:.1f} s"
        elif self._hay_persona:
            derecha = "Listo" + (" · modo manual" if config["modo_deteccion"] == "manual" else "")
        else:
            derecha = "Sin persona"
        return izquierda, derecha

    def inferior(self) -> tuple[tuple[str, str, str], marca.Color | None]:
        """Franja bajo el video: (espalda, rodillas, REBA) del último intento o de la comparación,
        y el color del acento, que es el de la flexión de espalda del intento actual.

        Lo primero es la técnica (espalda y rodillas), que es lo que el visitante puede
        cambiar. El REBA va debajo, completo y sin maquillar: una sentadilla profunda
        descarga la espalda pero suma puntos en piernas.
        """
        comparacion = self.visita.comparacion()
        if comparacion is not None:
            reba = "REBA · " + comparacion.texto()
            cambios = comparacion.texto_cambios()
            if cambios:
                reba += " · " + cambios
            return ((comparacion.texto_espalda(), comparacion.texto_rodillas(), reba),
                    marca.COLOR_DE_ESPALDA[comparacion.actual.tecnica.nivel])
        ultimo = self.visita.ultimo
        if ultimo is not None:
            tecnica = ultimo.tecnica
            return ((f"Flexión de espalda: {tecnica.texto_espalda()}", tecnica.texto_piernas(),
                     f"REBA · {ultimo.resumen()} · Haz un segundo intento para comparar"),
                    marca.COLOR_DE_ESPALDA[tecnica.nivel])
        return ("", "", ""), None

    def _fase(self, t: float) -> str:
        """En qué está la demo: decide qué instrucción se muestra y si hay pista."""
        if self.maquina.estado is Estado.LEVANTANDO:
            return "levantando"
        if not self._hay_persona:
            return "sin_persona"
        if self._descartado_en is not None and t - self._descartado_en < self.segundos_resultado:
            return "descartado"
        if self._mostrando_resultado(t):
            return "resultado"
        return "calibrando" if self._falta_calibrar else "listo"

    def _mostrando_resultado(self, t: float) -> bool:
        """El último intento acaba de terminar y su resultado sigue en pantalla."""
        return (self._resultado_en is not None and self.visita.ultimo is not None
                and self.maquina.estado is not Estado.LEVANTANDO
                and t - self._resultado_en < self.segundos_resultado)

    def instruccion(self, t: float, config: Mapping[str, Any]) -> str:
        """Texto del recuadro de instrucciones. Tras un intento, lo que conviene corregir."""
        manual = config["modo_deteccion"] == "manual"
        fase = self._fase(t)
        if fase == "levantando":
            return "Barra espaciadora para terminar" if manual else "Deja la caja en la mesa y ponte erguido"
        if fase == "sin_persona":
            return "Ubícate de lado, con el cuerpo completo en cuadro"
        if fase == "descartado":
            return "No se vio el cuerpo completo. Inténtalo de nuevo"
        if fase == "resultado":
            return " ".join(sugerir_correcciones(self.visita))
        if fase == "calibrando":
            return "Quédate de pie y quieto un momento"
        return "Barra espaciadora para iniciar" if manual else "Levanta la caja del piso a la mesa"

    def pista(self, t: float) -> str | None:
        """Pista contextual al terminar un levantamiento; va después de las correcciones.

        Solo mientras el resultado del intento está en pantalla. Depende de si la carga
        estaba en el piso y de si el REBA bajó respecto al intento anterior.
        """
        if self._fase(t) != "resultado":
            return None
        ultimo, comparacion = self.visita.ultimo, self.visita.comparacion()
        anterior = comparacion.anterior.puntaje if comparacion is not None else None
        return pista_contextual(ultimo.puntaje, ultimo.desde_piso, anterior)

    def resultado_reciente(self, t: float) -> tuple[Intento, AngulosCuerpo, tuple[float, float] | None] | None:
        """El intento que acaba de terminar, con los ángulos y la postura neutra de su fotograma
        crítico, mientras su resultado sigue en pantalla. El panel lo muestra en lugar de la
        postura en vivo: al terminar, la persona ya está de pie y el puntaje en vivo no dice nada."""
        if not self._mostrando_resultado(t) or self._ultimo_critico is None:
            return None
        return self.visita.ultimo, self._ultimo_critico.angulos, self._ultimo_critico.neutra
