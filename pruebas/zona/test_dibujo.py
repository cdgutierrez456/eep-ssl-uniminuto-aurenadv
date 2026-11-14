"""Dibujo de la estación: franja de advertencia, zona, personas, pantalla y la imagen que puede salir."""

import numpy as np
import pytest

from modulos.zona.interfaz import dibujo as modulo_dibujo
from modulos.zona.interfaz.dibujo import contorno_de_franja, dibujar_personas, dibujar_zona, imagen_para_guardar
from modulos.zona.interfaz.marca import AMARILLO, DEEP_CLARO, ROJO, bgr
from modulos.zona.interfaz.panel import AVISOS, EstadoPantalla, Pantalla, envolver
from modulos.zona.nucleo import EstadoZona, MonitorZona, crear_zona
from modulos.zona.nucleo.geometria import distancia_a_poligono, punto_en_poligono

ANCHO, ALTO = 1280, 720
CUADRADO = [[400 / ANCHO, 300 / ALTO], [800 / ANCHO, 300 / ALTO], [800 / ANCHO, 600 / ALTO], [400 / ANCHO, 600 / ALTO]]
ELE = [[0.2, 0.2], [0.6, 0.2], [0.6, 0.5], [0.4, 0.5], [0.4, 0.8], [0.2, 0.8]]
TRAPECIO = [[0.33, 0.25], [0.67, 0.25], [0.74, 0.60], [0.26, 0.60]]   # un rectángulo visto en perspectiva


def zona_px(poligono=CUADRADO, margen=80):
    return crear_zona("piso", poligono, ANCHO, ALTO, margen_px=margen)


def zona_m(margen=0.5):
    return crear_zona("piso", TRAPECIO, ANCHO, ALTO, margen_m=margen, rectangulo_real={"ancho_m": 1.5, "largo_m": 1.0})


def vista_de(zona, punto, segundos=1.0):
    """La persona tal como la ve el monitor después de estar quieta en ``punto``."""
    monitor = MonitorZona(zona)
    for i in range(round(segundos * 30) + 1):
        resultado = monitor.actualizar(i / 30, {1: [punto]})
    return resultado.personas[0], resultado.estado.estado


# ------------------------------------------------------- franja de advertencia
@pytest.mark.parametrize("poligono", [CUADRADO, ELE], ids=["cuadrado", "con_entrante"])
def test_la_franja_en_pixeles_queda_a_un_margen_de_la_zona(poligono):
    zona = zona_px(poligono)
    franja = contorno_de_franja(zona)
    distancias = [distancia_a_poligono((float(x), float(y)), zona.poligono) for x, y in franja]
    assert min(distancias) >= 80 - 2.5 and max(distancias) <= 80 + 2.5
    assert all(not punto_en_poligono((float(x), float(y)), zona.poligono) for x, y in franja)


def test_la_franja_en_metros_se_calcula_sobre_el_piso():
    zona = zona_m()
    franja = contorno_de_franja(zona)
    en_piso = [zona.homografia.aplicar((float(x), float(y))) for x, y in franja]
    distancias = [distancia_a_poligono(punto, zona.poligono_m) for punto in en_piso]
    assert min(distancias) >= 0.5 - 0.02 and max(distancias) <= 0.5 + 0.02      # medio metro, con 2 cm de tolerancia
    # En la imagen se ve más ancha cerca de la cámara (abajo) que lejos (arriba): perspectiva
    arriba = min(y for _, y in zona.poligono) - franja[:, 1].min()
    abajo = franja[:, 1].max() - max(y for _, y in zona.poligono)
    assert abajo > 1.2 * arriba


def test_sin_margen_no_hay_franja():
    assert contorno_de_franja(zona_px(margen=0)) is None
    assert contorno_de_franja(zona_m(margen=0)) is None


def test_la_franja_se_calcula_una_vez_por_zona():
    zona = zona_px()
    assert contorno_de_franja(zona) is contorno_de_franja(zona_px())   # zonas iguales comparten el resultado


# -------------------------------------------------------------------- dibujo
def test_la_zona_se_pinta_de_rojo_y_la_franja_de_amarillo_sin_tocar_el_resto():
    gris = np.full((ALTO, ANCHO, 3), 128, dtype=np.uint8)
    imagen = gris.copy()
    dibujar_zona(imagen, zona_px(), "libre")

    dentro, en_franja, lejos = imagen[450, 600], imagen[450, 350], imagen[100, 100]
    assert dentro[2] > 150 and dentro[2] > dentro[0] + 40                # rojo: canal R por encima del azul
    assert en_franja[2] > 135 and en_franja[1] > 135 and en_franja[0] < 128   # amarillo: R y G suben, B baja
    assert (lejos == 128).all()
    assert tuple(imagen[300, 600]) == bgr(ROJO)                          # el borde de la zona, en rojo pleno


def test_el_estado_intensifica_el_color_que_le_corresponde():
    def pintar(estado):
        imagen = np.full((ALTO, ANCHO, 3), 128, dtype=np.uint8)
        dibujar_zona(imagen, zona_px(), estado)
        return imagen
    libre, advertencia, peligro = pintar("libre"), pintar("advertencia"), pintar("peligro")
    assert int(peligro[450, 600][2]) > int(libre[450, 600][2])            # zona más roja en peligro
    assert int(advertencia[450, 350][0]) < int(libre[450, 350][0])        # franja más amarilla en advertencia


def test_cada_persona_lleva_el_color_de_su_estado():
    zona = zona_px()
    colores = {}
    for nombre, punto in [("libre", (100.0, 450.0)), ("advertencia", (350.0, 450.0)), ("peligro", (600.0, 450.0))]:
        persona, _ = vista_de(zona, punto)
        assert persona.estado == nombre
        imagen = np.full((ALTO, ANCHO, 3), 128, dtype=np.uint8)
        dibujar_personas(imagen, [persona], {1: (punto[0] - 30, punto[1] - 170, punto[0] + 30, punto[1] + 5)})
        colores[nombre] = tuple(int(v) for v in imagen[int(punto[1]), int(punto[0])])
    assert colores["peligro"] == bgr(ROJO) and colores["advertencia"] == bgr(AMARILLO)
    assert len(set(colores.values())) == 3


def test_quien_se_dejo_de_ver_se_dibuja_hueco():
    zona = zona_px()
    monitor = MonitorZona(zona)
    for i in range(20):
        monitor.actualizar(i / 30, {1: [(600.0, 450.0)]})
    oculta = monitor.actualizar(1.0, {}).personas[0]
    assert not oculta.presente and oculta.estado == "peligro"
    imagen = np.full((ALTO, ANCHO, 3), 128, dtype=np.uint8)
    dibujar_personas(imagen, [oculta])
    assert tuple(imagen[450, 600]) == (128, 128, 128)                    # el centro queda vacío
    assert tuple(imagen[450, 610]) == bgr(ROJO)                          # y el anillo, en rojo


# --------------------------------------------------- la imagen que puede salir
def test_la_imagen_para_guardar_se_difumina_primero_y_se_dibuja_despues(monkeypatch):
    zona = zona_px()
    persona, estado = vista_de(zona, (600.0, 450.0))
    original = np.full((ALTO, ANCHO, 3), 200, dtype=np.uint8)
    recibidos = []

    def difuminar_espia(frame):
        recibidos.append(frame.copy())
        return np.zeros_like(frame)      # un "difuminado" inconfundible: todo negro

    monkeypatch.setattr(modulo_dibujo, "difuminar_rostros", difuminar_espia)
    imagen = imagen_para_guardar(original, zona, [persona], estado=estado)

    assert len(recibidos) == 1 and (recibidos[0] == 200).all()           # al difuminado le llega la imagen limpia
    assert (original == 200).all()                                       # y la original no se toca
    assert tuple(imagen[100, 100]) == (0, 0, 0)                          # el fondo es el del difuminado
    assert tuple(imagen[300, 600]) == bgr(ROJO)                          # y encima va la zona
    assert tuple(imagen[450, 600]) == bgr(ROJO)                          # y el punto de apoyo de la persona


def test_sin_zona_la_imagen_para_guardar_solo_se_difumina():
    original = np.full((90, 160, 3), 77, dtype=np.uint8)
    imagen = imagen_para_guardar(original, None)
    assert imagen is not original and (imagen == 77).all()


# -------------------------------------------------------------------- pantalla
@pytest.mark.parametrize("estado, clave", [
    (None, "sin_zona"), (EstadoZona(), "libre"), (EstadoZona("advertencia", 0, 1), "advertencia"),
    (EstadoZona("peligro", 1, 0), "peligro"),
])
def test_el_aviso_grande_lleva_el_color_del_estado(estado, clave):
    pantalla = Pantalla(1920, 1080)
    imagen = pantalla.componer(np.full((ALTO, ANCHO, 3), 90, dtype=np.uint8), EstadoPantalla(estado=estado))
    assert imagen.shape == (1080, 1920, 3)
    assert tuple(int(v) for v in imagen[5, 1400]) == bgr(AVISOS[clave][0])   # esquina del aviso, sin texto encima


def test_el_aviso_usa_colores_de_seguridad_y_no_la_lima():
    assert AVISOS["peligro"][0] == ROJO and AVISOS["advertencia"][0] == AMARILLO
    assert AVISOS["libre"][0] == DEEP_CLARO


def test_un_clic_en_la_pantalla_se_convierte_en_un_punto_de_la_imagen():
    pantalla = Pantalla(1920, 1080)
    vista = np.zeros((ALTO, ANCHO, 3), dtype=np.uint8)
    vista[300:310, 500:510] = 255                                        # una marca en (505, 305) de la imagen
    imagen = pantalla.componer(vista, EstadoPantalla(estado=EstadoZona()))
    ys, xs = np.nonzero((imagen[150:994, :1480] == 255).all(axis=2))
    x_pantalla, y_pantalla = xs.mean(), ys.mean() + 150
    assert pantalla.a_imagen(x_pantalla, y_pantalla) == pytest.approx((505, 305), abs=1.5)


def test_la_pantalla_se_adapta_a_otra_resolucion_y_a_no_tener_camara():
    pantalla = Pantalla(1280, 720)
    estado = EstadoPantalla(estado=EstadoZona("peligro", 2, 1), mensaje="Cámara desconectada, reconectando…",
                            zona="Zona activa de 4 vértices. Mide en metros (1,50 × 1,00 m).", ocultas=1,
                            ingresos=3, casi_accidentes=7, fps=24.6, dispositivo="yolo26n-pose en CPU",
                            plataforma="sin conexión (4 en cola)", sonido_local=True)
    assert pantalla.componer(None, estado).shape == (720, 1280, 3)
    assert pantalla.componer(np.zeros((480, 640, 3), dtype=np.uint8), estado).shape == (720, 1280, 3)


def test_el_panel_no_se_vuelve_a_pintar_si_no_cambia_lo_que_muestra():
    pantalla = Pantalla(1920, 1080)
    vista = np.zeros((ALTO, ANCHO, 3), dtype=np.uint8)
    estado = EstadoPantalla(estado=EstadoZona(), fps=29.6)
    pantalla.componer(vista, estado)
    panel = pantalla._partes["panel"][1]
    estado.fps = 30.2                                                    # mismos fps redondeados
    pantalla.componer(vista, estado)
    assert pantalla._partes["panel"][1] is panel
    estado.ingresos = 1                                                  # ahora sí cambió algo
    pantalla.componer(vista, estado)
    assert pantalla._partes["panel"][1] is not panel


def test_envolver_parte_el_texto_sin_cortar_palabras():
    texto = "Zona activa de 4 vértices. Mide en píxeles: faltan las medidas reales del rectángulo."
    lineas = envolver(texto, 17, 300)
    assert len(lineas) > 1 and " ".join(lineas) == texto
    assert envolver("", 17, 300) == []
