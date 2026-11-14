"""Detección automática de la cinta amarilla que marca la zona en el piso.

Es una propuesta, no una decisión: la zona solo se activa cuando una persona la confirma.
Debe correrse con la zona vacía (sin personas y, de ser posible, antes de poner la máquina).

Cómo busca:

1. Máscara de amarillo en HSV (rango configurable).
2. Apertura para quitar puntos sueltos y cierre para unir las franjas amarillas de una
   cinta amarilla y negra.
3. De los contornos que quedan, el más grande que sea un marco hueco: la cinta rodea la
   zona, mientras que un objeto amarillo (una caja, un casco) es macizo.
4. Aproximación a polígono. Si resulta un cuadrilátero, sirve como rectángulo para la
   conversión a metros, y sus esquinas se afinan cortando las rectas de los lados.

Si no la encuentra lo dice con el motivo: no hay amarillo, solo hay objetos macizos, la
cinta se sale de la imagen o no llega a cerrar una figura.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import cv2
import numpy as np

from ..nucleo.geometria import Punto, area_con_signo

ANCHO_DE_TRABAJO = 960  # la detección corre sobre una copia reducida: más rápida y con menos ruido
# Tamaños del cierre, como fracción del ancho. Debe cubrir una franja negra: si con el primero
# el marco queda en pedazos (cinta vista muy de cerca), se prueba con los siguientes.
FRACCIONES_CIERRE = (0.022, 0.035, 0.05)
AREA_MINIMA = 0.02  # la zona debe ocupar al menos esta fracción de la imagen
RELLENO_MAXIMO = 0.6  # un marco de cinta tiene amarillo en menos de esta fracción de lo que encierra
SOLIDEZ_DE_TIRA = 0.5  # una tira de cinta encierra menos de esta fracción de lo que abarca
MARGEN_BORDE_PX = 3  # a esta distancia del borde de la imagen (en la copia reducida) la zona "toca el borde"

SIN_CINTA = ("No se encontró la cinta amarilla en la imagen. Revisa la iluminación y que la zona esté "
             "vacía, o marca la zona a mano.")
SOLO_OBJETOS = ("Se ve amarillo, pero no un marco de cinta: parece un objeto macizo. Despeja la zona "
                "o márcala a mano.")
ES_RECTANGULO = "Se encontró el rectángulo de cinta. Revisa las esquinas, escribe sus medidas reales y guarda la zona."
NO_ES_RECTANGULO = ("Se encontró la cinta, pero la figura tiene {lados} lados. Ajusta los vértices a mano; "
                    "para medir en metros la zona debe tener cuatro.")
CINTA_CORTADA = ("Se ve cinta amarilla, pero se sale de la imagen. Mueve la cámara para ver la zona "
                 "completa, o márcala a mano.")
CINTA_ABIERTA = ("Se ve cinta amarilla, pero no cierra una figura. Revisa que rodee toda la zona y que nada "
                 "la tape, o márcala a mano.")
TOCA_BORDE = " La zona toca el borde de la imagen: mueve la cámara para verla completa."


@dataclass(frozen=True)
class RangoHSV:
    """Rango de color del amarillo en HSV de OpenCV (tono 0-179; saturación y brillo 0-255)."""

    h_min: int = 18
    h_max: int = 38
    s_min: int = 80
    v_min: int = 80

    @classmethod
    def desde_config(cls, valores: Mapping[str, Any] | None) -> "RangoHSV":
        """Del grupo ``cinta_hsv`` de la configuración (ya validada)."""
        if not valores:
            return cls()
        base = cls()
        return cls(*(int(valores.get(campo, getattr(base, campo))) for campo in ("h_min", "h_max", "s_min", "v_min")))


@dataclass(frozen=True)
class DeteccionCinta:
    """Resultado de buscar la cinta en una imagen."""

    poligono: tuple[Punto, ...] | None  # vértices normalizados (0 a 1), o None si no se encontró
    mensaje: str  # qué pasó, para mostrárselo a quien calibra
    mascara: np.ndarray  # máscara de amarillo ya limpia, del tamaño de la imagen (para diagnóstico)
    toca_borde: bool = False

    @property
    def encontrada(self) -> bool:
        return self.poligono is not None

    @property
    def es_cuadrilatero(self) -> bool:
        return self.poligono is not None and len(self.poligono) == 4


def _amarillo(imagen: np.ndarray, rango: RangoHSV) -> np.ndarray:
    """Píxeles amarillos de la imagen, sin puntos sueltos (todavía con las franjas separadas)."""
    suave = cv2.GaussianBlur(imagen, (5, 5), 0)
    hsv = cv2.cvtColor(suave, cv2.COLOR_BGR2HSV)
    mascara = cv2.inRange(hsv, (rango.h_min, rango.s_min, rango.v_min), (rango.h_max, 255, 255))
    return cv2.morphologyEx(mascara, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))


def _unir_franjas(amarillo: np.ndarray, fraccion: float) -> np.ndarray:
    """Cierre morfológico: une las franjas amarillas separadas por menos de ``fraccion`` del ancho."""
    lado = max(5, round(amarillo.shape[1] * fraccion) | 1)  # impar
    return cv2.morphologyEx(amarillo, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (lado, lado)))


def mascara_de_amarillo(imagen: np.ndarray, rango: RangoHSV, fraccion_cierre: float = FRACCIONES_CIERRE[0]) -> np.ndarray:
    """Máscara binaria del amarillo de la cinta, sin puntos sueltos y con las franjas unidas."""
    return _unir_franjas(_amarillo(imagen, rango), fraccion_cierre)


def _relleno(mascara: np.ndarray, contorno: np.ndarray, area: float) -> float:
    """Fracción de lo que encierra el contorno que es amarillo: baja en un marco, alta en un objeto macizo."""
    x, y, ancho, alto = cv2.boundingRect(contorno)
    interior = np.zeros((alto, ancho), dtype=np.uint8)
    cv2.drawContours(interior, [contorno], -1, 255, thickness=cv2.FILLED, offset=(-x, -y))
    amarillo = cv2.countNonZero(cv2.bitwise_and(mascara[y:y + alto, x:x + ancho], interior))
    return amarillo / area if area > 0 else 1.0


def _a_poligono(contorno: np.ndarray, area: float) -> np.ndarray:
    """Aproxima el contorno a un polígono de pocos vértices (N x 2)."""
    casco = cv2.convexHull(contorno)
    area_casco = cv2.contourArea(casco)
    # Si la figura no tiene entrantes se usa su casco, que limpia los dientes que dejan las franjas
    convexa = area_casco > 0 and area / area_casco >= 0.9
    base = casco if convexa else contorno
    perimetro = cv2.arcLength(base, True)
    aproximaciones = [cv2.approxPolyDP(base, fraccion * perimetro, True) for fraccion in (0.01, 0.02, 0.03)]
    elegido = next((poligono for poligono in aproximaciones if len(poligono) == 4), aproximaciones[1])
    vertices = elegido.reshape(-1, 2).astype(float)
    if convexa and len(vertices) == 4:
        vertices = _afinar_esquinas(casco.reshape(-1, 2).astype(float), vertices)
    return vertices


def _afinar_esquinas(casco: np.ndarray, esquinas: np.ndarray) -> np.ndarray:
    """Recoloca las cuatro esquinas donde se cortan las rectas de los lados.

    En una cinta amarilla y negra la esquina puede caer en una franja negra: a la máscara le
    falta ese pedazo y la esquina aproximada queda corrida hacia adentro. Los lados, en
    cambio, se ven bien: se ajusta una recta a cada uno (sin sus extremos) y las esquinas
    salen de cortar rectas vecinas. Si algo no cuadra, se devuelven las esquinas originales.
    """
    borde = _muestrear(casco)
    lado_minimo = min(float(np.linalg.norm(esquinas[(i + 1) % 4] - esquinas[i])) for i in range(4))
    rectas = []
    for i in range(4):
        desde, hasta = esquinas[i], esquinas[(i + 1) % 4]
        largo = float(np.linalg.norm(hasta - desde))
        if largo < 8:
            return esquinas
        direccion = (hasta - desde) / largo
        relativo = borde - desde
        avance = relativo @ direccion  # posición a lo largo del lado
        desvio = np.abs(relativo @ np.array([-direccion[1], direccion[0]]))  # distancia a la recta del lado
        del_lado = borde[(avance > 0.18 * largo) & (avance < 0.82 * largo) & (desvio < 0.05 * largo + 3)]
        if len(del_lado) < 6:
            rectas.append((desde, direccion))
            continue
        vx, vy, x0, y0 = cv2.fitLine(del_lado.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        rectas.append((np.array([x0, y0], dtype=float), np.array([vx, vy], dtype=float)))
    afinadas = []
    for i in range(4):
        (p, d), (q, e) = rectas[i - 1], rectas[i]  # la esquina i es el cruce del lado anterior con el lado i
        determinante = d[0] * e[1] - d[1] * e[0]
        if abs(determinante) < 1e-6:
            return esquinas
        paso = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / determinante
        cruce = p + paso * d
        if float(np.linalg.norm(cruce - esquinas[i])) > 0.25 * lado_minimo:  # se fue demasiado lejos: no es fiable
            return esquinas
        afinadas.append(cruce)
    return np.array(afinadas)


def _muestrear(poligono: np.ndarray, paso: float = 2.0) -> np.ndarray:
    """Puntos repartidos cada ``paso`` píxeles a lo largo del borde de un polígono cerrado (N x 2)."""
    tramos = []
    for i in range(len(poligono)):
        desde, hasta = poligono[i], poligono[(i + 1) % len(poligono)]
        cantidad = max(1, int(np.linalg.norm(hasta - desde) / paso))
        tramos.append(desde + (hasta - desde) * np.linspace(0.0, 1.0, cantidad, endpoint=False)[:, None])
    return np.vstack(tramos)


def ordenar_vertices(vertices: list[Punto]) -> list[Punto]:
    """Deja los vértices en sentido horario en la imagen, empezando por el de arriba a la izquierda.

    Así, en un cuadrilátero, el lado del primer vértice al segundo es el de arriba (el lejano
    a la cámara) y el del segundo al tercero es el de la derecha.
    """
    if area_con_signo(vertices) < 0:  # con el eje y hacia abajo, área positiva = sentido horario
        vertices = list(reversed(vertices))
    primero = min(range(len(vertices)), key=lambda i: vertices[i][0] + vertices[i][1])
    return vertices[primero:] + vertices[:primero]


def detectar_cinta(imagen: np.ndarray, rango: RangoHSV | None = None, *, area_minima: float = AREA_MINIMA,
                   relleno_maximo: float = RELLENO_MAXIMO) -> DeteccionCinta:
    """Busca la cinta amarilla en la imagen BGR y propone el polígono de la zona.

    Nunca lanza por no encontrarla: devuelve ``poligono=None`` y un mensaje claro.
    """
    rango = rango or RangoHSV()
    alto, ancho = imagen.shape[:2]
    escala = min(1.0, ANCHO_DE_TRABAJO / ancho)
    trabajo = cv2.resize(imagen, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA) if escala < 1.0 else imagen
    alto_t, ancho_t = trabajo.shape[:2]

    def completa(mascara: np.ndarray) -> np.ndarray:
        return cv2.resize(mascara, (ancho, alto), interpolation=cv2.INTER_NEAREST) if escala < 1.0 else mascara

    def en_el_borde(puntos: np.ndarray) -> bool:
        return bool(((puntos[:, 0] <= MARGEN_BORDE_PX) | (puntos[:, 0] >= ancho_t - 1 - MARGEN_BORDE_PX)
                     | (puntos[:, 1] <= MARGEN_BORDE_PX) | (puntos[:, 1] >= alto_t - 1 - MARGEN_BORDE_PX)).any())

    amarillo = _amarillo(trabajo, rango)
    primera: tuple[np.ndarray, list] | None = None  # máscara y figuras grandes del primer intento
    mascara, marcos = amarillo, []
    for fraccion in FRACCIONES_CIERRE:
        mascara = _unir_franjas(amarillo, fraccion)
        contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # De cada figura: lo que encierra su contorno, lo que abarca (su casco) y el contorno.
        # El tamaño se juzga por lo que abarca: una cinta que no cierra encierra poco, pero abarca mucho.
        figuras = [(cv2.contourArea(contorno), cv2.contourArea(cv2.convexHull(contorno)), contorno)
                   for contorno in contornos]
        grandes = sorted((figura for figura in figuras if figura[1] >= area_minima * ancho_t * alto_t),
                         key=lambda figura: figura[0], reverse=True)
        if primera is None:
            primera = (mascara, grandes)
        marcos = [(area, contorno) for area, _, contorno in grandes
                  if _relleno(mascara, contorno, area) <= relleno_maximo]
        if marcos:
            break
    if not marcos:  # ningún tamaño de cierre dio un marco: se explica con lo que se vio en el primero
        mascara, grandes = primera
        if not grandes:
            return DeteccionCinta(None, SIN_CINTA, completa(mascara))
        # Una tira delgada (encierra mucho menos de lo que abarca) es cinta que no llega a cerrar la figura
        tiras = [contorno for area, area_casco, contorno in grandes if area < SOLIDEZ_DE_TIRA * area_casco]
        if any(en_el_borde(contorno.reshape(-1, 2)) for contorno in tiras):
            return DeteccionCinta(None, CINTA_CORTADA, completa(mascara), toca_borde=True)
        return DeteccionCinta(None, CINTA_ABIERTA if tiras else SOLO_OBJETOS, completa(mascara))

    mascara_completa = completa(mascara)
    area, contorno = marcos[0]
    vertices = _a_poligono(contorno, area)
    if len(vertices) < 3:
        return DeteccionCinta(None, SIN_CINTA, mascara_completa)
    toca_borde = en_el_borde(vertices)
    normalizados = ordenar_vertices([(float(x) / ancho_t, float(y) / alto_t) for x, y in vertices])
    poligono = tuple((min(1.0, max(0.0, x)), min(1.0, max(0.0, y))) for x, y in normalizados)
    mensaje = ES_RECTANGULO if len(poligono) == 4 else NO_ES_RECTANGULO.format(lados=len(poligono))
    return DeteccionCinta(poligono, mensaje + (TOCA_BORDE if toca_borde else ""), mascara_completa, toca_borde)
