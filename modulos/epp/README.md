# modulos/epp — verificación de EPP por perfil

Estación en vivo: una cámara mira al visitante y dice si lleva los elementos de protección
que exige el perfil activo. Dos perfiles, cada uno con su modelo:

| Perfil | Modelo | Exige por defecto | También detecta |
|---|---|---|---|
| `alimentos` (Planta de alimentos) | `epp-alimentos-v1.pt` | cofia, gafas, tapabocas | — |
| `industria` (Industria) | `epp-industria-v2.pt` | casco, gafas | chaleco |

Qué perfil está activo y qué elementos se exigen se cambia **desde la plataforma** (o el
receptor de prueba) sin reiniciar. El resultado es un **borrador: validar en campo**.

## Instalación

Además de la instalación base del repositorio (ver [README](../../README.md)):

```
.venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
.venv\Scripts\python -m pip install -e ".[dev,epp]"
```

- PyTorch va primero y con el índice de la GPU. `cu126` es el de la RTX 4050 del equipo de
  desarrollo (driver 546); sin ese paso, pip instala la versión solo CPU, que funciona pero
  más lento.
- **No instales el paquete `roboflow`**: reemplaza OpenCV 5 por una versión vieja. La
  descarga de datasets usa la API REST directamente.
- Los pesos no están en git. Deben estar en `modulos/epp/modelos/`:
  `epp-alimentos-v1.pt` y `epp-industria-v2.pt`. Si falta uno, ese perfil queda no
  disponible y el otro sigue funcionando.

## Cómo correr

```
.venv\Scripts\python -m herramientas.receptor_prueba
.venv\Scripts\python -m modulos.epp
```

El receptor (o la plataforma) es opcional: sin él la estación funciona igual, con la última
configuración guardada, y los eventos quedan en la cola local.

Opciones: `--ventana` (no abrir a pantalla completa), `--camara N`.

Para saber qué índice tiene cada cámara conectada:

```
.venv\Scripts\python -m modulos.comun.camaras
```

### Teclas

| Tecla | Acción |
|---|---|
| `1`, `2` | Cambiar de perfil (en el orden de `perfiles.yaml`: 1 alimentos, 2 industria). El cambio también se envía a la plataforma. |
| `V` | Teclear el número del visitante; Enter confirma, Esc cancela. `142` queda como `V-0142` y va en `sesion_id`. Se borra solo al terminar la visita. |
| `F` | Pantalla completa sí/no. |
| `Q` o Esc | Salir. |

### Qué publica

- `verificacion_epp` cuando el veredicto de la persona se mantiene igual 2 s: una vez por
  visita, y otra vez si cambia de forma estable (se pone o se quita algo). Severidad `info`
  si cumple, `media` si falta algo. Lleva una foto adjunta.
- `config_actualizada` cada vez que aplica una configuración nueva (remota o por teclado).
- `estado_modulo` (latido) cada 30 s; pasa a `error` si la cámara se queda sin señal.

Una visita empieza cuando aparece una persona y termina tras 3 s sin nadie. Solo se
verifica a la **persona principal** (la más grande en la imagen); las demás se dibujan en
gris y no cuentan.

### Privacidad

La vista en vivo es un espejo y no se difumina, porque no se guarda. La foto que se adjunta
al evento sí: primero se difuminan los rostros y después se dibujan las cajas. No se guarda
video.

## Configuración

Variables del `.env`:

| Variable | Por defecto | Para qué |
|---|---|---|
| `EPP_CAMARA` | `0` | Índice de la cámara |
| `EPP_PANTALLA_COMPLETA` | `1` | `0` para abrir en ventana |
| `EPP_ESPEJO` | `1` | Mostrar la imagen como espejo |
| `EPP_SEGUNDOS_ESTABLE` | `2` | Tiempo con el mismo veredicto antes de publicar |
| `EPP_SEGUNDOS_SIN_PERSONA` | `3` | Tiempo sin nadie para cerrar la visita |
| `CONFIG_INTERVALO_S` | `3` | Cada cuánto se consulta la configuración remota |

### Cambiar la configuración desde el receptor de prueba

Con el receptor y la estación corriendo, abre http://localhost:8000. En **Configuración de
módulos** aparece `epp` con un selector de perfil y un interruptor por cada elemento que el
modelo de ese perfil sabe detectar. En unos 3 s la estación actualiza el panel, reinicia el
veredicto y publica `config_actualizada`.

También se puede por API (forma en `contrato/config_epp.schema.json`):

```
curl -X PUT http://localhost:8000/api/modulos/epp/config -H "Content-Type: application/json" -d "{\"perfil_activo\": \"industria\", \"perfiles\": {\"industria\": {\"elementos_requeridos\": [\"casco\", \"gafas\", \"chaleco\"]}}}"
```

Reglas: un elemento que el modelo no sabe detectar se ignora con una advertencia en el log;
un perfil que no existe se rechaza y se conserva la configuración anterior. Si la plataforma
no responde se usa la última configuración válida (`cola/config/epp.json`) y, si no hay,
la de `perfiles.yaml`.

### Agregar un elemento o un perfil

Todo está en [config/perfiles.yaml](config/perfiles.yaml), que explica cada campo.

- **Afinar un elemento** (umbral, zona, negativa): edita su línea en `elementos`. La zona es
  la franja vertical de la persona donde debe caer el centro del elemento, `[inicio, fin]`
  con 0 arriba y 1 abajo: el casco en `[0, 0.5]`, el chaleco en `[0.2, 1.0]`.
- **Elemento nuevo**: hay que reentrenar el modelo del perfil con esa clase (abajo). Al
  cargarlo, el elemento aparece solo en las capacidades y en la plataforma; en el YAML solo
  hace falta añadirlo si se quiere otro nombre, umbral o zona que los de
  `elemento_por_defecto`. Para exigirlo desde el arranque, añádelo a `elementos_requeridos`.
- **Perfil nuevo**: añade una entrada en `perfiles` con `nombre`, `modelo` y
  `elementos_requeridos`, y deja sus pesos en `modulos/epp/modelos/`. Su tecla es su
  posición en el archivo.

Si cambias zonas o umbrales de `industria`, actualiza el bloque `reglas` de
`pruebas/epp/casos/casos_industria.json`: una prueba comprueba que coincidan.

## Modelo de industria: datos y entrenamiento

```
.venv\Scripts\python -m modulos.epp.datos.preparar_dataset
.venv\Scripts\python -m modulos.epp.entrenamiento.entrenar --nombre industria_n --epocas 60
.venv\Scripts\python -m modulos.epp.entrenamiento.evaluar --pesos runs/epp/industria_n/weights/best.pt
.venv\Scripts\python -m modulos.epp.entrenamiento.entrenar --nombre industria_n --publicar epp-industria-v2
```

- `preparar_dataset` necesita `ROBOFLOW_API_KEY` en el `.env`. Descarga las cuatro fuentes
  de [datos/fuentes.yaml](datos/fuentes.yaml) (todas CC BY 4.0), aplica el mapeo de clases,
  quita duplicados, parte 80/10/10 y escribe `datasets/epp_industria/` y
  [datos/reporte_balance.md](datos/reporte_balance.md).
- El entrenamiento tarda unas 4 horas en la RTX 4050. `--publicar` copia los mejores pesos a
  `modelos/` con el nombre de versión; luego cambia `modelo:` en `perfiles.yaml`.
- Métricas del v1 en [entrenamiento/reporte_evaluacion.md](entrenamiento/reporte_evaluacion.md):
  casco, persona y chaleco sobre 0,90 de mAP50; **gafas 0,57** y las clases negativas
  0,35–0,50. Por eso las negativas tienen umbral alto en `perfiles.yaml`.

### Modelo v2 (el activo)

El v1 fallaba con las gafas en vivo. El v2 es el v1 afinado una época con fotos propias
tomadas con la cámara del stand (anotadas solas por `datos/capturar.py`) y copias reducidas
de fotos con gafas:

```
.venv\Scripts\python -m modulos.epp.datos.capturar --gafas si --casco si
.venv\Scripts\python -m modulos.epp.datos.capturar --gafas no --casco si --para evaluar
.venv\Scripts\python -m modulos.epp.datos.ampliar_dataset
.venv\Scripts\python -m modulos.epp.entrenamiento.entrenar --nombre industria_v2 --modelo epp-industria-v1.pt --data datasets/epp_industria_v2/data.yaml --epocas 30 --paciencia 10
.venv\Scripts\python -m modulos.epp.entrenamiento.medir_gafas --pesos modulos/epp/modelos/epp-industria-v1.pt runs/epp/industria_v2/weights/best.pt --partes propias
```

| Medida | v1 | v2 |
|---|---|---|
| Gafas encontradas en fotos propias de evaluar (143) | 100 | 128 |
| Casco encontrado en fotos propias de evaluar (288) | 274 | 288 |
| «Gafas» falsas sin llevarlas (145) | 0 | 0 |
| mAP50 en prueba pública | 0,695 | 0,670 |
| Recall de gafas pequeñas (3–6 % del ancho) en datos públicos | 0,26 | 0,17 |

Límites conocidos: las fotos propias son de una sola persona en un solo lugar, así que la
mejora con otros visitantes puede ser menor; y a distancia (gafas de menos del 6 % del
ancho de la imagen) sigue fallando en los datos públicos. En la prueba en vivo con la
Logitech C930e funcionó bien hasta cerca de 1,5 m; más lejos no está comprobado. Seguir
entrenando más épocas subía el resultado en las fotos propias pero lo bajaba en las
públicas (memoriza), por eso se quedó en la primera. Sumar fotos de más personas es la
siguiente mejora.

Las fotos propias se guardan sin difuminar (excepción de `CLAUDE.md`): quedan en
`datasets/fotos_propias/`, fuera de git, y no se suben.

### Sumar fotos propias

Las fotos tomadas en el stand (misma cámara, misma distancia) son lo que más ayuda, sobre
todo para gafas. Arma una carpeta en formato YOLO:

```
mis_fotos/
├── images/      foto001.jpg …
├── labels/      foto001.txt …   (clase cx cy ancho alto, normalizados)
└── classes.txt  una clase por línea, con los nombres canónicos:
                 persona, casco, gafas, chaleco, proteccion_auditiva, sin_casco, sin_gafas
```

y pásala al preparar el dataset (se puede repetir `--local`):

```
.venv\Scripts\python -m modulos.epp.datos.preparar_dataset --local mis_fotos
```

Anota **todas** las clases visibles en cada foto (también la persona): un elemento visible
sin anotar le enseña al modelo que no está.

## Estructura

| Ruta | Qué es |
|---|---|
| `nucleo/` | Lógica pura, sin cámara ni modelos: `reglas.py` y `suavizado.py` (motor del proyecto de alimentos, con zona por elemento), `perfiles.py`, `configuracion.py`, `visitas.py` |
| `verificador.py` | Une lo anterior: detecciones de un cuadro → qué mostrar y qué publicar |
| `deteccion.py` | Carga de modelos YOLO (único archivo que usa Ultralytics) |
| `interfaz.py` | Cajas y panel lateral |
| `estacion.py` | Cámara, ventana, teclado, configuración remota y publicación |
| `config/perfiles.yaml` | Perfiles y ajustes por defecto |
| `datos/`, `entrenamiento/` | Dataset y entrenamiento del modelo de industria |

Pruebas en `pruebas/epp/` (no necesitan cámara, GPU ni modelos). El motor de reglas conserva
los 25 casos y 11 secuencias dorados del proyecto original (`casos_alimentos.json`) y suma
los de industria (`casos_industria.json`).

## Licencias

- **Ultralytics YOLO es AGPL-3.0.** Para un uso comercial cerrado hace falta su licencia
  Enterprise; está pendiente de decidir para después del evento.
- Datasets de Roboflow Universe: CC BY 4.0 (atribución en `datos/fuentes.yaml`).
