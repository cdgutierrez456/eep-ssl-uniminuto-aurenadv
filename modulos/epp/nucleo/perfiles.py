"""Perfiles de EPP: carga de perfiles.yaml y traducción a reglas del motor.

Funciones puras (sin Ultralytics ni OpenCV). Un perfil dice qué modelo usar, qué
elementos se exigen por defecto y cómo afinar cada elemento (umbral, zona, negativa).
Qué elementos *sabe detectar* un perfil sale de las clases de su modelo cargado
(``elementos_detectables``), no de una lista escrita a mano.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

RUTA_PERFILES = Path(__file__).resolve().parents[1] / "config" / "perfiles.yaml"
PREFIJO_NEGATIVA = "sin_"


class PerfilInvalido(ValueError):
    """El archivo de perfiles está mal formado o el perfil pedido no existe."""


def cargar_perfiles(ruta: str | Path = RUTA_PERFILES) -> dict[str, Any]:
    """Lee perfiles.yaml y comprueba lo mínimo para fallar pronto y con mensaje claro."""
    with open(ruta, encoding="utf-8") as archivo:
        perfiles = yaml.safe_load(archivo)
    if not isinstance(perfiles, dict) or not isinstance(perfiles.get("perfiles"), dict) or not perfiles["perfiles"]:
        raise PerfilInvalido(f"{ruta}: debe tener una sección 'perfiles' con al menos un perfil")
    for nombre, perfil in perfiles["perfiles"].items():
        for campo in ("nombre", "modelo", "elementos_requeridos"):
            if campo not in perfil:
                raise PerfilInvalido(f"{ruta}: al perfil '{nombre}' le falta '{campo}'")
        for elemento, ajustes in (perfil.get("elementos") or {}).items():
            zona = (ajustes or {}).get("zona", [0.0, 1.0])
            if not (isinstance(zona, list) and len(zona) == 2 and 0 <= zona[0] < zona[1] <= 1):
                raise PerfilInvalido(
                    f"{ruta}: la zona de '{elemento}' en '{nombre}' debe ser [inicio, fin] con 0 <= inicio < fin <= 1"
                )
    por_defecto = perfiles.get("perfil_por_defecto")
    if por_defecto not in perfiles["perfiles"]:
        raise PerfilInvalido(f"{ruta}: perfil_por_defecto '{por_defecto}' no existe")
    return perfiles


def _perfil(perfiles: dict[str, Any], nombre: str) -> dict[str, Any]:
    try:
        return perfiles["perfiles"][nombre]
    except KeyError:
        raise PerfilInvalido(f"No existe el perfil '{nombre}'") from None


def _ajustes(perfiles: dict[str, Any], perfil: dict[str, Any], elemento: str) -> dict[str, Any]:
    """Ajustes del elemento: los del perfil sobre ``elemento_por_defecto``."""
    ajustes = dict(perfiles.get("elemento_por_defecto") or {})
    ajustes.update((perfil.get("elementos") or {}).get(elemento) or {})
    return ajustes


def _negativa(ajustes: dict[str, Any], elemento: str, clases_modelo: set[str] | None) -> str | None:
    """Clase negativa del elemento: la declarada o, si el modelo la tiene, sin_<elemento>."""
    if "negativa" in ajustes:
        return ajustes["negativa"]
    candidata = PREFIJO_NEGATIVA + elemento
    return candidata if clases_modelo is not None and candidata in clases_modelo else None


def elementos_detectables(perfiles: dict[str, Any], nombre: str, clases_modelo: Iterable[str]) -> list[str]:
    """Elementos que el modelo del perfil sabe detectar, en el orden de sus clases.

    Son las clases del modelo menos la persona y las negativas (las declaradas en el
    perfil y las que empiezan por ``sin_``).
    """
    perfil = _perfil(perfiles, nombre)
    clases = list(clases_modelo)
    negativas = {
        (ajustes or {}).get("negativa") for ajustes in (perfil.get("elementos") or {}).values()
    }
    return [
        clase for clase in clases
        if clase != perfiles.get("clase_persona", "persona")
        and clase not in negativas
        and not clase.startswith(PREFIJO_NEGATIVA)
    ]


def nombre_visible(perfiles: dict[str, Any], nombre: str, elemento: str) -> str:
    """Nombre del elemento para el panel («Protección auditiva» y no «proteccion_auditiva»)."""
    ajustes = (_perfil(perfiles, nombre).get("elementos") or {}).get(elemento) or {}
    return ajustes.get("nombre") or elemento.replace("_", " ").capitalize()


def reglas_de_perfil(
    perfiles: dict[str, Any],
    nombre: str,
    elementos_requeridos: Iterable[str] | None = None,
    clases_modelo: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Arma las reglas del motor (``reglas.evaluar_cuadro``) para un perfil.

    ``elementos_requeridos`` sustituye a los del archivo (configuración remota).
    ``clases_modelo`` permite reconocer elementos y negativas que el modelo detecta
    aunque el archivo no los nombre; sin él solo cuentan los elementos del archivo.
    """
    perfil = _perfil(perfiles, nombre)
    clases = set(clases_modelo) if clases_modelo is not None else None
    requeridos = list(perfil["elementos_requeridos"] if elementos_requeridos is None else elementos_requeridos)

    elementos = list(perfil.get("elementos") or {})
    if clases is not None:
        elementos += [e for e in elementos_detectables(perfiles, nombre, clases_modelo) if e not in elementos]
    elementos += [e for e in requeridos if e not in elementos]

    clase_persona = perfiles.get("clase_persona", "persona")
    umbrales: dict[str, float] = {clase_persona: perfil.get("umbral_persona", 0.5)}
    negativas: dict[str, str] = {}
    zonas: dict[str, list[float]] = {}
    for elemento in elementos:
        ajustes = _ajustes(perfiles, perfil, elemento)
        umbrales[elemento] = ajustes.get("umbral", 0.5)
        zonas[elemento] = [float(v) for v in ajustes.get("zona", [0.0, 1.0])]
        negativa = _negativa(ajustes, elemento, clases)
        if negativa:
            negativas[elemento] = negativa
            umbrales[negativa] = ajustes.get("umbral_negativa", 0.6)

    return {
        "perfil": nombre,
        "clase_persona": clase_persona,
        "elementos_requeridos": requeridos,
        "clases_negativas": negativas,
        "umbral_confianza": umbrales,
        "zonas": zonas,
        "primer_plano": dict(perfiles["primer_plano"]),
        "suavizado": dict(perfiles["suavizado"]),
    }
