"""Configuración del módulo de zona.

Dos niveles:

- **Local (.env)**: lo que depende del equipo y no cambia durante la demo: cámara y pantalla.
  Se lee una vez al arrancar (``AjustesLocales.desde_entorno``).
- **Operativa (remota)**: la zona, su calibración y los parámetros de detección, que se
  ajustan en vivo desde la plataforma o desde la ventana de la estación. Su valor por
  defecto está en ``por_defecto.json`` y su forma en ``contrato/config_zona.schema.json``.
  ``validar_config`` es el validador que se le pasa a ``modulos.comun.obtener_config``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from modulos.comun.camara_stand import ConfigCamara

from ..nucleo.estados import Parametros
from ..nucleo.geometria import es_poligono_valido
from ..nucleo.zona import Zona, crear_zona

MODULO = "zona"
ESTACION = "zona"
ZONA_PISO = "piso"
RUTA_POR_DEFECTO = Path(__file__).with_name("por_defecto.json")
DECIMALES_DE_VERTICE = 5  # una cienmilésima de la imagen: menos de un píxel

# Lo que el módulo le cuenta a la plataforma para que pinte el editor de zona. La estación
# le agrega ``imagen_referencia`` (ruta, tamaño y hora) cada vez que toma una.
CAPACIDADES: dict[str, Any] = {
    "zonas": [{"id": ZONA_PISO, "nombre": "Zona de piso"}],
    "margen_advertencia_m": {"minimo": 0, "maximo": 3},
    "imagen_referencia": None,
}


def _booleano(texto: str | None, por_defecto: bool) -> bool:
    if texto is None or not texto.strip():
        return por_defecto
    return texto.strip().lower() in ("1", "true", "si", "sí", "on")


@dataclass(frozen=True)
class AjustesLocales:
    """Ajustes del equipo, leídos del .env."""

    camara: ConfigCamara
    pantalla_completa: bool = True
    ancho_pantalla: int = 1920
    alto_pantalla: int = 1080
    dispositivo: str = "cpu"  # cpu, auto (GPU solo si está libre) o gpu
    imgsz: int = 640  # lado de la imagen que ve el detector; más pequeño es más rápido y menos preciso
    modelo: Path | None = None  # otros pesos de pose; None = modulos/zona/modelos/yolo26n-pose.pt

    @classmethod
    def desde_entorno(cls) -> "AjustesLocales":
        def numero(nombre: str, por_defecto: int) -> int:
            try:
                return int(os.getenv(nombre, "").strip() or por_defecto)
            except ValueError:
                return por_defecto

        modelo = (os.getenv("ZONA_MODELO") or "").strip()
        return cls(
            camara=ConfigCamara.desde_entorno("ZONA"),
            pantalla_completa=_booleano(os.getenv("ZONA_PANTALLA_COMPLETA"), True),
            ancho_pantalla=numero("ZONA_PANTALLA_ANCHO", 1920),
            alto_pantalla=numero("ZONA_PANTALLA_ALTO", 1080),
            dispositivo=(os.getenv("ZONA_DISPOSITIVO") or "cpu").strip().lower(),
            imgsz=numero("ZONA_IMGSZ", 640),
            modelo=Path(modelo) if modelo else None,
        )


# --------------------------------------------------------------------------- #
# Validación de la configuración operativa
# --------------------------------------------------------------------------- #
def _por_defecto() -> dict[str, Any]:
    return json.loads(RUTA_POR_DEFECTO.read_text(encoding="utf-8"))


def _es_numero(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and valor == valor  # descarta NaN


def _exigir(condicion: bool, mensaje: str) -> None:
    if not condicion:
        raise ValueError(mensaje)


def _numero_en(valor: Any, nombre: str, minimo: float, maximo: float) -> float:
    _exigir(_es_numero(valor) and minimo <= valor <= maximo, f"{nombre} debe ser un número entre {minimo:g} y {maximo:g}")
    return valor


def _texto_o_nulo(valor: Any, nombre: str, largo_maximo: int = 512) -> str | None:
    if valor is None:
        return None
    _exigir(isinstance(valor, str) and 0 < len(valor.strip()) <= largo_maximo, f"{nombre} debe ser un texto o null")
    return valor.strip()


def _poligono_o_nulo(valor: Any, nombre: str) -> list[list[float]] | None:
    """Polígono normalizado: vértices recortados a la imagen y redondeados. Rechaza el que no encierra área."""
    if valor is None:
        return None
    _exigir(isinstance(valor, (list, tuple)) and 3 <= len(valor) <= 64,
            f"{nombre} debe ser una lista de 3 a 64 vértices, o null")
    vertices = []
    for vertice in valor:
        _exigir(isinstance(vertice, (list, tuple)) and len(vertice) == 2 and all(_es_numero(c) for c in vertice),
                f"cada vértice de {nombre} debe ser un par [x, y] de números")
        vertices.append([round(min(1.0, max(0.0, float(c))), DECIMALES_DE_VERTICE) for c in vertice])
    _exigir(es_poligono_valido(vertices),
            f"{nombre} no encierra un área: revisa que los vértices no estén alineados ni marcados en desorden")
    return vertices


def _rectangulo_o_nulo(valor: Any) -> dict[str, float] | None:
    if valor is None:
        return None
    _exigir(isinstance(valor, dict), "rectangulo_real debe ser un objeto con ancho_m y largo_m, o null")
    medidas = {}
    for clave in ("ancho_m", "largo_m"):
        medida = valor.get(clave)
        _exigir(_es_numero(medida) and 0 < medida <= 50, f"rectangulo_real.{clave} debe ser un número mayor que 0 (hasta 50)")
        medidas[clave] = medida
    return medidas


def _zona_propuesta_o_nula(valor: Any) -> dict[str, Any] | None:
    if valor is None:
        return None
    _exigir(isinstance(valor, dict), "zona_propuesta debe ser un objeto o null")
    poligono = _poligono_o_nulo(valor.get("poligono"), "zona_propuesta.poligono")
    mensaje = valor.get("mensaje", "")
    _exigir(isinstance(mensaje, str), "zona_propuesta.mensaje debe ser un texto")
    return {
        "solicitud": _texto_o_nulo(valor.get("solicitud"), "zona_propuesta.solicitud", 64),
        "poligono": poligono,
        "es_cuadrilatero": poligono is not None and len(poligono) == 4,
        "mensaje": mensaje,
        "imagen_referencia": _texto_o_nulo(valor.get("imagen_referencia"), "zona_propuesta.imagen_referencia"),
    }


# Rangos de los parámetros numéricos de cada grupo: (mínimo, máximo)
_RANGOS_DETECCION = {
    "confianza_persona": (0, 1),
    "confianza_punto": (0, 1),
    "antirrebote_s": (0, 5),
    "histeresis": (0, 1),
    "segundos_perdida": (0, 30),
    "segundos_perdida_peligro": (0, 60),
    "radio_reasociacion_m": (0, 5),
    "radio_reasociacion_px": (0, 2000),
}
_RANGOS_HSV = {"h_min": (0, 179), "h_max": (0, 179), "s_min": (0, 255), "v_min": (0, 255)}


def validar_config(candidata: Any) -> dict[str, Any]:
    """Valida y normaliza la configuración operativa. Lanza ``ValueError`` si no sirve.

    Las claves que falten toman su valor por defecto y las desconocidas se descartan, así que
    lo que el módulo aplica puede diferir de lo que la plataforma guardó. Una configuración
    con algo inválido se rechaza entera y se conserva la anterior.
    """
    _exigir(isinstance(candidata, dict), "la configuración debe ser un objeto")
    config = _por_defecto()
    datos = {clave: valor for clave, valor in candidata.items() if clave in config}

    if "zona_peligro" in datos:
        datos["zona_peligro"] = _poligono_o_nulo(datos["zona_peligro"], "zona_peligro")
    if "rectangulo_real" in datos:
        datos["rectangulo_real"] = _rectangulo_o_nulo(datos["rectangulo_real"])
    if "margen_advertencia_m" in datos:
        _numero_en(datos["margen_advertencia_m"], "margen_advertencia_m", 0, 10)
    if "margen_advertencia_px" in datos:
        _numero_en(datos["margen_advertencia_px"], "margen_advertencia_px", 0, 2000)
    if "imagen_referencia" in datos:
        datos["imagen_referencia"] = _texto_o_nulo(datos["imagen_referencia"], "imagen_referencia")
    if "solicitud_deteccion" in datos:
        datos["solicitud_deteccion"] = _texto_o_nulo(datos["solicitud_deteccion"], "solicitud_deteccion", 64)
    if "zona_propuesta" in datos:
        datos["zona_propuesta"] = _zona_propuesta_o_nula(datos["zona_propuesta"])
    for grupo, rangos in (("deteccion", _RANGOS_DETECCION), ("cinta_hsv", _RANGOS_HSV)):
        if grupo not in datos:
            continue
        valores = datos[grupo]
        _exigir(isinstance(valores, dict), f"{grupo} debe ser un objeto")
        normalizado = dict(config[grupo])
        for clave, (minimo, maximo) in rangos.items():
            if clave in valores:
                normalizado[clave] = _numero_en(valores[clave], f"{grupo}.{clave}", minimo, maximo)
        datos[grupo] = normalizado
    if "cinta_hsv" in datos:
        hsv = datos["cinta_hsv"]
        _exigir(all(isinstance(valor, int) for valor in hsv.values()), "los valores de cinta_hsv deben ser enteros")
        _exigir(hsv["h_min"] <= hsv["h_max"], "cinta_hsv.h_min no puede ser mayor que cinta_hsv.h_max")
    if "sonido_local" in datos:
        _exigir(isinstance(datos["sonido_local"], bool), "sonido_local debe ser verdadero o falso")
    config.update(datos)
    return config


# --------------------------------------------------------------------------- #
# De la configuración (ya validada) al núcleo
# --------------------------------------------------------------------------- #
def zona_desde_config(config: Mapping[str, Any], ancho_imagen: int, alto_imagen: int) -> Zona | None:
    """La zona de piso lista para vigilar, o None si todavía no se ha marcado."""
    if not config.get("zona_peligro"):
        return None
    return crear_zona(
        ZONA_PISO, config["zona_peligro"], ancho_imagen, alto_imagen,
        margen_px=config["margen_advertencia_px"], margen_m=config["margen_advertencia_m"],
        rectangulo_real=config.get("rectangulo_real"), histeresis=config["deteccion"]["histeresis"],
    )


def parametros_desde(config: Mapping[str, Any]) -> Parametros:
    """Tiempos de la máquina de estados a partir de la configuración."""
    deteccion = config["deteccion"]
    return Parametros(
        antirrebote_s=float(deteccion["antirrebote_s"]),
        segundos_perdida=float(deteccion["segundos_perdida"]),
        segundos_perdida_peligro=float(deteccion["segundos_perdida_peligro"]),
        radio_reasociacion_m=float(deteccion["radio_reasociacion_m"]),
        radio_reasociacion_px=float(deteccion["radio_reasociacion_px"]),
    )
