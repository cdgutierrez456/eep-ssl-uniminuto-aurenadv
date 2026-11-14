"""Suavizado temporal del veredicto EPP para video (función pura sobre estado explícito).

Implementa la sección *Suavizado temporal* de `contrato/CONTRATO.md`:

- Tracks por persona emparejados cuadro a cuadro con IoU (greedy uno-a-uno),
  sin tracker complejo. El ``id`` de la persona pasa a ser el del track.
- Máquina de estados por (track, elemento): ``CUMPLE`` / ``FALTA`` / ``BLOQUEADO``,
  con ventana de las últimas N evidencias observadas y voto de mayoría.
- Una negativa explícita invalida de inmediato; recuperar exige
  ``confirmacion_positiva`` positivas consecutivas.

Sin dependencias externas: solo ``collections.deque`` y las funciones geométricas
de ``reglas.py``. Fácil de reimplementar en Dart.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from .reglas import (
    EVIDENCIA_DESCONOCIDO,
    EVIDENCIA_NEGATIVO,
    EVIDENCIA_POSITIVO,
    calcular_resumen,
    clave_orden,
    completar_persona,
    iou,
)

ESTADO_CUMPLE = "CUMPLE"
ESTADO_FALTA = "FALTA"
ESTADO_BLOQUEADO = "BLOQUEADO"


class EstadoElemento:
    """Estado temporal de un elemento (p. ej. ``cofia``) dentro de un track."""

    def __init__(self, ventana_cuadros: int) -> None:
        self.estado: str = ESTADO_FALTA
        self.ventana: deque[str] = deque(maxlen=ventana_cuadros)
        self.positivas_consecutivas: int = 0

    def observar(self, evidencia: str, mayoria: float, confirmacion_positiva: int) -> None:
        """Aplica una observación y actualiza el estado según la máquina del contrato."""
        self.ventana.append(evidencia)
        if evidencia == EVIDENCIA_NEGATIVO:
            self.estado = ESTADO_BLOQUEADO
            self.positivas_consecutivas = 0
            return
        if evidencia == EVIDENCIA_POSITIVO:
            self.positivas_consecutivas += 1
        else:  # desconocido: rompe la racha, no bloquea
            self.positivas_consecutivas = 0

        if self.estado == ESTADO_BLOQUEADO:
            if self.positivas_consecutivas >= confirmacion_positiva:
                # Recuperación: la ventana se reinicia con las positivas confirmadas.
                self.ventana.clear()
                for _ in range(confirmacion_positiva):
                    self.ventana.append(EVIDENCIA_POSITIVO)
                self.positivas_consecutivas = confirmacion_positiva
                self.estado = ESTADO_CUMPLE
            return

        positivos = sum(1 for e in self.ventana if e == EVIDENCIA_POSITIVO)
        self.estado = ESTADO_CUMPLE if positivos / len(self.ventana) >= mayoria else ESTADO_FALTA

    def observaciones(self) -> int:
        return len(self.ventana)

    def valor(self, evidencia_actual: str, minimo_observaciones: int) -> bool:
        """Booleano suavizado del elemento (regla de arranque incluida)."""
        if len(self.ventana) < minimo_observaciones:
            if self.estado == ESTADO_BLOQUEADO:
                return False
            return evidencia_actual == EVIDENCIA_POSITIVO
        return self.estado == ESTADO_CUMPLE


class Track:
    """Una persona seguida a lo largo de los cuadros."""

    def __init__(self, identificador: int, caja: list[float], elementos: list[str], ventana: int) -> None:
        self.id = identificador
        self.ultima_caja: list[float] = list(caja)
        self.cuadros_sin_ver = 0
        self.elementos: dict[str, EstadoElemento] = {e: EstadoElemento(ventana) for e in elementos}


class SuavizadorTemporal:
    """Mantiene los tracks de una sesión de video y suaviza cada veredicto instantáneo.

    Uso::

        suavizador = SuavizadorTemporal(reglas)
        for cuadro in video:
            instantaneo = evaluar_cuadro(detecciones(cuadro), reglas)
            suavizado = suavizador.procesar(instantaneo)

    ``reiniciar()`` borra todos los tracks y el contador de ``id`` (reconexión,
    cambio de cámara o de modelo).
    """

    def __init__(self, reglas: dict[str, Any]) -> None:
        config = reglas["suavizado"]
        self.elementos: list[str] = list(reglas["elementos_requeridos"])
        self.ventana_cuadros: int = config["ventana_cuadros"]
        self.iou_minimo: float = config["iou_minimo"]
        self.mayoria: float = config["mayoria"]
        self.minimo_observaciones: int = config["minimo_observaciones"]
        self.confirmacion_positiva: int = config["confirmacion_positiva"]
        self.cuadros_sin_ver_max: int = config["cuadros_sin_ver_max"]
        self.tracks: list[Track] = []
        self._siguiente_id = 1

    def reiniciar(self) -> None:
        """Olvida todos los tracks y reinicia el contador de identificadores."""
        self.tracks = []
        self._siguiente_id = 1

    # ------------------------------------------------------------------ #
    def procesar(self, veredicto: dict[str, Any]) -> dict[str, Any]:
        """Suaviza un veredicto instantáneo (salida de ``evaluar_cuadro``).

        Devuelve un veredicto nuevo con ``id`` de track, ``elementos``/``cumple``/
        ``faltantes`` suavizados, ``estable`` por persona y ``resumen`` recalculado.
        El orden de la lista de personas se conserva (orden geométrico).
        """
        personas = veredicto["personas"]
        emparejamiento = self._emparejar(personas)

        # Tracks no emparejados: envejecen y caducan.
        emparejados = set(emparejamiento.values())
        supervivientes: list[Track] = []
        for track in self.tracks:
            if track.id in emparejados:
                supervivientes.append(track)
                continue
            track.cuadros_sin_ver += 1
            if track.cuadros_sin_ver <= self.cuadros_sin_ver_max:
                supervivientes.append(track)
        self.tracks = supervivientes

        # Personas nuevas: tracks nuevos en orden geométrico.
        por_id = {t.id: t for t in self.tracks}
        indices_nuevos = [i for i in range(len(personas)) if i not in emparejamiento]
        indices_nuevos.sort(key=lambda i: clave_orden({"caja": personas[i]["caja"], "confianza": 1.0}))
        for indice in indices_nuevos:
            track = Track(self._siguiente_id, personas[indice]["caja"], self.elementos, self.ventana_cuadros)
            self._siguiente_id += 1
            self.tracks.append(track)
            por_id[track.id] = track
            emparejamiento[indice] = track.id

        # Observación y salida.
        salida: list[dict[str, Any]] = []
        for indice, persona in enumerate(personas):
            track = por_id[emparejamiento[indice]]
            track.ultima_caja = list(persona["caja"])
            track.cuadros_sin_ver = 0
            elementos_suavizados: dict[str, bool] = {}
            estable = True
            for elemento in self.elementos:
                evidencia = persona["evidencia"].get(elemento, EVIDENCIA_DESCONOCIDO)
                estado = track.elementos[elemento]
                estado.observar(evidencia, self.mayoria, self.confirmacion_positiva)
                elementos_suavizados[elemento] = estado.valor(evidencia, self.minimo_observaciones)
                if estado.observaciones() < self.minimo_observaciones:
                    estable = False
            nueva = {
                "id": track.id,
                "caja": list(persona["caja"]),
                "inferida": persona.get("inferida", False),
                "elementos": elementos_suavizados,
                "evidencia": {e: persona["evidencia"].get(e, EVIDENCIA_DESCONOCIDO) for e in self.elementos},
                "estable": estable,
            }
            salida.append(completar_persona(nueva, self.elementos))

        return {"personas": salida, "resumen": calcular_resumen(salida)}

    # ------------------------------------------------------------------ #
    def _emparejar(self, personas: list[dict[str, Any]]) -> dict[int, int]:
        """Emparejamiento greedy uno-a-uno: índice de persona -> id de track.

        Candidatos con ``iou >= iou_minimo`` ordenados por IoU descendente, luego
        ``id`` de track ascendente, luego índice de persona (orden geométrico).
        """
        candidatos: list[tuple[float, int, int]] = []
        for track in self.tracks:
            for indice, persona in enumerate(personas):
                valor = iou(track.ultima_caja, persona["caja"])
                if valor >= self.iou_minimo:
                    candidatos.append((valor, track.id, indice))
        candidatos.sort(key=lambda c: (-c[0], c[1], c[2]))

        asignacion: dict[int, int] = {}
        tracks_usados: set[int] = set()
        for _, id_track, indice in candidatos:
            if indice in asignacion or id_track in tracks_usados:
                continue
            asignacion[indice] = id_track
            tracks_usados.add(id_track)
        return asignacion
