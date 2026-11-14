"""Contenido de los eventos de la zona y su validez contra el contrato."""

import json
import math
from pathlib import Path

import pytest

from modulos.comun import EventoInvalido, construir_evento
from modulos.zona.nucleo import EstadoZona, Textos, evento_casi_accidente, evento_estado_zona, evento_ingreso_zona
from modulos.zona.nucleo.eventos import descripcion_casi_accidente

CARPETA_EJEMPLOS = Path(__file__).resolve().parents[2] / "contrato" / "ejemplos"


@pytest.fixture(autouse=True)
def _dispositivo(monkeypatch):
    monkeypatch.setenv("DISPOSITIVO", "pc-pruebas")


def publicable(evento) -> dict:
    """El sobre que saldría hacia la plataforma; lanza EventoInvalido si no cumple el contrato."""
    return construir_evento("zona", evento.tipo, evento.datos, evento.severidad)


# ---------------------------------------------------------------- estado_zona
@pytest.mark.parametrize("estado, severidad", [("libre", "info"), ("advertencia", "media"), ("peligro", "alta")])
def test_estado_zona(estado, severidad):
    evento = evento_estado_zona("piso", EstadoZona(estado, 1 if estado == "peligro" else 0,
                                                   1 if estado == "advertencia" else 0))
    assert evento.tipo == "estado_zona" and evento.severidad == severidad
    assert evento.urgente and evento.persona_id is None
    assert "refresco" not in evento.datos
    assert publicable(evento)["datos"]["estado"] == estado


def test_estado_zona_de_refresco():
    evento = evento_estado_zona("mano", EstadoZona("peligro", 1, 0), refresco=True)
    assert evento.datos == {"zona_id": "mano", "estado": "peligro", "personas_peligro": 1,
                            "personas_advertencia": 0, "refresco": True}
    publicable(evento)


def test_el_contrato_rechaza_un_estado_desconocido_y_exige_los_conteos():
    with pytest.raises(EventoInvalido):
        construir_evento("zona", "estado_zona", {"zona_id": "piso", "estado": "alerta",
                                                 "personas_peligro": 0, "personas_advertencia": 0})
    with pytest.raises(EventoInvalido):
        construir_evento("zona", "estado_zona", {"zona_id": "piso", "estado": "libre"})
    with pytest.raises(EventoInvalido):   # solo lo publica la estación de zona
        construir_evento("epp", "estado_zona", {"zona_id": "piso", "estado": "libre",
                                                "personas_peligro": 0, "personas_advertencia": 0})


# --------------------------------------------------------------- ingreso_zona
def test_ingreso_zona():
    evento = evento_ingreso_zona("piso", 4.6642, True, persona_id=7)
    assert evento.tipo == "ingreso_zona" and evento.severidad == "alta" and not evento.urgente
    assert evento.datos == {"zona_id": "piso", "duracion_s": 4.7, "alarma_activada": True}
    assert evento.persona_id == 7
    publicable(evento)


def test_un_ingreso_nunca_dura_menos_de_cero():
    assert evento_ingreso_zona("piso", -0.01, False).datos["duracion_s"] == 0.0


# ------------------------------------------------------------- casi_accidente
def test_casi_accidente_en_metros():
    evento = evento_casi_accidente("piso", 46.2, 0.318, persona_id=3)
    assert evento.tipo == "casi_accidente" and evento.severidad == "alta"
    assert evento.datos == {
        "zona_id": "piso",
        "descripcion": "Una persona se acercó a 0,32 m de la zona de peligro y se retiró sin entrar.",
        "distancia_min_px": 46.2,
        "distancia_min_m": 0.32,
    }
    publicable(evento)


def test_casi_accidente_en_pixeles_no_menciona_metros():
    evento = evento_casi_accidente("piso", 46.2)
    assert evento.datos == {
        "zona_id": "piso",
        "descripcion": "Una persona se acercó a la zona de peligro hasta la franja de advertencia y se retiró sin entrar.",
        "distancia_min_px": 46.2,
    }
    publicable(evento)


def test_casi_accidente_que_rozo_el_borde():
    evento = evento_casi_accidente("piso", 0.0, 0.0)
    assert evento.datos["descripcion"] == "Una persona alcanzó el borde de la zona de peligro y se retiró sin llegar a entrar."
    assert evento.datos["distancia_min_m"] == 0.0
    publicable(evento)


def test_casi_accidente_sin_distancia_medible_omite_los_campos():
    evento = evento_casi_accidente("piso", math.inf, math.inf)
    assert set(evento.datos) == {"zona_id", "descripcion"}
    publicable(evento)


def test_la_zona_de_mano_usa_sus_propias_palabras():
    textos = Textos(quien="Una mano", lugar="la zona de atrapamiento")
    assert descripcion_casi_accidente(None, textos) == (
        "Una mano se acercó a la zona de atrapamiento hasta la franja de advertencia y se retiró sin entrar.")
    assert evento_casi_accidente("mano", 12.0, textos=textos).datos["zona_id"] == "mano"


# ------------------------------------------------------------------- ejemplos
def test_el_ejemplo_de_casi_accidente_es_lo_que_el_modulo_publica():
    ejemplo = json.loads((CARPETA_EJEMPLOS / "casi_accidente.json").read_text(encoding="utf-8"))
    evento = evento_casi_accidente("piso", 46, 0.32)
    assert ejemplo["datos"] == evento.datos
    assert ejemplo["severidad"] == evento.severidad


def test_el_ejemplo_de_estado_zona_es_lo_que_el_modulo_publica():
    ejemplo = json.loads((CARPETA_EJEMPLOS / "estado_zona.json").read_text(encoding="utf-8"))
    evento = evento_estado_zona("piso", EstadoZona("peligro", 1, 0))
    assert ejemplo["datos"] == evento.datos
    assert ejemplo["severidad"] == evento.severidad
