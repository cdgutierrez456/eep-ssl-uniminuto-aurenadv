"""Postura neutra por persona: calibración de pie y ángulos medidos desde ahí."""

import numpy as np
import pytest

from modulos.ergonomia.config import validar_config
from modulos.ergonomia.estacion import Analizador
from modulos.ergonomia.nucleo.angulos import calcular_angulos, correccion_de_tronco
from modulos.ergonomia.nucleo.neutra import LIMITE_CUELLO, LIMITE_TRONCO, PosturaNeutra

from .test_angulos import APROX, postura
from .test_vista import EstimadorFijo

FPS = 30
FRAME = np.zeros((720, 1280, 3), np.uint8)
CONFIG = validar_config({})
# Lo que la cámara mide con una persona de pie y derecha (visto en las pruebas en vivo)
DE_PIE_REAL = dict(tronco=-11, cuello=30, rodilla=3, brazo=-12, codo=20)


def alimentar(neutra, tronco, cuello, rodilla, segundos, desde=0.0, ruido=0.0):
    calibro = False
    for i in range(round(segundos * FPS)):
        vaiven = ruido if i % 2 else -ruido
        calibro = neutra.actualizar(desde + i / FPS, tronco + vaiven, cuello, rodilla) or calibro
    return calibro


def test_calibra_tras_estar_quieto_de_pie():
    neutra = PosturaNeutra()
    assert not alimentar(neutra, -11, 30, 3, 0.5) and not neutra.calibrada
    assert alimentar(neutra, -11, 30, 3, 0.5, desde=0.5)
    assert neutra.calibrada and (neutra.tronco, neutra.cuello) == (-11, 30)


def test_usa_la_mediana_y_tolera_un_poco_de_temblor():
    neutra = PosturaNeutra()
    assert alimentar(neutra, -10, 28, 5, 1.0, ruido=1.5)
    assert neutra.tronco == pytest.approx(-10, abs=1.5) and neutra.cuello == 28


@pytest.mark.parametrize("tronco, cuello, rodilla", [
    (40, 20, 5),     # agachado: no es la postura de pie
    (-5, 25, 60),    # en sentadilla
    (None, 25, 5), (-5, None, 5), (-5, 25, None),  # segmentos sin estimar
])
def test_no_calibra_si_no_esta_de_pie_o_falta_un_segmento(tronco, cuello, rodilla):
    neutra = PosturaNeutra()
    for i in range(60):
        neutra.actualizar(i / FPS, tronco, cuello, rodilla)
    assert not neutra.calibrada and (neutra.tronco, neutra.cuello) == (0.0, 0.0)


def test_no_calibra_mientras_se_mueve():
    neutra = PosturaNeutra()
    for i in range(90):  # el tronco oscila 10 grados
        neutra.actualizar(i / FPS, -10 + 10 * (i % 30) / 30, 30, 5)
    assert not neutra.calibrada


def test_una_interrupcion_reinicia_la_espera():
    neutra = PosturaNeutra()
    alimentar(neutra, -11, 30, 3, 0.5)
    neutra.actualizar(0.5, 50, 30, 3)  # se agacha un instante
    assert not alimentar(neutra, -11, 30, 3, 0.5, desde=0.55)
    assert alimentar(neutra, -11, 30, 3, 0.4, desde=1.05)


def test_se_calibra_una_sola_vez_por_persona_y_reiniciar_la_olvida():
    neutra = PosturaNeutra()
    alimentar(neutra, -11, 30, 3, 1.0)
    assert not alimentar(neutra, 5, 10, 3, 2.0, desde=1.0)  # ya calibrada: no cambia
    assert (neutra.tronco, neutra.cuello) == (-11, 30)
    neutra.reiniciar()
    assert not neutra.calibrada and (neutra.tronco, neutra.cuello) == (0.0, 0.0)
    assert alimentar(neutra, 5, 10, 3, 1.0, desde=3.0) and (neutra.tronco, neutra.cuello) == (5, 10)


def test_el_neutro_tiene_topes_para_no_esconder_una_inclinacion_real():
    neutra = PosturaNeutra()
    alimentar(neutra, 24, 70, 3, 1.0)
    assert neutra.tronco == LIMITE_TRONCO and neutra.cuello == LIMITE_CUELLO[1]


def test_con_neutro_corrige_tronco_cuello_y_brazo_pero_no_el_resto():
    crudos = calcular_angulos(postura(**DE_PIE_REAL))
    corregidos = crudos.con_neutro(-11, 30)
    assert corregidos.tronco == pytest.approx(0, **APROX) and corregidos.cuello == pytest.approx(0, **APROX)
    assert corregidos.brazo == pytest.approx(-1, **APROX)  # el brazo se mide respecto al tronco
    assert (corregidos.piernas, corregidos.antebrazo, corregidos.muneca, corregidos.brazo_vertical) == (
        crudos.piernas, crudos.antebrazo, crudos.muneca, crudos.brazo_vertical)


def test_sin_frente_conocido_no_se_corrige():
    puntos = postura(tronco=-11)
    for nombre in ("nariz", "talon_derecho"):
        puntos[nombre] = puntos[nombre]._replace(visibilidad=0.0)
    crudos = calcular_angulos(puntos)
    assert crudos.frente is None and crudos.con_neutro(-11, 30) is crudos


# --------------------------------------------------------------------------- #
# En el analizador
# --------------------------------------------------------------------------- #
def correr(analizador, estimador, pose, segundos, desde_ms=0, config=CONFIG):
    estimador.puntos = None if pose is None else postura(**pose)
    analisis = None
    for i in range(round(segundos * FPS)):
        analisis = analizador.analizar(FRAME, desde_ms + round(i * 1000 / FPS), config)
    return analisis


def test_de_pie_y_derecho_deja_de_marcar_riesgo():
    estimador = EstimadorFijo(None)
    analizador = Analizador(estimador)
    antes = correr(analizador, estimador, DE_PIE_REAL, 0.3)
    assert antes.neutra is None
    assert antes.resultado.segmentos["tronco"] == 2 and antes.resultado.segmentos["cuello"] == 2  # sin corregir
    assert antes.resultado.puntaje == 3
    despues = correr(analizador, estimador, DE_PIE_REAL, 1.0, desde_ms=300)
    assert despues.neutra == pytest.approx((-11, 30), abs=0.5)
    assert despues.angulos.tronco == pytest.approx(0, abs=0.5) and despues.angulos.cuello == pytest.approx(0, abs=0.5)
    assert despues.resultado.segmentos["tronco"] == 1 and despues.resultado.segmentos["cuello"] == 1
    assert despues.resultado.puntaje == 1


def test_al_agacharse_los_angulos_se_miden_desde_el_neutro():
    estimador = EstimadorFijo(None)
    analizador = Analizador(estimador)
    correr(analizador, estimador, DE_PIE_REAL, 1.2)
    agachado = correr(analizador, estimador, dict(tronco=80, cuello=10, rodilla=20, brazo=85, codo=10), 1.5,
                      desde_ms=1200)
    assert agachado.angulos.tronco == pytest.approx(80, abs=1)  # agachado manda el ángulo crudo
    assert agachado.angulos.brazo == pytest.approx(85, abs=1)  # y el brazo, que se mide respecto al tronco
    assert agachado.angulos.cuello == pytest.approx(-20, abs=1)  # 10 crudos − 30: mira al frente, en extensión
    assert agachado.resultado.segmentos["cuello"] == 2


def test_otra_persona_se_calibra_de_nuevo():
    estimador = EstimadorFijo(None)
    analizador = Analizador(estimador)
    correr(analizador, estimador, DE_PIE_REAL, 1.2)
    correr(analizador, estimador, None, 0.5, desde_ms=1200)  # una pérdida breve no borra la calibración
    assert analizador.neutra.calibrada
    correr(analizador, estimador, None, 2.5, desde_ms=1700)  # se fue
    assert not analizador.neutra.calibrada
    otra = correr(analizador, estimador, dict(tronco=-4, cuello=20, rodilla=3), 1.2, desde_ms=4200)
    assert otra.neutra == pytest.approx((-4, 20), abs=0.5)


def test_se_puede_desactivar_por_configuracion():
    estimador = EstimadorFijo(None)
    analizador = Analizador(estimador)
    config = validar_config({"postura_neutra": False})
    analisis = correr(analizador, estimador, DE_PIE_REAL, 1.5, config=config)
    assert analisis.neutra is None and analisis.angulos.tronco == pytest.approx(-11, abs=0.5)
    with pytest.raises(ValueError):
        validar_config({"postura_neutra": "si"})


# --------------------------------------------------------------------------- #
# La corrección del tronco se desvanece al inclinarse
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("crudo, esperado", [
    (-17, 0),      # de pie: se resta el neutro completo
    (-2, 6.5),     # inclinado 15° desde su postura de pie: media corrección
    (13, 13),      # a 30° de su postura de pie ya manda el ángulo crudo
    (19, 19),      # sentadilla vista en vivo: 19° en la imagen, no 36°
    (83, 83),      # espalda doblada vista en vivo: hombro aún sobre la cadera, no 100°
    (-30, -20.4),  # hacia atrás también se desvanece
])
def test_correccion_del_tronco_segun_la_inclinacion(crudo, esperado):
    assert crudo - correccion_de_tronco(crudo, -17) == pytest.approx(esperado, abs=0.1)


@pytest.mark.parametrize("neutro", [-20, -11, 0, 9, 20])
def test_el_tronco_corregido_nunca_retrocede_al_inclinarse(neutro):
    corregidos = [c - correccion_de_tronco(c, neutro) for c in range(-60, 121)]
    assert all(b > a for a, b in zip(corregidos, corregidos[1:]))
    assert corregidos[neutro + 60] == pytest.approx(0)


def test_sentadilla_con_espalda_recta_no_se_infla_por_el_neutro():
    """La captura en vivo: tronco a 19° en la imagen, neutro de −17°."""
    crudos = calcular_angulos(postura(tronco=19, cuello=-3, rodilla=146, brazo=50, codo=3))
    corregidos = crudos.con_neutro(-17, 28)
    assert corregidos.tronco == pytest.approx(19, **APROX) and corregidos.brazo == pytest.approx(50, **APROX)
    assert corregidos.cuello == pytest.approx(-31, **APROX)  # el cuello sí se corrige completo
