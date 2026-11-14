"""Puntaje REBA (Hignett y McAtamney, 2000) a partir de ángulos articulares.

Funciones puras: reciben ángulos en grados y condiciones de la tarea, y devuelven
puntajes. Las tablas A, B y C, el agarre y los niveles viven en ``tablas_reba.json``.

Convención de signos de los ángulos:

- tronco, cuello y brazo: positivo = flexión (hacia adelante), negativo = extensión.
- piernas: flexión de rodilla (0 = pierna recta).
- antebrazo: flexión del codo (0 = brazo recto).
- muñeca: desviación respecto a la línea del antebrazo, sin signo.

Convención de límites (la de Ergonautas, UPV): el valor exacto del límite cae en el rango
inferior. Por ejemplo, tronco a 20° exactos puntúa 2 y a 60° exactos puntúa 3. En la
muñeca, 15° exactos puntúan 1 (ninguna fuente lo define; decisión del proyecto).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Mapping

RUTA_TABLAS = Path(__file__).with_name("tablas_reba.json")

# El método da 1 punto al tronco "erguido" y 2 a cualquier flexión de 0 a 20°. Una medición
# con cámara nunca da 0° exactos, así que se considera erguido dentro de esta tolerancia.
# No sale del método: es una decisión de implementación y se puede cambiar por parámetro.
TOLERANCIA_ERGUIDO = 5.0

# Sin estos segmentos no se calcula el REBA final. La muñeca queda fuera: en vista lateral
# es una estimación de baja confianza y, si falta, se toma su puntaje mínimo (ver calcular_reba).
SEGMENTOS_ESENCIALES = ("tronco", "cuello", "piernas", "brazo", "antebrazo")
SEGMENTOS = ("tronco", "cuello", "piernas", "brazo", "antebrazo", "muneca")

# Nombre con el que queda anotado el ajuste automático del brazo (ver ``brazo_persona_inclinada``)
AJUSTE_BRAZO_INCLINADA = "brazo_persona_inclinada"


@lru_cache(maxsize=1)
def cargar_tablas() -> dict:
    """Lee las tablas REBA del archivo de datos (una sola vez)."""
    return json.loads(RUTA_TABLAS.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Grupo A
# --------------------------------------------------------------------------- #
def puntaje_tronco(angulo: float, torsion_o_inclinacion: bool = False,
                   tolerancia_erguido: float = TOLERANCIA_ERGUIDO) -> int:
    """Tronco: erguido 1; 0-20° flexión o extensión 2; 20-60° flexión o >20° extensión 3; >60° 4."""
    if abs(angulo) <= tolerancia_erguido:
        base = 1
    elif angulo > 0:  # flexión
        base = 2 if angulo <= 20 else 3 if angulo <= 60 else 4
    else:  # extensión
        base = 2 if -angulo <= 20 else 3
    return base + (1 if torsion_o_inclinacion else 0)


def puntaje_cuello(angulo: float, torsion_o_inclinacion: bool = False,
                   tolerancia_erguido: float = TOLERANCIA_ERGUIDO) -> int:
    """Cuello: 0-20° flexión 1; >20° flexión o en extensión 2.

    Una extensión dentro de la tolerancia se toma como cuello neutro (ruido de medición).
    """
    base = 1 if -tolerancia_erguido <= angulo <= 20 else 2
    return base + (1 if torsion_o_inclinacion else 0)


def puntaje_piernas(flexion_rodilla: float, apoyo_inestable: bool = False, sentado: bool = False) -> int:
    """Piernas: apoyo bilateral, caminando o sentado 1; unilateral o inestable 2.

    +1 si las rodillas están flexionadas entre 30 y 60°; +2 si más de 60° (salvo sentado).
    """
    base = 2 if apoyo_inestable else 1
    if sentado:
        return base
    if flexion_rodilla > 60:
        return base + 2
    if flexion_rodilla >= 30:
        return base + 1
    return base


def puntaje_carga(peso_kg: float, golpe_o_fuerza_brusca: bool = False) -> int:
    """Carga o fuerza: <5 kg 0; 5-10 kg 1; >10 kg 2. +1 si hay golpe o fuerza brusca."""
    base = 0 if peso_kg < 5 else 1 if peso_kg <= 10 else 2
    return base + (1 if golpe_o_fuerza_brusca else 0)


# --------------------------------------------------------------------------- #
# Grupo B
# --------------------------------------------------------------------------- #
def puntaje_brazo(angulo: float, abducido_o_rotado: bool = False, hombro_elevado: bool = False,
                  apoyado_o_a_favor_de_gravedad: bool = False) -> int:
    """Brazo: 20° ext. a 20° flex. 1; >20° ext. o 20-45° flex. 2; 45-90° flex. 3; >90° 4."""
    if -20 <= angulo <= 20:
        base = 1
    elif angulo < -20 or angulo <= 45:
        base = 2
    elif angulo <= 90:
        base = 3
    else:
        base = 4
    base += (1 if abducido_o_rotado else 0) + (1 if hombro_elevado else 0)
    base -= 1 if apoyado_o_a_favor_de_gravedad else 0
    return max(1, base)


def brazo_persona_inclinada(angulo_tronco: float | None, brazo_vertical: float | None,
                            umbral_tronco: float = 45.0, tolerancia_vertical: float = 20.0) -> bool:
    """Indica si aplica el -1 del brazo porque la persona está inclinada.

    La hoja de REBA resta 1 al brazo si está apoyado "o si la persona está inclinada": con
    el tronco doblado, un brazo que cuelga hacia el piso está a favor de la gravedad aunque
    respecto al tronco marque mucha flexión. Aplica cuando el tronco está flexionado más de
    ``umbral_tronco`` y el brazo se aparta de la vertical del piso (``brazo_vertical``, sin
    signo) como mucho ``tolerancia_vertical``.
    """
    if angulo_tronco is None or brazo_vertical is None:
        return False
    return angulo_tronco > umbral_tronco and abs(brazo_vertical) <= tolerancia_vertical


def puntaje_antebrazo(flexion_codo: float) -> int:
    """Antebrazo: 60-100° de flexión 1; menos de 60° o más de 100° 2."""
    return 1 if 60 <= flexion_codo <= 100 else 2


def puntaje_muneca(angulo: float, desviacion_o_torsion: bool = False) -> int:
    """Muñeca: 0-15° de flexión o extensión 1; más de 15° 2. +1 con desviación o torsión."""
    base = 1 if abs(angulo) <= 15 else 2
    return base + (1 if desviacion_o_torsion else 0)


def puntaje_agarre(agarre: str) -> int:
    """Agarre: bueno 0; regular 1; malo 2; inaceptable 3."""
    try:
        return cargar_tablas()["agarre"][agarre]
    except KeyError:
        raise ValueError(f"Agarre desconocido: {agarre!r}") from None


# --------------------------------------------------------------------------- #
# Tablas y niveles
# --------------------------------------------------------------------------- #
def _en_rango(nombre: str, valor: int, maximo: int) -> int:
    if not 1 <= valor <= maximo:
        raise ValueError(f"{nombre} fuera de rango (1-{maximo}): {valor}")
    return valor - 1


def tabla_a(cuello: int, tronco: int, piernas: int) -> int:
    valores = cargar_tablas()["tabla_a"]["valores"]
    return valores[_en_rango("cuello", cuello, 3)][_en_rango("tronco", tronco, 5)][_en_rango("piernas", piernas, 4)]


def tabla_b(antebrazo: int, brazo: int, muneca: int) -> int:
    valores = cargar_tablas()["tabla_b"]["valores"]
    return valores[_en_rango("antebrazo", antebrazo, 2)][_en_rango("brazo", brazo, 6)][_en_rango("muneca", muneca, 3)]


def tabla_c(puntaje_a: int, puntaje_b: int) -> int:
    valores = cargar_tablas()["tabla_c"]["valores"]
    return valores[_en_rango("puntaje A", puntaje_a, 12)][_en_rango("puntaje B", puntaje_b, 12)]


def _nivel(puntaje: int) -> dict:
    for nivel in cargar_tablas()["niveles"]:
        if nivel["desde"] <= puntaje <= nivel["hasta"]:
            return nivel
    raise ValueError(f"Puntaje REBA fuera de rango (1-15): {puntaje}")


def nivel_de_riesgo(puntaje: int) -> str:
    """Nivel REBA: 1 insignificante; 2-3 bajo; 4-7 medio; 8-10 alto; 11-15 muy_alto."""
    return _nivel(puntaje)["nivel"]


def severidad_de(puntaje: int) -> str:
    """Severidad del evento: 1 info; 2-3 baja; 4-7 media; 8-10 alta; 11-15 critica."""
    return _nivel(puntaje)["severidad"]


# --------------------------------------------------------------------------- #
# Evaluación completa
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Condiciones:
    """Lo que la cámara no mide: datos de la tarea y ajustes que marca el operador.

    Torsión, inclinación lateral, abducción y desviación no se miden de forma fiable en
    vista lateral 2D: por defecto no suman.
    """

    peso_carga_kg: float = 5.0
    golpe_o_fuerza_brusca: bool = False
    agarre: str = "bueno"
    apoyo_inestable: bool = False
    sentado: bool = False
    torsion_tronco: bool = False
    torsion_cuello: bool = False
    brazo_abducido_o_rotado: bool = False
    hombro_elevado: bool = False
    brazo_apoyado: bool = False
    muneca_desviada: bool = False
    # Ajuste automático: -1 al brazo si la persona está inclinada y el brazo cuelga vertical
    ajuste_brazo_inclinada: bool = True
    umbral_tronco_inclinado: float = 45.0  # flexión del tronco (grados) a partir de la que aplica
    tolerancia_brazo_vertical: float = 20.0  # grados que el brazo puede apartarse de la vertical
    # Actividad: +1 por cada condición
    actividad_estatica: bool = False  # una o más partes del cuerpo estáticas más de 1 min
    actividad_repetitiva: bool = False  # acciones repetidas en rango pequeño, más de 4 por minuto
    actividad_cambios_rapidos: bool = False  # cambios posturales rápidos y amplios, o base inestable


@dataclass(frozen=True)
class ResultadoReba:
    """Resultado de una evaluación. ``puntaje`` es None si faltó un segmento esencial."""

    segmentos: dict[str, int | None]  # puntaje por segmento; None = no estimado
    no_estimados: tuple[str, ...]  # segmentos sin ángulo
    asumidos: tuple[str, ...] = ()  # segmentos sin ángulo que entraron al cálculo con su mínimo
    ajustes_aplicados: tuple[str, ...] = ()  # ajustes automáticos, p. ej. "brazo_persona_inclinada"
    tabla_a: int | None = None
    carga: int = 0
    puntaje_a: int | None = None
    tabla_b: int | None = None
    agarre: int = 0
    puntaje_b: int | None = None
    tabla_c: int | None = None
    actividad: int = 0
    puntaje: int | None = None
    nivel: str | None = None
    severidad: str | None = None
    angulos: dict[str, float | None] = field(default_factory=dict)

    @property
    def completo(self) -> bool:
        return self.puntaje is not None


def calcular_reba(angulos: Mapping[str, float | None], condiciones: Condiciones | None = None,
                  tolerancia_erguido: float = TOLERANCIA_ERGUIDO) -> ResultadoReba:
    """Calcula el REBA completo a partir de los ángulos (grados) de los seis segmentos.

    ``angulos`` usa las claves ``tronco``, ``cuello``, ``piernas``, ``brazo``, ``antebrazo``
    y ``muneca``, más la opcional ``brazo_vertical`` (ángulo del brazo respecto a la vertical
    del piso), que solo sirve para el ajuste del brazo por persona inclinada. Un valor None (o una clave ausente) es un segmento no estimado: no se le
    inventa un puntaje. Si falta un segmento esencial no hay REBA final. Si solo falta la
    muñeca, el cálculo sigue con su puntaje mínimo (1) y queda anotada en ``asumidos``: el
    resultado es entonces una cota inferior.
    """
    condiciones = condiciones or Condiciones()
    medido = {nombre: angulos.get(nombre) for nombre in SEGMENTOS}
    c = condiciones
    # El -1 del brazo se aplica una sola vez, venga del operador (apoyado) o del ajuste automático
    inclinada = (c.ajuste_brazo_inclinada and not c.brazo_apoyado and medido["brazo"] is not None
                 and brazo_persona_inclinada(medido["tronco"], angulos.get("brazo_vertical"),
                                             c.umbral_tronco_inclinado, c.tolerancia_brazo_vertical))
    calculadores = {
        "tronco": lambda a: puntaje_tronco(a, c.torsion_tronco, tolerancia_erguido),
        "cuello": lambda a: puntaje_cuello(a, c.torsion_cuello, tolerancia_erguido),
        "piernas": lambda a: puntaje_piernas(a, c.apoyo_inestable, c.sentado),
        "brazo": lambda a: puntaje_brazo(a, c.brazo_abducido_o_rotado, c.hombro_elevado,
                                         c.brazo_apoyado or inclinada),
        "antebrazo": puntaje_antebrazo,
        "muneca": lambda a: puntaje_muneca(a, c.muneca_desviada),
    }
    segmentos = {n: (None if medido[n] is None else calculadores[n](medido[n])) for n in SEGMENTOS}
    no_estimados = tuple(n for n in SEGMENTOS if segmentos[n] is None)
    carga = puntaje_carga(c.peso_carga_kg, c.golpe_o_fuerza_brusca)
    agarre = puntaje_agarre(c.agarre)
    actividad = int(c.actividad_estatica) + int(c.actividad_repetitiva) + int(c.actividad_cambios_rapidos)
    comunes = dict(segmentos=segmentos, no_estimados=no_estimados, carga=carga, agarre=agarre,
                   actividad=actividad, angulos=medido,
                   ajustes_aplicados=(AJUSTE_BRAZO_INCLINADA,) if inclinada else ())

    if any(n in SEGMENTOS_ESENCIALES for n in no_estimados):
        return ResultadoReba(**comunes)

    asumidos = tuple(n for n in no_estimados if n not in SEGMENTOS_ESENCIALES)
    muneca = segmentos["muneca"] if segmentos["muneca"] is not None else 1
    valor_a = tabla_a(segmentos["cuello"], segmentos["tronco"], segmentos["piernas"])
    valor_b = tabla_b(segmentos["antebrazo"], segmentos["brazo"], muneca)
    puntaje_a, puntaje_b = valor_a + carga, valor_b + agarre
    valor_c = tabla_c(puntaje_a, puntaje_b)
    final = valor_c + actividad
    return ResultadoReba(**comunes, asumidos=asumidos, tabla_a=valor_a, puntaje_a=puntaje_a,
                         tabla_b=valor_b, puntaje_b=puntaje_b, tabla_c=valor_c, puntaje=final,
                         nivel=nivel_de_riesgo(final), severidad=severidad_de(final))
