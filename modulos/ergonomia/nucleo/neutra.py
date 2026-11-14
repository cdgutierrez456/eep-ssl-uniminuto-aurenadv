"""Postura neutra de cada persona: el cero desde el que se miden tronco y cuello.

REBA mide los ángulos respecto a la postura neutra de pie. Con puntos clave de una cámara
esa postura no da 0°: el punto del hombro queda algo por detrás del de la cadera (el tronco
sale en unos −10°) y la oreja por delante del hombro (el cuello sale en unos 30°), aunque la
persona esté derecha. Sin corregirlo, estar de pie normalmente puntúa como "tronco en
extensión" y "cuello flexionado".

La corrección: mientras la persona está de pie y quieta un momento, se guardan su tronco y
su cuello como neutros, y a partir de ahí los ángulos se miden desde ese cero. Se calibra
una vez por persona. Puro, sin dependencias.
"""

from __future__ import annotations

from collections import deque
from statistics import median

# Topes del neutro: una postura de pie fuera de esto no se acepta como "neutra" completa,
# para no esconder una inclinación real (por ejemplo, alguien que espera encorvado)
LIMITE_TRONCO = 20.0
LIMITE_CUELLO = (-15.0, 50.0)


def _acotar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


class PosturaNeutra:
    """Calibra el tronco y el cuello neutros con la persona de pie y quieta."""

    def __init__(self, segundos_quieto: float = 0.7, tronco_maximo: float = 25.0,
                 rodilla_maxima: float = 25.0, variacion_maxima: float = 4.0) -> None:
        self.segundos_quieto = segundos_quieto  # cuánto debe estar quieta para calibrar
        self.tronco_maximo = tronco_maximo  # más inclinada que esto no es "de pie"
        self.rodilla_maxima = rodilla_maxima
        self.variacion_maxima = variacion_maxima  # grados que puede moverse el tronco en la ventana
        self.tronco = 0.0
        self.cuello = 0.0
        self.calibrada = False
        self._ventana: deque[tuple[float, float, float]] = deque()

    def actualizar(self, t: float, tronco: float | None, cuello: float | None,
                   rodilla: float | None) -> bool:
        """Recibe los ángulos crudos de un fotograma. Devuelve True si acaba de calibrarse."""
        if self.calibrada:
            return False
        de_pie = (None not in (tronco, cuello, rodilla) and abs(tronco) <= self.tronco_maximo
                  and rodilla <= self.rodilla_maxima)
        if not de_pie:
            self._ventana.clear()
            return False
        self._ventana.append((t, tronco, cuello))
        while len(self._ventana) > 1 and t - self._ventana[1][0] >= self.segundos_quieto:
            self._ventana.popleft()
        if t - self._ventana[0][0] < self.segundos_quieto:
            return False
        troncos = [muestra[1] for muestra in self._ventana]
        cuellos = [muestra[2] for muestra in self._ventana]
        if (max(troncos) - min(troncos) > self.variacion_maxima
                or max(cuellos) - min(cuellos) > 2 * self.variacion_maxima):
            self._ventana.popleft()  # se está moviendo: se sigue esperando
            return False
        self.tronco = _acotar(median(troncos), -LIMITE_TRONCO, LIMITE_TRONCO)
        self.cuello = _acotar(median(cuellos), *LIMITE_CUELLO)
        self.calibrada = True
        self._ventana.clear()
        return True

    def reiniciar(self) -> None:
        """Olvida la calibración (cambió la persona)."""
        self.tronco = self.cuello = 0.0
        self.calibrada = False
        self._ventana.clear()
