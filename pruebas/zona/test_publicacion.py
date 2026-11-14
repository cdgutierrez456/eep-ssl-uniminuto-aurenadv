"""Publicación de los eventos de la zona: el estado sale urgente y cada evento de persona lleva su foto."""

import cv2
import numpy as np
import pytest

from modulos.zona import publicacion as modulo_publicacion
from modulos.zona.interfaz import dibujo as modulo_dibujo
from modulos.zona.interfaz.marca import ROJO, bgr
from modulos.zona.nucleo import MonitorZona, crear_zona
from modulos.zona.publicacion import Publicador

ANCHO, ALTO, FPS = 640, 360, 30
ZONA = [[200 / ANCHO, 150 / ALTO], [400 / ANCHO, 150 / ALTO], [400 / ANCHO, 300 / ALTO], [200 / ANCHO, 300 / ALTO]]
LEJOS, CERCA, DENTRO = (40.0, 225.0), (175.0, 225.0), (300.0, 225.0)


@pytest.fixture
def salida(tmp_path, monkeypatch):
    """Reemplaza ``publicar``, ``subir_medio`` y el difuminado por espías: nada sale de la prueba."""
    registro = {"publicados": [], "subidos": [], "difuminados": [], "en_cola": 0}

    def publicar(estacion, tipo, datos, severidad="info", adjuntos=None, modulo_version=None, urgente=False):
        registro["publicados"].append(dict(estacion=estacion, tipo=tipo, datos=datos, severidad=severidad,
                                           adjuntos=adjuntos, urgente=urgente, version=modulo_version))
        return {"id": "x"}

    def subir_medio(ruta):
        imagen = cv2.imdecode(np.fromfile(str(ruta), dtype=np.uint8), cv2.IMREAD_COLOR)
        registro["subidos"].append((ruta, imagen))
        return f"media/2026-11-14/{ruta.name}"

    def difuminar(frame):
        registro["difuminados"].append(int(frame[0, 0, 0]))   # cada fotograma de la prueba lleva su número en el brillo
        return np.zeros_like(frame)                           # "difuminado" inconfundible: todo negro

    monkeypatch.setattr(modulo_publicacion, "publicar", publicar)
    monkeypatch.setattr(modulo_publicacion, "subir_medio", subir_medio)
    monkeypatch.setattr(modulo_publicacion, "eventos_pendientes", lambda estacion: registro["en_cola"])
    monkeypatch.setattr(modulo_dibujo, "difuminar_rostros", difuminar)
    return registro


def correr(publicador, recorridos, zona=None):
    """Pasa por el monitor y el publicador un recorrido por persona; el fotograma i va pintado con el valor i."""
    zona = zona or crear_zona("piso", ZONA, ANCHO, ALTO, margen_px=60)
    monitor = MonitorZona(zona)
    for i in range(max(len(recorrido) for recorrido in recorridos.values())):
        observaciones = {persona: [recorrido[i]] for persona, recorrido in recorridos.items()
                         if i < len(recorrido) and recorrido[i] is not None}
        frame = np.full((ALTO, ANCHO, 3), i, dtype=np.uint8)
        publicador.procesar(monitor.actualizar(i / FPS, observaciones), frame, zona)
    publicador.publicar(monitor.cerrar(i / FPS), zona)
    publicador.cerrar()
    return zona


def quieto(punto, cuadros):
    return [punto] * cuadros


def de_tipo(registro, tipo):
    return [evento for evento in registro["publicados"] if evento["tipo"] == tipo]


def test_el_estado_de_la_zona_se_publica_en_el_acto_y_como_urgente(salida, tmp_path):
    publicador = Publicador(carpeta=tmp_path)
    zona = crear_zona("piso", ZONA, ANCHO, ALTO, margen_px=60)
    monitor = MonitorZona(zona)
    publicador.procesar(monitor.actualizar(0.0, {}), np.zeros((ALTO, ANCHO, 3), np.uint8), zona)

    (evento,) = salida["publicados"]              # ya está, sin esperar al hilo de las fotos
    assert evento["tipo"] == "estado_zona" and evento["urgente"] is True
    assert evento["estacion"] == "zona" and evento["severidad"] == "info" and evento["adjuntos"] is None
    assert evento["version"] == "0.1.0"
    publicador.cerrar()


def test_el_ingreso_lleva_la_foto_del_momento_de_entrada_difuminada_y_con_la_zona_encima(salida, tmp_path):
    # Entra en el fotograma 10 (se confirma en el 19), se queda y sale en el 60
    recorrido = quieto(LEJOS, 10) + quieto(DENTRO, 50) + quieto(LEJOS, 20)
    correr(Publicador(carpeta=tmp_path), {1: recorrido})

    (ingreso,) = de_tipo(salida, "ingreso_zona")
    assert ingreso["severidad"] == "alta" and ingreso["urgente"] is False
    assert ingreso["datos"]["duracion_s"] == pytest.approx(50 / FPS, abs=0.1)
    (ruta, imagen), = salida["subidos"]
    assert ingreso["adjuntos"] == [{"tipo": "imagen", "ruta": f"media/2026-11-14/{ruta.name}"}]
    assert ruta.parent == tmp_path and ruta.name.startswith("ingreso_zona-") and ruta.suffix == ".jpg"

    assert salida["difuminados"] == [19]          # la foto es la del fotograma en que se confirmó la entrada
    assert imagen[20, 20].max() < 12              # el fondo es lo que devolvió el difuminado (negro)
    rojo = np.array(bgr(ROJO), dtype=int)
    assert np.abs(imagen[150, 300].astype(int) - rojo).max() < 60     # encima, el borde de la zona
    assert np.abs(imagen[225, 300].astype(int) - rojo).max() < 60     # y el punto de apoyo de la persona


def test_el_casi_accidente_lleva_la_foto_del_momento_mas_cercano(salida, tmp_path):
    # Se acerca hasta 25 px de la zona en el fotograma 30 y se retira
    recorrido = quieto(LEJOS, 10) + quieto((150.0, 225.0), 20) + quieto(CERCA, 15) + quieto((150.0, 225.0), 15) + quieto(LEJOS, 20)
    correr(Publicador(carpeta=tmp_path), {1: recorrido})

    (casi,) = de_tipo(salida, "casi_accidente")
    assert casi["datos"]["distancia_min_px"] == 25.0
    assert casi["adjuntos"] and casi["adjuntos"][0]["tipo"] == "imagen"
    assert salida["difuminados"] == [30]          # el primer fotograma en que estuvo a 25 px
    assert de_tipo(salida, "ingreso_zona") == []


def test_cada_persona_recibe_su_propia_foto(salida, tmp_path):
    persona_1 = quieto(DENTRO, 40) + quieto(LEJOS, 20)                   # entra desde el principio
    persona_2 = [None] * 20 + quieto(CERCA, 20) + quieto(LEJOS, 20)      # se acerca desde el fotograma 20
    correr(Publicador(carpeta=tmp_path), {1: persona_1, 2: persona_2})
    assert len(de_tipo(salida, "ingreso_zona")) == 1 and len(de_tipo(salida, "casi_accidente")) == 1
    assert sorted(salida["difuminados"]) == [9, 20]    # la entrada de la 1 y el acercamiento de la 2


def test_si_el_tracker_cambia_el_id_la_foto_de_entrada_pasa_al_id_nuevo(salida, tmp_path):
    persona_1 = quieto(DENTRO, 30)
    persona_2 = [None] * 30 + quieto((305.0, 228.0), 30) + quieto(LEJOS, 20)
    correr(Publicador(carpeta=tmp_path), {1: persona_1, 2: persona_2})
    (ingreso,) = de_tipo(salida, "ingreso_zona")
    assert ingreso["adjuntos"] is not None
    assert salida["difuminados"] == [9]           # la foto es la de la primera vez que entró, con el id anterior


def test_al_cerrar_salen_los_eventos_pendientes_con_su_foto_y_la_zona_queda_libre(salida, tmp_path):
    correr(Publicador(carpeta=tmp_path), {1: quieto(DENTRO, 30)})        # sigue dentro cuando la estación se cierra
    assert [evento["datos"]["estado"] for evento in de_tipo(salida, "estado_zona")] == ["libre", "peligro", "libre"]
    (ingreso,) = de_tipo(salida, "ingreso_zona")
    assert ingreso["adjuntos"] is not None


def test_las_fotos_de_quien_se_va_sin_evento_no_se_quedan_en_memoria(salida, tmp_path):
    publicador = Publicador(carpeta=tmp_path)
    # Roza la franja 0,1 s (no llega a confirmarse la advertencia) y se va
    correr(publicador, {1: quieto(LEJOS, 5) + quieto(CERCA, 3) + quieto(LEJOS, 60)})
    assert publicador._entradas == {} and publicador._minimos == {}
    assert salida["subidos"] == [] and salida["difuminados"] == []


def test_sin_plataforma_no_se_publica_ni_se_guarda_nada_pero_se_cuenta(salida, tmp_path):
    publicador = Publicador(con_plataforma=False, carpeta=tmp_path)
    recorrido = quieto(LEJOS, 10) + quieto(DENTRO, 30) + quieto(LEJOS, 20) + quieto(CERCA, 20) + quieto(LEJOS, 20)
    correr(publicador, {1: recorrido})
    assert salida["publicados"] == [] and salida["subidos"] == [] and list(tmp_path.iterdir()) == []
    assert (publicador.ingresos, publicador.casi_accidentes) == (1, 1)
    assert publicador.en_cola == 0 and publicador.plataforma_recibe is False


def test_la_plataforma_recibe_mientras_no_haya_eventos_atascados(salida, tmp_path, monkeypatch):
    monkeypatch.setattr(modulo_publicacion, "INTERVALO_REVISION_COLA_S", 0.0)
    publicador = Publicador(carpeta=tmp_path)
    assert publicador.plataforma_recibe is True
    salida["en_cola"] = 3
    assert publicador.en_cola == 3 and publicador.plataforma_recibe is False
    publicador.cerrar()


def test_los_contadores_llevan_los_ingresos_y_los_casi_accidentes(salida, tmp_path):
    publicador = Publicador(carpeta=tmp_path)
    recorrido = quieto(LEJOS, 10) + quieto(DENTRO, 30) + quieto(LEJOS, 20) + quieto(CERCA, 20) + quieto(LEJOS, 20)
    correr(publicador, {1: recorrido})
    assert (publicador.ingresos, publicador.casi_accidentes) == (1, 1)
