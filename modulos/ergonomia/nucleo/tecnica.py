"""Técnica de levantamiento: lo que cambia entre doblar la espalda y usar las piernas.

Por qué existe: REBA mide la carga postural de **todo el cuerpo** y suma puntos por cada
articulación fuera de su posición neutra, también las rodillas. En su tabla A, espalda
doblada con piernas rectas (tronco 4, piernas 1) vale 3, y sentadilla con espalda recta
(tronco 2, piernas 3) vale 4. Es decir, REBA no premia levantar con las piernas: recoger
una caja del piso sale alto de las dos formas. No es un error de medición; es el método.

Este indicador muestra lo que la técnica de levantamiento sí cambia: cuánto se dobla la
espalda y si el esfuerzo lo hacen las piernas. **No es un método de evaluación ni tiene
umbrales propios**: usa las mismas franjas que REBA aplica al tronco (20° y 60°) y a las
rodillas (30° y 60°). Va junto al REBA, no en su lugar. Puro, sin dependencias.
"""

from __future__ import annotations

from dataclasses import dataclass

NIVELES_DE_ESPALDA = ("baja", "media", "alta")
ESTADOS_DE_PIERNAS = ("flexionadas", "poco_flexionadas", "rectas")

TEXTO_DE_ESPALDA = {"baja": "Flexión baja", "media": "Flexión media", "alta": "Flexión alta"}
TEXTO_DE_PIERNAS = {"flexionadas": "flexionadas", "poco_flexionadas": "poco flexionadas", "rectas": "rectas"}


def nivel_de_espalda(flexion_tronco: float) -> str:
    """Franja de flexión del tronco, con los límites de REBA: hasta 20° baja; de 20° a 60°
    media; más de 60° alta. Una extensión de más de 20° cuenta como media, igual que en REBA."""
    if flexion_tronco > 60:
        return "alta"
    if flexion_tronco > 20 or flexion_tronco < -20:
        return "media"
    return "baja"


def estado_de_piernas(flexion_rodilla: float) -> str:
    """Flexión de rodillas, con los límites de REBA: menos de 30° rectas; de 30° a 60° poco
    flexionadas; más de 60° flexionadas."""
    if flexion_rodilla > 60:
        return "flexionadas"
    if flexion_rodilla >= 30:
        return "poco_flexionadas"
    return "rectas"


@dataclass(frozen=True)
class Tecnica:
    """Espalda y rodillas en un momento dado, o en el peor momento de un levantamiento."""

    espalda: float  # flexión del tronco en grados
    rodillas: float | None = None  # flexión de rodillas en grados; None si no se pudo medir

    @property
    def nivel(self) -> str:
        # Con el entero que se muestra: "60°" no puede aparecer a veces como media y a veces como alta
        return nivel_de_espalda(round(self.espalda))

    @property
    def piernas(self) -> str | None:
        return None if self.rodillas is None else estado_de_piernas(round(self.rodillas))

    @property
    def piernas_bien(self) -> bool | None:
        """Lo que enseña la técnica: si hay que agacharse, que flexionen las rodillas.

        True: rodillas flexionadas, o no hacía falta (espalda casi recta). False: espalda
        doblada con las piernas rectas. None: intermedio o sin medir.
        """
        if self.piernas is None:
            return None
        if self.piernas == "flexionadas" or (self.piernas == "rectas" and self.nivel == "baja"):
            return True
        if self.piernas == "rectas":
            return False
        return None

    def texto_espalda(self) -> str:
        return f"{max(0, round(self.espalda))}° · {self.nivel}"

    def texto_piernas(self) -> str:
        if self.rodillas is None:
            return "Rodillas: no estimadas"
        return f"Rodillas {round(self.rodillas)}° · {TEXTO_DE_PIERNAS[self.piernas]}"
