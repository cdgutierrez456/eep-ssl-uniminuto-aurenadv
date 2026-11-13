"""La cola local: nada se pierde con el receptor apagado y se vacía al encenderlo."""

import time

import cv2
import httpx
import numpy as np

from modulos.comun import (
    difuminar_rostros, esperar_envios, eventos_pendientes, iniciar_latido, publicar, subir_medio,
)

DATOS_ZONA = {"zona_id": "prensa-1", "duracion_s": 2.8, "alarma_activada": True}


def test_con_receptor_apagado_se_encola_y_al_encenderlo_se_vacia(entorno, tmp_path):
    # 1. Receptor apagado: publicar() retorna de inmediato y el evento queda en disco
    inicio = time.monotonic()
    primero = publicar("zona", "ingreso_zona", DATOS_ZONA, severidad="media")
    segundo = publicar("zona", "casi_accidente", {"zona_id": "prensa-1", "descripcion": "Prueba"},
                       severidad="critica")
    assert time.monotonic() - inicio < 1.0, "publicar() no debe bloquear al módulo"

    assert not esperar_envios(1.5), "sin receptor, la cola no puede vaciarse"
    assert eventos_pendientes("zona") == 2
    archivo_cola = tmp_path / "cola" / "zona.jsonl"
    assert len(archivo_cola.read_text(encoding="utf-8").splitlines()) == 2

    # 2. Se enciende el receptor: el hilo de reintentos entrega todo
    entorno.encender()
    assert esperar_envios(20), "la cola debió vaciarse al encender el receptor"
    assert archivo_cola.read_text(encoding="utf-8") == ""

    # 3. Los eventos llegaron completos y en el orden en que se publicaron
    recibidos = httpx.get(entorno.url + "/api/eventos", params={"estacion": "zona"}).json()
    assert [e["id"] for e in recibidos] == [primero["id"], segundo["id"]]
    assert recibidos[0] == primero


def test_con_receptor_encendido_el_evento_llega_enseguida(entorno):
    entorno.encender()
    evento = publicar("epp", "verificacion_epp", {
        "perfil": "alimentos", "requeridos": ["cofia", "tapabocas"],
        "detectados": ["cofia", "tapabocas"], "faltantes": [], "cumple": True,
    }, sesion_id="V-0007")
    assert esperar_envios(5)
    recibidos = httpx.get(entorno.url + "/api/eventos").json()
    assert recibidos == [evento]


def test_el_receptor_rechaza_un_evento_invalido_con_422(entorno):
    entorno.encender()
    respuesta = httpx.post(entorno.url + "/api/eventos", json={"tipo": "evaluacion_reba"})
    assert respuesta.status_code == 422
    assert respuesta.json()["detalle"][0]["errores"]
    assert httpx.get(entorno.url + "/api/eventos").json() == []


def test_subir_medio_devuelve_ruta_y_respalda_si_no_hay_receptor(entorno, tmp_path):
    imagen = tmp_path / "captura.jpg"
    cv2.imwrite(str(imagen), np.full((60, 80, 3), 200, np.uint8))

    # Sin receptor: copia local de respaldo
    ruta_local = subir_medio(imagen)
    assert "medios_pendientes" in ruta_local
    assert (tmp_path / "cola").joinpath(*ruta_local.split("cola/")[-1].split("/")).is_file()

    # Con receptor: ruta relativa a la carpeta de medios
    entorno.encender()
    ruta = subir_medio(imagen)
    assert ruta.startswith("media/") and ruta.endswith(".jpg")
    assert (tmp_path / "receptor" / ruta).is_file()


def test_el_latido_publica_estado_modulo(entorno):
    entorno.encender()
    latido = iniciar_latido("ergonomia", "ergonomia", intervalo_s=0.2)
    time.sleep(1.0)
    latido.detener()
    recibidos = httpx.get(entorno.url + "/api/eventos").json()
    assert len(recibidos) >= 2
    assert all(e["tipo"] == "estado_modulo" and e["datos"]["estado"] == "activo" for e in recibidos)
    assert httpx.get(entorno.url + "/api/salud").json()["modulos"]["ergonomia"]["estado"] == "activo"


def test_difuminar_rostros_devuelve_una_copia():
    frame = np.full((240, 320, 3), 128, np.uint8)
    salida = difuminar_rostros(frame)
    assert salida is not frame
    assert salida.shape == frame.shape
    assert np.array_equal(salida, frame)  # sin rostros, la imagen no cambia
