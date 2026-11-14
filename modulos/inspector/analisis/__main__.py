"""Analiza una foto o una carpeta de fotos desde la consola.

    python -m modulos.inspector.analisis foto.jpg
    python -m modulos.inspector.analisis modulos/inspector/escenas --esfuerzo low --sin-cache
    python -m modulos.inspector.analisis foto.jpg --lado 2576 --modelo claude-opus-5-5

Sirve para ajustar el prompt y medir tiempo y costo sin levantar el servicio. Cada foto
pasa por lo mismo que en el stand: se orienta, se difuminan los rostros, se reduce y se
envía. Deja la foto anotada y el análisis en CARPETA_COLA/inspector/analisis/<foto>/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..configuracion import ESFUERZOS, Ajustes, carpeta_de_datos
from ..nucleo.esquema import CATEGORIAS
from ..nucleo.imagen import ImagenInvalida, anotar, guardar_jpeg, preparar_foto, tokens_de_imagen
from .cache import CacheDeAnalisis, hash_de_foto
from .cliente import Analizador, ErrorDeAnalisis, ResultadoAnalisis
from .costos import NOMBRE_CSV, RegistroDeCostos

EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp"}


def fotos_en(rutas: list[str]) -> list[Path]:
    """Las fotos de los archivos y carpetas indicados (las carpetas se recorren enteras)."""
    fotos: list[Path] = []
    for texto in rutas:
        ruta = Path(texto)
        if ruta.is_dir():
            fotos += sorted(archivo for archivo in ruta.rglob("*") if archivo.suffix.lower() in EXTENSIONES)
        elif ruta.is_file():
            fotos.append(ruta)
        else:
            print(f"No existe: {ruta}")
    return fotos


def nombre_de(foto: Path) -> str:
    """Nombre para la carpeta de salida: el de la foto o, si se llama 'foto', el de su carpeta."""
    return foto.parent.name if foto.stem.lower() == "foto" else foto.stem


def texto_del_resultado(resultado: ResultadoAnalisis) -> str:
    """El análisis en renglones, para la consola."""
    analisis = resultado.analisis
    costo = "sin precio" if resultado.costo_usd is None else f"{resultado.costo_usd:.4f} USD"
    renglones = [
        f"  {resultado.modelo} · esfuerzo {resultado.esfuerzo} · {resultado.ancho}x{resultado.alto} px "
        f"({tokens_de_imagen(resultado.ancho, resultado.alto)} tokens de imagen) · origen: {resultado.origen}",
        f"  {resultado.duracion_s} s · {resultado.tokens_entrada} tokens de entrada, "
        f"{resultado.tokens_salida} de salida · {costo} · intentos: {resultado.intentos}",
        f"  Escena: {analisis['descripcion_general']}",
    ]
    if analisis["advertencias"]:
        renglones.append("  Advertencias: " + "; ".join(analisis["advertencias"]))
    for peligro in analisis["peligros"]:
        clasificacion = peligro["clasificacion"]
        renglones += [
            f"  {peligro['n']}. [{peligro['confianza']}] {peligro['descripcion']}",
            f"     {CATEGORIAS[clasificacion['categoria']]} – {clasificacion['subcategoria']} · "
            f"deficiencia {peligro['nivel_deficiencia_propuesto']} · consecuencia {peligro['consecuencia_propuesta']}",
            f"     Evidencia: {peligro['evidencia_visible']}",
        ]
    if not analisis["peligros"]:
        renglones.append("  (sin peligros visibles)")
    return "\n".join(renglones)


def main(argumentos: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    base = Ajustes.desde_entorno()
    lector = argparse.ArgumentParser(prog="python -m modulos.inspector.analisis", description=__doc__.split("\n")[0])
    lector.add_argument("rutas", nargs="+", help="fotos o carpetas con fotos")
    lector.add_argument("--modelo", default=base.modelo)
    lector.add_argument("--esfuerzo", default=base.esfuerzo, choices=ESFUERZOS)
    lector.add_argument("--lado", type=int, default=base.lado_max, help="lado largo máximo en px (2576 = alta resolución)")
    lector.add_argument("--max-peligros", type=int, default=base.max_peligros)
    lector.add_argument("--tiempo", type=float, default=base.tiempo_maximo_s, help="tiempo máximo en segundos")
    lector.add_argument("--sin-cache", action="store_true", help="analiza de nuevo aunque la foto ya esté en la caché")
    lector.add_argument("--salida", type=Path, default=None, help="carpeta para las fotos anotadas y los análisis")
    opciones = lector.parse_args(argumentos)

    try:
        ajustes = base.con(modelo=opciones.modelo, esfuerzo=opciones.esfuerzo, lado_max=opciones.lado,
                           max_peligros=opciones.max_peligros, tiempo_maximo_s=opciones.tiempo)
    except ValueError as error:
        print(f"Ajustes no válidos: {error}")
        return 2
    datos = carpeta_de_datos()
    salida = opciones.salida or datos / "analisis"
    analizador = Analizador(ajustes, cache=CacheDeAnalisis(datos / "cache"),
                            registro=RegistroDeCostos(datos / NOMBRE_CSV))

    fallos = 0
    for foto in fotos_en(opciones.rutas):
        print(f"\n{foto}")
        try:
            original = foto.read_bytes()
            frame = preparar_foto(original, ajustes.lado_max)  # orientada, difuminada y reducida
            resultado = analizador.analizar(frame, hash_foto=hash_de_foto(original),
                                            usar_cache=not opciones.sin_cache)
        except ImagenInvalida as error:
            print(f"  {error}")
            fallos += 1
            continue
        except ErrorDeAnalisis as error:
            print(f"  {error.mensaje}\n  ({error.codigo}: {error.detalle})")
            fallos += 1
            continue
        print(texto_del_resultado(resultado))
        carpeta = salida / nombre_de(foto)
        guardar_jpeg(anotar(frame, resultado.analisis["peligros"]), carpeta / "anotada.jpg")
        (carpeta / "analisis.json").write_text(
            json.dumps({"analisis": resultado.analisis, "modelo": resultado.modelo, "esfuerzo": resultado.esfuerzo,
                        "ancho": resultado.ancho, "alto": resultado.alto, "origen": resultado.origen,
                        "duracion_s": resultado.duracion_s, "tokens_entrada": resultado.tokens_entrada,
                        "tokens_salida": resultado.tokens_salida, "costo_usd": resultado.costo_usd},
                       ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"  Guardado en {carpeta}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
