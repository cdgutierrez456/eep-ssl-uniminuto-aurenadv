"""Máquina de estados de un levantamiento: sin persona → persona lista → levantando → terminado.

Pura: recibe una muestra por fotograma (tiempo, ángulos, alturas y puntaje) y avisa cuándo
termina un levantamiento, con su fotograma crítico. No sabe de cámara ni de eventos.

Modo auto:

- **Empieza** cuando las muñecas bajan por debajo de las rodillas, o cuando el tronco pasa
  de ``tronco_inicio`` con las manos por debajo de la cadera.
- **Termina** cuando la persona lleva ``segundos_erguido`` erguida (tronco y rodillas casi
  rectos) y con las manos arriba. "Arriba" es por encima del punto medio entre rodilla y
  cadera, no por encima de la cadera: con los brazos colgando después de dejar la caja, las
  muñecas quedan a la altura de la cadera o un poco más abajo.

Modo manual: la barra espaciadora empieza y termina. En modo auto la barra también sirve
para forzar el inicio o el fin.

Fotograma crítico: el de mayor puntaje **sostenido** durante ``ventana_sostenida_s``. Tomar
el máximo de un solo fotograma premiaría el ruido: un ángulo que tiembla en el borde de un
rango sube un punto durante un instante. Si el levantamiento es demasiado corto para tener
una ventana completa, se usa el máximo simple.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Estado(str, Enum):
    SIN_PERSONA = "sin_persona"
    PERSONA_LISTA = "persona_lista"
    LEVANTANDO = "levantando"
    TERMINADO = "terminado"


@dataclass(frozen=True)
class Umbrales:
    """Umbrales de detección. Todos configurables (clave ``deteccion`` de la configuración)."""

    tronco_inicio: float = 20.0  # grados de flexión del tronco que inician el levantamiento
    tronco_erguido: float = 20.0  # hasta cuántos grados (en valor absoluto) cuenta como erguido
    rodilla_erguida: float = 30.0  # hasta cuánta flexión de rodilla cuenta como erguido
    segundos_erguido: float = 1.0  # tiempo erguido para dar por terminado el levantamiento
    duracion_minima_s: float = 0.7  # un movimiento más corto no cuenta como levantamiento
    duracion_maxima_s: float = 20.0  # tiempo máximo por levantamiento
    ventana_sostenida_s: float = 0.3  # cuánto debe sostenerse un puntaje para ser el crítico
    segundos_sin_persona: float = 1.5  # sin ver a la persona este tiempo, se abandona el levantamiento


@dataclass
class Muestra:
    """Lo que la máquina necesita de un fotograma. Las alturas son píxeles (y crece hacia abajo)."""

    t: float  # segundos
    hay_persona: bool = False
    tronco: float | None = None
    rodilla: float | None = None  # flexión de rodilla
    muneca_y: float | None = None
    rodilla_y: float | None = None
    cadera_y: float | None = None
    puntaje: int | None = None  # REBA del fotograma; None si no se pudo calcular
    carga: Any = None  # lo que haya que conservar del fotograma crítico (imagen, ángulos…)


@dataclass(frozen=True)
class Levantamiento:
    """Un levantamiento terminado. ``puntaje`` es None si no se pudo evaluar ningún fotograma."""

    inicio: float
    fin: float
    puntaje: int | None
    critico: Any  # la ``carga`` del fotograma crítico
    motivo_fin: str  # "auto", "manual" o "tiempo_maximo"
    sostenido: bool  # True si el puntaje se sostuvo la ventana completa; False si es el máximo simple
    # Para el indicador de técnica: mayor flexión de tronco y de rodillas durante el levantamiento
    # (sostenidas la misma ventana). None si no se pudieron medir.
    tronco_maximo: float | None = None
    rodilla_maxima: float | None = None
    # True si las muñecas bajaron de la altura de las rodillas (la carga estaba en el piso);
    # None si no se pudo saber
    desde_piso: bool | None = None

    @property
    def duracion_s(self) -> float:
        return self.fin - self.inicio


class _PicoSostenido:
    """Mayor valor de una medida que se sostiene durante la ventana (el mínimo dentro de la
    ventana, maximizado en el tiempo). Si nunca hubo una ventana completa, el máximo simple."""

    def __init__(self) -> None:
        self._muestras: deque[tuple[float, float]] = deque()
        self._sostenido: float | None = None
        self._simple: float | None = None

    def agregar(self, t: float, valor: float | None, ventana: float) -> None:
        if valor is None:
            self._muestras.clear()
            return
        if self._simple is None or valor > self._simple:
            self._simple = valor
        self._muestras.append((t, valor))
        while len(self._muestras) > 1 and t - self._muestras[1][0] >= ventana:
            self._muestras.popleft()
        if t - self._muestras[0][0] >= ventana:
            minimo = min(v for _, v in self._muestras)
            if self._sostenido is None or minimo > self._sostenido:
                self._sostenido = minimo

    @property
    def valor(self) -> float | None:
        return self._sostenido if self._sostenido is not None else self._simple


class MaquinaLevantamiento:
    """Sigue el estado del visitante y devuelve cada levantamiento cuando termina."""

    def __init__(self, umbrales: Umbrales | None = None) -> None:
        self.umbrales = umbrales or Umbrales()
        self.estado = Estado.SIN_PERSONA
        self.inicio: float | None = None  # cuándo empezó el levantamiento en curso
        self._erguido_desde: float | None = None
        self._ultima_vez_visto = float("-inf")
        self._ventana: deque[tuple[float, int, Any]] = deque()
        self._mejor_sostenido: tuple[int, Any] | None = None
        self._mejor_simple: tuple[int, Any] | None = None
        self._pico_tronco = _PicoSostenido()
        self._pico_rodilla = _PicoSostenido()
        self._pico_manos = _PicoSostenido()  # cuánto bajaron las muñecas respecto a las rodillas (píxeles)

    # ------------------------------------------------------------------ #
    def actualizar(self, m: Muestra, pulsacion: bool = False, modo: str = "auto") -> Levantamiento | None:
        """Procesa un fotograma. Devuelve el levantamiento si terminó en este fotograma.

        ``pulsacion`` indica que se oprimió la barra espaciadora desde el fotograma anterior.
        Un levantamiento abandonado (la persona salió del cuadro, o fue más corto que
        ``duracion_minima_s``) no se devuelve.
        """
        u = self.umbrales
        if m.hay_persona:
            self._ultima_vez_visto = m.t

        if self.estado is not Estado.LEVANTANDO:
            self.estado = Estado.PERSONA_LISTA if m.hay_persona else Estado.SIN_PERSONA
            if m.hay_persona and (pulsacion or (modo == "auto" and self._debe_empezar(m))):
                self._empezar(m)
            return None

        # Levantando
        if m.t - self._ultima_vez_visto > u.segundos_sin_persona:
            self._reiniciar(Estado.SIN_PERSONA)
            return None
        # Los fotogramas en que ya está erguido no compiten por ser el crítico. Sin esto, un
        # levantamiento cuyos fotogramas agachados no se pudieron puntuar (cuerpo cortado por
        # el encuadre) se evaluaba con la postura de pie y salía, falsamente, como riesgo bajo.
        if modo != "auto" or not self._esta_erguido(m):
            self._acumular(m)
        if pulsacion:
            return self._terminar(m.t, "manual")
        if m.t - self.inicio >= u.duracion_maxima_s:
            return self._terminar(m.t, "tiempo_maximo")
        if modo == "auto":
            if self._esta_erguido(m):
                if self._erguido_desde is None:
                    self._erguido_desde = m.t
                elif m.t - self._erguido_desde >= u.segundos_erguido:
                    # El levantamiento terminó cuando se puso erguido, no al cumplirse la espera
                    return self._terminar(self._erguido_desde, "auto")
            elif m.hay_persona:
                self._erguido_desde = None
        return None

    @property
    def segundos_levantando(self) -> float | None:
        """Para la pantalla: None si no hay un levantamiento en curso."""
        return None if self.inicio is None else max(0.0, self._ultima_vez_visto - self.inicio)

    # ------------------------------------------------------------------ #
    def _debe_empezar(self, m: Muestra) -> bool:
        if m.muneca_y is None:
            return False
        if m.rodilla_y is not None and m.muneca_y > m.rodilla_y:
            return True  # las manos bajaron por debajo de las rodillas
        return (m.tronco is not None and m.tronco > self.umbrales.tronco_inicio
                and m.cadera_y is not None and m.muneca_y > m.cadera_y)

    def _esta_erguido(self, m: Muestra) -> bool:
        u = self.umbrales
        if None in (m.tronco, m.muneca_y, m.rodilla_y, m.cadera_y):
            return False
        manos_arriba = m.muneca_y < (m.rodilla_y + m.cadera_y) / 2.0
        # Si la rodilla no se pudo medir (tobillo tapado), bastan el tronco y las manos:
        # de otro modo el levantamiento no terminaría hasta el tiempo máximo
        rodilla_recta = m.rodilla is None or m.rodilla <= u.rodilla_erguida
        return abs(m.tronco) <= u.tronco_erguido and rodilla_recta and manos_arriba

    def _empezar(self, m: Muestra) -> None:
        self.estado = Estado.LEVANTANDO
        self.inicio = m.t
        self._erguido_desde = None
        self._ventana.clear()
        self._mejor_sostenido = self._mejor_simple = None
        self._pico_tronco, self._pico_rodilla = _PicoSostenido(), _PicoSostenido()
        self._pico_manos = _PicoSostenido()
        self._acumular(m)

    def _acumular(self, m: Muestra) -> None:
        """Lleva la cuenta del mayor puntaje sostenido y del mayor puntaje simple."""
        self._pico_tronco.agregar(m.t, m.tronco, self.umbrales.ventana_sostenida_s)
        self._pico_rodilla.agregar(m.t, m.rodilla, self.umbrales.ventana_sostenida_s)
        bajo_las_rodillas = None if None in (m.muneca_y, m.rodilla_y) else m.muneca_y - m.rodilla_y
        self._pico_manos.agregar(m.t, bajo_las_rodillas, self.umbrales.ventana_sostenida_s)
        if m.puntaje is None:
            self._ventana.clear()  # un fotograma sin puntaje corta la racha
            return
        if self._mejor_simple is None or m.puntaje > self._mejor_simple[0]:
            self._mejor_simple = (m.puntaje, m.carga)
        ventana = self.umbrales.ventana_sostenida_s
        self._ventana.append((m.t, m.puntaje, m.carga))
        while len(self._ventana) > 1 and m.t - self._ventana[1][0] >= ventana:
            self._ventana.popleft()  # se conserva justo lo necesario para cubrir la ventana
        if m.t - self._ventana[0][0] < ventana:
            return  # todavía no hay una ventana completa
        sostenido = min(puntaje for _, puntaje, _ in self._ventana)
        if self._mejor_sostenido is None or sostenido > self._mejor_sostenido[0]:
            carga = next(c for _, p, c in reversed(self._ventana) if p == sostenido)
            self._mejor_sostenido = (sostenido, carga)

    def _terminar(self, fin: float, motivo: str) -> Levantamiento | None:
        inicio, mejor = self.inicio, self._mejor_sostenido or self._mejor_simple
        sostenido = self._mejor_sostenido is not None
        tronco, rodilla = self._pico_tronco.valor, self._pico_rodilla.valor
        desde_piso = None if self._pico_manos.valor is None else self._pico_manos.valor > 0
        self._reiniciar(Estado.TERMINADO)
        if motivo != "manual" and fin - inicio < self.umbrales.duracion_minima_s:
            return None  # un gesto demasiado corto no es un levantamiento
        puntaje, critico = mejor if mejor is not None else (None, None)
        return Levantamiento(inicio, fin, puntaje, critico, motivo, sostenido, tronco, rodilla, desde_piso)

    def _reiniciar(self, estado: Estado) -> None:
        self.estado = estado
        self.inicio = None
        self._erguido_desde = None
        self._ventana.clear()
        self._mejor_sostenido = self._mejor_simple = None
