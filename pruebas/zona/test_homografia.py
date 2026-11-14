"""Homografía imagen → piso contra una cámara simulada de la que se conoce todo."""

import math

import numpy as np
import pytest

from modulos.zona.nucleo.geometria import distancia_a_poligono
from modulos.zona.nucleo.homografia import HomografiaInvalida, homografia_de_rectangulo, homografia_entre

ANCHO_M, LARGO_M = 1.5, 1.0
RECTANGULO = ((0.0, 0.0), (ANCHO_M, 0.0), (ANCHO_M, LARGO_M), (0.0, LARGO_M))

# Cámara simulada: a 2 m de altura, 1,5 m antes del rectángulo, inclinada 50° hacia abajo
POSICION = np.array([0.75, -1.5, 2.0])
INCLINACION = math.radians(50)
FOCAL, CENTRO_X, CENTRO_Y = 900.0, 640.0, 360.0
ROTACION = np.array([
    [1.0, 0.0, 0.0],                                            # derecha de la cámara
    [0.0, -math.sin(INCLINACION), -math.cos(INCLINACION)],      # abajo de la cámara
    [0.0, math.cos(INCLINACION), -math.sin(INCLINACION)],       # hacia donde mira
])


def proyectar(x_m: float, y_m: float) -> tuple[float, float]:
    """Píxel donde la cámara simulada ve el punto del piso (x_m, y_m). Independiente del módulo."""
    x, y, z = ROTACION @ (np.array([x_m, y_m, 0.0]) - POSICION)
    assert z > 0, "el punto queda detrás de la cámara"
    return (FOCAL * x / z + CENTRO_X, FOCAL * y / z + CENTRO_Y)


ESQUINAS = tuple(proyectar(x, y) for x, y in RECTANGULO)


@pytest.fixture
def homografia():
    return homografia_de_rectangulo(ESQUINAS, ANCHO_M, LARGO_M)


def test_la_camara_simulada_ve_el_rectangulo_en_perspectiva():
    # El lado lejano se ve más corto que el cercano: no es una simple escala
    cercano = math.dist(ESQUINAS[0], ESQUINAS[1])
    lejano = math.dist(ESQUINAS[3], ESQUINAS[2])
    assert lejano < 0.85 * cercano
    assert all(0 <= x <= 1280 and 0 <= y <= 720 for x, y in ESQUINAS)


def test_las_esquinas_van_a_las_medidas_reales(homografia):
    for esquina, real in zip(ESQUINAS, RECTANGULO):
        assert homografia.aplicar(esquina) == pytest.approx(real, abs=1e-6)


@pytest.mark.parametrize("punto_real", [
    (0.75, 0.5),     # centro del rectángulo
    (0.3, 0.9),      # dentro
    (-0.5, 0.5),     # medio metro a la izquierda
    (2.0, 1.3),      # fuera, a la derecha y al fondo
    (0.75, -0.4),    # delante, hacia la cámara
    (-1.0, 2.5),     # lejos
])
def test_recupera_la_posicion_en_metros_de_cualquier_punto_del_piso(homografia, punto_real):
    assert homografia.aplicar(proyectar(*punto_real)) == pytest.approx(punto_real, abs=1e-6)


def test_mide_distancias_al_rectangulo_en_metros(homografia):
    casos = {(-0.5, 0.5): 0.5, (0.75, -0.4): 0.4, (1.8, 1.4): 0.5, (0.75, 0.5): 0.0}  # (1,8; 1,4): 3-4-5
    for punto_real, distancia in casos.items():
        en_piso = homografia.aplicar(proyectar(*punto_real))
        assert distancia_a_poligono(en_piso, homografia.destino) == pytest.approx(distancia, abs=1e-6)


def test_la_inversa_devuelve_a_la_imagen(homografia):
    inversa = homografia.inversa()
    for punto_real in [(0.75, 0.5), (-0.5, 0.5), (2.0, 1.3)]:
        assert inversa.aplicar(punto_real) == pytest.approx(proyectar(*punto_real), abs=1e-4)


def test_el_primer_lado_es_el_ancho_y_el_segundo_el_largo(homografia):
    assert homografia.aplicar(ESQUINAS[1]) == pytest.approx((ANCHO_M, 0.0), abs=1e-6)
    assert homografia.aplicar(ESQUINAS[3]) == pytest.approx((0.0, LARGO_M), abs=1e-6)
    # Empezar por otra esquina gira el sistema de coordenadas, pero las distancias son las mismas
    girada = homografia_de_rectangulo(ESQUINAS[1:] + ESQUINAS[:1], LARGO_M, ANCHO_M)
    a, b = proyectar(-0.5, 0.5), proyectar(0.75, 0.5)
    assert math.dist(girada.aplicar(a), girada.aplicar(b)) == pytest.approx(1.25, abs=1e-6)


def test_un_rectangulo_visto_de_frente_es_una_escala():
    # 400 x 300 píxeles para 2 x 1,5 metros: 200 píxeles por metro
    cuadrilatero = ((400.0, 300.0), (800.0, 300.0), (800.0, 600.0), (400.0, 600.0))
    homografia = homografia_de_rectangulo(cuadrilatero, 2.0, 1.5)
    assert homografia.aplicar((600.0, 450.0)) == pytest.approx((1.0, 0.75))
    assert homografia.aplicar((300.0, 450.0)) == pytest.approx((-0.5, 0.75))


def test_mas_alla_del_horizonte_no_hay_piso(homografia):
    # Con la cámara inclinada 50°, el horizonte queda muy por encima del borde de la imagen
    horizonte_y = CENTRO_Y - FOCAL * math.tan(INCLINACION)
    assert homografia.aplicar((640.0, horizonte_y - 50)) is None
    assert homografia.aplicar((640.0, horizonte_y + 50)) is not None


@pytest.mark.parametrize("cuadrilatero, ancho, largo", [
    (ESQUINAS[:3], ANCHO_M, LARGO_M),                                          # tres vértices
    (ESQUINAS, 0.0, LARGO_M),                                                  # medida nula
    (ESQUINAS, ANCHO_M, -1.0),                                                 # medida negativa
    (((0.0, 0.0), (10.0, 10.0), (10.0, 0.0), (0.0, 10.0)), 1.0, 1.0),          # lados cruzados
    (((0.0, 0.0), (10.0, 0.0), (3.0, 3.0), (0.0, 10.0)), 1.0, 1.0),            # vértice hundido
    (((0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (0.0, 10.0)), 1.0, 1.0),            # tres vértices alineados
    (((0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)), 1.0, 1.0),              # todos el mismo punto
], ids=["tres_vertices", "ancho_cero", "largo_negativo", "cruzado", "hundido", "alineados", "un_punto"])
def test_rechaza_lo_que_no_puede_ser_un_rectangulo(cuadrilatero, ancho, largo):
    with pytest.raises(HomografiaInvalida):
        homografia_de_rectangulo(cuadrilatero, ancho, largo)


def test_homografia_entre_exige_cuatro_puntos():
    with pytest.raises(HomografiaInvalida):
        homografia_entre(ESQUINAS[:3], RECTANGULO[:3])
