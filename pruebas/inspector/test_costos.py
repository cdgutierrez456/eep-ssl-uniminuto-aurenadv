"""Registro de costos, ajustes del .env y reglas del prompt del sistema."""

import re

import pytest

from modulos.inspector.analisis.costos import COLUMNAS, RegistroDeCostos, costo_usd, resumir, texto_del_resumen
from modulos.inspector.configuracion import CARPETA_PROMPTS, Ajustes, hay_clave, leer_prompt
from modulos.inspector.nucleo.esquema import CATEGORIAS, JERARQUIA


# --------------------------------------------------------------------------- #
# Costo de una llamada
# --------------------------------------------------------------------------- #
def test_costo_por_modelo():
    assert costo_usd("claude-sonnet-5-5", 1_000_000, 0) == 2.0
    assert costo_usd("claude-sonnet-5-5", 0, 1_000_000) == 10.0
    assert costo_usd("claude-opus-5-5", 1_000_000, 1_000_000) == 24.0
    assert costo_usd("claude-sonnet-5-5", 3000, 1500) == pytest.approx(0.021)
    assert costo_usd("claude-sonnet-5-5", 0, 0) == 0.0


def test_un_modelo_sin_precio_no_tiene_costo_estimado():
    assert costo_usd("otro-modelo", 1000, 1000) is None


def test_los_precios_se_pueden_editar(tmp_path):
    ruta = tmp_path / "precios.json"
    ruta.write_text('{"modelo-x": {"entrada": 1.0, "salida": 5.0}}', encoding="utf-8")
    assert costo_usd("modelo-x", 2_000_000, 1_000_000, ruta_precios=ruta) == 7.0
    # Sin precio de caché configurado, esos tokens se cobran como entrada
    assert costo_usd("modelo-x", 0, 0, lectura_cache=1_000_000, ruta_precios=ruta) == 1.0


# --------------------------------------------------------------------------- #
# Registro en CSV y resumen
# --------------------------------------------------------------------------- #
def fila(analisis_id, resultado, costo=0.0, duracion=10.0, intento=1, modelo="claude-sonnet-5-5", **extra):
    return {"analisis_id": analisis_id, "intento": intento, "modelo": modelo, "esfuerzo": "medium", "ancho": 1568,
            "alto": 1176, "tokens_entrada": 3000, "tokens_salida": 1500, "costo_usd": f"{costo:.6f}",
            "duracion_s": f"{duracion:.2f}", "resultado": resultado, **extra}


def test_el_registro_escribe_una_fila_por_llamada_con_encabezado(tmp_path):
    registro = RegistroDeCostos(tmp_path / "inspector" / "costos.csv")
    assert registro.leer() == []

    escrita = registro.registrar(**fila("a1", "ok", 0.021, peligros=5))
    registro.registrar(**fila("a2", "rechazo", 0.006, detalle="categoría: general_harms"))

    assert escrita["fecha"]  # la fecha la pone el registro
    texto = registro.ruta.read_text(encoding="utf-8-sig")
    assert texto.splitlines()[0] == ",".join(COLUMNAS)
    assert list(COLUMNAS[:4]) == ["fecha", "analisis_id", "intento", "modelo"]
    assert {"tokens_entrada", "tokens_salida", "costo_usd", "duracion_s"} <= set(COLUMNAS)
    filas = registro.leer()
    assert [(f["analisis_id"], f["resultado"], f["modelo"]) for f in filas] == [
        ("a1", "ok", "claude-sonnet-5-5"), ("a2", "rechazo", "claude-sonnet-5-5")]
    assert filas[0]["peligros"] == "5" and filas[1]["detalle"] == "categoría: general_harms"
    assert filas[0]["fecha"].endswith("-05:00")  # hora de Colombia


def test_si_el_csv_no_se_puede_escribir_el_analisis_sigue(tmp_path, caplog):
    carpeta = tmp_path / "ocupada"
    carpeta.mkdir()
    registro = RegistroDeCostos(carpeta)  # la ruta es una carpeta: no se puede abrir como archivo
    with caplog.at_level("WARNING"):
        registro.registrar(**fila("a1", "ok", 0.021))
    assert "No se pudo escribir el registro de costos" in caplog.text


def test_el_registro_queda_en_el_log(tmp_path, caplog):
    with caplog.at_level("INFO"):
        RegistroDeCostos(tmp_path / "costos.csv").registrar(**fila("a1", "ok", 0.021))
    assert "a1" in caplog.text and "claude-sonnet-5-5" in caplog.text and "0.021000 USD" in caplog.text


def test_el_costo_promedio_por_foto_incluye_reintentos_y_rechazos():
    filas = [
        fila("a1", "ok", 0.020, 12.0),
        fila("a2", "invalido", 0.018, 11.0),
        fila("a2", "ok", 0.022, 13.0, intento=2),          # la misma foto, segundo intento
        fila("a3", "rechazo", 0.006, 3.0),
        fila("a4", "error", 0.0, 2.0, detalle="sin_conexion"),
        fila("a5", "cache", 0.0, 0.0, intento=0),
        fila("a6", "ok", 0.050, 20.0, modelo="claude-opus-5-5"),
    ]
    resumen = resumir(filas)

    assert resumen["fotos_analizadas"] == 3 and resumen["llamadas"] == 6 and resumen["desde_cache"] == 1
    assert (resumen["rechazos"], resumen["invalidos"], resumen["errores"]) == (1, 1, 1)
    assert resumen["costo_total_usd"] == pytest.approx(0.116)
    assert resumen["costo_promedio_por_foto_usd"] == pytest.approx(0.116 / 3, abs=1e-4)
    assert resumen["duracion_promedio_s"] == pytest.approx(15.0)  # solo las llamadas que salieron bien
    assert resumen["por_modelo"]["claude-opus-5-5"] == {"fotos": 1, "costo_usd": 0.05,
                                                        "costo_promedio_por_foto_usd": 0.05}
    assert resumen["por_modelo"]["claude-sonnet-5-5"]["fotos"] == 2

    texto = texto_del_resumen(resumen)
    assert "Costo promedio por foto: 0.0387 USD" in texto and "Rechazos: 1" in texto


def test_el_resumen_de_un_registro_vacio():
    resumen = resumir([])
    assert resumen["fotos_analizadas"] == 0 and resumen["costo_promedio_por_foto_usd"] is None
    assert "Costo promedio por foto: sin datos" in texto_del_resumen(resumen)


# --------------------------------------------------------------------------- #
# Ajustes
# --------------------------------------------------------------------------- #
VARIABLES = ("INSPECTOR_MODELO", "INSPECTOR_ESFUERZO", "INSPECTOR_MAX_PELIGROS", "INSPECTOR_TIEMPO_MAXIMO_S",
             "INSPECTOR_IMAGEN_LADO_MAX", "INSPECTOR_PROMPT")


def test_la_version_del_prompt_se_elige_en_el_env(sin_variables, monkeypatch, caplog):
    monkeypatch.setenv("INSPECTOR_PROMPT", "sistema_v1")
    assert Ajustes.desde_entorno().prompt == "sistema_v1"
    monkeypatch.setenv("INSPECTOR_PROMPT", "sistema_v99")  # no existe: se conserva el de por defecto
    with caplog.at_level("WARNING"):
        assert Ajustes.desde_entorno().prompt == "sistema_v1"
    assert "INSPECTOR_PROMPT" in caplog.text


@pytest.fixture
def sin_variables(monkeypatch):
    for variable in VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def test_ajustes_por_defecto(sin_variables):
    ajustes = Ajustes.desde_entorno()
    assert ajustes == Ajustes()
    assert (ajustes.modelo, ajustes.esfuerzo, ajustes.max_peligros) == ("claude-sonnet-5-5", "medium", 6)
    assert (ajustes.tiempo_maximo_s, ajustes.lado_max, ajustes.intentos) == (60.0, 1568, 2)


def test_los_ajustes_salen_del_entorno(sin_variables, monkeypatch):
    monkeypatch.setenv("INSPECTOR_MODELO", "claude-opus-5-5")
    monkeypatch.setenv("INSPECTOR_ESFUERZO", "LOW")
    monkeypatch.setenv("INSPECTOR_MAX_PELIGROS", "4")
    monkeypatch.setenv("INSPECTOR_TIEMPO_MAXIMO_S", "45")
    monkeypatch.setenv("INSPECTOR_IMAGEN_LADO_MAX", "2576")
    ajustes = Ajustes.desde_entorno()
    assert (ajustes.modelo, ajustes.esfuerzo, ajustes.max_peligros) == ("claude-opus-5-5", "low", 4)
    assert (ajustes.tiempo_maximo_s, ajustes.lado_max) == (45.0, 2576)


def test_un_valor_que_no_sirve_se_ignora_con_un_aviso(sin_variables, monkeypatch, caplog):
    monkeypatch.setenv("INSPECTOR_ESFUERZO", "turbo")
    monkeypatch.setenv("INSPECTOR_MAX_PELIGROS", "muchos")
    monkeypatch.setenv("INSPECTOR_TIEMPO_MAXIMO_S", "-5")
    monkeypatch.setenv("INSPECTOR_IMAGEN_LADO_MAX", "9000")
    monkeypatch.setenv("INSPECTOR_PROMPT", "no_existe")
    with caplog.at_level("WARNING"):
        assert Ajustes.desde_entorno() == Ajustes()
    for variable in VARIABLES[1:]:
        assert variable in caplog.text


@pytest.mark.parametrize("cambio", [{"esfuerzo": "turbo"}, {"max_peligros": 0}, {"max_peligros": 13},
                                    {"tiempo_maximo_s": 0}, {"lado_max": 100}, {"lado_max": 3000}, {"modelo": " "}])
def test_ajustes_fuera_de_rango_se_rechazan(cambio):
    with pytest.raises(ValueError):
        Ajustes(**cambio)
    with pytest.raises(ValueError):
        Ajustes().con(**cambio)


def test_saber_si_hay_clave_sin_leerla(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert hay_clave() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    assert hay_clave() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-de-prueba")
    assert hay_clave() is True


# --------------------------------------------------------------------------- #
# Prompt del sistema
# --------------------------------------------------------------------------- #
def test_el_prompt_vive_en_un_archivo_versionado():
    assert (CARPETA_PROMPTS / "sistema_v1.md").is_file()
    assert leer_prompt() == leer_prompt("sistema_v1") and len(leer_prompt()) > 1500
    with pytest.raises(ValueError):
        leer_prompt("no_existe")


def test_el_prompt_trae_las_reglas_del_stand():
    prompt = leer_prompt()
    for regla in (
        "Solo peligros que se vean en la imagen",
        "confianza baja",
        "No cites leyes, resoluciones, decretos, normas técnicas, guías ni artículos",
        "con qué frecuencia se hace la tarea, cuántas personas la hacen y qué controles existen hoy",
        "No estimes ni menciones nada de eso",
        "español de Colombia",
        "del más grave al menos grave",
        "La caja es aproximada",
        "en píxeles de la imagen tal como la recibes",
        "No identifiques a las personas",
    ):
        assert regla in prompt, regla


def test_el_prompt_nombra_las_categorias_los_niveles_y_la_jerarquia_del_esquema():
    prompt = leer_prompt()
    for clave in (*CATEGORIAS, *JERARQUIA, "muy_alto", "alto", "medio", "bajo", "mortal", "muy_grave", "grave", "leve"):
        assert f"**{clave}**" in prompt or f"- {clave}:" in prompt, clave


def test_el_prompt_no_cita_normas_ni_fija_el_maximo_de_peligros():
    prompt = leer_prompt()
    assert not re.search(r"\b(GTC|NTC|ISO|OHSAS|ANSI|OSHA|Icontec)\b", prompt, re.IGNORECASE)
    assert not re.search(r"\b(Ley|Decreto|Resolución|Artículo)\s+\d", prompt, re.IGNORECASE)
    # El máximo llega en cada solicitud (es configurable); el archivo no lo fija
    assert not re.search(r"máximo\s+(de\s+)?\d+\s+peligros", prompt, re.IGNORECASE)
