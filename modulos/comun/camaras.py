"""Cámaras del stand: abrirlas igual en todos los módulos de visión y saber cuál es cuál.

Para ver qué cámaras hay conectadas y qué índice tiene cada una::

    python -m modulos.comun.camaras

El índice se pone en el .env del módulo (por ejemplo EPP_CAMARA=2). Ojo: el índice
depende del equipo y puede cambiar al conectar la cámara en otro puerto USB.
"""

from __future__ import annotations

import sys
import time

import cv2

INDICES_A_PROBAR = 6


def _backends() -> list[int]:
    # En Windows solo DirectShow: abre mucho más rápido y, sobre todo, cada backend numera
    # las cámaras a su manera; mezclarlos hace que una misma cámara salga con dos índices.
    return [cv2.CAP_DSHOW] if sys.platform == "win32" else [cv2.CAP_ANY]


def abrir_camara(indice: int, ancho: int = 1280, alto: int = 720) -> cv2.VideoCapture | None:
    """Abre la cámara a la resolución pedida y comprueba que entrega imagen.

    Devuelve None si no existe o no da imagen (nunca lanza). Pide MJPG después de fijar
    el tamaño: sin eso una webcam USB externa (Logitech) cae a ~10 cuadros por segundo
    en 720p; una cámara que no lo soporte simplemente lo ignora.
    """
    for backend in _backends():
        camara = cv2.VideoCapture(indice, backend)
        if camara.isOpened():
            camara.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
            camara.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
            camara.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            camara.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # siempre el cuadro más reciente
            correcto, frame = camara.read()
            if correcto and frame is not None:
                return camara
        camara.release()
    return None


def listar_camaras(maximo: int = INDICES_A_PROBAR) -> list[dict]:
    """Prueba los índices 0..maximo-1 y devuelve las cámaras que dan imagen.

    Por cada una: ``indice``, ``resolucion_maxima`` (ancho, alto) y ``fps`` medidos en 720p.
    La resolución máxima ayuda a reconocerlas: la integrada de un portátil suele llegar
    a 1280x720 y una Logitech externa a 1920x1080.
    """
    encontradas = []
    for indice in range(maximo):
        camara = abrir_camara(indice, 1920, 1080)
        if camara is None:
            continue
        maxima = (int(camara.get(cv2.CAP_PROP_FRAME_WIDTH)), int(camara.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        camara.release()
        camara = abrir_camara(indice)
        cuadros, inicio = 0, time.monotonic()
        while camara is not None and time.monotonic() - inicio < 1.5:
            if not camara.read()[0]:
                break
            cuadros += 1
        if camara is not None:
            camara.release()
        encontradas.append({"indice": indice, "resolucion_maxima": maxima, "fps": round(cuadros / 1.5)})
    return encontradas


def main() -> None:
    print("Buscando cámaras (unos segundos)…", flush=True)
    camaras = listar_camaras()
    if not camaras:
        print("No se encontró ninguna cámara. Revisa la conexión y que ningún otro programa la esté usando.")
        return
    for camara in camaras:
        ancho, alto = camara["resolucion_maxima"]
        print(f"  Cámara {camara['indice']}: hasta {ancho}x{alto}, ~{camara['fps']} cuadros por segundo en 720p")
    print("Pon el índice en el .env del módulo, por ejemplo EPP_CAMARA=2.")


if __name__ == "__main__":
    main()
