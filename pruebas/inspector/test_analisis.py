"""Análisis con Claude, siempre con un cliente simulado: ninguna prueba llama a la API."""

import base64
import json
from types import SimpleNamespace

import anthropic
import httpx2
import numpy as np
import pytest

from modulos.inspector.analisis import __main__ as consola
from modulos.inspector.analisis import (
    MENSAJE_RECHAZO,
    Analizador,
    CacheDeAnalisis,
    ErrorDeAnalisis,
    RegistroDeCostos,
    hash_de_foto,
)
from modulos.inspector.configuracion import Ajustes, leer_prompt
from modulos.inspector.ejemplo import leer_ejemplo
from modulos.inspector.nucleo.esquema import esquema_para_api
from modulos.inspector.nucleo.imagen import codificar_jpeg, decodificar

ANCHO, ALTO = 1568, 1176
FOTO = np.full((ALTO, ANCHO, 3), 120, np.uint8)
HASH = hash_de_foto(b"bytes de la foto original")
SOLICITUD_HTTP = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
CLAVE_FALSA = "sk-ant-clave-de-prueba-que-no-debe-aparecer"


class Reloj:
    """Reloj falso: el tiempo solo avanza cuando una llamada o una espera lo mueven."""

    def __init__(self) -> None:
        self.ahora = 1000.0
        self.esperas: list[float] = []

    def __call__(self) -> float:
        return self.ahora

    def dormir(self, segundos: float) -> None:
        self.esperas.append(segundos)
        self.ahora += segundos


class ClienteSimulado:
    """Hace de cliente de Anthropic: entrega en orden lo que se le preparó y guarda cada solicitud."""

    def __init__(self, *respuestas, reloj: Reloj | None = None, duracion: float = 8.0) -> None:
        self.pendientes = list(respuestas)
        self.solicitudes: list[dict] = []
        self.messages = self
        self._reloj = reloj
        self._duracion = duracion

    def create(self, **solicitud):
        self.solicitudes.append(solicitud)
        if self._reloj is not None:
            self._reloj.ahora += self._duracion
        siguiente = self.pendientes.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


def respuesta(datos=None, *, texto: str | None = None, stop_reason: str = "end_turn", entrada: int = 3000,
              salida: int = 1500, categoria: str | None = None):
    """Respuesta de la API con la forma que lee el módulo (el primer bloque es razonamiento vacío)."""
    if texto is None:
        texto = json.dumps(datos if datos is not None else leer_ejemplo("analisis_bodega.json"), ensure_ascii=False)
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=texto)],
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=categoria) if categoria else None,
        usage=SimpleNamespace(input_tokens=entrada, output_tokens=salida, cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
        model="claude-sonnet-5-5",
    )


def error_de_estado(clase, codigo: int, cabeceras: dict | None = None):
    return clase("mensaje del servicio", body=None,
                 response=httpx2.Response(codigo, request=SOLICITUD_HTTP, headers=cabeceras or {}))


@pytest.fixture
def reloj() -> Reloj:
    return Reloj()


@pytest.fixture
def registro(tmp_path) -> RegistroDeCostos:
    return RegistroDeCostos(tmp_path / "costos.csv")


@pytest.fixture
def cache(tmp_path) -> CacheDeAnalisis:
    return CacheDeAnalisis(tmp_path / "cache")


def analizador(cliente, reloj, registro=None, cache=None, **ajustes) -> Analizador:
    return Analizador(Ajustes(**ajustes), cliente=cliente, cache=cache, registro=registro, dormir=reloj.dormir,
                      reloj=reloj)


# --------------------------------------------------------------------------- #
# La solicitud
# --------------------------------------------------------------------------- #
def test_un_analisis_normal(reloj, registro):
    cliente = ClienteSimulado(respuesta(), reloj=reloj)
    resultado = analizador(cliente, reloj, registro).analizar(FOTO, analisis_id="insp-1")

    assert resultado.origen == "ia" and resultado.intentos == 1 and resultado.analisis_id == "insp-1"
    assert [peligro["n"] for peligro in resultado.analisis["peligros"]] == [1, 2, 3, 4, 5, 6]
    assert resultado.analisis["peligros"][0]["ubicacion"] == [round(640 / ANCHO, 4), round(100 / ALTO, 4),
                                                              round(920 / ANCHO, 4), round(950 / ALTO, 4)]
    assert (resultado.modelo, resultado.esfuerzo, resultado.prompt) == ("claude-sonnet-5-5", "medium", "sistema_v1")
    assert (resultado.ancho, resultado.alto) == (ANCHO, ALTO)
    assert (resultado.tokens_entrada, resultado.tokens_salida) == (3000, 1500)
    assert resultado.costo_usd == pytest.approx(3000 * 2 / 1e6 + 1500 * 10 / 1e6)  # 0,021 USD
    assert resultado.duracion_s == 8.0
    assert len(cliente.solicitudes) == 1


def test_la_solicitud_lleva_el_prompt_la_foto_y_el_esquema(reloj):
    cliente = ClienteSimulado(respuesta(), reloj=reloj)
    analizador(cliente, reloj).analizar(FOTO)
    solicitud = cliente.solicitudes[0]

    assert solicitud["model"] == "claude-sonnet-5-5"
    assert solicitud["system"] == leer_prompt("sistema_v1")
    assert solicitud["max_tokens"] == 16000
    assert solicitud["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": esquema_para_api()},
    }
    assert 0 < solicitud["timeout"] <= 60

    (mensaje,) = solicitud["messages"]
    imagen, texto = mensaje["content"]  # la imagen va antes que el texto
    assert mensaje["role"] == "user" and imagen["type"] == "image" and texto["type"] == "text"
    assert imagen["source"]["type"] == "base64" and imagen["source"]["media_type"] == "image/jpeg"
    enviada = decodificar(base64.standard_b64decode(imagen["source"]["data"]))
    assert enviada.shape == FOTO.shape  # exactamente la imagen preparada: las cajas vuelven en sus píxeles
    assert "1568 x 1176 píxeles" in texto["text"] and "como máximo 6 peligros" in texto["text"]


def test_la_solicitud_no_usa_lo_que_estos_modelos_rechazan_ni_el_respaldo_automatico(reloj):
    """Sin tool_choice forzado, sin temperatura, sin razonamiento manual y sin fallbacks (decisión del stand)."""
    cliente = ClienteSimulado(respuesta(), reloj=reloj)
    analizador(cliente, reloj).analizar(FOTO)
    assert set(cliente.solicitudes[0]) == {"model", "max_tokens", "system", "messages", "output_config", "timeout"}


def test_el_modelo_el_esfuerzo_y_el_maximo_de_peligros_salen_de_los_ajustes(reloj):
    cliente = ClienteSimulado(respuesta(), respuesta(), reloj=reloj)
    motor = analizador(cliente, reloj, modelo="claude-opus-5-5", esfuerzo="low", max_peligros=3)

    resultado = motor.analizar(FOTO)
    assert cliente.solicitudes[0]["model"] == "claude-opus-5-5"
    assert cliente.solicitudes[0]["output_config"]["effort"] == "low"
    assert "como máximo 3 peligros" in cliente.solicitudes[0]["messages"][0]["content"][1]["text"]
    assert len(resultado.analisis["peligros"]) == 3  # aunque el modelo devolvió 6
    assert resultado.costo_usd == pytest.approx(3000 * 4 / 1e6 + 1500 * 20 / 1e6)

    # Y se pueden cambiar para una sola llamada (así llegará la configuración remota)
    otro = motor.analizar(FOTO, ajustes=Ajustes(esfuerzo="high", max_peligros=5))
    assert cliente.solicitudes[1]["model"] == "claude-sonnet-5-5"
    assert cliente.solicitudes[1]["output_config"]["effort"] == "high"
    assert len(otro.analisis["peligros"]) == 5


def test_la_clave_no_viaja_en_la_solicitud_ni_queda_en_el_registro_ni_en_el_log(reloj, registro, monkeypatch, caplog):
    monkeypatch.setenv("ANTHROPIC_API_KEY", CLAVE_FALSA)
    cliente = ClienteSimulado(error_de_estado(anthropic.AuthenticationError, 401), reloj=reloj)
    with caplog.at_level("DEBUG"), pytest.raises(ErrorDeAnalisis) as error:
        analizador(cliente, reloj, registro).analizar(FOTO)

    assert CLAVE_FALSA not in json.dumps(cliente.solicitudes[0], default=str)
    assert CLAVE_FALSA not in registro.ruta.read_text(encoding="utf-8-sig")
    assert CLAVE_FALSA not in caplog.text
    assert CLAVE_FALSA not in error.value.mensaje and CLAVE_FALSA not in error.value.detalle


# --------------------------------------------------------------------------- #
# Validación de la salida y reintento
# --------------------------------------------------------------------------- #
def test_si_la_salida_no_cumple_el_esquema_se_reintenta_una_vez(reloj, registro):
    incompleto = leer_ejemplo("analisis_bodega.json")
    incompleto["peligros"][0].pop("evidencia_visible")
    cliente = ClienteSimulado(respuesta(incompleto, entrada=3000, salida=1400), respuesta(entrada=3000, salida=1600),
                              reloj=reloj)
    resultado = analizador(cliente, reloj, registro).analizar(FOTO, analisis_id="insp-2")

    assert len(cliente.solicitudes) == 2 and resultado.intentos == 2
    assert reloj.esperas == []  # el reintento por salida inválida es inmediato
    assert len(resultado.analisis["peligros"]) == 6
    # El costo de la foto incluye el intento fallido
    assert (resultado.tokens_entrada, resultado.tokens_salida) == (6000, 3000)
    assert resultado.costo_usd == pytest.approx(6000 * 2 / 1e6 + 3000 * 10 / 1e6)
    assert resultado.duracion_s == 16.0
    filas = registro.leer()
    assert [(fila["intento"], fila["resultado"]) for fila in filas] == [("1", "invalido"), ("2", "ok")]
    assert "evidencia_visible" in filas[0]["detalle"]
    assert filas[1]["peligros"] == "6"


@pytest.mark.parametrize(
    "mala",
    [
        respuesta(texto="{ esto no es json"),
        respuesta(texto=""),
        respuesta(texto='{"descripcion_general": "Bodega", "advertencias": [], "peli'),
        respuesta(stop_reason="max_tokens"),
        respuesta({"descripcion_general": "", "advertencias": [], "peligros": []}),
        respuesta({"resultado": "otra cosa"}),
    ],
    ids=["no_es_json", "sin_texto", "json_cortado", "max_tokens", "texto_vacio", "otra_forma"],
)
def test_dos_salidas_invalidas_seguidas_terminan_en_error_claro(reloj, registro, mala):
    cliente = ClienteSimulado(mala, mala, reloj=reloj)
    with pytest.raises(ErrorDeAnalisis) as error:
        analizador(cliente, reloj, registro).analizar(FOTO)

    assert error.value.codigo == "respuesta_invalida"
    assert error.value.mensaje == "El análisis no salió bien esta vez. Intenta de nuevo o usa una escena preparada."
    assert len(cliente.solicitudes) == 2  # un reintento, no más
    assert [fila["resultado"] for fila in registro.leer()] == ["invalido", "invalido"]


def test_un_analisis_sin_peligros_es_valido(reloj):
    vacio = {"descripcion_general": "Oficina ordenada, sin tareas en curso.", "advertencias": [], "peligros": []}
    resultado = analizador(ClienteSimulado(respuesta(vacio), reloj=reloj), reloj).analizar(FOTO)
    assert resultado.analisis["peligros"] == []


# --------------------------------------------------------------------------- #
# Rechazo del modelo
# --------------------------------------------------------------------------- #
def test_un_rechazo_da_el_mensaje_acordado_no_se_reintenta_y_queda_en_el_registro(reloj, registro):
    cliente = ClienteSimulado(respuesta(texto="No puedo ayudar con eso.", stop_reason="refusal",
                                        categoria="general_harms", entrada=2800, salida=40), reloj=reloj)
    with pytest.raises(ErrorDeAnalisis) as error:
        analizador(cliente, reloj, registro).analizar(FOTO, analisis_id="insp-3")

    assert MENSAJE_RECHAZO == "No pudimos analizar esta foto. Intenta con otra toma o usa una escena preparada."
    assert error.value.codigo == "rechazo" and error.value.mensaje == MENSAJE_RECHAZO
    assert len(cliente.solicitudes) == 1
    (fila,) = registro.leer()
    assert fila["resultado"] == "rechazo" and fila["analisis_id"] == "insp-3"
    assert fila["detalle"] == "categoría: general_harms"
    assert (fila["tokens_entrada"], fila["tokens_salida"]) == ("2800", "40")
    assert float(fila["costo_usd"]) == pytest.approx(2800 * 2 / 1e6 + 40 * 10 / 1e6)


def test_un_rechazo_no_se_guarda_en_la_cache(reloj, cache):
    cliente = ClienteSimulado(respuesta(texto="", stop_reason="refusal"), respuesta(), reloj=reloj)
    motor = analizador(cliente, reloj, cache=cache)
    with pytest.raises(ErrorDeAnalisis):
        motor.analizar(FOTO, hash_foto=HASH)
    assert motor.analizar(FOTO, hash_foto=HASH).origen == "ia"  # la siguiente vez se vuelve a intentar


# --------------------------------------------------------------------------- #
# Sin internet, tiempo máximo y fallas del servicio
# --------------------------------------------------------------------------- #
def test_sin_conexion_se_espera_y_se_reintenta(reloj, registro):
    cliente = ClienteSimulado(anthropic.APIConnectionError(request=SOLICITUD_HTTP), respuesta(), reloj=reloj,
                              duracion=1.0)
    resultado = analizador(cliente, reloj, registro).analizar(FOTO)

    assert resultado.intentos == 2 and reloj.esperas == [2.0]
    assert [fila["resultado"] for fila in registro.leer()] == ["error", "ok"]
    assert registro.leer()[0]["detalle"].startswith("sin_conexion")
    # El segundo intento solo dispone del tiempo que queda
    assert cliente.solicitudes[1]["timeout"] == pytest.approx(60 - 1 - 2)


def test_sin_conexion_dos_veces_termina_con_mensaje_claro(reloj):
    cliente = ClienteSimulado(anthropic.APIConnectionError(request=SOLICITUD_HTTP),
                              anthropic.APIConnectionError(request=SOLICITUD_HTTP), reloj=reloj, duracion=1.0)
    with pytest.raises(ErrorDeAnalisis) as error:
        analizador(cliente, reloj).analizar(FOTO)
    assert error.value.codigo == "sin_conexion"
    assert error.value.mensaje == ("No hay conexión a internet para analizar la foto. "
                                   "Intenta de nuevo o usa una escena preparada.")
    assert len(cliente.solicitudes) == 2


def test_si_se_agota_el_tiempo_maximo_no_hay_otro_intento(reloj, registro):
    cliente = ClienteSimulado(anthropic.APITimeoutError(request=SOLICITUD_HTTP), respuesta(), reloj=reloj,
                              duracion=20.0)
    with pytest.raises(ErrorDeAnalisis) as error:
        analizador(cliente, reloj, registro, tiempo_maximo_s=20).analizar(FOTO)

    assert error.value.codigo == "tiempo_agotado"
    assert error.value.mensaje == "El análisis tardó más de lo esperado. Intenta de nuevo o usa una escena preparada."
    assert len(cliente.solicitudes) == 1 and cliente.solicitudes[0]["timeout"] == 20
    assert registro.leer()[0]["resultado"] == "error"


def test_el_tiempo_maximo_es_configurable_y_cubre_el_reintento(reloj):
    cliente = ClienteSimulado(anthropic.APITimeoutError(request=SOLICITUD_HTTP), respuesta(), reloj=reloj,
                              duracion=10.0)
    resultado = analizador(cliente, reloj, tiempo_maximo_s=45, espera_reintento_s=1).analizar(FOTO)
    assert resultado.intentos == 2
    assert [solicitud["timeout"] for solicitud in cliente.solicitudes] == [45, pytest.approx(45 - 10 - 1)]


def test_con_limite_de_uso_se_respeta_la_espera_que_pide_el_servicio(reloj):
    cliente = ClienteSimulado(error_de_estado(anthropic.RateLimitError, 429, {"retry-after": "5"}), respuesta(),
                              reloj=reloj, duracion=1.0)
    assert analizador(cliente, reloj).analizar(FOTO).intentos == 2
    assert reloj.esperas == [5.0]


def test_si_la_espera_pedida_no_cabe_en_el_tiempo_maximo_se_avisa_sin_reintentar(reloj):
    cliente = ClienteSimulado(error_de_estado(anthropic.RateLimitError, 429, {"retry-after": "300"}), respuesta(),
                              reloj=reloj, duracion=1.0)
    with pytest.raises(ErrorDeAnalisis) as error:
        analizador(cliente, reloj).analizar(FOTO)
    assert error.value.codigo == "limite" and len(cliente.solicitudes) == 1
    assert reloj.esperas == [pytest.approx(59.0)]  # nunca espera más allá del tiempo máximo


@pytest.mark.parametrize(
    "error_api, codigo, llamadas",
    [
        (error_de_estado(anthropic.InternalServerError, 500), "servicio", 2),
        (error_de_estado(anthropic.InternalServerError, 529), "servicio", 2),
        (error_de_estado(anthropic.BadRequestError, 400), "solicitud", 1),
        (error_de_estado(anthropic.NotFoundError, 404), "solicitud", 1),
        (error_de_estado(anthropic.AuthenticationError, 401), "sin_clave", 1),
        (error_de_estado(anthropic.PermissionDeniedError, 403), "sin_clave", 1),
    ],
    ids=["500", "529", "400", "404", "401", "403"],
)
def test_fallas_del_servicio_se_reintentan_y_las_de_la_solicitud_no(reloj, error_api, codigo, llamadas):
    cliente = ClienteSimulado(error_api, error_api, reloj=reloj, duracion=1.0)
    with pytest.raises(ErrorDeAnalisis) as error:
        analizador(cliente, reloj).analizar(FOTO)
    assert error.value.codigo == codigo and len(cliente.solicitudes) == llamadas
    assert "escena preparada" in error.value.mensaje  # todos los mensajes ofrecen la salida sin internet


def test_sin_clave_en_el_equipo_no_se_intenta_llamar(monkeypatch, reloj):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    motor = Analizador(Ajustes(), dormir=reloj.dormir, reloj=reloj)  # sin cliente: lo crearía con la clave
    with pytest.raises(ErrorDeAnalisis) as error:
        motor.analizar(FOTO)
    assert error.value.codigo == "sin_clave"
    assert error.value.mensaje == "El análisis con IA no está configurado en este equipo. Usa una escena preparada."


# --------------------------------------------------------------------------- #
# Caché por foto
# --------------------------------------------------------------------------- #
def test_la_misma_foto_no_se_analiza_dos_veces(reloj, registro, cache):
    cliente = ClienteSimulado(respuesta(), reloj=reloj)
    motor = analizador(cliente, reloj, registro, cache)

    primero = motor.analizar(FOTO, hash_foto=HASH)
    segundo = motor.analizar(FOTO, hash_foto=HASH)

    assert len(cliente.solicitudes) == 1
    assert (primero.origen, segundo.origen) == ("ia", "cache")
    assert segundo.analisis == primero.analisis
    assert (segundo.tokens_entrada, segundo.tokens_salida, segundo.costo_usd, segundo.intentos) == (0, 0, 0.0, 0)
    filas = registro.leer()
    assert [fila["resultado"] for fila in filas] == ["ok", "cache"]
    assert float(filas[1]["costo_usd"]) == 0.0


@pytest.mark.parametrize(
    "cambio",
    [{"modelo": "claude-opus-5-5"}, {"esfuerzo": "low"}, {"max_peligros": 4}, {"prompt": "sistema_v2"}],
    ids=["modelo", "esfuerzo", "max_peligros", "prompt"],
)
def test_cambiar_un_ajuste_que_afecta_el_resultado_vuelve_a_analizar(reloj, cache, cambio, monkeypatch):
    monkeypatch.setattr("modulos.inspector.analisis.cliente.leer_prompt", lambda nombre: f"prompt {nombre}")
    cliente = ClienteSimulado(respuesta(), respuesta(), reloj=reloj)
    motor = analizador(cliente, reloj, cache=cache)
    motor.analizar(FOTO, hash_foto=HASH)
    assert motor.analizar(FOTO, hash_foto=HASH, ajustes=Ajustes(**cambio)).origen == "ia"
    assert len(cliente.solicitudes) == 2


def test_otra_foto_u_otro_tamano_de_imagen_no_usan_la_misma_entrada(reloj, cache):
    cliente = ClienteSimulado(respuesta(), respuesta(), respuesta(), reloj=reloj)
    motor = analizador(cliente, reloj, cache=cache)
    motor.analizar(FOTO, hash_foto=HASH)
    assert motor.analizar(FOTO, hash_foto=hash_de_foto(b"otra foto")).origen == "ia"
    alta = np.full((1659, 2212, 3), 120, np.uint8)  # la misma foto en alta resolución
    assert motor.analizar(alta, hash_foto=HASH).origen == "ia"
    assert len(cliente.solicitudes) == 3


def test_se_puede_pedir_un_analisis_nuevo_aunque_haya_cache(reloj, cache):
    cliente = ClienteSimulado(respuesta(), respuesta(), reloj=reloj)
    motor = analizador(cliente, reloj, cache=cache)
    motor.analizar(FOTO, hash_foto=HASH)
    assert motor.analizar(FOTO, hash_foto=HASH, usar_cache=False).origen == "ia"
    assert motor.analizar(FOTO, hash_foto=HASH).origen == "cache"  # y el nuevo quedó guardado
    assert len(cliente.solicitudes) == 2


def test_sin_huella_de_la_foto_no_hay_cache(reloj, cache):
    cliente = ClienteSimulado(respuesta(), respuesta(), reloj=reloj)
    motor = analizador(cliente, reloj, cache=cache)
    motor.analizar(FOTO)
    motor.analizar(FOTO)
    assert len(cliente.solicitudes) == 2 and not list(cache.carpeta.glob("*.json"))


def test_una_entrada_de_cache_danada_se_ignora(reloj, cache):
    cliente = ClienteSimulado(respuesta(), respuesta(), reloj=reloj)
    motor = analizador(cliente, reloj, cache=cache)
    motor.analizar(FOTO, hash_foto=HASH)
    (entrada,) = cache.carpeta.glob("*.json")
    entrada.write_text("{ archivo cortado", encoding="utf-8")
    assert motor.analizar(FOTO, hash_foto=HASH).origen == "ia"


def test_la_huella_depende_solo_del_contenido_de_la_foto():
    assert hash_de_foto(b"abc") == hash_de_foto(b"abc") != hash_de_foto(b"abd")
    assert len(hash_de_foto(b"abc")) == 64


# --------------------------------------------------------------------------- #
# Consola
# --------------------------------------------------------------------------- #
def test_la_consola_analiza_una_carpeta_y_guarda_la_foto_anotada(tmp_path, monkeypatch, capsys, reloj):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    escena = tmp_path / "escenas" / "bodega"
    escena.mkdir(parents=True)
    (escena / "foto.jpg").write_bytes(codificar_jpeg(np.full((900, 1200, 3), 120, np.uint8)))
    (escena / "escena.json").write_text("{}", encoding="utf-8")  # lo que no es foto se ignora
    cliente = ClienteSimulado(respuesta(), reloj=reloj)
    monkeypatch.setattr(consola, "Analizador",
                        lambda ajustes, **extra: Analizador(ajustes, cliente=cliente, dormir=reloj.dormir,
                                                            reloj=reloj, **extra))

    codigo = consola.main([str(tmp_path / "escenas"), "--esfuerzo", "low", "--salida", str(tmp_path / "salida")])

    assert codigo == 0 and len(cliente.solicitudes) == 1
    assert cliente.solicitudes[0]["output_config"]["effort"] == "low"
    salida = capsys.readouterr().out
    assert "esfuerzo low" in salida and "1200x900 px" in salida and "0.0210 USD" in salida
    assert "1. [alta] Trabajador sobre escalera de tijera" in salida and "Evidencia:" in salida
    assert (tmp_path / "salida" / "bodega" / "anotada.jpg").is_file()
    guardado = json.loads((tmp_path / "salida" / "bodega" / "analisis.json").read_text(encoding="utf-8"))
    assert len(guardado["analisis"]["peligros"]) == 6 and guardado["esfuerzo"] == "low"
    assert (tmp_path / "cola" / "inspector" / "costos.csv").is_file()


def test_la_consola_muestra_el_costo_promedio_por_foto(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    registro = RegistroDeCostos(tmp_path / "cola" / "inspector" / "costos.csv")
    for identificador, costo in (("a1", "0.030000"), ("a2", "0.050000")):
        registro.registrar(analisis_id=identificador, intento=1, modelo="claude-sonnet-5-5", resultado="ok",
                           costo_usd=costo, duracion_s="15.00", tokens_entrada=7000, tokens_salida=2000)

    assert consola.main(["--costos"]) == 0
    salida = capsys.readouterr().out
    assert "Fotos analizadas con la API: 2" in salida and "Costo promedio por foto: 0.0400 USD" in salida


def test_la_consola_avisa_cuando_no_puede_analizar(tmp_path, monkeypatch, capsys, reloj):
    monkeypatch.setenv("CARPETA_COLA", str(tmp_path / "cola"))
    foto = tmp_path / "taller.jpg"
    foto.write_bytes(codificar_jpeg(np.full((600, 800, 3), 120, np.uint8)))
    (tmp_path / "roto.jpg").write_bytes(b"no es una imagen")
    cliente = ClienteSimulado(respuesta(texto="", stop_reason="refusal"), reloj=reloj)
    monkeypatch.setattr(consola, "Analizador",
                        lambda ajustes, **extra: Analizador(ajustes, cliente=cliente, dormir=reloj.dormir,
                                                            reloj=reloj, **extra))

    codigo = consola.main([str(foto), str(tmp_path / "roto.jpg"), str(tmp_path / "no_existe.jpg")])

    salida = capsys.readouterr().out
    assert codigo == 1
    assert MENSAJE_RECHAZO in salida and "No se pudo leer la imagen" in salida and "No existe" in salida
