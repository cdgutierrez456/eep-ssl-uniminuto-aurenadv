"""Qué significa un puntaje REBA: textos por nivel, pistas contextuales y sección del reporte."""

import json

import pytest

from modulos.ergonomia.nucleo import mensajes
from modulos.ergonomia.nucleo.levantamiento import MaquinaLevantamiento
from modulos.ergonomia.nucleo.mensajes import (
    RUTA_MENSAJES,
    cierre_varios_intentos,
    linea_fija,
    mensaje_de_nivel,
    mensaje_de_puntaje,
    pista_contextual,
    seccion_que_significa,
)
from modulos.ergonomia.nucleo.reba import nivel_de_riesgo

from .test_levantamiento import AGACHADO, CON_CAJA, DE_PIE, correr, muestras

# Lo que debe decir cada nivel (el contenido lo define el archivo de datos; aquí se fija lo acordado)
ESPERADO = {
    "insignificante": ("Riesgo insignificante",
                       "Esta postura no representa un riesgo relevante, aun repetida en un trabajo.",
                       "No es necesario intervenir."),
    "bajo": ("Riesgo bajo", "Si esta postura se repite en un trabajo, el riesgo es bajo.",
             "Puede ser necesario intervenir."),
    "medio": ("Riesgo medio · intervenir", "Si esta postura se repite en un trabajo, la tarea debería modificarse.",
              "Es necesario intervenir."),
    "alto": ("Riesgo alto · intervenir pronto",
             "Si esta postura se repite en un trabajo, la tarea debe modificarse pronto.",
             "Es necesario intervenir pronto."),
    "muy_alto": ("Riesgo muy alto · intervenir ya",
                 "Si esta postura se repite en un trabajo, la tarea debe modificarse de inmediato.",
                 "Es necesario intervenir de inmediato."),
}
NIVEL_DE_PUNTAJE = {1: "insignificante", 2: "bajo", 3: "bajo", 4: "medio", 5: "medio", 6: "medio", 7: "medio",
                    8: "alto", 9: "alto", 10: "alto", 11: "muy_alto", 12: "muy_alto", 13: "muy_alto",
                    14: "muy_alto", 15: "muy_alto"}
PISTA_PISO = ("Desde el piso, incluso con buena técnica, el riesgo rara vez baja de medio. "
              "Lo que más lo reduce es elevar la carga.")
PISTA_ELEVADA = "Elevar la carga es un control de ingeniería: cambia la tarea, no solo la técnica."


@pytest.mark.parametrize("puntaje", range(1, 16))
def test_cada_puntaje_devuelve_el_mensaje_de_su_nivel(puntaje):
    nivel = NIVEL_DE_PUNTAJE[puntaje]
    mensaje = mensaje_de_puntaje(puntaje)
    assert mensaje.nivel == nivel == nivel_de_riesgo(puntaje)
    assert (mensaje.etiqueta, mensaje.panel, mensaje.accion) == ESPERADO[nivel]
    assert mensaje == mensaje_de_nivel(nivel)


@pytest.mark.parametrize("puntaje", [0, 16])
def test_puntaje_fuera_de_rango(puntaje):
    with pytest.raises(ValueError):
        mensaje_de_puntaje(puntaje)


def test_nivel_desconocido():
    with pytest.raises(ValueError):
        mensaje_de_nivel("extremo")


def test_los_textos_viven_en_el_archivo_de_datos_y_estan_completos():
    datos = json.loads(RUTA_MENSAJES.read_text(encoding="utf-8"))
    assert set(datos["niveles"]) == set(ESPERADO)
    for nivel, textos in datos["niveles"].items():
        assert set(textos) == {"etiqueta", "panel", "accion", "ampliado"}
        assert all(texto.strip() for texto in textos.values())
    assert set(datos["pistas"]) == {"desde_piso", "carga_elevada"}
    assert linea_fija() == ("REBA no califica tu técnica: estima el riesgo de una postura si forma parte de un trabajo.")
    assert cierre_varios_intentos() == (
        "La técnica de levantamiento reduce el riesgo; rediseñar la tarea (elevar la carga, acercarla al cuerpo, "
        "reducir su peso) es lo que más lo reduce.")


@pytest.mark.parametrize("nivel", list(ESPERADO))
def test_el_texto_ampliado_habla_de_la_tarea_y_no_culpa_a_la_persona(nivel):
    ampliado = mensaje_de_nivel(nivel).ampliado
    frases = [frase for frase in ampliado.split(". ") if frase.strip()]
    assert 2 <= len(frases) <= 3
    assert "postura" in ampliado.lower()
    for reproche in ("lo hiciste", "hiciste mal", "tu culpa", "mala técnica", "error tuyo", "levantaste mal"):
        assert reproche not in ampliado.lower()


# --------------------------------------------------------------------------- #
# Pistas contextuales: solo en sus condiciones
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("puntaje", range(1, 16))
def test_pista_desde_el_piso_solo_con_reba_de_4_o_mas(puntaje):
    pista = pista_contextual(puntaje, desde_piso=True)
    assert pista == (PISTA_PISO if puntaje >= 4 else None)
    # Desde el piso nunca sale la otra pista, aunque el puntaje haya bajado
    assert pista_contextual(puntaje, desde_piso=True, puntaje_anterior=15) == pista


@pytest.mark.parametrize("puntaje, anterior, esperada", [
    (4, 8, PISTA_ELEVADA),   # carga elevada y el REBA bajó
    (2, 3, PISTA_ELEVADA),   # también en puntajes bajos
    (8, 8, None),            # igual: no bajó
    (9, 5, None),            # subió
    (4, None, None),         # primer intento: no hay con qué comparar
])
def test_pista_de_carga_elevada_solo_si_el_reba_bajo_respecto_al_anterior(puntaje, anterior, esperada):
    assert pista_contextual(puntaje, desde_piso=False, puntaje_anterior=anterior) == esperada


@pytest.mark.parametrize("puntaje, anterior", [(9, None), (4, 9), (1, 2)])
def test_sin_saber_si_fue_desde_el_piso_no_hay_pista(puntaje, anterior):
    assert pista_contextual(puntaje, desde_piso=None, puntaje_anterior=anterior) is None


# --------------------------------------------------------------------------- #
# La máquina sabe si el levantamiento empezó desde el piso
# --------------------------------------------------------------------------- #
def test_desde_el_piso_cuando_las_munecas_bajan_de_las_rodillas():
    terminados, _ = correr(MaquinaLevantamiento(), muestras([(DE_PIE, 0.5, 3), (AGACHADO, 1.0, 8), (CON_CAJA, 1.5, 3)]))
    assert terminados[0].desde_piso is True  # muñecas a 610 px, rodillas a 500 px


def test_carga_elevada_cuando_las_munecas_no_bajan_de_las_rodillas():
    a_media_altura = dict(tronco=50.0, rodilla=10.0, muneca_y=450.0)
    terminados, _ = correr(MaquinaLevantamiento(), muestras([(DE_PIE, 0.5, 3), (a_media_altura, 1.0, 6),
                                                            (CON_CAJA, 1.5, 3)]))
    assert terminados[0].desde_piso is False


def test_un_fotograma_suelto_bajo_las_rodillas_no_cuenta_como_desde_el_piso():
    a_media_altura = dict(tronco=50.0, rodilla=10.0, muneca_y=450.0)
    secuencia = muestras([(DE_PIE, 0.5, 3), (a_media_altura, 0.5, 6), (AGACHADO, 1 / 30, 6), (a_media_altura, 0.5, 6),
                          (CON_CAJA, 1.5, 3)])
    # Un solo fotograma no se sostiene la ventana de 0,3 s: es ruido del estimador, no la carga en el piso
    terminados, _ = correr(MaquinaLevantamiento(), secuencia)
    assert terminados[0].desde_piso is False


# --------------------------------------------------------------------------- #
# Sección del reporte PDF
# --------------------------------------------------------------------------- #
def test_seccion_que_significa_este_resultado():
    seccion = seccion_que_significa(9)
    assert seccion == {
        "titulo": "Qué significa este resultado",
        "etiqueta": "Riesgo alto · intervenir pronto",
        "accion": "Es necesario intervenir pronto.",
        "ampliado": mensaje_de_nivel("alto").ampliado,
        "linea_fija": linea_fija(),
    }


def test_con_varios_intentos_la_seccion_cierra_con_el_rediseno_de_la_tarea():
    assert "cierre" not in seccion_que_significa(5)
    assert seccion_que_significa(5, varios_intentos=True)["cierre"] == cierre_varios_intentos()


def test_los_textos_se_leen_una_sola_vez():
    assert mensajes.cargar_mensajes() is mensajes.cargar_mensajes()
