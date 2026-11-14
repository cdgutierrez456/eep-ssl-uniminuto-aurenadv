"""Imagen del inspector: leer la foto, ajustarla al tamaño del modelo, difuminar y anotar.

Orden obligatorio: primero se difuminan los rostros y después se dibujan las cajas. La
foto original nunca se guarda: lo que sale de ``preparar_foto`` ya va difuminado y es lo
único que se envía al modelo, se escribe en disco o se sube.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from modulos.comun import difuminar_rostros

# Un token visual es un parche de 28 x 28 píxeles. Los modelos actuales procesan hasta
# 2576 px de lado largo y 4784 tokens por imagen; lo que pase de ahí lo reducen ellos, y
# entonces las cajas que devuelven dejan de coincidir con la imagen enviada. Por eso la
# imagen se reduce aquí, antes de enviarla.
PARCHE_PX = 28
LADO_MAX_POR_DEFECTO = 1568
LADO_MAX_ALTA_RESOLUCION = 2576
TOKENS_MAX_DEL_MODELO = 4784
LADO_MINIMO = 200  # por debajo de esto el modelo interpreta mal la imagen

# Marca Auren, en BGR
AUREN_DEEP = (59, 52, 18)      # #12343B
AUREN_BLACK = (20, 20, 17)     # #111414
MARFIL = (234, 241, 242)       # #F2F1EA
LIMA = (105, 241, 200)         # #C8F169


class ImagenInvalida(ValueError):
    """El archivo recibido no es una imagen que se pueda analizar."""


# --------------------------------------------------------------------------- #
# Tamaño
# --------------------------------------------------------------------------- #
def tokens_de_imagen(ancho: int, alto: int) -> int:
    """Tokens visuales que consume una imagen: un token por cada parche de 28 x 28 px."""
    return math.ceil(ancho / PARCHE_PX) * math.ceil(alto / PARCHE_PX)


def tamano_para_enviar(ancho: int, alto: int, lado_max: int = LADO_MAX_POR_DEFECTO,
                       tokens_max: int = TOKENS_MAX_DEL_MODELO) -> tuple[int, int]:
    """Mayor tamaño con la misma proporción que cabe en el lado y en los tokens máximos.

    Sigue el cálculo de referencia de la documentación de visión de Anthropic. Una imagen
    que ya cabe se devuelve igual: nunca se agranda.
    """
    def cabe(w: int, h: int) -> bool:
        return (math.ceil(w / PARCHE_PX) * PARCHE_PX <= lado_max
                and math.ceil(h / PARCHE_PX) * PARCHE_PX <= lado_max
                and tokens_de_imagen(w, h) <= tokens_max)

    if cabe(ancho, alto):
        return ancho, alto
    if alto > ancho:
        alto_nuevo, ancho_nuevo = tamano_para_enviar(alto, ancho, lado_max, tokens_max)
        return ancho_nuevo, alto_nuevo

    # Búsqueda binaria sobre el lado largo: 'cabe' siempre cabe y 'no_cabe' nunca
    proporcion = ancho / alto
    cabe_en, no_cabe_en = 1, ancho
    while cabe_en + 1 < no_cabe_en:
        medio = (cabe_en + no_cabe_en) // 2
        if cabe(medio, max(round(medio / proporcion), 1)):
            cabe_en = medio
        else:
            no_cabe_en = medio
    return cabe_en, max(round(cabe_en / proporcion), 1)


def redimensionar(frame: np.ndarray, lado_max: int = LADO_MAX_POR_DEFECTO,
                  tokens_max: int = TOKENS_MAX_DEL_MODELO) -> np.ndarray:
    """Reduce el frame al tamaño que se envía al modelo. Si ya cabe, lo devuelve igual."""
    alto, ancho = frame.shape[:2]
    ancho_nuevo, alto_nuevo = tamano_para_enviar(ancho, alto, lado_max, tokens_max)
    if (ancho_nuevo, alto_nuevo) == (ancho, alto):
        return frame
    return cv2.resize(frame, (ancho_nuevo, alto_nuevo), interpolation=cv2.INTER_AREA)


# --------------------------------------------------------------------------- #
# Lectura y escritura
# --------------------------------------------------------------------------- #
def decodificar(datos: bytes) -> np.ndarray:
    """Bytes de una foto (JPEG, PNG, WebP…) -> frame BGR, ya girado según su orientación EXIF.

    Las fotos de tablet y celular suelen venir "acostadas" con la orientación en los
    metadatos; sin aplicarla, la imagen llegaría girada al modelo.
    """
    try:
        with Image.open(io.BytesIO(datos)) as imagen:
            imagen = ImageOps.exif_transpose(imagen).convert("RGB")
            rgb = np.asarray(imagen)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise ImagenInvalida("No se pudo leer la imagen. Usa una foto en JPEG o PNG.") from error
    if min(rgb.shape[:2]) < LADO_MINIMO:
        raise ImagenInvalida(f"La imagen es muy pequeña: cada lado debe medir al menos {LADO_MINIMO} px.")
    return np.ascontiguousarray(rgb[:, :, ::-1])


def preparar_foto(datos: bytes, lado_max: int = LADO_MAX_POR_DEFECTO) -> np.ndarray:
    """Foto recibida -> imagen lista para enviar al modelo: orientada, difuminada y reducida.

    Los rostros se buscan sobre la imagen a (como mucho) la resolución alta del modelo,
    donde las caras pequeñas todavía se detectan, y después se reduce a ``lado_max``.
    """
    frame = redimensionar(decodificar(datos), LADO_MAX_ALTA_RESOLUCION)
    frame = difuminar_rostros(frame)
    return redimensionar(frame, lado_max)


def codificar_jpeg(frame: np.ndarray, calidad: int = 90) -> bytes:
    """Frame BGR -> bytes JPEG."""
    correcto, datos = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, calidad])
    if not correcto:
        raise ValueError("No se pudo codificar la imagen como JPEG")
    return datos.tobytes()


def guardar_jpeg(frame: np.ndarray, ruta: str | Path, calidad: int = 90) -> Path:
    """Escribe el frame como JPEG. El frame debe venir ya difuminado.

    No usa ``cv2.imwrite`` porque en Windows falla con rutas que llevan tildes.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(codificar_jpeg(frame, calidad))
    return ruta


def miniatura(frame: np.ndarray, ancho_max: int, alto_max: int) -> np.ndarray:
    """Copia reducida del frame que cabe en ``ancho_max`` x ``alto_max``, sin agrandar."""
    alto, ancho = frame.shape[:2]
    escala = min(ancho_max / ancho, alto_max / alto, 1.0)
    if escala >= 1.0:
        return frame.copy()
    tamano = (max(1, round(ancho * escala)), max(1, round(alto * escala)))
    return cv2.resize(frame, tamano, interpolation=cv2.INTER_AREA)


# --------------------------------------------------------------------------- #
# Anotación
# --------------------------------------------------------------------------- #
def anotar(frame: np.ndarray, peligros: list[dict]) -> np.ndarray:
    """Devuelve una copia del frame con la caja numerada de cada peligro.

    ``frame`` debe venir ya difuminado: las cajas se dibujan siempre después. Cada peligro
    aporta ``n`` y ``ubicacion`` ([x1, y1, x2, y2] de 0 a 1). Los de confianza baja llevan
    la caja punteada: son "posibles, por verificar".
    """
    salida = frame.copy()
    alto, ancho = salida.shape[:2]
    grosor = max(2, round(max(ancho, alto) / 500))
    lado_etiqueta = max(26, round(max(ancho, alto) / 34))

    cajas = []
    for peligro in peligros:
        x1, y1, x2, y2 = peligro["ubicacion"]
        cajas.append((peligro, (round(x1 * (ancho - 1)), round(y1 * (alto - 1)),
                                round(x2 * (ancho - 1)), round(y2 * (alto - 1)))))

    # Primero todas las cajas y después todas las etiquetas, para que ningún borde tape un número
    for peligro, (x1, y1, x2, y2) in cajas:
        punteada = peligro.get("confianza") == "baja"
        _rectangulo(salida, (x1, y1), (x2, y2), AUREN_BLACK, grosor + 2, punteada)
        _rectangulo(salida, (x1, y1), (x2, y2), LIMA, grosor, punteada)
    ocupadas: list[tuple[int, int, int, int]] = []
    for peligro, (x1, y1, _, _) in cajas:
        ocupadas.append(_etiqueta(salida, str(peligro["n"]), x1, y1, lado_etiqueta, ocupadas))
    return salida


def _rectangulo(imagen: np.ndarray, p1: tuple[int, int], p2: tuple[int, int], color: tuple[int, int, int],
                grosor: int, punteado: bool) -> None:
    if not punteado:
        cv2.rectangle(imagen, p1, p2, color, grosor, cv2.LINE_AA)
        return
    (x1, y1), (x2, y2) = p1, p2
    for inicio, fin in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))):
        _linea_punteada(imagen, inicio, fin, color, grosor)


def _linea_punteada(imagen: np.ndarray, inicio: tuple[int, int], fin: tuple[int, int],
                    color: tuple[int, int, int], grosor: int) -> None:
    largo = math.hypot(fin[0] - inicio[0], fin[1] - inicio[1])
    trazo = max(8, grosor * 5)
    pasos = max(1, int(largo // (trazo * 2)))
    for paso in range(pasos + 1):
        desde = min(paso * trazo * 2 / max(largo, 1), 1.0)
        hasta = min((paso * trazo * 2 + trazo) / max(largo, 1), 1.0)
        a = (round(inicio[0] + (fin[0] - inicio[0]) * desde), round(inicio[1] + (fin[1] - inicio[1]) * desde))
        b = (round(inicio[0] + (fin[0] - inicio[0]) * hasta), round(inicio[1] + (fin[1] - inicio[1]) * hasta))
        cv2.line(imagen, a, b, color, grosor, cv2.LINE_AA)


def _etiqueta(imagen: np.ndarray, texto: str, x: int, y: int, lado: int,
              ocupadas: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    """Recuadro Auren Deep con el número en marfil, en la esquina superior izquierda de la caja.

    Si ahí ya hay otra etiqueta (dos cajas que empiezan en el mismo punto), se corre a la
    derecha hasta quedar libre. Devuelve el rectángulo que ocupó.
    """
    alto, ancho = imagen.shape[:2]
    fuente = cv2.FONT_HERSHEY_DUPLEX
    escala = lado / 44
    grosor_texto = max(1, round(lado / 18))
    (ancho_texto, alto_texto), _ = cv2.getTextSize(texto, fuente, escala, grosor_texto)
    ancho_etiqueta = max(lado, ancho_texto + lado // 2)
    x = min(max(x, 0), max(ancho - ancho_etiqueta, 0))
    y = min(max(y, 0), max(alto - lado, 0))
    for _ in range(len(ocupadas)):
        if not any(x < ox2 and ox1 < x + ancho_etiqueta and y < oy2 and oy1 < y + lado
                   for ox1, oy1, ox2, oy2 in ocupadas):
            break
        x += ancho_etiqueta + 2
        if x + ancho_etiqueta > ancho:  # no cabe más a la derecha: baja una fila
            x, y = max(ancho - ancho_etiqueta, 0), min(y + lado + 2, max(alto - lado, 0))
    cv2.rectangle(imagen, (x, y), (x + ancho_etiqueta, y + lado), AUREN_DEEP, cv2.FILLED)
    cv2.rectangle(imagen, (x, y), (x + ancho_etiqueta, y + lado), LIMA, max(1, lado // 16), cv2.LINE_AA)
    origen = (x + (ancho_etiqueta - ancho_texto) // 2, y + (lado + alto_texto) // 2)
    cv2.putText(imagen, texto, origen, fuente, escala, MARFIL, grosor_texto, cv2.LINE_AA)
    return x, y, x + ancho_etiqueta, y + lado
