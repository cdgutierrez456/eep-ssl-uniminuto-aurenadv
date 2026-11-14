"""Verificador de EPP: une perfiles, configuración, reglas, suavizado y visitas.

No usa cámara, modelos ni OpenCV: recibe las detecciones de un cuadro y devuelve qué
mostrar y si hay que publicar. La estación (estacion.py) le pone alrededor la cámara,
la ventana y la red; las pruebas le pasan detecciones simuladas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .nucleo import reglas as motor
from .nucleo.configuracion import capacidades_de, config_por_defecto, validar_config
from .nucleo.perfiles import reglas_de_perfil
from .nucleo.suavizado import SuavizadorTemporal
from .nucleo.visitas import Novedad, SeguidorDeVisitas


@dataclass
class Cuadro:
    """Resultado de procesar un cuadro."""

    principal: dict[str, Any] | None            # persona que se verifica (la más grande), o None
    otras: list[dict[str, Any]]                 # demás personas: se dibujan, no cuentan
    detecciones: list[dict[str, Any]]           # detecciones sobre umbral (para dibujar)
    novedad: Novedad = field(default_factory=Novedad)
    evento: dict[str, Any] | None = None        # datos de verificacion_epp si hay que publicar


class Verificador:
    """Estado de la verificación en vivo.

    ``clases_por_perfil`` trae las clases del modelo de cada perfil que sí cargó; un
    perfil ausente no está disponible.
    """

    def __init__(self, perfiles: dict[str, Any], clases_por_perfil: dict[str, list[str]],
                 segundos_estable: float = 2.0, segundos_sin_persona: float = 3.0) -> None:
        from .nucleo.perfiles import elementos_detectables

        self.perfiles = perfiles
        self.clases_por_perfil = {nombre: list(clases) for nombre, clases in clases_por_perfil.items()}
        self.capacidades = capacidades_de(perfiles, {
            nombre: elementos_detectables(perfiles, nombre, clases)
            for nombre, clases in self.clases_por_perfil.items()
        })
        self.config_por_defecto = config_por_defecto(perfiles, self.capacidades)
        self.visitas = SeguidorDeVisitas(segundos_estable, segundos_sin_persona)
        self.config: dict[str, Any] = {}
        self.reglas: dict[str, Any] = {}
        self.suavizador: SuavizadorTemporal
        self.aplicar_config(self.config_por_defecto)

    # ------------------------------------------------------------------ #
    @property
    def perfil_activo(self) -> str:
        return self.config["perfil_activo"]

    @property
    def requeridos(self) -> list[str]:
        return list(self.config["perfiles"][self.perfil_activo]["elementos_requeridos"])

    def validar(self, candidata: Any) -> tuple[dict[str, Any], list[str]]:
        """Normaliza una configuración candidata; lanza ConfigRechazada si no se puede aplicar."""
        return validar_config(candidata, self.capacidades, self.config_por_defecto)

    def aplicar_config(self, config: dict[str, Any]) -> bool:
        """Aplica una configuración ya validada. Devuelve si cambió algo.

        Al cambiar se reinician el suavizado temporal y el veredicto en curso.
        """
        if config == self.config:
            return False
        self.config = config
        self.reglas = reglas_de_perfil(
            self.perfiles, self.perfil_activo, self.requeridos, self.clases_por_perfil[self.perfil_activo]
        )
        self.suavizador = SuavizadorTemporal(self.reglas)
        self.visitas.reiniciar_veredicto()
        return True

    def con_perfil(self, nombre: str) -> dict[str, Any]:
        """Copia de la configuración vigente con otro perfil activo (cambio por teclado)."""
        return {**self.config, "perfil_activo": nombre}

    def datos_config(self) -> dict[str, Any]:
        """Datos del evento config_actualizada."""
        return {"perfil_activo": self.perfil_activo, "elementos_requeridos": self.requeridos}

    # ------------------------------------------------------------------ #
    def procesar(self, detecciones: list[dict[str, Any]], ahora: float) -> Cuadro:
        """Evalúa las detecciones de un cuadro (cajas normalizadas 0-1)."""
        instantaneo = motor.evaluar_cuadro(detecciones, self.reglas)
        suavizado = self.suavizador.procesar(instantaneo)
        personas = suavizado["personas"]
        # Solo se verifica a la persona principal: la de caja más grande (la más cercana)
        principal = max(personas, key=lambda p: motor.area(p["caja"]), default=None)
        otras = [p for p in personas if p is not principal]
        novedad = self.visitas.actualizar(ahora, principal)

        evento = None
        if novedad.publicar and principal is not None:
            requeridos = self.requeridos
            evento = {
                "perfil": self.perfil_activo,
                "requeridos": requeridos,
                "detectados": [e for e in requeridos if principal["elementos"][e]],
                "faltantes": list(principal["faltantes"]),
                "cumple": bool(principal["cumple"]),
            }
        sobre_umbral = motor.filtrar_por_umbral(
            motor.normalizar_detecciones(detecciones, self.reglas["umbral_confianza"]),
            self.reglas["umbral_confianza"],
        )
        return Cuadro(principal, otras, sobre_umbral, novedad, evento)
