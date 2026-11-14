# modulos/ergonomia — evaluación ergonómica REBA en vivo

Estación en vivo: el visitante levanta una caja frente a una cámara en vista lateral. La
pantalla muestra su esqueleto con cada segmento coloreado por su puntaje, los ángulos y el
puntaje REBA (Hignett y McAtamney, 2000). El módulo detecta cada levantamiento, toma el
fotograma de mayor puntaje, publica el evento y genera un reporte PDF de una página.

La demo se hace dos veces: primero como salga y luego flexionando las rodillas. La pantalla
compara los dos intentos.

**Qué dice y qué no dice el resultado.** REBA no califica si la persona levantó "bien" o
"mal": estima el riesgo de una postura si forma parte de un trabajo y qué tan urgente es
intervenir **la tarea**. Recoger una caja del piso suele dar riesgo medio o alto de las dos
formas, porque el método suma por la flexión de la espalda o por la de las rodillas. Lo que
la técnica sí cambia (cuánto se dobla la espalda) se muestra aparte, junto al puntaje. Todo
resultado es un **borrador: validar en campo**.

## Instalación

Este módulo vive en **su propio entorno**, `modulos/ergonomia/.venv`, no en el `.venv` del
repositorio. MediaPipe instala `opencv-contrib-python`, que choca con el `opencv-python` que
usa EPP (los dos escriben en la misma carpeta `cv2`).

Desde la raíz del repositorio (Windows; en Linux cambia `.venv\Scripts\` por `.venv/bin/`):

```
py -3.12 -m venv modulos\ergonomia\.venv
modulos\ergonomia\.venv\Scripts\python -m pip install -r modulos\ergonomia\requirements.txt
modulos\ergonomia\.venv\Scripts\python -m pip install --no-deps -e .
modulos\ergonomia\.venv\Scripts\python -m modulos.ergonomia.pose.mediapipe_pose
```

- La tercera línea instala `modulos.comun` en modo editable **sin** sus dependencias: así no
  entra `opencv-python`. `pip check` avisará que falta; es lo esperado.
- La cuarta descarga una vez el modelo de pose (`pose_landmarker_full.task`, unos 9 MB) a
  `modulos/ergonomia/modelos/`, que no va en git. Es el único paso que necesita internet.
- **MediaPipe va fijo en 1.2.2.** Smart App Control de Windows bloquea la DLL sin firmar de
  la 1.2.3 (`WinError 4551`) y sí deja cargar la de la 1.2.2. Antes de subir de versión,
  comprueba que arranca en la PC del stand.
- Si no existe, copia `.env.example` como `.env` en la raíz y ajusta `ERGONOMIA_CAMARA`.

Todo corre en CPU. No usa la GPU.

## Cómo correr

Con el receptor de prueba (o la plataforma) arriba en `API_URL`:

```
.venv\Scripts\python -m herramientas.receptor_prueba
modulos\ergonomia\.venv\Scripts\python -m modulos.ergonomia
```

Sin plataforma el módulo también funciona: los eventos quedan en la cola local y se entregan
cuando vuelva.

| Opción | Para qué |
|---|---|
| `--video ruta.mp4` | Procesa un archivo en lugar de la cámara |
| `--repetir` | Con `--video`, vuelve a empezar al terminar |
| `--ventana` | Abre en ventana, no a pantalla completa |
| `--sin-plataforma` | No consulta la configuración remota ni publica eventos |
| `--sin-ventana` | Procesa sin mostrar nada (pruebas) |
| `--max-cuadros N` | Termina después de N fotogramas |
| `--captura ruta.png` | Al terminar, guarda la pantalla del último fotograma (rostros difuminados) |

### Teclas

| Tecla | Acción |
|---|---|
| Barra espaciadora | Inicia o termina el levantamiento (modo manual, o para forzarlo en modo auto) |
| Dígitos y Enter | Número de visitante: `142` + Enter → `V-0142`. Retroceso corrige, Esc cancela |
| N | Nueva visita sin número (reinicia los intentos) |
| F | Pantalla completa sí o no |
| Q o Esc | Salir |

### La demo, paso a paso

1. El visitante se para de lado y **se queda quieto un segundo**. El módulo toma su postura
   de pie como cero ("postura neutra"); mientras lo hace, la instrucción dice "Quédate de pie
   y quieto un momento".
2. Levanta la caja. El levantamiento empieza solo cuando las manos bajan de las rodillas o
   el tronco pasa de 20° con las manos abajo, y termina cuando lleva un segundo erguido.
3. Al terminar, el panel muestra durante 8 s el **resultado de ese intento** (no la postura
   de pie): el puntaje, lo que significa, qué corregir y una pista.
4. Segundo intento. La franja inferior compara: flexión de espalda, rodillas y REBA.
5. Si se tecleó el número de visitante y hay `BASE_URL_PUBLICA`, aparece el QR del reporte.

Cada agachada cuenta como un levantamiento. Dejar la caja otra vez en el piso es otro intento.

## Cámara

### Elegir la Logitech

```
modulos\ergonomia\.venv\Scripts\python -m herramientas.listar_camaras
```

Lista las cámaras con su índice y sus resoluciones, y abre una vista previa de la que
elijas. La integrada del portátil suele ser la 0. Pon el índice en el `.env`:

```
ERGONOMIA_CAMARA=2
```

**Conecta cada cámara siempre al mismo puerto USB**: el índice puede cambiar al cambiarla
de puerto. Con dos Logitech del mismo modelo el nombre no las distingue; la vista previa sí.
En el log debe salir `Cámara 2 abierta: 1280x720 a 30 fps`, sin la advertencia de formato YUY2.

### Montaje

- **Vista lateral de verdad**, a la altura de la cadera y a unos 3 m. En diagonal o desde
  arriba los ángulos salen acortados y la postura de pie da un neutro grande.
- **Cuerpo completo en cuadro, también al agacharse**: cabeza y pies. Si un segmento se sale,
  el intento se descarta con "No se vio el cuerpo completo".
- Buena luz de frente o cenital, sin contraluz. Fondo despejado.
- **Sin público en el encuadre.** El estimador sigue a una sola persona y puede saltar a
  quien se cruce. Además, una cara cortada por el borde de la imagen no se difumina.
- La caja no debe tapar las manos ni los pies desde la cámara.

## Modo video

Para desarrollar y ajustar sin estar frente a la cámara:

```
modulos\ergonomia\.venv\Scripts\python -m herramientas.grabar_video --camara 2 --segundos 60
modulos\ergonomia\.venv\Scripts\python -m modulos.ergonomia --video datasets\videos\prueba.mp4 --ventana
```

`grabar_video` empieza y termina con la barra espaciadora. Los videos son material de
desarrollo: quien aparece aceptó ser grabado, se quedan en `datasets/videos/` (fuera de git)
y nunca se suben. Durante el evento no se graba video de los visitantes.

## Configuración

### Del equipo (`.env`)

| Variable | Por defecto | Qué es |
|---|---|---|
| `ERGONOMIA_CAMARA` | `0` | Índice (recomendado) o nombre de la cámara |
| `ERGONOMIA_CAMARA_ANCHO`, `_ALTO`, `_FPS` | `1280`, `720`, `30` | Formato pedido a la cámara (siempre MJPG) |
| `ERGONOMIA_CAMARA_AUTOFOCO` | `0` | 0 = autofoco apagado y enfoque fijo |
| `ERGONOMIA_CAMARA_ENFOQUE` | `0` | Enfoque fijo (0 = infinito) |
| `ERGONOMIA_CAMARA_EXPOSICION` | vacío | Exposición fija; vacío = automática |
| `ERGONOMIA_PANTALLA_COMPLETA` | `1` | 0 = abrir en ventana |
| `ERGONOMIA_PANTALLA_ANCHO`, `_ALTO` | `1920`, `1080` | Tamaño de la pantalla del stand |
| `ERGONOMIA_DISPOSITIVO` | `cpu` | Dispositivo del estimador de pose |
| `ERGONOMIA_UMBRAL_VISIBILIDAD` | `0.5` | Visibilidad mínima de un punto para estimar su segmento |
| `ERGONOMIA_SEGUNDOS_RESULTADO` | `8` | Cuánto se deja en pantalla el resultado de un intento |
| `ERGONOMIA_SEGUNDOS_NUEVA_VISITA` | `20` | Sin nadie en cuadro este tiempo, empieza otra visita |
| `BASE_URL_PUBLICA` | vacío | URL pública para el QR: `{BASE_URL_PUBLICA}/r/{sesion_id}`. Vacía = sin QR |

Las generales (`API_URL`, `DISPOSITIVO`, `CARPETA_COLA`, `CONFIG_INTERVALO_S`, `LOG_NIVEL`)
están en `.env.example`.

### Operativa (remota, en vivo)

El módulo registra sus capacidades y consulta `GET /api/modulos/ergonomia/config` cada pocos
segundos; un cambio se aplica en el siguiente fotograma. Valor por defecto en
[config/por_defecto.json](config/por_defecto.json) y forma en
[contrato/config_ergonomia.schema.json](../../contrato/config_ergonomia.schema.json).

| Clave | Por defecto | Qué es |
|---|---|---|
| `peso_carga_kg` | `5` | Menos de 5 kg suma 0; de 5 a 10 kg, 1; más de 10 kg, 2 |
| `agarre` | `bueno` | `bueno`, `regular`, `malo` o `inaceptable` (suma 0 a 3) |
| `golpe_o_fuerza_brusca` | `false` | Suma 1 a la carga |
| `actividad` | todo `false` | `estatica`, `repetitiva`, `cambios_rapidos`: cada una suma 1 al final |
| `modo_deteccion` | `auto` | `auto` o `manual` (barra espaciadora) |
| `lado` | `auto` | `auto` (el más visible), `izquierdo` o `derecho` |
| `camara` | `null` | Índice o nombre; `null` = la del `.env` |
| `postura_neutra` | `true` | Medir tronco y cuello desde la postura de pie de cada persona |
| `ajuste_brazo_inclinada` | `true` | Restar 1 al brazo si la persona está inclinada y el brazo cuelga |
| `umbral_tronco_inclinado`, `tolerancia_brazo_vertical` | `45`, `20` | Umbrales de ese ajuste, en grados |
| `deteccion` | ver archivo | Umbrales del modo auto: `tronco_inicio`, `tronco_erguido`, `rodilla_erguida`, `segundos_erguido`, `duracion_minima_s`, `duracion_maxima_s`, `ventana_sostenida_s` |

Para cambiarla contra el receptor de prueba, desde PowerShell:

```
Invoke-RestMethod -Method Put -Uri http://localhost:8000/api/modulos/ergonomia/config -ContentType "application/json" -Body '{"peso_carga_kg": 12, "agarre": "regular"}'
```

Lo que no vaya en el objeto vuelve a su valor por defecto, no al anterior. Una configuración
inválida se rechaza entera y se conserva la vigente.

## Qué publica

Todo sale por `modulos.comun`. Detalle de campos en
[docs/cambios-contrato.md](../../docs/cambios-contrato.md).

- **`evaluacion_reba`**, uno por levantamiento: `puntaje`, `nivel`, `angulos`, `duracion_s`
  y, opcionales, `puntajes` (desglose), `lado`, `intento`, `desde_piso`, `tecnica`,
  `postura_neutra`, `segmentos_no_estimados`, `segmentos_asumidos`, `ajustes_aplicados`,
  `no_evaluado`, `peso_carga_kg` y `agarre`. Adjunta el fotograma crítico.
- **`reporte_generado`**, uno por levantamiento: `reporte_id`, `url_reporte`, `intento` y
  `evaluacion_id`. Adjunta el PDF.
- **`estado_modulo`** (latido) cada 30 s; pasa a `error` si la cámara se desconecta.

No publica `config_actualizada`: el esquema fija ese evento a la estación `epp`.

### El reporte PDF

Una página: fotograma crítico, puntaje con su etiqueta y nivel de acción, tabla de ángulos y
puntajes por segmento, cálculo de las tablas A, B y C, "Qué significa este resultado",
comparación de intentos, de 2 a 4 recomendaciones y cómo se midió. Las recomendaciones salen
de reglas escritas en [nucleo/recomendaciones.json](nucleo/recomendaciones.json): sin IA y sin
internet. Las copias locales quedan en `CARPETA_COLA/ergonomia/` (`capturas/` y `reportes/`).

### Privacidad

- La ventana es un espejo en vivo: no se difumina, no se guarda ni se envía.
- El fotograma crítico pasa por `difuminar_rostros` **antes** de dibujar el esqueleto y de
  tocar el disco. Es la única imagen que se guarda y se sube, y es la que va en el PDF.
- No se guarda video.

## Cómo se calcula

- **Tablas y textos fuera del código**: [nucleo/tablas_reba.json](nucleo/tablas_reba.json),
  [nucleo/mensajes_reba.json](nucleo/mensajes_reba.json) y `recomendaciones.json`. Las tablas
  A, B y C se verificaron contra Ergonautas (UPV), la NTP 601 del INSHT y la hoja de ErgoPlus;
  no se pudo consultar el artículo original.
- **Límites de rango**: el valor exacto del límite cae en el rango inferior (20° de tronco
  puntúa 2; 60° puntúa 3). En la muñeca, 15° exactos puntúan 1.
- **Ángulos** (`nucleo/angulos.py`), del lado más visible: tronco respecto a la vertical;
  cuello respecto al tronco; rodilla y codo como 180° menos el ángulo interior; brazo respecto
  a la línea del tronco; muñeca como desviación de la mano respecto al antebrazo.
- **Fotograma crítico**: el de mayor puntaje **sostenido 0,3 s**. El máximo de un solo
  fotograma premiaría el ruido. Los fotogramas en que la persona ya está erguida no compiten.
- **Segmento no estimado**: si un punto clave tiene poca visibilidad, su segmento queda en
  gris y sin puntaje. Sin tronco, cuello, piernas, brazo o antebrazo no hay REBA final.

Decisiones que **no salen del método** y conviene conocer:

| Decisión | Qué hace | Por qué |
|---|---|---|
| Tolerancia de erguido de ±5° | Dentro de ±5° el tronco puntúa 1 | Una cámara nunca mide 0° exactos |
| Muñeca no bloqueante | Si no se ve, se asume 1 y el puntaje es una cota inferior | A 3 m la mano se pierde con frecuencia |
| Postura neutra por persona | Tronco y cuello se miden desde la postura de pie | De pie y derecho, los puntos de la cámara dan unos −10° de tronco y 30° de cuello |
| La corrección del tronco se desvanece | Se aplica completa de pie y deja de aplicarse a 30° de esa postura | El desfase de pie no se conserva al agacharse. Es un criterio práctico, no verificable con una sola cámara |
| Brazo −1 por persona inclinada | Tronco a más de 45° y brazo colgando a 20° o menos de la vertical | La hoja de REBA resta 1 si el brazo está a favor de la gravedad |
| Técnica de levantamiento | Flexión de espalda y de rodillas, con las franjas del propio REBA | REBA no distingue espalda doblada de sentadilla (tabla A: tronco 4 y piernas 1 vale 3; tronco 2 y piernas 3 vale 4) |
| "Desde el piso" | Las muñecas bajo las rodillas 0,3 s seguidos | Decide la pista contextual |

## Limitaciones con una cámara 2D

- **Torsión, inclinación lateral, abducción y hombro elevado no se miden** y no suman. Si la
  persona gira el tronco mientras levanta, el puntaje real es mayor.
- **Solo sirve en vista lateral.** En diagonal los ángulos salen acortados.
- **La muñeca es una estimación de baja confianza.**
- **Carga, agarre y actividad no se miden**: los pone el operador.
- **Una sola persona.** Con público en cuadro puede seguir a otra.
- **Oclusiones**: la caja, la mesa o la ropa holgada pueden tapar puntos clave.
- **No está validado** contra un evaluador humano ni contra captura de movimiento. Es una
  estimación automática: debe validarla un profesional de SST.

## Pruebas

```
modulos\ergonomia\.venv\Scripts\python -m pytest pruebas\ergonomia pruebas\test_camara_stand.py
```

No necesitan cámara ni el modelo de pose: usan posturas simuladas y el receptor de prueba
real. En el `.venv` del repositorio también pasan, salvo las del PDF y el QR, que se saltan
porque `fpdf2` y `qrcode` solo están en el entorno de ergonomía.

## Problemas frecuentes

| Síntoma | Causa y arreglo |
|---|---|
| Abre la cámara del portátil | Falta `ERGONOMIA_CAMARA` en el `.env`. Revisa el índice con `listar_camaras` |
| `WinError 4551` al arrancar | Smart App Control bloqueó MediaPipe. Reinstala con `requirements.txt` (deja la 1.2.2) |
| "Falta el modelo de pose" | Corre `python -m modulos.ergonomia.pose.mediapipe_pose` con internet |
| Advertencia "quedó en formato YUY2" | La cámara no aceptó MJPG: dará unos 10 fps en 720p. Prueba otro puerto USB |
| "No se vio el cuerpo completo" | Algo se salió del encuadre al agacharse. Aleja o baja la cámara |
| De pie no marca 1 | No se calibró: la persona se agachó sin quedarse quieta antes |
| No aparece el QR | Falta `BASE_URL_PUBLICA`, el número de visitante o el primer intento |

## Estructura

```
modulos/ergonomia/
├── __main__.py          # python -m modulos.ergonomia
├── estacion.py          # bucle principal: cámara, análisis, pantalla
├── flujo.py             # levantamientos, visita, teclas y textos de la pantalla
├── publicacion.py       # fotograma crítico, evaluacion_reba, PDF y reporte_generado
├── fuentes.py           # modo video
├── requirements.txt     # dependencias del entorno propio
├── nucleo/              # puro: sin cámara, OpenCV ni MediaPipe
│   ├── reba.py, tablas_reba.json
│   ├── angulos.py, neutra.py, suavizado.py
│   ├── levantamiento.py, intentos.py, tecnica.py
│   ├── mensajes.py, mensajes_reba.json
│   └── recomendaciones.py, recomendaciones.json
├── pose/                # EstimadorPose y su implementación con MediaPipe
├── interfaz/            # esqueleto, panel Auren, franjas y QR
├── reporte/             # contenido del reporte y maquetación del PDF
├── config/              # ajustes del .env y configuración remota
└── modelos/             # modelo de pose descargado (fuera de git)
```

Para cambiar de estimador (por ejemplo a YOLO-pose) basta otra clase que cumpla
`pose/estimador.py` y devuelva los mismos nombres de puntos.
