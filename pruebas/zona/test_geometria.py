"""Geometría del módulo de zona: casos con resultado conocido."""

import pytest

from modulos.zona.nucleo.geometria import (
    area,
    area_con_signo,
    desnormalizar,
    distancia_a_poligono,
    distancia_a_segmento,
    distancia_al_borde,
    es_convexo,
    es_poligono_valido,
    normalizar,
    punto_en_poligono,
)

CUADRADO = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
# Una L: el cuadrado de 10 sin su cuarto de x > 5, y > 5
ELE = ((0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (5.0, 5.0), (5.0, 10.0), (0.0, 10.0))
MONO = ((0.0, 0.0), (10.0, 10.0), (10.0, 0.0), (0.0, 10.0))  # se cruza a sí mismo


@pytest.mark.parametrize("punto, esperado", [
    ((5.0, 5.0), True),      # centro
    ((0.1, 9.9), True),      # cerca de una esquina, por dentro
    ((11.0, 5.0), False),    # a la derecha
    ((-0.1, 5.0), False),    # a la izquierda
    ((5.0, -3.0), False),    # arriba
    ((10.0, 5.0), True),     # sobre un lado: el borde cuenta como dentro
    ((0.0, 0.0), True),      # sobre un vértice
    ((15.0, 10.0), False),   # a la altura de un lado horizontal, pero fuera
    ((-1.0, 0.0), False),    # alineado con el lado de arriba, fuera
])
def test_punto_en_cuadrado(punto, esperado):
    assert punto_en_poligono(punto, CUADRADO) is esperado


@pytest.mark.parametrize("punto, esperado", [
    ((2.0, 8.0), True),      # brazo vertical de la L
    ((8.0, 2.0), True),      # brazo horizontal
    ((8.0, 8.0), False),     # el entrante: dentro del cuadrado que la rodea, fuera de la L
    ((5.0, 7.0), True),      # sobre el lado interior
    ((2.0, 5.0), True),      # dentro, a la altura exacta del lado horizontal interior
    ((-3.0, 5.0), False),    # fuera, a esa misma altura (la semirrecta roza un lado y un vértice)
    ((12.0, 5.0), False),
])
def test_punto_en_poligono_con_entrante(punto, esperado):
    assert punto_en_poligono(punto, ELE) is esperado


def test_el_sentido_de_los_vertices_no_cambia_el_resultado():
    al_reves = tuple(reversed(ELE))
    for punto in [(2.0, 8.0), (8.0, 8.0), (8.0, 2.0), (-3.0, 5.0)]:
        assert punto_en_poligono(punto, al_reves) is punto_en_poligono(punto, ELE)


def test_menos_de_tres_vertices_no_encierran_nada():
    assert punto_en_poligono((0.0, 0.0), ((0.0, 0.0), (1.0, 1.0))) is False


@pytest.mark.parametrize("punto, a, b, esperado", [
    ((5.0, 3.0), (0.0, 0.0), (10.0, 0.0), 3.0),     # la perpendicular cae dentro del segmento
    ((13.0, 4.0), (0.0, 0.0), (10.0, 0.0), 5.0),    # más allá del extremo: distancia al extremo (3-4-5)
    ((-3.0, -4.0), (0.0, 0.0), (10.0, 0.0), 5.0),   # antes del otro extremo
    ((4.0, 0.0), (0.0, 0.0), (10.0, 0.0), 0.0),     # sobre el segmento
    ((3.0, 4.0), (0.0, 0.0), (0.0, 0.0), 5.0),      # segmento reducido a un punto
])
def test_distancia_a_segmento(punto, a, b, esperado):
    assert distancia_a_segmento(punto, a, b) == pytest.approx(esperado)


@pytest.mark.parametrize("punto, esperado", [
    ((5.0, 5.0), 0.0),       # dentro
    ((10.0, 5.0), 0.0),      # en el borde
    ((13.0, 5.0), 3.0),      # frente a un lado
    ((13.0, 14.0), 5.0),     # frente a una esquina (3-4-5)
    ((5.0, -2.5), 2.5),
])
def test_distancia_a_cuadrado(punto, esperado):
    assert distancia_a_poligono(punto, CUADRADO) == pytest.approx(esperado)


def test_distancia_dentro_del_entrante_de_la_ele():
    # (8, 8) está a 3 de los dos lados interiores de la L
    assert distancia_a_poligono((8.0, 8.0), ELE) == pytest.approx(3.0)
    assert distancia_a_poligono((9.0, 6.0), ELE) == pytest.approx(1.0)


def test_distancia_al_borde_tambien_mide_desde_dentro():
    assert distancia_al_borde((5.0, 5.0), CUADRADO) == pytest.approx(5.0)
    assert distancia_al_borde((1.0, 5.0), CUADRADO) == pytest.approx(1.0)


def test_area():
    assert area(CUADRADO) == pytest.approx(100.0)
    assert area(ELE) == pytest.approx(75.0)
    assert area_con_signo(tuple(reversed(CUADRADO))) == pytest.approx(-area_con_signo(CUADRADO))


def test_poligono_valido():
    assert es_poligono_valido(CUADRADO)
    assert not es_poligono_valido(((0.0, 0.0), (1.0, 1.0)))                 # dos vértices
    assert not es_poligono_valido(((0.0, 0.0), (1.0, 1.0), (2.0, 2.0)))     # alineados


def test_convexidad():
    assert es_convexo(CUADRADO)
    assert es_convexo(tuple(reversed(CUADRADO)))
    assert es_convexo(((400.0, 300.0), (880.0, 300.0), (1000.0, 620.0), (280.0, 620.0)))  # trapecio
    assert not es_convexo(ELE)
    assert not es_convexo(MONO)
    assert not es_convexo(((0.0, 0.0), (10.0, 0.0), (3.0, 3.0), (0.0, 10.0)))  # un vértice hundido


def test_normalizar_y_desnormalizar_son_inversas():
    normalizado = ((0.25, 0.5), (0.75, 0.5), (0.5, 1.0))
    en_pixeles = desnormalizar(normalizado, 1280, 720)
    assert en_pixeles == ((320.0, 360.0), (960.0, 360.0), (640.0, 720.0))
    for obtenido, esperado in zip(normalizar(en_pixeles, 1280, 720), normalizado, strict=True):
        assert obtenido == pytest.approx(esperado)
