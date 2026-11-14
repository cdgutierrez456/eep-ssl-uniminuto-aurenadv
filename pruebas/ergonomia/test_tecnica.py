"""Indicador de técnica de levantamiento: espalda y rodillas, con las franjas de REBA."""

import pytest

from modulos.ergonomia.nucleo import reba
from modulos.ergonomia.nucleo.intentos import Visita
from modulos.ergonomia.nucleo.levantamiento import MaquinaLevantamiento
from modulos.ergonomia.nucleo.tecnica import Tecnica, estado_de_piernas, nivel_de_espalda

from .test_levantamiento import AGACHADO, CON_CAJA, DE_PIE, correr, muestras


def test_por_que_existe_reba_no_premia_levantar_con_las_piernas():
    """La tabla A de REBA, tal como la da el método: sentadilla con espalda recta puntúa más
    que espalda doblada con piernas rectas. Por eso el REBA total no distingue la técnica."""
    espalda_doblada = reba.tabla_a(cuello=1, tronco=4, piernas=1)
    sentadilla = reba.tabla_a(cuello=1, tronco=2, piernas=3)
    assert (espalda_doblada, sentadilla) == (3, 4)
    assert reba.puntaje_piernas(145) == 3 and reba.puntaje_tronco(98) == 4 and reba.puntaje_tronco(19) == 2


@pytest.mark.parametrize("flexion, nivel", [
    (0, "baja"), (20, "baja"), (21, "media"), (60, "media"), (61, "alta"), (105, "alta"),
    (-10, "baja"), (-25, "media"),
])
def test_nivel_de_espalda_usa_las_franjas_del_tronco_de_reba(flexion, nivel):
    assert nivel_de_espalda(flexion) == nivel
    # Mismas fronteras que el puntaje de tronco de REBA (sin tolerancia de erguido)
    esperado = {1: "baja", 2: "baja", 3: "media", 4: "alta"}[reba.puntaje_tronco(flexion, tolerancia_erguido=0)]
    assert nivel == esperado


@pytest.mark.parametrize("flexion, estado", [
    (0, "rectas"), (29, "rectas"), (30, "poco_flexionadas"), (60, "poco_flexionadas"), (61, "flexionadas"),
    (145, "flexionadas"),
])
def test_estado_de_piernas_usa_las_franjas_de_rodilla_de_reba(flexion, estado):
    assert estado_de_piernas(flexion) == estado
    suma = reba.puntaje_piernas(flexion) - 1  # lo que REBA suma por las rodillas: 0, 1 o 2
    assert estado == ("rectas", "poco_flexionadas", "flexionadas")[suma]


@pytest.mark.parametrize("espalda, rodillas, nivel, piernas_bien", [
    (98, 23, "alta", False),     # espalda doblada y piernas rectas: lo que la técnica evita
    (26, 145, "media", True),    # sentadilla: el esfuerzo lo hacen las piernas
    (15, 5, "baja", True),       # de pie: no hace falta flexionar
    (50, 45, "media", None),     # a medias
    (40, None, "media", None),   # rodillas sin medir
])
def test_tecnica(espalda, rodillas, nivel, piernas_bien):
    tecnica = Tecnica(espalda, rodillas)
    assert tecnica.nivel == nivel and tecnica.piernas_bien is piernas_bien


def test_textos_y_redondeo_coherente_con_lo_que_se_muestra():
    assert Tecnica(98.4, 22.6).texto_espalda() == "98° · alta"
    assert Tecnica(98.4, 22.6).texto_piernas() == "Rodillas 23° · rectas"
    assert Tecnica(40, None).texto_piernas() == "Rodillas: no estimadas"
    assert Tecnica(-8, 3).texto_espalda() == "0° · baja"
    # 60,4° se muestra como 60° y por eso es media, no alta
    assert Tecnica(60.4).nivel == "media" and Tecnica(60.6).nivel == "alta"


# --------------------------------------------------------------------------- #
# Máximos durante el levantamiento
# --------------------------------------------------------------------------- #
def test_la_maquina_entrega_los_maximos_sostenidos_de_tronco_y_rodilla():
    bajando = dict(tronco=60.0, rodilla=40.0, muneca_y=520.0)
    secuencia = muestras([(DE_PIE, 0.5, 3), (bajando, 0.5, 6), (AGACHADO, 1.0, 8), (CON_CAJA, 1.5, 3)])
    terminados, _ = correr(MaquinaLevantamiento(), secuencia)
    assert terminados[0].tronco_maximo == 95.0  # el de AGACHADO
    assert terminados[0].rodilla_maxima == 40.0  # el máximo de rodilla fue al bajar, no abajo


def test_un_pico_de_un_fotograma_no_cuenta_como_maximo():
    pico = dict(tronco=140.0, rodilla=25.0, muneca_y=610.0)
    secuencia = muestras([(DE_PIE, 0.5, 3), (AGACHADO, 0.5, 8), (pico, 1 / 30, 8), (AGACHADO, 0.5, 8),
                          (CON_CAJA, 1.5, 3)])
    terminados, _ = correr(MaquinaLevantamiento(), secuencia)
    assert terminados[0].tronco_maximo == 95.0


def test_los_fotogramas_de_pie_no_cuentan_para_los_maximos():
    inclinado_de_pie = dict(tronco=18.0, rodilla=28.0, muneca_y=270.0)  # cuenta como erguido
    secuencia = muestras([(DE_PIE, 0.5, 3), (dict(tronco=40.0, rodilla=10.0, muneca_y=560.0), 1.0, 5),
                          (inclinado_de_pie, 1.5, 3)])
    terminados, _ = correr(MaquinaLevantamiento(), secuencia)
    assert terminados[0].tronco_maximo == 40.0 and terminados[0].rodilla_maxima == 10.0


def test_intento_usa_los_maximos_y_si_faltan_los_del_fotograma_critico():
    resultado = reba.calcular_reba({"tronco": 80, "cuello": 5, "piernas": 20, "brazo": 60, "antebrazo": 30})
    visita = Visita()
    con_maximos = visita.registrar(resultado, 2.0, espalda_max=101.3, rodillas_max=33.0)
    assert (con_maximos.espalda, con_maximos.rodillas) == (101, 33)
    sin_maximos = visita.registrar(resultado, 2.0)
    assert (sin_maximos.espalda, sin_maximos.rodillas) == (80, 20)
    comparacion = visita.comparacion()
    assert comparacion.texto_espalda() == "Flexión de espalda: 101° → 80°"
    assert comparacion.texto_rodillas() == "Rodillas: 33° → 20°"
