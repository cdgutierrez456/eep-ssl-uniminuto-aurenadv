"""Imagen del inspector: tamaño para el modelo, lectura con orientación, difuminado y anotación."""

import io

import cv2
import numpy as np
import pytest
from PIL import Image

from modulos.inspector.nucleo import imagen as modulo_imagen
from modulos.inspector.nucleo.imagen import (
    AUREN_DEEP,
    LIMA,
    ImagenInvalida,
    anotar,
    codificar_jpeg,
    decodificar,
    guardar_jpeg,
    miniatura,
    preparar_foto,
    redimensionar,
    tamano_para_enviar,
    tokens_de_imagen,
)

GRIS = (120, 120, 120)


def lienzo(ancho: int = 800, alto: int = 600) -> np.ndarray:
    return np.full((alto, ancho, 3), GRIS, np.uint8)


def foto_en_bytes(ancho: int, alto: int, formato: str = "JPEG", orientacion: int | None = None) -> bytes:
    """Foto de prueba con la mitad izquierda roja, para reconocer hacia dónde quedó girada."""
    foto = Image.new("RGB", (ancho, alto), (40, 40, 40))
    foto.paste((220, 30, 30), (0, 0, ancho // 2, alto))
    salida = io.BytesIO()
    if orientacion is None:
        foto.save(salida, formato)
    else:
        exif = Image.Exif()
        exif[0x0112] = orientacion
        foto.save(salida, formato, exif=exif)
    return salida.getvalue()


def pixeles_de_color(frame: np.ndarray, color: tuple[int, int, int], tolerancia: int = 12) -> int:
    return int(np.all(np.abs(frame.astype(int) - np.array(color)) <= tolerancia, axis=2).sum())


# --------------------------------------------------------------------------- #
# Tamaño para enviar al modelo
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ancho, alto, lado_max, tokens_max, esperado",
    [
        # Ejemplos de la documentación de visión de Anthropic
        (1075, 1520, 1568, 1568, (924, 1307)),
        (1920, 1080, 1568, 1568, (1456, 819)),
        (3840, 2160, 2576, 4784, (2576, 1449)),
        (1920, 1080, 2576, 4784, (1920, 1080)),
        (1000, 1000, 1568, 1568, (1000, 1000)),
    ],
)
def test_tamano_de_referencia_de_la_documentacion(ancho, alto, lado_max, tokens_max, esperado):
    assert tamano_para_enviar(ancho, alto, lado_max, tokens_max) == esperado


@pytest.mark.parametrize(
    "ancho, alto, esperado",
    [
        (4000, 3000, (1568, 1176)),   # foto de tablet 4:3
        (3000, 4000, (1176, 1568)),   # la misma en vertical
        (4032, 2268, (1568, 882)),    # 16:9
        (1568, 1176, (1568, 1176)),   # ya cabe
        (800, 600, (800, 600)),       # nunca se agranda
    ],
)
def test_por_defecto_el_lado_largo_queda_en_1568(ancho, alto, esperado):
    assert tamano_para_enviar(ancho, alto) == esperado
    assert max(esperado) <= 1568 and tokens_de_imagen(*esperado) <= 4784


def test_alta_resolucion_llega_al_maximo_del_modelo():
    """En 4:3 manda el tope de tokens, no el de 2576 px: la foto queda en 2212 x 1659."""
    assert tamano_para_enviar(4000, 3000, lado_max=2576) == (2212, 1659)
    assert tokens_de_imagen(2212, 1659) <= 4784 < tokens_de_imagen(2576, 1932)
    assert tamano_para_enviar(4032, 2268, lado_max=2576) == (2576, 1449)  # en 16:9 sí llega a 2576


@pytest.mark.parametrize("lado_max, tokens_max", [(1568, 4784), (2576, 4784), (1568, 1568)])
@pytest.mark.parametrize("ancho, alto", [(4000, 3000), (3000, 4000), (4032, 2268), (2000, 1500), (5000, 1200),
                                         (1075, 1520), (3024, 4032), (6000, 4000)])
def test_el_tamano_calculado_siempre_cabe_y_es_el_mayor_posible(ancho, alto, lado_max, tokens_max):
    """Si cabe, el modelo no vuelve a reducir la imagen y sus cajas coinciden con lo enviado."""
    def cabe(w, h):
        return (-(-w // 28) * 28 <= lado_max and -(-h // 28) * 28 <= lado_max
                and tokens_de_imagen(w, h) <= tokens_max)

    nuevo_ancho, nuevo_alto = tamano_para_enviar(ancho, alto, lado_max, tokens_max)
    assert cabe(nuevo_ancho, nuevo_alto)
    assert abs(nuevo_ancho / nuevo_alto - ancho / alto) / (ancho / alto) < 0.005   # misma proporción
    if (nuevo_ancho, nuevo_alto) == (ancho, alto):
        return  # ya cabía: no se toca (y nunca se agranda)
    largo = max(nuevo_ancho, nuevo_alto) + 1                                       # un píxel más ya no cabe
    corto = round(largo * min(ancho, alto) / max(ancho, alto))
    assert not cabe(largo, corto)


def test_tokens_de_imagen():
    assert tokens_de_imagen(1000, 1000) == 1296      # ejemplo de la documentación
    assert tokens_de_imagen(1568, 1176) == 56 * 42
    assert tokens_de_imagen(29, 28) == 2             # un parche incompleto cuenta entero


def test_redimensionar_reduce_y_no_agranda():
    assert redimensionar(lienzo(4000, 3000)).shape == (1176, 1568, 3)
    pequena = lienzo(640, 480)
    assert redimensionar(pequena) is pequena


# --------------------------------------------------------------------------- #
# Lectura
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("formato", ["JPEG", "PNG", "WEBP"])
def test_decodifica_los_formatos_habituales_en_bgr(formato):
    frame = decodificar(foto_en_bytes(400, 300, formato))
    assert frame.shape == (300, 400, 3) and frame.dtype == np.uint8
    azul, verde, rojo = frame[150, 50]
    assert rojo > 180 and azul < 80 and verde < 80  # la mitad izquierda es roja: el orden es BGR


def test_aplica_la_orientacion_exif_de_las_fotos_de_tablet():
    """Orientación 6: la foto se guardó acostada y hay que girarla 90° para verla derecha."""
    frame = decodificar(foto_en_bytes(400, 300, orientacion=6))
    assert frame.shape == (400, 300, 3)
    # La mitad roja, que estaba a la izquierda, queda arriba
    assert frame[50, 150][2] > 180 and frame[350, 150][2] < 90


@pytest.mark.parametrize("datos", [b"", b"esto no es una imagen", b"\xff\xd8\xff\xe0 jpeg truncado"])
def test_un_archivo_que_no_es_imagen_se_rechaza_con_mensaje_claro(datos):
    with pytest.raises(ImagenInvalida, match="No se pudo leer la imagen"):
        decodificar(datos)


def test_una_imagen_demasiado_pequena_se_rechaza():
    with pytest.raises(ImagenInvalida, match="muy pequeña"):
        decodificar(foto_en_bytes(300, 150))


def test_preparar_foto_difumina_antes_de_reducir(monkeypatch):
    """La foto se difumina sí o sí, a buena resolución, y sale del tamaño que se envía."""
    vistos = []

    def difuminar_espia(frame):
        vistos.append(frame.shape)
        return np.zeros_like(frame)  # una marca para saber que lo que sale pasó por aquí

    monkeypatch.setattr(modulo_imagen, "difuminar_rostros", difuminar_espia)
    frame = preparar_foto(foto_en_bytes(4000, 3000))

    assert vistos == [(1659, 2212, 3)]          # los rostros se buscan a la resolución alta
    assert frame.shape == (1176, 1568, 3)       # y se envía con lado largo de 1568
    assert not frame.any()                      # lo que sale es lo difuminado, no el original


def test_preparar_foto_respeta_el_lado_maximo_configurado(monkeypatch):
    monkeypatch.setattr(modulo_imagen, "difuminar_rostros", lambda frame: frame)
    assert preparar_foto(foto_en_bytes(4000, 3000), lado_max=2576).shape == (1659, 2212, 3)
    assert preparar_foto(foto_en_bytes(640, 480)).shape == (480, 640, 3)


def test_preparar_foto_con_el_difuminado_real_no_falla():
    frame = preparar_foto(foto_en_bytes(1200, 900))
    assert frame.shape == (900, 1200, 3)


# --------------------------------------------------------------------------- #
# Anotación
# --------------------------------------------------------------------------- #
def peligro(n: int, caja: list[float], confianza: str = "alta") -> dict:
    return {"n": n, "ubicacion": caja, "confianza": confianza}


def test_anotar_dibuja_la_caja_y_el_numero_sin_tocar_el_original():
    original = lienzo()
    copia = original.copy()
    anotada = anotar(original, [peligro(1, [0.25, 0.25, 0.75, 0.75])])

    assert np.array_equal(original, copia)
    assert anotada.shape == original.shape and not np.array_equal(anotada, original)
    assert pixeles_de_color(anotada, LIMA) > 500         # el borde de la caja
    assert pixeles_de_color(anotada, AUREN_DEEP) > 300   # el recuadro del número
    # El borde pasa por donde debe: lado superior, en el centro
    assert pixeles_de_color(anotada[145:155, 380:420], LIMA) > 0
    # El interior de la caja no se tapa
    assert np.array_equal(anotada[250:350, 350:450], original[250:350, 350:450])


def test_sin_peligros_devuelve_una_copia_igual():
    original = lienzo()
    anotada = anotar(original, [])
    assert np.array_equal(anotada, original) and anotada is not original


def test_la_confianza_baja_se_dibuja_punteada():
    caja = [0.2, 0.2, 0.8, 0.8]
    continua = pixeles_de_color(anotar(lienzo(), [peligro(1, caja, "alta")]), LIMA)
    punteada = pixeles_de_color(anotar(lienzo(), [peligro(1, caja, "baja")]), LIMA)
    assert 0 < punteada < continua * 0.8


def test_dos_cajas_en_el_mismo_punto_no_se_tapan_el_numero():
    caja = [0.2, 0.2, 0.8, 0.8]
    una = pixeles_de_color(anotar(lienzo(), [peligro(1, caja)]), AUREN_DEEP)
    dos = pixeles_de_color(anotar(lienzo(), [peligro(1, caja), peligro(2, caja)]), AUREN_DEEP)
    assert dos > una * 1.6


def test_una_caja_en_el_borde_no_saca_la_etiqueta_de_la_imagen():
    anotada = anotar(lienzo(), [peligro(12, [0.97, 0.97, 1.0, 1.0]), peligro(3, [0.0, 0.0, 0.03, 0.03])])
    assert anotada.shape == (600, 800, 3)
    assert pixeles_de_color(anotada, AUREN_DEEP) > 600  # las dos etiquetas quedaron dentro


# --------------------------------------------------------------------------- #
# Escritura
# --------------------------------------------------------------------------- #
def test_guarda_jpeg_en_rutas_con_tildes(tmp_path):
    ruta = guardar_jpeg(lienzo(), tmp_path / "señalización" / "inspección ñ.jpg")
    assert ruta.is_file()
    leida = decodificar(ruta.read_bytes())
    assert leida.shape == (600, 800, 3)
    assert abs(int(leida[300, 400][0]) - GRIS[0]) < 6


def test_codificar_jpeg_devuelve_un_jpeg():
    datos = codificar_jpeg(lienzo())
    assert datos[:2] == b"\xff\xd8"
    assert cv2.imdecode(np.frombuffer(datos, np.uint8), cv2.IMREAD_COLOR).shape == (600, 800, 3)


def test_la_miniatura_cabe_en_el_espacio_y_no_agranda():
    assert miniatura(lienzo(1568, 1176), 640, 415).shape == (415, 553, 3)
    assert miniatura(lienzo(1176, 1568), 640, 415).shape == (415, 311, 3)
    assert miniatura(lienzo(1568, 882), 640, 415).shape == (360, 640, 3)
    assert miniatura(lienzo(320, 240), 640, 415).shape == (240, 320, 3)
