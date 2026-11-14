"""Motor de reglas de EPP: casos dorados originales (alimentos) y nuevos (industria).

Los de alimentos son los del proyecto original, sin tocar: pasan por
``adaptar_reglas_antiguas`` y deben dar exactamente el mismo veredicto que antes.
"""

import json
from pathlib import Path

import pytest

from modulos.epp.nucleo import reglas as motor
from modulos.epp.nucleo.perfiles import cargar_perfiles, elementos_detectables, reglas_de_perfil
from modulos.epp.nucleo.suavizado import SuavizadorTemporal

CASOS = Path(__file__).parent / "casos"
CLASES_ALIMENTOS = ["persona", "cofia", "gafas", "tapabocas", "sin_cofia", "sin_gafas", "sin_tapabocas"]
CLASES_INDUSTRIA = ["persona", "casco", "gafas", "chaleco", "sin_casco", "sin_gafas"]


def _json(nombre: str):
    return json.loads((CASOS / nombre).read_text(encoding="utf-8"))


def _con_override(reglas: dict, override: dict | None) -> dict:
    """Reemplaza claves de primer nivel completas (misma semántica que el proyecto original)."""
    copia = json.loads(json.dumps(reglas))
    copia.update(override or {})
    return copia


REGLAS_ALIMENTOS = _json("reglas_alimentos_v1.json")
ALIMENTOS = _json("casos_alimentos.json")
INDUSTRIA = _json("casos_industria.json")

IMAGENES = (
    [(REGLAS_ALIMENTOS, caso) for caso in ALIMENTOS["casos_imagen"]]
    + [(INDUSTRIA["reglas"], caso) for caso in INDUSTRIA["casos_imagen"]]
)
SECUENCIAS = (
    [(REGLAS_ALIMENTOS, s) for s in ALIMENTOS["secuencias"]]
    + [(INDUSTRIA["reglas"], s) for s in INDUSTRIA["secuencias"]]
)


def _reglas_del_caso(base: dict, caso: dict) -> dict:
    return motor.adaptar_reglas_antiguas(_con_override(base, caso.get("reglas_override")))


@pytest.mark.parametrize("base, caso", IMAGENES, ids=[c["id"] for _, c in IMAGENES])
def test_caso_dorado_imagen(base, caso):
    entrada = json.loads(json.dumps(caso["detecciones"]))
    resultado = motor.evaluar_cuadro(entrada, _reglas_del_caso(base, caso))
    assert resultado == caso["esperado"], f"{caso['id']}: {caso['descripcion']}"
    assert entrada == caso["detecciones"], "evaluar_cuadro no debe modificar la entrada"
    json.dumps(resultado)


def _subconjunto(obtenido, esperado, ruta: str) -> None:
    """Compara solo las claves presentes en ``esperado``."""
    if isinstance(esperado, dict):
        for clave, valor in esperado.items():
            assert clave in obtenido, f"{ruta}: falta '{clave}'"
            _subconjunto(obtenido[clave], valor, f"{ruta}.{clave}")
    elif isinstance(esperado, list):
        assert len(obtenido) == len(esperado), f"{ruta}: longitud {len(obtenido)} != {len(esperado)}"
        for indice, (o, e) in enumerate(zip(obtenido, esperado)):
            _subconjunto(o, e, f"{ruta}[{indice}]")
    else:
        assert obtenido == esperado, f"{ruta}: obtenido {obtenido!r}, esperado {esperado!r}"


@pytest.mark.parametrize("base, secuencia", SECUENCIAS, ids=[s["id"] for _, s in SECUENCIAS])
def test_secuencia_dorada(base, secuencia):
    reglas = _reglas_del_caso(base, secuencia)
    suavizador = SuavizadorTemporal(reglas)
    for numero, paso in enumerate(secuencia["pasos"], start=1):
        if paso.get("reiniciar"):
            suavizador.reiniciar()
        suavizado = suavizador.procesar(motor.evaluar_cuadro(paso["detecciones"], reglas))
        _subconjunto(suavizado, paso["esperado"], f"{secuencia['id']} paso {numero}")


def test_estan_todos_los_casos_originales():
    assert len(ALIMENTOS["casos_imagen"]) == 25
    assert len(ALIMENTOS["secuencias"]) == 11


# ---------------------------------------------------------------------------
# Perfiles: perfiles.yaml produce las mismas reglas que los casos dorados usan
# ---------------------------------------------------------------------------
CLAVES_DEL_MOTOR = ["clase_persona", "elementos_requeridos", "clases_negativas", "umbral_confianza",
                    "zonas", "primer_plano", "suavizado"]


def test_perfil_alimentos_equivale_a_las_reglas_originales():
    del_yaml = reglas_de_perfil(cargar_perfiles(), "alimentos", clases_modelo=CLASES_ALIMENTOS)
    originales = motor.adaptar_reglas_antiguas(REGLAS_ALIMENTOS)
    assert {c: del_yaml[c] for c in CLAVES_DEL_MOTOR} == {c: originales[c] for c in CLAVES_DEL_MOTOR}


def test_perfil_industria_equivale_a_las_reglas_de_sus_casos():
    del_yaml = reglas_de_perfil(cargar_perfiles(), "industria", clases_modelo=CLASES_INDUSTRIA)
    assert {c: del_yaml[c] for c in CLAVES_DEL_MOTOR} == {c: INDUSTRIA["reglas"][c] for c in CLAVES_DEL_MOTOR}


def test_elementos_detectables_salen_de_las_clases_del_modelo():
    perfiles = cargar_perfiles()
    assert elementos_detectables(perfiles, "industria", CLASES_INDUSTRIA) == ["casco", "gafas", "chaleco"]
    assert elementos_detectables(perfiles, "alimentos", CLASES_ALIMENTOS) == ["cofia", "gafas", "tapabocas"]


def test_elemento_del_modelo_que_el_yaml_no_nombra_usa_los_valores_por_defecto():
    clases = CLASES_INDUSTRIA + ["proteccion_auditiva", "sin_proteccion_auditiva"]
    perfiles = cargar_perfiles()
    assert elementos_detectables(perfiles, "industria", clases)[-1] == "proteccion_auditiva"
    reglas = reglas_de_perfil(perfiles, "industria", ["casco", "proteccion_auditiva"], clases)
    assert reglas["zonas"]["proteccion_auditiva"] == [0.0, 1.0]
    assert reglas["clases_negativas"]["proteccion_auditiva"] == "sin_proteccion_auditiva"
    assert reglas["umbral_confianza"]["proteccion_auditiva"] == 0.5


def test_zonas_antiguas_equivalen_a_la_franja_superior():
    adaptadas = motor.adaptar_reglas_antiguas(REGLAS_ALIMENTOS)
    assert adaptadas["zonas"] == {e: [0.0, 0.625] for e in ("cofia", "gafas", "tapabocas")}
    assert adaptadas["primer_plano"]["zona"] == [0.0, 1.0]
    assert "asociacion" in REGLAS_ALIMENTOS, "el adaptador no debe modificar la entrada"
