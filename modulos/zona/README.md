# Módulo de zona de peligro

Detecta personas que se acercan o entran a una zona de peligro marcada en el piso con cinta
amarilla, alrededor de una "máquina" simulada. Si alguien se acerca, la plataforma muestra un
aviso amarillo; si pisa la zona, suena la alarma y la pantalla se pone roja. Los acercamientos
que no llegan a entrar quedan registrados como casi-accidentes.

No hay ESP32 ni torre de luz: la alarma, visual y sonora, vive en la plataforma. La estación
publica eventos (`estado_zona`, `ingreso_zona`, `casi_accidente`) y tiene un respaldo visual
en su propia ventana.

> **En construcción.** Hoy está el núcleo (`nucleo/`): geometría, conversión a metros, estados
> y eventos, sin cámara. La calibración, la detección en vivo y el resto de este README llegan
> con las siguientes fases.

## Montaje

### La cámara

- Una webcam Logitech **alta, a unos 2 m, inclinada hacia abajo**. No cenital: vista desde
  justo encima, la persona tapa sus propios pies y el modelo de pose pierde los tobillos.
- Debe ver **la zona completa y su alrededor**: al menos la franja de advertencia (0,5 m por
  defecto) por los cuatro lados, y mejor 1 m, para ver a la gente llegar.
- Siempre en el mismo puerto USB (ver la sección "Cámaras" de `CLAUDE.md`).

### La zona

- Un **rectángulo** de cinta amarilla de peligro en el piso, con los cuatro lados rectos y las
  esquinas bien marcadas.
- **Mide el ancho y el largo** del rectángulo: con esas dos medidas las distancias y el margen
  de advertencia se dan en metros. Sin ellas todo funciona igual, en píxeles.

### La "máquina"

La caja que hace de máquina va dentro del rectángulo, y **no debe tapar a quien entra**:

- Que sea **baja** (por debajo de la rodilla), o
- que quede en **el lado de la zona más lejano a la cámara**, para que la gente entre por
  delante de ella y no por detrás.

Si alguien queda oculto detrás de la máquina, el módulo asume que sigue dentro: mantiene la
alarma 4 s (`segundos_perdida_peligro`) y, si vuelve a verse dentro de la zona en ese lapso,
lo trata como la misma persona y registra un solo ingreso. Pasados los 4 s sin verlo, cierra
el ingreso y la alarma se apaga aunque siga ahí. Por eso conviene que la máquina no tape.

## Núcleo

`modulos/zona/nucleo/` no usa cámara, YOLO ni la plataforma; se prueba con secuencias simuladas.

| Archivo | Qué hace |
|---|---|
| `geometria.py` | Punto en polígono y distancia de un punto a un polígono |
| `homografia.py` | Homografía imagen → piso: de píxeles a metros con las cuatro esquinas del rectángulo |
| `zona.py` | Arma la zona desde la configuración y mide a cada persona contra ella, en metros o en píxeles |
| `clasificacion.py` | Libre, advertencia o peligro, con histéresis |
| `estados.py` | Máquina de estados por persona y por zona, con antirrebote |
| `eventos.py` | Contenido de `estado_zona`, `ingreso_zona` y `casi_accidente` |

Reglas principales:

- **Peligro:** un pie dentro de la zona. **Advertencia:** el pie más cercano a menos del margen.
- **Antirrebote:** un cambio de estado se confirma cuando se sostiene 0,3 s.
- **Histéresis:** para bajar de nivel hay que alejarse 20 % más de lo que bastó para subir.
- **Personas que se dejan de ver:** conservan su estado 1 s; si estaban dentro de la zona, 4 s.

## Pruebas

```
.venv\Scripts\python -m pytest pruebas/zona
```
