"""Elección del dispositivo de cómputo: CPU, GPU o ``auto`` (GPU solo si está libre).

La GPU del equipo se comparte: puede estar entrenando un modelo o atendiendo a otro módulo.
``auto`` la usa solo si ``nvidia-smi`` la muestra desocupada; si no, se queda en CPU. La
decisión se toma una vez, al arrancar.
"""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

USO_MAXIMO = 25.0  # % de uso de la GPU por encima del cual se considera ocupada
MEMORIA_MAXIMA = 0.5  # fracción de memoria usada por encima de la cual se considera ocupada


def estado_de_gpu() -> tuple[float, float] | None:
    """Uso (%) y fracción de memoria ocupada de la primera GPU según ``nvidia-smi``; None si no se puede saber."""
    try:
        salida = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if salida.returncode != 0:
            return None
        uso, usada, total = (float(valor) for valor in salida.stdout.strip().splitlines()[0].split(","))
        return uso, (usada / total if total > 0 else 1.0)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def gpu_libre() -> tuple[bool, str]:
    """Si la GPU está desocupada, y el motivo en una frase."""
    estado = estado_de_gpu()
    if estado is None:
        return False, "nvidia-smi no responde"
    uso, memoria = estado
    if uso > USO_MAXIMO or memoria > MEMORIA_MAXIMA:
        return False, f"la GPU está ocupada ({uso:.0f} % de uso, {memoria * 100:.0f} % de memoria)"
    return True, f"la GPU está libre ({uso:.0f} % de uso, {memoria * 100:.0f} % de memoria)"


def _cuda_disponible() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except ImportError:
        return False


def resolver_dispositivo(pedido: str | None) -> tuple[str | int, str]:
    """Convierte lo pedido en ``ZONA_DISPOSITIVO`` en un dispositivo para Ultralytics, y dice por qué.

    - ``cpu`` (por defecto): siempre CPU.
    - ``auto``: GPU si hay una y está libre; si no, CPU.
    - ``gpu``, ``cuda`` o un número: esa GPU, esté como esté. Si no hay GPU, CPU.
    """
    pedido = (pedido or "cpu").strip().lower()
    if pedido == "cpu":
        return "cpu", "CPU (así está configurado)"
    if not _cuda_disponible():
        return "cpu", "CPU (PyTorch no ve ninguna GPU)"
    if pedido == "auto":
        libre, motivo = gpu_libre()
        return (0, f"GPU ({motivo})") if libre else ("cpu", f"CPU ({motivo})")
    if pedido in ("gpu", "cuda"):
        return 0, "GPU (así está configurado)"
    if pedido.isdigit():
        return int(pedido), f"GPU {pedido} (así está configurado)"
    log.warning("ZONA_DISPOSITIVO='%s' no se entiende (cpu, auto, gpu o un número); se usa CPU", pedido)
    return "cpu", "CPU (valor de ZONA_DISPOSITIVO no reconocido)"
