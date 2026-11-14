"""Máquina de estados de una zona: de las posiciones de cada persona a estados y eventos.

Pura y determinista: en cada fotograma recibe el tiempo y los puntos de apoyo de cada
persona (por su id del tracker) y devuelve el estado de la zona, el de cada persona y los
eventos que hay que publicar. No conoce cámaras, modelos ni la plataforma, así que se prueba
con secuencias simuladas.

Cómo decide:

- **Por persona.** En cada fotograma la persona tiene un nivel instantáneo (``clasificar``,
  con histéresis). Su estado confirmado solo cambia cuando el nivel instantáneo se sostiene
  ``antirrebote_s`` segundos: sube al nivel más alto que lleve sostenido ese tiempo y baja
  al más bajo. Así un parpadeo de la detección no dispara ni apaga la alarma.
- **Por zona.** El estado de la zona es el peor estado confirmado entre las personas.
- **Personas que se dejan de ver.** Conservan su estado ``segundos_perdida`` segundos (una
  oclusión corta no cierra nada); pasado ese tiempo se dan por retiradas y se cierra lo que
  tuvieran abierto.
- **Personas ocultas dentro de la zona.** Quien se deja de ver estando dentro puede seguir
  ahí, tapada por la máquina: conserva el peligro ``segundos_perdida_peligro`` segundos, y la
  alarma no se apaga. Si en ese lapso aparece dentro de la zona alguien con un id nuevo, se
  asume que es la misma persona y hereda su estado y su historial: un solo ingreso.
- **Cambios de id del tracker.** Un id nuevo que aparece a menos del radio de reasociación
  de donde se vio por última vez a una persona perdida (dentro de su espera) es esa persona:
  hereda su estado y su historial, así no salen dos eventos por la misma.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from .clasificacion import Nivel, clasificar
from .eventos import (
    EstadoZona,
    EventoZona,
    Textos,
    evento_casi_accidente,
    evento_estado_zona,
    evento_ingreso_zona,
)
from .geometria import Punto
from .zona import Medida, Zona

# Holgura al comparar tiempos: a 30 fps, nueve fotogramas suman 0,3 s solo "casi" exactos
HOLGURA_S = 1e-6


@dataclass(frozen=True)
class Parametros:
    """Tiempos de la máquina de estados."""

    antirrebote_s: float = 0.3  # cuánto debe sostenerse un nivel para cambiar de estado
    segundos_perdida: float = 1.0  # sin ver a una persona este tiempo, se da por retirada
    segundos_perdida_peligro: float = 4.0  # lo mismo para quien se dejó de ver dentro de la zona
    intervalo_refresco_s: float = 2.0  # cada cuánto se repite estado_zona mientras no esté libre
    # Un id nuevo que aparece a menos de este radio de una persona recién perdida es esa persona
    radio_reasociacion_m: float = 0.5  # cuando la zona mide en metros
    radio_reasociacion_px: float = 80.0  # cuando mide en píxeles


@dataclass(frozen=True)
class VistaPersona:
    """Lo que la estación necesita de una persona en un fotograma, para dibujarla y fotografiarla."""

    persona_id: int
    estado: str  # confirmado, con antirrebote: libre, advertencia o peligro
    nivel: str  # el del último fotograma en que se vio, sin antirrebote
    puntos: tuple[Punto, ...]  # sus puntos de apoyo más recientes, en píxeles
    medida: Medida | None  # su última medida contra la zona
    presente: bool  # False si en este fotograma no se vio (sigue contando mientras dure su espera)
    entro_a_peligro: bool = False  # se acaba de confirmar dentro de la zona: momento de la foto de entrada
    nuevo_minimo: bool = False  # acaba de marcar su menor distancia del acercamiento: foto del casi-accidente
    heredada_de: int | None = None  # id anterior de esta persona, si acaba de reaparecer con uno nuevo


@dataclass(frozen=True)
class Resultado:
    """Lo que deja un fotograma."""

    estado: EstadoZona
    personas: tuple[VistaPersona, ...]
    eventos: tuple[EventoZona, ...]  # primero estado_zona (urgente), después los de cada persona


class _Persona:
    """Seguimiento de una persona (un id del tracker) frente a la zona."""

    def __init__(self, persona_id: int, t: float) -> None:
        self.persona_id = persona_id
        self.estado = Nivel.LIBRE  # confirmado
        self.nivel = Nivel.LIBRE  # instantáneo, del último fotograma en que se vio
        self.visto = t
        self.puntos: tuple[Punto, ...] = ()
        self.medida: Medida | None = None
        # Desde cuándo el nivel instantáneo lleva, sin interrupción, siendo al menos (o a lo sumo) cada nivel
        self.desde_al_menos: dict[Nivel, float | None] = {Nivel.ADVERTENCIA: None, Nivel.PELIGRO: None}
        self.desde_a_lo_sumo: dict[Nivel, float | None] = {Nivel.LIBRE: None, Nivel.ADVERTENCIA: None}
        self.entrada_t = t  # cuándo entró a la zona de peligro
        self.alarma_activada = False  # la alarma estuvo activa en algún momento de su ingreso
        self.reiniciar_acercamiento()

    def reiniciar_acercamiento(self) -> None:
        """Empieza de cero el acercamiento: distancia mínima y si llegó a pisar la zona."""
        self.minimo = math.inf  # en la unidad de la zona
        self.minimo_px = math.inf
        self.minimo_m: float | None = None
        self.piso_peligro = False

    def registrar_distancia(self, medida: Medida, distancia: float) -> bool:
        """Anota la medida en el acercamiento en curso. Devuelve si marcó un nuevo mínimo."""
        self.minimo_px = min(self.minimo_px, medida.distancia_px)
        if medida.distancia_m is not None:
            self.minimo_m = medida.distancia_m if self.minimo_m is None else min(self.minimo_m, medida.distancia_m)
        if distancia < self.minimo:
            self.minimo = distancia
            return True
        return False

    def cronometrar(self, t: float) -> None:
        """Actualiza desde cuándo se sostiene cada nivel, según el nivel instantáneo."""
        for nivel in self.desde_al_menos:
            if self.nivel >= nivel:
                if self.desde_al_menos[nivel] is None:
                    self.desde_al_menos[nivel] = t
            else:
                self.desde_al_menos[nivel] = None
        for nivel in self.desde_a_lo_sumo:
            if self.nivel <= nivel:
                if self.desde_a_lo_sumo[nivel] is None:
                    self.desde_a_lo_sumo[nivel] = t
            else:
                self.desde_a_lo_sumo[nivel] = None

    @property
    def oculta_dentro(self) -> bool:
        """La última vez que se vio estaba dentro de la zona, con el peligro ya confirmado."""
        return self.estado is Nivel.PELIGRO and self.nivel is Nivel.PELIGRO

    def vista(self, presente: bool, entro_a_peligro: bool = False, nuevo_minimo: bool = False,
              heredada_de: int | None = None) -> VistaPersona:
        return VistaPersona(self.persona_id, self.estado.nombre, self.nivel.nombre, self.puntos, self.medida,
                            presente, entro_a_peligro, nuevo_minimo, heredada_de)


def _separacion(unos: Sequence[Punto], otros: Sequence[Punto]) -> float:
    """Distancia entre los dos puntos más cercanos de dos grupos de puntos de apoyo."""
    return min((math.dist(a, b) for a in unos for b in otros), default=math.inf)


class MonitorZona:
    """Vigila una zona: llámese ``actualizar`` una vez por fotograma.

    ``textos`` cambia las palabras con que se describe un casi-accidente, si la zona lo necesita.
    """

    def __init__(self, zona: Zona, parametros: Parametros | None = None, textos: Textos | None = None) -> None:
        self.zona = zona
        self.parametros = parametros or Parametros()
        self.textos = textos or Textos()
        self._personas: dict[int, _Persona] = {}
        self._emitido: EstadoZona | None = None  # el último estado_zona que se mandó
        self._t_emitido = -math.inf

    @property
    def estado(self) -> EstadoZona:
        """Estado vigente de la zona: el peor estado confirmado entre las personas."""
        en_peligro = sum(1 for persona in self._personas.values() if persona.estado is Nivel.PELIGRO)
        en_advertencia = sum(1 for persona in self._personas.values() if persona.estado is Nivel.ADVERTENCIA)
        nivel = Nivel.PELIGRO if en_peligro else Nivel.ADVERTENCIA if en_advertencia else Nivel.LIBRE
        return EstadoZona(nivel.nombre, en_peligro, en_advertencia)

    # ------------------------------------------------------------------ #
    def actualizar(self, t: float, observaciones: Mapping[int, Sequence[Punto]],
                   alarma_activa: bool = True) -> Resultado:
        """Procesa un fotograma.

        ``t`` es el tiempo en segundos y debe crecer de un fotograma al siguiente.
        ``observaciones`` trae, por id de persona, sus puntos de apoyo en píxeles de la imagen
        (los tobillos, o el punto medio del borde inferior de su caja). ``alarma_activa`` dice
        si en este momento la alarma puede sonar (la plataforma responde o hay sonido local);
        queda registrado en ``alarma_activada`` de cada ``ingreso_zona``.
        """
        eventos: list[EventoZona] = []
        vistas: list[VistaPersona] = []
        # Detectada pero sin ningún punto de apoyo: como si no se viera
        presentes = {persona_id: tuple(puntos) for persona_id, puntos in observaciones.items() if puntos}
        for persona_id, puntos in presentes.items():
            persona = self._personas.get(persona_id)
            heredada_de = None
            if persona is None:
                persona = self._perdida_que_reaparece(puntos, t, presentes)
                if persona is None:
                    persona = _Persona(persona_id, t)
                else:  # misma persona con otro id: sigue su seguimiento donde iba
                    heredada_de = persona.persona_id
                    del self._personas[heredada_de]
                    persona.persona_id = persona_id
                self._personas[persona_id] = persona
            vistas.append(self._observar(persona, t, puntos, alarma_activa, eventos, heredada_de))
        for persona_id in [clave for clave in self._personas if clave not in presentes]:
            persona = self._personas[persona_id]
            if t - persona.visto > self._espera(persona):
                self._despedir(persona, eventos)
                del self._personas[persona_id]
            else:
                if persona.estado is Nivel.PELIGRO and alarma_activa:
                    persona.alarma_activada = True
                vistas.append(persona.vista(presente=False))
        estado = self.estado
        return Resultado(estado, tuple(vistas), tuple(self._eventos_de_estado(t, estado) + eventos))

    def cerrar(self, t: float) -> tuple[EventoZona, ...]:
        """Cierra la vigilancia (al apagar la estación o al cambiar la zona).

        Da por retiradas a todas las personas, con sus eventos pendientes, y deja la zona en
        libre para que ninguna alarma se quede encendida.
        """
        eventos: list[EventoZona] = []
        for persona in self._personas.values():
            self._despedir(persona, eventos)
        self._personas.clear()
        return tuple(self._eventos_de_estado(t, self.estado) + eventos)

    # ------------------------------------------------------------------ #
    def _espera(self, persona: _Persona) -> float:
        """Cuánto se conserva el estado de una persona que se dejó de ver.

        Quien se dejó de ver dentro de la zona puede seguir ahí, oculta: se espera más. Quien
        ya iba saliendo (su último fotograma fue fuera de la zona) no está oculta dentro.
        """
        if persona.oculta_dentro:
            return self.parametros.segundos_perdida_peligro
        return self.parametros.segundos_perdida

    def _perdida_que_reaparece(self, puntos: tuple[Punto, ...], t: float,
                               presentes: Mapping[int, tuple[Punto, ...]]) -> _Persona | None:
        """Decide si un id nuevo es en realidad una persona que se había dejado de ver.

        Lo es en dos casos, siempre dentro de la espera de la persona perdida:

        - Aparece a menos del radio de reasociación de donde se la vio por última vez: el
          tracker le cambió el id.
        - Aparece dentro de la zona y la perdida estaba oculta dentro: salió de detrás de la
          máquina, aunque sea por el otro lado.

        Devuelve el seguimiento de la más cercana que cumpla, o None si es de verdad otra persona.
        """
        radio = self.parametros.radio_reasociacion_m if self.zona.en_metros else self.parametros.radio_reasociacion_px
        dentro = self.zona.medir(puntos).dentro
        candidatas = [
            persona for persona in self._personas.values()
            if persona.persona_id not in presentes and t - persona.visto <= self._espera(persona)
            and ((dentro and persona.oculta_dentro) or self.zona.separacion(persona.puntos, puntos) <= radio)
        ]
        if not candidatas:
            return None
        return min(candidatas, key=lambda persona: _separacion(persona.puntos, puntos))

    def _observar(self, persona: _Persona, t: float, puntos: tuple[Punto, ...], alarma_activa: bool,
                  eventos: list[EventoZona], heredada_de: int | None = None) -> VistaPersona:
        medida = self.zona.medir(puntos)
        persona.visto, persona.puntos, persona.medida = t, puntos, medida
        persona.nivel = clasificar(medida, self.zona, persona.estado)
        persona.cronometrar(t)

        # El acercamiento dura mientras la persona no esté libre, ni confirmada ni en este fotograma
        nuevo_minimo = False
        if persona.nivel > Nivel.LIBRE or persona.estado > Nivel.LIBRE:
            nuevo_minimo = persona.registrar_distancia(medida, self.zona.distancia(medida))
        else:
            persona.reiniciar_acercamiento()

        entro_a_peligro = False
        destino = self._destino(persona, t)
        if destino is not None:
            entro_a_peligro = destino is Nivel.PELIGRO
            self._cambiar(persona, destino, eventos)
        if persona.estado is Nivel.PELIGRO and alarma_activa:
            persona.alarma_activada = True
        return persona.vista(True, entro_a_peligro, nuevo_minimo, heredada_de)

    def _destino(self, persona: _Persona, t: float) -> Nivel | None:
        """El estado al que la persona debe pasar ya, o None si se queda como está."""
        espera = self.parametros.antirrebote_s - HOLGURA_S
        for nivel in (Nivel.PELIGRO, Nivel.ADVERTENCIA):  # subir: al nivel más alto ya sostenido
            desde = persona.desde_al_menos[nivel]
            if nivel > persona.estado and desde is not None and t - desde >= espera:
                return nivel
        for nivel in (Nivel.LIBRE, Nivel.ADVERTENCIA):  # bajar: al nivel más bajo ya sostenido
            desde = persona.desde_a_lo_sumo[nivel]
            if nivel < persona.estado and desde is not None and t - desde >= espera:
                return nivel
        return None

    def _cambiar(self, persona: _Persona, destino: Nivel, eventos: list[EventoZona]) -> None:
        """Aplica un cambio de estado confirmado y genera los eventos que cierra."""
        if persona.estado is Nivel.PELIGRO:
            # Salió de la zona: el ingreso se cuenta hasta que dejó de estar dentro, no hasta que se confirmó
            salida = persona.desde_a_lo_sumo[Nivel.ADVERTENCIA]
            eventos.append(self._ingreso(persona, persona.visto if salida is None else salida))
        persona.estado = destino
        if destino is Nivel.PELIGRO:
            # Igual al entrar: cuenta desde que puso el pie dentro
            persona.entrada_t = persona.desde_al_menos[Nivel.PELIGRO]
            persona.piso_peligro = True
            persona.alarma_activada = False
        elif destino is Nivel.LIBRE:
            if not persona.piso_peligro:
                eventos.append(self._casi_accidente(persona))
            persona.reiniciar_acercamiento()

    def _despedir(self, persona: _Persona, eventos: list[EventoZona]) -> None:
        """Cierra lo que la persona tenía abierto cuando se dejó de ver."""
        if persona.estado is Nivel.PELIGRO:
            salida = persona.desde_a_lo_sumo[Nivel.ADVERTENCIA]
            eventos.append(self._ingreso(persona, persona.visto if salida is None else salida))
        elif persona.estado is Nivel.ADVERTENCIA and not persona.piso_peligro:
            eventos.append(self._casi_accidente(persona))
        persona.estado = Nivel.LIBRE

    def _ingreso(self, persona: _Persona, salida_t: float) -> EventoZona:
        return evento_ingreso_zona(self.zona.zona_id, salida_t - persona.entrada_t, persona.alarma_activada,
                                   persona.persona_id)

    def _casi_accidente(self, persona: _Persona) -> EventoZona:
        return evento_casi_accidente(self.zona.zona_id, persona.minimo_px,
                                     persona.minimo_m if self.zona.en_metros else None,
                                     persona.persona_id, self.textos)

    def _eventos_de_estado(self, t: float, estado: EstadoZona) -> list[EventoZona]:
        """``estado_zona`` si cambió el estado o los conteos, o si toca refrescarlo."""
        if estado != self._emitido:
            refresco = False  # también es el primer estado: la plataforma arranca sabiendo cómo está la zona
        elif estado.estado != "libre" and t - self._t_emitido >= self.parametros.intervalo_refresco_s - HOLGURA_S:
            refresco = True
        else:
            return []
        self._emitido, self._t_emitido = estado, t
        return [evento_estado_zona(self.zona.zona_id, estado, refresco)]
