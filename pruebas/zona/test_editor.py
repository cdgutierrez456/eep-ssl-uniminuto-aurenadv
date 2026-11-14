"""Editor de polígono: clics, arrastres y borrados simulados, sin ventana."""

import pytest

from modulos.zona.calibracion.editor import MAXIMO_DE_VERTICES, EditorPoligono

ANCHO, ALTO = 1280, 720
ESQUINAS = [(300.0, 200.0), (900.0, 200.0), (900.0, 500.0), (300.0, 500.0)]   # horario desde arriba a la izquierda


def editor_con(puntos) -> EditorPoligono:
    editor = EditorPoligono(ANCHO, ALTO)
    for x, y in puntos:
        editor.presionar(x, y)
        editor.soltar()
    return editor


def test_marcar_una_zona_desde_cero_con_cuatro_clics():
    editor = EditorPoligono(ANCHO, ALTO)
    assert not editor.valido and editor.vertices == []
    for esquina in ESQUINAS:
        editor.presionar(*esquina)
        editor.soltar()
    assert editor.vertices == ESQUINAS            # el cuarto clic cierra el rectángulo, no lo cruza
    assert editor.valido and editor.es_cuadrilatero and editor.modificado


def test_con_dos_vertices_todavia_no_es_una_zona():
    assert not editor_con(ESQUINAS[:2]).valido
    assert editor_con(ESQUINAS[:3]).valido


def test_un_clic_sobre_un_vertice_lo_agarra_en_vez_de_crear_otro():
    editor = editor_con(ESQUINAS)
    assert editor.presionar(905.0, 196.0) == 1    # a 6 px del segundo vértice
    assert len(editor.vertices) == 4 and editor.agarrado == 1


def test_arrastrar_mueve_el_vertice_agarrado_y_soltar_lo_deja():
    editor = editor_con(ESQUINAS)
    editor.presionar(900.0, 200.0)
    assert editor.mover(950.0, 180.0)
    assert editor.vertices[1] == (950.0, 180.0)
    editor.soltar()
    assert editor.agarrado is None
    assert not editor.mover(10.0, 10.0)           # sin nada agarrado, mover el mouse no hace nada
    assert editor.vertices[1] == (950.0, 180.0)


def test_un_clic_sobre_un_lado_inserta_el_vertice_entre_sus_extremos():
    editor = editor_con(ESQUINAS)
    indice = editor.presionar(600.0, 505.0)       # junto al lado de abajo (del tercero al cuarto)
    assert indice == 3
    assert editor.vertices == [ESQUINAS[0], ESQUINAS[1], ESQUINAS[2], (600.0, 505.0), ESQUINAS[3]]
    editor.mover(600.0, 600.0)                    # y queda agarrado para ajustarlo
    assert editor.vertices[3] == (600.0, 600.0)


def test_un_clic_cerca_del_lado_que_cierra_inserta_al_final():
    editor = editor_con(ESQUINAS)
    assert editor.presionar(295.0, 350.0) == 4    # junto al lado izquierdo (del cuarto al primero)
    assert editor.vertices[-1] == (295.0, 350.0)


def test_clic_derecho_quita_el_vertice_que_esta_ahi():
    editor = editor_con(ESQUINAS)
    assert editor.borrar(898.0, 503.0)
    assert editor.vertices == [ESQUINAS[0], ESQUINAS[1], ESQUINAS[3]]
    assert not editor.borrar(600.0, 350.0)        # ahí no hay ningún vértice
    assert len(editor.vertices) == 3


def test_los_vertices_no_se_salen_de_la_imagen():
    editor = EditorPoligono(ANCHO, ALTO)
    editor.presionar(-50.0, -20.0)
    editor.mover(5000.0, 5000.0)
    assert editor.vertices == [(ANCHO - 1.0, ALTO - 1.0)]
    editor.mover(-5.0, 300.0)
    assert editor.vertices == [(0.0, 300.0)]


def test_el_poligono_sale_normalizado_y_se_puede_volver_a_cargar():
    editor = editor_con(ESQUINAS)
    normalizado = editor.normalizado()
    assert normalizado == [[round(x / ANCHO, 5), round(y / ALTO, 5)] for x, y in ESQUINAS]

    otro = EditorPoligono(ANCHO, ALTO, normalizado)
    assert not otro.modificado
    for vertice, esquina in zip(otro.vertices, ESQUINAS, strict=True):
        assert vertice == pytest.approx(esquina, abs=0.02)


def test_cargar_reemplaza_y_limpiar_vacia():
    editor = editor_con(ESQUINAS)
    editor.cargar([[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]])
    assert len(editor.vertices) == 3 and not editor.modificado
    editor.limpiar()
    assert editor.vertices == [] and editor.modificado and not editor.valido
    editor.cargar(None)
    assert editor.vertices == [] and not editor.modificado


def test_si_la_imagen_cambia_de_tamano_los_vertices_conservan_su_lugar():
    editor = editor_con(ESQUINAS)
    antes = editor.normalizado()
    editor.redimensionar(640, 360)
    assert editor.vertices[0] == pytest.approx((150.0, 100.0), abs=0.01)
    for despues, original in zip(editor.normalizado(), antes, strict=True):
        assert despues == pytest.approx(original, abs=1e-4)


def test_vertice_en_respeta_el_radio_de_agarre():
    editor = editor_con(ESQUINAS)
    assert editor.vertice_en(310.0, 208.0) == 0
    assert editor.vertice_en(330.0, 230.0) is None
    assert EditorPoligono(ANCHO, ALTO).vertice_en(0.0, 0.0) is None


def test_hay_un_tope_de_vertices():
    editor = EditorPoligono(ANCHO, ALTO)
    for i in range(MAXIMO_DE_VERTICES + 5):
        editor.presionar(20.0 + 19.0 * (i % 60), 40.0 + 300.0 * (i // 60))
        editor.soltar()
    assert len(editor.vertices) == MAXIMO_DE_VERTICES
