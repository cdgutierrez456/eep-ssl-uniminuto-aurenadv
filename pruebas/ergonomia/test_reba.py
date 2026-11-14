"""Pruebas del puntaje REBA: segmentos, bordes de rango, tablas completas y ejemplos trabajados."""

import pytest

from modulos.ergonomia.nucleo import reba
from modulos.ergonomia.nucleo.reba import Condiciones, calcular_reba

# Copia independiente de las tablas (transcritas del método), para detectar cualquier
# cambio accidental en tablas_reba.json.
TABLA_A = [
    [[1, 2, 3, 4], [2, 3, 4, 5], [2, 4, 5, 6], [3, 5, 6, 7], [4, 6, 7, 8]],
    [[1, 2, 3, 4], [3, 4, 5, 6], [4, 5, 6, 7], [5, 6, 7, 8], [6, 7, 8, 9]],
    [[3, 3, 5, 6], [4, 5, 6, 7], [5, 6, 7, 8], [6, 7, 8, 9], [7, 8, 9, 9]],
]
TABLA_B = [
    [[1, 2, 2], [1, 2, 3], [3, 4, 5], [4, 5, 5], [6, 7, 8], [7, 8, 8]],
    [[1, 2, 3], [2, 3, 4], [4, 5, 5], [5, 6, 7], [7, 8, 8], [8, 9, 9]],
]
TABLA_C = [
    [1, 1, 1, 2, 3, 3, 4, 5, 6, 7, 7, 7],
    [1, 2, 2, 3, 4, 4, 5, 6, 6, 7, 7, 8],
    [2, 3, 3, 3, 4, 5, 6, 7, 7, 8, 8, 8],
    [3, 4, 4, 4, 5, 6, 7, 8, 8, 9, 9, 9],
    [4, 4, 4, 5, 6, 7, 8, 8, 9, 9, 9, 9],
    [6, 6, 6, 7, 8, 8, 9, 9, 10, 10, 10, 10],
    [7, 7, 7, 8, 9, 9, 9, 10, 10, 11, 11, 11],
    [8, 8, 8, 9, 10, 10, 10, 10, 10, 11, 11, 11],
    [9, 9, 9, 10, 10, 10, 11, 11, 11, 12, 12, 12],
    [10, 10, 10, 11, 11, 11, 11, 12, 12, 12, 12, 12],
    [11, 11, 11, 11, 12, 12, 12, 12, 12, 12, 12, 12],
    [12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12],
]


# --------------------------------------------------------------------------- #
# Segmentos: valores conocidos y bordes (el límite exacto cae en el rango inferior)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("angulo, esperado", [
    (0, 1), (5, 1), (-5, 1),            # erguido, dentro de la tolerancia
    (5.1, 2), (10, 2), (20, 2),         # 0-20° flexión
    (20.1, 3), (40, 3), (60, 3),        # 20-60° flexión
    (60.1, 4), (90, 4),                 # >60° flexión
    (-5.1, 2), (-20, 2),                # 0-20° extensión
    (-20.1, 3), (-45, 3),               # >20° extensión
])
def test_tronco(angulo, esperado):
    assert reba.puntaje_tronco(angulo) == esperado


def test_tronco_sin_tolerancia_solo_cero_es_erguido():
    assert reba.puntaje_tronco(0, tolerancia_erguido=0) == 1
    assert reba.puntaje_tronco(0.5, tolerancia_erguido=0) == 2
    assert reba.puntaje_tronco(-0.5, tolerancia_erguido=0) == 2


def test_tronco_con_torsion_suma_uno():
    assert reba.puntaje_tronco(70, torsion_o_inclinacion=True) == 5


@pytest.mark.parametrize("angulo, esperado", [
    (0, 1), (10, 1), (20, 1), (20.1, 2), (45, 2),
    (-5, 1),                             # extensión dentro de la tolerancia: neutro
    (-5.1, 2), (-30, 2),                 # en extensión
])
def test_cuello(angulo, esperado):
    assert reba.puntaje_cuello(angulo) == esperado


def test_cuello_con_torsion_suma_uno():
    assert reba.puntaje_cuello(30, torsion_o_inclinacion=True) == 3


@pytest.mark.parametrize("flexion, inestable, esperado", [
    (0, False, 1), (29.9, False, 1),
    (30, False, 2), (45, False, 2), (60, False, 2),
    (60.1, False, 3), (110, False, 3),
    (0, True, 2), (45, True, 3), (90, True, 4),
])
def test_piernas(flexion, inestable, esperado):
    assert reba.puntaje_piernas(flexion, inestable) == esperado


def test_piernas_sentado_no_suma_por_rodillas():
    assert reba.puntaje_piernas(90, sentado=True) == 1


@pytest.mark.parametrize("peso, brusca, esperado", [
    (0, False, 0), (4.9, False, 0), (5, False, 1), (10, False, 1), (10.1, False, 2),
    (25, False, 2), (3, True, 1), (15, True, 3),
])
def test_carga(peso, brusca, esperado):
    assert reba.puntaje_carga(peso, brusca) == esperado


@pytest.mark.parametrize("angulo, esperado", [
    (0, 1), (20, 1), (-20, 1),
    (-20.1, 2), (-40, 2),                # >20° extensión
    (20.1, 2), (45, 2),                  # 20-45° flexión
    (45.1, 3), (90, 3),                  # 45-90° flexión
    (90.1, 4), (170, 4),                 # >90° flexión
])
def test_brazo(angulo, esperado):
    assert reba.puntaje_brazo(angulo) == esperado


def test_brazo_ajustes():
    assert reba.puntaje_brazo(100, abducido_o_rotado=True, hombro_elevado=True) == 6
    assert reba.puntaje_brazo(60, apoyado_o_a_favor_de_gravedad=True) == 2
    assert reba.puntaje_brazo(0, apoyado_o_a_favor_de_gravedad=True) == 1  # nunca baja de 1


@pytest.mark.parametrize("flexion, esperado", [
    (59.9, 2), (60, 1), (80, 1), (100, 1), (100.1, 2), (0, 2), (140, 2),
])
def test_antebrazo(flexion, esperado):
    assert reba.puntaje_antebrazo(flexion) == esperado


@pytest.mark.parametrize("angulo, desviada, esperado", [
    (0, False, 1), (15, False, 1), (-15, False, 1), (15.1, False, 2), (-30, False, 2),
    (10, True, 2), (40, True, 3),
])
def test_muneca(angulo, desviada, esperado):
    assert reba.puntaje_muneca(angulo, desviada) == esperado


def test_agarre():
    assert [reba.puntaje_agarre(a) for a in ("bueno", "regular", "malo", "inaceptable")] == [0, 1, 2, 3]
    with pytest.raises(ValueError):
        reba.puntaje_agarre("excelente")


# --------------------------------------------------------------------------- #
# Tablas completas
# --------------------------------------------------------------------------- #
def test_tabla_a_completa():
    for cuello in range(1, 4):
        for tronco in range(1, 6):
            for piernas in range(1, 5):
                assert reba.tabla_a(cuello, tronco, piernas) == TABLA_A[cuello - 1][tronco - 1][piernas - 1]


def test_tabla_b_completa():
    for antebrazo in range(1, 3):
        for brazo in range(1, 7):
            for muneca in range(1, 4):
                assert reba.tabla_b(antebrazo, brazo, muneca) == TABLA_B[antebrazo - 1][brazo - 1][muneca - 1]


def test_tabla_c_completa():
    for a in range(1, 13):
        for b in range(1, 13):
            assert reba.tabla_c(a, b) == TABLA_C[a - 1][b - 1]


@pytest.mark.parametrize("llamada", [
    lambda: reba.tabla_a(4, 1, 1), lambda: reba.tabla_a(1, 6, 1), lambda: reba.tabla_a(1, 1, 0),
    lambda: reba.tabla_b(3, 1, 1), lambda: reba.tabla_b(1, 7, 1), lambda: reba.tabla_b(1, 1, 4),
    lambda: reba.tabla_c(13, 1), lambda: reba.tabla_c(1, 0),
])
def test_tablas_rechazan_indices_fuera_de_rango(llamada):
    with pytest.raises(ValueError):
        llamada()


@pytest.mark.parametrize("puntaje, nivel, severidad", [
    (1, "insignificante", "info"),
    (2, "bajo", "baja"), (3, "bajo", "baja"),
    (4, "medio", "media"), (7, "medio", "media"),
    (8, "alto", "alta"), (10, "alto", "alta"),
    (11, "muy_alto", "critica"), (15, "muy_alto", "critica"),
])
def test_niveles_y_severidad(puntaje, nivel, severidad):
    assert reba.nivel_de_riesgo(puntaje) == nivel
    assert reba.severidad_de(puntaje) == severidad


def test_nivel_fuera_de_rango():
    for puntaje in (0, 16):
        with pytest.raises(ValueError):
            reba.nivel_de_riesgo(puntaje)


# --------------------------------------------------------------------------- #
# Ejemplos trabajados completos
# --------------------------------------------------------------------------- #
def test_ejemplo_ntp_601_sanitario_moviendo_paciente():
    """NTP 601 (INSHT), ejemplo con fe de erratas de 2003. Leído directamente de la fuente."""
    r = calcular_reba(
        {"tronco": 40, "cuello": 10, "piernas": 70, "brazo": 60, "antebrazo": 40, "muneca": 5},
        Condiciones(peso_carga_kg=15, golpe_o_fuerza_brusca=True, agarre="regular",
                    brazo_apoyado=True, actividad_cambios_rapidos=True),
    )
    assert r.segmentos == {"tronco": 3, "cuello": 1, "piernas": 3, "brazo": 2, "antebrazo": 2, "muneca": 1}
    assert (r.tabla_a, r.carga, r.puntaje_a) == (5, 3, 8)
    assert (r.tabla_b, r.agarre, r.puntaje_b) == (2, 1, 3)
    assert (r.tabla_c, r.actividad, r.puntaje) == (8, 1, 9)
    assert (r.nivel, r.severidad) == ("alto", "alta")


def test_ejemplo_ergoplus_operario_alcanzando():
    """Guía REBA de ErgoPlus. Verificación de menor confianza (no leído directamente):
    los valores salen de un resumen de la página, coherentes con las tablas."""
    r = calcular_reba(
        {"tronco": 15, "cuello": 10, "piernas": 0, "brazo": 100, "antebrazo": 40, "muneca": 25},
        Condiciones(peso_carga_kg=7, agarre="regular", torsion_tronco=True, brazo_abducido_o_rotado=True,
                    hombro_elevado=True, muneca_desviada=True, actividad_repetitiva=True),
    )
    assert r.segmentos == {"tronco": 3, "cuello": 1, "piernas": 1, "brazo": 6, "antebrazo": 2, "muneca": 3}
    assert (r.tabla_a, r.carga, r.puntaje_a) == (2, 1, 3)
    assert (r.tabla_b, r.agarre, r.puntaje_b) == (9, 1, 10)
    assert (r.tabla_c, r.actividad, r.puntaje) == (8, 1, 9)
    assert r.nivel == "alto"


def test_ejemplo_levantamiento_con_buena_tecnica():
    """Derivado, no publicado: calculado a mano con las tablas para la demo del stand
    (espalda casi recta, rodillas flexionadas, caja de 5 kg con buen agarre)."""
    r = calcular_reba({"tronco": 10, "cuello": 10, "piernas": 70, "brazo": 30, "antebrazo": 80, "muneca": 5})
    assert r.segmentos == {"tronco": 2, "cuello": 1, "piernas": 3, "brazo": 2, "antebrazo": 1, "muneca": 1}
    assert (r.tabla_a, r.carga, r.puntaje_a) == (4, 1, 5)
    assert (r.tabla_b, r.agarre, r.puntaje_b) == (1, 0, 1)
    assert (r.tabla_c, r.actividad, r.puntaje) == (4, 0, 4)
    assert (r.nivel, r.severidad) == ("medio", "media")


# --------------------------------------------------------------------------- #
# Segmentos no estimados y extremos
# --------------------------------------------------------------------------- #
ANGULOS_BASE = {"tronco": 40, "cuello": 10, "piernas": 0, "brazo": 30, "antebrazo": 80, "muneca": 5}


@pytest.mark.parametrize("faltante", ["tronco", "cuello", "piernas", "brazo", "antebrazo"])
def test_sin_un_segmento_esencial_no_hay_reba_final(faltante):
    r = calcular_reba({**ANGULOS_BASE, faltante: None})
    assert r.puntaje is None and r.nivel is None and r.severidad is None
    assert not r.completo
    assert r.segmentos[faltante] is None
    assert r.no_estimados == (faltante,)
    # Los demás segmentos sí conservan su puntaje
    assert all(r.segmentos[n] is not None for n in ANGULOS_BASE if n != faltante)


def test_sin_muneca_se_calcula_con_su_minimo_y_queda_anotado():
    con_muneca = calcular_reba(ANGULOS_BASE)
    sin_muneca = calcular_reba({n: a for n, a in ANGULOS_BASE.items() if n != "muneca"})
    assert sin_muneca.completo
    assert sin_muneca.segmentos["muneca"] is None  # no se inventa un puntaje para mostrar
    assert sin_muneca.no_estimados == ("muneca",) and sin_muneca.asumidos == ("muneca",)
    assert sin_muneca.puntaje == con_muneca.puntaje  # la muñeca medida también puntuaba 1


def test_puntaje_maximo_es_15():
    r = calcular_reba(
        {"tronco": 90, "cuello": 40, "piernas": 90, "brazo": 120, "antebrazo": 20, "muneca": 40},
        Condiciones(peso_carga_kg=20, golpe_o_fuerza_brusca=True, agarre="inaceptable",
                    apoyo_inestable=True, torsion_tronco=True, torsion_cuello=True,
                    brazo_abducido_o_rotado=True, hombro_elevado=True, muneca_desviada=True,
                    actividad_estatica=True, actividad_repetitiva=True, actividad_cambios_rapidos=True),
    )
    assert (r.puntaje_a, r.puntaje_b, r.tabla_c, r.puntaje) == (12, 12, 12, 15)
    assert r.nivel == "muy_alto"


def test_puntaje_minimo_es_1():
    r = calcular_reba({"tronco": 0, "cuello": 5, "piernas": 0, "brazo": 0, "antebrazo": 80, "muneca": 0},
                      Condiciones(peso_carga_kg=0))
    assert (r.puntaje, r.nivel, r.severidad) == (1, "insignificante", "info")


# --------------------------------------------------------------------------- #
# Ajuste automático del brazo: persona inclinada con el brazo colgando
# --------------------------------------------------------------------------- #
def test_espalda_doblada_y_brazo_colgando_resta_uno_al_brazo():
    # Tronco a 70° y brazo vertical hacia el piso: 70° respecto al tronco (puntaje 3 sin ajuste)
    angulos = {"tronco": 70, "cuello": 10, "piernas": 10, "brazo": 70, "antebrazo": 10, "muneca": 5,
               "brazo_vertical": 0}
    r = calcular_reba(angulos)
    assert r.segmentos["brazo"] == 2
    assert r.ajustes_aplicados == ("brazo_persona_inclinada",)
    sin_ajuste = calcular_reba(angulos, Condiciones(ajuste_brazo_inclinada=False))
    assert sin_ajuste.segmentos["brazo"] == 3
    assert sin_ajuste.ajustes_aplicados == ()


def test_tronco_erguido_y_brazo_colgando_no_aplica():
    r = calcular_reba({"tronco": 0, "cuello": 10, "piernas": 0, "brazo": 0, "antebrazo": 80, "muneca": 5,
                       "brazo_vertical": 0})
    assert r.segmentos["brazo"] == 1 and r.ajustes_aplicados == ()


def test_tronco_flexionado_y_brazo_extendido_al_frente_no_aplica():
    # Tronco a 60° y brazo horizontal hacia adelante: 90° respecto a la vertical del piso
    r = calcular_reba({"tronco": 60, "cuello": 10, "piernas": 0, "brazo": 150, "antebrazo": 10, "muneca": 5,
                       "brazo_vertical": 90})
    assert r.segmentos["brazo"] == 4 and r.ajustes_aplicados == ()


@pytest.mark.parametrize("tronco, vertical, aplica", [
    (45, 0, False), (45.1, 0, True),      # el tronco debe superar el umbral
    (70, 20, True), (70, 20.1, False),    # el brazo, dentro de la tolerancia
    (70, None, False),                    # sin el ángulo auxiliar no se aplica
])
def test_bordes_del_ajuste_por_persona_inclinada(tronco, vertical, aplica):
    assert reba.brazo_persona_inclinada(tronco, vertical) is aplica


def test_umbrales_del_ajuste_son_configurables():
    angulos = {**ANGULOS_BASE, "tronco": 40, "brazo": 60, "brazo_vertical": 25}
    assert calcular_reba(angulos).ajustes_aplicados == ()
    r = calcular_reba(angulos, Condiciones(umbral_tronco_inclinado=30, tolerancia_brazo_vertical=30))
    assert r.ajustes_aplicados == ("brazo_persona_inclinada",) and r.segmentos["brazo"] == 2


def test_el_ajuste_no_baja_el_brazo_de_uno_ni_se_suma_al_de_apoyado():
    base = {"tronco": 70, "cuello": 10, "piernas": 10, "antebrazo": 10, "muneca": 5, "brazo_vertical": 15}
    assert calcular_reba({**base, "brazo": 15}).segmentos["brazo"] == 1  # 1 - 1 se queda en 1
    # Si el operador ya marcó "apoyado", el -1 se aplica una sola vez y no se anota el automático
    r = calcular_reba({**base, "brazo": 70}, Condiciones(brazo_apoyado=True))
    assert r.segmentos["brazo"] == 2 and r.ajustes_aplicados == ()


def test_sin_brazo_estimado_no_se_anota_el_ajuste():
    r = calcular_reba({"tronco": 70, "cuello": 10, "piernas": 10, "brazo": None, "antebrazo": 10,
                       "brazo_vertical": 0})
    assert r.ajustes_aplicados == () and r.puntaje is None


@pytest.mark.parametrize("vertical", [0, 90])
def test_los_ejemplos_publicados_no_cambian_con_el_ajuste(vertical):
    """NTP 601 (tronco a 40°) y ErgoPlus (tronco a 15°) quedan bajo el umbral de 45°."""
    ntp = calcular_reba(
        {"tronco": 40, "cuello": 10, "piernas": 70, "brazo": 60, "antebrazo": 40, "muneca": 5,
         "brazo_vertical": vertical},
        Condiciones(peso_carga_kg=15, golpe_o_fuerza_brusca=True, agarre="regular",
                    brazo_apoyado=True, actividad_cambios_rapidos=True))
    ergoplus = calcular_reba(
        {"tronco": 15, "cuello": 10, "piernas": 0, "brazo": 100, "antebrazo": 40, "muneca": 25,
         "brazo_vertical": vertical},
        Condiciones(peso_carga_kg=7, agarre="regular", torsion_tronco=True, brazo_abducido_o_rotado=True,
                    hombro_elevado=True, muneca_desviada=True, actividad_repetitiva=True))
    assert (ntp.puntaje, ergoplus.puntaje) == (9, 9)
    assert ntp.ajustes_aplicados == ergoplus.ajustes_aplicados == ()
