"""Arranque: python -m herramientas.receptor_prueba [--puerto 8000] [--datos carpeta]"""

import argparse
import os

import uvicorn

from .app import crear_app


def main() -> None:
    analizador = argparse.ArgumentParser(description="Receptor de prueba de la plataforma SST en vivo")
    analizador.add_argument("--host", default=os.getenv("RECEPTOR_HOST", "127.0.0.1"),
                            help="Use 0.0.0.0 para recibir eventos de otros equipos de la red")
    analizador.add_argument("--puerto", type=int, default=int(os.getenv("RECEPTOR_PUERTO", "8000")))
    analizador.add_argument("--datos", default=os.getenv("RECEPTOR_DATOS", "."),
                            help="Carpeta donde quedan receptor.db y media/")
    opciones = analizador.parse_args()

    print(f"Receptor de prueba (NO es la plataforma final) en http://{opciones.host}:{opciones.puerto}")
    uvicorn.run(crear_app(opciones.datos), host=opciones.host, port=opciones.puerto, log_level="warning")


if __name__ == "__main__":
    main()
