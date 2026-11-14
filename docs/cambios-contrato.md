# Cambios de contrato — módulo EPP configurable

Para Cristian. Resume lo que el módulo EPP espera ahora de la plataforma. Todo está
implementado en el receptor de prueba (`herramientas/receptor_prueba/app.py`), que sirve de
referencia ejecutable, y en `modulos/comun/config_remota.py` del lado de los módulos.

Idea general: **la plataforma manda y el módulo consulta.** El módulo no expone ningún
servidor. Al arrancar dice qué sabe hacer (capacidades) y luego pregunta cada 3 s cuál es
su configuración. Los endpoints son genéricos por `{modulo}`; hoy solo los usa `epp`.

## 1. Endpoints nuevos

| Método y ruta | Quién lo llama | Cuerpo | Respuesta |
|---|---|---|---|
| `PUT /api/modulos/{modulo}/capacidades` | El módulo, al arrancar | Capacidades (JSON) | 200 |
| `GET /api/modulos/{modulo}/config` | El módulo, cada ~3 s | — | 200 con la configuración, o **404** si aún no hay |
| `PUT /api/modulos/{modulo}/config` | La interfaz de la plataforma (operador) **y** el módulo (cambio por teclado) | Configuración (JSON) | 200; 422 si no cumple el esquema |

Los cuerpos van tal cual, sin envoltorio: el `GET` devuelve exactamente el objeto que se
guardó con el `PUT`.

El receptor de prueba tiene además `GET /api/modulos/{modulo}/capacidades` y
`GET /api/modulos` (todo junto) para armar su página; la plataforma puede resolverlo como
prefiera, los módulos no los usan.

### Comportamientos que conviene respetar

- **404 en el GET de config**: significa «todavía no tengo configuración». El módulo
  responde subiendo la suya con `PUT`, para que la plataforma tenga algo que mostrar. Si la
  plataforma prefiere crear ella una configuración inicial, basta con que nunca devuelva 404.
- **El PUT de config guarda y nada más.** No hace falta avisar al módulo: la verá en su
  siguiente consulta. Gana el último que escribe (operador o teclado de la estación).
- **Capacidades se vuelven a registrar** cada vez que el módulo arranca; reemplazan a las
  anteriores. Pueden cambiar entre arranques (por ejemplo, si falta un modelo, ese perfil
  no aparece).
- Si la plataforma no responde, el módulo sigue con la última configuración válida y
  reintenta solo. No hay nada que hacer del lado de la plataforma.

## 2. Capacidades del módulo EPP

Cuerpo de `PUT /api/modulos/epp/capacidades`. Los elementos salen de las clases del modelo
cargado, no de una lista fija: úsalos para pintar los controles.

```json
{
  "perfiles": {
    "alimentos": {
      "nombre": "Planta de alimentos",
      "elementos": [
        { "id": "cofia", "nombre": "Cofia" },
        { "id": "gafas", "nombre": "Gafas" },
        { "id": "tapabocas", "nombre": "Tapabocas" }
      ]
    },
    "industria": {
      "nombre": "Industria",
      "elementos": [
        { "id": "casco", "nombre": "Casco" },
        { "id": "gafas", "nombre": "Gafas" },
        { "id": "chaleco", "nombre": "Chaleco" }
      ]
    }
  }
}
```

`id` es lo que viaja en la configuración y en los eventos; `nombre` es para mostrar.

## 3. Configuración del módulo EPP

Esquema: [`contrato/config_epp.schema.json`](../contrato/config_epp.schema.json).

```json
{
  "perfil_activo": "industria",
  "perfiles": {
    "alimentos": { "elementos_requeridos": ["cofia", "gafas", "tapabocas"] },
    "industria": { "elementos_requeridos": ["casco", "gafas"] }
  }
}
```

- `perfil_activo` (obligatorio): una de las claves de `capacidades.perfiles`.
- `perfiles.<id>.elementos_requeridos`: lista de `id` de elementos de ese perfil. Un perfil
  que no aparezca conserva sus valores por defecto. Lista vacía = no se exige nada.

Cómo reacciona el módulo:

| Lo que recibe | Qué hace |
|---|---|
| Configuración válida y distinta | La aplica en vivo, reinicia el veredicto y publica `config_actualizada` |
| Elemento que el modelo del perfil no detecta | Lo ignora (advertencia en su log) y aplica el resto |
| `perfil_activo` que no existe, o forma inválida | La rechaza entera y conserva la anterior |

El módulo normaliza lo que recibe (quita elementos desconocidos, ordena), así que lo que
aplica puede diferir de lo guardado; lo aplicado es lo que llega en `config_actualizada`.

Sugerencia para la interfaz: un selector de perfil y un interruptor por elemento del perfil
activo; en cada cambio, `PUT` con el objeto completo. La página del receptor de prueba
(`herramientas/receptor_prueba/pagina.html`) lo hace en unas 60 líneas.

## 4. Evento nuevo: `config_actualizada`

Añadido a [`contrato/evento.schema.json`](../contrato/evento.schema.json) (el sobre no cambia,
`version_esquema` sigue en 1). Ejemplo en
[`contrato/ejemplos/config_actualizada.json`](../contrato/ejemplos/config_actualizada.json).

- `tipo`: `config_actualizada`; `estacion`: siempre `epp`; `severidad`: siempre `info`.
- `datos.perfil_activo` (texto) y `datos.elementos_requeridos` (lista): lo que el módulo
  **aplicó**, solo del perfil activo.
- Se publica cuando cambia la configuración, venga de la plataforma o del teclado de la
  estación. No se publica al arrancar.

Sirve para que el tablero confirme al operador que el cambio llegó a la estación.

## 5. Lo que no cambió

- `verificacion_epp` conserva su forma. `perfil` ahora es `alimentos` o `industria`;
  `detectados` son los elementos requeridos que la persona lleva; trae una imagen adjunta
  (rostros difuminados) subida antes por `POST /api/medios`. Severidad `info` si cumple y
  `media` si falta algo. Puede llegar más de uno por visitante si su veredicto cambia.
- `POST /api/eventos`, `GET /api/eventos`, `POST /api/medios` y el latido, sin cambios.

---

# Cambios de contrato — módulo de ergonomía REBA

Para Cristian. Lo que agrega el módulo de ergonomía. Todo es aditivo: `version_esquema`
sigue en 1 y nada de lo anterior cambia.

## 1. Configuración del módulo de ergonomía

Usa los mismos endpoints genéricos (`/api/modulos/ergonomia/capacidades` y
`/api/modulos/ergonomia/config`). Esquema:
[`contrato/config_ergonomia.schema.json`](../contrato/config_ergonomia.schema.json).

```json
{
  "peso_carga_kg": 5,
  "agarre": "bueno",
  "golpe_o_fuerza_brusca": false,
  "actividad": { "estatica": false, "repetitiva": false, "cambios_rapidos": false },
  "modo_deteccion": "auto",
  "lado": "auto",
  "camara": null,
  "ajuste_brazo_inclinada": true,
  "umbral_tronco_inclinado": 45,
  "tolerancia_brazo_vertical": 20
}
```

- Todas las claves son opcionales: la que falte conserva su valor por defecto.
- `camara`: índice o nombre; `null` = la del `.env` de la estación.
- El módulo aplica los cambios en vivo, en el siguiente fotograma.
- Capacidades que registra: `agarres`, `modos_deteccion`, `lados`, `condiciones_actividad`
  (con `id` y `nombre`) y el rango de `peso_carga_kg`, para pintar los controles.

## 2. Pendiente: `config_actualizada` solo admite la estación `epp`

El esquema fija `config_actualizada` a `estacion: "epp"` y a los campos `perfil_activo` y
`elementos_requeridos`. Por eso **ergonomía aplica la configuración en vivo pero no publica
ese evento**: el tablero no recibe confirmación de que el cambio llegó a la estación. Si se
quiere esa confirmación para ergonomía hay que abrir el esquema (permitir otras estaciones
y una forma de `datos` por módulo). Queda como decisión conjunta; no se cambió nada.

## 3. Cámaras: todos los módulos usan `conectar_camara`

`modulos/comun/camara_stand.py` trae `conectar_camara(ConfigCamara)`: selección por índice
o nombre, MJPG 1280x720 a 30 fps, enfoque fijo, exposición opcional y reconexión
automática. Ergonomía y EPP ya la usan (EPP con las variables `EPP_CAMARA_*`). No afecta a
la plataforma.

## 4. `evaluacion_reba`: campos opcionales nuevos

Añadidos a `datos` en [`contrato/evento.schema.json`](../contrato/evento.schema.json); ejemplo
actualizado en [`contrato/ejemplos/evaluacion_reba.json`](../contrato/ejemplos/evaluacion_reba.json).
`puntaje` y `nivel` siguen siendo los únicos obligatorios: un tablero que solo lea esos dos
sigue funcionando.

| Campo | Tipo | Qué trae |
|---|---|---|
| `puntajes` | objeto | Desglose: puntaje de cada segmento estimado (`tronco`, `cuello`, `piernas`, `brazo`, `antebrazo`, `muneca`) y `tabla_a`, `carga`, `puntaje_a`, `tabla_b`, `agarre`, `puntaje_b`, `tabla_c`, `actividad` |
| `lado` | `izquierdo` o `derecho` | Lado del cuerpo evaluado |
| `intento` | entero ≥ 1 | Número del intento dentro de la visita. Sirve para armar "Intento 1 → Intento 2" |
| `segmentos_no_estimados` | lista | Segmentos que la cámara no pudo medir. No traen ángulo ni puntaje |
| `segmentos_asumidos` | lista | Segmentos no estimados que entraron al cálculo con su mínimo (solo la muñeca). Si no está vacía, el puntaje es una cota inferior |
| `ajustes_aplicados` | lista | Ajustes automáticos del método; hoy `brazo_persona_inclinada` (−1 al brazo) |
| `no_evaluado` | lista | Siempre `torsion`, `inclinacion_lateral`, `abduccion`: una cámara lateral 2D no los mide y no suman |
| `peso_carga_kg`, `agarre` | número, texto | Condiciones de la tarea usadas en el cálculo |

Cómo llega el evento:

- **Uno por levantamiento**, al terminar. Un visitante puede generar varios (uno por intento);
  todos llevan el mismo `sesion_id` si el operador lo tecleó, y ninguno si no.
- `puntaje`, `angulos` y `puntajes` son los del **fotograma crítico**: el de mayor puntaje
  sostenido durante 0,3 s dentro del levantamiento.
- `angulos` solo trae los segmentos estimados (un segmento sin estimar no lleva número).
- `duracion_s`: desde que empieza a agacharse hasta que vuelve a estar erguido.
- `severidad`: 1 → `info`; 2–3 → `baja`; 4–7 → `media`; 8–10 → `alta`; 11–15 → `critica`.
- Trae **una imagen adjunta**: el fotograma crítico con los rostros difuminados y el
  esqueleto dibujado encima, subida antes por `POST /api/medios`.
- El latido (`estado_modulo`) sale con `estacion: "ergonomia"` y `modulo: "ergonomia"`; pasa
  a `estado: "error"` con el mensaje "Cámara desconectada, reconectando…" si se cae la cámara.

## 5. Postura neutra por persona

De pie y derecha, una persona no da 0° con los puntos de la cámara: el tronco sale en unos
−10° y el cuello en unos 30°. El módulo ahora calibra esa postura (la persona quieta de pie
0,7 s, una vez por persona) y mide tronco, cuello y brazo desde ahí.

- Configuración: clave nueva `postura_neutra` (booleano, por defecto `true`) en
  [`contrato/config_ergonomia.schema.json`](../contrato/config_ergonomia.schema.json).
  También `deteccion` (objeto con los umbrales del modo automático).
- Evento `evaluacion_reba`: campo opcional `datos.postura_neutra` = `{ "tronco", "cuello" }`
  con la postura de pie medida, en grados crudos. Cuando viene, `angulos.tronco`,
  `angulos.cuello` y `angulos.brazo` ya están corregidos. Si falta, la persona se agachó
  sin haber estado quieta antes y los ángulos van sin corregir.

Para el tablero: lo que la buena técnica cambia es `angulos.tronco` (la flexión de espalda),
más que `puntaje`. Recoger una caja del piso da REBA alto doblando la espalda **y** en
sentadilla, porque el método suma 2 puntos por rodillas a más de 60°. Un ranking de "mejor
técnica" debería ordenar por `angulos.tronco` del fotograma crítico, no por `puntaje`.

## 6. Qué significa el puntaje, técnica de levantamiento y `desde_piso`

REBA no califica si la persona levantó "bien" o "mal": estima el riesgo de una postura si
forma parte de un trabajo y qué tan urgente es intervenir **la tarea**. La estación ahora lo
dice así, y conviene que el tablero use el mismo lenguaje. Los textos están en
[`modulos/ergonomia/nucleo/mensajes_reba.json`](../modulos/ergonomia/nucleo/mensajes_reba.json)
(etiqueta corta, mensaje del panel, nivel de acción y texto ampliado para el reporte, por nivel).

| Nivel | Puntaje | Etiqueta | Nivel de acción |
|---|---|---|---|
| `insignificante` | 1 | Riesgo insignificante | No es necesario intervenir. |
| `bajo` | 2–3 | Riesgo bajo | Puede ser necesario intervenir. |
| `medio` | 4–7 | Riesgo medio · intervenir | Es necesario intervenir. |
| `alto` | 8–10 | Riesgo alto · intervenir pronto | Es necesario intervenir pronto. |
| `muy_alto` | 11–15 | Riesgo muy alto · intervenir ya | Es necesario intervenir de inmediato. |

Línea fija que acompaña siempre al puntaje: «REBA no califica tu técnica: estima el riesgo de
una postura si forma parte de un trabajo.»

Campos opcionales nuevos en `datos` de `evaluacion_reba` (aditivos; `version_esquema` sigue en 1):

| Campo | Tipo | Qué trae |
|---|---|---|
| `desde_piso` | booleano | `true` si el levantamiento empezó desde el piso (las muñecas bajaron de la altura de las rodillas); `false` si la carga estaba elevada. Si falta, no se pudo determinar |
| `tecnica.espalda_max` | número | Mayor flexión del tronco durante el levantamiento, en grados |
| `tecnica.nivel_espalda` | `baja`, `media`, `alta` | Hasta 20°; de 20° a 60°; más de 60° (las franjas del tronco de REBA) |
| `tecnica.rodillas_max` | número | Mayor flexión de rodillas durante el levantamiento, en grados |
| `tecnica.piernas` | `rectas`, `poco_flexionadas`, `flexionadas` | Menos de 30°; de 30° a 60°; más de 60° (las franjas de rodilla de REBA) |

`tecnica` no es un método de evaluación: muestra lo que la técnica de levantamiento cambia
(cuánto se dobla la espalda y si el esfuerzo lo hacen las piernas), con las mismas franjas de
REBA. Va junto al puntaje, no en su lugar.

Por qué importa `desde_piso`: desde el piso, incluso con buena técnica, el REBA rara vez baja
de medio, porque el método suma por la flexión de espalda **o** por la de rodillas. Lo que
más reduce el puntaje es cambiar la tarea (elevar o acercar la carga). Para un ranking de
"mejor técnica", ordenar por `tecnica.espalda_max` y no por `puntaje`.

## 7. `reporte_generado`: un PDF por intento

Al terminar cada levantamiento, después de `evaluacion_reba`, la estación genera un PDF de
una página, lo sube con `POST /api/medios` y publica `reporte_generado`
([ejemplo](../contrato/ejemplos/reporte_generado.json)).

- `datos.reporte_id`: `REBA-0142-01` para el visitante `V-0142`, intento 1. Sin número de
  visitante, el lugar del número lo ocupa un código al azar de seis caracteres, el mismo
  para todos los intentos de esa visita (`REBA-7F3A9C-01`, `REBA-7F3A9C-02`).
- `datos.url_reporte`: la ruta que devolvió `POST /api/medios`; es la misma del adjunto
  (`adjuntos: [{ "tipo": "pdf", "ruta": ... }]`).
- Campos opcionales nuevos (aditivos): `datos.intento` (número del intento) y
  `datos.evaluacion_id` (el `id` del `evaluacion_reba` del mismo intento), para enlazar el
  reporte con su evaluación.
- `severidad`: siempre `info`. Lleva `sesion_id` si el operador tecleó el número.
- Con varios intentos en la visita hay un PDF por intento; el último trae la comparación
  con los anteriores. Para el pasaporte basta con mostrar el de `intento` más alto.
- Si el PDF no se puede generar, `evaluacion_reba` se publica igual y no hay `reporte_generado`.

Qué trae el PDF: fotograma crítico (rostros difuminados, con esqueleto), puntaje y nivel con
su nivel de acción, tabla de ángulos y puntajes por segmento, el cálculo (tablas A, B y C),
la sección "Qué significa este resultado", la comparación de intentos si la hay, de 2 a 4
recomendaciones por reglas escritas (sin IA, funciona sin internet) y cómo se midió.

**QR en la estación:** si la PC tiene `BASE_URL_PUBLICA` en su `.env` y el operador tecleó
el número de visitante, la pantalla de ergonomía muestra un QR hacia
`{BASE_URL_PUBLICA}/r/{sesion_id}` desde el primer intento. Sin esa variable no hay QR. La
URL pública sigue siendo una decisión abierta del brief: la estación solo la lee.

---

# Cambios de contrato — módulo de zona de peligro

Para Cristian. Lo que agrega el módulo de zona. Todo es aditivo: `version_esquema` sigue en 1
y ningún evento anterior cambia de forma.

**Cambio respecto al brief: no hay ESP32 ni torre de luz.** La alarma, visual y sonora, vive
en la plataforma. La estación solo publica eventos y tiene un respaldo visual en su ventana.

Cubre los eventos (con sus fotos), la configuración de la zona, la calibración y, en la
sección 5, **lo que la plataforma debe implementar**: el flujo en tiempo real, la vista de
alarma y el editor de zona. Todo está funcionando en el receptor de prueba, que sirve de
referencia ejecutable.

La zona de mano que mencionaba el plan (un segundo polígono sobre la mesa de la máquina) **no
se implementó**: hay una sola zona, la de piso, con `zona_id: "piso"`.

## 1. Evento nuevo: `estado_zona`

Añadido a [`contrato/evento.schema.json`](../contrato/evento.schema.json); ejemplo en
[`contrato/ejemplos/estado_zona.json`](../contrato/ejemplos/estado_zona.json). De este evento
depende la alarma.

| Campo | Valor |
|---|---|
| `tipo`, `estacion` | `estado_zona`, siempre `zona` |
| `datos.zona_id` | Siempre `piso`: la zona marcada con cinta |
| `datos.estado` | `libre`, `advertencia` o `peligro`: el peor nivel entre las personas a la vista |
| `datos.personas_peligro` | Personas con un pie dentro de la zona |
| `datos.personas_advertencia` | Personas en la franja de advertencia, sin pisar la zona |
| `datos.refresco` | Opcional. `true` si el evento repite el estado vigente sin que nada haya cambiado |
| `severidad` | `libre` → `info`; `advertencia` → `media`; `peligro` → `alta` |

Cuándo se publica:

- **En cada cambio** de estado o de conteos (por ejemplo, una segunda persona se acerca
  mientras la zona ya está en peligro). Estos no traen `refresco`.
- **Al arrancar y al cerrar la estación**, uno con `libre`, para que ninguna alarma se quede
  encendida de una sesión anterior.
- **Cada 2 s mientras la zona no esté libre**, con `refresco: true`. Mantiene viva la alarma:
  si dejan de llegar, la estación se cayó o perdió la conexión.

Un cambio se confirma cuando se sostiene 0,3 s, así que la alarma no parpadea con el temblor
de la detección. Si la estación estuvo sin conexión, los eventos salen de su cola local más
tarde y con su `timestamp` original.

Lo que el tablero debe hacer:

1. **Alarma por zona.** El estado de cada zona es su último `estado_zona`; la alarma del stand
   es el peor estado entre las zonas. Hoy solo existe `piso`, pero conviene llevar el estado
   por `zona_id` y no suponer que es una sola.
2. **Ignorar los viejos.** Un `estado_zona` con más de 5 s de antigüedad (su `timestamp`
   frente a la hora actual) no enciende ni cambia la alarma: salió tarde de una cola.
3. **Apagado automático.** Si pasan 5 s sin recibir ningún `estado_zona` de una zona que no
   está libre, la alarma de esa zona se apaga sola.
4. **Filtrar los refrescos del historial.** Los eventos con `refresco: true` no van al feed ni
   a los conteos: solo sirven para sostener la alarma.

## 2. `ingreso_zona` y `casi_accidente`

Ya existían. Lo que cambia y cómo llegan:

- **`ingreso_zona`**: uno por persona, cuando **sale** de la zona de peligro. `duracion_s` va
  desde que puso el pie dentro hasta que dejó de estar dentro. `alarma_activada` dice si la
  alarma estuvo activa en algún momento del ingreso. Severidad `alta`. Si la misma persona
  entra dos veces, llegan dos.
  - Quien queda oculto dentro de la zona (detrás de la máquina) sigue contando como dentro:
    la zona sigue en `peligro` hasta 4 s después de dejar de verlo. Si no reaparece, llega
    su `ingreso_zona` con la duración hasta la última vez que se vio.
- **`casi_accidente`**: cuando una persona entra a la franja de advertencia y se va sin pisar
  la zona. Quien sí entró genera `ingreso_zona`, no `casi_accidente`. Severidad `alta`.
  - Campo opcional nuevo: `datos.distancia_min_m`, la distancia mínima en metros sobre el
    piso. Solo viene cuando la zona está calibrada con sus medidas reales.
  - `datos.distancia_min_px` viene siempre (píxeles de la imagen).
  - `datos.descripcion` solo menciona metros cuando hay `distancia_min_m`.
  - El [ejemplo](../contrato/ejemplos/casi_accidente.json) se corrigió: antes describía a
    alguien dentro del perímetro con severidad `critica`, que es un `ingreso_zona`.
- Ninguno de los dos trae `sesion_id`: la cámara de la zona no identifica al visitante.
- **Los dos traen una imagen adjunta** (`adjuntos: [{ "tipo": "imagen", "ruta": ... }]`), subida
  antes por `POST /api/medios`, con los rostros difuminados y, dibujados encima, la zona en
  rojo, la franja de advertencia en amarillo y los puntos de apoyo de la persona:
  - `ingreso_zona`: el momento en que se confirmó que la persona entró.
  - `casi_accidente`: el momento en que estuvo más cerca de la zona.
  - Si la plataforma no respondió al subirla, la `ruta` es una ruta local de la estación
    (`cola/medios_pendientes/...`), igual que en los demás módulos.
- **`alarma_activada`** es `true` si, en algún momento del ingreso, la plataforma estaba
  recibiendo los eventos de la estación (o la estación tenía su sonido local encendido). Es
  `false` cuando la persona entró y salió con la plataforma caída: la alarma no pudo sonar.
- **Un evento por persona, aunque el tracker le cambie el id.** Si la cámara pierde a alguien
  un instante y lo vuelve a ver, sigue siendo la misma persona: no llegan dos `ingreso_zona`
  ni un `casi_accidente` de más.
- `estado_zona` sale en el acto. Si la estación estaba reintentando tras una caída de la
  plataforma, un `estado_zona` nuevo corta esa espera: llega apenas la plataforma responde.

## 3. Configuración del módulo de zona

Usa los endpoints genéricos (`/api/modulos/zona/capacidades` y `/api/modulos/zona/config`).
Esquema: [`contrato/config_zona.schema.json`](../contrato/config_zona.schema.json).

```json
{
  "zona_peligro": [[0.31, 0.42], [0.68, 0.40], [0.74, 0.81], [0.27, 0.84]],
  "rectangulo_real": { "ancho_m": 1.5, "largo_m": 1.0 },
  "margen_advertencia_m": 0.5,
  "margen_advertencia_px": 80,
  "imagen_referencia": "media/2026-11-14/ab12cd34.jpg",
  "solicitud_deteccion": null,
  "zona_propuesta": null,
  "deteccion": {
    "confianza_persona": 0.4, "confianza_punto": 0.5, "antirrebote_s": 0.3,
    "histeresis": 0.2, "segundos_perdida": 1.0, "segundos_perdida_peligro": 4.0,
    "radio_reasociacion_m": 0.5, "radio_reasociacion_px": 80
  },
  "cinta_hsv": { "h_min": 18, "h_max": 38, "s_min": 80, "v_min": 80 },
  "sonido_local": false
}
```

| Campo | Quién lo escribe | Qué es |
|---|---|---|
| `zona_peligro` | Quien guarda la zona | Polígono activo. `null`: no hay zona y el módulo no vigila nada |
| `rectangulo_real` | Quien guarda la zona | Medidas reales del rectángulo de cinta. `null`: todo va en píxeles |
| `margen_advertencia_m`, `margen_advertencia_px` | Operador | Ancho de la franja de advertencia, en metros o en píxeles |
| `imagen_referencia` | Quien guarda la zona | Ruta de la imagen sobre la que se marcó `zona_peligro` |
| `solicitud_deteccion` | Plataforma | Pedido de detección automática de la cinta (ver sección 4) |
| `zona_propuesta` | **Módulo** | Su respuesta al pedido. Solo una propuesta |
| `deteccion`, `cinta_hsv`, `sonido_local` | Operador | Ajustes finos; normalmente no se tocan |

Reglas:

- **Los polígonos van normalizados**: cada vértice es `[x, y]` de 0 a 1 sobre la imagen de
  referencia, con `(0, 0)` arriba a la izquierda. Así no dependen de la resolución.
- **Metros o píxeles.** Si `zona_peligro` tiene cuatro vértices y hay `rectangulo_real`, el
  módulo mide en metros: usa `margen_advertencia_m` y los eventos traen `distancia_min_m`.
  Si no, mide en píxeles con `margen_advertencia_px` y los mensajes no mencionan metros.
- **Cuál lado es cuál.** `ancho_m` es el lado del primer vértice al segundo; `largo_m`, el
  del segundo al tercero. El editor debe rotular esos dos lados para que la persona escriba
  cada medida donde va.
- **El `PUT` reemplaza el documento entero.** Quien escribe debe leer la configuración,
  cambiar sus campos y mandarla completa. Mandar solo `{"solicitud_deteccion": ...}` es
  válido para el esquema, pero deja todo lo demás en su valor por defecto y **borra la zona**.
- **Esperar a que el módulo suba su configuración.** Mientras el `GET` devuelva 404 el
  módulo todavía no arrancó: el editor no debe escribir nada hasta que haya configuración.
- Una configuración con algo inválido (un polígono de dos vértices, una medida negativa) el
  módulo la rechaza entera y conserva la anterior. El receptor de prueba responde 422.

### Capacidades

```json
{
  "zonas": [ { "id": "piso", "nombre": "Zona de piso" } ],
  "margen_advertencia_m": { "minimo": 0, "maximo": 3 },
  "imagen_referencia": { "ruta": "media/2026-11-14/ab12cd34.jpg", "ancho": 1280, "alto": 720,
                         "timestamp": "2026-11-14T10:02:13-05:00" }
}
```

`imagen_referencia` es la foto más reciente de la cámara (rostros difuminados), subida por
`POST /api/medios`: es el fondo sobre el que el editor dibuja la zona. El módulo la toma al
arrancar y en cada detección, y vuelve a registrar sus capacidades. Es `null` si no pudo
subirla.

## 4. Calibración: cómo se entienden el editor y el módulo

1. **Al arrancar**, el módulo sube la imagen de referencia y registra sus capacidades. No
   escribe la configuración (salvo la primera vez, si la plataforma no tiene ninguna).
2. **"Detectar zona"**: el editor escribe en `solicitud_deteccion` una marca de tiempo ISO
   8601 (con el documento completo).
3. **El módulo lo ve** en su siguiente consulta (hasta 3 s), busca la cinta amarilla en la
   imagen de ese momento, sube una imagen de referencia nueva y escribe `zona_propuesta`:

   ```json
   {
     "solicitud": "2026-11-14T10:02:11-05:00",
     "poligono": [[0.33, 0.25], [0.67, 0.25], [0.71, 0.57], [0.29, 0.57]],
     "es_cuadrilatero": true,
     "mensaje": "Se encontró el rectángulo de cinta. Revisa las esquinas, escribe sus medidas reales y guarda la zona.",
     "imagen_referencia": "media/2026-11-14/ef56ab78.jpg"
   }
   ```

   - `solicitud` repite el pedido atendido: el pedido está pendiente mientras
     `solicitud_deteccion` no sea `null` y sea distinto de `zona_propuesta.solicitud`.
   - `poligono` es `null` si no encontró la cinta; `mensaje` dice por qué (no hay amarillo,
     solo objetos macizos, la cinta se sale de la imagen o no cierra una figura) y sugiere
     marcarla a mano. Mostrar ese mensaje tal cual.
   - Los vértices salen en sentido horario empezando por el de arriba a la izquierda: el
     lado 1-2 es el de arriba en la imagen.
4. **La persona confirma.** El editor dibuja la propuesta sobre `zona_propuesta.imagen_referencia`,
   deja mover, agregar y quitar vértices y pide las medidas reales. **"Guardar zona"** escribe
   `zona_peligro`, `rectangulo_real` e `imagen_referencia`, y deja `zona_propuesta` y
   `solicitud_deteccion` en `null`. Solo entonces el módulo empieza a vigilar esa zona.
5. **Respaldo en la estación.** La ventana de la estación hace lo mismo con teclas y mouse,
   y al guardar escribe la configuración igual que el editor. Gana el último que escribe.

La detección conviene hacerla con la zona vacía, sin personas y antes de poner la máquina.

## 5. Lo que la plataforma debe implementar para la zona

Cuatro piezas. Las cuatro están hechas en el receptor de prueba
(`python -m herramientas.receptor_prueba`) y se pueden abrir para ver cómo se comportan:
[`app.py`](../herramientas/receptor_prueba/app.py) (el flujo),
[`alarma.html`](../herramientas/receptor_prueba/alarma.html) (la vista de alarma, en `/alarma`) y
[`pagina.html`](../herramientas/receptor_prueba/pagina.html) (el editor de zona, en `/`).

### 5.1 Flujo en tiempo real: `GET /api/stream`

Server-Sent Events (`Content-Type: text/event-stream`). La alarma no puede depender de
consultar cada 2 s: necesita enterarse en el acto.

- **Cada evento aceptado** por `POST /api/eventos` sale enseguida como un mensaje sin nombre,
  con `id:` igual al `id` del evento y, en `data:`, el sobre completo en una línea de JSON,
  tal como llegó. Salen todos los tipos y todas las estaciones.
- **Un mensaje `reloj`** al conectar y cada 5 s: `event: reloj` y `data: {"ahora": "<ISO 8601>"}`
  con la hora del servidor. Mantiene viva la conexión y le da a la vista la hora con que se
  estamparon los eventos.
- Un evento repetido (mismo `id`) o rechazado (422) no sale por el flujo.
- Quien se conecta recibe solo lo nuevo; lo anterior se consulta con `GET /api/eventos`.

```
event: reloj
data: {"ahora": "2026-11-20T10:41:00.512-05:00"}

id: c3d9a2f1-6b47-4e0a-8f15-2a9d7c4b1e60
data: {"id": "c3d9a2f1-...", "estacion": "zona", "tipo": "estado_zona", "timestamp": "2026-11-20T10:41:00-05:00", ...}
```

### 5.2 Vista de alarma, a pantalla completa

| Estado | Pantalla | Texto | Sonido |
|---|---|---|---|
| `libre` | Fondo Auren Deep | "Zona despejada" | Ninguno |
| `advertencia` | Borde amarillo que pulsa | "Precaución: persona cerca de la zona de peligro" | Pitido lento: 880 Hz, 0,22 s, cada 1,2 s |
| `peligro` | Fondo y borde rojos que pulsan | "PERSONA EN ZONA DE PELIGRO" | Pitido rápido: 1320 Hz, 0,14 s, cada 0,3 s |

- **Colores de seguridad, no de marca:** rojo `#E02B20` para peligro y amarillo `#F9C80E` para
  advertencia (NTC 1461). Es la única excepción a la lima como acento.
- **El estado que se muestra** es el peor entre las zonas (hoy solo `piso`), cada una con su
  último `estado_zona`. Debajo del texto va cuánta gente hay: `personas_peligro` y
  `personas_advertencia`.
- **Debajo:** ingresos y casi-accidentes del día (cuenta de `ingreso_zona` y `casi_accidente`
  de hoy) y el último de esos dos eventos, con su hora.
- **Sonido con Web Audio API**, con tonos generados (un oscilador), sin archivos de audio.
- **Botón grande "Activar sonido" al abrir.** Los navegadores bloquean el audio hasta que la
  persona interactúa con la página: sin ese clic la alarma no suena. La vista debe pedirlo de
  forma visible cada vez que se abre, y seguir funcionando en lo visual aunque nadie lo pulse.
- **Control de volumen y botón de silencio**, siempre a la vista. Conviene recordar el volumen
  pero no el silencio: la alarma no debe abrir callada porque alguien la silenció ayer.

### 5.3 Filtro de eventos viejos y apagado automático

Son las dos reglas que evitan que la pantalla muestre algo falso. Las dos usan 5 s.

1. **Un `estado_zona` con más de 5 s de antigüedad no enciende ni cambia la alarma.** Si la
   estación estuvo sin conexión, sus eventos salen después de su cola local con el `timestamp`
   original: sirven para el historial, no para alarmar. La antigüedad es la hora del servidor
   (la del mensaje `reloj`) menos el `timestamp` del evento; no la hora del navegador, que
   puede estar corrida. La estación y la plataforma corren en la misma PC, así que comparten reloj.
2. **Si pasan 5 s sin recibir ningún `estado_zona` de una zona que no está libre, su alarma
   se apaga sola**, y la vista dice que no hay señal de la estación. Mientras hay alguien, la
   estación repite el estado cada 2 s (`refresco: true`); si deja de hacerlo es que se cayó.
3. **Los eventos con `refresco: true` no van al historial ni a los conteos** del tablero:
   solo sostienen la alarma.

Al abrir la vista: primero conectarse al flujo, y con la hora del primer `reloj` leer los
eventos del día (`GET /api/eventos?estacion=zona&desde=...`) para los conteos. Como un evento
puede llegar por los dos caminos, hay que procesar cada `id` una sola vez.

### 5.4 Editor de zona

Un editor simple sobre la imagen de referencia de la cámara (`capacidades.imagen_referencia`):

- Dibuja el polígono vigente: la propuesta pendiente (`zona_propuesta.poligono`, punteada y
  sobre `zona_propuesta.imagen_referencia`) si hay una; si no, `zona_peligro`.
- **Vértices arrastrables**; **clic sobre la imagen agrega** uno (en el lado más cercano, para
  que el polígono no se cruce); clic derecho lo quita.
- Vértices numerados y, con cuatro, los lados 1-2 y 2-3 rotulados "ancho" y "largo".
- **Botón "Detectar zona"**: escribe `solicitud_deteccion` y espera la respuesta (sección 4).
  Si en unos 15 s no llega, avisar que la estación no respondió.
- **Campos de medidas reales** (ancho y largo en metros) y el margen de advertencia.
- **Botón "Guardar zona"**: escribe `zona_peligro`, `rectangulo_real` e `imagen_referencia`, y
  deja `zona_propuesta` y `solicitud_deteccion` en `null`.
- Mostrar el `mensaje` de la propuesta tal cual, y el detalle del 422 si la plataforma rechaza
  lo que se guarda.
- Mientras la persona tiene cambios sin guardar, no reemplazar lo que está editando con lo
  que llegue de la configuración.

Recordatorio de la sección 3: cada escritura lee la configuración vigente, cambia sus campos
y la manda completa.
