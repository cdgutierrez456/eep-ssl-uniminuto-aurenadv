"""Descarga los modelos públicos (preentrenados) que usan los módulos, si no están en disco.

    python -m herramientas.descargar_modelos             # baja los que falten
    python -m herramientas.descargar_modelos --listar    # solo dice cuáles hay y cuáles faltan
    python -m herramientas.descargar_modelos --forzar    # los vuelve a bajar aunque estén

Los pesos que entrenamos nosotros (los de EPP) se versionan en git porque son únicos. Los
públicos no: se pueden volver a bajar, así que quedan fuera de git (``*.pt`` está en
``.gitignore``) y esta herramienta los trae. Hay que correrla una vez, con internet, en cada
equipo; después los módulos funcionan sin red.

Cada descarga se comprueba contra el tamaño y la huella SHA-256 anotados aquí: un archivo
cortado o distinto del esperado no se deja en disco.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

RAIZ_REPO = Path(__file__).resolve().parents[1]
TIEMPO_LIMITE_S = 30.0


@dataclass(frozen=True)
class ModeloPublico:
    """Un modelo que se baja de internet en lugar de versionarse."""

    nombre: str
    destino: Path  # dónde lo busca el módulo que lo usa
    url: str
    uso: str  # quién lo usa y para qué
    tamano: int | None = None  # bytes esperados
    sha256: str | None = None  # huella esperada (hexadecimal)


MODELOS: tuple[ModeloPublico, ...] = (
    ModeloPublico(
        nombre="yolo26n-pose.pt",
        destino=RAIZ_REPO / "modulos" / "zona" / "modelos" / "yolo26n-pose.pt",
        url="https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n-pose.pt",
        uso="Módulo de zona: pose de personas (YOLO26 nano de Ultralytics, preentrenado en COCO)",
        tamano=7_878_574,
        sha256="eb3bb8268828aeaf515cec23a4bfafd793944a86fe9af94ba7823609c14522a9",
    ),
)


class ErrorDeDescarga(RuntimeError):
    """El modelo no se pudo bajar o lo que llegó no es lo esperado. El mensaje dice qué pasó."""


def huella(ruta: Path) -> str:
    """SHA-256 del archivo, en hexadecimal."""
    resumen = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def problema_de(ruta: Path, modelo: ModeloPublico) -> str | None:
    """Por qué el archivo no sirve como ese modelo, o None si está bien."""
    if not ruta.is_file():
        return "no está en disco"
    tamano = ruta.stat().st_size
    if modelo.tamano is not None and tamano != modelo.tamano:
        return f"pesa {tamano} bytes y se esperaban {modelo.tamano}"
    if modelo.sha256 is not None and huella(ruta) != modelo.sha256.lower():
        return "su huella SHA-256 no es la esperada"
    return None


def descargar(modelo: ModeloPublico, forzar: bool = False, informar: Callable[[str], None] = print) -> bool:
    """Baja el modelo si falta (o si ``forzar``). Devuelve True si lo descargó, False si ya estaba.

    Lanza ``ErrorDeDescarga`` si no se pudo bajar o si lo que llegó no coincide con lo esperado;
    en ese caso no queda ningún archivo a medias en el destino.
    """
    problema = problema_de(modelo.destino, modelo)
    if problema is None and not forzar:
        informar(f"  {modelo.nombre}: ya está en {_relativa(modelo.destino)}")
        return False
    if problema is not None and modelo.destino.is_file():
        informar(f"  {modelo.nombre}: el archivo que hay {problema}; se vuelve a bajar")

    modelo.destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = modelo.destino.with_name(modelo.destino.name + ".parcial")
    informar(f"  {modelo.nombre}: bajando de {modelo.url}")
    try:
        with httpx.stream("GET", modelo.url, follow_redirects=True, timeout=TIEMPO_LIMITE_S) as respuesta:
            respuesta.raise_for_status()
            with open(parcial, "wb") as archivo:
                for bloque in respuesta.iter_bytes(1 << 16):
                    archivo.write(bloque)
        problema = problema_de(parcial, modelo)
        if problema is not None:
            raise ErrorDeDescarga(f"{modelo.nombre}: lo descargado {problema}")
        parcial.replace(modelo.destino)
    except httpx.HTTPError as error:
        raise ErrorDeDescarga(f"{modelo.nombre}: no se pudo bajar ({type(error).__name__}: {error})") from None
    finally:
        parcial.unlink(missing_ok=True)
    megas = modelo.destino.stat().st_size / 1e6
    informar(f"  {modelo.nombre}: listo en {_relativa(modelo.destino)} ({megas:.1f} MB, SHA-256 {huella(modelo.destino)})")
    return True


def _relativa(ruta: Path) -> str:
    try:
        return ruta.relative_to(RAIZ_REPO).as_posix()
    except ValueError:
        return ruta.as_posix()


def main(argumentos: list[str] | None = None, modelos: tuple[ModeloPublico, ...] = MODELOS) -> int:
    analizador = argparse.ArgumentParser(
        prog="python -m herramientas.descargar_modelos",
        description="Descarga los modelos públicos que usan los módulos, si no están en disco.",
    )
    analizador.add_argument("--listar", action="store_true", help="solo muestra cuáles hay y cuáles faltan")
    analizador.add_argument("--forzar", action="store_true", help="vuelve a bajar los que ya están")
    opciones = analizador.parse_args(argumentos)

    if opciones.listar:
        for modelo in modelos:
            estado = problema_de(modelo.destino, modelo)
            print(f"  {modelo.nombre}: {'presente' if estado is None else 'FALTA (' + estado + ')'}"
                  f" · {_relativa(modelo.destino)}\n    {modelo.uso}")
        return 0

    print("Modelos públicos de los módulos:")
    fallos = 0
    for modelo in modelos:
        try:
            descargar(modelo, forzar=opciones.forzar)
        except ErrorDeDescarga as error:
            fallos += 1
            print(f"  ERROR: {error}")
    if fallos:
        print(f"{fallos} modelo(s) no se pudieron bajar. Revisa la conexión a internet y vuelve a intentarlo.")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
