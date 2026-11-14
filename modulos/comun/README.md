# modulos/comun — cliente compartido

Única puerta de salida de los módulos hacia la plataforma. Ningún módulo hace HTTP
directo: todos usan estas funciones.

```python
from modulos.comun import publicar, iniciar_latido, subir_medio, difuminar_rostros
```

Probarlo solo (publica tres eventos de ejemplo en `API_URL`):

```
python -m modulos.comun
```

## Funciones

| Función | Qué hace |
|---|---|
| `publicar(estacion, tipo, datos, severidad="info", sesion_id=None, adjuntos=None)` | Arma el sobre, lo valida contra `contrato/evento.schema.json`, lo escribe en la cola local y retorna de inmediato. Un hilo lo envía a `{API_URL}/api/eventos`. Devuelve el sobre. |
| `iniciar_latido(estacion, modulo)` | Hilo que publica `estado_modulo` cada 30 s. Devuelve un objeto con `estado`, `mensaje` y `detener()`. |
| `subir_medio(ruta_archivo)` | POST multipart (campo `archivo`) a `{API_URL}/api/medios`. Devuelve la `ruta` para `adjuntos`. Si falla, copia el archivo a `CARPETA_COLA/medios_pendientes/` y devuelve esa ruta local. |
| `difuminar_rostros(frame)` | Recibe un frame BGR de OpenCV y devuelve una copia con los rostros difuminados. |
| `registrar_capacidades(modulo, capacidades)` | PUT a `{API_URL}/api/modulos/{modulo}/capacidades`: el módulo declara qué sabe hacer. Si la plataforma no responde, queda pendiente y se reintenta. |
| `obtener_config(modulo, por_defecto, validar=None, al_cambiar=None)` | Arranca un hilo que consulta `GET {API_URL}/api/modulos/{modulo}/config` cada `CONFIG_INTERVALO_S` y devuelve un objeto con `valor`, `fuente`, `al_cambiar()` y `detener()`. Nunca bloquea: sin plataforma usa la última configuración válida (`CARPETA_COLA/config/<modulo>.json`) y, si no hay, `por_defecto`. `validar` normaliza o rechaza (con `ValueError`) cada configuración. |
| `actualizar_config(modulo, config)` | El módulo cambia su propia configuración: se aplica de inmediato y se sube con PUT (si la plataforma no responde, cuando vuelva). |
| `abrir_camara(indice, ancho=1280, alto=720)` | Abre la cámara igual en todos los módulos de visión (MJPG, DirectShow en Windows). Devuelve `None` si no hay. `python -m modulos.comun.camaras` lista las conectadas. |
| `conectar_camara(config)` | Cámara del stand a partir de un `ConfigCamara` (índice o nombre, MJPG 1280x720 a 30 fps, autofoco apagado y enfoque fijo, exposición opcional; DirectShow en Windows y V4L2 en Linux). Devuelve una `Camara`: `leer()` da el fotograma o `None`, informa `resolucion` y `fps_reales`, y si se desconecta reintenta sola (`mensaje` = "Cámara desconectada, reconectando…"). `ConfigCamara.desde_entorno("ERGONOMIA")` la lee del `.env`. `python -m herramientas.listar_camaras` lista las cámaras con vista previa. |
| `esperar_envios(tiempo_limite_s=5)` | Espera a que la cola se vacíe; útil antes de cerrar un script corto. |
| `eventos_pendientes(estacion=None)` | Cuántos eventos siguen sin entregar. |

## Cola de respaldo

- Cada evento se escribe **primero en disco** (`CARPETA_COLA/<estacion>.jsonl`) y luego se
  envía. Si el módulo se cae o la API no responde, el evento sigue ahí.
- El hilo de envío reintenta con espera creciente: 1 s, 2 s, 4 s… hasta 60 s.
- Los eventos se entregan en el orden en que se publicaron.
- Si la API responde 422, el evento pasa a `<estacion>.rechazados.jsonl`: reintentarlo no
  serviría. Si el evento es inválido desde el módulo, `publicar()` lanza `EventoInvalido`.
- Los latidos **no** se encolan: un latido viejo no sirve.
- Limitación: un solo proceso por estación (un archivo de cola por estación).
- Lo que quede en la cola al cerrar se envía cuando la estación vuelva a publicar.
- Los medios guardados en `medios_pendientes/` no se resuben solos todavía.

## Rostros

Detector YuNet de OpenCV: corre en CPU y sin internet. El modelo
(`modelos/face_detection_yunet_2023mar.onnx`, 230 KB, licencia MIT) viene del repositorio
oficial [opencv_zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet).
Si el modelo falta, se usa la cascada Haar incluida en OpenCV, que es menos precisa.

## Configuración (.env)

| Variable | Por defecto | Para qué |
|---|---|---|
| `API_URL` | `http://localhost:8000` | API local de la plataforma |
| `DISPOSITIVO` | nombre del equipo | Va en `origen.dispositivo` |
| `CARPETA_COLA` | `cola` | Carpeta de la cola y de los medios de respaldo |
| `CONFIG_INTERVALO_S` | `3` | Cada cuántos segundos se consulta la configuración remota |
| `LOG_NIVEL` | `INFO` | Nivel de los logs |
