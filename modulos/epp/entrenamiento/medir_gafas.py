"""Mide la detección de gafas por tamaño del objeto, que es donde falla el modelo.

Las métricas globales esconden el problema: en el stand las gafas miden 3-6 % del ancho de
la imagen y casi todas las de los datasets son primeros planos. Este script da el recall
de gafas y de sin_gafas por tramo de tamaño, para uno o varios pesos::

    python -m modulos.epp.entrenamiento.medir_gafas --pesos modulos/epp/modelos/epp-industria-v1.pt
    python -m modulos.epp.entrenamiento.medir_gafas --pesos v1.pt v2.pt --partes propias

Un acierto es una detección de la clase correcta, sobre el umbral del perfil, cuyo centro
cae dentro de la caja anotada: lo mismo que le importa al motor de reglas.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

RAIZ = Path(__file__).resolve().parents[3]
TRAMOS = [(0, 0.03, "<3 %"), (0.03, 0.06, "3-6 %"), (0.06, 0.12, "6-12 %"), (0.12, 9, ">12 %")]
UMBRALES = {"gafas": 0.35, "sin_gafas": 0.65}   # los de config/perfiles.yaml


def tramo(ancho: float) -> str:
    return next(nombre for a, b, nombre in TRAMOS if a <= ancho < b)


def medir(pesos: Path, datos: Path, partes: list[str]) -> dict:
    from ultralytics import YOLO

    modelo = YOLO(str(pesos))
    indices = {nombre: i for i, nombre in modelo.names.items()}
    total = defaultdict(lambda: defaultdict(int))
    aciertos = defaultdict(lambda: defaultdict(int))
    contraria = defaultdict(lambda: defaultdict(int))
    for parte in partes:
        carpeta = datos / "images" / parte
        for imagen in sorted(carpeta.iterdir()) if carpeta.is_dir() else []:
            etiqueta = datos / "labels" / parte / (imagen.stem + ".txt")
            if not etiqueta.exists():
                continue
            anotadas = [linea.split() for linea in etiqueta.read_text(encoding="utf-8").splitlines()]
            anotadas = [(int(p[0]), *map(float, p[1:5])) for p in anotadas if len(p) >= 5]
            if not any(c in (indices["gafas"], indices["sin_gafas"]) for c, *_ in anotadas):
                continue
            frame = cv2.imdecode(np.fromfile(str(imagen), np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            cajas = modelo.predict(frame, conf=0.1, device=0, verbose=False)[0].boxes
            detecciones = list(zip(cajas.cls.tolist(), cajas.conf.tolist(), cajas.xywhn.tolist()))

            def hay(clase: str, cx, cy, w, h) -> bool:
                return any(
                    int(c) == indices[clase] and p >= UMBRALES[clase]
                    and abs(d[0] - cx) <= w / 2 and abs(d[1] - cy) <= h / 2
                    for c, p, d in detecciones
                )

            for c, cx, cy, w, h in anotadas:
                for clase, otra in (("gafas", "sin_gafas"), ("sin_gafas", "gafas")):
                    if c == indices[clase]:
                        t = tramo(w)
                        total[clase][t] += 1
                        aciertos[clase][t] += hay(clase, cx, cy, w, h)
                        contraria[clase][t] += hay(otra, cx, cy, w, h)
    return {"total": total, "aciertos": aciertos, "contraria": contraria}


def main() -> None:
    analizador = argparse.ArgumentParser(description="Recall de gafas por tamaño")
    analizador.add_argument("--pesos", nargs="+", required=True)
    analizador.add_argument("--datos", default=str(RAIZ / "datasets" / "epp_industria_v2"))
    analizador.add_argument("--partes", nargs="+", default=["valid", "test"],
                            help="Carpetas de images/ a medir: valid, test, propias")
    opciones = analizador.parse_args()

    resultados = {Path(p).stem: medir(Path(p), Path(opciones.datos), opciones.partes) for p in opciones.pesos}
    modelos = list(resultados)
    referencia = resultados[modelos[0]]["total"]
    print(f"\nConjunto: {', '.join(opciones.partes)} de {opciones.datos}")
    for clase, otra in (("gafas", "sin_gafas"), ("sin_gafas", "gafas")):
        print(f"\n### {clase} anotadas: recall, y entre paréntesis las veces que el modelo dijo {otra}")
        print("| Ancho en la imagen | Cantidad | " + " | ".join(modelos) + " |")
        print("|---|---|" + "---|" * len(modelos))
        for _, _, nombre in TRAMOS:
            n = referencia[clase][nombre]
            if not n:
                continue
            celdas = [
                f"{resultados[m]['aciertos'][clase][nombre] / n:.2f} ({resultados[m]['contraria'][clase][nombre] / n:.2f})"
                for m in modelos
            ]
            print(f"| {nombre} | {n} | " + " | ".join(celdas) + " |")


if __name__ == "__main__":
    main()
