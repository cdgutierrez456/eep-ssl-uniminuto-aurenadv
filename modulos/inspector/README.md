# Módulo inspector por foto

El visitante toma una foto de una escena de trabajo con la tablet. En unos 15 a 20 segundos ve
los peligros que se distinguen en la foto, marcados y numerados, clasificados y con controles
propuestos según la jerarquía. La aplicación le pregunta lo que la foto no muestra (frecuencia
de la tarea, personas expuestas, controles que existen) y genera las filas de una matriz IPEVR
en Excel.

Todo sale marcado como borrador. El mensaje del stand: **la IA propone, el profesional de SST
decide.**

El análisis lo hace un modelo de visión de Claude por API, desde la PC del stand. La valoración
del riesgo y el Excel se calculan en la PC, sin IA.

## Probarlo todo junto

En dos terminales, desde la raíz del repositorio:

```
.venv\Scripts\python -m herramientas.receptor_prueba
```

```
.venv\Scripts\python -m modulos.inspector
```

Abre `http://localhost:8010`. Para verlo sin gastar una llamada, entra por **Usar una escena
preparada**. Al generar la matriz, el evento `inspeccion_foto` aparece en
`http://localhost:8000` con la foto anotada y el Excel adjuntos.

Para ver solo el Excel y la foto anotada, sin IA, sin servicio y sin internet:

```
.venv\Scripts\python -m modulos.inspector.ejemplo
```

Deja `matriz_ipevr_ejemplo.xlsx` y `foto_anotada_ejemplo.jpg` en `cola/inspector/ejemplo/`
(la escena de ese ejemplo es un dibujo, no una foto).

## Instalación

Usa el entorno compartido del repositorio (`.venv`):

```
.venv\Scripts\python -m pip install -e ".[dev,inspector]"
```

No necesita cámara Logitech ni GPU: las fotos vienen de la tablet o de un archivo.

## La clave de la API

El módulo llama a Claude con una clave de Anthropic. Va **solo en el archivo `.env`** de la raíz
del repositorio, en la PC del stand:

```
ANTHROPIC_API_KEY=sk-ant-...
```

- **Nunca en `.env.example`**: ese archivo se versiona en git. Si la clave llega a un commit,
  hay que revocarla en la consola de Anthropic y crear otra.
- La clave no pasa por el código, los logs, el registro de costos ni las respuestas del
  servicio. La tablet nunca habla con Claude: todas las llamadas salen de la PC.
- Para comprobar que quedó bien sin mostrarla: `http://localhost:8010/salud` responde
  `"hay_clave": true`.
- Sin clave el servicio arranca igual y solo ofrece las escenas preparadas.

## Configuración

En el `.env` (los valores por defecto están en `.env.example`):

| Variable | Por defecto | Qué hace |
|---|---|---|
| `INSPECTOR_MODELO` | `claude-sonnet-5-5` | Modelo de visión. `claude-opus-5-5` es la opción de mayor calidad y cuesta el doble |
| `INSPECTOR_ESFUERZO` | `medium` | Cuánto razona el modelo: `low`, `medium` o `high` |
| `INSPECTOR_MAX_PELIGROS` | `6` | Máximo de peligros por foto; se conservan los más graves |
| `INSPECTOR_TIEMPO_MAXIMO_S` | `60` | Segundos máximos de espera, incluido un reintento |
| `INSPECTOR_IMAGEN_LADO_MAX` | `1568` | Lado largo de la foto que se envía. `2576` es alta resolución |
| `INSPECTOR_PUERTO` | `8010` | Puerto del servicio |
| `INSPECTOR_SOLO_ESCENAS` | `0` | `1` = no llamar a la IA; solo escenas preparadas |
| `INSPECTOR_PROMPT` | `sistema_v1` | Versión del prompt del sistema (archivo de `prompts/`) |

El operador puede cambiar en vivo, desde la plataforma, el modelo, el máximo de peligros, el
tiempo máximo y el modo solo escenas (`/api/modulos/inspector/config`). El cambio aplica en el
siguiente análisis. El detalle está en [`docs/cambios-contrato.md`](../../docs/cambios-contrato.md).

## Abrir la interfaz desde la tablet

1. Conecta la PC y la tablet a la misma red (el router del stand).
2. Arranca el servicio. Al iniciar escribe en la consola la dirección para la tablet, por ejemplo
   `Interfaz de tablet: http://192.168.1.20:8010`.
3. Abre esa dirección en el navegador de la tablet.

Si la tablet no carga la página, lo más probable es el firewall de Windows: hay que permitir
conexiones entrantes al puerto 8010 (o a Python) en redes privadas.

**Tomar foto** abre la cámara trasera de la tablet y **Subir una foto guardada** abre la galería.
Funciona por `http://` en la red local, sin certificados.

La interfaz que trae el módulo es provisional, hasta que exista la de la plataforma. La API que
consume está documentada en [`docs/cambios-contrato.md`](../../docs/cambios-contrato.md).

### El recorrido

1. **Foto**: tomarla, subirla o elegir una escena preparada.
2. **Espera**: pasos y tiempo transcurrido.
3. **Peligros propuestos**: la foto con las cajas numeradas y una tarjeta por peligro, con
   evidencia, clasificación, confianza y controles. Los de confianza baja dicen "Posible —
   verificar" y llevan la caja punteada.
4. **Lo que la foto no muestra**: por cada peligro, frecuencia, número de personas y controles
   existentes. La persona puede ajustar la deficiencia y la consecuencia, o descartar el peligro.
5. **Matriz**: tabla con el nivel de riesgo por peligro y el botón para descargar el Excel.

## Escenas preparadas

Son fotos con el análisis ya calculado. Sirven cuando no hay internet o la API falla: la tablet
ofrece **Usar una escena preparada** y el resultado sale del disco, sin llamar a la IA.

Cada escena es una carpeta de `modulos/inspector/escenas/`:

```
escenas/bodega_stand/foto.jpg         la foto, con los rostros difuminados
escenas/bodega_stand/escena.json      el nombre que ve la persona (y la fuente, si la foto no es propia)
escenas/bodega_stand/resultado.json   el análisis precalculado
```

### Preparar las escenas del stand

1. Monta la escena y tómale una foto, tal como la tomaría un visitante.
2. Copia la foto suelta en `modulos/inspector/escenas/`, con el nombre que quieras para la
   escena (por ejemplo `bodega_stand.jpg`).
3. Con internet y la clave configurada, corre:

   ```
   .venv\Scripts\python -m herramientas.precalcular_escenas
   ```

   Por cada foto suelta crea su carpeta, guarda la foto con los rostros difuminados, **borra
   el archivo suelto** (una foto sin difuminar no puede quedar en el repositorio) y la analiza.
4. Edita el `nombre` en `escena.json` si quieres otro texto en la tablet.
5. Revisa el resultado en la interfaz. Si no convence, repite el análisis de esa escena:

   ```
   .venv\Scripts\python -m herramientas.precalcular_escenas --forzar --solo bodega_stand
   ```

Las escenas se versionan en git, así que llegan a la PC del stand con el repositorio. Para
quitar una, borra su carpeta.

Para la demo sin internet, o para no gastar, pon `INSPECTOR_SOLO_ESCENAS=1` o activa
`solo_escenas_preparadas` desde la plataforma.

### Escenas de ejemplo incluidas

Vienen cinco fotos de uso libre de Wikimedia Commons, con los rostros difuminados y el tamaño
reducido. Sirven para probar; conviene reemplazarlas por las escenas reales del stand.

| Escena | Autor | Licencia | Fuente |
|---|---|---|---|
| `altura_sin_proteccion` | NIOSH | Dominio público | [Commons](https://commons.wikimedia.org/wiki/File:Construction_workers_not_wearing_fall_protection_equipment.jpg) |
| `andamio_taiwan` | Mk2010 (Malcolm Koo) | CC BY-SA 4.0 | [Commons](https://commons.wikimedia.org/wiki/File:Workers_on_metal_pole_scaffold_(Taiwan).jpg) |
| `bodega_estanterias` | ProjectManhattan | CC0 1.0 | [Commons](https://commons.wikimedia.org/wiki/File:Warehouse_goods.jpg) |
| `obra_andamios` | John Salvino | CC0 1.0 | [Commons](https://commons.wikimedia.org/wiki/File:Construction_Work_(Unsplash).jpg) |
| `soldador_taller` | Uğur Gürcüoğlu | CC0 1.0 | [Commons](https://commons.wikimedia.org/wiki/File:Welder_in_a_workshop_(Unsplash).jpg) |

La copia de `andamio_taiwan` se distribuye bajo la misma licencia CC BY-SA 4.0.

## Costos y tiempos

Medidos el 14 de noviembre de 2026 con las cinco fotos de ejemplo, modelo `claude-sonnet-5-5`:

| Ajuste | Tiempo promedio | Costo promedio por foto |
|---|---|---|
| Esfuerzo medium, 1568 px (por defecto) | 16,7 s | 0,037 USD |
| Esfuerzo low, 1568 px | 16,9 s | 0,038 USD |
| Esfuerzo medium, alta resolución | 16,4 s | 0,041 USD |

- El tiempo va de 11 a 21 s según la foto. Bajar el esfuerzo no lo acorta y la alta resolución
  no encontró peligros que la estándar no viera.
- Cada foto gasta unos 7000 tokens de entrada (unos 5000 son el prompt y el esquema, fijos) y
  entre 1400 y 3000 de salida, que incluyen el razonamiento del modelo.
- Una foto repetida no se cobra: sale de la caché (`cola/inspector/cache/`). Las escenas
  preparadas tampoco.
- Cada llamada queda en el log y en `cola/inspector/costos.csv` con modelo, tokens, costo
  estimado, duración y resultado. Los rechazos y los errores también quedan ahí.

Para ver el costo promedio por foto:

```
.venv\Scripts\python -m modulos.inspector.analisis --costos
```

Los precios por modelo están en `config/precios.json`; si Anthropic los cambia, se editan ahí.

## Ajustar el análisis

- **Prompt del sistema**: `prompts/sistema_v1.md`. Se edita sin tocar código. Para comparar
  versiones, copia el archivo como `sistema_v2.md` y pon `INSPECTOR_PROMPT=sistema_v2`; la caché
  distingue versiones.
- **Esquema de salida del modelo**: `esquemas/analisis.schema.json`. Si cambia, cambian con él
  el prompt y `nucleo/esquema.py`.
- **Probar una foto desde la consola**, sin levantar el servicio:

  ```
  .venv\Scripts\python -m modulos.inspector.analisis foto.jpg
  .venv\Scripts\python -m modulos.inspector.analisis modulos\inspector\escenas --esfuerzo low --sin-cache
  ```

  Muestra los peligros, el tiempo y el costo, y deja la foto anotada en `cola/inspector/analisis/`.

## Valoración del riesgo

La calcula `nucleo/valoracion.py`, una función pura: `NP = ND × NE` y `NR = NP × NC`. Los
valores y los textos están en `config/parametros_valoracion.json` y se pueden editar.

| Escala | Valores |
|---|---|
| Deficiencia (ND) | muy alto 10, alto 6, medio 2, bajo sin valor |
| Exposición (NE) | continua 4, frecuente 3, ocasional 2, esporádica 1 |
| Probabilidad (NP) | muy alto 24 a 40, alto 10 a 20, medio 6 a 8, bajo 2 a 4 |
| Consecuencia (NC) | mortal 100, muy grave 60, grave 25, leve 10 |
| Riesgo (NR) | I de 600 a 4000, II de 150 a 500, III de 40 a 120, IV 20 |
| Aceptabilidad | I no aceptable; II no aceptable o aceptable con control específico; III mejorable; IV aceptable |

- Con deficiencia baja no hay NP ni NR: el peligro va directo a nivel IV, aceptable, y el Excel
  lo explica en una nota al pie.
- Un valor que caiga entre dos rangos se clasifica por el umbral inferior, así nada queda sin nivel.
- La deficiencia y la consecuencia las propone la IA y las puede ajustar la persona. La
  exposición la pone siempre la persona.

## El Excel

Una hoja con el aviso "BORRADOR — Generado con IA. Debe ser validado en campo por un
profesional de SST.", la fecha, la miniatura de la foto con las cajas numeradas, una fila por
peligro y las notas al pie. Las columnas: identificación (n.º, proceso, zona, actividad, tarea,
rutinaria), peligro (descripción, clasificación, efectos), controles existentes (fuente, medio,
individuo), evaluación (ND, NE, NP, NC, NR y sus interpretaciones), aceptabilidad, expuestos,
peor consecuencia, requisito legal, medidas de intervención por jerarquía, y confianza y
evidencia de la IA.

Proceso, zona, actividad y tarea son opcionales: lo que la persona no llene queda en blanco.

## Privacidad

- La foto se orienta, se reduce y pasa por `difuminar_rostros` **antes** de enviarse a la API y
  antes de escribirse en disco. Las cajas se dibujan después.
- La foto original nunca se guarda: solo existe en memoria mientras se prepara.
- Cada inspección queda en `cola/inspector/inspecciones/<id>/` (fuera de git) con la foto
  difuminada, las fotos anotadas, el análisis y el Excel.
- No se identifica a las personas: el prompt lo prohíbe y los rostros llegan difuminados.

## Limitaciones

- **La IA puede equivocarse.** Puede proponer un peligro que no existe, pasar por alto uno que
  sí, o describir mal lo que ve. Por eso cada peligro trae su evidencia y su confianza, la
  persona puede descartarlo y todo sale como borrador para validar en campo.
- **El resultado varía.** La misma foto analizada dos veces puede dar peligros o confianzas algo
  distintos. La caché evita que una foto repetida cambie de resultado durante la demo.
- **Solo ve lo que está en la foto.** No sabe qué hay fuera del encuadre, qué pasó antes ni cómo
  se hace la tarea. Las advertencias dicen qué limita el análisis (imagen oscura, piso tapado).
- **Las cajas son aproximadas.** Sirven para señalar el peligro, no para medir. Cuando varios
  peligros salen de la misma persona, las cajas se enciman.
- **El requisito legal queda vacío a propósito.** Un modelo de lenguaje puede citar con total
  seguridad una norma derogada, un artículo que no existe o uno que no aplica al caso, y eso en
  una matriz es peor que un espacio en blanco. El prompt le prohíbe citar normas y el Excel
  deja la columna vacía con la nota "A completar por el profesional".
- **La exposición la pone la persona.** Una foto es un instante: no dice si la tarea se hace
  una vez al año o todo el turno, ni cuántas personas la hacen, ni qué controles existen fuera
  de cuadro. Si la IA lo estimara, estaría inventando. Como la frecuencia entra directo al
  cálculo del riesgo, un dato inventado ahí cambiaría el nivel.
- **La valoración es preliminar.** Sale de dos niveles que propone la IA y de la exposición que
  responde un visitante en un stand. No reemplaza la valoración del profesional.
- **El análisis tarda de 11 a 21 segundos** y necesita internet. Sin internet quedan las escenas
  preparadas.
- **El modelo puede declinar una foto.** La interfaz responde "No pudimos analizar esta foto.
  Intenta con otra toma o usa una escena preparada." y el rechazo queda en el registro de costos.
- **Un evento por inspección.** Si la persona corrige sus respuestas y genera de nuevo, recibe
  el Excel nuevo, pero el tablero conserva el evento de la primera vez.

## Estructura

```
modulos/inspector/
├── __main__.py          arranque del servicio
├── configuracion.py     ajustes del .env y configuración remota
├── preparadas.py        escenas preparadas
├── ejemplo.py           Excel y foto anotada de ejemplo, sin IA
├── nucleo/              sin IA: valoración, esquema, matriz, imagen y Excel
├── analisis/            cliente de Claude, caché, costos y consola
├── servicio/            API HTTP, almacén de inspecciones y publicación del evento
├── interfaz/            interfaz provisional de tablet
├── prompts/             prompt del sistema, versionado
├── esquemas/            esquema de la salida del modelo
├── config/              parámetros de valoración y precios
├── ejemplos/            datos de ejemplo
└── escenas/             escenas preparadas
```

Los eventos salen solo por `modulos/comun` (`subir_medio`, `publicar`, `iniciar_latido`).

## Pruebas

```
.venv\Scripts\python -m pytest pruebas\inspector
```

Ninguna prueba llama a la API ni necesita internet: el cliente de Claude es simulado. Cubren la
valoración con todas las combinaciones de ND, NE y NC, el Excel, la imagen, el análisis
(reintentos, rechazos, tiempo máximo, caché, costos), el servicio y la publicación del evento
contra el receptor de prueba.
