"""Arma el dataset v2 de industria: el v1 más gafas pequeñas y fotos propias.

El modelo v1 casi solo vio gafas en primer plano (mediana: 14 % del ancho de la imagen) y
en el stand, a 1-2 m, miden cerca del 5 %. Este script añade al conjunto de entrenamiento:

1. Gafas pequeñas sintéticas: copias reducidas (2 a 4 veces, sobre fondo gris) de las fotos
   de entrenamiento con gafas grandes. Las etiquetas se reducen con la imagen.
2. Fotos propias de ``datasets/fotos_propias/entrenar/`` (ver capturar.py), repetidas
   ``--repetir-propias`` veces para que pesen frente a las ~10.000 públicas, más una
   copia reducida de cada una.

Las sesiones de ``datasets/fotos_propias/evaluar/`` no entran al entrenamiento: quedan como
conjunto aparte (``data_propias.yaml``) para medir si el modelo mejoró en el stand.
Validación y prueba del v1 no se tocan, así las métricas son comparables.

Uso::

    python -m modulos.epp.datos.ampliar_dataset
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

RAIZ = Path(__file__).resolve().parents[3]
ORIGEN = RAIZ / "datasets" / "epp_industria"
DESTINO = RAIZ / "datasets" / "epp_industria_v2"
DIR_PROPIAS = RAIZ / "datasets" / "fotos_propias"
SEMILLA = 20261113
ANCHO_GAFAS_GRANDES = 0.10       # solo se reducen fotos cuyas gafas ocupan al menos esto
REDUCCION = (0.25, 0.5)          # la copia mide entre un cuarto y la mitad del original
GRIS = 114                       # el mismo gris de relleno que usa Ultralytics


def enlazar(origen: Path, destino: Path) -> None:
    """Enlace duro (no ocupa disco); si no se puede, copia."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        destino.unlink()
    try:
        os.link(origen, destino)
    except OSError:
        shutil.copy2(origen, destino)


def leer_etiquetas(ruta: Path) -> list[tuple[int, float, float, float, float]]:
    if not ruta.exists():
        return []
    filas = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        partes = linea.split()
        if len(partes) >= 5:
            filas.append((int(partes[0]), *map(float, partes[1:5])))
    return filas


def escribir_etiquetas(ruta: Path, filas) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("".join(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n" for c, cx, cy, w, h in filas), encoding="utf-8")


def copiar_v1() -> dict[str, int]:
    conteo = {}
    for parte in ("train", "valid", "test"):
        imagenes = sorted((ORIGEN / "images" / parte).iterdir())
        for imagen in imagenes:
            enlazar(imagen, DESTINO / "images" / parte / imagen.name)
            etiqueta = ORIGEN / "labels" / parte / (imagen.stem + ".txt")
            if etiqueta.exists():
                enlazar(etiqueta, DESTINO / "labels" / parte / etiqueta.name)
        conteo[parte] = len(imagenes)
    return conteo


def reducir(imagen: Path, filas, nombre: str, azar: random.Random) -> bool:
    """Escribe en train una copia reducida de la imagen sobre fondo gris, con sus etiquetas."""
    original = cv2.imdecode(np.fromfile(str(imagen), np.uint8), cv2.IMREAD_COLOR)
    if original is None:
        return False
    alto, ancho = original.shape[:2]
    factor = azar.uniform(*REDUCCION)
    nuevo_ancho, nuevo_alto = max(8, int(ancho * factor)), max(8, int(alto * factor))
    reducida = cv2.resize(original, (nuevo_ancho, nuevo_alto), interpolation=cv2.INTER_AREA)
    x0, y0 = azar.randint(0, ancho - nuevo_ancho), azar.randint(0, alto - nuevo_alto)
    lienzo = np.full_like(original, GRIS)
    lienzo[y0:y0 + nuevo_alto, x0:x0 + nuevo_ancho] = reducida
    fx, fy = nuevo_ancho / ancho, nuevo_alto / alto
    nuevas = [(c, x0 / ancho + cx * fx, y0 / alto + cy * fy, w * fx, h * fy) for c, cx, cy, w, h in filas]
    (DESTINO / "images" / "train").mkdir(parents=True, exist_ok=True)
    cv2.imencode(".jpg", lienzo, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(str(DESTINO / "images" / "train" / f"{nombre}.jpg"))
    escribir_etiquetas(DESTINO / "labels" / "train" / f"{nombre}.txt", nuevas)
    return True


def gafas_pequenas(indice_gafas: int, azar: random.Random) -> int:
    """Crea las copias reducidas de las fotos de train con gafas grandes."""
    creadas = 0
    for imagen in sorted((ORIGEN / "images" / "train").iterdir()):
        filas = leer_etiquetas(ORIGEN / "labels" / "train" / (imagen.stem + ".txt"))
        if any(c == indice_gafas and w >= ANCHO_GAFAS_GRANDES for c, _, _, w, _ in filas):
            creadas += reducir(imagen, filas, f"peq_{imagen.stem}", azar)
    return creadas


def sumar_propias(uso: str, parte: str, nombres_v1: list[str], repetir: int,
                  azar: random.Random | None = None) -> tuple[int, dict[str, int]]:
    """Enlaza las sesiones propias de ``uso`` en la partición ``parte``, con las clases del v1.

    Con ``azar`` añade además una copia reducida de cada foto: las capturas suelen hacerse
    cerca de la cámara y en el stand el visitante está a 1-2 m.
    """
    fotos, por_clase = 0, {}
    for sesion in sorted((DIR_PROPIAS / uso).glob("*/")) if (DIR_PROPIAS / uso).is_dir() else []:
        clases = [n.strip() for n in (sesion / "classes.txt").read_text(encoding="utf-8").splitlines() if n.strip()]
        for imagen in sorted((sesion / "images").iterdir()):
            filas = [
                (nombres_v1.index(clases[c]), cx, cy, w, h)
                for c, cx, cy, w, h in leer_etiquetas(sesion / "labels" / (imagen.stem + ".txt"))
                if clases[c] in nombres_v1
            ]
            for copia in range(repetir):
                nombre = f"propia_{imagen.stem}" + (f"_r{copia}" if copia else "")
                enlazar(imagen, DESTINO / "images" / parte / f"{nombre}{imagen.suffix}")
                escribir_etiquetas(DESTINO / "labels" / parte / f"{nombre}.txt", filas)
            if azar is not None:
                reducir(imagen, filas, f"peq_propia_{imagen.stem}", azar)
            fotos += 1
            for c, *_ in filas:
                por_clase[nombres_v1[c]] = por_clase.get(nombres_v1[c], 0) + 1
    return fotos, por_clase


def main() -> None:
    analizador = argparse.ArgumentParser(description="Arma el dataset v2 de industria")
    analizador.add_argument("--repetir-propias", type=int, default=3,
                            help="Veces que cada foto propia entra al entrenamiento")
    opciones = analizador.parse_args()
    if not (ORIGEN / "data.yaml").exists():
        sys.exit(f"No existe {ORIGEN}. Corre antes: python -m modulos.epp.datos.preparar_dataset")

    nombres = yaml.safe_load((ORIGEN / "data.yaml").read_text(encoding="utf-8"))["names"]
    nombres_v1 = [nombres[i] for i in sorted(nombres)]
    if DESTINO.exists():
        shutil.rmtree(DESTINO)

    conteo = copiar_v1()
    azar = random.Random(SEMILLA)
    pequenas = gafas_pequenas(nombres_v1.index("gafas"), azar)
    propias, clases_propias = sumar_propias("entrenar", "train", nombres_v1, max(1, opciones.repetir_propias), azar)
    de_evaluar, clases_evaluar = sumar_propias("evaluar", "propias", nombres_v1, 1)

    base = {"path": DESTINO.as_posix(), "names": {i: n for i, n in enumerate(nombres_v1)}}
    (DESTINO / "data.yaml").write_text(yaml.safe_dump(
        {**base, "train": "images/train", "val": "images/valid", "test": "images/test"},
        allow_unicode=True, sort_keys=False), encoding="utf-8")
    if de_evaluar:
        (DESTINO / "data_propias.yaml").write_text(yaml.safe_dump(
            {**base, "train": "images/train", "val": "images/propias"}, allow_unicode=True, sort_keys=False),
            encoding="utf-8")

    print(f"Dataset v2 en {DESTINO}")
    print(f"  v1: train {conteo['train']}, valid {conteo['valid']}, test {conteo['test']}")
    print(f"  + {pequenas} copias con gafas pequeñas (train)")
    print(f"  + {propias} fotos propias x{opciones.repetir_propias} y una copia reducida de cada una (train): "
          f"{clases_propias or 'ninguna'}")
    print(f"  + {de_evaluar} fotos propias para evaluar (aparte): {clases_evaluar or 'ninguna'}")
    if not propias:
        print("  Aviso: no hay fotos propias de entrenamiento. Captúralas con python -m modulos.epp.datos.capturar")
    if not de_evaluar:
        print("  Aviso: sin sesiones '--para evaluar' no se puede medir la mejora en el stand.")
    print("Siguiente paso: python -m modulos.epp.entrenamiento.entrenar --nombre industria_v2 "
          f"--modelo epp-industria-v1.pt --data {(DESTINO / 'data.yaml').as_posix()} --epocas 30")


if __name__ == "__main__":
    main()
