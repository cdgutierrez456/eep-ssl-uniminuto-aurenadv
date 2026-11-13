"""Servidor FastAPI mínimo que imita la API local de la plataforma.

HERRAMIENTA DE PRUEBA: existe solo para probar los módulos Python sin la
plataforma real (Next.js, carpeta plataforma/). No es parte del producto final.
"""

import json
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from modulos.comun.esquema import errores_de

ZONA_HORARIA = ZoneInfo("America/Bogota")
RUTA_PAGINA = Path(__file__).parent / "pagina.html"


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

    app = FastAPI(title="Receptor de prueba SST en vivo", docs_url="/docs")
    app.mount("/media", StaticFiles(directory=carpeta_media), name="media")

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
        return {"aceptados": [evento["id"] for evento in eventos]}

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
        return {"estado": "ok", "eventos": total, "modulos": modulos}

    @app.get("/", response_class=HTMLResponse)
    def pagina():
        return RUTA_PAGINA.read_text(encoding="utf-8")

    return app
