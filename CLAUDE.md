# auren-sst — Plataforma "SST en vivo"

## Contexto

Monorepo de la plataforma "SST en vivo" de Auren Advisory, para un stand en un evento
de UNIMINUTO sobre IA aplicada a Seguridad y Salud en el Trabajo (SST). Seis módulos
alimentan un tablero central: ergonomía REBA, EPP por perfil, zona de peligro con torre
de luz, inspector por foto, investigación por voz y el tablero. Los módulos 1 a 5 son
Python (`modulos/`, Juan); la plataforma es Next.js (`plataforma/`, Cristian). Ambos
lados se entienden solo por el contrato de eventos (`contrato/evento.schema.json`).
Arquitectura local primero: la PC del stand es el servidor y todo funciona sin internet,
salvo los módulos que llaman IA en la nube. El mensaje: la IA potencia al profesional de
SST, no lo reemplaza; todo resultado de IA es un "borrador — validar en campo".

Contexto completo, arquitectura y contrato: `docs/plataforma-sst-en-vivo-brief.md`.
Léelo antes de un cambio grande.

**Cambio respecto al brief, módulo de zona:** no hay ESP32 ni torre de luz. La alarma, visual
y sonora, vive en la plataforma; la estación solo publica eventos (`estado_zona`,
`ingreso_zona`, `casi_accidente`). Ver `modulos/zona/README.md`.

**No crear ni modificar nada dentro de `plataforma/`**: es de Cristian.

## Convenciones obligatorias para todos los módulos

- **Python 3.11+**, código modular, comentarios y docstrings **en español**.
- Cada módulo vive en `modulos/<nombre>/`, corre solo con un comando
  (`python -m modulos.<nombre>`) y tiene su `README.md`.
- Todo módulo publica eventos **únicamente a través de `modulos/comun`**
  (`publicar`, `iniciar_latido`, `subir_medio`). Nunca HTTP directo a la plataforma.
- **Primero un pipeline funcional de punta a punta**; la optimización viene después.
- **Funciona sin internet**, salvo los módulos que llaman IA en la nube (inspector e incidente).
- **Toda imagen guardada o enviada lleva los rostros difuminados**: pasa por
  `modulos.comun.difuminar_rostros(frame)` antes de escribirla en disco o subirla, y las
  cajas y etiquetas se dibujan **después** del difuminado. No se guarda video, solo
  fotogramas puntuales.
- **Excepción, la vista en vivo**: en los módulos de visión, la imagen de la cámara que se
  muestra en pantalla en el momento es un espejo y **no** se difumina, porque no se guarda
  ni se envía. En cuanto un fotograma sale de esa vista (archivo, subida, adjunto, captura
  para un reporte), aplica la regla anterior sin excepciones.
- **Excepción, fotos de entrenamiento**: para enseñar a un modelo elementos que van en la
  cara (gafas, tapabocas) se pueden guardar fotos **sin difuminar**, solo con estas
  condiciones: quien aparece aceptó posar; se guardan en `datasets/` (fuera de git) en el
  equipo donde se tomaron; nunca se suben, se adjuntan a eventos ni se envían a ningún
  servicio; y cualquier otro rostro que salga en la imagen se difumina. Hoy solo aplica a
  `modulos/epp/datos/capturar.py`.
- **Excepción, videos de prueba para desarrollo**: para desarrollar y ajustar un módulo sin
  estar frente a la cámara se pueden grabar videos cortos **sin difuminar** con
  `herramientas/grabar_video.py`, con las mismas condiciones: quien aparece aceptó ser
  grabado; se guardan en `datasets/videos/` (fuera de git) en el equipo donde se grabaron;
  y nunca se suben, se adjuntan a eventos ni se envían a ningún servicio. Es material de
  desarrollo, no de la demo: durante el evento no se graba video de los visitantes. Todo
  fotograma que salga de uno de estos videos hacia un archivo, un evento o un reporte se
  difumina como cualquier otro.
- **Configuración por `.env`** (con `.env.example` versionado). Nunca claves en el código.
- Debe funcionar en **Windows y Linux**: rutas con `pathlib`, archivos con `encoding="utf-8"`.
- **Marca Auren** en cualquier interfaz visual: Auren Deep `#12343B`, Auren Black `#111414`,
  marfil `#F2F1EA`; lima `#C8F169` solo como acento (máx. ~10 % de la pantalla, nunca texto
  lima sobre marfil). Nada de iconografía de IA (cerebros, robots, circuitos).
- **Antes de cambios grandes, mostrar el plan y esperar aprobación.**

## Contrato de eventos

- `contrato/evento.schema.json` es la fuente de verdad. Si cambia un campo, cambia ahí
  primero, junto con su ejemplo en `contrato/ejemplos/`, y se avisa a Cristian.
- `publicar()` valida contra el esquema antes de enviar; un evento inválido lanza
  `EventoInvalido` y es un error del módulo, no algo que reintentar.
- El latido (`estado_modulo`) sale con la estación del módulo que late y no se encola.
- La cola de respaldo usa un archivo por estación: un solo proceso por estación.

## Comandos

Instalar (Windows; en Linux cambia `.venv\Scripts\` por `.venv/bin/`):

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env
```

Correr el receptor de prueba (imita la API local; página en http://localhost:8000):

```
.venv\Scripts\python -m herramientas.receptor_prueba
```

Publicar tres eventos de ejemplo contra el receptor:

```
.venv\Scripts\python -m modulos.comun
```

Correr las pruebas:

```
.venv\Scripts\python -m pytest
```

Bajar los modelos públicos que usan los módulos (una vez por equipo, con internet):

```
.venv\Scripts\python -m herramientas.descargar_modelos
```

Los pesos preentrenados y públicos (hoy `yolo26n-pose.pt`, del módulo de zona) **no se
versionan**: se pueden volver a bajar y `*.pt` está en `.gitignore`. Se anotan en
`herramientas/descargar_modelos.py` con su URL, tamaño y huella SHA-256, y esa herramienta los
trae si faltan. Solo se versionan los pesos entrenados por nosotros (los de EPP), que son únicos.

## Cámaras

Las demos corren en webcams USB Logitech externas, no en la cámara del portátil. Reglas
para todos los módulos de visión:

- Abrir la cámara con `modulos.comun.conectar_camara(ConfigCamara.desde_entorno("<MODULO>"))`,
  no con `cv2.VideoCapture` directo. (`abrir_camara(indice)` es la utilidad anterior; EPP
  todavía la usa.)
- La cámara se elige **por índice**, desde el `.env` (`<MODULO>_CAMARA`) o la configuración
  del módulo; la integrada del portátil suele ser la 0. El nombre de dispositivo es solo un
  respaldo: dos Logitech del mismo modelo se llaman igual.
- **Cada cámara se conecta siempre al mismo puerto USB**: el índice puede cambiar al
  cambiarla de puerto. Tras mover un cable, confirmar con la vista previa de
  `python -m herramientas.listar_camaras`.
- Backend DirectShow en Windows y V4L2 en Linux.
- Por defecto MJPG, 1280x720 a 30 fps (configurable), para que dos cámaras convivan en el
  mismo USB.
- Autofoco apagado y enfoque fijo; la exposición se puede fijar desde configuración. Si la
  cámara no soporta una propiedad, se informa en el log y se sigue.
- Se informan la resolución y los fps reales obtenidos.
- Si la cámara se desconecta, el módulo no se cierra: muestra "Cámara desconectada,
  reconectando…" y reintenta hasta que vuelva.
