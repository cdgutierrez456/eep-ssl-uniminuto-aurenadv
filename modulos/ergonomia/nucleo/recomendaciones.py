"""Recomendaciones del reporte, por reglas escritas: sin IA y sin internet.

Parten de los segmentos con mayor puntaje REBA del fotograma crítico. Las reglas y los
textos viven en ``recomendaciones.json``. Puro, sin dependencias.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .reba import ResultadoReba

RUTA_RECOMENDACIONES = Path(__file__).with_name("recomendaciones.json")
MINIMO, MAXIMO = 2, 4


@lru_cache(maxsize=1)
def cargar_reglas() -> dict:
    """Lee las reglas del archivo de datos (una sola vez)."""
    return json.loads(RUTA_RECOMENDACIONES.read_text(encoding="utf-8"))


def _regla(reglas: list[dict], puntaje: int | None, clave: str = "texto") -> str | None:
    """Texto de la regla de mayor ``desde`` que el puntaje alcanza; None si ninguna aplica.

    ``clave`` permite pedir una variante del texto; si la regla no la trae, se usa ``texto``.
    """
    if puntaje is None:
        return None
    aplicables = [regla for regla in reglas if puntaje >= regla["desde"]]
    if not aplicables:
        return None
    regla = max(aplicables, key=lambda regla: regla["desde"])
    return regla.get(clave, regla["texto"])


def recomendar(resultado: ResultadoReba, minimo: int = MINIMO, maximo: int = MAXIMO) -> list[str]:
    """Entre ``minimo`` y ``maximo`` recomendaciones para un resultado REBA.

    Primero las de la carga y el agarre, si aplican: cambiar la tarea reduce el riesgo más
    que la técnica. Después las de los segmentos, del puntaje más alto al más bajo; en
    empate manda el orden del archivo (tronco, piernas, brazo, cuello, muñeca, antebrazo).
    Si no se llega al mínimo, se completa con recomendaciones generales. Un segmento no
    estimado no genera recomendación.
    """
    reglas = cargar_reglas()
    elegidas = [texto for texto in (_regla(reglas["carga"], resultado.carga),
                                    _regla(reglas["agarre"], resultado.agarre)) if texto]
    orden = list(reglas["segmentos"])
    por_puntaje = sorted((segmento for segmento in orden if resultado.segmentos.get(segmento) is not None),
                         key=lambda segmento: (-resultado.segmentos[segmento], orden.index(segmento)))
    rodillas_flexionadas = (resultado.segmentos.get("piernas") or 0) >= 3
    for segmento in por_puntaje:
        clave = "texto_con_rodillas_flexionadas" if segmento == "tronco" and rodillas_flexionadas else "texto"
        texto = _regla(reglas["segmentos"][segmento], resultado.segmentos[segmento], clave)
        if texto:
            elegidas.append(texto)
    elegidas = elegidas[:maximo]
    for general in reglas["generales"]:
        if len(elegidas) >= minimo:
            break
        elegidas.append(general)
    return elegidas
