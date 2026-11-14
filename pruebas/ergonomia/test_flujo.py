"""Flujo de la demo y publicación, sin cámara: posturas simuladas y el receptor de prueba real."""

import cv2
import httpx
import numpy as np
import pytest

from modulos.comun import esperar_envios, validar_evento
from modulos.comun.eventos import construir_evento
from modulos.ergonomia.config import umbrales_desde, validar_config
from modulos.ergonomia.estacion import Analizador
from modulos.ergonomia.interfaz import marca
from modulos.ergonomia.flujo import TECLA_ENTER, TECLA_ESC, TECLA_ESPACIO, TECLA_RETROCESO, Flujo
from modulos.ergonomia.nucleo.intentos import Visita, sugerir_correcciones
from modulos.ergonomia.nucleo.mensajes import cargar_mensajes
from modulos.ergonomia.nucleo.levantamiento import Estado
from modulos.ergonomia.nucleo.reba import calcular_reba
from modulos.ergonomia.publicacion import NO_EVALUADO, Critico, Publicador, datos_evaluacion

from .test_angulos import postura
from .test_vista import EstimadorFijo

FPS = 30
FRAME = np.full((720, 1280, 3), 120, np.uint8)
CONFIG = validar_config({})

DE_PIE = dict(tronco=0, rodilla=5, brazo=0, codo=20)
ESPALDA_DOBLADA = dict(tronco=95, cuello=-15, rodilla=35, brazo=95, codo=10)
SENTADILLA = dict(tronco=45, cuello=5, rodilla=110, brazo=70, codo=20)


class Simulacion:
    """Alimenta el flujo con posturas, como lo haría la estación con la cámara."""

    def __init__(self, flujo: Flujo, config=CONFIG):
        self.flujo, self.config = flujo, config
        self.estimador = EstimadorFijo(None)
        self.analizador = Analizador(self.estimador)
        self.cuadro = 0
        self.intentos = []

    @property
    def t(self) -> float:
        return self.cuadro / FPS

    def avanzar(self, pose: dict | None, segundos: float) -> None:
        self.estimador.puntos = None if pose is None else postura(**pose)
        for _ in range(round(segundos * FPS)):
            analisis = self.analizador.analizar(FRAME, round(self.t * 1000), self.config)
            intento = self.flujo.procesar(self.t, FRAME, analisis, self.config)
            if intento is not None:
                self.intentos.append(intento)
            self.cuadro += 1

    def levantar(self, pose: dict) -> None:
        self.avanzar(DE_PIE, 1.0)
        self.avanzar(pose, 1.5)
        self.avanzar(DE_PIE, 2.0)


# --------------------------------------------------------------------------- #
# Flujo
# --------------------------------------------------------------------------- #
def test_dos_intentos_y_su_comparacion_en_pantalla():
    flujo = Flujo()
    sim = Simulacion(flujo)
    assert flujo.instruccion(0, CONFIG) == "Ubícate de lado, con el cuerpo completo en cuadro"
    sim.avanzar(DE_PIE, 0.3)
    assert flujo.instruccion(sim.t, CONFIG) == "Quédate de pie y quieto un momento"  # calibrando la postura neutra
    sim.avanzar(DE_PIE, 0.7)
    assert flujo.instruccion(sim.t, CONFIG) == "Levanta la caja del piso a la mesa"
    assert flujo.superior(CONFIG) == ("Sin número de visitante · Intento 1", "Listo")
    assert flujo.inferior() == (("", "", ""), None)

    sim.avanzar(ESPALDA_DOBLADA, 1.0)
    assert flujo.maquina.estado is Estado.LEVANTANDO
    assert flujo.superior(CONFIG)[1].startswith("Levantando · ")
    assert flujo.instruccion(sim.t, CONFIG) == "Deja la caja en la mesa y ponte erguido"
    sim.avanzar(DE_PIE, 2.0)
    assert [i.numero for i in sim.intentos] == [1]
    primero = sim.intentos[0]
    assert primero.nivel == "alto" and primero.resultado.segmentos["tronco"] == 4
    # La franja pone primero la técnica (espalda y rodillas) y el REBA debajo; el acento es el de la espalda
    assert flujo.inferior() == (("Flexión de espalda: 95° · alta", "Rodillas 35° · poco flexionadas",
                                 f"REBA · {primero.resumen()} · Haz un segundo intento para comparar"), marca.ROJO)
    assert flujo.instruccion(sim.t, CONFIG) == "Espalda doblada 95°. En el siguiente intento, flexiona las rodillas"

    sim.levantar(SENTADILLA)
    segundo = sim.intentos[1]
    assert segundo.numero == 2 and segundo.puntaje < primero.puntaje
    (principal, secundaria, detalle), color = flujo.inferior()
    assert principal == "Flexión de espalda: 95° → 45°"  # lo primero: lo que la técnica cambia
    assert secundaria == "Rodillas: 35° → 110°"
    assert detalle.startswith(f"REBA · {primero.resumen()} → {segundo.resumen()} · ")  # el REBA, completo, debajo
    assert "Tronco 4 → 3" in detalle and "Piernas 2 → 3" in detalle
    assert color == marca.AMARILLO  # espalda a 45°: flexión media
    assert flujo.instruccion(sim.t, CONFIG) == "Espalda 50° más recta y REBA más bajo"
    assert flujo.superior(CONFIG)[0] == "Sin número de visitante · Intento 3"
    # Pasado el tiempo del resultado vuelve la instrucción normal
    sim.avanzar(DE_PIE, flujo.segundos_resultado)
    assert flujo.instruccion(sim.t, CONFIG) == "Levanta la caja del piso a la mesa"


def test_numero_de_visitante_por_teclado():
    flujo = Flujo()
    for tecla in "14":
        assert flujo.tecla(ord(tecla))
    assert flujo.superior(CONFIG)[0].startswith("Número de visitante: 14_")
    assert flujo.tecla(ord("3")) and flujo.tecla(TECLA_RETROCESO) and flujo.tecla(ord("2"))
    assert flujo.tecla(TECLA_ENTER)
    assert flujo.visita.sesion_id == "V-0142" and flujo.entrada is None
    assert flujo.superior(CONFIG)[0] == "Visitante V-0142 · Intento 1"
    # Esc cancela la entrada sin cambiar de visitante (y no cierra el programa)
    assert flujo.tecla(ord("9")) and flujo.tecla(TECLA_ESC)
    assert flujo.visita.sesion_id == "V-0142" and flujo.entrada is None
    # Fuera de la entrada, Esc y Enter no son del flujo
    assert not flujo.tecla(TECLA_ESC) and not flujo.tecla(TECLA_ENTER) and not flujo.tecla(ord("q"))


def test_otro_numero_empieza_una_visita_nueva_y_n_la_reinicia():
    flujo = Flujo()
    sim = Simulacion(flujo)
    for tecla in "7":
        flujo.tecla(ord(tecla))
    flujo.tecla(TECLA_ENTER)
    sim.levantar(ESPALDA_DOBLADA)
    assert len(flujo.visita.intentos) == 1
    flujo.tecla(ord("8"))
    flujo.tecla(TECLA_ENTER)
    assert flujo.visita.sesion_id == "V-0008" and flujo.visita.intentos == []
    sim.levantar(ESPALDA_DOBLADA)
    assert flujo.visita.intentos[0].numero == 1  # la numeración empieza de nuevo
    assert flujo.tecla(ord("n"))
    assert flujo.visita.vacia


def test_el_numero_tecleado_despues_se_asigna_a_la_visita_en_curso():
    flujo = Flujo()
    sim = Simulacion(flujo)
    sim.levantar(ESPALDA_DOBLADA)
    flujo.tecla(ord("5"))
    flujo.tecla(TECLA_ENTER)
    assert flujo.visita.sesion_id == "V-0005" and len(flujo.visita.intentos) == 1


def test_sin_nadie_en_cuadro_termina_la_visita():
    flujo = Flujo(segundos_nueva_visita=3.0)
    sim = Simulacion(flujo)
    flujo.visita = Visita("V-0042")
    sim.levantar(ESPALDA_DOBLADA)
    sim.avanzar(None, 2.0)
    assert flujo.visita.sesion_id == "V-0042"  # una ausencia corta no la termina
    sim.avanzar(None, 1.5)
    assert flujo.visita.vacia
    assert flujo.superior(CONFIG) == ("Sin número de visitante · Intento 1", "Sin persona")


def test_modo_manual_con_la_barra():
    config = validar_config({"modo_deteccion": "manual"})
    flujo = Flujo()
    sim = Simulacion(flujo, config)
    sim.avanzar(DE_PIE, 1.0)
    assert flujo.instruccion(sim.t, config) == "Barra espaciadora para iniciar"
    assert flujo.superior(config)[1] == "Listo · modo manual"
    sim.avanzar(ESPALDA_DOBLADA, 1.0)
    assert flujo.maquina.estado is not Estado.LEVANTANDO  # en manual no empieza solo
    assert flujo.tecla(TECLA_ESPACIO)
    sim.avanzar(ESPALDA_DOBLADA, 1.0)
    assert flujo.instruccion(sim.t, config) == "Barra espaciadora para terminar"
    flujo.tecla(TECLA_ESPACIO)
    sim.avanzar(DE_PIE, 0.2)
    assert len(sim.intentos) == 1 and sim.intentos[0].nivel == "alto"


def test_levantamiento_sin_cuerpo_completo_no_cuenta_como_intento():
    flujo = Flujo()
    sim = Simulacion(flujo)
    sim.avanzar(DE_PIE, 1.0)
    agachado = postura(**ESPALDA_DOBLADA)
    agachado["tobillo_derecho"] = agachado["tobillo_derecho"]._replace(visibilidad=0.1)
    sim.estimador.puntos = agachado
    for _ in range(45):
        analisis = sim.analizador.analizar(FRAME, round(sim.t * 1000), CONFIG)
        flujo.procesar(sim.t, FRAME, analisis, CONFIG)
        sim.cuadro += 1
    sim.avanzar(dict(DE_PIE), 0.0)
    de_pie = postura(**DE_PIE)
    de_pie["tobillo_derecho"] = de_pie["tobillo_derecho"]._replace(visibilidad=0.1)
    sim.estimador.puntos = de_pie
    for _ in range(60):
        analisis = sim.analizador.analizar(FRAME, round(sim.t * 1000), CONFIG)
        flujo.procesar(sim.t, FRAME, analisis, CONFIG)
        sim.cuadro += 1
    assert flujo.visita.intentos == []
    assert flujo.instruccion(sim.t, CONFIG) == "No se vio el cuerpo completo. Inténtalo de nuevo"


def test_los_umbrales_de_la_config_llegan_a_la_maquina():
    config = validar_config({"deteccion": {"segundos_erguido": 0.4, "duracion_maxima_s": 9}})
    assert umbrales_desde(config).segundos_erguido == 0.4
    assert umbrales_desde(config).tronco_inicio == 20  # lo no indicado conserva su valor
    flujo = Flujo()
    sim = Simulacion(flujo, config)
    sim.avanzar(DE_PIE, 0.2)
    assert flujo.maquina.umbrales.duracion_maxima_s == 9
    with pytest.raises(ValueError):
        validar_config({"deteccion": {"segundos_erguido": "uno"}})


# --------------------------------------------------------------------------- #
# Datos del evento
# --------------------------------------------------------------------------- #
def _intento_y_angulos(pose=ESPALDA_DOBLADA, numero=1):
    analisis = Analizador(EstimadorFijo(postura(**pose))).analizar(FRAME, 0, CONFIG)
    visita = Visita()
    for _ in range(numero):
        intento = visita.registrar(analisis.resultado, 2.34)
    return intento, analisis


def test_datos_del_evento_cumplen_el_contrato():
    intento, analisis = _intento_y_angulos(numero=2)
    datos = datos_evaluacion(intento, analisis.angulos, CONFIG)
    r = intento.resultado
    assert (datos["puntaje"], datos["nivel"], datos["intento"], datos["lado"]) == (r.puntaje, r.nivel, 2, "derecho")
    assert datos["duracion_s"] == 2.3
    assert datos["angulos"]["tronco"] == pytest.approx(95, abs=0.2) and set(datos["angulos"]) == set(r.segmentos)
    assert datos["puntajes"]["tronco"] == 4 and datos["puntajes"]["tabla_c"] == r.tabla_c
    assert datos["ajustes_aplicados"] == ["brazo_persona_inclinada"]
    assert datos["no_evaluado"] == NO_EVALUADO == ["torsion", "inclinacion_lateral", "abduccion"]
    assert (datos["peso_carga_kg"], datos["agarre"]) == (5, "bueno")
    assert datos["segmentos_no_estimados"] == [] and datos["segmentos_asumidos"] == []
    validar_evento(construir_evento("ergonomia", "evaluacion_reba", datos, severidad=r.severidad))


def test_muneca_no_estimada_va_declarada_y_sin_numero():
    puntos = postura(**ESPALDA_DOBLADA)
    puntos["indice_derecho"] = puntos["indice_derecho"]._replace(visibilidad=0.1)
    analisis = Analizador(EstimadorFijo(puntos)).analizar(FRAME, 0, CONFIG)
    intento = Visita().registrar(analisis.resultado, 2.0)
    datos = datos_evaluacion(intento, analisis.angulos, CONFIG)
    assert datos["segmentos_no_estimados"] == ["muneca"] == datos["segmentos_asumidos"]
    assert "muneca" not in datos["angulos"] and "muneca" not in datos["puntajes"]
    validar_evento(construir_evento("ergonomia", "evaluacion_reba", datos, severidad=intento.resultado.severidad))


@pytest.mark.parametrize("angulos, severidad", [
    ({"tronco": 0, "cuello": 5, "piernas": 0, "brazo": 0, "antebrazo": 80, "muneca": 0}, "info"),
    ({"tronco": 30, "cuello": 10, "piernas": 0, "brazo": 30, "antebrazo": 80, "muneca": 0}, "baja"),
    ({"tronco": 70, "cuello": 10, "piernas": 0, "brazo": 60, "antebrazo": 30, "muneca": 0}, "media"),
    ({"tronco": 95, "cuello": 30, "piernas": 40, "brazo": 100, "antebrazo": 20, "muneca": 20}, "alta"),
])
def test_severidad_del_evento_segun_el_puntaje(angulos, severidad):
    assert calcular_reba(angulos).severidad == severidad


# --------------------------------------------------------------------------- #
# Publicación contra el receptor de prueba
# --------------------------------------------------------------------------- #
def test_publica_evaluacion_reba_con_su_fotograma_critico(entorno, tmp_path, monkeypatch):
    from modulos.ergonomia.interfaz import dibujo

    difuminados = []
    original = dibujo.difuminar_rostros
    monkeypatch.setattr(dibujo, "difuminar_rostros", lambda f: (difuminados.append(f.shape), original(f))[1])
    entorno.encender()
    intento, analisis = _intento_y_angulos()
    publicador = Publicador(tmp_path / "capturas")
    critico = Critico(FRAME, analisis.puntos, analisis.angulos)
    publicado = publicador.publicar_levantamiento(critico, intento, "V-0142", CONFIG).result(timeout=20)
    publicador.cerrar()
    assert esperar_envios(10)

    assert difuminados == [FRAME.shape]  # el fotograma pasó por el difuminado antes de guardarse
    imagen = cv2.imdecode(np.fromfile(str(publicado.ruta_imagen), np.uint8), cv2.IMREAD_COLOR)
    assert imagen.shape == FRAME.shape
    assert (imagen != FRAME).any()  # lleva el esqueleto dibujado
    assert not (FRAME != 120).any()  # el fotograma original no se tocó

    recibidos = httpx.get(entorno.url + "/api/eventos").json()
    assert recibidos == [publicado.evento]
    evento = recibidos[0]
    assert (evento["estacion"], evento["tipo"], evento["sesion_id"]) == ("ergonomia", "evaluacion_reba", "V-0142")
    assert evento["severidad"] == intento.resultado.severidad == "alta"
    assert evento["datos"]["puntaje"] == intento.puntaje and evento["datos"]["intento"] == 1
    adjunto = evento["adjuntos"][0]
    assert adjunto["tipo"] == "imagen" and adjunto["ruta"].startswith("media/") and adjunto["ruta"].endswith(".jpg")
    assert (tmp_path / "receptor" / adjunto["ruta"]).is_file()  # el archivo llegó al receptor


def test_sin_sesion_el_evento_no_lleva_sesion_id_y_sin_receptor_queda_en_cola(entorno, tmp_path):
    intento, analisis = _intento_y_angulos()
    publicador = Publicador(tmp_path / "capturas")
    critico = Critico(FRAME, analisis.puntos, analisis.angulos)
    publicado = publicador.publicar_levantamiento(critico, intento, None, CONFIG).result(timeout=30)
    publicador.cerrar()
    assert "sesion_id" not in publicado.evento
    assert "medios_pendientes" in publicado.ruta_medio  # sin receptor, la imagen queda respaldada
    assert not esperar_envios(1.0)
    entorno.encender()  # al volver la plataforma, el evento se entrega solo
    assert esperar_envios(20)
    assert [e["id"] for e in httpx.get(entorno.url + "/api/eventos").json()] == [publicado.evento["id"]]


def test_el_flujo_publica_cada_intento_con_el_numero_de_visitante(entorno, tmp_path):
    entorno.encender()
    publicador = Publicador(tmp_path / "capturas")
    flujo = Flujo(publicador)
    sim = Simulacion(flujo)
    for tecla in "142":
        flujo.tecla(ord(tecla))
    flujo.tecla(TECLA_ENTER)
    sim.levantar(ESPALDA_DOBLADA)
    sim.levantar(SENTADILLA)
    publicador.cerrar()
    assert esperar_envios(10)
    recibidos = httpx.get(entorno.url + "/api/eventos").json()
    assert [(e["sesion_id"], e["datos"]["intento"]) for e in recibidos] == [("V-0142", 1), ("V-0142", 2)]
    assert recibidos[0]["datos"]["puntaje"] > recibidos[1]["datos"]["puntaje"]
    assert all((tmp_path / "receptor" / e["adjuntos"][0]["ruta"]).is_file() for e in recibidos)


# --------------------------------------------------------------------------- #
# Correcciones: primero la espalda, y el REBA sin maquillar
# --------------------------------------------------------------------------- #
def _visita(*intentos: dict) -> Visita:
    visita = Visita()
    for angulos in intentos:
        visita.registrar(calcular_reba(angulos), 2.0)
    return visita


DOBLADA = {"tronco": 99, "cuello": -30, "piernas": 13, "brazo": 102, "antebrazo": 12, "muneca": 18, "brazo_vertical": 3}
PROFUNDA = {"tronco": 56, "cuello": -40, "piernas": 110, "brazo": 82, "antebrazo": 14, "muneca": 13, "brazo_vertical": 30}
SILLA = {"tronco": 15, "cuello": 5, "piernas": 45, "brazo": 30, "antebrazo": 80, "muneca": 5, "brazo_vertical": 20}


def test_sin_intentos_no_hay_correcciones():
    assert sugerir_correcciones(Visita()) == []


@pytest.mark.parametrize("espalda, rodillas, mensaje", [
    (95, 20, "Espalda doblada 95°. En el siguiente intento, flexiona las rodillas"),
    (45, 110, "Las piernas hicieron el esfuerzo. Espalda a 45°: intenta mantenerla más recta"),
    (40, 20, "Espalda inclinada 40°. En el siguiente intento, flexiona más las rodillas"),
    (15, 100, "Espalda recta: buena técnica"),
])
def test_correcciones_tras_el_primer_intento_segun_la_tecnica(espalda, rodillas, mensaje):
    visita = Visita()
    visita.registrar(calcular_reba(DOBLADA), 2.0, espalda_max=espalda, rodillas_max=rodillas)
    assert sugerir_correcciones(visita) == [mensaje]


def test_espalda_mas_recta_pero_reba_no_baja_se_dice_tal_cual():
    visita = _visita(DOBLADA, PROFUNDA)
    comparacion = visita.comparacion()
    assert comparacion.texto_espalda() == "Flexión de espalda: 99° → 56°"
    assert comparacion.diferencia_espalda == -43 and comparacion.piernas_cargan_mas and comparacion.diferencia >= 0
    assert sugerir_correcciones(visita) == ["Espalda 43° más recta. REBA no baja: ahora cargan las rodillas"]


def test_correcciones_al_comparar_dos_intentos():
    # Las correcciones describen la postura; no regañan a la persona
    assert sugerir_correcciones(_visita(PROFUNDA, DOBLADA)) == ["La espalda se dobló más esta vez. Inténtalo de nuevo"]
    assert sugerir_correcciones(_visita(DOBLADA, {**DOBLADA, "tronco": 93}))[0].startswith("Espalda parecida.")
    visita = _visita(DOBLADA, SILLA)
    assert visita.comparacion().diferencia < 0
    assert sugerir_correcciones(visita) == ["Espalda 84° más recta y REBA más bajo"]


def test_espalda_en_extension_se_muestra_como_cero():
    visita = Visita()
    intento = visita.registrar(calcular_reba({"tronco": -8, "cuello": 5, "piernas": 0, "brazo": 0, "antebrazo": 80}), 1)
    assert intento.espalda == 0


# --------------------------------------------------------------------------- #
# Pista contextual y resultado del intento en el panel
# --------------------------------------------------------------------------- #
PISTAS = cargar_mensajes()["pistas"]


def test_tras_un_levantamiento_desde_el_piso_van_las_correcciones_y_luego_la_pista():
    flujo = Flujo()
    sim = Simulacion(flujo)
    sim.avanzar(DE_PIE, 1.0)
    assert flujo.pista(sim.t) is None and flujo.resultado_reciente(sim.t) is None  # antes de levantar, nada
    sim.avanzar(ESPALDA_DOBLADA, 1.0)
    assert flujo.pista(sim.t) is None  # mientras levanta, tampoco
    sim.avanzar(DE_PIE, 1.5)
    intento = sim.intentos[0]
    assert intento.desde_piso is True and intento.puntaje >= 4
    assert flujo.instruccion(sim.t, CONFIG) == "Espalda doblada 95°. En el siguiente intento, flexiona las rodillas"
    assert flujo.pista(sim.t) == PISTAS["desde_piso"]
    # El panel muestra el resultado del intento, no la postura de pie en vivo
    mostrado, angulos, neutra = flujo.resultado_reciente(sim.t)
    assert mostrado is intento and angulos.tronco == pytest.approx(95, abs=1) and neutra == (0.0, 0.0)
    # Pasado el tiempo del resultado vuelven la instrucción normal y la postura en vivo
    sim.avanzar(DE_PIE, flujo.segundos_resultado)
    assert flujo.pista(sim.t) is None and flujo.resultado_reciente(sim.t) is None
    assert flujo.instruccion(sim.t, CONFIG) == "Levanta la caja del piso a la mesa"


def test_al_empezar_otro_levantamiento_se_deja_de_mostrar_el_resultado_anterior():
    flujo = Flujo()
    sim = Simulacion(flujo)
    sim.levantar(ESPALDA_DOBLADA)
    assert flujo.resultado_reciente(sim.t) is not None
    sim.avanzar(ESPALDA_DOBLADA, 0.5)
    assert flujo.maquina.estado is Estado.LEVANTANDO
    assert flujo.resultado_reciente(sim.t) is None and flujo.pista(sim.t) is None


ELEVADA_DOBLADA = dict(tronco=70, cuello=-15, rodilla=10, brazo=40, codo=30)  # la carga está a media altura
ELEVADA_RECTA = dict(tronco=28, cuello=5, rodilla=10, brazo=20, codo=70)


def test_carga_elevada_y_reba_mas_bajo_da_la_pista_de_control_de_ingenieria():
    flujo = Flujo()
    sim = Simulacion(flujo)
    sim.levantar(ELEVADA_DOBLADA)
    primero = sim.intentos[0]
    assert primero.desde_piso is False  # las muñecas no bajaron de las rodillas
    assert flujo.pista(sim.t) is None  # un solo intento con la carga elevada: no hay pista
    sim.levantar(ELEVADA_RECTA)
    segundo = sim.intentos[1]
    assert segundo.desde_piso is False and segundo.puntaje < primero.puntaje
    assert flujo.pista(sim.t) == PISTAS["carga_elevada"]


def test_carga_elevada_sin_mejora_no_da_pista():
    flujo = Flujo()
    sim = Simulacion(flujo)
    sim.levantar(ELEVADA_RECTA)
    sim.levantar(ELEVADA_DOBLADA)
    assert sim.intentos[1].puntaje > sim.intentos[0].puntaje
    assert flujo.pista(sim.t) is None


# --------------------------------------------------------------------------- #
# Postura neutra, técnica y desde_piso en el evento
# --------------------------------------------------------------------------- #
def test_el_evento_declara_la_postura_neutra_usada():
    intento, analisis = _intento_y_angulos()
    datos = datos_evaluacion(intento, analisis.angulos, CONFIG, (-9.46, 28.04))
    assert datos["postura_neutra"] == {"tronco": -9.5, "cuello": 28.0}
    validar_evento(construir_evento("ergonomia", "evaluacion_reba", datos, severidad=intento.resultado.severidad))
    assert "postura_neutra" not in datos_evaluacion(intento, analisis.angulos, CONFIG)  # sin calibrar no se inventa


def test_el_intento_guarda_la_mayor_flexion_de_espalda_y_de_rodillas_del_levantamiento():
    flujo = Flujo()
    sim = Simulacion(flujo)
    sim.avanzar(DE_PIE, 1.0)
    sim.avanzar(dict(tronco=60, rodilla=20, brazo=60, codo=10), 0.8)  # bajando
    sim.avanzar(ESPALDA_DOBLADA, 1.0)                                  # abajo: 95° de espalda
    sim.avanzar(dict(tronco=30, rodilla=50, brazo=30, codo=40), 0.8)  # subiendo, con las rodillas a 50°
    sim.avanzar(DE_PIE, 2.0)
    intento = sim.intentos[0]
    assert intento.espalda == 95 and intento.rodillas == 50  # cada máximo ocurrió en un momento distinto
    assert intento.tecnica.nivel == "alta" and intento.tecnica.piernas == "poco_flexionadas"


def test_el_evento_lleva_la_tecnica_y_desde_piso_ademas_del_reba():
    resultado = calcular_reba(DOBLADA)
    analisis = Analizador(EstimadorFijo(postura(**ESPALDA_DOBLADA))).analizar(FRAME, 0, CONFIG)
    visita = Visita()
    intento = visita.registrar(resultado, 2.0, espalda_max=104.6, rodillas_max=28.2, desde_piso=True)
    datos = datos_evaluacion(intento, analisis.angulos, CONFIG)
    assert datos["desde_piso"] is True
    assert datos["tecnica"] == {"espalda_max": 104.6, "nivel_espalda": "alta", "rodillas_max": 28.2, "piernas": "rectas"}
    assert datos["puntaje"] == resultado.puntaje  # el REBA no cambia por la técnica
    validar_evento(construir_evento("ergonomia", "evaluacion_reba", datos, severidad=resultado.severidad))
    # Carga elevada: false. Sin poder saberlo: el campo no va
    elevada = visita.registrar(resultado, 2.0, desde_piso=False)
    assert datos_evaluacion(elevada, analisis.angulos, CONFIG)["desde_piso"] is False
    sin_saber = visita.registrar(resultado, 2.0)
    assert "desde_piso" not in datos_evaluacion(sin_saber, analisis.angulos, CONFIG)
