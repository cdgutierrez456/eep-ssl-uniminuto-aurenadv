"""Servidor FastAPI mínimo que imita la API local de la plataforma.

HERRAMIENTA DE PRUEBA: existe solo para probar los módulos Python sin la
plataforma real (Next.js, carpeta plataforma/). No es parte del producto final.
"""

import asyncio
import json
import sqlite3
import sys
import threading
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jsonschema import Draft202012Validator

from modulos.comun.esquema import errores_de

ZONA_HORARIA = ZoneInfo("America/Bogota")
RUTA_PAGINA = Path(__file__).parent / "pagina.html"
RUTA_ALARMA = Path(__file__).parent / "alarma.html"
CARPETA_CONTRATO = Path(__file__).resolve().parents[2] / "contrato"
INTERVALO_RELOJ_SSE_S = 5.0  # cada cuánto el flujo SSE manda la hora del servidor (y de paso sigue vivo)


def _ahora() -> str:
    """Hora del servidor en ISO 8601 con milisegundos (America/Bogota)."""
    return datetime.now(ZONA_HORARIA).isoformat(timespec="milliseconds")


def _mensaje_sse(datos: Any, evento: str | None = None, identificador: str | None = None) -> str:
    """Un mensaje de Server-Sent Events: campos opcionales ``event`` e ``id`` y los datos en JSON de una línea."""
    cabecera = (f"event: {evento}\n" if evento else "") + (f"id: {identificador}\n" if identificador else "")
    return f"{cabecera}data: {json.dumps(datos, ensure_ascii=False)}\n\n"


class Difusor:
    """Reparte cada evento nuevo a los navegadores conectados a GET /api/stream.

    Los eventos llegan por un hilo (POST /api/eventos) y se entregan en el bucle asíncrono de
    cada conexión, cada una con su propia cola. Si un navegador se atrasa, pierde los más viejos.
    """

    MAXIMO_EN_COLA = 500

    def __init__(self) -> None:
        self._suscriptores: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._cerrojo = threading.Lock()

    def suscribir(self) -> tuple[asyncio.AbstractEventLoop, asyncio.Queue]:
        suscripcion = (asyncio.get_running_loop(), asyncio.Queue(maxsize=self.MAXIMO_EN_COLA))
        with self._cerrojo:
            self._suscriptores.add(suscripcion)
        return suscripcion

    def cancelar(self, suscripcion: tuple[asyncio.AbstractEventLoop, asyncio.Queue]) -> None:
        with self._cerrojo:
            self._suscriptores.discard(suscripcion)

    @property
    def conectados(self) -> int:
        with self._cerrojo:
            return len(self._suscriptores)

    def difundir(self, evento: dict) -> None:
        """Entrega el evento a todos los conectados. Se puede llamar desde cualquier hilo."""
        with self._cerrojo:
            suscriptores = list(self._suscriptores)
        for suscripcion in suscriptores:
            bucle, cola = suscripcion
            try:
                bucle.call_soon_threadsafe(self._poner, cola, evento)
            except RuntimeError:  # el bucle de esa conexión ya se cerró
                self.cancelar(suscripcion)

    @staticmethod
    def _poner(cola: asyncio.Queue, evento: dict) -> None:
        if cola.full():
            cola.get_nowait()
        cola.put_nowait(evento)


def _errores_de_config(modulo: str, config: Any) -> list[str]:
    """Valida la configuración contra contrato/config_<modulo>.schema.json, si ese esquema existe."""
    if not isinstance(config, dict):
        return ["la configuración debe ser un objeto JSON"]
    ruta = CARPETA_CONTRATO / f"config_{modulo}.schema.json"
    if not ruta.is_file():
        return []
    validador = Draft202012Validator(json.loads(ruta.read_text(encoding="utf-8")))
    errores = []
    for error in validador.iter_errors(config):
        campo = "/".join(str(parte) for parte in error.absolute_path) or "(raíz)"
        errores.append(f"{campo}: {error.message}")
    return errores


def _imprimir_evento(evento: dict) -> None:
    """Muestra el evento en consola en una línea legible."""
    hora = evento["timestamp"][11:19]
    sesion = f"  sesión {evento['sesion_id']}" if "sesion_id" in evento else ""
    datos = json.dumps(evento["datos"], ensure_ascii=False)
    if len(datos) > 160:
        datos = datos[:157] + "..."
    print(
        f"[{hora}] {evento['estacion'].upper():<10} {evento['tipo']:<18} "
        f"{evento['severidad'].upper():<8}{sesion}\n           {datos}",
        flush=True,
    )


def crear_app(carpeta_datos: str | Path = ".") -> FastAPI:
    """Crea la aplicación. En ``carpeta_datos`` quedan receptor.db y media/."""
    carpeta_datos = Path(carpeta_datos)
    carpeta_media = carpeta_datos / "media"
    carpeta_media.mkdir(parents=True, exist_ok=True)
    ruta_db = carpeta_datos / "receptor.db"

    # La consola de Windows puede no ser UTF-8: que una tilde nunca tumbe el servidor
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    def conectar() -> sqlite3.Connection:
        conexion = sqlite3.connect(ruta_db)
        conexion.row_factory = sqlite3.Row
        return conexion

    with closing(conectar()) as conexion, conexion:
        conexion.execute(
            """CREATE TABLE IF NOT EXISTS eventos (
                   id TEXT PRIMARY KEY,
                   estacion TEXT NOT NULL,
                   tipo TEXT NOT NULL,
                   instante REAL NOT NULL,      -- timestamp del evento en segundos UTC
                   recibido TEXT NOT NULL,
                   cuerpo TEXT NOT NULL         -- el evento completo en JSON
               )"""
        )
        conexion.execute(
            """CREATE TABLE IF NOT EXISTS modulos (
                   modulo TEXT PRIMARY KEY,
                   capacidades TEXT,            -- lo que el módulo dice que sabe hacer (JSON)
                   config TEXT,                 -- su configuración vigente (JSON)
                   actualizado TEXT
               )"""
        )

    def guardar_de_modulo(modulo: str, columna: str, valor: Any) -> None:
        ahora = datetime.now(ZONA_HORARIA).isoformat(timespec="seconds")
        with closing(conectar()) as conexion, conexion:
            conexion.execute("INSERT OR IGNORE INTO modulos (modulo) VALUES (?)", (modulo,))
            conexion.execute(
                f"UPDATE modulos SET {columna} = ?, actualizado = ? WHERE modulo = ?",
                (json.dumps(valor, ensure_ascii=False), ahora, modulo),
            )

    def leer_de_modulo(modulo: str, columna: str) -> Any:
        with closing(conectar()) as conexion:
            fila = conexion.execute(f"SELECT {columna} FROM modulos WHERE modulo = ?", (modulo,)).fetchone()
        if fila is None or fila[columna] is None:
            raise HTTPException(404, f"El módulo '{modulo}' no tiene {columna} registrada")
        return json.loads(fila[columna])

    app = FastAPI(title="Receptor de prueba SST en vivo", docs_url="/docs")
    app.mount("/media", StaticFiles(directory=carpeta_media), name="media")
    difusor = Difusor()
    app.state.difusor = difusor

    @app.post("/api/eventos", status_code=201)
    def recibir_eventos(cuerpo: Any = Body(...)):
        """Recibe un evento o un lote. Si alguno es inválido, no se guarda ninguno."""
        eventos = cuerpo if isinstance(cuerpo, list) else [cuerpo]
        fallos = []
        for indice, evento in enumerate(eventos):
            errores = errores_de(evento)
            if errores:
                id_evento = evento.get("id") if isinstance(evento, dict) else None
                fallos.append({"indice": indice, "id": id_evento, "errores": errores})
        if fallos:
            print(f"[RECHAZADO] {json.dumps(fallos, ensure_ascii=False)}", flush=True)
            return JSONResponse(status_code=422, content={"error": "Evento inválido", "detalle": fallos})

        recibido = datetime.now(ZONA_HORARIA).isoformat(timespec="seconds")
        nuevos = []
        with closing(conectar()) as conexion, conexion:
            for evento in eventos:
                instante = datetime.fromisoformat(evento["timestamp"]).timestamp()
                cursor = conexion.execute(
                    "INSERT OR IGNORE INTO eventos VALUES (?, ?, ?, ?, ?, ?)",
                    (evento["id"], evento["estacion"], evento["tipo"], instante, recibido,
                     json.dumps(evento, ensure_ascii=False)),
                )
                if cursor.rowcount:  # un id repetido se ignora (idempotencia)
                    nuevos.append(evento)
        for evento in nuevos:
            _imprimir_evento(evento)
            difusor.difundir(evento)  # empuje en tiempo real a quienes escuchan GET /api/stream
        return {"aceptados": [evento["id"] for evento in eventos]}

    @app.get("/api/stream")
    async def flujo_de_eventos():
        """Empuje en tiempo real (Server-Sent Events) de cada evento nuevo, tal como llegó.

        Cada evento sale como un mensaje sin nombre (``onmessage`` en el navegador) con su ``id``
        y el sobre completo en ``data``. Al conectar y cada pocos segundos sale además un mensaje
        ``reloj`` con la hora del servidor, para que la vista mida la antigüedad de los eventos
        sin depender del reloj del navegador.
        """
        suscripcion = difusor.suscribir()

        async def generar():
            try:
                yield _mensaje_sse({"ahora": _ahora()}, evento="reloj")
                while True:
                    try:
                        evento = await asyncio.wait_for(suscripcion[1].get(), INTERVALO_RELOJ_SSE_S)
                    except asyncio.TimeoutError:
                        yield _mensaje_sse({"ahora": _ahora()}, evento="reloj")
                    else:
                        yield _mensaje_sse(evento, identificador=evento["id"])
            finally:
                difusor.cancelar(suscripcion)

        return StreamingResponse(generar(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/eventos")
    def consultar_eventos(desde: str | None = None, estacion: str | None = None, limite: int = 500):
        """Eventos en orden cronológico. Con ``limite`` devuelve los más recientes."""
        condiciones, parametros = [], []
        if desde:
            try:
                # En una URL el "+" de la zona horaria llega como espacio
                parametros.append(datetime.fromisoformat(desde.replace(" ", "+")).timestamp())
            except ValueError:
                raise HTTPException(422, "El parámetro 'desde' debe ser una fecha ISO 8601")
            condiciones.append("instante >= ?")
        if estacion:
            condiciones.append("estacion = ?")
            parametros.append(estacion)
        donde = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
        with closing(conectar()) as conexion:
            filas = conexion.execute(
                f"SELECT cuerpo FROM eventos {donde} ORDER BY instante DESC, rowid DESC LIMIT ?",
                (*parametros, max(1, min(limite, 5000))),
            ).fetchall()
        return [json.loads(fila["cuerpo"]) for fila in reversed(filas)]

    @app.post("/api/medios", status_code=201)
    def recibir_medio(archivo: UploadFile = File(...)):
        """Guarda el archivo en media/AAAA-MM-DD/ y devuelve la ruta para adjuntos."""
        fecha = datetime.now(ZONA_HORARIA).strftime("%Y-%m-%d")
        extension = Path(archivo.filename or "").suffix.lower()
        nombre = f"{uuid.uuid4().hex[:8]}{extension}"
        (carpeta_media / fecha).mkdir(parents=True, exist_ok=True)
        (carpeta_media / fecha / nombre).write_bytes(archivo.file.read())
        ruta = f"media/{fecha}/{nombre}"
        print(f"[MEDIO] {archivo.filename} -> {ruta}", flush=True)
        return {"ruta": ruta}

    @app.put("/api/modulos/{modulo}/capacidades")
    def registrar_capacidades(modulo: str, capacidades: Any = Body(...)):
        """El módulo declara qué sabe hacer (para EPP: perfiles y elementos detectables)."""
        guardar_de_modulo(modulo, "capacidades", capacidades)
        print(f"[CAPACIDADES] {modulo}: {json.dumps(capacidades, ensure_ascii=False)[:200]}", flush=True)
        return {"modulo": modulo}

    @app.get("/api/modulos/{modulo}/capacidades")
    def consultar_capacidades(modulo: str):
        return leer_de_modulo(modulo, "capacidades")

    @app.get("/api/modulos/{modulo}/config")
    def consultar_config(modulo: str):
        """Configuración vigente del módulo. 404 si todavía no hay ninguna."""
        return leer_de_modulo(modulo, "config")

    @app.put("/api/modulos/{modulo}/config")
    def guardar_config(modulo: str, config: Any = Body(...)):
        """Guarda la configuración; la escriben la página (operador) y el propio módulo (teclado)."""
        errores = _errores_de_config(modulo, config)
        if errores:
            return JSONResponse(status_code=422, content={"error": "Configuración inválida", "detalle": errores})
        guardar_de_modulo(modulo, "config", config)
        print(f"[CONFIG] {modulo}: {json.dumps(config, ensure_ascii=False)[:200]}", flush=True)
        return config

    @app.get("/api/modulos")
    def consultar_modulos():
        """Capacidades y configuración de todos los módulos registrados (para la página)."""
        with closing(conectar()) as conexion:
            filas = conexion.execute("SELECT * FROM modulos ORDER BY modulo").fetchall()
        return {
            fila["modulo"]: {
                "capacidades": json.loads(fila["capacidades"]) if fila["capacidades"] else None,
                "config": json.loads(fila["config"]) if fila["config"] else None,
                "actualizado": fila["actualizado"],
            }
            for fila in filas
        }

    @app.get("/api/salud")
    def salud():
        """Estado del receptor y último latido de cada módulo."""
        with closing(conectar()) as conexion:
            total = conexion.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
            latidos = conexion.execute(
                "SELECT cuerpo FROM eventos WHERE tipo = 'estado_modulo' ORDER BY instante"
            ).fetchall()
        modulos = {}
        for fila in latidos:
            evento = json.loads(fila["cuerpo"])
            modulos[evento["datos"]["modulo"]] = {
                "estado": evento["datos"]["estado"],
                "ultimo_latido": evento["timestamp"],
            }
        return {"estado": "ok", "eventos": total, "modulos": modulos, "ahora": _ahora()}

    @app.get("/", response_class=HTMLResponse)
    def pagina():
        return RUTA_PAGINA.read_text(encoding="utf-8")

    @app.get("/alarma", response_class=HTMLResponse)
    def alarma():
        """Vista de alarma de la zona de peligro, a pantalla completa (visual y sonora)."""
        return RUTA_ALARMA.read_text(encoding="utf-8")

    return app
