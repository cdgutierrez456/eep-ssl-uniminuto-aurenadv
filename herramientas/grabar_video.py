"""Graba un video de prueba desde la cámara del stand, para desarrollar sin estar frente a ella.

    python -m herramientas.grabar_video                       # cámara de ERGONOMIA_CAMARA
    python -m herramientas.grabar_video --camara 1 --segundos 20
    python -m herramientas.grabar_video --salida datasets/videos/levantamiento.mp4

Empieza a grabar con la barra espaciadora y termina con la barra otra vez, con Q o Esc, o
al cumplirse ``--segundos``. El archivo sirve para ``python -m modulos.ergonomia --video``.

Privacidad: es material de desarrollo, con las mismas condiciones que las fotos de
entrenamiento. Quien aparece aceptó ser grabado; el video queda en ``datasets/`` (fuera de
git) en este equipo; nunca se sube, se adjunta a eventos ni se envía a ningún servicio. No
se difumina por defecto porque el estimador de pose necesita ver la cabeza; con
``--difuminar`` se guardan los rostros difuminados.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

import cv2

from modulos.comun.camara_stand import ConfigCamara, conectar_camara
from modulos.comun.rostros import difuminar_rostros

CARPETA_POR_DEFECTO = Path("datasets") / "videos"


def main() -> None:
    analizador = argparse.ArgumentParser(description="Graba un video de prueba desde la cámara.")
    analizador.add_argument("--camara", help="índice o nombre; por defecto, el de --prefijo en el .env")
    analizador.add_argument("--prefijo", default="ERGONOMIA", help="prefijo de las variables de cámara del .env")
    analizador.add_argument("--salida", type=Path, help="archivo .mp4 de salida")
    analizador.add_argument("--segundos", type=float, default=30.0, help="duración máxima de la grabación")
    analizador.add_argument("--difuminar", action="store_true", help="guardar con los rostros difuminados")
    opciones = analizador.parse_args()

    config = ConfigCamara.desde_entorno(opciones.prefijo).con_camara(opciones.camara)
    camara = conectar_camara(config)
    if not camara.conectada:
        print("No se pudo abrir la cámara. Revisa el índice con: python -m herramientas.listar_camaras")
        return

    salida = opciones.salida or CARPETA_POR_DEFECTO / f"prueba-{datetime.now():%Y%m%d-%H%M%S}.mp4"
    salida.parent.mkdir(parents=True, exist_ok=True)
    print("Solo graba a quien aceptó ser grabado. El video se queda en este equipo y no se sube a ningún lado.")
    print("Barra espaciadora: empezar y terminar. Q o Esc: salir.")

    ventana = "Grabar video - espacio: grabar / Q: salir"
    cv2.namedWindow(ventana, cv2.WINDOW_NORMAL)
    escritor: cv2.VideoWriter | None = None
    inicio = 0.0
    cuadros = 0
    try:
        while True:
            frame = camara.leer()
            tecla = cv2.waitKey(1 if frame is not None else 100) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27):
                break
            if frame is None:
                continue
            if tecla == ord(" "):
                if escritor is not None:
                    break
                alto, ancho = frame.shape[:2]
                fps = camara.fps_reales or config.fps
                # La ruta va como texto: cv2 no acepta Path
                escritor = cv2.VideoWriter(str(salida), cv2.VideoWriter_fourcc(*"mp4v"), round(fps), (ancho, alto))
                inicio = time.monotonic()
            if escritor is not None:
                escritor.write(difuminar_rostros(frame) if opciones.difuminar else frame)
                cuadros += 1
                if time.monotonic() - inicio >= opciones.segundos:
                    break
            # La vista es un espejo en pantalla: el indicador se dibuja sobre una copia
            vista = frame.copy()
            if escritor is not None:
                cv2.circle(vista, (40, 40), 14, (40, 40, 220), -1, cv2.LINE_AA)
                cv2.putText(vista, f"{time.monotonic() - inicio:4.1f} s", (66, 50), cv2.FONT_HERSHEY_SIMPLEX,
                            1.0, (234, 241, 242), 2, cv2.LINE_AA)
            cv2.imshow(ventana, vista)
    finally:
        if escritor is not None:
            escritor.release()
        camara.cerrar()
        cv2.destroyAllWindows()

    if cuadros:
        print(f"Video guardado: {salida.as_posix()} ({cuadros} cuadros)")
    else:
        print("No se grabó nada.")


if __name__ == "__main__":
    main()
