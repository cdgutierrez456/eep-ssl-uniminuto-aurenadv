"""Ventana de calibración de la zona: ``python -m modulos.zona.calibracion``.

Muestra la cámara en vivo con la zona encima y deja detectar la cinta, corregir los vértices
con el mouse, escribir las medidas reales y guardar. También atiende los pedidos de
detección que lleguen desde la plataforma. Es la estación sin la detección de personas:
sirve para montar y calibrar el stand.

Privacidad: lo que se ve en la ventana es un espejo en vivo y no se difumina. Lo que sale
de ahí (la imagen de referencia, la captura) lleva los rostros difuminados.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from modulos.comun import conectar_camara, difuminar_rostros
from modulos.comun.camara_stand import MENSAJE_DESCONECTADA

from ..config import AjustesLocales, AlmacenConfig
from ..fuentes import FuenteImagen, FuenteVideo
from ..interfaz.marca import DEEP, LIMA, MARFIL, MARFIL_TENUE, bgr
from ..interfaz.texto import escribir
from .calibrador import CUADROS_ANTES_DE_LA_REFERENCIA, TECLA_ESC, Calibrador
from .cinta import RangoHSV
from .vista import resaltar_amarillo

log = logging.getLogger(__name__)

VENTANA = "Auren SST - Zona: calibracion"
ALTO_BARRA = 72  # franja superior: título y estado de la zona
ALTO_PIE = 76  # franja inferior: aviso y teclas
TAMANO_SIN_IMAGEN = (1280, 720)


def componer(vista: np.ndarray | None, calibrador: Calibrador, config: Mapping[str, Any], fuente: str,
             aviso: str | None = None, tamano: tuple[int, int] = TAMANO_SIN_IMAGEN) -> np.ndarray:
    """Arma la pantalla: franja de título, la vista de la cámara y franja de avisos y teclas."""
    ancho, alto = (vista.shape[1], vista.shape[0]) if vista is not None else tamano
    # Solo se pintan de fondo las dos franjas: rellenar el lienzo entero en cada fotograma es lento
    lienzo = np.empty((ALTO_BARRA + alto + ALTO_PIE, ancho, 3), dtype=np.uint8)
    lienzo[:ALTO_BARRA] = bgr(DEEP)
    lienzo[ALTO_BARRA + alto:] = bgr(DEEP)
    lienzo[ALTO_BARRA:ALTO_BARRA + alto] = vista if vista is not None else bgr(DEEP)
    escribir(lienzo, "Calibración de la zona de peligro", 20, 10, 26, MARFIL, negrita=True)
    escribir(lienzo, f"{fuente}  ·  {calibrador.estado(config, ancho, alto)}", 20, 44, 16, MARFIL_TENUE)
    lienzo[ALTO_BARRA - 3:ALTO_BARRA, :160] = bgr(LIMA)  # acento de marca, pequeño
    pie = ALTO_BARRA + alto
    escribir(lienzo, aviso or calibrador.mensaje, 20, pie + 10, 20, MARFIL, negrita=True)
    escribir(lienzo, calibrador.ayuda() + ("" if calibrador.medidas_en_curso is not None
                                           else "  ·  V ver máscara  ·  Q salir"), 20, pie + 44, 15, MARFIL_TENUE)
    return lienzo


def _abrir_fuente(opciones: argparse.Namespace, ajustes: AjustesLocales):
    if opciones.imagen:  # una imagen fija no se acaba: siempre va a su ritmo, para no ocupar un núcleo entero
        return FuenteImagen(opciones.imagen), "Imagen"
    if opciones.video:
        return FuenteVideo(opciones.video, repetir=opciones.repetir, tiempo_real=not opciones.sin_ventana), "Video"
    camara = conectar_camara(ajustes.camara)
    return camara, f"Cámara {camara.indice if camara.indice is not None else ajustes.camara.indice}"


def _pantalla_completa(activar: bool) -> None:
    cv2.setWindowProperty(VENTANA, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN if activar else cv2.WINDOW_NORMAL)


def ejecutar(opciones: argparse.Namespace) -> int:
    ajustes = AjustesLocales.desde_entorno()
    almacen = AlmacenConfig(con_plataforma=not opciones.sin_plataforma)
    calibrador = Calibrador(almacen)
    fuente, nombre_fuente = _abrir_fuente(opciones, ajustes)
    de_archivo = bool(opciones.imagen or opciones.video)
    con_ventana = not opciones.sin_ventana
    if con_ventana:
        cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
        _pantalla_completa(ajustes.pantalla_completa and not opciones.ventana)
        # El mouse llega en píxeles de la pantalla compuesta: se le resta la franja superior
        cv2.setMouseCallback(VENTANA, lambda evento, x, y, *_: calibrador.mouse(evento, x, y - ALTO_BARRA))

    cuadros = 0
    ver_mascara = False
    ultimo: np.ndarray | None = None
    config = almacen.valor
    try:
        while True:
            config = almacen.valor  # se relee en cada fotograma: un cambio remoto se ve en vivo
            frame = fuente.leer()
            vista, aviso = None, None
            if frame is None:
                if getattr(fuente, "terminada", False):
                    break
                aviso = MENSAJE_DESCONECTADA if not fuente.conectada else None
            else:
                cuadros += 1
                ultimo = frame
                if cuadros == (1 if de_archivo else CUADROS_ANTES_DE_LA_REFERENCIA):
                    calibrador.tomar_referencia(frame)
                if opciones.detectar and cuadros == 1:
                    calibrador.detectar_local(frame, config)
                calibrador.atender(frame, config)
                vista = frame.copy()  # espejo en vivo: no se difumina porque no se guarda ni se envía
                if ver_mascara:
                    resaltar_amarillo(vista, RangoHSV.desde_config(config.get("cinta_hsv")))
                calibrador.dibujar(vista, config)
            if con_ventana:
                tamano = (ultimo.shape[1], ultimo.shape[0]) if ultimo is not None else TAMANO_SIN_IMAGEN
                cv2.imshow(VENTANA, componer(vista, calibrador, config, nombre_fuente, aviso, tamano))
                tecla = cv2.waitKey(1 if frame is not None else 50) & 0xFF
                if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                    break
                if tecla != 0xFF and not calibrador.tecla(tecla, frame, config):
                    if tecla in (ord("q"), ord("Q"), TECLA_ESC):
                        break
                    if tecla in (ord("v"), ord("V")):
                        ver_mascara = not ver_mascara
                    elif tecla in (ord("f"), ord("F")):
                        completa = cv2.getWindowProperty(VENTANA, cv2.WND_PROP_FULLSCREEN) == cv2.WINDOW_FULLSCREEN
                        _pantalla_completa(not completa)
            if opciones.max_cuadros and cuadros >= opciones.max_cuadros:
                break
    except KeyboardInterrupt:
        pass
    finally:
        fuente.cerrar()
        almacen.detener()
        if con_ventana:
            cv2.destroyAllWindows()
    if opciones.captura and ultimo is not None:
        _guardar_captura(opciones.captura, ultimo, calibrador, config, nombre_fuente)
    return 0


def _guardar_captura(ruta: Path, frame: np.ndarray, calibrador: Calibrador, config: Mapping[str, Any],
                     nombre_fuente: str) -> None:
    """Guarda la pantalla del último fotograma. Sale del espejo, así que va con rostros difuminados."""
    imagen = difuminar_rostros(frame)  # primero se difumina; la zona se dibuja después
    calibrador.dibujar(imagen, config)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    correcto, datos = cv2.imencode(ruta.suffix or ".png", componer(imagen, calibrador, config, nombre_fuente))
    if not correcto:
        raise OSError(f"No se pudo codificar la captura {ruta}")
    datos.tofile(str(ruta))  # así también funcionan las rutas con tildes en Windows
    log.info("Captura guardada (rostros difuminados): %s", ruta.as_posix())


def analizar_argumentos(argumentos: list[str] | None = None) -> argparse.Namespace:
    analizador = argparse.ArgumentParser(
        prog="python -m modulos.zona.calibracion",
        description=("Calibración de la zona de peligro. Teclas: D detecta la cinta; E edita con el mouse (clic agrega "
                     "o agarra un vértice, arrastrar lo mueve, clic derecho lo quita); G guarda; M medidas reales; "
                     "R nueva imagen de referencia; V ver la máscara de amarillo; F pantalla completa; Q o Esc salir."),
    )
    origen = analizador.add_mutually_exclusive_group()
    origen.add_argument("--video", type=Path, help="usa un archivo de video en lugar de la cámara")
    origen.add_argument("--imagen", type=Path, help="usa una imagen fija en lugar de la cámara")
    analizador.add_argument("--repetir", action="store_true", help="con --video, vuelve a empezar al terminar")
    analizador.add_argument("--ventana", action="store_true", help="abre en ventana, no a pantalla completa")
    analizador.add_argument("--sin-plataforma", action="store_true",
                            help="no consulta la plataforma: la zona se guarda solo en este equipo")
    analizador.add_argument("--detectar", action="store_true", help="detecta la cinta en el primer fotograma")
    analizador.add_argument("--sin-ventana", action="store_true", help="procesa sin mostrar nada (para pruebas)")
    analizador.add_argument("--max-cuadros", type=int, default=0, help="termina después de N fotogramas")
    analizador.add_argument("--captura", type=Path,
                            help="al terminar, guarda la pantalla del último fotograma (rostros difuminados)")
    return analizador.parse_args(argumentos)


def main(argumentos: list[str] | None = None) -> int:
    return ejecutar(analizar_argumentos(argumentos))
