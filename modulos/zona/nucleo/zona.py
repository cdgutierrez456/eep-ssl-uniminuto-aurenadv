"""La zona de peligro: su polígono, su margen de advertencia y cómo se mide contra ella.

La zona siempre conoce su polígono en píxeles de la imagen. Si además es un cuadrilátero con
medidas reales, lleva una homografía y entonces las distancias y el margen van en metros;
si no, todo funciona en píxeles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .geometria import (
    Punto,
    desnormalizar,
    distancia_a_poligono,
    distancia_al_borde,
    es_poligono_valido,
    punto_en_poligono,
)
from .homografia import Homografia, HomografiaInvalida, homografia_de_rectangulo


@dataclass(frozen=True)
class Medida:
    """Dónde está una persona respecto a la zona en un fotograma."""

    dentro: bool  # alguno de sus puntos de apoyo está dentro del polígono
    distancia_px: float  # del punto de apoyo más cercano al polígono; 0 si está dentro
    distancia_m: float | None = None  # lo mismo en metros; None si la zona no mide en metros


@dataclass(frozen=True)
class Zona:
    """Zona de peligro lista para medir. Se arma con ``crear_zona``."""

    zona_id: str
    poligono: tuple[Punto, ...]  # en píxeles de la imagen
    margen_px: float  # ancho de la franja de advertencia cuando se mide en píxeles
    histeresis: float = 0.2  # fracción del margen que hay que alejarse de más para bajar de nivel
    homografia: Homografia | None = None  # imagen → piso en metros
    poligono_m: tuple[Punto, ...] | None = None  # el mismo polígono sobre el piso, en metros
    margen_m: float | None = None  # ancho de la franja de advertencia en metros
    motivo_sin_metros: str | None = None  # por qué la zona mide en píxeles, para decírselo al operador

    @property
    def en_metros(self) -> bool:
        return self.homografia is not None and self.poligono_m is not None and self.margen_m is not None

    @property
    def unidad(self) -> str:
        return "m" if self.en_metros else "px"

    @property
    def margen(self) -> float:
        """Ancho de la franja de advertencia en la unidad de la zona."""
        return self.margen_m if self.en_metros else self.margen_px

    def distancia(self, medida: Medida) -> float:
        """La distancia de una medida en la unidad de la zona."""
        if self.en_metros and medida.distancia_m is not None:
            return medida.distancia_m
        return medida.distancia_px

    def medir(self, puntos: Sequence[Punto]) -> Medida:
        """Mide los puntos de apoyo de una persona (en píxeles de la imagen) contra la zona.

        Está dentro si alguno de sus puntos lo está; la distancia es la del punto más cercano.
        """
        if not puntos:
            return Medida(False, math.inf, math.inf if self.en_metros else None)
        dentro = any(punto_en_poligono(punto, self.poligono) for punto in puntos)
        distancia_px = 0.0 if dentro else min(distancia_al_borde(punto, self.poligono) for punto in puntos)
        if not self.en_metros:
            return Medida(dentro, distancia_px)
        if dentro:
            return Medida(True, 0.0, 0.0)
        distancias_m = []
        for punto in puntos:
            en_piso = self.homografia.aplicar(punto)
            # Un punto en el horizonte o más allá está, para efectos prácticos, infinitamente lejos
            distancias_m.append(math.inf if en_piso is None else distancia_a_poligono(en_piso, self.poligono_m))
        return Medida(False, distancia_px, min(distancias_m))


def crear_zona(
    zona_id: str,
    poligono_normalizado: Sequence[Sequence[float]],
    ancho_imagen: float,
    alto_imagen: float,
    *,
    margen_px: float = 80.0,
    margen_m: float = 0.5,
    rectangulo_real: Mapping[str, Any] | None = None,
    histeresis: float = 0.2,
) -> Zona:
    """Arma la zona a partir de la configuración.

    ``poligono_normalizado`` son los vértices en coordenadas de 0 a 1 sobre la imagen de
    referencia. Si la zona es un cuadrilátero y ``rectangulo_real`` trae ``ancho_m`` y
    ``largo_m`` (el lado de la primera esquina a la segunda y el de la segunda a la tercera),
    la zona mide en metros. Si no se puede, mide en píxeles y ``motivo_sin_metros`` dice por qué.

    Lanza ``ValueError`` si el polígono no sirve: menos de tres vértices o sin área (vértices
    alineados, o un cuadrilátero marcado en desorden cuyos lados se cruzan y se anulan).
    """
    if ancho_imagen <= 0 or alto_imagen <= 0:
        raise ValueError("el tamaño de la imagen debe ser mayor que cero")
    try:
        poligono = desnormalizar([(float(x), float(y)) for x, y in poligono_normalizado], ancho_imagen, alto_imagen)
    except (TypeError, ValueError):
        raise ValueError("cada vértice de la zona debe ser un par de números") from None
    if not es_poligono_valido(poligono):
        raise ValueError("la zona necesita al menos tres vértices que encierren un área "
                         "(revisa que no estén alineados ni marcados en desorden)")
    base = dict(zona_id=zona_id, poligono=poligono, margen_px=max(0.0, float(margen_px)),
                histeresis=max(0.0, float(histeresis)))

    if len(poligono) != 4:
        return Zona(**base, motivo_sin_metros="la zona no es un cuadrilátero")
    ancho_m = (rectangulo_real or {}).get("ancho_m")
    largo_m = (rectangulo_real or {}).get("largo_m")
    if not (_es_medida(ancho_m) and _es_medida(largo_m)):
        return Zona(**base, motivo_sin_metros="faltan las medidas reales del rectángulo")
    try:
        homografia = homografia_de_rectangulo(poligono, ancho_m, largo_m)
    except HomografiaInvalida as error:
        return Zona(**base, motivo_sin_metros=str(error))
    return Zona(**base, homografia=homografia, poligono_m=homografia.destino,
                margen_m=max(0.0, float(margen_m)))


def _es_medida(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor) and valor > 0
