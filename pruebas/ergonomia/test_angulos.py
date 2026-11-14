"""Pruebas de los ángulos 2D: posturas construidas con ángulos conocidos."""

import math

import pytest

from modulos.ergonomia.nucleo import angulos
from modulos.ergonomia.nucleo.angulos import Punto, calcular_angulos

APROX = dict(abs=1e-6)


def polar(origen: Punto, largo: float, grados_desde_arriba: float, frente: int = 1, vis: float = 1.0) -> Punto:
    """Punto a ``largo`` píxeles de ``origen``, girado desde la vertical hacia arriba (+ = al frente)."""
    r = math.radians(grados_desde_arriba)
    return Punto(origen.x + frente * largo * math.sin(r), origen.y - largo * math.cos(r), vis)


def postura(tronco=0.0, cuello=0.0, rodilla=0.0, brazo=0.0, codo=0.0, muneca=0.0,
            frente=1, lado="derecho", vis=1.0) -> dict[str, Punto]:
    """Arma un cuerpo de perfil con los ángulos pedidos (en grados, + = flexión)."""
    cadera = Punto(500.0, 400.0, vis)
    hombro = polar(cadera, 200, tronco, frente, vis)
    oreja = polar(hombro, 60, tronco + cuello, frente, vis)
    nariz = Punto(oreja.x + frente * 40, oreja.y, vis)
    # Pierna: el muslo gira hacia el frente y la pantorrilla vuelve hacia atrás
    rodilla_p = polar(cadera, 180, 180 - rodilla / 2, frente, vis)
    tobillo = polar(rodilla_p, 180, 180 + rodilla / 2, frente, vis)
    # Brazo: se mide desde la línea del tronco hacia abajo
    codo_p = polar(hombro, 120, 180 + tronco - brazo, frente, vis)
    muneca_p = polar(codo_p, 110, 180 + tronco - brazo - codo, frente, vis)
    mano = polar(muneca_p, 40, 180 + tronco - brazo - codo - muneca, frente, vis)
    puntos = {
        "cadera": cadera, "hombro": hombro, "oreja": oreja, "rodilla": rodilla_p, "tobillo": tobillo,
        "codo": codo_p, "muneca": muneca_p,
        "indice": Punto(mano.x + 3, mano.y - 3, vis), "menique": Punto(mano.x - 3, mano.y + 3, vis),
        "talon": Punto(tobillo.x - frente * 20, tobillo.y + 10, vis),
        "punta_pie": Punto(tobillo.x + frente * 60, tobillo.y + 10, vis),
    }
    salida = {f"{nombre}_{lado}": punto for nombre, punto in puntos.items()}
    salida["nariz"] = nariz
    return salida


# --------------------------------------------------------------------------- #
# Funciones sueltas
# --------------------------------------------------------------------------- #
def test_angulo_en_vertice():
    assert angulos.angulo_en_vertice(Punto(0, 0), Punto(0, 10), Punto(10, 10)) == pytest.approx(90)
    assert angulos.angulo_en_vertice(Punto(0, 0), Punto(0, 10), Punto(0, 20)) == pytest.approx(180)
    assert angulos.angulo_en_vertice(Punto(0, 0), Punto(0, 10), Punto(0, 5)) == pytest.approx(0)


@pytest.mark.parametrize("esperado", [0, 10, 20, 45, 60, 90, -15, -30])
@pytest.mark.parametrize("frente", [1, -1])
def test_tronco(esperado, frente):
    cadera = Punto(300, 500)
    hombro = polar(cadera, 200, esperado, frente)
    assert angulos.angulo_tronco(cadera, hombro, frente) == pytest.approx(esperado, **APROX)


@pytest.mark.parametrize("tronco, cuello", [(0, 0), (0, 25), (60, 10), (60, -20), (90, 30), (-10, 15)])
@pytest.mark.parametrize("frente", [1, -1])
def test_cuello_es_relativo_al_tronco(tronco, cuello, frente):
    cadera = Punto(300, 500)
    hombro = polar(cadera, 200, tronco, frente)
    oreja = polar(hombro, 60, tronco + cuello, frente)
    assert angulos.angulo_cuello(cadera, hombro, oreja, frente) == pytest.approx(cuello, **APROX)


@pytest.mark.parametrize("flexion", [0, 30, 60, 90, 120])
def test_rodilla(flexion):
    p = postura(rodilla=flexion)
    medida = angulos.flexion_rodilla(p["cadera_derecho"], p["rodilla_derecho"], p["tobillo_derecho"])
    assert medida == pytest.approx(flexion, **APROX)


@pytest.mark.parametrize("tronco", [0, 45, 90])
@pytest.mark.parametrize("brazo", [0, 20, 45, 90, 135, 180, 200, -20, -45])
@pytest.mark.parametrize("frente", [1, -1])
def test_brazo_es_relativo_al_tronco(tronco, brazo, frente):
    p = postura(tronco=tronco, brazo=brazo, frente=frente)
    medida = angulos.angulo_brazo(p["cadera_derecho"], p["hombro_derecho"], p["codo_derecho"], frente)
    assert medida == pytest.approx(brazo, **APROX)


def test_brazo_colgando_con_tronco_flexionado_cuenta_como_flexion():
    # Tronco a 90° y brazo vertical hacia el piso: 90° respecto al tronco
    cadera, hombro, codo = Punto(300, 400), Punto(500, 400), Punto(500, 520)
    assert angulos.angulo_brazo(cadera, hombro, codo, frente=1) == pytest.approx(90)


@pytest.mark.parametrize("flexion", [0, 60, 90, 100, 140])
def test_codo(flexion):
    p = postura(brazo=30, codo=flexion)
    medida = angulos.flexion_codo(p["hombro_derecho"], p["codo_derecho"], p["muneca_derecho"])
    assert medida == pytest.approx(flexion, **APROX)


@pytest.mark.parametrize("desviacion", [0, 15, 30, -30])
def test_muneca_sin_signo(desviacion):
    p = postura(brazo=30, codo=80, muneca=desviacion)
    medida = angulos.angulo_muneca(p["codo_derecho"], p["muneca_derecho"], p["indice_derecho"], p["menique_derecho"])
    assert medida == pytest.approx(abs(desviacion), **APROX)


# --------------------------------------------------------------------------- #
# Lado, frente y cálculo conjunto
# --------------------------------------------------------------------------- #
def test_elegir_lado_el_mas_visible():
    puntos = {**postura(lado="izquierdo", vis=0.3), **postura(lado="derecho", vis=0.9)}
    assert angulos.elegir_lado(puntos) == "derecho"
    puntos = {**postura(lado="izquierdo", vis=0.9), **postura(lado="derecho", vis=0.3)}
    assert angulos.elegir_lado(puntos) == "izquierdo"


@pytest.mark.parametrize("frente", [1, -1])
def test_direccion_frente_por_la_cabeza(frente):
    assert angulos.direccion_frente(postura(frente=frente), "derecho") == frente


@pytest.mark.parametrize("frente", [1, -1])
def test_direccion_frente_por_el_pie_si_no_se_ve_la_cabeza(frente):
    puntos = postura(frente=frente)
    puntos["nariz"] = puntos["nariz"]._replace(visibilidad=0.1)
    assert angulos.direccion_frente(puntos, "derecho") == frente


def test_direccion_frente_desconocida():
    puntos = postura()
    for nombre in ("nariz", "talon_derecho"):
        puntos[nombre] = puntos[nombre]._replace(visibilidad=0.0)
    assert angulos.direccion_frente(puntos, "derecho") is None


@pytest.mark.parametrize("frente", [1, -1])
def test_calcular_angulos_postura_de_levantamiento(frente):
    puntos = postura(tronco=65, cuello=15, rodilla=40, brazo=50, codo=20, muneca=10, frente=frente)
    a = calcular_angulos(puntos)
    assert (a.lado, a.frente) == ("derecho", frente)
    assert a.tronco == pytest.approx(65, **APROX)
    assert a.cuello == pytest.approx(15, **APROX)
    assert a.piernas == pytest.approx(40, **APROX)
    assert a.brazo == pytest.approx(50, **APROX)
    assert a.antebrazo == pytest.approx(20, **APROX)
    assert a.muneca == pytest.approx(10, **APROX)
    assert set(a.como_dict()) == {"tronco", "cuello", "piernas", "brazo", "antebrazo", "muneca"}


def test_extension_sale_negativa_mirando_a_cualquier_lado():
    for frente in (1, -1):
        a = calcular_angulos(postura(tronco=-15, brazo=-30, frente=frente))
        assert a.tronco == pytest.approx(-15, **APROX)
        assert a.brazo == pytest.approx(-30, **APROX)


def test_sin_frente_conocido_los_angulos_van_sin_signo():
    puntos = postura(tronco=-15)
    for nombre in ("nariz", "talon_derecho"):
        puntos[nombre] = puntos[nombre]._replace(visibilidad=0.0)
    a = calcular_angulos(puntos)
    assert a.frente is None
    assert a.tronco == pytest.approx(15, **APROX)


def test_segmento_con_punto_poco_visible_queda_sin_estimar():
    puntos = postura(tronco=30, rodilla=40, brazo=50, codo=70)
    puntos["tobillo_derecho"] = puntos["tobillo_derecho"]._replace(visibilidad=0.2)
    puntos["indice_derecho"] = puntos["indice_derecho"]._replace(visibilidad=0.2)
    a = calcular_angulos(puntos, lado="derecho")
    assert a.piernas is None and a.muneca is None
    assert a.tronco == pytest.approx(30, **APROX)
    assert a.brazo == pytest.approx(50, **APROX)
    assert a.antebrazo == pytest.approx(70, **APROX)


def test_punto_ausente_deja_sus_segmentos_sin_estimar():
    puntos = postura()
    del puntos["cadera_derecho"]
    a = calcular_angulos(puntos, lado="derecho")
    assert a.tronco is None and a.cuello is None and a.piernas is None and a.brazo is None
    assert a.antebrazo is not None


def test_lado_desconocido():
    with pytest.raises(ValueError):
        calcular_angulos(postura(), lado="centro")


@pytest.mark.parametrize("tronco, brazo, esperado", [
    (0, 0, 0),      # de pie, brazo colgando
    (70, 70, 0),    # espalda doblada, brazo colgando hacia el piso
    (60, 150, 90),  # tronco flexionado, brazo horizontal hacia adelante
    (0, -30, 30),   # brazo hacia atrás: sin signo
])
def test_brazo_respecto_a_la_vertical_del_piso(tronco, brazo, esperado):
    a = calcular_angulos(postura(tronco=tronco, brazo=brazo))
    assert a.brazo_vertical == pytest.approx(esperado, **APROX)
    assert a.para_reba()["brazo_vertical"] == a.brazo_vertical
    assert "brazo_vertical" not in a.como_dict()  # no es un ángulo del contrato
