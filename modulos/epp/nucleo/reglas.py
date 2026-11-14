"""Reglas de veredicto EPP como funciones puras.

Copia adaptada del motor del proyecto de EPP para alimentos (vision/nucleo/reglas.py).
No depende de Ultralytics, OpenCV ni numpy: trabaja solo con listas y diccionarios,
para que la misma lógica pueda reimplementarse en Dart y dar resultados idénticos.

Cambio frente al original: la asociación ya no usa una única «franja superior», sino
una **zona vertical por elemento** ``[inicio, fin]`` (fracciones de la altura de la
persona, 0 = arriba). El casco se busca en la cabeza y el chaleco en el torso. Con
todas las zonas en ``[0, 0.625]`` el resultado es idéntico al del motor original:
``adaptar_reglas_antiguas`` convierte el formato viejo y los casos dorados originales
siguen pasando (pruebas/epp/).

Entrada: lista de detecciones normalizadas ``{"clase": str, "confianza": float,
"caja": [x1, y1, x2, y2]}`` con coordenadas en ``[0, 1]`` y las reglas del perfil
(ver ``perfiles.reglas_de_perfil``).

Salida: ``{"personas": [...], "resumen": {...}}``.

Convenciones de determinismo:
- Nada se redondea; todas las comparaciones son inclusivas (``>=``, ``<=``).
- El orden de cálculo de ``cx``, ``cy``, límites de zona, ``area`` e ``iou`` es fijo.
- El orden de las personas es total (``cx``, ``cy``, ``x2``, ``y2``, confianza desc.).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

Caja = list[float]
Deteccion = dict[str, Any]
Reglas = dict[str, Any]

EVIDENCIA_POSITIVO = "positivo"
EVIDENCIA_NEGATIVO = "negativo"
EVIDENCIA_DESCONOCIDO = "desconocido"

MODO_AUTO = "auto"
MODO_SIEMPRE = "siempre"
MODO_NUNCA = "nunca"


# --------------------------------------------------------------------------- #
# Carga y versionado de reglas
# --------------------------------------------------------------------------- #
def cargar_reglas(ruta: str | Path) -> Reglas:
    """Carga el archivo de reglas (JSON, UTF-8) y devuelve el diccionario."""
    with open(ruta, "rb") as archivo:
        return json.loads(archivo.read().decode("utf-8"))


def adaptar_reglas_antiguas(reglas: Reglas) -> Reglas:
    """Convierte reglas del formato original (una sola franja) al formato por zonas.

    Cada elemento recibe la zona ``[0, franja_superior]`` y el primer plano la zona
    ``[0, primer_plano.franja_superior]``. Si las reglas ya traen ``zonas`` se devuelven
    sin cambios. No modifica la entrada.
    """
    if "zonas" in reglas:
        return reglas
    nuevas = json.loads(json.dumps(reglas))
    franja = nuevas.pop("asociacion")["franja_superior"]
    elementos = list(nuevas["elementos_requeridos"])
    elementos += [e for e in nuevas["clases_negativas"] if e not in elementos]
    nuevas["zonas"] = {elemento: [0.0, franja] for elemento in elementos}
    primer_plano = nuevas["primer_plano"]
    primer_plano["zona"] = [0.0, primer_plano.pop("franja_superior")]
    return nuevas


def clases_conocidas(reglas: Reglas) -> list[str]:
    """Lista ordenada de clases que el contrato reconoce (persona, elementos, negativas)."""
    clases = [reglas["clase_persona"]]
    for elemento in reglas["elementos_requeridos"]:
        clases.append(elemento)
    for elemento in reglas["elementos_requeridos"]:
        negativa = reglas["clases_negativas"].get(elemento)
        if negativa is not None:
            clases.append(negativa)
    # También se admiten elementos del mapa de negativas que no sean requeridos
    # (p. ej. una planta que no exige gafas pero el modelo sí las detecta).
    for elemento, negativa in reglas["clases_negativas"].items():
        if elemento not in clases:
            clases.append(elemento)
        if negativa not in clases:
            clases.append(negativa)
    return clases


# --------------------------------------------------------------------------- #
# Geometría (orden de cálculo fijo)
# --------------------------------------------------------------------------- #
def centro(caja: Caja) -> tuple[float, float]:
    """Centro de la caja: ``cx = (x1 + x2) / 2``, ``cy = (y1 + y2) / 2``."""
    return (caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2


def area(caja: Caja) -> float:
    """Área de la caja: ``(x2 - x1) * (y2 - y1)``."""
    return (caja[2] - caja[0]) * (caja[3] - caja[1])


def iou(a: Caja, b: Caja) -> float:
    """Intersección sobre unión de dos cajas ``[x1, y1, x2, y2]``.

    ``inter = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))``
    ``iou = inter / (area_a + area_b - inter)``; devuelve 0 si la unión es 0.
    """
    ancho = min(a[2], b[2]) - max(a[0], b[0])
    alto = min(a[3], b[3]) - max(a[1], b[1])
    if ancho <= 0 or alto <= 0:
        return 0.0
    inter = ancho * alto
    union = area(a) + area(b) - inter
    if union <= 0:
        return 0.0
    return inter / union


ZONA_COMPLETA: list[float] = [0.0, 1.0]


def limites_zona(caja_persona: Caja, zona: list[float]) -> tuple[float, float]:
    """Coordenadas ``y`` de la zona: ``y1 + inicio * (y2 - y1)`` y ``y1 + fin * (y2 - y1)``."""
    alto = caja_persona[3] - caja_persona[1]
    return caja_persona[1] + zona[0] * alto, caja_persona[1] + zona[1] * alto


def centro_en_zona(caja_persona: Caja, punto: tuple[float, float], zona: list[float]) -> bool:
    """``True`` si el punto cae dentro de la caja y en la zona vertical dada (inclusivo)."""
    cx, cy = punto
    if not (caja_persona[0] <= cx <= caja_persona[2]):
        return False
    arriba, abajo = limites_zona(caja_persona, zona)
    return arriba <= cy <= abajo


def zonas_por_clase(zonas: dict[str, list[float]], clases_negativas: dict[str, str]) -> dict[str, list[float]]:
    """Zona aplicable a cada clase: la del elemento, compartida con su clase negativa."""
    mapa = {elemento: list(zona) for elemento, zona in zonas.items()}
    for elemento, negativa in clases_negativas.items():
        if elemento in mapa:
            mapa[negativa] = mapa[elemento]
    return mapa


# --------------------------------------------------------------------------- #
# Normalización y filtrado
# --------------------------------------------------------------------------- #
def _es_finito(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


def _recortar(valor: float) -> float:
    """Recorta un valor al rango ``[0, 1]``."""
    if valor < 0.0:
        return 0.0
    if valor > 1.0:
        return 1.0
    return valor


def normalizar_detecciones(detecciones: Iterable[Deteccion], conocidas: Iterable[str]) -> list[Deteccion]:
    """Aplica la *entrada canónica* del contrato.

    - Ignora clases desconocidas y detecciones mal formadas.
    - Descarta confianzas no finitas o fuera de ``[0, 1]``.
    - Recorta las coordenadas a ``[0, 1]`` y DESPUÉS exige ``x2 > x1`` y ``y2 > y1``.

    Devuelve copias nuevas; nunca modifica la entrada.
    """
    conjunto = set(conocidas)
    salida: list[Deteccion] = []
    for det in detecciones:
        if not isinstance(det, dict):
            continue
        clase = det.get("clase")
        confianza = det.get("confianza")
        caja = det.get("caja")
        if not isinstance(clase, str) or clase not in conjunto or not _es_finito(confianza):
            continue
        if confianza < 0.0 or confianza > 1.0:
            continue
        if not isinstance(caja, (list, tuple)) or len(caja) != 4 or not all(_es_finito(v) for v in caja):
            continue
        recortada = [_recortar(float(v)) for v in caja]
        if recortada[2] <= recortada[0] or recortada[3] <= recortada[1]:
            continue
        salida.append({"clase": clase, "confianza": float(confianza), "caja": recortada})
    return salida


def filtrar_por_umbral(detecciones: Iterable[Deteccion], umbrales: dict[str, float]) -> list[Deteccion]:
    """Conserva las detecciones con ``confianza >= umbral`` de su clase (inclusivo).

    Una clase sin umbral configurado se descarta (no hay regla para ella).
    """
    salida: list[Deteccion] = []
    for det in detecciones:
        umbral = umbrales.get(det["clase"])
        if umbral is not None and det["confianza"] >= umbral:
            salida.append(det)
    return salida


# --------------------------------------------------------------------------- #
# Orden total y asociación
# --------------------------------------------------------------------------- #
def clave_orden(persona: Deteccion) -> tuple[float, float, float, float, float]:
    """Clave del orden total de personas: ``cx, cy, x2, y2, -confianza``."""
    cx, cy = centro(persona["caja"])
    return (cx, cy, persona["caja"][2], persona["caja"][3], -persona["confianza"])


def ordenar_personas(personas: list[Deteccion]) -> list[Deteccion]:
    """Devuelve las personas en el orden total del contrato."""
    return sorted(personas, key=clave_orden)


def asociar_elementos_a_personas(
    elementos: list[Deteccion], personas: list[Deteccion], zonas: list[dict[str, list[float]] | list[float]]
) -> list[list[Deteccion]]:
    """Asigna cada detección de elemento/negativa a UNA sola persona.

    Para cada elemento se consideran las personas en cuya zona (la de ese elemento)
    cae su centro; se elige la de menor área y, en empate, la primera en el orden total
    (``personas`` ya debe venir ordenada). Un elemento que no cae en ninguna queda
    sin asociar.

    ``zonas[i]`` son las zonas aplicables a ``personas[i]``: un mapa clase -> zona
    (una clase sin zona usa la persona completa) o una sola zona para todas las clases
    (la persona inferida del modo primer plano).
    """
    asociadas: list[list[Deteccion]] = [[] for _ in personas]
    for elemento in elementos:
        punto = centro(elemento["caja"])
        mejor_indice = -1
        mejor_area = math.inf
        for indice, persona in enumerate(personas):
            zona = zonas[indice]
            if isinstance(zona, dict):
                zona = zona.get(elemento["clase"], ZONA_COMPLETA)
            if not centro_en_zona(persona["caja"], punto, zona):
                continue
            area_persona = area(persona["caja"])
            # Estrictamente menor: en empate se conserva la primera (orden total).
            if area_persona < mejor_area:
                mejor_area = area_persona
                mejor_indice = indice
        if mejor_indice >= 0:
            asociadas[mejor_indice].append(elemento)
    return asociadas


def evidencia_por_elemento(asociadas: list[Deteccion], elementos_requeridos: list[str],
                           clases_negativas: dict[str, str]) -> dict[str, str]:
    """Reduce las detecciones asociadas a una persona a evidencia tri-estado.

    ``negativo`` si hay al menos una negativa del elemento; si no, ``positivo`` si
    hay al menos una positiva; si no, ``desconocido``. La negativa gana (criterio
    conservador).
    """
    clases_presentes = {det["clase"] for det in asociadas}
    evidencia: dict[str, str] = {}
    for elemento in elementos_requeridos:
        negativa = clases_negativas.get(elemento)
        if negativa is not None and negativa in clases_presentes:
            evidencia[elemento] = EVIDENCIA_NEGATIVO
        elif elemento in clases_presentes:
            evidencia[elemento] = EVIDENCIA_POSITIVO
        else:
            evidencia[elemento] = EVIDENCIA_DESCONOCIDO
    return evidencia


# --------------------------------------------------------------------------- #
# Construcción de la salida
# --------------------------------------------------------------------------- #
def construir_persona(identificador: int, caja: Caja, inferida: bool,
                      evidencia: dict[str, str], elementos_requeridos: list[str]) -> dict[str, Any]:
    """Arma el objeto ``persona`` del contrato a partir de su evidencia."""
    elementos = {e: evidencia[e] == EVIDENCIA_POSITIVO for e in elementos_requeridos}
    return completar_persona(
        {"id": identificador, "caja": list(caja), "inferida": inferida,
         "elementos": elementos, "evidencia": {e: evidencia[e] for e in elementos_requeridos}},
        elementos_requeridos,
    )


def completar_persona(persona: dict[str, Any], elementos_requeridos: list[str]) -> dict[str, Any]:
    """Recalcula ``faltantes`` y ``cumple`` a partir de ``persona["elementos"]``.

    Es la única función que deriva el veredicto de los booleanos; la usa tanto la
    evaluación de imagen única como el suavizado temporal.
    """
    faltantes = [e for e in elementos_requeridos if not persona["elementos"][e]]
    persona["faltantes"] = faltantes
    persona["cumple"] = len(faltantes) == 0
    return persona


def calcular_resumen(personas: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumen del cuadro calculado solo sobre las personas de la respuesta."""
    cumplen = sum(1 for p in personas if p["cumple"])
    total = len(personas)
    return {
        "personas": total,
        "cumplen": cumplen,
        "no_cumplen": total - cumplen,
        "cumple_global": total > 0 and cumplen == total,
    }


# --------------------------------------------------------------------------- #
# Evaluación de un cuadro
# --------------------------------------------------------------------------- #
def evaluar_cuadro(detecciones: Iterable[Deteccion], reglas: Reglas) -> dict[str, Any]:
    """Evalúa un cuadro completo y devuelve ``{"personas": [...], "resumen": {...}}``.

    Pasos (en este orden):
    1. Entrada canónica (``normalizar_detecciones``).
    2. Filtro por umbral de confianza por clase.
    3. Separación en personas y elementos/negativas; orden total de personas.
    4. Modo primer plano (``auto`` | ``siempre`` | ``nunca``).
    5. Asociación uno-a-uno de elementos a personas, con la zona de cada elemento.
    6. Evidencia tri-estado y veredicto por persona; resumen.
    """
    clase_persona: str = reglas["clase_persona"]
    requeridos: list[str] = list(reglas["elementos_requeridos"])
    negativas: dict[str, str] = dict(reglas["clases_negativas"])
    zonas_normales = zonas_por_clase(reglas["zonas"], negativas)
    config_pp = reglas["primer_plano"]

    validas = normalizar_detecciones(detecciones, clases_conocidas(reglas))
    sobre_umbral = filtrar_por_umbral(validas, reglas["umbral_confianza"])

    personas_det = ordenar_personas([d for d in sobre_umbral if d["clase"] == clase_persona])
    elementos_det = [d for d in sobre_umbral if d["clase"] != clase_persona]

    # Modo primer plano: decide la lista de personas a evaluar y sus zonas.
    modo = config_pp["modo"]
    inferidas: list[bool]
    zonas: list[Any]
    if modo == MODO_SIEMPRE:
        personas_eval = [_persona_virtual(config_pp)]
        inferidas, zonas = [True], [list(config_pp["zona"])]
    elif modo == MODO_AUTO and not personas_det and len(elementos_det) >= config_pp["minimo_evidencias"]:
        personas_eval = [_persona_virtual(config_pp)]
        inferidas, zonas = [True], [list(config_pp["zona"])]
    else:
        personas_eval = personas_det
        inferidas = [False] * len(personas_eval)
        zonas = [zonas_normales] * len(personas_eval)

    asociadas = asociar_elementos_a_personas(elementos_det, personas_eval, zonas)

    personas_salida: list[dict[str, Any]] = []
    for indice, persona in enumerate(personas_eval):
        evidencia = evidencia_por_elemento(asociadas[indice], requeridos, negativas)
        personas_salida.append(
            construir_persona(indice + 1, persona["caja"], inferidas[indice], evidencia, requeridos)
        )

    return {"personas": personas_salida, "resumen": calcular_resumen(personas_salida)}


def _persona_virtual(config_pp: dict[str, Any]) -> Deteccion:
    """Persona inferida que ocupa la caja virtual del modo primer plano."""
    return {"clase": config_pp.get("clase_persona", "persona"), "confianza": 1.0, "caja": [float(v) for v in config_pp["caja_virtual"]]}
