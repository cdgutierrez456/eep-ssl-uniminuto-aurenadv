"""La zona: cómo se arma desde la configuración, cómo mide y cómo clasifica con histéresis."""

import math

import pytest

from modulos.zona.nucleo import Medida, Nivel, clasificar, crear_zona

ANCHO, ALTO = 1280, 720
# Cuadrado de (400, 300) a (800, 600) píxeles, en coordenadas normalizadas
CUADRADO = [[400 / ANCHO, 300 / ALTO], [800 / ANCHO, 300 / ALTO], [800 / ANCHO, 600 / ALTO], [400 / ANCHO, 600 / ALTO]]
TRIANGULO = [[0.3, 0.3], [0.7, 0.3], [0.5, 0.8]]


def mismos_puntos(obtenidos, esperados) -> bool:
    """Compara dos listas de puntos con tolerancia (pytest.approx no admite listas anidadas)."""
    return len(obtenidos) == len(esperados) and all(
        punto == pytest.approx(esperado) for punto, esperado in zip(obtenidos, esperados))


def zona_px(**opciones):
    return crear_zona("piso", CUADRADO, ANCHO, ALTO, margen_px=80, **opciones)


def zona_m(**opciones):
    # 400 x 300 píxeles para 2 x 1,5 metros: 200 píxeles por metro
    return crear_zona("piso", CUADRADO, ANCHO, ALTO, margen_px=80, margen_m=0.5,
                      rectangulo_real={"ancho_m": 2.0, "largo_m": 1.5}, **opciones)


# ----------------------------------------------------------------------- armado
def test_el_poligono_normalizado_pasa_a_pixeles():
    assert mismos_puntos(zona_px().poligono, [(400, 300), (800, 300), (800, 600), (400, 600)])


def test_sin_medidas_reales_la_zona_mide_en_pixeles():
    zona = zona_px()
    assert not zona.en_metros
    assert zona.unidad == "px" and zona.margen == 80
    assert "medidas" in zona.motivo_sin_metros


def test_con_cuadrilatero_y_medidas_la_zona_mide_en_metros():
    zona = zona_m()
    assert zona.en_metros
    assert zona.unidad == "m" and zona.margen == 0.5
    assert zona.motivo_sin_metros is None
    assert mismos_puntos(zona.poligono_m, [(0, 0), (2.0, 0), (2.0, 1.5), (0, 1.5)])


def test_una_zona_que_no_es_cuadrilatero_mide_en_pixeles_aunque_tenga_medidas():
    zona = crear_zona("piso", TRIANGULO, ANCHO, ALTO, rectangulo_real={"ancho_m": 2.0, "largo_m": 1.5})
    assert not zona.en_metros
    assert "cuadrilátero" in zona.motivo_sin_metros


@pytest.mark.parametrize("rectangulo", [
    {"ancho_m": 2.0}, {"ancho_m": 0, "largo_m": 1.5}, {"ancho_m": "2", "largo_m": 1.5}, {"ancho_m": True, "largo_m": 1.5},
])
def test_medidas_incompletas_o_invalidas_dejan_la_zona_en_pixeles(rectangulo):
    assert not crear_zona("piso", CUADRADO, ANCHO, ALTO, rectangulo_real=rectangulo).en_metros


def test_un_cuadrilatero_con_los_lados_cruzados_mide_en_pixeles_y_dice_por_que():
    cruzado = [[0.3, 0.3], [0.7, 0.8], [0.9, 0.4], [0.2, 0.7]]   # vértices marcados en desorden
    zona = crear_zona("piso", cruzado, ANCHO, ALTO, rectangulo_real={"ancho_m": 2.0, "largo_m": 1.5})
    assert not zona.en_metros
    assert "cruzan" in zona.motivo_sin_metros


@pytest.mark.parametrize("poligono", [
    [],
    [[0.1, 0.1], [0.5, 0.5]],                                    # dos vértices
    [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]],                        # alineados
    [[0.1], [0.2], [0.3]],                                       # vértices que no son pares
    [CUADRADO[0], CUADRADO[2], CUADRADO[1], CUADRADO[3]],        # un moño simétrico: no encierra área
], ids=["vacio", "dos_vertices", "alineados", "sin_pares", "mono"])
def test_un_poligono_que_no_sirve_se_rechaza(poligono):
    with pytest.raises(ValueError):
        crear_zona("piso", poligono, ANCHO, ALTO)


# ----------------------------------------------------------------------- medida
def test_medida_en_pixeles():
    zona = zona_px()
    assert zona.medir([(600, 450)]) == Medida(True, 0.0)
    assert zona.medir([(350, 450)]) == Medida(False, pytest.approx(50.0))
    assert zona.medir([(850, 640)]) == Medida(False, pytest.approx(math.hypot(50, 40)))  # frente a una esquina


def test_con_dos_pies_basta_uno_dentro_y_cuenta_el_mas_cercano():
    zona = zona_px()
    assert zona.medir([(350, 450), (410, 450)]).dentro  # un pie fuera y el otro dentro
    assert zona.medir([(300, 450), (360, 450)]).distancia_px == pytest.approx(40.0)


def test_medida_en_metros():
    zona = zona_m()
    medida = zona.medir([(300, 450)])  # 100 píxeles a la izquierda: medio metro
    assert not medida.dentro
    assert medida.distancia_px == pytest.approx(100.0)
    assert medida.distancia_m == pytest.approx(0.5)
    assert zona.distancia(medida) == pytest.approx(0.5)
    assert zona.medir([(600, 450)]) == Medida(True, 0.0, 0.0)


def test_sin_puntos_de_apoyo_la_persona_esta_infinitamente_lejos():
    assert zona_px().medir([]) == Medida(False, math.inf)
    assert zona_m().medir([]).distancia_m == math.inf


# ---------------------------------------------------------------- clasificación
def a_la_izquierda(distancia_px: float) -> list[tuple[float, float]]:
    """Un pie a ``distancia_px`` del lado izquierdo de la zona, por fuera."""
    return [(400 - distancia_px, 450)]


@pytest.mark.parametrize("confirmado, distancia_px, esperado", [
    # Viniendo de libre: entra a advertencia al cruzar el margen (80)
    (Nivel.LIBRE, 81, Nivel.LIBRE),
    (Nivel.LIBRE, 79, Nivel.ADVERTENCIA),
    # Ya en advertencia: la conserva hasta alejarse 20 % más (96)
    (Nivel.ADVERTENCIA, 90, Nivel.ADVERTENCIA),
    (Nivel.ADVERTENCIA, 97, Nivel.LIBRE),
    # Ya en peligro: lo conserva hasta alejarse del borde 20 % del margen (16)
    (Nivel.PELIGRO, 10, Nivel.PELIGRO),
    (Nivel.PELIGRO, 17, Nivel.ADVERTENCIA),
    (Nivel.PELIGRO, 90, Nivel.ADVERTENCIA),
    (Nivel.PELIGRO, 97, Nivel.LIBRE),
    # Sin estar en peligro, quedarse pegado al borde por fuera es advertencia
    (Nivel.ADVERTENCIA, 10, Nivel.ADVERTENCIA),
    (Nivel.LIBRE, 10, Nivel.ADVERTENCIA),
])
def test_clasificacion_con_histeresis_en_pixeles(confirmado, distancia_px, esperado):
    zona = zona_px(histeresis=0.2)
    assert clasificar(zona.medir(a_la_izquierda(distancia_px)), zona, confirmado) is esperado


@pytest.mark.parametrize("confirmado", list(Nivel))
def test_un_pie_dentro_siempre_es_peligro(confirmado):
    zona = zona_px()
    assert clasificar(zona.medir([(600, 450)]), zona, confirmado) is Nivel.PELIGRO


@pytest.mark.parametrize("confirmado, distancia_m, esperado", [
    (Nivel.LIBRE, 0.51, Nivel.LIBRE),
    (Nivel.LIBRE, 0.49, Nivel.ADVERTENCIA),
    (Nivel.ADVERTENCIA, 0.59, Nivel.ADVERTENCIA),   # hasta 0,5 × 1,2 = 0,6 m
    (Nivel.ADVERTENCIA, 0.61, Nivel.LIBRE),
    (Nivel.PELIGRO, 0.09, Nivel.PELIGRO),           # hasta 0,5 × 0,2 = 0,1 m
    (Nivel.PELIGRO, 0.11, Nivel.ADVERTENCIA),
])
def test_clasificacion_con_histeresis_en_metros(confirmado, distancia_m, esperado):
    zona = zona_m(histeresis=0.2)
    assert clasificar(zona.medir(a_la_izquierda(distancia_m * 200)), zona, confirmado) is esperado


def test_en_metros_el_margen_en_pixeles_no_cuenta():
    # A 90 píxeles (0,45 m): fuera del margen de 80 px, pero dentro del de 0,5 m
    zona = zona_m()
    assert clasificar(zona.medir(a_la_izquierda(90)), zona, Nivel.LIBRE) is Nivel.ADVERTENCIA


def test_sin_histeresis_los_limites_son_los_mismos_al_subir_y_al_bajar():
    zona = zona_px(histeresis=0.0)
    assert clasificar(zona.medir(a_la_izquierda(81)), zona, Nivel.ADVERTENCIA) is Nivel.LIBRE
    assert clasificar(zona.medir(a_la_izquierda(1)), zona, Nivel.PELIGRO) is Nivel.ADVERTENCIA


def test_los_niveles_se_ordenan_y_se_nombran_como_en_los_eventos():
    assert Nivel.LIBRE < Nivel.ADVERTENCIA < Nivel.PELIGRO
    assert [nivel.nombre for nivel in Nivel] == ["libre", "advertencia", "peligro"]
