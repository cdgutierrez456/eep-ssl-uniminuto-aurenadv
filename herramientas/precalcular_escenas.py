"""Prepara las escenas del stand del inspector y precalcula su análisis.

    python -m herramientas.precalcular_escenas              analiza las escenas que aún no tienen resultado
    python -m herramientas.precalcular_escenas --forzar     vuelve a analizarlas todas
    python -m herramientas.precalcular_escenas --solo bodega_estanterias

Para agregar una escena basta con dejar su foto suelta en ``modulos/inspector/escenas/``
(por ejemplo ``bodega_stand.jpg``): la herramienta crea la carpeta ``bodega_stand/``, guarda
la foto con los rostros difuminados y borra el archivo suelto, porque en el repositorio no
puede quedar una foto sin difuminar. El nombre que ve la persona se edita en
``escena.json``. Necesita internet y la clave de la API; cada análisis cuesta unos
centavos de dólar y queda en el registro de costos.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from modulos.inspector.analisis import Analizador, CacheDeAnalisis, ErrorDeAnalisis, RegistroDeCostos, hash_de_foto
from modulos.inspector.analisis.costos import NOMBRE_CSV
from modulos.inspector.configuracion import ESFUERZOS, Ajustes, carpeta_de_datos
from modulos.inspector.nucleo.imagen import LADO_MAX_ALTA_RESOLUCION, ImagenInvalida, guardar_jpeg, preparar_foto
from modulos.inspector.preparadas import (
    CARPETA_ESCENAS,
    NOMBRE_ESCENA,
    NOMBRE_FOTO,
    guardar_resultado,
    id_valido,
    listar_escenas,
)

EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp"}


def id_desde_nombre(nombre: str) -> str:
    """'Bodega Stand 2.JPG' -> 'bodega_stand_2'."""
    return re.sub(r"[^a-z0-9]+", "_", nombre.lower()).strip("_")[:64]


def incorporar_fotos_sueltas(carpeta: Path) -> list[str]:
    """Convierte cada foto suelta de la carpeta en una escena con la foto difuminada. Devuelve los ids creados."""
    creadas = []
    for foto in sorted(ruta for ruta in carpeta.iterdir() if ruta.is_file() and ruta.suffix.lower() in EXTENSIONES):
        identificador = id_desde_nombre(foto.stem)
        if not id_valido(identificador) or (carpeta / identificador / NOMBRE_FOTO).exists():
            print(f"  {foto.name}: ya existe la escena '{identificador}' o el nombre no sirve; no se toca")
            continue
        try:
            frame = preparar_foto(foto.read_bytes(), LADO_MAX_ALTA_RESOLUCION)  # orientada y difuminada
        except ImagenInvalida as error:
            print(f"  {foto.name}: {error}")
            continue
        destino = carpeta / identificador
        guardar_jpeg(frame, destino / NOMBRE_FOTO, 88)
        (destino / NOMBRE_ESCENA).write_text(
            json.dumps({"id": identificador, "nombre": foto.stem.replace("_", " ").capitalize()},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        foto.unlink()  # la foto sin difuminar no se queda en el repositorio
        creadas.append(identificador)
        print(f"  {foto.name} -> {identificador}/ (foto difuminada; el archivo suelto se borró)")
    return creadas


def main(argumentos: list[str] | None = None, analizador: Analizador | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    base = Ajustes.desde_entorno()
    lector = argparse.ArgumentParser(prog="python -m herramientas.precalcular_escenas",
                                     description="Precalcula el análisis de las escenas preparadas del inspector.")
    lector.add_argument("--carpeta", type=Path, default=CARPETA_ESCENAS)
    lector.add_argument("--forzar", action="store_true", help="vuelve a analizar las que ya tienen resultado")
    lector.add_argument("--solo", action="append", default=[], metavar="ID", help="solo esta escena (se puede repetir)")
    lector.add_argument("--modelo", default=base.modelo)
    lector.add_argument("--esfuerzo", default=base.esfuerzo, choices=ESFUERZOS)
    opciones = lector.parse_args(argumentos)

    carpeta = opciones.carpeta
    if not carpeta.is_dir():
        print(f"No existe la carpeta de escenas: {carpeta}")
        return 2
    incorporar_fotos_sueltas(carpeta)

    ajustes = base.con(modelo=opciones.modelo, esfuerzo=opciones.esfuerzo)
    datos = carpeta_de_datos()
    analizador = analizador or Analizador(ajustes, cache=CacheDeAnalisis(datos / "cache"),
                                          registro=RegistroDeCostos(datos / NOMBRE_CSV))
    fallos = costo_total = analizadas = 0
    for escena in listar_escenas(carpeta):
        if opciones.solo and escena["id"] not in opciones.solo:
            continue
        if escena["resultado"] and not opciones.forzar:
            print(f"{escena['id']}: ya tiene resultado ({len(escena['resultado']['analisis']['peligros'])} peligros)")
            continue
        original = escena["ruta_foto"].read_bytes()
        try:
            frame = preparar_foto(original, ajustes.lado_max)
            resultado = analizador.analizar(frame, hash_foto=hash_de_foto(original), ajustes=ajustes,
                                            usar_cache=not opciones.forzar, analisis_id=f"escena-{escena['id']}")
        except (ImagenInvalida, ErrorDeAnalisis) as error:
            print(f"{escena['id']}: {error}")
            fallos += 1
            continue
        guardar_resultado(escena["id"], resultado.analisis, carpeta, modelo=resultado.modelo,
                          esfuerzo=resultado.esfuerzo, ancho=resultado.ancho, alto=resultado.alto)
        analizadas += 1
        costo_total += resultado.costo_usd or 0
        print(f"{escena['id']}: {len(resultado.analisis['peligros'])} peligros · {resultado.duracion_s} s · "
              f"{resultado.costo_usd or 0:.4f} USD · origen {resultado.origen}")
    print(f"\nEscenas analizadas: {analizadas} · costo: {costo_total:.4f} USD · fallos: {fallos}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
