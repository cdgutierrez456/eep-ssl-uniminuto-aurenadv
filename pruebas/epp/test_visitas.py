"""Visitas y publicación, sin cámara: detecciones simuladas y reloj controlado."""

import queue

import httpx
import numpy as np
import pytest

from modulos.comun import esperar_envios
from modulos.epp import estacion as modulo_estacion
from modulos.epp.nucleo.perfiles import cargar_perfiles
from modulos.epp.nucleo.visitas import SeguidorDeVisitas
from modulos.epp.verificador import Verificador

CLASES = {
    "alimentos": ["persona", "cofia", "gafas", "tapabocas", "sin_cofia", "sin_gafas", "sin_tapabocas"],
    "industria": ["persona", "casco", "gafas", "chaleco", "sin_casco", "sin_gafas"],
}
CUADRO_S = 1 / 30


def d(clase, confianza, caja):
    return {"clase": clase, "confianza": confianza, "caja": caja}


PERSONA = d("persona", 0.9, [0.3, 0.1, 0.7, 1.0])
CASCO = d("casco", 0.9, [0.42, 0.1, 0.58, 0.25])
GAFAS = d("gafas", 0.8, [0.44, 0.28, 0.56, 0.34])
COMPLETA = [PERSONA, CASCO, GAFAS]
SIN_CASCO = [PERSONA, GAFAS]
# Otra persona al fondo (caja más pequeña), sin ningún elemento
DEL_FONDO = d("persona", 0.8, [0.02, 0.5, 0.18, 1.0])


@pytest.fixture
def verificador():
    return Verificador(cargar_perfiles(), CLASES, segundos_estable=2.0, segundos_sin_persona=3.0)


class Simulacion:
    """Alimenta al verificador cuadro a cuadro y anota lo que habría que publicar."""

    def __init__(self, verificador: Verificador) -> None:
        self.verificador = verificador
        self.ahora = 0.0
        self.eventos: list[dict] = []
        self.fines = 0
        self.ultimo = None

    def correr(self, detecciones: list[dict], segundos: float) -> "Simulacion":
        for _ in range(round(segundos / CUADRO_S)):
            self.ultimo = self.verificador.procesar(detecciones, self.ahora)
            if self.ultimo.evento:
                self.eventos.append(self.ultimo.evento)
            self.fines += self.ultimo.novedad.visita_terminada
            self.ahora += CUADRO_S
        return self


# ---------------------------------------------------------------------------
# Seguidor de visitas (reloj a mano)
# ---------------------------------------------------------------------------
CUMPLE = {"cumple": True, "faltantes": []}
FALTA = {"cumple": False, "faltantes": ["casco"]}


def test_publica_una_sola_vez_cuando_el_veredicto_se_mantiene():
    seguidor = SeguidorDeVisitas(segundos_estable=2.0, segundos_sin_persona=3.0)
    assert seguidor.actualizar(0.0, CUMPLE).visita_iniciada
    assert not seguidor.actualizar(1.9, CUMPLE).publicar
    assert seguidor.actualizar(2.0, CUMPLE).publicar
    assert not any(seguidor.actualizar(t, CUMPLE).publicar for t in (2.1, 5.0, 60.0))


def test_un_parpadeo_no_publica_y_un_cambio_estable_si():
    seguidor = SeguidorDeVisitas(2.0, 3.0)
    seguidor.actualizar(0.0, CUMPLE)
    assert seguidor.actualizar(2.0, CUMPLE).publicar
    seguidor.actualizar(3.0, FALTA)                          # parpadeo de un segundo
    assert not seguidor.actualizar(4.0, CUMPLE).publicar     # vuelve: ya estaba publicado
    assert not seguidor.actualizar(7.0, CUMPLE).publicar
    seguidor.actualizar(8.0, FALTA)
    assert not seguidor.actualizar(9.9, FALTA).publicar
    assert seguidor.actualizar(10.0, FALTA).publicar         # cambio estable: se publica de nuevo


def test_la_visita_termina_tras_unos_segundos_sin_nadie():
    seguidor = SeguidorDeVisitas(2.0, 3.0)
    seguidor.actualizar(0.0, CUMPLE)
    seguidor.actualizar(2.0, CUMPLE)
    assert not seguidor.actualizar(4.9, None).visita_terminada   # ausencia breve
    assert seguidor.actualizar(5.0, None).visita_terminada
    assert not seguidor.actualizar(6.0, None).visita_terminada   # solo avisa una vez
    # Visita nueva: el mismo veredicto vuelve a publicarse
    assert seguidor.actualizar(10.0, CUMPLE).visita_iniciada
    assert seguidor.actualizar(12.0, CUMPLE).publicar
    assert seguidor.numero_visita == 2


def test_una_ausencia_breve_no_corta_la_visita_ni_republica():
    seguidor = SeguidorDeVisitas(2.0, 3.0)
    seguidor.actualizar(0.0, CUMPLE)
    seguidor.actualizar(2.0, CUMPLE)
    seguidor.actualizar(3.0, None)
    assert not seguidor.actualizar(4.0, CUMPLE).visita_iniciada
    assert not seguidor.actualizar(9.0, CUMPLE).publicar
    assert seguidor.numero_visita == 1


# ---------------------------------------------------------------------------
# Verificador con detecciones simuladas
# ---------------------------------------------------------------------------
def test_una_visita_completa_publica_un_solo_evento(verificador):
    sim = Simulacion(verificador).correr(COMPLETA, 1.5)
    assert sim.eventos == []
    sim.correr(COMPLETA, 5)
    assert sim.eventos == [{
        "perfil": "industria", "requeridos": ["casco", "gafas"], "detectados": ["casco", "gafas"],
        "faltantes": [], "cumple": True,
    }]
    sim.correr([], 4)
    assert sim.fines == 1


def test_quitarse_el_casco_en_la_misma_visita_publica_de_nuevo(verificador):
    sim = Simulacion(verificador).correr(COMPLETA, 3).correr(SIN_CASCO, 4)
    assert [e["cumple"] for e in sim.eventos] == [True, False]
    assert sim.eventos[1]["faltantes"] == ["casco"]
    assert sim.eventos[1]["detectados"] == ["gafas"]


def test_solo_cuenta_la_persona_principal(verificador):
    sim = Simulacion(verificador).correr(COMPLETA + [DEL_FONDO], 3)
    assert [e["cumple"] for e in sim.eventos] == [True]
    assert sim.ultimo.principal["caja"] == PERSONA["caja"]
    assert [p["caja"] for p in sim.ultimo.otras] == [DEL_FONDO["caja"]]
    assert sim.ultimo.otras[0]["cumple"] is False


def test_cambio_de_config_reinicia_y_vuelve_a_publicar(verificador):
    sim = Simulacion(verificador).correr(SIN_CASCO, 3)
    assert [e["cumple"] for e in sim.eventos] == [False]

    solo_gafas, _ = verificador.validar(
        {"perfil_activo": "industria", "perfiles": {"industria": {"elementos_requeridos": ["gafas"]}}}
    )
    assert verificador.aplicar_config(solo_gafas) is True
    assert verificador.aplicar_config(solo_gafas) is False       # la misma config no es un cambio
    assert verificador.datos_config() == {"perfil_activo": "industria", "elementos_requeridos": ["gafas"]}
    assert verificador.suavizador.tracks == []                   # suavizado temporal reiniciado

    sim.correr(SIN_CASCO, 1)
    assert len(sim.eventos) == 1                                 # aún no se estabiliza
    sim.correr(SIN_CASCO, 2)
    assert sim.eventos[1] == {
        "perfil": "industria", "requeridos": ["gafas"], "detectados": ["gafas"], "faltantes": [], "cumple": True,
    }


def test_cambiar_de_perfil_usa_las_reglas_del_otro_modelo(verificador):
    verificador.aplicar_config(verificador.con_perfil("alimentos"))
    assert verificador.perfil_activo == "alimentos"
    assert verificador.requeridos == ["cofia", "gafas", "tapabocas"]
    sim = Simulacion(verificador).correr([PERSONA, d("cofia", 0.9, [0.42, 0.1, 0.58, 0.25])], 3)
    assert sim.eventos[0]["perfil"] == "alimentos"
    assert sim.eventos[0]["faltantes"] == ["gafas", "tapabocas"]


# ---------------------------------------------------------------------------
# Publicación: foto difuminada, subida y evento
# ---------------------------------------------------------------------------
def test_publicar_verificacion_difumina_antes_de_dibujar_y_adjunta_la_foto(entorno, verificador, monkeypatch, tmp_path):
    entorno.encender()
    sim = Simulacion(verificador).correr(SIN_CASCO, 3)
    orden = []
    difuminar_real, dibujar_real = modulo_estacion.difuminar_rostros, modulo_estacion.interfaz.dibujar_cajas
    monkeypatch.setattr(modulo_estacion, "difuminar_rostros", lambda f: (orden.append("difuminar"), difuminar_real(f))[1])
    monkeypatch.setattr(modulo_estacion.interfaz, "dibujar_cajas",
                        lambda *a: (orden.append("dibujar"), dibujar_real(*a))[1])

    frame = np.full((480, 640, 3), 90, np.uint8)
    original = frame.copy()
    evento = modulo_estacion.publicar_verificacion(frame, sim.ultimo, verificador.reglas, sim.eventos[0], "V-0007")
    esperar_envios(5)

    assert orden == ["difuminar", "dibujar"]
    assert (frame == original).all(), "la imagen en vivo no debe modificarse"
    assert evento["severidad"] == "media" and evento["sesion_id"] == "V-0007"
    recibidos = httpx.get(entorno.url + "/api/eventos").json()
    recibidos = [e for e in recibidos if e["id"] == evento["id"]]
    assert [e["tipo"] for e in recibidos] == ["verificacion_epp"]
    ruta = recibidos[0]["adjuntos"][0]["ruta"]
    assert httpx.get(f"{entorno.url}/{ruta}").status_code == 200
    assert list((tmp_path / "cola" / "epp_fotos").iterdir()) == [], "la foto temporal se borra tras subirla"


def test_severidad_info_cuando_cumple(entorno, verificador):
    sim = Simulacion(verificador).correr(COMPLETA, 3)
    evento = modulo_estacion.publicar_verificacion(
        np.zeros((240, 320, 3), np.uint8), sim.ultimo, verificador.reglas, sim.eventos[0], None
    )
    assert evento["severidad"] == "info" and "sesion_id" not in evento
    # Sin plataforma la foto queda en la carpeta local de respaldo
    assert "medios_pendientes" in evento["adjuntos"][0]["ruta"]


def test_la_estacion_publica_config_actualizada_al_aplicar_un_cambio(entorno, verificador):
    entorno.encender()
    estacion = modulo_estacion.Estacion(camara=0, pantalla_completa=False)
    estacion.verificador = verificador
    estacion._configs = queue.Queue()
    estacion._configs.put(verificador.con_perfil("alimentos"))
    estacion._aplicar_configs_pendientes()
    estacion._aplicar_configs_pendientes()  # sin cambios pendientes no publica nada
    esperar_envios(5)
    # Solo los de configuración: la cola de otra prueba puede vaciarse en este receptor
    recibidos = [e for e in httpx.get(entorno.url + "/api/eventos").json() if e["tipo"] == "config_actualizada"]
    assert [(e["tipo"], e["severidad"]) for e in recibidos] == [("config_actualizada", "info")]
    assert recibidos[0]["datos"] == {"perfil_activo": "alimentos", "elementos_requeridos": ["cofia", "gafas", "tapabocas"]}
