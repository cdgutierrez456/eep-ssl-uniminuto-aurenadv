"""Configuración del módulo EPP: validación y sincronización con la plataforma."""

import json
import time

import httpx
import pytest

from modulos.comun import actualizar_config, obtener_config, registrar_capacidades
from modulos.comun import config_remota
from modulos.epp.nucleo.configuracion import (
    ConfigRechazada,
    capacidades_de,
    config_por_defecto,
    validar_config,
)
from modulos.epp.nucleo.perfiles import cargar_perfiles

PERFILES = cargar_perfiles()
CAPACIDADES = capacidades_de(PERFILES, {
    "alimentos": ["cofia", "gafas", "tapabocas"],
    "industria": ["casco", "gafas", "chaleco"],
})
POR_DEFECTO = config_por_defecto(PERFILES, CAPACIDADES)


def validar(candidata):
    """Validador que el módulo EPP le pasa a obtener_config."""
    return validar_config(candidata, CAPACIDADES, POR_DEFECTO)[0]


def esperar(condicion, limite_s: float = 5.0) -> None:
    fin = time.monotonic() + limite_s
    while time.monotonic() < fin:
        if condicion():
            return
        time.sleep(0.05)
    raise AssertionError("La condición no se cumplió a tiempo")


@pytest.fixture
def config_viva(entorno):
    """Crea configuraciones remotas y las detiene al terminar la prueba."""
    creadas = []

    def crear(**opciones):
        config = obtener_config("epp", POR_DEFECTO, validar=validar, intervalo_s=0.2, **opciones)
        creadas.append(config)
        return config

    yield crear
    for config in creadas:
        config.detener()
    config_remota._capacidades_pendientes.clear()


# ---------------------------------------------------------------------------
# Validación (funciones puras)
# ---------------------------------------------------------------------------
def test_config_por_defecto_sale_de_perfiles_yaml():
    assert POR_DEFECTO == {
        "perfil_activo": "industria",
        "perfiles": {
            "alimentos": {"elementos_requeridos": ["cofia", "gafas", "tapabocas"]},
            "industria": {"elementos_requeridos": ["casco", "gafas"]},
        },
    }


def test_capacidades_llevan_nombre_visible():
    industria = CAPACIDADES["perfiles"]["industria"]
    assert industria["nombre"] == "Industria"
    assert industria["elementos"] == [
        {"id": "casco", "nombre": "Casco"}, {"id": "gafas", "nombre": "Gafas"}, {"id": "chaleco", "nombre": "Chaleco"},
    ]


def test_elemento_desconocido_se_ignora_con_advertencia():
    config, advertencias = validar_config(
        {"perfil_activo": "industria", "perfiles": {"industria": {"elementos_requeridos": ["casco", "arnes"]}}},
        CAPACIDADES, POR_DEFECTO,
    )
    assert config["perfiles"]["industria"]["elementos_requeridos"] == ["casco"]
    assert any("arnes" in aviso for aviso in advertencias)


def test_perfil_inexistente_se_rechaza():
    with pytest.raises(ConfigRechazada, match="alturas"):
        validar_config({"perfil_activo": "alturas"}, CAPACIDADES, POR_DEFECTO)


@pytest.mark.parametrize("mala", [
    {}, {"perfil_activo": 3}, {"perfil_activo": "industria", "otro": 1}, "industria",
    {"perfil_activo": "industria", "perfiles": {"industria": {"elementos_requeridos": "casco"}}},
])
def test_config_mal_formada_se_rechaza(mala):
    with pytest.raises(ConfigRechazada):
        validar_config(mala, CAPACIDADES, POR_DEFECTO)


def test_perfil_no_mencionado_conserva_sus_valores_por_defecto():
    config, advertencias = validar_config({"perfil_activo": "alimentos"}, CAPACIDADES, POR_DEFECTO)
    assert config == {**POR_DEFECTO, "perfil_activo": "alimentos"}
    assert advertencias == []


def test_perfil_cuyo_modelo_no_cargo_no_se_puede_activar():
    solo_industria = capacidades_de(PERFILES, {"industria": ["casco", "gafas", "chaleco"]})
    defecto = config_por_defecto(PERFILES, solo_industria)
    assert list(defecto["perfiles"]) == ["industria"]
    with pytest.raises(ConfigRechazada):
        validar_config({"perfil_activo": "alimentos"}, solo_industria, defecto)


# ---------------------------------------------------------------------------
# Sincronización con la plataforma (receptor de prueba real)
# ---------------------------------------------------------------------------
def test_sin_plataforma_y_sin_cache_usa_el_archivo_local(config_viva, tmp_path):
    archivo = tmp_path / "defecto.json"
    archivo.write_text(json.dumps(POR_DEFECTO), encoding="utf-8")
    config = obtener_config("epp", archivo, validar=validar, intervalo_s=0.2)
    try:
        assert config.valor == POR_DEFECTO
        assert config.fuente == "defecto"
    finally:
        config.detener()


def test_cambio_remoto_se_aplica_en_vivo_y_avisa(entorno, config_viva):
    entorno.encender()
    cambios = []
    config = config_viva(al_cambiar=cambios.append)
    # La plataforma no tenía configuración: el módulo le entrega la suya
    esperar(lambda: httpx.get(entorno.url + "/api/modulos/epp/config").status_code == 200)
    assert httpx.get(entorno.url + "/api/modulos/epp/config").json() == POR_DEFECTO

    nueva = {"perfil_activo": "alimentos", "perfiles": {"alimentos": {"elementos_requeridos": ["cofia"]}}}
    httpx.put(entorno.url + "/api/modulos/epp/config", json=nueva).raise_for_status()
    esperar(lambda: config.valor["perfil_activo"] == "alimentos")
    assert config.valor["perfiles"]["alimentos"]["elementos_requeridos"] == ["cofia"]
    assert config.valor["perfiles"]["industria"] == POR_DEFECTO["perfiles"]["industria"]
    assert config.fuente == "plataforma"
    assert [c["perfil_activo"] for c in cambios] == ["alimentos"]


def test_elemento_desconocido_remoto_se_ignora(entorno, config_viva):
    entorno.encender()
    httpx.put(entorno.url + "/api/modulos/epp/config", json={
        "perfil_activo": "industria", "perfiles": {"industria": {"elementos_requeridos": ["arnes", "casco", "chaleco"]}},
    }).raise_for_status()
    config = config_viva()
    esperar(lambda: config.fuente == "plataforma")
    assert config.valor["perfiles"]["industria"]["elementos_requeridos"] == ["casco", "chaleco"]


def test_perfil_inexistente_remoto_se_rechaza_y_se_mantiene_la_anterior(entorno, config_viva):
    entorno.encender()
    cambios = []
    config = config_viva(al_cambiar=cambios.append)
    esperar(lambda: httpx.get(entorno.url + "/api/modulos/epp/config").status_code == 200)
    httpx.put(entorno.url + "/api/modulos/epp/config", json={"perfil_activo": "alturas"}).raise_for_status()
    time.sleep(0.8)  # varias consultas
    assert config.valor == POR_DEFECTO
    assert cambios == []


def test_plataforma_caida_usa_la_cache(entorno, config_viva):
    entorno.encender()
    primera = config_viva()
    esperar(lambda: httpx.get(entorno.url + "/api/modulos/epp/config").status_code == 200)
    httpx.put(entorno.url + "/api/modulos/epp/config", json={"perfil_activo": "alimentos"}).raise_for_status()
    esperar(lambda: primera.valor["perfil_activo"] == "alimentos")
    primera.detener()
    entorno.apagar()

    # El módulo se reinicia sin plataforma: arranca con la última configuración válida
    segunda = config_viva()
    assert segunda.valor["perfil_activo"] == "alimentos"
    assert segunda.fuente == "cache"
    time.sleep(0.5)
    assert segunda.valor["perfil_activo"] == "alimentos"


def test_actualizar_config_aplica_ya_y_sube_a_la_plataforma(entorno, config_viva):
    entorno.encender()
    cambios = []
    config = config_viva(al_cambiar=cambios.append)
    esperar(lambda: httpx.get(entorno.url + "/api/modulos/epp/config").status_code == 200)

    assert actualizar_config("epp", {**POR_DEFECTO, "perfil_activo": "alimentos"}) is True
    assert config.valor["perfil_activo"] == "alimentos"  # sin esperar a la siguiente consulta
    assert [c["perfil_activo"] for c in cambios] == ["alimentos"]
    assert httpx.get(entorno.url + "/api/modulos/epp/config").json()["perfil_activo"] == "alimentos"

    with pytest.raises(ConfigRechazada):
        actualizar_config("epp", {"perfil_activo": "alturas"})
    assert config.valor["perfil_activo"] == "alimentos"


def test_cambio_local_sin_plataforma_se_sube_cuando_vuelve(entorno, config_viva):
    config = config_viva()
    assert actualizar_config("epp", {**POR_DEFECTO, "perfil_activo": "alimentos"}) is False
    assert config.valor["perfil_activo"] == "alimentos"
    entorno.encender()
    esperar(lambda: httpx.get(entorno.url + "/api/modulos/epp/config").status_code == 200)
    assert httpx.get(entorno.url + "/api/modulos/epp/config").json()["perfil_activo"] == "alimentos"


def test_capacidades_se_registran_y_se_reintentan(entorno, config_viva):
    assert registrar_capacidades("epp", CAPACIDADES) is False  # plataforma apagada
    entorno.encender()
    config_viva()  # su hilo reintenta el registro pendiente
    esperar(lambda: httpx.get(entorno.url + "/api/modulos/epp/capacidades").status_code == 200)
    assert httpx.get(entorno.url + "/api/modulos/epp/capacidades").json() == CAPACIDADES
    modulos = httpx.get(entorno.url + "/api/modulos").json()
    assert modulos["epp"]["capacidades"] == CAPACIDADES


def test_el_receptor_rechaza_una_config_mal_formada(entorno):
    entorno.encender()
    respuesta = httpx.put(entorno.url + "/api/modulos/epp/config", json={"perfil": "industria"})
    assert respuesta.status_code == 422
    assert httpx.get(entorno.url + "/api/modulos/epp/config").status_code == 404
