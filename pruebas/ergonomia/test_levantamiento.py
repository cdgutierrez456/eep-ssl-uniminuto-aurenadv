"""Máquina de estados del levantamiento e intentos, con secuencias simuladas (sin cámara)."""

import pytest

from modulos.ergonomia.nucleo.intentos import Visita, normalizar_sesion
from modulos.ergonomia.nucleo.levantamiento import Estado, MaquinaLevantamiento, Muestra, Umbrales
from modulos.ergonomia.nucleo.reba import Condiciones, calcular_reba

FPS = 30
# Alturas en píxeles (y crece hacia abajo): cadera 360, rodilla 500
DE_PIE = dict(tronco=-8.0, rodilla=5.0, muneca_y=375.0)  # brazos colgando: muñeca algo bajo la cadera
CON_CAJA = dict(tronco=-8.0, rodilla=5.0, muneca_y=270.0)  # sostiene la caja a la altura del pecho
AGACHADO = dict(tronco=95.0, rodilla=25.0, muneca_y=610.0)
A_MEDIAS = dict(tronco=30.0, rodilla=20.0, muneca_y=440.0)


def muestras(tramos, fps=FPS, desde=0.0):
    """Arma la secuencia: cada tramo es (postura, segundos, puntaje)."""
    salida, t = [], desde
    for postura, segundos, puntaje in tramos:
        for _ in range(round(segundos * fps)):
            if postura is None:
                salida.append(Muestra(t=t, hay_persona=False))
            else:
                salida.append(Muestra(t=t, hay_persona=True, rodilla_y=500.0, cadera_y=360.0,
                                      puntaje=puntaje, carga=(round(t, 3), puntaje), **postura))
            t += 1.0 / fps
    return salida


def correr(maquina, secuencia, modo="auto", pulsar_en=()):
    """Devuelve los levantamientos terminados y los estados por los que pasó."""
    terminados, estados = [], []
    for i, m in enumerate(secuencia):
        resultado = maquina.actualizar(m, pulsacion=i in pulsar_en, modo=modo)
        if not estados or estados[-1] is not maquina.estado:
            estados.append(maquina.estado)
        if resultado is not None:
            terminados.append(resultado)
    return terminados, estados


LEVANTAMIENTO = [(DE_PIE, 1.0, 3), (A_MEDIAS, 0.3, 4), (AGACHADO, 1.0, 8), (A_MEDIAS, 0.3, 4),
                 (CON_CAJA, 2.0, 3)]


def test_ciclo_completo_en_modo_auto():
    terminados, estados = correr(MaquinaLevantamiento(), [*muestras([(None, 0.5, None)]),
                                                         *muestras(LEVANTAMIENTO, desde=0.5)])
    assert estados == [Estado.SIN_PERSONA, Estado.PERSONA_LISTA, Estado.LEVANTANDO, Estado.TERMINADO,
                       Estado.PERSONA_LISTA]
    assert len(terminados) == 1
    lev = terminados[0]
    assert lev.puntaje == 8 and lev.motivo_fin == "auto" and lev.sostenido
    assert lev.critico[1] == 8  # la carga es la del fotograma crítico
    # Empieza al agacharse (1,5 s) y termina al quedar erguido (3,1 s), no un segundo después
    assert lev.inicio == pytest.approx(1.5, abs=0.05)
    assert lev.duracion_s == pytest.approx(1.6, abs=0.1)


def test_empieza_cuando_las_munecas_bajan_de_las_rodillas_aunque_el_tronco_siga_recto():
    sentadilla = dict(tronco=10.0, rodilla=120.0, muneca_y=560.0)
    terminados, _ = correr(MaquinaLevantamiento(), muestras([(DE_PIE, 0.5, 3), (sentadilla, 1.0, 6),
                                                            (CON_CAJA, 1.5, 3)]))
    assert [lev.puntaje for lev in terminados] == [6]


def test_tronco_inclinado_con_las_manos_arriba_no_empieza():
    cargando_inclinado = dict(tronco=35.0, rodilla=5.0, muneca_y=300.0)  # lleva la caja, manos sobre la cadera
    terminados, estados = correr(MaquinaLevantamiento(), muestras([(cargando_inclinado, 2.0, 5)]))
    assert terminados == [] and Estado.LEVANTANDO not in estados


def test_termina_con_los_brazos_colgando_despues_de_dejar_la_caja():
    # Al final las muñecas quedan bajo la cadera (375 > 360) pero sobre el punto medio con la rodilla
    terminados, _ = correr(MaquinaLevantamiento(), muestras([(DE_PIE, 0.5, 3), (AGACHADO, 1.0, 8),
                                                            (DE_PIE, 1.5, 3)]))
    assert len(terminados) == 1


def test_no_termina_si_no_lleva_un_segundo_erguido():
    secuencia = muestras([(DE_PIE, 0.5, 3), (AGACHADO, 1.0, 8), (CON_CAJA, 0.6, 3), (AGACHADO, 1.0, 9),
                          (CON_CAJA, 1.5, 3)])
    terminados, _ = correr(MaquinaLevantamiento(), secuencia)
    assert [lev.puntaje for lev in terminados] == [9]  # un solo levantamiento, con su peor momento


def test_dos_levantamientos_seguidos():
    terminados, _ = correr(MaquinaLevantamiento(), muestras(LEVANTAMIENTO + [(AGACHADO, 1.0, 5),
                                                                              (CON_CAJA, 1.5, 3)]))
    assert [lev.puntaje for lev in terminados] == [8, 5]


def test_el_critico_es_el_puntaje_sostenido_no_un_pico_de_un_fotograma():
    pico = [(DE_PIE, 0.5, 3), (AGACHADO, 0.5, 8), (AGACHADO, 1 / FPS, 11), (AGACHADO, 0.5, 8), (CON_CAJA, 1.5, 3)]
    terminados, _ = correr(MaquinaLevantamiento(), muestras(pico))
    assert terminados[0].puntaje == 8 and terminados[0].sostenido


def test_un_puntaje_que_se_sostiene_la_ventana_si_cuenta():
    secuencia = [(DE_PIE, 0.5, 3), (AGACHADO, 0.5, 8), (AGACHADO, 0.4, 9), (AGACHADO, 0.3, 8), (CON_CAJA, 1.5, 3)]
    terminados, _ = correr(MaquinaLevantamiento(), muestras(secuencia))
    assert terminados[0].puntaje == 9 and terminados[0].critico[1] == 9


def test_con_pocos_fotogramas_usa_el_maximo_simple():
    # A 2 fotogramas por segundo no hay ventana sostenida de 0,3 s con el puntaje alto
    secuencia = muestras([(DE_PIE, 1.0, 3), (AGACHADO, 1.0, 8), (CON_CAJA, 2.0, 3)], fps=2)
    terminados, _ = correr(MaquinaLevantamiento(Umbrales(ventana_sostenida_s=5.0)), secuencia)
    assert terminados[0].puntaje == 8 and not terminados[0].sostenido


def test_fotogramas_sin_puntaje_cortan_la_racha_pero_no_el_levantamiento():
    secuencia = muestras([(DE_PIE, 0.5, 3), (AGACHADO, 0.2, 8), (AGACHADO, 0.1, None), (AGACHADO, 0.2, 8),
                          (AGACHADO, 0.5, 7), (CON_CAJA, 1.5, 3)])
    terminados, _ = correr(MaquinaLevantamiento(), secuencia)
    assert terminados[0].puntaje == 7  # los 8 no llegaron a sostenerse 0,3 s seguidos


def test_levantamiento_sin_ningun_puntaje_termina_sin_evaluar():
    terminados, _ = correr(MaquinaLevantamiento(), muestras([(DE_PIE, 0.5, None), (AGACHADO, 1.0, None),
                                                            (CON_CAJA, 1.5, None)]))
    assert len(terminados) == 1 and terminados[0].puntaje is None and terminados[0].critico is None


def test_si_solo_se_pudo_puntuar_de_pie_el_levantamiento_queda_sin_evaluar():
    """Visto en vivo: agachado no se veía el cuerpo completo y el intento salía "3 bajo" con la
    postura de pie. Los fotogramas erguidos no pueden ser el fotograma crítico."""
    terminados, _ = correr(MaquinaLevantamiento(), muestras([(DE_PIE, 0.5, 3), (AGACHADO, 1.5, None),
                                                            (CON_CAJA, 1.5, 3)]))
    assert len(terminados) == 1 and terminados[0].puntaje is None


def test_el_critico_nunca_es_un_fotograma_erguido():
    terminados, _ = correr(MaquinaLevantamiento(), muestras([(DE_PIE, 0.5, 9), (AGACHADO, 1.0, 5),
                                                            (CON_CAJA, 1.5, 9)]))
    assert [lev.puntaje for lev in terminados] == [5]


def test_un_gesto_muy_corto_no_cuenta():
    terminados, estados = correr(MaquinaLevantamiento(), muestras([(DE_PIE, 0.5, 3), (AGACHADO, 0.3, 8),
                                                                  (CON_CAJA, 1.5, 3)]))
    assert terminados == [] and Estado.LEVANTANDO in estados


def test_tiempo_maximo():
    maquina = MaquinaLevantamiento(Umbrales(duracion_maxima_s=3.0))
    terminados, _ = correr(maquina, muestras([(DE_PIE, 0.5, 3), (AGACHADO, 4.0, 8)]))
    assert len(terminados) == 1
    assert terminados[0].motivo_fin == "tiempo_maximo" and terminados[0].puntaje == 8
    assert terminados[0].duracion_s == pytest.approx(3.0, abs=0.05)


def test_si_la_persona_sale_del_cuadro_se_abandona():
    terminados, estados = correr(MaquinaLevantamiento(), muestras([(DE_PIE, 0.5, 3), (AGACHADO, 1.0, 8),
                                                                  (None, 2.0, None), (DE_PIE, 1.0, 3)]))
    assert terminados == []
    assert estados[-2:] == [Estado.SIN_PERSONA, Estado.PERSONA_LISTA]


def test_una_perdida_breve_de_la_persona_no_abandona():
    terminados, _ = correr(MaquinaLevantamiento(), muestras([(DE_PIE, 0.5, 3), (AGACHADO, 0.6, 8), (None, 0.5, None),
                                                            (AGACHADO, 0.6, 8), (CON_CAJA, 1.5, 3)]))
    assert [lev.puntaje for lev in terminados] == [8]


def test_modo_manual_con_la_barra_espaciadora():
    secuencia = muestras([(DE_PIE, 0.5, 3), (AGACHADO, 1.0, 8), (CON_CAJA, 2.0, 3)])
    sin_pulsar, estados = correr(MaquinaLevantamiento(), secuencia, modo="manual")
    assert sin_pulsar == [] and Estado.LEVANTANDO not in estados  # en manual nada empieza solo
    terminados, _ = correr(MaquinaLevantamiento(), secuencia, modo="manual", pulsar_en={15, 60})
    assert len(terminados) == 1
    assert terminados[0].motivo_fin == "manual" and terminados[0].puntaje == 8
    assert terminados[0].duracion_s == pytest.approx(1.5, abs=0.05)


def test_la_barra_tambien_fuerza_el_fin_en_modo_auto():
    terminados, _ = correr(MaquinaLevantamiento(), muestras([(DE_PIE, 0.5, 3), (AGACHADO, 2.0, 8)]), pulsar_en={45})
    assert len(terminados) == 1 and terminados[0].motivo_fin == "manual"


def test_sin_persona_la_barra_no_empieza_nada():
    terminados, estados = correr(MaquinaLevantamiento(), muestras([(None, 1.0, None)]), pulsar_en={5})
    assert terminados == [] and estados == [Estado.SIN_PERSONA]


def test_umbrales_configurables():
    suave = [(DE_PIE, 0.5, 3), (dict(tronco=15.0, rodilla=5.0, muneca_y=420.0), 1.0, 4), (CON_CAJA, 1.5, 3)]
    assert correr(MaquinaLevantamiento(), muestras(suave))[0] == []  # 15° no llega al umbral de 20°
    terminados, _ = correr(MaquinaLevantamiento(Umbrales(tronco_inicio=10.0, tronco_erguido=9.0)), muestras(suave))
    assert [lev.puntaje for lev in terminados] == [4]


# --------------------------------------------------------------------------- #
# Intentos
# --------------------------------------------------------------------------- #
MALA = calcular_reba({"tronco": 95, "cuello": -15, "piernas": 25, "brazo": 100, "antebrazo": 15, "muneca": 20,
                      "brazo_vertical": 5})
BUENA = calcular_reba({"tronco": 50, "cuello": 8, "piernas": 120, "brazo": 60, "antebrazo": 30, "muneca": 8,
                       "brazo_vertical": 10})


def test_normalizar_sesion():
    assert normalizar_sesion("142") == "V-0142"
    assert normalizar_sesion("7") == "V-0007"
    assert normalizar_sesion("12345") == "V-12345"
    assert normalizar_sesion("") is None and normalizar_sesion("abc") is None


def test_intentos_numerados_y_comparacion():
    visita = Visita("V-0142")
    assert visita.comparacion() is None and visita.ultimo is None
    primero = visita.registrar(MALA, 2.1)
    assert (primero.numero, primero.puntaje, primero.nivel) == (1, 8, "alto")
    assert primero.resumen() == "Intento 1: 8 alto"
    assert visita.comparacion() is None  # con un solo intento no hay qué comparar
    segundo = visita.registrar(BUENA, 2.4)
    assert (segundo.numero, segundo.puntaje, segundo.nivel) == (2, 6, "medio")
    comparacion = visita.comparacion()
    assert comparacion.texto() == "Intento 1: 8 alto → Intento 2: 6 medio"
    assert comparacion.diferencia == -2
    assert comparacion.cambios == [("tronco", 4, 3), ("cuello", 2, 1), ("piernas", 1, 3), ("brazo", 3, 2),
                                   ("muneca", 2, 1)]
    assert comparacion.texto_cambios() == "Tronco 4 → 3 · Cuello 2 → 1 · Piernas 1 → 3 · Brazo 3 → 2 · Muñeca 2 → 1"


def test_la_comparacion_es_siempre_entre_los_dos_ultimos():
    visita = Visita()
    for resultado in (MALA, BUENA, MALA):
        visita.registrar(resultado, 2.0)
    assert visita.comparacion().texto() == "Intento 2: 6 medio → Intento 3: 8 alto"
    assert visita.comparacion().diferencia == 2


def test_nivel_muy_alto_se_escribe_con_espacio():
    extremo = calcular_reba({"tronco": 95, "cuello": 40, "piernas": 90, "brazo": 120, "antebrazo": 20, "muneca": 30},
                            Condiciones(peso_carga_kg=20, agarre="malo", actividad_cambios_rapidos=True))
    visita = Visita()
    visita.registrar(MALA, 1.0)
    intento = visita.registrar(extremo, 1.0)
    assert intento.nivel == "muy_alto" and intento.resumen().endswith("muy alto")


def test_no_se_registra_un_intento_sin_reba_completo():
    incompleto = calcular_reba({"tronco": 30, "cuello": 10, "piernas": None, "brazo": 20, "antebrazo": 80})
    with pytest.raises(ValueError):
        Visita().registrar(incompleto, 1.0)


def test_visita_vacia():
    assert Visita().vacia
    assert not Visita("V-0001").vacia
    visita = Visita()
    visita.registrar(MALA, 1.0)
    assert not visita.vacia
