"""Qué dice el reporte: textos y tablas, sin nada de maquetación. Puro.

Separar el contenido del PDF permite probar lo que el reporte afirma sin leer un PDF.
Todo sale de reglas escritas y archivos de datos: funciona sin internet y sin IA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..nucleo.angulos import AngulosCuerpo
from ..nucleo.intentos import NOMBRE_DE_SEGMENTO, TEXTO_DE_NIVEL, Intento, Visita, sugerir_correcciones
from ..nucleo.mensajes import mensaje_de_puntaje, pista_contextual, seccion_que_significa
from ..nucleo.reba import SEGMENTOS, TOLERANCIA_ERGUIDO
from ..nucleo.recomendaciones import recomendar

TITULO = "Evaluación ergonómica REBA"
MARCA = "SST en vivo · Auren Advisory"
BORRADOR = "Borrador — validar en campo"
# Pie obligatorio del reporte
PIE = ("Estimación automática con visión artificial. Debe ser validada por un profesional de SST. "
       "Método REBA (Hignett & McAtamney, 2000). Torsión e inclinación lateral no evaluadas.")
MAXIMO_DE_INTENTOS_EN_LA_COMPARACION = 3


def numero(valor: float, decimales: int = 1) -> str:
    """Número con coma decimal: 2.0 → "2,0"."""
    return f"{valor:.{decimales}f}".replace(".", ",")


@dataclass(frozen=True)
class DatosReporte:
    """Lo que hace falta para armar el reporte de un intento."""

    reporte_id: str
    fecha: datetime
    intento: Intento
    angulos: AngulosCuerpo  # los del fotograma crítico
    intentos: tuple[Intento, ...] = ()  # todos los de la visita hasta este, en orden
    sesion_id: str | None = None
    neutra: tuple[float, float] | None = None  # postura neutra (tronco, cuello); None = sin calibrar
    peso_carga_kg: float = 5.0
    agarre: str = "bueno"
    ruta_imagen: Path | None = None  # fotograma crítico ya difuminado y con el esqueleto
    tolerancia_erguido: float = TOLERANCIA_ERGUIDO
    ventana_sostenida_s: float = 0.3


@dataclass(frozen=True)
class FilaSegmento:
    nombre: str
    angulo: str  # "102°" o "—"
    puntaje: int | None  # None = no estimado
    nota: str = ""


@dataclass(frozen=True)
class FilaIntento:
    intento: str  # "Intento 2"
    puntaje: int
    nivel: str  # clave del nivel REBA
    espalda: str  # "102°"
    rodillas: str  # "31°" o "—"


@dataclass(frozen=True)
class ContenidoReporte:
    """Todo lo que el reporte dice, listo para maquetar."""

    titulo: str
    marca: str
    reporte_id: str
    subtitulo: str  # visitante e intento
    fecha: str
    puntaje: int
    nivel: str
    etiqueta: str
    mensaje: str  # mensaje principal del nivel
    accion: str
    # (texto, estado) de la espalda y de las rodillas. Estado de la espalda: baja, media o alta.
    # De las rodillas: bien, mal, intermedio o "" si no se midieron
    tecnica: tuple[tuple[str, str], ...]
    condiciones: str
    segmentos: tuple[FilaSegmento, ...]
    calculo: tuple[tuple[str, str], ...]
    significado: dict[str, str]
    recomendaciones: tuple[str, ...]
    notas: tuple[str, ...]
    comparacion: tuple[FilaIntento, ...] = ()
    lectura: str | None = None  # qué cambió respecto al intento anterior
    pista: str | None = None
    pie: str = PIE
    borrador: str = BORRADOR
    ruta_imagen: Path | None = field(default=None, compare=False)


def _fila_segmento(segmento: str, datos: DatosReporte) -> FilaSegmento:
    r = datos.intento.resultado
    puntaje, angulo = r.segmentos.get(segmento), datos.angulos.como_dict().get(segmento)
    if puntaje is None:
        nota = "no estimado: se asume 1" if segmento in r.asumidos else "no estimado"
        return FilaSegmento(NOMBRE_DE_SEGMENTO[segmento], "—", None, nota)
    nota = ""
    if segmento == "muneca":
        nota = "estimación de baja confianza"
    elif segmento == "brazo" and r.ajustes_aplicados:
        nota = "se resta 1: persona inclinada"
    return FilaSegmento(NOMBRE_DE_SEGMENTO[segmento], "—" if angulo is None else f"{angulo:.0f}°", puntaje, nota)


def _notas(datos: DatosReporte) -> tuple[str, ...]:
    """Cómo se midió: lo que el lector necesita para interpretar el puntaje."""
    r = datos.intento.resultado
    notas = [f"Postura erguida con tolerancia de ±{datos.tolerancia_erguido:g}°."]
    if datos.neutra is not None:
        notas.append(f"Tronco y cuello medidos desde la postura de pie de la persona "
                     f"(tronco {datos.neutra[0]:.0f}°, cuello {datos.neutra[1]:.0f}°).")
    else:
        notas.append("Postura de pie sin calibrar: ángulos sin corregir.")
    if "muneca" in r.asumidos:
        notas.append("Muñeca no estimada: se asume el mínimo (1); el puntaje final es una cota inferior.")
    if r.ajustes_aplicados:
        notas.append("Brazo: se resta 1 por persona inclinada con el brazo a favor de la gravedad.")
    notas.append(f"El puntaje es el del fotograma crítico: el mayor sostenido {numero(datos.ventana_sostenida_s)} s "
                 "durante el levantamiento.")
    notas.append("No evaluado y por eso no suma: torsión, inclinación lateral y abducción.")
    return tuple(notas)


def armar_contenido(datos: DatosReporte) -> ContenidoReporte:
    """Arma todo lo que el reporte dice a partir de un intento evaluado."""
    intento, r = datos.intento, datos.intento.resultado
    mensaje = mensaje_de_puntaje(r.puntaje)
    tecnica = intento.tecnica
    intentos = datos.intentos or (intento,)
    varios = len(intentos) > 1

    visitante = f"Visitante {datos.sesion_id}" if datos.sesion_id else "Sin número de visitante"
    altura = {True: " · Carga en el piso", False: " · Carga elevada", None: ""}[intento.desde_piso]
    condiciones = (f"Carga {datos.peso_carga_kg:g} kg · Agarre {datos.agarre} · Lado {datos.angulos.lado} · "
                   f"Duración {numero(intento.duracion_s)} s{altura}")
    calculo = (
        ("Tabla A (cuello, tronco, piernas)", str(r.tabla_a)), ("Carga o fuerza", f"+{r.carga}"),
        ("Puntaje A", str(r.puntaje_a)),
        ("Tabla B (brazo, antebrazo, muñeca)", str(r.tabla_b)), ("Agarre", f"+{r.agarre}"),
        ("Puntaje B", str(r.puntaje_b)),
        ("Tabla C", str(r.tabla_c)), ("Actividad", f"+{r.actividad}"), ("REBA final", str(r.puntaje)),
    )
    comparacion, lectura, anterior = (), None, None
    if varios:
        comparacion = tuple(
            FilaIntento(f"Intento {i.numero}", i.puntaje, i.nivel, f"{i.espalda}°",
                        "—" if i.rodillas is None else f"{i.rodillas}°")
            for i in intentos[-MAXIMO_DE_INTENTOS_EN_LA_COMPARACION:])
        lectura = " ".join(sugerir_correcciones(Visita(datos.sesion_id, list(intentos))))
        anterior = intentos[-2].puntaje

    return ContenidoReporte(
        titulo=TITULO, marca=MARCA, reporte_id=datos.reporte_id,
        subtitulo=f"{visitante} · Intento {intento.numero}",
        fecha=datos.fecha.strftime("%d/%m/%Y %H:%M"),
        puntaje=r.puntaje, nivel=r.nivel, etiqueta=mensaje.etiqueta, mensaje=mensaje.panel, accion=mensaje.accion,
        tecnica=((f"Flexión de espalda {tecnica.texto_espalda()}", tecnica.nivel),
                 (tecnica.texto_piernas(),
                  "" if tecnica.rodillas is None else {True: "bien", False: "mal", None: "intermedio"}[tecnica.piernas_bien])),
        condiciones=condiciones,
        segmentos=tuple(_fila_segmento(segmento, datos) for segmento in SEGMENTOS),
        calculo=calculo,
        significado=seccion_que_significa(r.puntaje, varios_intentos=varios),
        recomendaciones=tuple(recomendar(r)),
        notas=_notas(datos),
        comparacion=comparacion, lectura=lectura,
        pista=pista_contextual(r.puntaje, intento.desde_piso, anterior),
        ruta_imagen=datos.ruta_imagen,
    )


__all__ = ["DatosReporte", "ContenidoReporte", "FilaSegmento", "FilaIntento", "armar_contenido", "PIE", "BORRADOR",
           "TEXTO_DE_NIVEL"]
