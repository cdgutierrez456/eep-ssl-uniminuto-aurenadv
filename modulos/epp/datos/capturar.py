"""Captura fotos propias para el modelo de industria y las anota sola.

Te paras frente a la cámara del stand y dices qué llevas puesto; la herramienta guarda una
foto cada medio segundo con sus etiquetas en formato YOLO, sin anotar nada a mano::

    python -m modulos.epp.datos.capturar --gafas si --casco si
    python -m modulos.epp.datos.capturar --gafas no --casco si
    python -m modulos.epp.datos.capturar --gafas si --casco no --para evaluar

De dónde sale cada caja:
- gafas / sin_gafas: de los ojos que ubica el detector de rostros (la caja mide 3,1 veces
  la distancia entre ojos de ancho y 1,7 de alto: la mediana de las gafas anotadas en los
  datasets públicos).
- persona: del modelo COCO.
- casco y chaleco (si dices que los llevas): del modelo de industria actual, que en esas
  clases es fiable. sin_casco: la cabeza, estimada desde el rostro.
Una foto en la que no se ve tu rostro, o no aparece algo que dijiste llevar, no se guarda.

PRIVACIDAD: estas fotos se guardan SIN difuminar tu rostro (difuminarlo borraría las
gafas). Es la excepción de CLAUDE.md para fotos de entrenamiento: quedan en
datasets/fotos_propias/ (fuera de git) y no se suben a ningún lado. Solo se anota el
rostro más grande; cualquier otro rostro que salga se difumina antes de guardar.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from modulos.comun.camara_stand import ConfigCamara, conectar_camara
from modulos.comun.rostros import MARGEN, detectar_rostros_con_ojos

RAIZ = Path(__file__).resolve().parents[3]
DIR_FOTOS = RAIZ / "datasets" / "fotos_propias"
DIR_MODELOS = RAIZ / "modulos" / "epp" / "modelos"
CLASES = ["persona", "casco", "gafas", "chaleco", "proteccion_auditiva", "sin_casco", "sin_gafas"]

# Caja de gafas a partir de los ojos, en múltiplos de la distancia entre ojos
ANCHO_GAFAS, ALTO_GAFAS = 3.1, 1.7
CONFIANZA_ROSTRO = 0.7
VERDE, ROJO, MARFIL, NEGRO = (138, 195, 76), (77, 96, 229), (234, 241, 242), (20, 20, 17)


def caja_gafas(ojos) -> list[float]:
    """Caja [x1, y1, x2, y2] en píxeles centrada entre los ojos."""
    (ax, ay), (bx, by) = ojos
    d = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
    cx, cy = (ax + bx) / 2, (ay + by) / 2
    return [cx - ANCHO_GAFAS * d / 2, cy - ALTO_GAFAS * d / 2, cx + ANCHO_GAFAS * d / 2, cy + ALTO_GAFAS * d / 2]


def caja_cabeza(rostro) -> list[float]:
    """Cabeza sin casco estimada desde el rostro: algo más ancha y con el pelo."""
    x, y, w, h = rostro
    return [x - 0.2 * w, y - 0.45 * h, x + 1.2 * w, y + 1.05 * h]


def _detectar(modelo, frame, clases: set[str], confianza: float) -> list[tuple[str, list[float]]]:
    resultado = modelo.predict(frame, conf=confianza, verbose=False)[0].boxes
    return [
        (modelo.names[int(c)], caja) for c, caja in zip(resultado.cls.tolist(), resultado.xyxy.tolist())
        if modelo.names[int(c)] in clases
    ]


def anotar(frame: np.ndarray, coco, industria, opciones) -> tuple[list[tuple[str, list[float]]], list, str | None]:
    """Devuelve ``(cajas, otros_rostros, motivo)``; con motivo la foto no se guarda."""
    rostros = [r for r in detectar_rostros_con_ojos(frame) if r["confianza"] >= CONFIANZA_ROSTRO]
    if not rostros:
        return [], [], "No veo tu rostro: mira hacia la cámara"
    rostros.sort(key=lambda r: r["caja"][2] * r["caja"][3], reverse=True)
    principal, otros = rostros[0], [r["caja"] for r in rostros[1:]]
    x, y, w, h = principal["caja"]
    centro_x = x + w / 2

    cajas = [("persona", caja) for nombre, caja in _detectar(coco, frame, {"person"}, 0.5)]
    if not cajas:
        return [], otros, "No veo a la persona completa"
    cajas.append(("gafas" if opciones.gafas == "si" else "sin_gafas", caja_gafas(principal["ojos"])))

    del_modelo = _detectar(industria, frame, {"casco", "chaleco"}, 0.4) if "si" in (opciones.casco, opciones.chaleco) else []
    if opciones.casco == "si":
        # El casco de quien posa: sobre su rostro (centro alineado y por encima de los ojos)
        cascos = [c for n, c in del_modelo if n == "casco" and c[0] <= centro_x <= c[2] and (c[1] + c[3]) / 2 < y + h / 2]
        if not cascos:
            return [], otros, "No veo el casco"
        cajas.append(("casco", min(cascos, key=lambda c: abs((c[0] + c[2]) / 2 - centro_x))))
    else:
        cajas.append(("sin_casco", caja_cabeza(principal["caja"])))
    if opciones.chaleco == "si":
        chalecos = [c for n, c in del_modelo if n == "chaleco" and c[0] <= centro_x <= c[2]]
        if not chalecos:
            return [], otros, "No veo el chaleco"
        cajas.append(("chaleco", chalecos[0]))
    return cajas, otros, None


def difuminar(frame: np.ndarray, rostros: list) -> None:
    """Difumina en el frame los rostros de quienes no están posando."""
    alto, ancho = frame.shape[:2]
    for x, y, w, h in rostros:
        x0, y0 = max(0, int(x - w * MARGEN)), max(0, int(y - h * MARGEN))
        x1, y1 = min(ancho, int(x + w * (1 + MARGEN))), min(alto, int(y + h * (1 + MARGEN)))
        if x1 > x0 and y1 > y0:
            nucleo = max(31, (max(x1 - x0, y1 - y0) // 2) | 1)
            frame[y0:y1, x0:x1] = cv2.GaussianBlur(frame[y0:y1, x0:x1], (nucleo, nucleo), 0)


def a_yolo(cajas, ancho: int, alto: int) -> str:
    lineas = []
    for nombre, (x1, y1, x2, y2) in cajas:
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(ancho, x2), min(alto, y2)
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        lineas.append(f"{CLASES.index(nombre)} {(x1 + x2) / 2 / ancho:.6f} {(y1 + y2) / 2 / alto:.6f} "
                      f"{(x2 - x1) / ancho:.6f} {(y2 - y1) / alto:.6f}")
    return "\n".join(lineas) + "\n"


def dibujar(frame: np.ndarray, cajas, con_nombre: bool = True) -> None:
    for nombre, (x1, y1, x2, y2) in cajas:
        color = ROJO if nombre.startswith("sin_") else VERDE
        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2, cv2.LINE_AA)
        if con_nombre:
            cv2.putText(frame, nombre, (int(x1) + 4, int(y1) + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)


def texto(frame: np.ndarray, mensaje: str, linea: int, color=MARFIL) -> None:
    y = 34 + 32 * linea
    cv2.putText(frame, mensaje, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, NEGRO, 5, cv2.LINE_AA)
    cv2.putText(frame, mensaje, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2, cv2.LINE_AA)


def main() -> int:
    analizador = argparse.ArgumentParser(description="Captura fotos propias con anotación automática")
    analizador.add_argument("--gafas", choices=["si", "no"], required=True, help="¿Llevas gafas de seguridad?")
    analizador.add_argument("--casco", choices=["si", "no"], required=True, help="¿Llevas casco?")
    analizador.add_argument("--chaleco", choices=["si", "no"], default="no", help="¿Llevas chaleco?")
    analizador.add_argument("--para", choices=["entrenar", "evaluar"], default="entrenar",
                            help="Las de 'evaluar' no se usan para entrenar: miden si el modelo mejoró")
    analizador.add_argument("--segundos", type=float, default=90)
    analizador.add_argument("--cada", type=float, default=0.5, help="Segundos entre fotos")
    analizador.add_argument("--camara", type=int, help="Índice de la cámara (por defecto EPP_CAMARA)")
    opciones = analizador.parse_args()

    from ultralytics import YOLO

    for archivo in ("yolo26n.pt", "epp-industria-v1.pt"):
        if not (DIR_MODELOS / archivo).is_file():
            print(f"Falta {archivo} en {DIR_MODELOS}", file=sys.stderr)
            return 1
    coco, industria = YOLO(str(DIR_MODELOS / "yolo26n.pt")), YOLO(str(DIR_MODELOS / "epp-industria-v1.pt"))
    # La misma cámara y los mismos ajustes (enfoque, exposición) que usa la estación
    camara = conectar_camara(ConfigCamara.desde_entorno("EPP").con_camara(opciones.camara))
    if not camara.conectada:
        print("No se encontró la cámara. Ver: python -m herramientas.listar_camaras", file=sys.stderr)
        return 1

    sesion = f"{datetime.now():%Y%m%d-%H%M%S}_gafas-{opciones.gafas}_casco-{opciones.casco}_chaleco-{opciones.chaleco}"
    carpeta = DIR_FOTOS / opciones.para / sesion
    (carpeta / "images").mkdir(parents=True)
    (carpeta / "labels").mkdir()
    (carpeta / "classes.txt").write_text("\n".join(CLASES) + "\n", encoding="utf-8")

    ventana = "Captura de fotos propias"
    cv2.namedWindow(ventana, cv2.WINDOW_NORMAL)
    guardadas, ultima, motivo, cajas = 0, 0.0, None, []
    inicio = time.monotonic() + 4  # cuenta regresiva para acomodarse
    resumen = f"gafas: {opciones.gafas}   casco: {opciones.casco}   chaleco: {opciones.chaleco}"
    try:
        while True:
            frame = camara.leer()
            if frame is None:
                if not camara.conectada:
                    print("La cámara se desconectó; la captura termina aquí.", file=sys.stderr)
                    break
                continue
            ahora = time.monotonic()
            restante = opciones.segundos - (ahora - inicio)
            if restante <= 0:
                break
            if ahora >= inicio and ahora - ultima >= opciones.cada:
                ultima = ahora
                cajas, otros, motivo = anotar(frame, coco, industria, opciones)
                if motivo is None:
                    foto = frame.copy()
                    difuminar(foto, otros)
                    nombre = f"{sesion}_{guardadas:04d}"
                    cv2.imwrite(str(carpeta / "images" / f"{nombre}.jpg"), foto, [cv2.IMWRITE_JPEG_QUALITY, 92])
                    (carpeta / "labels" / f"{nombre}.txt").write_text(a_yolo(cajas, frame.shape[1], frame.shape[0]), encoding="utf-8")
                    guardadas += 1

            vista = frame.copy()
            dibujar(vista, cajas if motivo is None else [], con_nombre=False)
            vista = cv2.flip(vista, 1)  # espejo; los nombres no se dibujan porque quedarían al revés
            if ahora < inicio:
                texto(vista, f"Empieza en {inicio - ahora:.0f}...  ({resumen})", 0)
            else:
                texto(vista, f"Fotos: {guardadas}   Quedan {restante:.0f} s   ({resumen})", 0)
                texto(vista, motivo or "Muevete: cerca, lejos, a los lados, gira un poco la cabeza", 1, ROJO if motivo else MARFIL)
            texto(vista, "Q para terminar", 2)
            cv2.imshow(ventana, vista)
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q"), 27):
                break
    finally:
        camara.cerrar()
        cv2.destroyAllWindows()

    if guardadas == 0:
        for sub in ("images", "labels"):
            (carpeta / sub).rmdir()
        (carpeta / "classes.txt").unlink()
        carpeta.rmdir()
        print("No se guardó ninguna foto.")
        return 1
    print(f"{guardadas} fotos guardadas en {carpeta}")
    print("Siguiente paso, cuando tengas todas las sesiones: python -m modulos.epp.datos.ampliar_dataset")
    return 0


if __name__ == "__main__":
    sys.exit(main())
