"""API HTTP del inspector. La consume la tablet (hoy la interfaz provisional, después la plataforma).

    POST /analizar        foto (o escena preparada) -> peligros propuestos
    POST /valorar/{id}    respuestas de la persona -> valoración, Excel y evento
    GET  /excel/{id}      la matriz IPEVR
    GET  /imagen/{id}     la foto anotada
    GET  /escenas         escenas preparadas (sin internet)
    GET  /opciones        textos y valores para pintar los formularios
    GET  /salud           estado del servicio

La clave de la API nunca sale de aquí: todas las llamadas a Claude las hace este servicio
y ninguna respuesta la incluye.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from .. import __version__
from ..analisis import Analizador, CacheDeAnalisis, ErrorDeAnalisis, RegistroDeCostos, hash_de_foto, resumir
from ..analisis.costos import NOMBRE_CSV
from ..configuracion import (
    MODULO,
    Ajustes,
    ajustes_con_config,
    carpeta_de_datos,
    config_por_defecto,
    hay_clave,
)
from ..nucleo.esquema import CATEGORIAS
from ..nucleo.excel import LEMA, generar_excel
from ..nucleo.imagen import ImagenInvalida, anotar, codificar_jpeg, decodificar, guardar_jpeg, miniatura, preparar_foto
from ..nucleo.matriz import RespuestasInvalidas, valorar_peligros
from ..nucleo.valoracion import cargar_parametros, peor_nivel, severidad_del_evento
from ..preparadas import CARPETA_ESCENAS, leer_escena, listar_escenas
from . import almacen as archivos
from .almacen import Almacen
from .publicacion import publicar_inspeccion

log = logging.getLogger(__name__)

RUTA_INTERFAZ = Path(__file__).resolve().parents[1] / "interfaz" / "index.html"
TAMANO_MAXIMO_FOTO = 25 * 1024 * 1024
MENSAJE_SOLO_ESCENAS = "El análisis con IA está apagado en este momento. Usa una escena preparada."
MENSAJE_SIN_FOTO = "Envía una foto o elige una escena preparada."


def crear_app(
    ajustes: Ajustes | None = None,
    *,
    analizador: Analizador | None = None,
    carpeta: str | Path | None = None,
    carpeta_escenas: str | Path | None = None,
    config: Callable[[], dict] | None = None,
    publicar_eventos: bool = True,
) -> FastAPI:
    """Crea el servicio.

    ``config`` devuelve la configuración operativa vigente (la remota, viva); sin ella se
    usa la del .env. ``analizador`` permite inyectar uno con cliente simulado en las pruebas.
    """
    ajustes = ajustes or Ajustes.desde_entorno()
    carpeta = Path(carpeta) if carpeta else carpeta_de_datos()
    carpeta_escenas = Path(carpeta_escenas) if carpeta_escenas else CARPETA_ESCENAS
    registro = RegistroDeCostos(carpeta / NOMBRE_CSV)
    analizador = analizador or Analizador(ajustes, cache=CacheDeAnalisis(carpeta / "cache"), registro=registro)
    almacen = Almacen(carpeta / "inspecciones")
    config_fija = config_por_defecto(ajustes)
    config = config or (lambda: config_fija)
    parametros = cargar_parametros()

    app = FastAPI(title="Inspector por foto · SST en vivo", version=__version__, docs_url="/docs")

    # ------------------------------------------------------------------ #
    def fallo(estado: int, error: str, mensaje: str, con_escenas: bool = False) -> JSONResponse:
        cuerpo: dict[str, Any] = {"error": error, "mensaje": mensaje}
        if con_escenas:
            cuerpo["escenas_preparadas"] = escenas_para_mostrar()
        return JSONResponse(status_code=estado, content=cuerpo)

    def escenas_para_mostrar() -> list[dict]:
        return [{"id": escena["id"], "nombre": escena["nombre"], "url_imagen": f"/escenas/{escena['id']}/imagen"}
                for escena in listar_escenas(carpeta_escenas, solo_listas=True)]

    def peligro_para_mostrar(peligro: dict) -> dict:
        clasificacion = peligro["clasificacion"]
        return {**peligro,
                "clasificacion": {**clasificacion, "nombre": CATEGORIAS[clasificacion["categoria"]]},
                "posible": peligro["confianza"] == "baja"}

    # ------------------------------------------------------------------ #
    @app.get("/salud")
    def salud():
        """Estado del servicio. Dice si hay clave, nunca cuál es."""
        vigente = config()
        resumen = resumir(registro.leer())
        return {
            "estado": "ok", "modulo": MODULO, "version": __version__,
            "modelo": vigente["modelo"],
            "ia_disponible": hay_clave() and not vigente["solo_escenas_preparadas"],
            "hay_clave": hay_clave(),
            "solo_escenas_preparadas": vigente["solo_escenas_preparadas"],
            "escenas_preparadas": len(escenas_para_mostrar()),
            "fotos_analizadas": resumen["fotos_analizadas"],
            "costo_promedio_por_foto_usd": resumen["costo_promedio_por_foto_usd"],
        }

    @app.get("/opciones")
    def opciones():
        """Valores y textos de los formularios: frecuencias, controles existentes, niveles y colores."""
        def lista(escala: str) -> list[dict]:
            return [{"id": clave, "nombre": nivel["etiqueta"], "valor": nivel["valor"]}
                    for clave, nivel in parametros[escala].items()]
        return {
            "aviso": LEMA,
            "frecuencias": lista("nivel_exposicion"),
            "niveles_deficiencia": lista("nivel_deficiencia"),
            "consecuencias": lista("nivel_consecuencia"),
            "controles_existentes": [{"id": clave, "nombre": control["etiqueta"]}
                                     for clave, control in parametros["controles_existentes"].items()],
            "niveles_riesgo": [{campo: tramo[campo] for campo in
                                ("id", "rango", "aceptabilidad", "significado", "color", "color_texto")}
                               for tramo in parametros["nivel_riesgo"]],
            "categorias": [{"id": clave, "nombre": nombre} for clave, nombre in CATEGORIAS.items()],
        }

    @app.get("/escenas")
    def escenas():
        """Escenas preparadas que ya tienen su análisis: sirven sin internet."""
        return escenas_para_mostrar()

    @app.get("/escenas/{escena_id}/imagen")
    def imagen_de_escena(escena_id: str):
        escena = leer_escena(escena_id, carpeta_escenas)
        if escena is None:
            return fallo(404, "escena_no_existe", "Esa escena preparada no existe.")
        try:
            mini = miniatura(decodificar(escena["ruta_foto"].read_bytes()), 900, 900)
        except (OSError, ImagenInvalida):
            return fallo(404, "escena_no_existe", "No se pudo leer la foto de esa escena.")
        return Response(codificar_jpeg(mini, 85), media_type="image/jpeg", headers={"Cache-Control": "max-age=300"})

    # ------------------------------------------------------------------ #
    @app.post("/analizar")
    def analizar(foto: UploadFile | None = File(None), escena_preparada: str | None = Form(None),
                 escena: str | None = Form(None), sesion_id: str | None = Form(None)):
        """Analiza una foto o carga una escena preparada. Devuelve la inspección con sus peligros propuestos."""
        vigente = config()
        if escena_preparada:
            preparada = leer_escena(escena_preparada, carpeta_escenas)
            if preparada is None or preparada["resultado"] is None:
                return fallo(404, "escena_no_existe", "Esa escena preparada no existe o aún no se ha precalculado.",
                             con_escenas=True)
            try:
                frame = preparar_foto(preparada["ruta_foto"].read_bytes(), ajustes.lado_max)
            except (OSError, ImagenInvalida) as error:
                return fallo(422, "imagen_invalida", str(error), con_escenas=True)
            analisis, origen = preparada["resultado"]["analisis"], "escena_preparada"
            modelo, duracion = preparada["resultado"].get("modelo"), 0.0
            escena = escena or preparada["nombre"]
        else:
            if foto is None:
                return fallo(422, "sin_foto", MENSAJE_SIN_FOTO, con_escenas=True)
            if vigente["solo_escenas_preparadas"]:
                return fallo(503, "solo_escenas", MENSAJE_SOLO_ESCENAS, con_escenas=True)
            original = foto.file.read(TAMANO_MAXIMO_FOTO + 1)
            if len(original) > TAMANO_MAXIMO_FOTO:
                return fallo(422, "imagen_invalida", "La foto pesa demasiado. Usa una de menos de 25 MB.")
            try:
                frame = preparar_foto(original, ajustes.lado_max)  # orientada, difuminada y reducida
            except ImagenInvalida as error:
                return fallo(422, "imagen_invalida", str(error))
            try:
                resultado = analizador.analizar(frame, hash_foto=hash_de_foto(original),
                                                ajustes=ajustes_con_config(ajustes, vigente))
            except ErrorDeAnalisis as error:
                log.warning("No se pudo analizar la foto: %s (%s)", error.codigo, error.detalle)
                return fallo(422 if error.codigo == "rechazo" else 503, error.codigo, error.mensaje, con_escenas=True)
            analisis, origen, modelo, duracion = resultado.analisis, resultado.origen, resultado.modelo, resultado.duracion_s

        inspeccion = almacen.crear(frame, analisis, origen=origen, modelo=modelo,
                                   escena=(escena or "").strip() or None,
                                   sesion_id=(sesion_id or "").strip() or None, duracion_s=duracion)
        return {
            "inspeccion_id": inspeccion["id"],
            "origen": origen,
            "modelo": modelo,
            "borrador": True,
            "aviso": LEMA,
            "duracion_s": duracion,
            "descripcion_general": analisis["descripcion_general"],
            "advertencias": analisis["advertencias"],
            "peligros": [peligro_para_mostrar(peligro) for peligro in analisis["peligros"]],
            "url_imagen": f"/imagen/{inspeccion['id']}",
            "ancho": inspeccion["ancho"], "alto": inspeccion["alto"],
        }

    @app.post("/valorar/{inspeccion_id}")
    def valorar(inspeccion_id: str, cuerpo: dict = Body(...)):
        """Aplica las respuestas de la persona, calcula la valoración, genera el Excel y publica el evento."""
        inspeccion = almacen.leer(inspeccion_id)
        if inspeccion is None:
            return fallo(404, "inspeccion_no_existe", "Esa inspección no existe. Toma la foto de nuevo.")
        contexto = cuerpo.get("contexto") if isinstance(cuerpo.get("contexto"), dict) else {}
        propuestos = inspeccion["analisis"]["peligros"]
        try:
            valorados = valorar_peligros(propuestos, cuerpo.get("peligros"), parametros)
        except RespuestasInvalidas as error:
            return fallo(422, "respuestas_invalidas", str(error))
        descartados = len(propuestos) - len(valorados)

        try:
            frame = decodificar(almacen.ruta(inspeccion_id, archivos.FOTO).read_bytes())
        except (OSError, ImagenInvalida):
            return fallo(404, "inspeccion_no_existe", "La foto de esa inspección ya no está. Toma la foto de nuevo.")
        final = anotar(frame, valorados)  # la foto ya está difuminada; las cajas van después
        ruta_imagen = guardar_jpeg(final, almacen.ruta(inspeccion_id, archivos.FINAL))
        ruta_excel = generar_excel(
            almacen.ruta(inspeccion_id, archivos.EXCEL), valorados,
            descripcion_general=inspeccion["analisis"]["descripcion_general"],
            advertencias=inspeccion["analisis"]["advertencias"], contexto=contexto, imagen=final,
            inspeccion_id=inspeccion_id, parametros=parametros)

        # El evento se publica una sola vez por inspección; si la persona corrige y vuelve a
        # generar, recibe el Excel nuevo pero el tablero no cuenta la inspección dos veces.
        publicado = False
        if publicar_eventos and not inspeccion.get("evento_id"):
            try:
                evento = publicar_inspeccion(inspeccion, valorados, descartados, contexto, ruta_imagen, ruta_excel)
                inspeccion["evento_id"], publicado = evento["id"], True
            except Exception:  # la persona no pierde su Excel porque falle la publicación
                log.exception("No se pudo publicar la inspección %s", inspeccion_id)

        niveles = [peligro["valoracion"]["nivel_riesgo"] for peligro in valorados]
        inspeccion["valoracion"] = {"peligros": valorados, "contexto": contexto, "descartados": descartados}
        almacen.guardar(inspeccion)
        return {
            "inspeccion_id": inspeccion_id,
            "borrador": True,
            "aviso": LEMA,
            "peligros": [peligro_para_mostrar(peligro) for peligro in valorados],
            "descartados": descartados,
            "resumen": {
                "peor_nivel": peor_nivel(niveles, parametros),
                "severidad": severidad_del_evento(niveles, parametros),
                "por_nivel": {tramo["id"]: niveles.count(tramo["id"]) for tramo in parametros["nivel_riesgo"]},
            },
            "url_excel": f"/excel/{inspeccion_id}",
            "url_imagen": f"/imagen/{inspeccion_id}",
            "evento_id": inspeccion.get("evento_id"),
            "publicado": publicado,
        }

    @app.get("/excel/{inspeccion_id}")
    def excel(inspeccion_id: str):
        if almacen.leer(inspeccion_id) is None or not almacen.ruta(inspeccion_id, archivos.EXCEL).is_file():
            return fallo(404, "sin_excel", "Esa inspección no tiene matriz todavía.")
        return FileResponse(
            almacen.ruta(inspeccion_id, archivos.EXCEL), filename=f"matriz-ipevr-{inspeccion_id}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get("/imagen/{inspeccion_id}")
    def imagen(inspeccion_id: str, limpia: bool = False):
        """La foto anotada: con los peligros que quedaron si ya se valoró; si no, con todos los propuestos.

        ``?limpia=1`` devuelve la foto sin cajas (siempre con los rostros difuminados), para
        una interfaz que prefiera dibujarlas ella con ``ubicacion``.
        """
        if almacen.leer(inspeccion_id) is None:
            return fallo(404, "inspeccion_no_existe", "Esa inspección no existe.")
        nombres = (archivos.FOTO,) if limpia else (archivos.FINAL, archivos.ANOTADA)
        for nombre in nombres:
            if almacen.ruta(inspeccion_id, nombre).is_file():
                return FileResponse(almacen.ruta(inspeccion_id, nombre), media_type="image/jpeg",
                                    headers={"Cache-Control": "no-store"})
        return fallo(404, "inspeccion_no_existe", "Esa inspección no tiene imagen.")

    @app.get("/", response_class=HTMLResponse)
    def interfaz():
        """Interfaz provisional para la tablet."""
        return RUTA_INTERFAZ.read_text(encoding="utf-8")

    return app
