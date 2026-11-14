"""Intentos de una visita y comparación entre el intento anterior y el actual. Puro."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .reba import SEGMENTOS, ResultadoReba
from .tecnica import Tecnica

TEXTO_DE_NIVEL = {"insignificante": "insignificante", "bajo": "bajo", "medio": "medio",
                  "alto": "alto", "muy_alto": "muy alto"}
CAMBIO_MINIMO_DE_ESPALDA = 10  # grados de flexión de espalda para decir que cambió entre intentos
NOMBRE_DE_SEGMENTO = {"tronco": "Tronco", "cuello": "Cuello", "piernas": "Piernas", "brazo": "Brazo",
                      "antebrazo": "Antebrazo", "muneca": "Muñeca"}


def normalizar_sesion(texto: str) -> str | None:
    """Convierte lo tecleado en un ``sesion_id``: "142" → "V-0142". Vacío o sin dígitos → None."""
    digitos = "".join(c for c in texto if c.isdigit())
    return f"V-{int(digitos):04d}" if digitos else None


@dataclass(frozen=True)
class Intento:
    """Un levantamiento evaluado dentro de una visita."""

    numero: int
    resultado: ResultadoReba
    duracion_s: float
    # Mayor flexión de tronco y de rodillas durante el levantamiento. Si faltan, se usan las
    # del fotograma crítico de REBA.
    espalda_max: float | None = None
    rodillas_max: float | None = None
    desde_piso: bool | None = None  # la carga estaba en el piso; None si no se pudo saber

    @property
    def puntaje(self) -> int:
        return self.resultado.puntaje

    @property
    def nivel(self) -> str:
        return self.resultado.nivel

    @property
    def tecnica(self) -> Tecnica:
        """Espalda y rodillas en el peor momento del levantamiento."""
        angulos = self.resultado.angulos
        espalda = self.espalda_max if self.espalda_max is not None else (angulos.get("tronco") or 0.0)
        rodillas = self.rodillas_max if self.rodillas_max is not None else angulos.get("piernas")
        return Tecnica(espalda, rodillas)

    @property
    def espalda(self) -> int:
        """Mayor flexión de espalda del levantamiento, en grados enteros (0 si no hubo flexión)."""
        return max(0, round(self.tecnica.espalda))

    @property
    def rodillas(self) -> int | None:
        """Mayor flexión de rodillas del levantamiento, en grados enteros."""
        return None if self.tecnica.rodillas is None else round(self.tecnica.rodillas)

    def resumen(self) -> str:
        """Por ejemplo "Intento 1: 9 alto"."""
        return f"Intento {self.numero}: {self.puntaje} {TEXTO_DE_NIVEL[self.nivel]}"


@dataclass(frozen=True)
class Comparacion:
    """El intento anterior frente al actual."""

    anterior: Intento
    actual: Intento

    @property
    def diferencia(self) -> int:
        """Negativa si el puntaje bajó (mejoró)."""
        return self.actual.puntaje - self.anterior.puntaje

    @property
    def cambios(self) -> list[tuple[str, int, int]]:
        """Segmentos cuyo puntaje cambió: (segmento, antes, después). Solo los estimados en ambos."""
        antes, despues = self.anterior.resultado.segmentos, self.actual.resultado.segmentos
        return [(s, antes[s], despues[s]) for s in SEGMENTOS
                if antes.get(s) is not None and despues.get(s) is not None and antes[s] != despues[s]]

    @property
    def diferencia_espalda(self) -> int:
        """Grados de flexión de espalda de diferencia; negativa si se dobló menos."""
        return self.actual.espalda - self.anterior.espalda

    @property
    def piernas_cargan_mas(self) -> bool:
        """El puntaje de piernas subió: la espalda se cuidó a costa de flexionar las rodillas."""
        antes, despues = (i.resultado.segmentos.get("piernas") for i in (self.anterior, self.actual))
        return antes is not None and despues is not None and despues > antes

    def texto_espalda(self) -> str:
        """Por ejemplo "Flexión de espalda: 99° → 56°"."""
        return f"Flexión de espalda: {self.anterior.espalda}° → {self.actual.espalda}°"

    def texto_rodillas(self) -> str:
        """Por ejemplo "Rodillas: 23° → 145°". Vacío si alguna no se pudo medir."""
        if self.anterior.rodillas is None or self.actual.rodillas is None:
            return ""
        return f"Rodillas: {self.anterior.rodillas}° → {self.actual.rodillas}°"

    def texto(self) -> str:
        """Por ejemplo "Intento 1: 9 alto → Intento 2: 4 medio"."""
        return f"{self.anterior.resumen()} → {self.actual.resumen()}"

    def texto_cambios(self) -> str:
        """Por ejemplo "Tronco 4 → 3 · Piernas 1 → 3". Vacío si ningún segmento cambió."""
        return " · ".join(f"{NOMBRE_DE_SEGMENTO[s]} {a} → {d}" for s, a, d in self.cambios)


@dataclass
class Visita:
    """Lo que hace un visitante en la estación: su número (opcional) y sus intentos."""

    sesion_id: str | None = None
    intentos: list[Intento] = field(default_factory=list)
    # Código al azar de la visita: identifica sus reportes cuando no se tecleó el número de visitante
    codigo: str = field(default_factory=lambda: uuid.uuid4().hex[:6].upper(), compare=False)

    def registrar(self, resultado: ResultadoReba, duracion_s: float, espalda_max: float | None = None,
                  rodillas_max: float | None = None, desde_piso: bool | None = None) -> Intento:
        """Agrega un intento evaluado (con REBA completo) y lo devuelve numerado."""
        if not resultado.completo:
            raise ValueError("solo se registran intentos con REBA completo")
        intento = Intento(len(self.intentos) + 1, resultado, duracion_s, espalda_max, rodillas_max, desde_piso)
        self.intentos.append(intento)
        return intento

    @property
    def ultimo(self) -> Intento | None:
        return self.intentos[-1] if self.intentos else None

    def comparacion(self) -> Comparacion | None:
        """El intento anterior frente al actual; None si hay menos de dos."""
        if len(self.intentos) < 2:
            return None
        return Comparacion(self.intentos[-2], self.intentos[-1])

    @property
    def vacia(self) -> bool:
        return self.sesion_id is None and not self.intentos


def sugerir_correcciones(visita: Visita) -> list[str]:
    """Qué corregir tras el último intento de la visita, según la técnica (espalda y rodillas).

    Con un solo intento habla de ese intento; con dos o más, de lo que cambió respecto al
    anterior. Describe la postura, no regaña a la persona, y no promete lo que REBA no dice:
    si la espalda mejoró pero el puntaje no bajó, lo dice. Lista vacía si no hay intentos.
    """
    ultimo = visita.ultimo
    if ultimo is None:
        return []
    comparacion = visita.comparacion()
    if comparacion is None:
        tecnica = ultimo.tecnica
        if tecnica.nivel == "alta":
            return [f"Espalda doblada {ultimo.espalda}°. En el siguiente intento, flexiona las rodillas"]
        if tecnica.nivel == "media":
            if tecnica.piernas_bien:
                return [f"Las piernas hicieron el esfuerzo. Espalda a {ultimo.espalda}°: intenta mantenerla más recta"]
            return [f"Espalda inclinada {ultimo.espalda}°. En el siguiente intento, flexiona más las rodillas"]
        return ["Espalda recta: buena técnica"]
    grados = -comparacion.diferencia_espalda
    if grados >= CAMBIO_MINIMO_DE_ESPALDA:
        if comparacion.diferencia < 0:
            return [f"Espalda {grados}° más recta y REBA más bajo"]
        if comparacion.piernas_cargan_mas:
            return [f"Espalda {grados}° más recta. REBA no baja: ahora cargan las rodillas"]
        return [f"Espalda {grados}° más recta. Mira qué segmentos cambiaron"]
    if grados <= -CAMBIO_MINIMO_DE_ESPALDA:
        return ["La espalda se dobló más esta vez. Inténtalo de nuevo"]
    if comparacion.actual.tecnica.piernas == "flexionadas":
        # Ya flexiona las rodillas: no tiene sentido pedírselo
        return ["Espalda parecida al intento anterior. Mantén la carga cerca del cuerpo"]
    return ["Espalda parecida. Flexiona las rodillas y acerca la caja"]
