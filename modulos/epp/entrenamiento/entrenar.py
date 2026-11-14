"""Entrena el detector de EPP de un perfil con Ultralytics YOLO26.

Uso::

    python -m modulos.epp.entrenamiento.entrenar --nombre industria_n --epocas 60
    python -m modulos.epp.entrenamiento.entrenar --nombre industria_n --publicar epp-industria-v1

Requiere PyTorch con CUDA (ver README del módulo). El dataset sale de
``python -m modulos.epp.datos.preparar_dataset``. Los resultados quedan en runs/epp/<nombre>/
y, con --publicar, los mejores pesos se copian a modulos/epp/modelos/<version>.pt.
Ni runs/ ni los pesos se versionan en git.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
DIR_MODELOS = RAIZ / "modulos" / "epp" / "modelos"
DIR_RUNS = RAIZ / "runs" / "epp"
DATA_POR_DEFECTO = RAIZ / "datasets" / "epp_industria" / "data.yaml"

# Aumentos moderados: gafas y casco son objetos pequeños. Sin volteo vertical: en el stand
# nadie aparece de cabeza, y la asociación por zonas depende de que "arriba" sea arriba.
AUMENTOS = dict(
    hsv_h=0.015, hsv_s=0.6, hsv_v=0.5, degrees=3.0, translate=0.1, scale=0.5,
    fliplr=0.5, flipud=0.0, mosaic=1.0, mixup=0.05, close_mosaic=10,
)


def main() -> None:
    analizador = argparse.ArgumentParser(description="Entrena el detector de EPP")
    analizador.add_argument("--nombre", default="industria_n", help="Nombre de la corrida en runs/epp/")
    analizador.add_argument("--modelo", default="yolo26n.pt", help="Pesos base (yolo26n.pt o yolo26s.pt)")
    analizador.add_argument("--data", default=str(DATA_POR_DEFECTO))
    analizador.add_argument("--epocas", type=int, default=60)
    analizador.add_argument("--paciencia", type=int, default=15, help="Épocas sin mejora antes de parar")
    analizador.add_argument("--imgsz", type=int, default=640)
    analizador.add_argument("--lote", type=float, default=0.6,
                            help="Tamaño de lote; una fracción (<1) usa esa parte de la VRAM")
    analizador.add_argument("--reanudar", action="store_true", help="Continúa una corrida interrumpida")
    analizador.add_argument("--publicar", metavar="VERSION",
                            help="Solo copia best.pt de la corrida a modelos/<VERSION>.pt (no entrena)")
    opciones = analizador.parse_args()

    mejores = DIR_RUNS / opciones.nombre / "weights" / "best.pt"
    if opciones.publicar:
        if not mejores.exists():
            sys.exit(f"No existe {mejores}: primero hay que entrenar la corrida '{opciones.nombre}'.")
        destino = DIR_MODELOS / f"{opciones.publicar}.pt"
        shutil.copy2(mejores, destino)
        print(f"Pesos publicados en {destino}")
        return

    import torch
    from ultralytics import YOLO

    if not torch.cuda.is_available():
        sys.exit("No hay GPU CUDA disponible. Instala PyTorch con CUDA (ver README) o entrena en Colab.")
    if not Path(opciones.data).exists():
        sys.exit(f"No existe {opciones.data}. Corre antes: python -m modulos.epp.datos.preparar_dataset")

    if opciones.reanudar:
        ultimo = DIR_RUNS / opciones.nombre / "weights" / "last.pt"
        YOLO(str(ultimo)).train(resume=True)
        return

    base = DIR_MODELOS / opciones.modelo
    modelo = YOLO(str(base) if base.exists() else opciones.modelo)
    lote = opciones.lote if opciones.lote < 1 else int(opciones.lote)
    modelo.train(
        data=opciones.data, epochs=opciones.epocas, patience=opciones.paciencia, imgsz=opciones.imgsz,
        batch=lote, workers=2, device=0, amp=True, cache=False, seed=20261113, plots=True,
        project=str(DIR_RUNS), name=opciones.nombre, exist_ok=True, **AUMENTOS,
    )
    print(f"\nEntrenamiento terminado. Mejores pesos: {mejores}")
    print("Siguiente paso: python -m modulos.epp.entrenamiento.evaluar --pesos", mejores)


if __name__ == "__main__":
    main()
