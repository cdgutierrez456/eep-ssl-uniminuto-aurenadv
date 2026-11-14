"""Editor de polígono con el mouse. Solo la lógica: sin ventana, se prueba con clics simulados.

Trabaja en píxeles de la imagen de la cámara y entrega el polígono normalizado (0 a 1), que
es como viaja en la configuración. Uso desde una ventana de OpenCV::

    editor = EditorPoligono(ancho, alto)
    editor.presionar(x, y)   # botón izquierdo abajo: agarra un vértice o crea uno
    editor.mover(x, y)       # el mouse se mueve con el botón abajo
    editor.soltar()          # botón izquierdo arriba
    editor.borrar(x, y)      # botón derecho: quita el vértice que esté ahí
"""

from __future__ import annotations

import math
from typing import Sequence

from ..nucleo.geometria import Punto, desnormalizar, distancia_a_segmento, es_poligono_valido

RADIO_DE_AGARRE = 16.0  # píxeles de la imagen alrededor de un vértice en los que un clic lo agarra
MAXIMO_DE_VERTICES = 64


class EditorPoligono:
    """Un polígono que se arma y se corrige a clics."""

    def __init__(self, ancho: int, alto: int, poligono_normalizado: Sequence[Sequence[float]] | None = None,
                 radio: float = RADIO_DE_AGARRE) -> None:
        self.ancho, self.alto = ancho, alto
        self.radio = radio
        self.vertices: list[Punto] = []
        self.agarrado: int | None = None  # índice del vértice que se está arrastrando
        self.modificado = False  # cambió desde que se cargó
        if poligono_normalizado:
            self.cargar(poligono_normalizado)

    # ------------------------------------------------------------------ #
    def cargar(self, poligono_normalizado: Sequence[Sequence[float]] | None) -> None:
        """Reemplaza los vértices por los de un polígono normalizado (None lo deja vacío)."""
        self.vertices = [self._dentro(x, y) for x, y in desnormalizar(poligono_normalizado or (), self.ancho, self.alto)]
        self.agarrado = None
        self.modificado = False

    def limpiar(self) -> None:
        """Quita todos los vértices para empezar de cero."""
        self.modificado = self.modificado or bool(self.vertices)
        self.vertices = []
        self.agarrado = None

    def redimensionar(self, ancho: int, alto: int) -> None:
        """La imagen cambió de tamaño: los vértices conservan su lugar relativo."""
        if (ancho, alto) == (self.ancho, self.alto):
            return
        normalizado = self.normalizado()
        self.ancho, self.alto = ancho, alto
        self.vertices = [self._dentro(x, y) for x, y in desnormalizar(normalizado, ancho, alto)]

    def normalizado(self) -> list[list[float]]:
        """Los vértices en coordenadas de 0 a 1 sobre la imagen, como van en la configuración."""
        return [[round(x / self.ancho, 5), round(y / self.alto, 5)] for x, y in self.vertices]

    @property
    def valido(self) -> bool:
        """True si ya es una zona que se puede guardar: al menos tres vértices que encierran un área."""
        return es_poligono_valido(self.vertices)

    @property
    def es_cuadrilatero(self) -> bool:
        return len(self.vertices) == 4

    # ------------------------------------------------------------------ #
    def vertice_en(self, x: float, y: float) -> int | None:
        """Índice del vértice más cercano a (x, y) dentro del radio de agarre, o None."""
        if not self.vertices:
            return None
        indice = min(range(len(self.vertices)), key=lambda i: math.dist(self.vertices[i], (x, y)))
        return indice if math.dist(self.vertices[indice], (x, y)) <= self.radio else None

    def presionar(self, x: float, y: float) -> int | None:
        """Clic izquierdo: agarra el vértice que esté ahí; si no hay, crea uno y lo deja agarrado.

        Con menos de tres vértices el nuevo va al final. Con tres o más se inserta en el lado
        más cercano al clic, así el polígono no se cruza. Devuelve el índice agarrado.
        """
        punto = self._dentro(x, y)
        indice = self.vertice_en(*punto)
        if indice is None:
            if len(self.vertices) >= MAXIMO_DE_VERTICES:
                return None
            indice = self._lugar_para(punto)
            self.vertices.insert(indice, punto)
            self.modificado = True
        self.agarrado = indice
        return indice

    def mover(self, x: float, y: float) -> bool:
        """Arrastra el vértice agarrado hasta (x, y). Devuelve si movió algo."""
        if self.agarrado is None:
            return False
        self.vertices[self.agarrado] = self._dentro(x, y)
        self.modificado = True
        return True

    def soltar(self) -> None:
        self.agarrado = None

    def borrar(self, x: float, y: float) -> bool:
        """Clic derecho: quita el vértice que esté en (x, y). Devuelve si quitó alguno."""
        indice = self.vertice_en(x, y)
        if indice is None:
            return False
        del self.vertices[indice]
        self.agarrado = None
        self.modificado = True
        return True

    # ------------------------------------------------------------------ #
    def _dentro(self, x: float, y: float) -> Punto:
        """El punto, recortado a la imagen."""
        return (min(float(self.ancho - 1), max(0.0, float(x))), min(float(self.alto - 1), max(0.0, float(y))))

    def _lugar_para(self, punto: Punto) -> int:
        """Posición donde insertar un vértice nuevo: después del primer extremo del lado más cercano."""
        cantidad = len(self.vertices)
        if cantidad < 3:
            return cantidad
        lado = min(range(cantidad),
                   key=lambda i: distancia_a_segmento(punto, self.vertices[i], self.vertices[(i + 1) % cantidad]))
        return lado + 1
