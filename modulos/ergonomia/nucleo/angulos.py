"""Ángulos articulares a partir de puntos clave 2D en vista lateral.

Funciones puras, solo con ``math``. Los puntos van en **píxeles** de la imagen (x hacia la
derecha, y hacia abajo), no normalizados: con coordenadas normalizadas de una imagen que no
es cuadrada los ángulos salen deformados.

Nombres de los puntos (con sufijo ``_izquierdo`` o ``_derecho`` salvo la nariz):
``nariz``, ``oreja``, ``hombro``, ``codo``, ``muneca``, ``indice``, ``menique``,
``cadera``, ``rodilla``, ``tobillo``, ``talon``, ``punta_pie``.

Signos: positivo = flexión (hacia donde mira la persona), negativo = extensión. Para eso
hace falta saber hacia qué lado de la imagen mira (``frente``: +1 derecha, -1 izquierda).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, NamedTuple

UMBRAL_VISIBILIDAD = 0.5

LADOS = ("izquierdo", "derecho")
# Puntos con los que se decide qué lado del cuerpo mira a la cámara
PUNTOS_DE_LADO = ("hombro", "codo", "muneca", "cadera", "rodilla", "tobillo")


class Punto(NamedTuple):
    """Punto clave en píxeles, con la visibilidad (0 a 1) que da el estimador de pose."""

    x: float
    y: float
    visibilidad: float = 1.0


Puntos = Mapping[str, Punto]


@dataclass(frozen=True)
class AngulosCuerpo:
    """Ángulos en grados del lado evaluado. None = segmento no estimado (puntos poco visibles)."""

    lado: str
    frente: int | None  # +1 mira a la derecha de la imagen, -1 a la izquierda, None desconocido
    tronco: float | None = None
    cuello: float | None = None
    piernas: float | None = None
    brazo: float | None = None
    antebrazo: float | None = None
    muneca: float | None = None  # estimación de baja confianza
    # Auxiliar, no es un segmento REBA: ángulo del brazo respecto a la vertical del piso
    brazo_vertical: float | None = None

    def como_dict(self) -> dict[str, float | None]:
        """Los seis ángulos REBA, con las claves del contrato de eventos."""
        return {n: getattr(self, n) for n in ("tronco", "cuello", "piernas", "brazo", "antebrazo", "muneca")}

    def para_reba(self) -> dict[str, float | None]:
        """Lo que recibe ``calcular_reba``: los seis ángulos más los auxiliares."""
        return {**self.como_dict(), "brazo_vertical": self.brazo_vertical}


# --------------------------------------------------------------------------- #
# Geometría
# --------------------------------------------------------------------------- #
def _normalizar(grados: float) -> float:
    """Lleva un ángulo al intervalo (-180, 180]."""
    grados = (grados + 180.0) % 360.0 - 180.0
    return 180.0 if grados == -180.0 else grados


def angulo_en_vertice(a: Punto, vertice: Punto, b: Punto) -> float:
    """Ángulo interior (0 a 180°) en ``vertice`` entre los segmentos hacia ``a`` y hacia ``b``."""
    ax, ay = a.x - vertice.x, a.y - vertice.y
    bx, by = b.x - vertice.x, b.y - vertice.y
    return abs(math.degrees(math.atan2(ax * by - ay * bx, ax * bx + ay * by)))


def _desde_arriba(origen: Punto, destino: Punto, frente: int) -> float:
    """Ángulo del vector origen→destino medido desde la vertical hacia arriba; + = hacia el frente."""
    return math.degrees(math.atan2((destino.x - origen.x) * frente, -(destino.y - origen.y)))


def _desde_abajo(origen: Punto, destino: Punto, frente: int) -> float:
    """Ángulo del vector origen→destino medido desde la vertical hacia abajo; + = hacia el frente."""
    return math.degrees(math.atan2((destino.x - origen.x) * frente, destino.y - origen.y))


def angulo_tronco(cadera: Punto, hombro: Punto, frente: int = 1) -> float:
    """Inclinación del tronco: ángulo entre la vertical y el vector cadera → hombro."""
    return _desde_arriba(cadera, hombro, frente)


def angulo_cuello(cadera: Punto, hombro: Punto, oreja: Punto, frente: int = 1) -> float:
    """Ángulo de la cabeza (hombro → oreja) respecto a la línea del tronco (cadera → hombro)."""
    return _normalizar(_desde_arriba(hombro, oreja, frente) - _desde_arriba(cadera, hombro, frente))


def flexion_rodilla(cadera: Punto, rodilla: Punto, tobillo: Punto) -> float:
    """Flexión de la rodilla: 180° menos el ángulo cadera-rodilla-tobillo (0 = pierna recta)."""
    return 180.0 - angulo_en_vertice(cadera, rodilla, tobillo)


def angulo_brazo(cadera: Punto, hombro: Punto, codo: Punto, frente: int = 1) -> float:
    """Ángulo entre la línea del tronco hacia abajo (hombro → cadera) y hombro → codo.

    Positivo = flexión. Va de -90° (extensión máxima plausible) a 270°: un brazo por encima
    de la cabeza y algo hacia atrás sigue siendo flexión de más de 180°, no extensión.
    """
    angulo = _normalizar(_desde_abajo(hombro, codo, frente) - _desde_abajo(hombro, cadera, frente))
    return angulo + 360.0 if angulo < -90.0 else angulo


def angulo_brazo_vertical(hombro: Punto, codo: Punto) -> float:
    """Cuánto se aparta el brazo (hombro → codo) de la vertical hacia el piso, sin signo (0 a 180°)."""
    return abs(_desde_abajo(hombro, codo, 1))


def flexion_codo(hombro: Punto, codo: Punto, muneca: Punto) -> float:
    """Flexión del antebrazo: 180° menos el ángulo hombro-codo-muñeca (0 = brazo recto)."""
    return 180.0 - angulo_en_vertice(hombro, codo, muneca)


def angulo_muneca(codo: Punto, muneca: Punto, indice: Punto, menique: Punto) -> float:
    """Desviación de la mano respecto al antebrazo (sin signo). Estimación de baja confianza.

    La mano se toma como muñeca → punto medio entre índice y meñique.
    """
    mano = Punto((indice.x + menique.x) / 2.0, (indice.y + menique.y) / 2.0)
    return 180.0 - angulo_en_vertice(codo, muneca, mano)


# --------------------------------------------------------------------------- #
# Lado, frente y cálculo conjunto
# --------------------------------------------------------------------------- #
def elegir_lado(puntos: Puntos) -> str:
    """Lado del cuerpo con mayor visibilidad media (el que mira a la cámara)."""
    def media(lado: str) -> float:
        return sum(puntos[f"{p}_{lado}"].visibilidad if f"{p}_{lado}" in puntos else 0.0
                   for p in PUNTOS_DE_LADO) / len(PUNTOS_DE_LADO)
    return max(LADOS, key=media)  # en empate gana el izquierdo


def _visibles(puntos: Puntos, nombres: tuple[str, ...], umbral: float) -> tuple[Punto, ...] | None:
    """Los puntos pedidos, o None si alguno falta o no alcanza el umbral de visibilidad."""
    encontrados = []
    for nombre in nombres:
        punto = puntos.get(nombre)
        if punto is None or punto.visibilidad < umbral:
            return None
        encontrados.append(punto)
    return tuple(encontrados)


def direccion_frente(puntos: Puntos, lado: str, umbral: float = UMBRAL_VISIBILIDAD) -> int | None:
    """Hacia qué lado de la imagen mira la persona: +1 derecha, -1 izquierda, None si no se sabe.

    Primero por la cabeza (la nariz queda delante de la oreja) y, si no se ve, por el pie
    (la punta queda delante del talón).
    """
    for atras, adelante in ((f"oreja_{lado}", "nariz"), (f"talon_{lado}", f"punta_pie_{lado}")):
        par = _visibles(puntos, (atras, adelante), umbral)
        if par is not None and par[1].x != par[0].x:
            return 1 if par[1].x > par[0].x else -1
    return None


def calcular_angulos(puntos: Puntos, lado: str = "auto", frente: int | None = None,
                     umbral_visibilidad: float = UMBRAL_VISIBILIDAD) -> AngulosCuerpo:
    """Calcula los seis ángulos REBA del lado elegido.

    ``lado``: ``"auto"`` (el más visible), ``"izquierdo"`` o ``"derecho"``. ``frente`` se
    deduce de los puntos si no se indica; si no se puede deducir, tronco, cuello y brazo se
    devuelven sin signo (se toman como flexión). Un segmento con algún punto por debajo de
    ``umbral_visibilidad`` queda en None: no se inventa.
    """
    if lado == "auto":
        lado = elegir_lado(puntos)
    elif lado not in LADOS:
        raise ValueError(f"Lado desconocido: {lado!r}")
    if frente is None:
        frente = direccion_frente(puntos, lado, umbral_visibilidad)
    sentido = frente or 1

    def con(*nombres: str) -> tuple[Punto, ...] | None:
        return _visibles(puntos, tuple(f"{n}_{lado}" for n in nombres), umbral_visibilidad)

    def firmado(valor: float) -> float:
        return valor if frente is not None else abs(valor)

    tronco = cuello = piernas = brazo = antebrazo = muneca = brazo_vertical = None
    if (p := con("cadera", "hombro")) is not None:
        tronco = firmado(angulo_tronco(*p, sentido))
    if (p := con("cadera", "hombro", "oreja")) is not None:
        cuello = firmado(angulo_cuello(*p, sentido))
    if (p := con("cadera", "rodilla", "tobillo")) is not None:
        piernas = flexion_rodilla(*p)
    if (p := con("cadera", "hombro", "codo")) is not None:
        brazo = firmado(angulo_brazo(*p, sentido))
        brazo_vertical = angulo_brazo_vertical(p[1], p[2])
    if (p := con("hombro", "codo", "muneca")) is not None:
        antebrazo = flexion_codo(*p)
    if (p := con("codo", "muneca", "indice", "menique")) is not None:
        muneca = angulo_muneca(*p)
    return AngulosCuerpo(lado=lado, frente=frente, tronco=tronco, cuello=cuello, piernas=piernas,
                         brazo=brazo, antebrazo=antebrazo, muneca=muneca,
                         brazo_vertical=brazo_vertical)
