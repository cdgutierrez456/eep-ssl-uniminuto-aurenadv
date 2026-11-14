"""Registro de costos del inspector: una fila por llamada a la API, en el log y en un CSV.

    python -m modulos.inspector.analisis.costos

muestra el resumen: fotos analizadas, costo total, costo promedio por foto, duración
promedio y cuántos rechazos y errores hubo.
"""

from __future__ import annotations

import csv
import json
import logging
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from modulos.comun.eventos import ZONA_HORARIA

log = logging.getLogger(__name__)

RUTA_PRECIOS = Path(__file__).resolve().parents[1] / "config" / "precios.json"
NOMBRE_CSV = "costos.csv"

COLUMNAS = (
    "fecha", "analisis_id", "intento", "modelo", "esfuerzo", "ancho", "alto",
    "tokens_entrada", "tokens_salida", "costo_usd", "duracion_s", "resultado", "peligros", "detalle",
)

# Valores de la columna "resultado"
OK = "ok"                      # análisis válido
CACHE = "cache"                # la foto ya estaba analizada: no hubo llamada
RECHAZO = "rechazo"            # el modelo declinó analizar la foto
INVALIDO = "invalido"          # la salida no cumplió el esquema
ERROR = "error"                # sin conexión, tiempo agotado, límite o falla del servicio


@lru_cache(maxsize=4)
def _precios(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def costo_usd(modelo: str, tokens_entrada: int, tokens_salida: int, *, lectura_cache: int = 0,
              escritura_cache: int = 0, ruta_precios: Path | None = None) -> float | None:
    """Costo estimado de una llamada, en USD. ``None`` si el modelo no tiene precio en ``precios.json``."""
    precio = _precios(ruta_precios or RUTA_PRECIOS).get(modelo)
    if not isinstance(precio, dict):
        return None
    total = (tokens_entrada * precio["entrada"] + tokens_salida * precio["salida"]
             + lectura_cache * precio.get("lectura_cache", precio["entrada"])
             + escritura_cache * precio.get("escritura_cache", precio["entrada"]))
    return round(total / 1_000_000, 6)


class RegistroDeCostos:
    """CSV con una fila por llamada a la API (y por foto servida desde la caché)."""

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = Path(ruta)
        self._cerrojo = threading.Lock()

    def registrar(self, **fila: Any) -> dict:
        """Agrega una fila al CSV y la deja en el log. Devuelve la fila escrita.

        Un fallo al escribir no interrumpe el análisis: queda como advertencia en el log.
        """
        fila = {columna: fila.get(columna, "") for columna in COLUMNAS}
        fila["fecha"] = fila["fecha"] or datetime.now(ZONA_HORARIA).isoformat(timespec="seconds")
        for columna in COLUMNAS:
            if fila[columna] is None:
                fila[columna] = ""
        log.info(
            "Análisis %s intento %s: %s · %s · entrada %s, salida %s tokens · %s USD · %s s%s",
            fila["analisis_id"], fila["intento"], fila["resultado"], fila["modelo"], fila["tokens_entrada"],
            fila["tokens_salida"], fila["costo_usd"], fila["duracion_s"],
            f" · {fila['detalle']}" if fila["detalle"] else "",
        )
        try:
            with self._cerrojo:
                nuevo = not self.ruta.is_file()
                self.ruta.parent.mkdir(parents=True, exist_ok=True)
                with self.ruta.open("a", encoding="utf-8-sig" if nuevo else "utf-8", newline="") as archivo:
                    escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS)
                    if nuevo:
                        escritor.writeheader()
                    escritor.writerow(fila)
        except OSError as error:
            log.warning("No se pudo escribir el registro de costos (%s): %s", self.ruta, error)
        return fila

    def leer(self) -> list[dict]:
        """Todas las filas del CSV (lista vacía si aún no existe)."""
        if not self.ruta.is_file():
            return []
        with self.ruta.open(encoding="utf-8-sig", newline="") as archivo:
            return list(csv.DictReader(archivo))


def _numero(valor: Any) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def resumir(filas: Iterable[dict]) -> dict:
    """Resumen del registro. El costo de una foto incluye sus reintentos.

    ``fotos_analizadas`` cuenta los análisis que terminaron bien llamando a la API (los
    servidos desde la caché no cuestan y van aparte). ``costo_promedio_por_foto`` es el
    costo total de las llamadas (incluidos rechazos y reintentos) entre esas fotos.
    """
    filas = list(filas)
    llamadas = [fila for fila in filas if fila.get("resultado") != CACHE]
    analizadas = {fila.get("analisis_id") for fila in llamadas if fila.get("resultado") == OK}
    costo_total = sum(_numero(fila.get("costo_usd")) for fila in llamadas)
    duraciones = [_numero(fila.get("duracion_s")) for fila in llamadas if fila.get("resultado") == OK]
    por_modelo: dict[str, dict] = {}
    for fila in llamadas:
        modelo = por_modelo.setdefault(fila.get("modelo") or "?", {"fotos": set(), "costo_usd": 0.0})
        modelo["costo_usd"] += _numero(fila.get("costo_usd"))
        if fila.get("resultado") == OK:
            modelo["fotos"].add(fila.get("analisis_id"))
    return {
        "fotos_analizadas": len(analizadas),
        "llamadas": len(llamadas),
        "desde_cache": sum(1 for fila in filas if fila.get("resultado") == CACHE),
        "rechazos": sum(1 for fila in llamadas if fila.get("resultado") == RECHAZO),
        "invalidos": sum(1 for fila in llamadas if fila.get("resultado") == INVALIDO),
        "errores": sum(1 for fila in llamadas if fila.get("resultado") == ERROR),
        "costo_total_usd": round(costo_total, 4),
        "costo_promedio_por_foto_usd": round(costo_total / len(analizadas), 4) if analizadas else None,
        "duracion_promedio_s": round(sum(duraciones) / len(duraciones), 1) if duraciones else None,
        "tokens_entrada": int(sum(_numero(fila.get("tokens_entrada")) for fila in llamadas)),
        "tokens_salida": int(sum(_numero(fila.get("tokens_salida")) for fila in llamadas)),
        "por_modelo": {
            nombre: {
                "fotos": len(datos["fotos"]),
                "costo_usd": round(datos["costo_usd"], 4),
                "costo_promedio_por_foto_usd": round(datos["costo_usd"] / len(datos["fotos"]), 4)
                if datos["fotos"] else None,
            }
            for nombre, datos in por_modelo.items()
        },
    }


def texto_del_resumen(resumen: dict) -> str:
    """El resumen en renglones, para la consola."""
    promedio = resumen["costo_promedio_por_foto_usd"]
    duracion = resumen["duracion_promedio_s"]
    renglones = [
        f"Fotos analizadas con la API: {resumen['fotos_analizadas']} ({resumen['llamadas']} llamadas)",
        f"Servidas desde la caché: {resumen['desde_cache']}",
        f"Rechazos: {resumen['rechazos']} · salidas inválidas: {resumen['invalidos']} · errores: {resumen['errores']}",
        f"Tokens: {resumen['tokens_entrada']} de entrada, {resumen['tokens_salida']} de salida",
        f"Costo total: {resumen['costo_total_usd']:.4f} USD",
        "Costo promedio por foto: " + (f"{promedio:.4f} USD" if promedio is not None else "sin datos"),
        "Duración promedio: " + (f"{duracion} s" if duracion is not None else "sin datos"),
    ]
    for modelo, datos in resumen["por_modelo"].items():
        por_foto = datos["costo_promedio_por_foto_usd"]
        renglones.append(f"  {modelo}: {datos['fotos']} fotos, {datos['costo_usd']:.4f} USD"
                         + (f" ({por_foto:.4f} USD por foto)" if por_foto is not None else ""))
    return "\n".join(renglones)


if __name__ == "__main__":
    from modulos.inspector.configuracion import carpeta_de_datos

    registro = RegistroDeCostos(carpeta_de_datos() / NOMBRE_CSV)
    print(f"Registro: {registro.ruta.resolve()}")
    print(texto_del_resumen(resumir(registro.leer())))
