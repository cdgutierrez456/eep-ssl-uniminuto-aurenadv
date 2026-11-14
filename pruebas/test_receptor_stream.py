"""El receptor de prueba empuja los eventos por SSE y sirve la vista de alarma y el editor de zona."""

import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

ZONA_HORARIA = ZoneInfo("America/Bogota")


def evento(tipo: str, datos: dict, severidad: str = "info", estacion: str = "zona") -> dict:
    return {"id": str(uuid.uuid4()), "version_esquema": 1, "estacion": estacion, "tipo": tipo,
            "timestamp": datetime.now(ZONA_HORARIA).isoformat(timespec="seconds"), "severidad": severidad,
            "datos": datos, "origen": {"dispositivo": "pc-pruebas", "modulo_version": "0.1.0"}}


PELIGRO = {"zona_id": "piso", "estado": "peligro", "personas_peligro": 1, "personas_advertencia": 0}


class Flujo:
    """Lector mínimo de Server-Sent Events sobre una conexión de httpx."""

    def __init__(self, url: str) -> None:
        self._contexto = httpx.stream("GET", url + "/api/stream", timeout=httpx.Timeout(10.0, read=10.0))
        self.respuesta = self._contexto.__enter__()
        self._lineas = self.respuesta.iter_lines()

    def siguiente(self) -> dict:
        """El siguiente mensaje completo: sus campos ``event``, ``id`` y ``data`` (ya leído como JSON)."""
        mensaje: dict = {}
        for linea in self._lineas:
            if not linea:
                if mensaje:
                    return mensaje
                continue
            campo, _, valor = linea.partition(": ")
            mensaje[campo] = json.loads(valor) if campo == "data" else valor
        raise AssertionError("el flujo se cerró antes de entregar un mensaje")

    def cerrar(self) -> None:
        self._contexto.__exit__(None, None, None)


@pytest.fixture
def receptor(entorno):
    entorno.encender()
    return entorno


@pytest.fixture
def flujo(receptor):
    lector = Flujo(receptor.url)
    yield lector
    lector.cerrar()      # hay que cerrarlo antes de apagar el receptor: una conexión SSE abierta lo retiene


def publicar(receptor, cuerpo) -> httpx.Response:
    return httpx.post(receptor.url + "/api/eventos", json=cuerpo, timeout=5)


# ------------------------------------------------------------------------ SSE
def test_el_flujo_empieza_con_la_hora_del_servidor(flujo):
    assert flujo.respuesta.status_code == 200
    assert flujo.respuesta.headers["content-type"].startswith("text/event-stream")
    primero = flujo.siguiente()
    assert primero["event"] == "reloj"
    ahora = datetime.fromisoformat(primero["data"]["ahora"])
    assert abs((datetime.now(ZONA_HORARIA) - ahora).total_seconds()) < 5
    assert primero["data"]["ahora"].endswith("-05:00")


def test_cada_evento_nuevo_sale_por_el_flujo_tal_como_llego(receptor, flujo):
    flujo.siguiente()                                         # el reloj inicial
    enviado = evento("estado_zona", PELIGRO, "alta")
    assert publicar(receptor, enviado).status_code == 201

    recibido = flujo.siguiente()
    assert "event" not in recibido                            # mensaje sin nombre: llega a onmessage
    assert recibido["id"] == enviado["id"]
    assert recibido["data"] == enviado                        # el sobre completo, sin envoltorio


def test_los_eventos_salen_en_orden_incluidos_los_refrescos_y_los_de_otras_estaciones(receptor, flujo):
    flujo.siguiente()
    enviados = [
        evento("estado_zona", PELIGRO, "alta"),
        evento("estado_zona", {**PELIGRO, "refresco": True}, "alta"),
        evento("ingreso_zona", {"zona_id": "piso", "duracion_s": 3.2, "alarma_activada": True}, "alta"),
        evento("estado_modulo", {"modulo": "epp", "estado": "activo"}, estacion="epp"),
    ]
    assert publicar(receptor, enviados).status_code == 201    # un lote
    assert [flujo.siguiente()["id"] for _ in enviados] == [e["id"] for e in enviados]


def test_un_evento_invalido_o_repetido_no_sale_por_el_flujo(receptor, flujo):
    flujo.siguiente()
    bueno = evento("estado_zona", PELIGRO, "alta")
    assert publicar(receptor, {**bueno, "tipo": "no_existe"}).status_code == 422
    assert publicar(receptor, bueno).status_code == 201
    assert publicar(receptor, bueno).status_code == 201       # el mismo id otra vez: se ignora
    otro = evento("estado_zona", {**PELIGRO, "estado": "libre", "personas_peligro": 0})
    publicar(receptor, otro)
    assert [flujo.siguiente()["id"], flujo.siguiente()["id"]] == [bueno["id"], otro["id"]]


def test_varias_pantallas_reciben_el_mismo_evento(receptor, flujo):
    otra = Flujo(receptor.url)
    try:
        flujo.siguiente(), otra.siguiente()
        enviado = evento("estado_zona", PELIGRO, "alta")
        publicar(receptor, enviado)
        assert flujo.siguiente()["id"] == otra.siguiente()["id"] == enviado["id"]
    finally:
        otra.cerrar()


def test_quien_se_conecta_despues_solo_recibe_lo_nuevo(receptor):
    viejo = evento("estado_zona", PELIGRO, "alta")
    publicar(receptor, viejo)
    lector = Flujo(receptor.url)
    try:
        assert lector.siguiente()["event"] == "reloj"
        nuevo = evento("casi_accidente", {"zona_id": "piso", "descripcion": "Prueba"}, "alta")
        publicar(receptor, nuevo)
        assert lector.siguiente()["id"] == nuevo["id"]        # el viejo se consulta con GET /api/eventos
    finally:
        lector.cerrar()
    assert [e["id"] for e in httpx.get(receptor.url + "/api/eventos", timeout=5).json()] == [viejo["id"], nuevo["id"]]


def test_la_salud_trae_la_hora_del_servidor(receptor):
    salud = httpx.get(receptor.url + "/api/salud", timeout=5).json()
    assert salud["estado"] == "ok"
    assert abs((datetime.now(ZONA_HORARIA) - datetime.fromisoformat(salud["ahora"])).total_seconds()) < 5


# --------------------------------------------------------------------- páginas
def test_la_vista_de_alarma_trae_los_tres_estados_el_sonido_y_las_reglas(receptor):
    respuesta = httpx.get(receptor.url + "/alarma", timeout=5)
    assert respuesta.status_code == 200 and respuesta.headers["content-type"].startswith("text/html")
    pagina = respuesta.text
    for texto in ("Zona despejada", "Precaución: persona cerca de la zona de peligro", "PERSONA EN ZONA DE PELIGRO",
                  "Activar sonido", "Ingresos hoy", "Casi-accidentes hoy", "Último evento", 'id="volumen"',
                  'id="silencio"'):
        assert texto in pagina
    assert 'new EventSource("/api/stream")' in pagina
    assert "AudioContext" in pagina and "createOscillator" in pagina     # tonos generados, sin archivos
    assert "<audio" not in pagina and ".mp3" not in pagina and ".wav" not in pagina
    assert "VIGENCIA_MS = 5000" in pagina                                # eventos viejos y apagado automático


def test_la_pagina_del_receptor_trae_el_editor_de_zona_y_el_enlace_a_la_alarma(receptor):
    pagina = httpx.get(receptor.url + "/", timeout=5).text
    for texto in ('href="/alarma"', 'id="zona-svg"', "Detectar zona", "Guardar zona", "Ancho real (m)",
                  "Largo real (m)", "solicitud_deteccion", "zona_propuesta: null"):
        assert texto in pagina


def test_la_configuracion_de_zona_que_escribe_el_editor_cumple_el_esquema(receptor):
    """Los dos PUT del editor: pedir la detección y guardar la zona, siempre con el documento completo."""
    from modulos.zona.config import validar_config
    url = receptor.url + "/api/modulos/zona/config"
    assert httpx.get(url, timeout=5).status_code == 404                  # la estación aún no subió nada
    httpx.put(url, json=validar_config({}), timeout=5).raise_for_status()

    actual = httpx.get(url, timeout=5).json()
    pedido = {**actual, "solicitud_deteccion": "2026-11-14T15:02:11.123Z"}   # como lo escribe toISOString()
    assert httpx.put(url, json=pedido, timeout=5).status_code == 200

    guardada = {**pedido, "zona_peligro": [[0.31234, 0.42], [0.68, 0.4], [0.74, 0.81], [0.27, 0.84]],
                "rectangulo_real": {"ancho_m": 1.5, "largo_m": 1}, "margen_advertencia_m": 0.5,
                "zona_propuesta": None, "solicitud_deteccion": None, "imagen_referencia": "media/2026-11-14/ab12cd34.jpg"}
    assert httpx.put(url, json=guardada, timeout=5).status_code == 200
    assert validar_config(httpx.get(url, timeout=5).json())["zona_peligro"] == guardada["zona_peligro"]

    mala = {**guardada, "zona_peligro": [[0.1, 0.1], [0.2, 0.2]]}
    respuesta = httpx.put(url, json=mala, timeout=5)
    assert respuesta.status_code == 422 and respuesta.json()["detalle"]  # el editor muestra este detalle
