"""Máquina de estados de la zona con secuencias simuladas, fotograma a fotograma.

Cada persona es un recorrido: la posición de su punto de apoyo en cada fotograma (None si
en ese fotograma no se ve). La zona es un cuadrado de (400, 300) a (800, 600) píxeles con
una franja de advertencia de 80 píxeles.
"""

import pytest

from modulos.comun import construir_evento
from modulos.zona.nucleo import EstadoZona, MonitorZona, Parametros, crear_zona

FPS = 30
ANCHO, ALTO = 1280, 720
CUADRADO = [[400 / ANCHO, 300 / ALTO], [800 / ANCHO, 300 / ALTO], [800 / ANCHO, 600 / ALTO], [400 / ANCHO, 600 / ALTO]]

LEJOS = (100.0, 450.0)       # a 300 px del lado izquierdo
CERCA = (350.0, 450.0)       # a 50 px: dentro de la franja de advertencia
DENTRO = (600.0, 450.0)      # en el centro de la zona
LEJOS_DERECHA = (1100.0, 450.0)
CERCA_DERECHA = (850.0, 450.0)


# ----------------------------------------------------------------- utilidades
def monitor_px(**parametros) -> MonitorZona:
    return MonitorZona(crear_zona("piso", CUADRADO, ANCHO, ALTO, margen_px=80), Parametros(**parametros))


def monitor_m() -> MonitorZona:
    # 400 x 300 píxeles para 2 x 1,5 metros: 200 píxeles por metro
    zona = crear_zona("piso", CUADRADO, ANCHO, ALTO, margen_m=0.5, rectangulo_real={"ancho_m": 2.0, "largo_m": 1.5})
    return MonitorZona(zona)


def quieto(punto, segundos):
    return [punto] * round(segundos * FPS)


def tramo(desde, hasta, segundos):
    """Posiciones de quien camina en línea recta de ``desde`` a ``hasta`` en ese tiempo."""
    pasos = round(segundos * FPS)
    return [(desde[0] + (hasta[0] - desde[0]) * i / pasos, desde[1] + (hasta[1] - desde[1]) * i / pasos)
            for i in range(1, pasos + 1)]


def ausente(segundos):
    return [None] * round(segundos * FPS)


def alternar(a, b, segundos, cada=1):
    """Salta entre ``a`` y ``b`` cada ``cada`` fotogramas: una detección que tiembla."""
    return [a if (i // cada) % 2 == 0 else b for i in range(round(segundos * FPS))]


def simular(monitor, recorridos, alarma_activa=True):
    """Corre el monitor sobre los recorridos. Devuelve la lista de (t, Resultado)."""
    resultados = []
    for i in range(max(len(recorrido) for recorrido in recorridos.values())):
        observaciones = {persona: [recorrido[i]] for persona, recorrido in recorridos.items()
                         if i < len(recorrido) and recorrido[i] is not None}
        t = i / FPS
        resultados.append((t, monitor.actualizar(t, observaciones, alarma_activa)))
    return resultados


def eventos(resultados, tipo, con_refrescos=False):
    return [evento for _, resultado in resultados for evento in resultado.eventos
            if evento.tipo == tipo and (con_refrescos or not evento.datos.get("refresco"))]


def estados(resultados):
    """Estados por los que pasó la zona, según los estado_zona publicados (sin refrescos)."""
    return [(e.datos["estado"], e.datos["personas_peligro"], e.datos["personas_advertencia"])
            for e in eventos(resultados, "estado_zona")]


def nombres(resultados):
    return [estado for estado, _, _ in estados(resultados)]


def instantes(resultados, tipo, **datos):
    """Momentos en que se publicó un evento de ese tipo con esos datos."""
    return [t for t, resultado in resultados for evento in resultado.eventos
            if evento.tipo == tipo and all(evento.datos.get(clave) == valor for clave, valor in datos.items())]


def instante(resultados, tipo, **datos):
    """Momento en que se publicó el primer evento de ese tipo con esos datos."""
    momentos = instantes(resultados, tipo, **datos)
    assert momentos, f"no se publicó {tipo} con {datos}"
    return momentos[0]


# -------------------------------------------------------------- casi-accidente
def test_acercarse_y_alejarse_registra_un_casi_accidente():
    recorrido = (quieto(LEJOS, 0.5) + tramo(LEJOS, CERCA, 1) + quieto(CERCA, 1)
                 + tramo(CERCA, LEJOS, 1) + quieto(LEJOS, 1))
    resultados = simular(monitor_px(), {1: recorrido})

    assert estados(resultados) == [("libre", 0, 0), ("advertencia", 0, 1), ("libre", 0, 0)]
    casi = eventos(resultados, "casi_accidente")
    assert len(casi) == 1
    assert casi[0].severidad == "alta"
    assert casi[0].persona_id == 1
    assert casi[0].datos["zona_id"] == "piso"
    assert casi[0].datos["distancia_min_px"] == pytest.approx(50.0)
    assert eventos(resultados, "ingreso_zona") == []
    # El casi-accidente sale cuando la persona vuelve a quedar libre (empieza a alejarse a los 2,5 s)
    assert instante(resultados, "casi_accidente") == instantes(resultados, "estado_zona", estado="libre")[-1]
    assert instante(resultados, "casi_accidente") == pytest.approx(2.97, abs=2 / FPS)


def test_sin_homografia_el_casi_accidente_no_habla_de_metros():
    recorrido = tramo(LEJOS, CERCA, 1) + quieto(CERCA, 1) + tramo(CERCA, LEJOS, 1) + quieto(LEJOS, 1)
    (casi,) = eventos(simular(monitor_px(), {1: recorrido}), "casi_accidente")
    assert "distancia_min_m" not in casi.datos
    assert " m " not in casi.datos["descripcion"] and "metro" not in casi.datos["descripcion"]


def test_con_homografia_el_casi_accidente_trae_la_distancia_en_metros():
    recorrido = tramo(LEJOS, CERCA, 1) + quieto(CERCA, 1) + tramo(CERCA, LEJOS, 1) + quieto(LEJOS, 1)
    (casi,) = eventos(simular(monitor_m(), {1: recorrido}), "casi_accidente")
    assert casi.datos["distancia_min_m"] == pytest.approx(0.25)   # 50 px a 200 px por metro
    assert casi.datos["distancia_min_px"] == pytest.approx(50.0)
    assert "0,25 m" in casi.datos["descripcion"]


def test_pasar_de_largo_sin_detenerse_no_cuenta():
    # Cruza la franja de advertencia en 0,2 s: menos que el antirrebote
    recorrido = quieto(LEJOS, 0.5) + quieto(CERCA, 0.2) + quieto(LEJOS, 1)
    resultados = simular(monitor_px(), {1: recorrido})
    assert estados(resultados) == [("libre", 0, 0)]
    assert eventos(resultados, "casi_accidente") == []


def test_rozar_el_borde_sin_quedarse_dentro_es_casi_accidente_con_distancia_cero():
    # En advertencia, mete el pie 0,2 s (no alcanza a confirmarse el peligro) y se va
    recorrido = quieto(CERCA, 1) + quieto(DENTRO, 0.2) + quieto(CERCA, 0.5) + quieto(LEJOS, 1)
    resultados = simular(monitor_px(), {1: recorrido})
    assert nombres(resultados) == ["libre", "advertencia", "libre"]
    (casi,) = eventos(resultados, "casi_accidente")
    assert casi.datos["distancia_min_px"] == 0.0
    assert eventos(resultados, "ingreso_zona") == []


# --------------------------------------------------------------------- ingreso
def test_entrar_pone_la_zona_en_peligro_y_salir_registra_el_ingreso_con_su_duracion():
    recorrido = (quieto(LEJOS, 0.5) + tramo(LEJOS, DENTRO, 2) + quieto(DENTRO, 3)
                 + tramo(DENTRO, LEJOS, 2) + quieto(LEJOS, 1))
    resultados = simular(monitor_px(), {1: recorrido})

    assert estados(resultados) == [("libre", 0, 0), ("advertencia", 0, 1), ("peligro", 1, 0),
                                   ("advertencia", 0, 1), ("libre", 0, 0)]
    (ingreso,) = eventos(resultados, "ingreso_zona")
    assert ingreso.severidad == "alta"
    assert ingreso.persona_id == 1
    assert ingreso.datos["zona_id"] == "piso"
    assert ingreso.datos["alarma_activada"] is True
    # Pisa la zona 1,2 s después de empezar a caminar y deja de estar dentro 0,86 s después de
    # empezar a volver: 0,8 + 3 + 0,86 = 4,66 s (la duración no incluye la espera del antirrebote)
    assert ingreso.datos["duracion_s"] == pytest.approx(4.7, abs=0.1)
    # Quien entró no genera además un casi-accidente
    assert eventos(resultados, "casi_accidente") == []
    # El ingreso se publica al salir de la zona, antes de que la persona quede libre
    assert instante(resultados, "ingreso_zona") == instantes(resultados, "estado_zona", estado="advertencia")[-1]
    assert instante(resultados, "ingreso_zona") < instantes(resultados, "estado_zona", estado="libre")[-1]


def test_el_peligro_se_confirma_a_los_0_3_s_de_pisar_la_zona():
    resultados = simular(monitor_px(), {1: quieto(LEJOS, 1) + quieto(DENTRO, 2)})
    assert instante(resultados, "estado_zona", estado="peligro") == pytest.approx(1.3, abs=1 / FPS)


def test_el_momento_de_entrada_se_marca_una_sola_vez_para_la_foto():
    recorrido = quieto(LEJOS, 0.5) + tramo(LEJOS, DENTRO, 1) + quieto(DENTRO, 2) + tramo(DENTRO, LEJOS, 1)
    resultados = simular(monitor_px(), {1: recorrido})
    marcas = [t for t, resultado in resultados for persona in resultado.personas if persona.entro_a_peligro]
    assert marcas == [instante(resultados, "estado_zona", estado="peligro")]


def test_el_minimo_del_acercamiento_se_marca_mientras_la_persona_se_acerca():
    recorrido = quieto(LEJOS, 0.5) + tramo(LEJOS, CERCA, 1) + quieto(CERCA, 1) + tramo(CERCA, LEJOS, 1)
    resultados = simular(monitor_px(), {1: recorrido})
    marcas = [(t, persona.medida.distancia_px) for t, resultado in resultados
              for persona in resultado.personas if persona.nuevo_minimo]
    distancias = [distancia for _, distancia in marcas]
    assert distancias == sorted(distancias, reverse=True)          # cada marca mejora la anterior
    assert distancias[-1] == pytest.approx(50.0)                   # la última es el punto más cercano
    assert marcas[-1][0] == pytest.approx(1.5, abs=2 / FPS)        # y cae cuando llega, no después


def test_si_la_alarma_no_estaba_activa_el_ingreso_lo_dice():
    recorrido = quieto(DENTRO, 2) + quieto(LEJOS, 1)
    (ingreso,) = eventos(simular(monitor_px(), {1: recorrido}, alarma_activa=False), "ingreso_zona")
    assert ingreso.datos["alarma_activada"] is False


def test_entrar_dos_veces_en_el_mismo_acercamiento_da_dos_ingresos():
    recorrido = quieto(DENTRO, 1) + quieto(CERCA, 1) + quieto(DENTRO, 1) + quieto(LEJOS, 1)
    resultados = simular(monitor_px(), {1: recorrido})
    assert nombres(resultados) == ["libre", "peligro", "advertencia", "peligro", "libre"]
    assert len(eventos(resultados, "ingreso_zona")) == 2
    assert eventos(resultados, "casi_accidente") == []


# --------------------------------------------------------------- dos personas
def test_dos_personas_a_la_vez_cada_una_con_su_evento():
    # La 1 entra a la zona y se queda; mientras tanto la 2 se acerca por el otro lado y se va
    persona_1 = (quieto(LEJOS, 0.5) + tramo(LEJOS, DENTRO, 1) + quieto(DENTRO, 5)
                 + tramo(DENTRO, LEJOS, 1) + quieto(LEJOS, 1.5))
    persona_2 = (quieto(LEJOS_DERECHA, 2.5) + tramo(LEJOS_DERECHA, CERCA_DERECHA, 1) + quieto(CERCA_DERECHA, 1)
                 + tramo(CERCA_DERECHA, LEJOS_DERECHA, 1) + quieto(LEJOS_DERECHA, 3.5))
    resultados = simular(monitor_px(), {1: persona_1, 2: persona_2})

    assert estados(resultados) == [
        ("libre", 0, 0),
        ("advertencia", 0, 1),   # la 1 se acerca
        ("peligro", 1, 0),       # la 1 entra
        ("peligro", 1, 1),       # la 2 se acerca: la zona sigue en peligro, cambia el conteo
        ("peligro", 1, 0),       # la 2 se va
        ("advertencia", 0, 1),   # la 1 sale de la zona
        ("libre", 0, 0),
    ]
    (casi,) = eventos(resultados, "casi_accidente")
    (ingreso,) = eventos(resultados, "ingreso_zona")
    assert casi.persona_id == 2 and casi.datos["distancia_min_px"] == pytest.approx(50.0)
    assert ingreso.persona_id == 1 and ingreso.datos["duracion_s"] == pytest.approx(5.8, abs=0.15)


def test_con_dos_personas_dentro_la_zona_sigue_en_peligro_hasta_que_sale_la_ultima():
    monitor = monitor_px()
    persona_1 = quieto(DENTRO, 4)
    persona_2 = ausente(1) + quieto((700.0, 500.0), 1.5) + quieto(LEJOS_DERECHA, 1.5)   # entra y sale
    resultados = simular(monitor, {1: persona_1, 2: persona_2})

    assert estados(resultados) == [("libre", 0, 0), ("peligro", 1, 0), ("peligro", 2, 0), ("peligro", 1, 0)]
    (ingreso,) = eventos(resultados, "ingreso_zona")
    assert ingreso.persona_id == 2
    assert ingreso.datos["duracion_s"] == pytest.approx(1.5, abs=0.1)
    assert monitor.estado == EstadoZona("peligro", 1, 0)


# ------------------------------------------------------------------- parpadeo
@pytest.mark.parametrize("cada", [1, 5])
def test_temblar_en_el_limite_de_la_franja_no_cambia_el_estado(cada):
    # Salta entre 70 px (dentro del margen) y 90 px (fuera) cada 1 o 5 fotogramas (0,17 s)
    recorrido = alternar((330.0, 450.0), (310.0, 450.0), 3, cada)
    resultados = simular(monitor_px(), {1: recorrido})
    assert estados(resultados) == [("libre", 0, 0)]
    assert sum(len(resultado.eventos) for _, resultado in resultados) == 1   # solo el estado inicial


def test_un_salto_fugaz_dentro_de_la_zona_no_dispara_la_alarma():
    recorrido = quieto(LEJOS, 1) + quieto(DENTRO, 5 / FPS) + quieto(LEJOS, 1)
    resultados = simular(monitor_px(), {1: recorrido})
    assert estados(resultados) == [("libre", 0, 0)]
    assert not any(persona.entro_a_peligro for _, resultado in resultados for persona in resultado.personas)


def test_perder_el_punto_un_instante_no_apaga_la_alarma_ni_parte_el_ingreso():
    # Dentro de la zona, la detección salta lejos 0,2 s dos veces y vuelve
    recorrido = (quieto(DENTRO, 1) + quieto(LEJOS, 0.2) + quieto(DENTRO, 1) + quieto(LEJOS, 0.2)
                 + quieto(DENTRO, 1) + quieto(LEJOS, 1))
    resultados = simular(monitor_px(), {1: recorrido})
    assert nombres(resultados) == ["libre", "peligro", "libre"]
    (ingreso,) = eventos(resultados, "ingreso_zona")
    assert ingreso.datos["duracion_s"] == pytest.approx(3.4, abs=0.1)


def test_temblar_sobre_el_borde_de_la_zona_deja_la_advertencia_y_no_parpadea():
    # Un pie que salta en cada fotograma entre 5 px fuera y 5 px dentro de la zona
    recorrido = alternar((395.0, 450.0), (405.0, 450.0), 3) + quieto(LEJOS, 1)
    resultados = simular(monitor_px(), {1: recorrido})
    # No se queda en libre (está pegado a la zona) ni llega a peligro (nunca 0,3 s seguidos dentro)
    assert nombres(resultados) == ["libre", "advertencia", "libre"]


def test_la_histeresis_sostiene_el_peligro_junto_al_borde():
    # Ya en peligro, queda parado 10 px fuera del borde: dentro de la banda de histéresis (16 px)
    recorrido = quieto(DENTRO, 1) + quieto((390.0, 450.0), 2)
    monitor = monitor_px()
    resultados = simular(monitor, {1: recorrido})
    assert nombres(resultados) == ["libre", "peligro"]
    assert monitor.estado.estado == "peligro"


def test_sin_antirrebote_los_cambios_son_inmediatos():
    resultados = simular(monitor_px(antirrebote_s=0.0), {1: quieto(LEJOS, 0.1) + quieto(DENTRO, 0.1) + quieto(LEJOS, 0.1)})
    assert nombres(resultados) == ["libre", "peligro", "libre"]
    assert instante(resultados, "estado_zona", estado="peligro") == pytest.approx(0.1)


# --------------------------------------------------------- personas que se pierden
def en_peligro_todo_el_tiempo(resultados, desde, hasta):
    """True si la zona estuvo en peligro en cada fotograma entre esos dos momentos."""
    tramo_de_interes = [resultado for t, resultado in resultados if desde <= t <= hasta]
    return bool(tramo_de_interes) and all(resultado.estado.estado == "peligro" for resultado in tramo_de_interes)


def test_quien_se_oculta_3_s_dentro_de_la_zona_y_reaparece_tiene_un_solo_ingreso():
    # Dentro 2 s, tapada por la máquina 3 s, vuelve a verse dentro 1 s y sale
    recorrido = quieto(DENTRO, 2) + ausente(3) + quieto(DENTRO, 1) + quieto(LEJOS, 1)
    resultados = simular(monitor_px(), {1: recorrido})

    assert nombres(resultados) == ["libre", "peligro", "libre"]
    assert en_peligro_todo_el_tiempo(resultados, 0.35, 6.2)      # la alarma nunca se apaga
    (ingreso,) = eventos(resultados, "ingreso_zona")
    assert ingreso.datos["duracion_s"] == pytest.approx(6.0, abs=0.1)   # cuenta también el tiempo oculta
    # Mientras está oculta, el estado se sigue refrescando: la alarma de la plataforma sigue viva
    refrescos = instantes(resultados, "estado_zona", refresco=True)
    assert [t for t in refrescos if 2.0 < t < 5.0] != []


def test_quien_se_oculta_dentro_y_reaparece_con_otro_id_es_la_misma_persona():
    # El tracker la pierde tras la máquina y, 3 s después, le da un id nuevo a pocos pasos
    persona_1 = quieto(DENTRO, 2)
    persona_2 = ausente(5) + quieto((680.0, 520.0), 1) + quieto(LEJOS, 1)
    resultados = simular(monitor_px(), {1: persona_1, 2: persona_2})

    assert estados(resultados) == [("libre", 0, 0), ("peligro", 1, 0), ("libre", 0, 0)]   # nunca dos personas
    assert en_peligro_todo_el_tiempo(resultados, 0.35, 6.2)
    (ingreso,) = eventos(resultados, "ingreso_zona")
    assert ingreso.persona_id == 2                                       # sale con el id vigente
    assert ingreso.datos["duracion_s"] == pytest.approx(6.0, abs=0.1)    # y con el historial de la primera
    herencias = [(t, persona.persona_id, persona.heredada_de) for t, resultado in resultados
                 for persona in resultado.personas if persona.heredada_de is not None]
    assert herencias == [(pytest.approx(5.0), 2, 1)]                     # se avisa una vez, al reaparecer
    # No vuelve a marcar la entrada: la foto del ingreso es la de la primera vez
    assert sum(persona.entro_a_peligro for _, resultado in resultados for persona in resultado.personas) == 1


def test_quien_se_deja_de_ver_dentro_de_la_zona_y_no_reaparece_se_cierra_a_los_4_s():
    resultados = simular(monitor_px(), {1: quieto(DENTRO, 2) + ausente(5)})
    assert nombres(resultados) == ["libre", "peligro", "libre"]
    assert en_peligro_todo_el_tiempo(resultados, 0.35, 5.9)             # 4 s de alarma tras dejar de verla
    (ingreso,) = eventos(resultados, "ingreso_zona")
    assert ingreso.datos["duracion_s"] == pytest.approx(2.0, abs=0.1)   # hasta la última vez que se vio
    assert instante(resultados, "ingreso_zona") == pytest.approx(6.0, abs=2 / FPS)
    assert instante(resultados, "ingreso_zona") == instantes(resultados, "estado_zona", estado="libre")[-1]


def test_la_espera_de_quien_se_oculta_dentro_es_configurable():
    resultados = simular(monitor_px(segundos_perdida_peligro=2.0), {1: quieto(DENTRO, 2) + ausente(5)})
    assert instante(resultados, "ingreso_zona") == pytest.approx(4.0, abs=2 / FPS)


def test_un_id_nuevo_que_aparece_dentro_cuando_ya_paso_la_espera_es_otra_persona():
    persona_1 = quieto(DENTRO, 2)
    persona_2 = ausente(7) + quieto((680.0, 520.0), 1) + quieto(LEJOS, 1)   # 5 s después: ya se cerró
    resultados = simular(monitor_px(), {1: persona_1, 2: persona_2})
    assert nombres(resultados) == ["libre", "peligro", "libre", "peligro", "libre"]
    assert [evento.persona_id for evento in eventos(resultados, "ingreso_zona")] == [1, 2]


def test_un_id_nuevo_que_aparece_fuera_de_la_zona_no_hereda_a_la_oculta():
    # Mientras la 1 está oculta dentro, la 2 aparece cerca, por fuera: es otra persona
    persona_1 = quieto(DENTRO, 2)
    persona_2 = ausente(3) + quieto(CERCA, 5)
    resultados = simular(monitor_px(), {1: persona_1, 2: persona_2})
    assert ("peligro", 1, 1) in estados(resultados)
    (ingreso,) = eventos(resultados, "ingreso_zona")
    assert ingreso.persona_id == 1 and ingreso.datos["duracion_s"] == pytest.approx(2.0, abs=0.1)
    assert not any(persona.heredada_de for _, resultado in resultados for persona in resultado.personas)


def test_con_dos_ocultas_el_id_nuevo_hereda_a_la_mas_cercana():
    izquierda, derecha = (450.0, 450.0), (750.0, 450.0)
    persona_1 = quieto(izquierda, 2)                       # las dos se dejan de ver a los 2 s
    persona_2 = quieto(derecha, 2)
    persona_3 = ausente(4) + quieto((730.0, 460.0), 3)     # reaparece junto a la de la derecha
    resultados = simular(monitor_px(), {1: persona_1, 2: persona_2, 3: persona_3})
    herencias = [(persona.persona_id, persona.heredada_de) for _, resultado in resultados
                 for persona in resultado.personas if persona.heredada_de is not None]
    assert herencias == [(3, 2)]
    # La de la izquierda no reapareció: su ingreso se cierra a los 4 s; la otra sigue dentro
    (ingreso,) = eventos(resultados, "ingreso_zona")
    assert ingreso.persona_id == 1
    assert resultados[-1][1].estado == EstadoZona("peligro", 1, 0)


def test_quien_ya_iba_saliendo_no_cuenta_como_oculta_dentro():
    # Confirmada en peligro, da un paso fuera de la zona y se deja de ver antes de que se confirme la salida
    recorrido = quieto(DENTRO, 1) + quieto(LEJOS, 0.1) + ausente(3)
    resultados = simular(monitor_px(), {1: recorrido})
    assert nombres(resultados) == ["libre", "peligro", "libre"]
    assert instante(resultados, "ingreso_zona") == pytest.approx(2.1, abs=2 / FPS)   # espera de 1 s, no de 4


def test_una_oclusion_corta_no_cierra_nada():
    monitor = monitor_px()
    resultados = simular(monitor, {1: quieto(DENTRO, 1) + ausente(0.5) + quieto(DENTRO, 1)})
    assert nombres(resultados) == ["libre", "peligro"]
    assert eventos(resultados, "ingreso_zona") == []
    # Mientras no se ve sigue apareciendo, marcada como ausente
    ausentes = [persona for _, resultado in resultados for persona in resultado.personas if not persona.presente]
    assert ausentes and all(persona.estado == "peligro" for persona in ausentes)


def test_quien_se_deja_de_ver_en_la_franja_deja_su_casi_accidente():
    resultados = simular(monitor_px(), {1: quieto(CERCA, 1) + ausente(2)})
    assert nombres(resultados) == ["libre", "advertencia", "libre"]
    assert len(eventos(resultados, "casi_accidente")) == 1


def test_quien_pasa_lejos_no_deja_rastro():
    monitor = monitor_px()
    resultados = simular(monitor, {1: tramo(LEJOS, (100.0, 100.0), 2) + ausente(2)})
    assert sum(len(resultado.eventos) for _, resultado in resultados) == 1
    assert resultados[-1][1].personas == ()   # ya se olvidó


def test_una_persona_sin_puntos_de_apoyo_no_cuenta():
    monitor = monitor_px()
    resultado = monitor.actualizar(0.0, {1: []})
    assert resultado.personas == ()
    assert monitor.estado == EstadoZona("libre", 0, 0)


# ------------------------------------------------------------ estado y refresco
def test_el_primer_fotograma_publica_el_estado_inicial():
    resultado = monitor_px().actualizar(0.0, {})
    (evento,) = resultado.eventos
    assert evento.tipo == "estado_zona" and evento.severidad == "info" and evento.urgente
    assert evento.datos == {"zona_id": "piso", "estado": "libre", "personas_peligro": 0, "personas_advertencia": 0}


def test_mientras_la_zona_no_esta_libre_el_estado_se_refresca_cada_2_s():
    resultados = simular(monitor_px(), {1: quieto(DENTRO, 7) + quieto(LEJOS, 6)})
    refrescos = [(t, evento) for t, resultado in resultados for evento in resultado.eventos
                 if evento.datos.get("refresco")]
    # Peligro confirmado a los 0,3 s; refrescos a los 2,3, 4,3 y 6,3 s; después sale y queda libre
    assert [t for t, _ in refrescos] == pytest.approx([2.3, 4.3, 6.3], abs=1 / FPS)
    for _, evento in refrescos:
        assert evento.tipo == "estado_zona" and evento.urgente and evento.severidad == "alta"
        assert evento.datos == {"zona_id": "piso", "estado": "peligro", "personas_peligro": 1,
                                "personas_advertencia": 0, "refresco": True}
    # Los cambios de verdad no llevan la marca, y en libre no hay refrescos
    assert all("refresco" not in evento.datos for evento in eventos(resultados, "estado_zona"))
    assert nombres(resultados) == ["libre", "peligro", "libre"]


def test_el_refresco_se_cuenta_desde_el_ultimo_estado_publicado():
    # La 2 se acerca a los 1,5 s: ese cambio de conteo reinicia la cuenta del refresco
    persona_1 = quieto(DENTRO, 5)
    persona_2 = ausente(1.5) + quieto(CERCA_DERECHA, 3.5)
    resultados = simular(monitor_px(), {1: persona_1, 2: persona_2})
    cambio = instante(resultados, "estado_zona", personas_advertencia=1)
    primer_refresco = instante(resultados, "estado_zona", refresco=True)
    assert primer_refresco == pytest.approx(cambio + 2.0, abs=1 / FPS)


def test_severidad_de_cada_estado():
    recorrido = quieto(LEJOS, 0.5) + quieto(CERCA, 1) + quieto(DENTRO, 1) + quieto(LEJOS, 1)
    severidades = {e.datos["estado"]: e.severidad for e in eventos(simular(monitor_px(), {1: recorrido}), "estado_zona")}
    assert severidades == {"libre": "info", "advertencia": "media", "peligro": "alta"}


def test_los_eventos_de_estado_van_primero_y_son_los_unicos_urgentes():
    recorrido = quieto(DENTRO, 1) + quieto(LEJOS, 1)
    for _, resultado in simular(monitor_px(), {1: recorrido}):
        tipos = [evento.tipo for evento in resultado.eventos]
        if "estado_zona" in tipos:
            assert tipos[0] == "estado_zona"
        assert all(evento.urgente == (evento.tipo == "estado_zona") for evento in resultado.eventos)


# --------------------------------------------------------------------- cierre
def test_cerrar_despide_a_todos_y_deja_la_zona_libre():
    monitor = monitor_px()
    simular(monitor, {1: quieto(DENTRO, 2), 2: quieto(CERCA_DERECHA, 2)})
    assert monitor.estado == EstadoZona("peligro", 1, 1)

    cierre = monitor.cerrar(2.0)
    assert [evento.tipo for evento in cierre][0] == "estado_zona"
    assert cierre[0].datos["estado"] == "libre"
    assert sorted(evento.tipo for evento in cierre[1:]) == ["casi_accidente", "ingreso_zona"]
    assert monitor.estado == EstadoZona("libre", 0, 0)
    assert monitor.cerrar(3.0) == ()   # cerrar dos veces no repite nada


# ------------------------------------------------------------------- contrato
@pytest.mark.parametrize("monitor", [monitor_px, monitor_m], ids=["pixeles", "metros"])
def test_todo_lo_que_sale_de_una_secuencia_cumple_el_contrato(monitor, monkeypatch):
    monkeypatch.setenv("DISPOSITIVO", "pc-pruebas")
    persona_1 = (quieto(LEJOS, 0.5) + tramo(LEJOS, DENTRO, 1) + quieto(DENTRO, 5)
                 + tramo(DENTRO, LEJOS, 1) + quieto(LEJOS, 1.5))
    persona_2 = (quieto(LEJOS_DERECHA, 2.5) + tramo(LEJOS_DERECHA, CERCA_DERECHA, 1) + quieto(CERCA_DERECHA, 1)
                 + tramo(CERCA_DERECHA, LEJOS_DERECHA, 1) + quieto(LEJOS_DERECHA, 3.5))
    resultados = simular(monitor(), {1: persona_1, 2: persona_2})
    publicados = [evento for _, resultado in resultados for evento in resultado.eventos]

    assert {evento.tipo for evento in publicados} == {"estado_zona", "ingreso_zona", "casi_accidente"}
    assert any(evento.datos.get("refresco") for evento in publicados)
    for evento in publicados:   # construir_evento valida contra contrato/evento.schema.json
        construir_evento("zona", evento.tipo, evento.datos, evento.severidad)
