"""El contrato: los ejemplos validan y los eventos inválidos se rechazan."""

import copy
import json
from pathlib import Path

import pytest

from modulos.comun import EventoInvalido, construir_evento, validar_evento

CARPETA_EJEMPLOS = Path(__file__).resolve().parents[1] / "contrato" / "ejemplos"
EJEMPLOS = sorted(CARPETA_EJEMPLOS.glob("*.json"))
TIPOS_DEL_BRIEF = {
    "evaluacion_reba", "reporte_generado", "verificacion_epp", "ingreso_zona", "casi_accidente",
    "inspeccion_foto", "informe_incidente", "lead_registrado", "estado_modulo",
    "config_actualizada", "estado_zona",
}


def _cargar(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


@pytest.fixture
def evento_valido() -> dict:
    return _cargar(CARPETA_EJEMPLOS / "evaluacion_reba.json")


def test_hay_un_ejemplo_por_cada_tipo():
    assert {_cargar(ruta)["tipo"] for ruta in EJEMPLOS} == TIPOS_DEL_BRIEF
    assert all(_cargar(ruta)["tipo"] == ruta.stem for ruta in EJEMPLOS)


@pytest.mark.parametrize("ruta", EJEMPLOS, ids=lambda ruta: ruta.stem)
def test_ejemplo_valida_contra_el_esquema(ruta):
    validar_evento(_cargar(ruta))


CAMBIOS_INVALIDOS = {
    "sin_id": lambda e: e.pop("id"),
    "id_no_uuid": lambda e: e.update(id="123"),
    "version_esquema_2": lambda e: e.update(version_esquema=2),
    "estacion_desconocida": lambda e: e.update(estacion="cafeteria"),
    "tipo_desconocido": lambda e: e.update(tipo="otro_tipo"),
    "severidad_desconocida": lambda e: e.update(severidad="urgente"),
    "timestamp_sin_zona": lambda e: e.update(timestamp="2026-11-20T10:32:05"),
    "campo_extra_en_el_sobre": lambda e: e.update(nombre="Ana"),
    "tipo_en_estacion_equivocada": lambda e: e.update(estacion="epp"),
    "datos_sin_puntaje": lambda e: e["datos"].pop("puntaje"),
    "puntaje_fuera_de_rango": lambda e: e["datos"].update(puntaje=40),
    "nivel_desconocido": lambda e: e["datos"].update(nivel="terrible"),
    "adjunto_sin_ruta": lambda e: e.update(adjuntos=[{"tipo": "imagen"}]),
    "origen_incompleto": lambda e: e.update(origen={"dispositivo": "pc-stand"}),
}


@pytest.mark.parametrize("cambio", CAMBIOS_INVALIDOS.values(), ids=CAMBIOS_INVALIDOS.keys())
def test_evento_invalido_es_rechazado(evento_valido, cambio):
    evento = copy.deepcopy(evento_valido)
    cambio(evento)
    with pytest.raises(EventoInvalido):
        validar_evento(evento)


def test_un_lead_no_admite_datos_personales():
    lead = _cargar(CARPETA_EJEMPLOS / "lead_registrado.json")
    lead["datos"]["correo"] = "persona@empresa.com"
    with pytest.raises(EventoInvalido):
        validar_evento(lead)


def test_construir_evento_arma_un_sobre_valido(monkeypatch):
    monkeypatch.setenv("DISPOSITIVO", "pc-pruebas")
    evento = construir_evento(
        "zona", "ingreso_zona",
        {"zona_id": "prensa-1", "duracion_s": 2.8, "alarma_activada": True},
        severidad="media", sesion_id="V-0001",
    )
    assert evento["version_esquema"] == 1
    assert evento["timestamp"].endswith("-05:00")  # America/Bogota
    assert evento["origen"]["dispositivo"] == "pc-pruebas"
    assert evento["sesion_id"] == "V-0001"


def test_construir_evento_rechaza_datos_invalidos():
    with pytest.raises(EventoInvalido):
        construir_evento("zona", "ingreso_zona", {"zona_id": "prensa-1"})
