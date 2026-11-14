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
from dataclasses import dataclass, replace
from typing import Mapping, NamedTuple

UMBRAL_VISIBILIDAD = 0.5
# Con el tronco más inclinado que esto, la cabeza ya no sirve para saber hacia dónde mira
INCLINACION_MAXIMA_PARA_FRENTE_POR_CABEZA = 60.0
# El neutro del tronco corrige del todo con la persona de pie y se desvanece al inclinarse
# estos grados respecto a su postura de pie (ver ``correccion_de_tronco``)
DESVANECER_NEUTRO_TRONCO = 30.0

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

    def con_neutro(self, tronco_neutro: float, cuello_neutro: float) -> "AngulosCuerpo":
        """Copia con tronco y cuello medidos desde la postura neutra de la persona.

        El cuello se corrige completo. El tronco, solo cerca de la postura de pie (ver
        ``correccion_de_tronco``). El brazo se mide respecto a la línea del tronco, así que
        lleva la misma corrección que el tronco; su ángulo respecto a la vertical del piso
        no cambia. Sin frente conocido los ángulos no tienen signo y no se corrigen.
        """
        if self.frente is None:
            return self
        def menos(valor: float | None, resta: float) -> float | None:
            return None if valor is None else valor - resta
        del_tronco = 0.0 if self.tronco is None else correccion_de_tronco(self.tronco, tronco_neutro)
        return replace(self, tronco=menos(self.tronco, del_tronco), cuello=menos(self.cuello, cuello_neutro),
                       brazo=menos(self.brazo, del_tronco))

    def para_reba(self) -> dict[str, float | None]:
        """Lo que recibe ``calcular_reba``: los seis ángulos más los auxiliares."""
        return {**self.como_dict(), "brazo_vertical": self.brazo_vertical}


def correccion_de_tronco(tronco_crudo: float, tronco_neutro: float,
                         desvanecer: float = DESVANECER_NEUTRO_TRONCO) -> float:
    """Cuánto restarle al tronco crudo para medirlo desde la postura neutra de la persona.

    De pie se resta el neutro completo (queda en 0°). A medida que la persona se inclina, la
    corrección se desvanece y a ``desvanecer`` grados de su postura de pie ya no se resta nada.

    Por qué no restar siempre el neutro: el desfase que se ve de pie (el hombro algo por
    detrás de la cadera) depende de la postura y del punto de vista de la cámara, y no se
    conserva al agacharse. Visto en vivo: con el tronco casi horizontal y el hombro todavía
    por encima de la cadera (83° medidos), restar un neutro de −17° daba 100°, que significaría
    el hombro por debajo de la cadera. Agachado, el ángulo crudo es el que coincide con la imagen.
    """
    peso = max(0.0, 1.0 - abs(tronco_crudo - tronco_neutro) / desvanecer)
    return tronco_neutro * peso


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
def elegir_lado(puntos: Puntos, actual: str | None = None, margen: float = 0.0) -> str:
    """Lado del cuerpo con mayor visibilidad media (el que mira a la cámara).

    Con ``actual`` y ``margen`` hay histéresis: el lado vigente se conserva mientras el
    otro no lo supere por más de ``margen``, para que no salte de un fotograma a otro.
    """
    def media(lado: str) -> float:
        return sum(puntos[f"{p}_{lado}"].visibilidad if f"{p}_{lado}" in puntos else 0.0
                   for p in PUNTOS_DE_LADO) / len(PUNTOS_DE_LADO)
    if actual in LADOS:
        otro = LADOS[1 - LADOS.index(actual)]
        return otro if media(otro) > media(actual) + margen else actual
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

    Primero por el pie (la punta queda delante del talón): está apoyado en el piso y no
    cambia durante el levantamiento. Si no se ve, por la cabeza (la nariz queda delante de
    la oreja), pero solo con el tronco más o menos erguido: al agacharse a fondo la cabeza
    cuelga y esa señal se invierte.
    """
    pie = _visibles(puntos, (f"talon_{lado}", f"punta_pie_{lado}"), umbral)
    if pie is not None and pie[1].x != pie[0].x:
        return 1 if pie[1].x > pie[0].x else -1
    tronco = _visibles(puntos, (f"cadera_{lado}", f"hombro_{lado}"), umbral)
    if tronco is not None and abs(angulo_tronco(*tronco)) > INCLINACION_MAXIMA_PARA_FRENTE_POR_CABEZA:
        return None
    cabeza = _visibles(puntos, (f"oreja_{lado}", "nariz"), umbral)
    if cabeza is not None and cabeza[1].x != cabeza[0].x:
        return 1 if cabeza[1].x > cabeza[0].x else -1
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
