"""Arranque de la estación de EPP: ``python -m modulos.epp``."""

from __future__ import annotations

import argparse
import logging
import sys

log = logging.getLogger("modulos.epp")


def main() -> int:
    analizador = argparse.ArgumentParser(
        prog="python -m modulos.epp", description="Estación en vivo de verificación de EPP por perfil"
    )
    analizador.add_argument("--camara", type=int, help="Índice de la cámara (por defecto EPP_CAMARA o 0)")
    analizador.add_argument("--ventana", action="store_true", help="Abrir en ventana en vez de pantalla completa")
    analizador.add_argument("--max-cuadros", type=int, help="Salir tras N cuadros (para pruebas)")
    opciones = analizador.parse_args()

    # La consola de Windows puede no ser UTF-8: que una tilde nunca tumbe el arranque
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(errors="replace")

    try:
        from .estacion import ErrorEstacion, Estacion
    except ImportError as error:
        print(f"Falta instalar una dependencia del módulo EPP ({error.name}). "
              'Instala con: pip install -e ".[epp]" (ver modulos/epp/README.md).', file=sys.stderr)
        return 1

    try:
        Estacion(opciones.camara, False if opciones.ventana else None, opciones.max_cuadros).ejecutar()
    except ErrorEstacion as error:
        print(f"\nNo se pudo iniciar la estación de EPP.\n{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nEstación detenida.")
    except Exception as error:  # sin traceback crudo en pantalla; el detalle queda en el log
        log.debug("Error inesperado", exc_info=True)
        print(f"\nLa estación de EPP se detuvo por un error inesperado: {type(error).__name__}: {error}\n"
              "Vuelve a iniciarla; si se repite, corre con LOG_NIVEL=DEBUG para ver el detalle.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
