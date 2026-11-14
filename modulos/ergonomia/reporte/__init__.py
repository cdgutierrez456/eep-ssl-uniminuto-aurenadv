"""Reporte PDF de una página de una evaluación REBA.

``contenido`` arma lo que el reporte dice (puro, sin dependencias) y ``pdf`` lo maqueta con
fpdf2. ``pdf`` no se importa aquí para que el resto del módulo no dependa de fpdf2:
``from modulos.ergonomia.reporte.pdf import generar_reporte``.
"""

from .contenido import ContenidoReporte, DatosReporte, armar_contenido

__all__ = ["DatosReporte", "ContenidoReporte", "armar_contenido"]
