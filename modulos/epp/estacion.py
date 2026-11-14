"""Estación en vivo de verificación de EPP: cámara, ventana, teclado y publicación.

Privacidad: la vista en vivo es un espejo y no se difumina porque no se guarda. Toda
imagen que se guarda o se envía pasa antes por ``difuminar_rostros`` y las cajas y
etiquetas se dibujan DESPUÉS del difuminado. No se guarda video.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from modulos.comun import (
    actualizar_config,
    difuminar_rostros,
    esperar_envios,
    iniciar_latido,
    obtener_config,
    publicar,
    registrar_capacidades,
    subir_medio,
)
from modulos.comun.camaras import abrir_camara
from modulos.comun.config import leer_entorno

from . import interfaz
from .deteccion import cargar_detectores
from .nucleo.perfiles import PerfilInvalido, cargar_perfiles, nombre_visible
from .verificador import Cuadro, Verificador

log = logging.getLogger(__name__)

MODULO = ESTACION = "epp"
VENTANA = "Auren - Verificacion de EPP"
TECLA_ENTER, TECLA_ESC, TECLAS_BORRAR = 13, 27, (8, 127)
SEGUNDOS_AVISO = 4.0


class ErrorEstacion(RuntimeError):
    """Problema que impide arrancar. El mensaje se muestra tal cual al operador."""


def _numero(variable: str, por_defecto: float) -> float:
    try:
        return float(os.getenv(variable, por_defecto))
    except ValueError:
        log.warning("%s no es un número; se usa %s", variable, por_defecto)
        return por_defecto


class Trabajos:
    """Un hilo que hace en orden lo que no debe frenar la imagen (red y disco)."""

    def __init__(self) -> None:
        self._cola: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self._hilo = threading.Thread(target=self._bucle, name="epp-trabajos", daemon=True)
        self._hilo.start()

    def encargar(self, trabajo: Callable[[], None]) -> None:
        self._cola.put(trabajo)

    def terminar(self, limite_s: float = 15.0) -> None:
        self._cola.put(None)
        self._hilo.join(timeout=limite_s)

    def _bucle(self) -> None:
        while (trabajo := self._cola.get()) is not None:
            try:
                trabajo()
            except Exception:
                log.exception("Falló un trabajo en segundo plano de la estación")


def publicar_verificacion(frame: np.ndarray, cuadro: Cuadro, reglas: dict[str, Any],
                          datos: dict[str, Any], sesion_id: str | None) -> dict:
    """Guarda la foto (rostros difuminados, cajas encima), la sube y publica verificacion_epp."""
    foto = difuminar_rostros(frame)
    interfaz.dibujar_cajas(foto, cuadro, reglas)  # siempre después del difuminado
    ruta_local = leer_entorno().carpeta_cola / "epp_fotos" / f"{uuid.uuid4().hex[:12]}.jpg"
    interfaz.guardar_foto(ruta_local, foto)
    try:
        ruta = subir_medio(ruta_local)
    finally:
        ruta_local.unlink(missing_ok=True)
    return publicar(
        ESTACION, "verificacion_epp", datos,
        severidad="info" if datos["cumple"] else "media",
        sesion_id=sesion_id, adjuntos=[{"tipo": "imagen", "ruta": ruta}],
    )


class Estacion:
    """Bucle de la estación. ``ejecutar`` no retorna hasta que el operador sale."""

    def __init__(self, camara: int | None = None, pantalla_completa: bool | None = None,
                 max_cuadros: int | None = None) -> None:
        self.indice_camara = int(_numero("EPP_CAMARA", 0)) if camara is None else camara
        self.pantalla_completa = (
            bool(_numero("EPP_PANTALLA_COMPLETA", 1)) if pantalla_completa is None else pantalla_completa
        )
        self.espejo = bool(_numero("EPP_ESPEJO", 1))
        self.max_cuadros = max_cuadros
        self.sesion_id: str | None = None
        self.entrada: str | None = None
        self._aviso: tuple[str, float] | None = None
        self._configs: queue.Queue[dict[str, Any]] = queue.Queue()

    # ------------------------------------------------------------------ #
    def ejecutar(self) -> None:
        try:
            self.perfiles = cargar_perfiles()
        except (PerfilInvalido, OSError) as error:
            raise ErrorEstacion(f"El archivo de perfiles no sirve: {error}") from None

        print("Cargando modelos…", flush=True)
        self.detectores, errores = cargar_detectores(self.perfiles)
        if not self.detectores:
            detalle = "\n".join(f"  - {nombre}: {error}" for nombre, error in errores.items())
            raise ErrorEstacion(f"No se pudo cargar ningún modelo de EPP:\n{detalle}")
        for nombre, error in errores.items():
            print(f"Aviso: el perfil '{nombre}' no está disponible ({error}). Los demás siguen funcionando.", flush=True)

        camara = abrir_camara(self.indice_camara)
        if camara is None:
            raise ErrorEstacion(
                f"No se encontró la cámara {self.indice_camara}. Revisa que esté conectada y que ningún otro "
                "programa la esté usando, o elige otra con EPP_CAMARA en el .env.\n"
                "Para ver las cámaras conectadas: python -m modulos.comun.camaras"
            )

        self.verificador = Verificador(
            self.perfiles, {nombre: d.clases for nombre, d in self.detectores.items()},
            segundos_estable=_numero("EPP_SEGUNDOS_ESTABLE", 2.0),
            segundos_sin_persona=_numero("EPP_SEGUNDOS_SIN_PERSONA", 3.0),
        )
        self.trabajos = Trabajos()
        registrar_capacidades(MODULO, self.verificador.capacidades)
        self.config_remota = obtener_config(
            MODULO, self.verificador.config_por_defecto, validar=self._validar, al_cambiar=self._configs.put
        )
        self.verificador.aplicar_config(self.config_remota.valor)
        self.latido = iniciar_latido(ESTACION, MODULO)
        self.panel = interfaz.Panel()

        cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(VENTANA, interfaz.ANCHO_LIENZO * 3 // 4, interfaz.ALTO_LIENZO * 3 // 4)
        self._aplicar_pantalla()
        try:
            self._bucle(camara)
        finally:
            if getattr(self, "_camara", None) is not None:
                self._camara.release()
            cv2.destroyAllWindows()
            self.config_remota.detener()
            self.latido.detener()
            self.trabajos.terminar()
            esperar_envios(5)

    # ------------------------------------------------------------------ #
    def _validar(self, candidata: Any) -> dict[str, Any]:
        config, advertencias = self.verificador.validar(candidata)
        for advertencia in advertencias:
            log.warning("Configuración de EPP: %s", advertencia)
        return config

    def _aplicar_pantalla(self) -> None:
        modo = cv2.WINDOW_FULLSCREEN if self.pantalla_completa else cv2.WINDOW_NORMAL
        cv2.setWindowProperty(VENTANA, cv2.WND_PROP_FULLSCREEN, modo)

    def avisar(self, texto: str) -> None:
        self._aviso = (texto, time.monotonic() + SEGUNDOS_AVISO)

    def _bucle(self, camara: cv2.VideoCapture) -> None:
        self._camara = camara
        cuadros = 0
        proximo_intento = 0.0
        while True:
            ahora = time.monotonic()
            self._aplicar_configs_pendientes()

            frame = None
            if self._camara is not None:
                correcto, frame = self._camara.read()
                if not correcto or frame is None:
                    log.error("La cámara dejó de entregar imagen")
                    self._camara.release()
                    self._camara, frame = None, None
                    self.latido.estado, self.latido.mensaje = "error", "Cámara sin señal"
            elif ahora >= proximo_intento:
                proximo_intento = ahora + 2.0
                self._camara = abrir_camara(self.indice_camara)
                if self._camara is not None:
                    log.info("Cámara recuperada")
                    self.latido.estado, self.latido.mensaje = "activo", None

            if frame is not None:
                if self.espejo:
                    frame = cv2.flip(frame, 1)
                cuadro = self.verificador.procesar(self.detectores[self.verificador.perfil_activo].detectar(frame), ahora)
                self._atender(cuadro, frame)
                interfaz.dibujar_cajas(frame, cuadro, self.verificador.reglas)  # el frame en vivo no se guarda
                lienzo = interfaz.componer(frame, self.panel.imagen(self._estado_panel(cuadro)))
            else:
                lienzo = interfaz.componer(
                    None, self.panel.imagen(self._estado_panel(None)),
                    ("Cámara sin señal", "Revisa la conexión; se reintenta sola cada 2 segundos."),
                )
            cv2.imshow(VENTANA, lienzo)

            tecla = cv2.waitKey(1 if frame is not None else 100) & 0xFF
            if tecla != 0xFF and not self._tecla(tecla):
                return
            if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:  # cerraron la ventana
                return
            cuadros += 1
            if self.max_cuadros is not None and cuadros >= self.max_cuadros:
                return

    # ------------------------------------------------------------------ #
    def _aplicar_configs_pendientes(self) -> None:
        """Aplica el último cambio de configuración (remoto o local) llegado desde otro hilo."""
        ultima = None
        while True:
            try:
                ultima = self._configs.get_nowait()
            except queue.Empty:
                break
        if ultima is not None and self.verificador.aplicar_config(ultima):
            datos = self.verificador.datos_config()
            publicar(ESTACION, "config_actualizada", datos, severidad="info")
            self.avisar("Configuración actualizada")
            log.info("Configuración aplicada: perfil %s, requeridos %s",
                     datos["perfil_activo"], ", ".join(datos["elementos_requeridos"]) or "ninguno")

    def _atender(self, cuadro: Cuadro, frame: np.ndarray) -> None:
        """Reacciona a las novedades del cuadro: fin de visita y publicación."""
        if cuadro.novedad.visita_terminada:
            self.sesion_id = None
        if cuadro.evento is not None:
            copia, reglas, datos, sesion = frame.copy(), self.verificador.reglas, cuadro.evento, self.sesion_id
            self.trabajos.encargar(lambda: publicar_verificacion(copia, cuadro, reglas, datos, sesion))
            self.avisar("Verificación registrada")

    def _estado_panel(self, cuadro: Cuadro | None) -> interfaz.EstadoPanel:
        verificador = self.verificador
        perfil = verificador.perfil_activo
        principal = cuadro.principal if cuadro is not None else None
        if principal is None:
            veredicto = "nadie"
        elif not principal.get("estable", True):
            veredicto = "verificando"
        else:
            veredicto = "cumple" if principal["cumple"] else "no_cumple"
        elementos = tuple(
            (nombre_visible(self.perfiles, perfil, e),
             "pendiente" if principal is None else ("si" if principal["elementos"][e] else "no"))
            for e in verificador.requeridos
        )
        faltantes = tuple(nombre_visible(self.perfiles, perfil, e).lower() for e in principal["faltantes"]) if principal else ()
        aviso = self._aviso[0] if self._aviso and time.monotonic() < self._aviso[1] else None
        teclas = tuple(
            (str(numero), self.perfiles["perfiles"][nombre]["nombre"], nombre in self.detectores)
            for numero, nombre in enumerate(self.perfiles["perfiles"], start=1)
        )
        return interfaz.EstadoPanel(
            perfil=self.perfiles["perfiles"][perfil]["nombre"], elementos=elementos, veredicto=veredicto,
            faltantes=faltantes, sesion=self.sesion_id, entrada=self.entrada, aviso=aviso,
            fuente_config=self.config_remota.fuente, teclas=teclas,
        )

    # ------------------------------------------------------------------ #
    def _tecla(self, tecla: int) -> bool:
        """Atiende una tecla. Devuelve False para salir."""
        caracter = chr(tecla).lower()
        if self.entrada is not None:  # tecleando el número de visitante
            if tecla == TECLA_ENTER:
                self.sesion_id = f"V-{int(self.entrada):04d}" if self.entrada else None
                self.entrada = None
            elif tecla == TECLA_ESC:
                self.entrada = None
            elif tecla in TECLAS_BORRAR:
                self.entrada = self.entrada[:-1]
            elif caracter.isdigit() and len(self.entrada) < 6:
                self.entrada += caracter
            return True

        if caracter == "q" or tecla == TECLA_ESC:
            return False
        if caracter == "v":
            self.entrada = ""
        elif caracter == "f":
            self.pantalla_completa = not self.pantalla_completa
            self._aplicar_pantalla()
        elif caracter.isdigit() and caracter != "0":
            self._cambiar_perfil(int(caracter))
        return True

    def _cambiar_perfil(self, numero: int) -> None:
        nombres = list(self.perfiles["perfiles"])
        if numero > len(nombres):
            return
        nombre = nombres[numero - 1]
        if nombre not in self.detectores:
            self.avisar(f"El perfil {self.perfiles['perfiles'][nombre]['nombre']} no está disponible")
        elif nombre != self.verificador.perfil_activo:
            # En segundo plano: si la plataforma no responde, el PUT no debe congelar la imagen.
            # El cambio se aplica de inmediato y vuelve por el aviso de configuración.
            nueva = self.verificador.con_perfil(nombre)
            self.trabajos.encargar(lambda: actualizar_config(MODULO, nueva))
