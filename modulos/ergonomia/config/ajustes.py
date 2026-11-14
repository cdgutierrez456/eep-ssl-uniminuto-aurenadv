"""Configuración del módulo de ergonomía.

Dos niveles:

- **Local (.env)**: lo que depende del equipo y no cambia durante la demo: cámara, pantalla,
  dispositivo de cómputo. Se lee una vez al arrancar (``AjustesLocales.desde_entorno``).
- **Operativa (remota)**: lo que el operador ajusta en vivo desde la plataforma: peso de la
  carga, agarre, condiciones de actividad, modo de detección, lado y cámara. Su valor por
  defecto está en ``por_defecto.json`` y su forma en ``contrato/config_ergonomia.schema.json``.
  ``validar_config`` es el validador que se le pasa a ``modulos.comun.obtener_config``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modulos.comun.camara_stand import ConfigCamara

from ..nucleo.levantamiento import Umbrales
from ..nucleo.reba import Condiciones

RUTA_POR_DEFECTO = Path(__file__).with_name("por_defecto.json")

AGARRES = ("bueno", "regular", "malo", "inaceptable")
MODOS_DETECCION = ("auto", "manual")
LADOS = ("auto", "izquierdo", "derecho")
CONDICIONES_ACTIVIDAD = ("estatica", "repetitiva", "cambios_rapidos")

# Lo que el módulo le cuenta a la plataforma para que pinte los controles
CAPACIDADES = {
    "agarres": list(AGARRES),
    "modos_deteccion": list(MODOS_DETECCION),
    "lados": list(LADOS),
    "condiciones_actividad": [
        {"id": "estatica", "nombre": "Parte del cuerpo estática más de 1 minuto"},
        {"id": "repetitiva", "nombre": "Acciones repetidas más de 4 veces por minuto"},
        {"id": "cambios_rapidos", "nombre": "Cambios posturales rápidos o base inestable"},
    ],
    "peso_carga_kg": {"minimo": 0, "maximo": 50},
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
    espejo: bool = False  # en vista lateral no hace falta; invierte izquierda y derecha
    dispositivo: str = "cpu"
    ancho_pantalla: int = 1920
    alto_pantalla: int = 1080
    umbral_visibilidad: float = 0.5
    segundos_resultado: float = 8.0  # cuánto se deja en pantalla el resultado de un intento
    segundos_nueva_visita: float = 20.0  # sin nadie en cuadro este tiempo, empieza otra visita

    @classmethod
    def desde_entorno(cls) -> "AjustesLocales":
        def numero(nombre: str, por_defecto, tipo=int):
            try:
                return tipo(os.getenv(nombre, "").strip() or por_defecto)
            except ValueError:
                return por_defecto

        return cls(
            camara=ConfigCamara.desde_entorno("ERGONOMIA"),
            pantalla_completa=_booleano(os.getenv("ERGONOMIA_PANTALLA_COMPLETA"), True),
            espejo=_booleano(os.getenv("ERGONOMIA_ESPEJO"), False),
            dispositivo=(os.getenv("ERGONOMIA_DISPOSITIVO") or "cpu").strip().lower(),
            ancho_pantalla=numero("ERGONOMIA_PANTALLA_ANCHO", 1920),
            alto_pantalla=numero("ERGONOMIA_PANTALLA_ALTO", 1080),
            umbral_visibilidad=numero("ERGONOMIA_UMBRAL_VISIBILIDAD", 0.5, float),
            segundos_resultado=numero("ERGONOMIA_SEGUNDOS_RESULTADO", 8.0, float),
            segundos_nueva_visita=numero("ERGONOMIA_SEGUNDOS_NUEVA_VISITA", 20.0, float),
        )


def _por_defecto() -> dict[str, Any]:
    return json.loads(RUTA_POR_DEFECTO.read_text(encoding="utf-8"))


def _es_numero(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def validar_config(candidata: Any) -> dict[str, Any]:
    """Valida y normaliza la configuración operativa. Lanza ``ValueError`` si no sirve.

    Las claves que falten toman su valor por defecto y las desconocidas se descartan, así
    que lo que el módulo aplica puede diferir de lo que la plataforma guardó.
    """
    if not isinstance(candidata, dict):
        raise ValueError("la configuración debe ser un objeto")
    config = _por_defecto()
    datos = {clave: valor for clave, valor in candidata.items() if clave in config}

    def exigir(condicion: bool, mensaje: str) -> None:
        if not condicion:
            raise ValueError(mensaje)

    if "peso_carga_kg" in datos:
        exigir(_es_numero(datos["peso_carga_kg"]) and 0 <= datos["peso_carga_kg"] <= 200,
               "peso_carga_kg debe ser un número entre 0 y 200")
    if "agarre" in datos:
        exigir(datos["agarre"] in AGARRES, f"agarre debe ser uno de {', '.join(AGARRES)}")
    if "modo_deteccion" in datos:
        exigir(datos["modo_deteccion"] in MODOS_DETECCION,
               f"modo_deteccion debe ser uno de {', '.join(MODOS_DETECCION)}")
    if "lado" in datos:
        exigir(datos["lado"] in LADOS, f"lado debe ser uno de {', '.join(LADOS)}")
    for clave in ("golpe_o_fuerza_brusca", "ajuste_brazo_inclinada", "postura_neutra"):
        if clave in datos:
            exigir(isinstance(datos[clave], bool), f"{clave} debe ser verdadero o falso")
    for clave, maximo in (("umbral_tronco_inclinado", 90), ("tolerancia_brazo_vertical", 90)):
        if clave in datos:
            exigir(_es_numero(datos[clave]) and 0 <= datos[clave] <= maximo,
                   f"{clave} debe ser un número entre 0 y {maximo}")
    if "camara" in datos:
        camara = datos["camara"]
        exigir(camara is None or (isinstance(camara, int) and not isinstance(camara, bool) and camara >= 0)
               or (isinstance(camara, str) and camara.strip() != ""),
               "camara debe ser un índice, un nombre o null")
    if "actividad" in datos:
        actividad = datos["actividad"]
        exigir(isinstance(actividad, dict), "actividad debe ser un objeto")
        for clave, valor in actividad.items():
            if clave in CONDICIONES_ACTIVIDAD:
                exigir(isinstance(valor, bool), f"actividad.{clave} debe ser verdadero o falso")
        datos["actividad"] = {**config["actividad"],
                              **{c: v for c, v in actividad.items() if c in CONDICIONES_ACTIVIDAD}}
    if "deteccion" in datos:
        deteccion = datos["deteccion"]
        exigir(isinstance(deteccion, dict), "deteccion debe ser un objeto")
        for clave, valor in deteccion.items():
            if clave in config["deteccion"]:
                exigir(_es_numero(valor) and 0 <= valor <= 180, f"deteccion.{clave} debe ser un número entre 0 y 180")
        datos["deteccion"] = {**config["deteccion"],
                              **{c: v for c, v in deteccion.items() if c in config["deteccion"]}}
    config.update(datos)
    return config


def umbrales_desde(config: dict[str, Any]) -> Umbrales:
    """Umbrales de detección del levantamiento a partir de la configuración operativa (ya validada)."""
    return Umbrales(**{clave: float(valor) for clave, valor in config["deteccion"].items()})


def condiciones_desde(config: dict[str, Any]) -> Condiciones:
    """Convierte la configuración operativa (ya validada) en las condiciones del cálculo REBA."""
    actividad = config["actividad"]
    return Condiciones(
        peso_carga_kg=float(config["peso_carga_kg"]),
        golpe_o_fuerza_brusca=config["golpe_o_fuerza_brusca"],
        agarre=config["agarre"],
        actividad_estatica=actividad["estatica"],
        actividad_repetitiva=actividad["repetitiva"],
        actividad_cambios_rapidos=actividad["cambios_rapidos"],
        ajuste_brazo_inclinada=config["ajuste_brazo_inclinada"],
        umbral_tronco_inclinado=float(config["umbral_tronco_inclinado"]),
        tolerancia_brazo_vertical=float(config["tolerancia_brazo_vertical"]),
    )
