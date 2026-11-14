"""Lista las cámaras conectadas y abre una vista previa de la que se elija.

    python -m herramientas.listar_camaras              # lista y pregunta cuál ver
    python -m herramientas.listar_camaras --indice 1   # vista previa directa de la cámara 1
    python -m herramientas.listar_camaras --sin-vista  # solo la lista

Por cada cámara muestra el índice, el nombre (si el sistema lo permite) y las resoluciones
que acepta. El índice que funcione va en el .env del módulo (por ejemplo ERGONOMIA_CAMARA=1).

Cada cámara debe conectarse siempre al mismo puerto USB: el índice puede cambiar al
cambiarla de puerto. Con dos cámaras del mismo modelo el nombre no las distingue; la vista
previa es la forma de saber cuál es cuál.

La vista previa es un espejo en pantalla: no guarda ni envía nada. Se cierra con Q o Esc.
"""

from __future__ import annotations

import argparse

import cv2

from modulos.comun.camara_stand import ConfigCamara, _backend, conectar_camara, nombres_de_camaras

INDICES_A_PROBAR = 6
RESOLUCIONES = ((640, 480), (1280, 720), (1920, 1080), (2560, 1440), (3840, 2160))


def resoluciones_soportadas(indice: int) -> list[tuple[int, int]]:
    """Resoluciones de la lista habitual que la cámara acepta de verdad (pidiéndolas una a una)."""
    captura = cv2.VideoCapture(indice, _backend())
    aceptadas: list[tuple[int, int]] = []
    try:
        if not captura.isOpened() or not captura.read()[0]:
            return []
        for ancho, alto in RESOLUCIONES:
            captura.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
            captura.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
            captura.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            real = (int(captura.get(cv2.CAP_PROP_FRAME_WIDTH)), int(captura.get(cv2.CAP_PROP_FRAME_HEIGHT)))
            if real == (ancho, alto) and real not in aceptadas:
                aceptadas.append(real)
    finally:
        captura.release()
    return aceptadas


def listar(maximo: int = INDICES_A_PROBAR) -> list[dict]:
    """Cámaras que dan imagen: ``indice``, ``nombre`` (o None) y ``resoluciones``."""
    nombres = nombres_de_camaras()
    camaras = []
    for indice in range(maximo):
        resoluciones = resoluciones_soportadas(indice)
        if resoluciones:
            camaras.append({"indice": indice, "resoluciones": resoluciones,
                            "nombre": nombres[indice] if indice < len(nombres) else None})
    return camaras


def vista_previa(indice: int) -> None:
    """Muestra la cámara elegida con la configuración del stand (720p, MJPG, enfoque fijo)."""
    camara = conectar_camara(ConfigCamara(indice=indice))
    ventana = f"Camara {indice} - Q o Esc para cerrar"
    cv2.namedWindow(ventana, cv2.WINDOW_NORMAL)
    try:
        while True:
            frame = camara.leer()
            if frame is not None:
                ancho, alto = camara.resolucion or (0, 0)
                texto = f"Camara {indice}  {ancho}x{alto}  {camara.fps_reales:.0f} fps"
                cv2.putText(frame, texto, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4, cv2.LINE_AA)
                cv2.putText(frame, texto, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (234, 241, 242), 2, cv2.LINE_AA)
                cv2.imshow(ventana, frame)
            tecla = cv2.waitKey(1 if frame is not None else 100) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27) or cv2.getWindowProperty(ventana, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        camara.cerrar()
        cv2.destroyAllWindows()


def main() -> None:
    analizador = argparse.ArgumentParser(description="Lista las cámaras y abre una vista previa.")
    analizador.add_argument("--indice", type=int, help="abre la vista previa de esta cámara sin preguntar")
    analizador.add_argument("--sin-vista", action="store_true", help="solo lista, no abre vista previa")
    opciones = analizador.parse_args()

    if opciones.indice is None or opciones.sin_vista:
        print("Buscando cámaras (unos segundos)…", flush=True)
        camaras = listar()
        if not camaras:
            print("No se encontró ninguna cámara. Revisa la conexión y que ningún otro programa la esté usando.")
            return
        for camara in camaras:
            resoluciones = ", ".join(f"{ancho}x{alto}" for ancho, alto in camara["resoluciones"])
            print(f"  Cámara {camara['indice']}: {camara['nombre'] or 'nombre no disponible'} — {resoluciones}")
        print("El nombre es orientativo (en Windows puede no corresponder al índice): confirma con la vista previa.")
        print("Conecta cada cámara siempre al mismo puerto USB: el índice cambia al cambiar de puerto.")
        if opciones.sin_vista:
            return
        respuesta = input("Índice de la cámara para la vista previa (Enter para salir): ").strip()
        if not respuesta.isdigit():
            return
        opciones.indice = int(respuesta)
    vista_previa(opciones.indice)


if __name__ == "__main__":
    main()
