"""Eventos urgentes: cortan la espera entre reintentos de la cola; los demás no cambian."""

import time

import httpx

from modulos.comun import cola, eventos_pendientes, publicar

INGRESO = {"zona_id": "piso", "duracion_s": 2.8, "alarma_activada": True}
PELIGRO = {"zona_id": "piso", "estado": "peligro", "personas_peligro": 1, "personas_advertencia": 0}
ESPERA_LARGA_S = 30.0  # intervalo de reintento de estas pruebas: mucho más de lo que dura cada una


def recibidos(receptor) -> list[dict]:
    return httpx.get(receptor.url + "/api/eventos", params={"estacion": "zona"}, timeout=5).json()


def esperar(condicion, segundos: float) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.05)
    return False


def dejar_la_cola_esperando(monkeypatch, caplog) -> dict:
    """Publica un evento con la plataforma caída: el hilo de envío falla y se queda esperando 30 s.

    Espera a ver el aviso del fallo en el log: en Windows un intento de conexión a un puerto
    cerrado tarda un par de segundos en fallar, y hasta entonces el hilo todavía no está esperando.
    """
    monkeypatch.setattr(cola, "ESPERA_MINIMA_S", ESPERA_LARGA_S)
    caplog.set_level("WARNING", logger="modulos.comun.cola")
    atascado = publicar("zona", "ingreso_zona", INGRESO, severidad="alta")
    assert esperar(lambda: any("No se pudo enviar" in registro.getMessage() for registro in caplog.records), 15.0)
    assert eventos_pendientes("zona") == 1
    return atascado


def test_un_evento_urgente_sale_apenas_vuelve_la_conexion(entorno, monkeypatch, caplog):
    atascado = dejar_la_cola_esperando(monkeypatch, caplog)
    entorno.encender()                      # vuelve la plataforma, pero la cola sigue en su espera de 30 s

    inicio = time.monotonic()
    urgente = publicar("zona", "estado_zona", PELIGRO, severidad="alta", urgente=True)
    assert esperar(lambda: len(recibidos(entorno)) == 2, 5.0), "el evento urgente debió salir sin esperar el reintento"
    assert time.monotonic() - inicio < ESPERA_LARGA_S / 2

    # Llegan los dos y en orden: el urgente destraba la cola, no se salta a los anteriores
    assert [evento["id"] for evento in recibidos(entorno)] == [atascado["id"], urgente["id"]]
    assert eventos_pendientes("zona") == 0


def test_un_evento_normal_sigue_esperando_el_intervalo_de_reintento(entorno, monkeypatch, caplog):
    dejar_la_cola_esperando(monkeypatch, caplog)
    entorno.encender()

    publicar("zona", "ingreso_zona", INGRESO, severidad="alta")     # sin urgente: el comportamiento de siempre
    assert not esperar(lambda: len(recibidos(entorno)) > 0, 3.0), "un evento normal no debe cortar la espera"
    assert eventos_pendientes("zona") == 2

    # Limpieza: se vacía la cola antes de terminar, para que su hilo no le entregue estos
    # eventos al receptor de otra prueba cuando por fin despierte
    publicar("zona", "estado_zona", PELIGRO, severidad="alta", urgente=True)
    assert esperar(lambda: eventos_pendientes("zona") == 0, 10.0)


def test_con_la_plataforma_caida_el_urgente_reintenta_y_queda_en_cola(entorno, monkeypatch, caplog):
    dejar_la_cola_esperando(monkeypatch, caplog)
    urgente = publicar("zona", "estado_zona", PELIGRO, severidad="alta", urgente=True)   # sigue caída
    # El urgente cortó la espera y hubo un segundo intento, que también falló
    assert esperar(lambda: sum("No se pudo enviar" in r.getMessage() for r in caplog.records) >= 2, 15.0)
    assert eventos_pendientes("zona") == 2      # nada se pierde: sigue en disco con su timestamp original

    entorno.encender()
    otro = publicar("zona", "estado_zona", {**PELIGRO, "refresco": True}, severidad="alta", urgente=True)
    assert esperar(lambda: len(recibidos(entorno)) == 3, 5.0)
    llegados = recibidos(entorno)
    assert [evento["id"] for evento in llegados][1:] == [urgente["id"], otro["id"]]
    assert llegados[1]["timestamp"] == urgente["timestamp"]


def test_con_la_plataforma_arriba_un_urgente_llega_como_cualquier_otro(entorno):
    entorno.encender()
    evento = publicar("zona", "estado_zona", PELIGRO, severidad="alta", urgente=True)
    assert esperar(lambda: recibidos(entorno) == [evento], 5.0)
