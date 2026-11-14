"""Núcleo puro del módulo de zona: geometría, homografía, estados y eventos.

Nada aquí usa cámaras, YOLO ni la plataforma: solo números. Uso típico::

    from modulos.zona.nucleo import MonitorZona, crear_zona

    zona = crear_zona("piso", poligono_normalizado, 1280, 720,
                      rectangulo_real={"ancho_m": 1.5, "largo_m": 1.0})
    monitor = MonitorZona(zona)
    resultado = monitor.actualizar(t, {id_persona: [tobillo_izquierdo, tobillo_derecho]})
    for evento in resultado.eventos:
        publicar("zona", evento.tipo, evento.datos, severidad=evento.severidad)
"""

from .clasificacion import Nivel, clasificar
from .estados import MonitorZona, Parametros, Resultado, VistaPersona
from .eventos import (
    EstadoZona,
    EventoZona,
    Textos,
    evento_casi_accidente,
    evento_estado_zona,
    evento_ingreso_zona,
)
from .geometria import (
    Poligono,
    Punto,
    desnormalizar,
    distancia_a_poligono,
    distancia_a_segmento,
    distancia_al_borde,
    es_convexo,
    es_poligono_valido,
    normalizar,
    punto_en_poligono,
)
from .homografia import Homografia, HomografiaInvalida, homografia_de_rectangulo, homografia_entre
from .zona import Medida, Zona, crear_zona

__all__ = [
    "MonitorZona",
    "Parametros",
    "Resultado",
    "VistaPersona",
    "EstadoZona",
    "EventoZona",
    "Textos",
    "evento_estado_zona",
    "evento_ingreso_zona",
    "evento_casi_accidente",
    "Nivel",
    "clasificar",
    "Zona",
    "Medida",
    "crear_zona",
    "Homografia",
    "HomografiaInvalida",
    "homografia_entre",
    "homografia_de_rectangulo",
    "Punto",
    "Poligono",
    "punto_en_poligono",
    "distancia_a_segmento",
    "distancia_al_borde",
    "distancia_a_poligono",
    "es_poligono_valido",
    "es_convexo",
    "normalizar",
    "desnormalizar",
]
