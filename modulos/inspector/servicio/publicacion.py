"""Publicación de una inspección: sube la foto anotada y el Excel y publica ``inspeccion_foto``.

Todo sale por ``modulos.comun`` (``subir_medio`` y ``publicar``). La foto que se sube es la
anotada sobre la imagen ya difuminada.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from modulos.comun import publicar, subir_medio

from .. import __version__
from ..configuracion import ESTACION
from ..nucleo.esquema import JERARQUIA
from ..nucleo.valoracion import severidad_del_evento

log = logging.getLogger(__name__)

TIPO = "inspeccion_foto"
_CAMPOS_DE_VALORACION = ("nd", "ne", "np", "interpretacion_np", "nc", "nr", "nivel_riesgo", "aceptabilidad")
_CAMPOS_DE_CONTEXTO = ("proceso", "zona", "actividad", "tarea")


def peligro_del_evento(peligro: dict) -> dict:
    """Un peligro valorado, con la forma de ``datos.peligros[]`` del contrato."""
    controles = peligro["controles_propuestos"]
    valoracion = peligro["valoracion"]
    datos: dict[str, Any] = {
        "peligro": peligro["descripcion"],
        "clasificacion": peligro["clasificacion"]["categoria"],
        "efectos": peligro["efectos_posibles"],
        "controles_propuestos": [control for nivel in JERARQUIA for control in controles[nivel]],
        "nivel_preliminar": valoracion["nivel_preliminar"],
        "subclasificacion": peligro["clasificacion"]["subcategoria"],
        "evidencia": peligro["evidencia_visible"],
        "confianza": peligro["confianza"],
        "ubicacion": peligro["ubicacion"],
        "peor_consecuencia": peligro["peor_consecuencia"],
        "controles_por_jerarquia": {nivel: list(controles[nivel]) for nivel in JERARQUIA},
        "exposicion": peligro["exposicion"],
        "controles_existentes": peligro["controles_existentes"],
        "valoracion": {campo: valoracion[campo] for campo in _CAMPOS_DE_VALORACION},
    }
    if peligro.get("expuestos") is not None:
        datos["expuestos"] = peligro["expuestos"]
    return datos


def datos_del_evento(inspeccion: dict, valorados: list[dict], descartados: int, contexto: dict | None,
                     url_excel: str) -> dict:
    """``datos`` del evento ``inspeccion_foto``."""
    analisis = inspeccion["analisis"]
    datos: dict[str, Any] = {
        "escena": (inspeccion.get("escena") or analisis["descripcion_general"] or "Escena sin descripción").strip(),
        "peligros": [peligro_del_evento(peligro) for peligro in valorados],
        "url_excel": url_excel,
        "inspeccion_id": inspeccion["id"],
        "borrador": True,
        "origen_analisis": inspeccion["origen"],
        "advertencias": list(analisis["advertencias"]),
        "peligros_descartados": descartados,
    }
    if inspeccion.get("modelo"):
        datos["modelo"] = inspeccion["modelo"]
    contexto = contexto or {}
    limpio = {campo: str(contexto[campo]).strip() for campo in _CAMPOS_DE_CONTEXTO
              if str(contexto.get(campo) or "").strip()}
    if isinstance(contexto.get("rutinaria"), bool):
        limpio["rutinaria"] = contexto["rutinaria"]
    if limpio:
        datos["contexto"] = limpio
    return datos


def publicar_inspeccion(inspeccion: dict, valorados: list[dict], descartados: int, contexto: dict | None,
                        ruta_imagen: Path, ruta_excel: Path) -> dict:
    """Sube la foto anotada y el Excel y publica el evento. Devuelve el sobre publicado.

    Si la plataforma no responde, ``subir_medio`` deja los archivos en la carpeta local de
    pendientes y ``publicar`` encola el evento: la persona recibe su Excel de todos modos.
    """
    ruta_medio_imagen = subir_medio(ruta_imagen)
    ruta_medio_excel = subir_medio(ruta_excel)
    sesion_id = (inspeccion.get("sesion_id") or "").strip()[:64] or None
    return publicar(
        ESTACION, TIPO,
        datos_del_evento(inspeccion, valorados, descartados, contexto, ruta_medio_excel),
        severidad=severidad_del_evento(peligro["valoracion"]["nivel_riesgo"] for peligro in valorados),
        sesion_id=sesion_id,
        adjuntos=[{"tipo": "imagen", "ruta": ruta_medio_imagen}, {"tipo": "excel", "ruta": ruta_medio_excel}],
        modulo_version=__version__,
    )
