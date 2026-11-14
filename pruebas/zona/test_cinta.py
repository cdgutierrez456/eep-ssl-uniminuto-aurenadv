"""Detección de la cinta sobre escenas sintéticas: franjas, perspectiva, ruido y objetos que distraen."""

import math

import numpy as np
import pytest

from modulos.zona.calibracion.cinta import (
    CINTA_ABIERTA,
    CINTA_CORTADA,
    SIN_CINTA,
    SOLO_OBJETOS,
    RangoHSV,
    detectar_cinta,
    mascara_de_amarillo,
    ordenar_vertices,
)
from modulos.zona.calibracion.vista import imagen_de_diagnostico
from modulos.zona.nucleo.geometria import area_con_signo

from .escenas import crear_escena


def en_pixeles(deteccion, imagen):
    alto, ancho = imagen.shape[:2]
    return [(x * ancho, y * alto) for x, y in deteccion.poligono]


def error_maximo(escena, deteccion) -> float:
    """Mayor distancia, en píxeles, entre una esquina real de la cinta y el vértice detectado más cercano."""
    vertices = en_pixeles(deteccion, escena.imagen)
    return max(min(math.dist(esquina, vertice) for vertice in vertices) for esquina in escena.esquinas)


# ------------------------------------------------------------------ la encuentra
def test_encuentra_el_rectangulo_con_franjas_perspectiva_ruido_y_un_objeto_amarillo():
    escena = crear_escena()  # el caso de la demo: cinta amarilla y negra, piso beige, ruido y un objeto amarillo
    deteccion = detectar_cinta(escena.imagen)

    assert deteccion.encontrada and deteccion.es_cuadrilatero
    assert not deteccion.toca_borde
    assert "rectángulo" in deteccion.mensaje
    assert error_maximo(escena, deteccion) <= 8   # píxeles, en una imagen de 1280 de ancho


@pytest.mark.parametrize("opciones", [
    dict(giro=25, semilla=1),                            # zona girada respecto a la cámara
    dict(giro=-40, semilla=2),
    dict(ruido=18, semilla=3),                           # cámara con mucho ruido
    dict(franjas=False),                                 # cinta amarilla lisa
    dict(maquina=True, semilla=4),                       # con la caja de la máquina dentro
    dict(altura=2.6, inclinacion=62, semilla=5),         # cámara más alta y más inclinada
    dict(rectangulo=(2.0, 1.2), semilla=6),              # zona más grande
    dict(distractor=None, semilla=7),                    # sin nada que distraiga
    dict(ancho=1920, alto=1080, semilla=8),              # otra resolución
    dict(ancho=640, alto=360, ruido=5, semilla=9),
    dict(altura=1.5, distancia=0.9, inclinacion=48, rectangulo=(1.2, 0.8), distractor=None, semilla=10),
], ids=["girada_25", "girada_-40", "ruido_alto", "cinta_lisa", "con_maquina", "camara_alta", "zona_grande",
        "sin_distractor", "1080p", "360p", "camara_cercana"])
def test_encuentra_el_rectangulo_en_condiciones_distintas(opciones):
    escena = crear_escena(**opciones)
    deteccion = detectar_cinta(escena.imagen)
    assert deteccion.es_cuadrilatero, deteccion.mensaje
    assert error_maximo(escena, deteccion) <= 0.008 * escena.imagen.shape[1]   # menos del 1 % del ancho


def test_un_objeto_amarillo_mas_grande_que_la_zona_no_la_reemplaza():
    # La zona es pequeña y al lado hay una lona amarilla bastante más grande: gana el marco hueco
    escena = crear_escena(rectangulo=(0.9, 0.6), distractor=(1.3, -0.2, 1.3), semilla=5)
    deteccion = detectar_cinta(escena.imagen)
    assert deteccion.es_cuadrilatero
    assert error_maximo(escena, deteccion) <= 8


def test_los_vertices_salen_en_sentido_horario_desde_arriba_a_la_izquierda():
    escena = crear_escena()
    primero, segundo, tercero, cuarto = en_pixeles(detectar_cinta(escena.imagen), escena.imagen)
    assert area_con_signo([primero, segundo, tercero, cuarto]) > 0     # horario en la imagen (y hacia abajo)
    assert primero[0] < segundo[0] and cuarto[0] < tercero[0]          # 1 y 4 a la izquierda
    assert max(primero[1], segundo[1]) < min(tercero[1], cuarto[1])    # el lado 1-2 es el de arriba (el lejano)


def test_ordenar_vertices_no_depende_del_orden_de_entrada():
    cuadrado = [(10.0, 10.0), (90.0, 12.0), (95.0, 80.0), (5.0, 85.0)]
    for inicio in range(4):
        girado = cuadrado[inicio:] + cuadrado[:inicio]
        assert ordenar_vertices(girado) == cuadrado
        assert ordenar_vertices(list(reversed(girado))) == cuadrado


# ---------------------------------------------------------------- no la encuentra
def test_sin_cinta_lo_dice_claramente_y_sugiere_marcarla_a_mano():
    escena = crear_escena(con_cinta=False, distractor=None)
    deteccion = detectar_cinta(escena.imagen)
    assert not deteccion.encontrada and deteccion.poligono is None
    assert deteccion.mensaje == SIN_CINTA
    assert "No se encontró la cinta" in deteccion.mensaje and "a mano" in deteccion.mensaje


@pytest.mark.parametrize("distractor", [(1.8, 0.1, 0.5), (2.2, 0.1, 0.6)], ids=["entero", "cortado_por_el_borde"])
def test_un_objeto_amarillo_solo_no_es_una_zona(distractor):
    escena = crear_escena(con_cinta=False, distractor=distractor)   # solo el objeto macizo
    deteccion = detectar_cinta(escena.imagen)
    assert not deteccion.encontrada
    assert deteccion.mensaje == SOLO_OBJETOS


def test_el_piso_beige_no_se_confunde_con_la_cinta_ni_con_mucho_ruido():
    escena = crear_escena(con_cinta=False, distractor=None, ruido=20, semilla=11)
    deteccion = detectar_cinta(escena.imagen)
    assert not deteccion.encontrada
    assert np.count_nonzero(deteccion.mascara) < 0.001 * deteccion.mascara.size


def test_con_otro_rango_de_color_la_cinta_amarilla_no_aparece():
    escena = crear_escena()
    azul = RangoHSV.desde_config({"h_min": 100, "h_max": 130, "s_min": 80, "v_min": 80})
    assert not detectar_cinta(escena.imagen, azul).encontrada
    assert RangoHSV.desde_config(None) == RangoHSV() == RangoHSV.desde_config({})


# ------------------------------------------------------------------------ avisos
def test_avisa_si_la_zona_se_sale_de_la_imagen():
    escena = crear_escena(rectangulo=(4.0, 1.0), distractor=None)   # tan ancha que la cámara no la ve entera
    deteccion = detectar_cinta(escena.imagen)
    assert not deteccion.encontrada and deteccion.toca_borde
    assert deteccion.mensaje == CINTA_CORTADA
    assert "se sale de la imagen" in deteccion.mensaje


def test_avisa_si_la_cinta_no_cierra_la_figura():
    escena = crear_escena(distractor=None)
    # Algo tapa un tramo de 30 cm del lado cercano: el marco queda abierto
    (x0, y0), (x1, _) = escena.esquinas[0], escena.esquinas[1]
    medio = round((x0 + x1) / 2)
    escena.imagen[round(y0) - 40:round(y0) + 20, medio - 60:medio + 60] = (170, 200, 220)
    deteccion = detectar_cinta(escena.imagen)
    assert not deteccion.encontrada and not deteccion.toca_borde
    assert deteccion.mensaje == CINTA_ABIERTA


def test_una_figura_que_no_es_rectangulo_se_propone_pero_avisa():
    # Dos escenas pegadas dan una cinta en forma de L vista de frente: seis lados
    imagen = np.full((720, 1280, 3), (170, 200, 220), dtype=np.uint8)
    ele = np.array([(300, 150), (900, 150), (900, 350), (600, 350), (600, 600), (300, 600)], dtype=np.int32)
    import cv2
    cv2.polylines(imagen, [ele], True, (25, 200, 240), 14)
    deteccion = detectar_cinta(imagen)
    assert deteccion.encontrada and not deteccion.es_cuadrilatero
    assert len(deteccion.poligono) == 6
    assert "6 lados" in deteccion.mensaje


# ----------------------------------------------------------------------- máscara
def test_la_mascara_es_binaria_del_tamano_de_la_imagen_y_marca_la_cinta():
    escena = crear_escena(distractor=None)
    deteccion = detectar_cinta(escena.imagen)
    assert deteccion.mascara.shape == escena.imagen.shape[:2]
    assert set(np.unique(deteccion.mascara)) <= {0, 255}
    (x0, y0), (x1, y1) = escena.esquinas[0], escena.esquinas[1]
    sobre_la_cinta = (round((x0 + x1) / 2), round((y0 + y1) / 2) - 4)   # mitad del lado cercano, un poco adentro
    centro_de_la_zona = tuple(round(sum(c) / 4) for c in zip(*escena.esquinas))
    assert deteccion.mascara[sobre_la_cinta[1], sobre_la_cinta[0]] == 255
    assert deteccion.mascara[centro_de_la_zona[1], centro_de_la_zona[0]] == 0   # el interior es piso


def test_el_cierre_une_las_franjas_amarillas_y_negras():
    escena = crear_escena(distractor=None, ruido=0)
    mascara = mascara_de_amarillo(escena.imagen, RangoHSV())
    import cv2
    cantidad, _ = cv2.connectedComponents(mascara)
    assert cantidad == 2   # el fondo y una sola pieza: el marco completo, sin cortes


def test_imagen_de_diagnostico_muestra_la_imagen_y_la_mascara_lado_a_lado():
    escena = crear_escena()
    diagnostico = imagen_de_diagnostico(escena.imagen, detectar_cinta(escena.imagen))
    assert diagnostico.shape == (360 + 44, 1280, 3)
    sin_cinta = crear_escena(con_cinta=False, distractor=None)
    assert imagen_de_diagnostico(sin_cinta.imagen, detectar_cinta(sin_cinta.imagen)).shape == (360 + 44, 1280, 3)
