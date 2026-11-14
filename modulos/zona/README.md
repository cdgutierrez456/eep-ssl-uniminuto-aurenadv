# Módulo de zona de peligro

Detecta personas que se acercan o entran a una zona de peligro marcada en el piso con cinta
amarilla, alrededor de una "máquina" simulada. Si alguien se acerca, la plataforma muestra un
aviso amarillo; si pisa la zona, suena la alarma y la pantalla se pone roja. Los acercamientos
que no llegan a entrar quedan registrados como casi-accidentes.

No hay ESP32 ni torre de luz: la alarma, visual y sonora, vive en la plataforma. La estación
publica eventos (`estado_zona`, `ingreso_zona`, `casi_accidente`) y tiene un respaldo visual
en su propia ventana.

## Probarlo todo junto

En dos terminales, desde la raíz del repositorio:

```
.venv\Scripts\python -m herramientas.receptor_prueba
```

```
.venv\Scripts\python -m modulos.zona --ventana
```

En el navegador, `http://localhost:8000/alarma` (pulsa **Activar sonido**) y
`http://localhost:8000` para el editor de zona. Al acercarse alguien a la zona la vista se
pone en precaución y pita lento; al entrar, se pone roja y pita rápido. El detalle de la vista
y del editor está en [`herramientas/receptor_prueba/README.md`](../../herramientas/receptor_prueba/README.md).

## Instalación

Usa el entorno compartido del repositorio (`.venv`), con PyTorch instalado como para EPP:

```
.venv\Scripts\python -m pip install -e ".[dev,zona]"
.venv\Scripts\python -m herramientas.descargar_modelos
```

El segundo comando baja el modelo de pose (`yolo26n-pose.pt`, 7,9 MB) a `modulos/zona/modelos/`.
Hay que correrlo una vez por equipo, con internet; después el módulo funciona sin red. El
modelo no se versiona: es público y se puede volver a bajar. Si falta, la estación no arranca
y dice cómo bajarlo.

## Montaje

### La cámara

- Una webcam Logitech **alta, a unos 2 m, inclinada hacia abajo**. No cenital: vista desde
  justo encima, la persona tapa sus propios pies y el modelo de pose pierde los tobillos.
- Debe ver **la zona completa y su alrededor**: al menos la franja de advertencia (0,5 m por
  defecto) por los cuatro lados, y mejor 1 m, para ver a la gente llegar.
- **Fija**, en un trípode o soporte firme. La zona se guarda como posiciones dentro de la
  imagen: si la cámara se mueve, la zona deja de coincidir con la cinta y hay que recalibrar.
- Siempre en el mismo puerto USB (ver la sección "Cámaras" de `CLAUDE.md`). Su índice va en
  `ZONA_CAMARA` del `.env`.

### La cinta

- Un **rectángulo** de cinta amarilla de peligro en el piso, con los cuatro lados rectos y las
  esquinas bien marcadas. Sirve la cinta amarilla y negra y la de "PELIGRO NO PASE".
- **Mide el ancho y el largo** del rectángulo, de borde exterior a borde exterior: con esas
  dos medidas las distancias y el margen de advertencia se dan en metros. Sin ellas todo
  funciona igual, en píxeles.
- Que el piso no sea amarillo ni haya objetos amarillos tocando la cinta.

### La "máquina"

La caja que hace de máquina va dentro del rectángulo, y **no debe tapar a quien entra**:

- Que sea **baja** (por debajo de la rodilla), o
- que quede en **el lado de la zona más lejano a la cámara**, para que la gente entre por
  delante de ella y no por detrás.

Si alguien queda oculto detrás de la máquina, el módulo asume que sigue dentro: mantiene la
alarma 4 s (`segundos_perdida_peligro`) y, si vuelve a verse dentro de la zona en ese lapso,
lo trata como la misma persona y registra un solo ingreso. Pasados los 4 s sin verlo, cierra
el ingreso y la alarma se apaga aunque siga ahí. Por eso conviene que la máquina no tape.

## Calibración paso a paso

Se hace en la ventana de la estación, con la zona vacía (sin personas y, mejor, antes de
poner la máquina):

1. **D** detecta la cinta. Si la encuentra, deja el polígono propuesto en pantalla, con los
   vértices numerados. Si no, dice por qué: no hay amarillo, solo ve objetos macizos, la
   cinta se sale de la imagen o no llega a cerrar una figura.
2. **Corrige con el mouse** lo que haga falta: clic agrega un vértice o agarra el que esté
   ahí, arrastrar lo mueve, clic derecho lo quita y **C** los borra todos. Si no hubo
   detección, **E** entra a la edición para marcar la zona a mano.
3. **G** guarda: desde ese momento esa es la zona activa. **Esc** cancela y deja la anterior.
4. **M** pide las medidas reales: primero el ancho (el lado del vértice 1 al 2, rotulado
   "ancho" en pantalla) y luego el largo (del 2 al 3). Se escriben con coma o punto y Enter.
   Dejarlas vacías las quita y la zona vuelve a medir en píxeles.

El panel dice en qué quedó la zona: cuántos vértices tiene y si mide en metros o en píxeles
(y por qué). Para medir en metros la zona debe tener cuatro vértices y sus dos medidas.

Desde la plataforma se hace lo mismo con el editor de zona: "Detectar zona" le pide la
detección a la estación, que responde con una propuesta; la persona la corrige y la guarda.

**Si alguien mueve la cámara**, repite los pasos 1 y 3 (D y G). Las medidas se conservan.

### Solo la calibración, sin detección de personas

```
.venv\Scripts\python -m modulos.zona.calibracion
```

Sirve para montar el stand en un equipo que todavía no tiene el modelo, o para revisar cómo
se ve la cinta. Opciones: `--ventana`, `--sin-plataforma`, `--imagen foto.jpg` o
`--video ruta.mp4` (en lugar de la cámara), `--detectar` (busca la cinta en el primer
fotograma) y `--captura archivo.png` (guarda la última pantalla al salir, difuminada). No la
corras a la vez que la estación: las dos atenderían los mismos pedidos de la plataforma.

### Si la detección no encuentra la cinta

- **Iluminación:** con poca luz o con sombras duras el amarillo pierde color. Fijar la
  exposición de la cámara (`ZONA_CAMARA_EXPOSICION`) ayuda a que se vea siempre igual.
- **Rango de color:** con **V** se ve qué toma por amarillo. El rango está en `cinta_hsv`
  de la configuración (tono de 18 a 38, saturación y brillo desde 80, en la escala de OpenCV).
- **Objetos amarillos:** un objeto macizo no se confunde con la zona, aunque sea más grande:
  la detección busca un marco hueco. Uno que toque la cinta sí puede deformarla.
- **Siempre queda marcarla a mano** con **E**: la detección es solo una ayuda.

## Correr la estación

```
.venv\Scripts\python -m modulos.zona
```

| Opción | Qué hace |
|---|---|
| `--video ruta.mp4` | Modo video: procesa un archivo en lugar de la cámara (`--repetir` lo vuelve a empezar) |
| `--ventana` | Abre en ventana, no a pantalla completa |
| `--sin-plataforma` | No consulta la plataforma ni publica eventos; la zona se guarda en este equipo |
| `--dispositivo cpu\|auto\|gpu` | Dónde corre la detección; por defecto, `ZONA_DISPOSITIVO` del `.env` |
| `--sin-ventana`, `--max-cuadros N`, `--captura archivo.png` | Para pruebas: procesar sin mostrar, terminar tras N fotogramas y guardar la última pantalla (difuminada) |

La pantalla muestra un aviso grande con el estado de la zona, la cámara en vivo con la zona
en rojo, la franja de advertencia en amarillo y los pies de cada persona con el color de su
estado, y un panel con los conteos de la sesión.

El modo video sirve para desarrollar sin estar frente a la cámara, con videos grabados con
`python -m herramientas.grabar_video --prefijo ZONA`. Esos videos son material de desarrollo:
se quedan en `datasets/videos/`, fuera de git.

### Teclas

| Tecla | Qué hace |
|---|---|
| **D** | Detecta la cinta y deja la propuesta lista para corregir |
| **E** | Entra a la edición de la zona con el mouse (o sale sin guardar) |
| Clic, arrastrar, clic derecho | En edición: agregar o agarrar un vértice, moverlo, quitarlo |
| **C** | En edición: borra todos los vértices |
| **G** o Enter | Guarda la zona editada y la activa |
| **M** | Pide las medidas reales del rectángulo (ancho y largo, en metros) |
| **R** | Toma una imagen de referencia nueva y la sube a la plataforma |
| **V** | Muestra en blanco lo que la detección toma por amarillo |
| **S** | Enciende o apaga el pitido de la propia estación (apagado por defecto) |
| **F** | Pantalla completa |
| **Q** o Esc | Salir (Esc dentro de la edición solo la cancela) |

### Qué publica

| Evento | Cuándo | Trae |
|---|---|---|
| `estado_zona` | Cada cambio de estado o de conteos; cada 2 s mientras la zona no esté libre (`refresco: true`) | Estado y personas en cada nivel |
| `ingreso_zona` | Cuando una persona sale de la zona de peligro | Duración, si la alarma estuvo activa y la foto del momento de entrada |
| `casi_accidente` | Cuando una persona entra a la franja de advertencia y se va sin pisar la zona | Distancia mínima (en metros si la zona está calibrada con medidas) y la foto del momento más cercano |

Las fotos llevan los rostros difuminados y, dibujados después, la zona y los pies de la
persona. El detalle de cada evento está en [`docs/cambios-contrato.md`](../../docs/cambios-contrato.md).

## Configuración

### Del equipo (`.env`)

| Variable | Por defecto | Qué es |
|---|---|---|
| `ZONA_CAMARA` | `0` | Índice de la cámara (o su nombre). También `ZONA_CAMARA_ANCHO`, `_ALTO`, `_FPS`, `_AUTOFOCO`, `_ENFOQUE` y `_EXPOSICION` |
| `ZONA_PANTALLA_COMPLETA` | `1` | Abrir a pantalla completa |
| `ZONA_PANTALLA_ANCHO`, `ZONA_PANTALLA_ALTO` | `1920`, `1080` | Tamaño de la pantalla del stand |
| `ZONA_DISPOSITIVO` | `cpu` | `cpu`, `auto` (GPU solo si está libre al arrancar) o `gpu` |
| `ZONA_IMGSZ` | `640` | Lado de la imagen que ve el detector |
| `ZONA_MODELO` | vacío | Otros pesos de pose; vacío usa `modulos/zona/modelos/yolo26n-pose.pt` |
| `API_URL`, `CARPETA_COLA`, `CONFIG_INTERVALO_S` | | Las comunes a todos los módulos |

### De la zona (remota)

Se ajusta en vivo desde la plataforma o desde la ventana de la estación, y la estación la
consulta cada pocos segundos. Su forma está en
[`contrato/config_zona.schema.json`](../../contrato/config_zona.schema.json) y sus valores
por defecto en [`config/por_defecto.json`](config/por_defecto.json).

| Clave | Por defecto | Qué es |
|---|---|---|
| `zona_peligro` | sin zona | Polígono activo, en coordenadas de 0 a 1 sobre la imagen |
| `rectangulo_real` | sin medidas | `ancho_m` y `largo_m` del rectángulo de cinta |
| `margen_advertencia_m` | 0,5 | Ancho de la franja de advertencia cuando la zona mide en metros |
| `margen_advertencia_px` | 80 | Lo mismo en píxeles, cuando no hay medidas |
| `deteccion.confianza_persona` | 0,4 | Confianza mínima para contar a una persona |
| `deteccion.confianza_punto` | 0,5 | Confianza mínima de un tobillo para usarlo como punto de apoyo |
| `deteccion.antirrebote_s` | 0,3 | Tiempo que debe sostenerse un nivel para cambiar de estado |
| `deteccion.histeresis` | 0,2 | Cuánto de más hay que alejarse para bajar de nivel |
| `deteccion.segundos_perdida` | 1 | Tiempo sin ver a alguien para darlo por retirado |
| `deteccion.segundos_perdida_peligro` | 4 | Lo mismo para quien se dejó de ver dentro de la zona |
| `deteccion.radio_reasociacion_m`, `_px` | 0,5 y 80 | Radio para reconocer a la misma persona si el tracker le cambia el id |
| `cinta_hsv` | 18 a 38, 80, 80 | Rango de amarillo de la cinta |
| `sonido_local` | apagado | Pitido en la propia estación |

Sin plataforma (`--sin-plataforma`) la configuración se guarda en
`CARPETA_COLA/config/zona.json` y sube sola la próxima vez que la estación corra con plataforma.

## Rendimiento y dispositivo

Medido en la PC de desarrollo (RTX 4050 de portátil) con un video de 1280x720:

| | CPU | GPU |
|---|---|---|
| Solo detección y seguimiento | 36 fps (27 ms) | 78 fps (13 ms) |
| Estación completa, publicando eventos | 27 fps | 46 fps |

En CPU alcanza para la cámara a 30 fps, así que `ZONA_DISPOSITIVO=cpu` es el valor por
defecto y la GPU queda libre para otros módulos. `auto` usa la GPU solo si `nvidia-smi` la
muestra desocupada al arrancar (menos de 25 % de uso y de la mitad de su memoria); si no, CPU.
La decisión se toma una vez, al arrancar.

Con poca luz la cámara baja sola a unos 15 fps aunque el módulo pueda más. Fijar la
exposición (`ZONA_CAMARA_EXPOSICION`) lo evita.

## Limitaciones

- **Es una demostración, no una protección de máquina.** No reemplaza un resguardo físico ni
  un dispositivo de seguridad certificado.
- **La zona vive en la imagen.** Si la cámara se mueve o la golpean, la zona guardada deja de
  coincidir con la cinta y el módulo no lo avisa: hay que volver a detectar y guardar.
- **El pie se mide en el tobillo.** La punta del zapato puede pisar la cinta un instante
  antes de que el módulo lo cuente como dentro. Con la cámara alta el desfase es pequeño.
- **Las distancias en metros valen sobre el piso.** Salen del tobillo, que está unos
  centímetros por encima: sirven para la franja de advertencia, no para medir con precisión.
- **Personas tapadas.** Quien queda oculto dentro de la zona sigue contando 4 s; después la
  alarma se apaga aunque siga ahí. Con mucha gente junta, el modelo puede perder a alguien o
  cambiarle el id; el módulo lo reconoce si reaparece cerca y pronto, no siempre.
- **La alarma depende de la plataforma.** Si la plataforma no recibe los eventos, su vista de
  alarma se apaga sola a los 5 s. El pitido de la estación (**S**) es el respaldo.
- **La detección de la cinta es una propuesta.** Depende de la luz y del color de la cinta;
  una persona siempre la revisa antes de guardarla.
- **Una sola zona y un solo proceso.** No hay zona de mano, y la estación y la ventana de
  calibración no deben correr a la vez.
- **Por validar en el montaje real:** está probado con video, con secuencias simuladas y con
  la cinta real frente a la cámara, pero falta el ensayo con personas entrando a la zona
  desde la cámara alta del stand, y oír el sonido en la pantalla que se vaya a usar.

## Cómo está hecho

| Carpeta | Qué hace |
|---|---|
| `nucleo/` | Geometría, homografía, clasificación con histéresis, máquina de estados y eventos. Sin cámara ni YOLO: se prueba con secuencias simuladas |
| `calibracion/` | Detección de la cinta, editor con el mouse, imagen de referencia y pedidos remotos |
| `deteccion/` | YOLO-pose con seguimiento (único lugar que usa Ultralytics), puntos de apoyo y elección de CPU o GPU |
| `interfaz/` | Dibujo de la zona y las personas, pantalla con marca Auren y pitido local |
| `config/` | Ajustes del `.env`, validación de la configuración remota y su almacén |
| `publicacion.py`, `estacion.py` | Eventos con foto y bucle principal |

Reglas principales del núcleo:

- **Peligro:** un pie dentro de la zona. **Advertencia:** el pie más cercano a menos del margen.
- **Antirrebote:** un cambio de estado se confirma cuando se sostiene 0,3 s.
- **Histéresis:** para bajar de nivel hay que alejarse 20 % más de lo que bastó para subir.
- **Personas que se dejan de ver:** conservan su estado 1 s; si estaban dentro de la zona, 4 s.
- **Cambios de id del tracker:** un id nuevo que aparece a menos de 0,5 m (u 80 px sin
  medidas) de donde se vio por última vez a una persona recién perdida es esa persona, y
  sigue con su estado y su historial. Así no salen dos eventos por la misma.
- **Punto de apoyo:** los tobillos que el modelo ve con confianza; si no ve ninguno, el punto
  medio del borde inferior de la caja de la persona.

### Privacidad

La ventana es un espejo en vivo y no se difumina. Todo lo que sale de ahí lleva los rostros
difuminados, y la zona y las personas se dibujan después del difuminado: la imagen de
referencia (`CARPETA_COLA/zona/referencia/`), las fotos de los eventos
(`CARPETA_COLA/zona/capturas/`) y las capturas de pantalla. No se guarda video.

## Pruebas

```
.venv\Scripts\python -m pytest pruebas/zona
```

No necesitan cámara. La prueba del detector real se omite si el modelo no está en el equipo.
