"""Evalúa un detector de EPP: métricas por clase, matriz de confusión y primer plano.

Uso::

    python -m modulos.epp.entrenamiento.evaluar --pesos runs/epp/industria_n/weights/best.pt

Evalúa tres conjuntos: validación, prueba y «primer plano» (las imágenes de validación y
prueba donde la persona o el elemento se ven grandes, como en el stand a 1-2 m).
Escribe reporte_evaluacion.md junto a este archivo y las matrices de confusión en
runs/epp/evaluacion/<conjunto>/confusion_matrix.png.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
DIR_DATASET = RAIZ / "datasets" / "epp_industria"
DIR_SALIDA = RAIZ / "runs" / "epp" / "evaluacion"
RUTA_REPORTE = Path(__file__).with_name("reporte_evaluacion.md")

CONJUNTOS = [
    ("valid", "Validación", "data.yaml", "val"),
    ("test", "Prueba", "data.yaml", "test"),
    ("primer_plano", "Primer plano (valid + test)", "data_primer_plano.yaml", "val"),
]


def evaluar(modelo, archivo_data: str, split: str, nombre: str, imgsz: int) -> dict:
    """Corre la validación de Ultralytics y devuelve las métricas en un diccionario simple."""
    resultado = modelo.val(
        data=str(DIR_DATASET / archivo_data), split=split, imgsz=imgsz, device=0, workers=2,
        plots=True, project=str(DIR_SALIDA), name=nombre, exist_ok=True, verbose=False,
    )
    cajas = resultado.box
    por_clase = {}
    for posicion, indice in enumerate(cajas.ap_class_index):
        por_clase[resultado.names[int(indice)]] = {
            "precision": float(cajas.p[posicion]),
            "recall": float(cajas.r[posicion]),
            "mAP50": float(cajas.ap50[posicion]),
            "mAP50-95": float(cajas.ap[posicion]),
        }
    return {
        "mAP50": float(cajas.map50),
        "mAP50-95": float(cajas.map),
        "precision": float(cajas.mp),
        "recall": float(cajas.mr),
        "por_clase": por_clase,
        "matriz_confusion": str((DIR_SALIDA / nombre / "confusion_matrix.png").relative_to(RAIZ).as_posix()),
        "velocidad_ms": {k: round(float(v), 1) for k, v in resultado.speed.items()},
    }


def a_markdown(pesos: Path, resultados: dict[str, dict]) -> str:
    lineas = [
        "# Evaluación del detector de EPP industrial",
        "",
        f"Pesos: `{pesos.as_posix()}`. Generado por `python -m modulos.epp.entrenamiento.evaluar`.",
        "",
        "## Resumen",
        "",
        "| Conjunto | mAP50 | mAP50-95 | Precisión | Recall |",
        "|---|---|---|---|---|",
    ]
    for _, titulo, _, _ in CONJUNTOS:
        m = resultados[titulo]
        lineas.append(f"| {titulo} | {m['mAP50']:.3f} | {m['mAP50-95']:.3f} | {m['precision']:.3f} | {m['recall']:.3f} |")
    for _, titulo, _, _ in CONJUNTOS:
        m = resultados[titulo]
        lineas += ["", f"## {titulo}", "", "| Clase | Precisión | Recall | mAP50 | mAP50-95 |", "|---|---|---|---|---|"]
        for clase, v in m["por_clase"].items():
            lineas.append(f"| {clase} | {v['precision']:.3f} | {v['recall']:.3f} | {v['mAP50']:.3f} | {v['mAP50-95']:.3f} |")
        lineas += ["", f"Matriz de confusión: `{m['matriz_confusion']}`"]
    lineas.append("")
    return "\n".join(lineas)


def main() -> None:
    analizador = argparse.ArgumentParser(description="Evalúa el detector de EPP")
    analizador.add_argument("--pesos", required=True)
    analizador.add_argument("--imgsz", type=int, default=640)
    opciones = analizador.parse_args()

    pesos = Path(opciones.pesos).resolve()
    if not pesos.exists():
        sys.exit(f"No existen los pesos {pesos}")
    from ultralytics import YOLO

    modelo = YOLO(str(pesos))
    resultados = {
        titulo: evaluar(modelo, archivo, split, nombre, opciones.imgsz)
        for nombre, titulo, archivo, split in CONJUNTOS
    }
    try:
        pesos_relativos = pesos.relative_to(RAIZ)
    except ValueError:
        pesos_relativos = pesos
    texto = a_markdown(pesos_relativos, resultados)
    RUTA_REPORTE.write_text(texto, encoding="utf-8")
    (DIR_SALIDA / "evaluacion.json").write_text(json.dumps(resultados, indent=1, ensure_ascii=False), encoding="utf-8")
    print(texto)
    print(f"Reporte en {RUTA_REPORTE}")


if __name__ == "__main__":
    main()
