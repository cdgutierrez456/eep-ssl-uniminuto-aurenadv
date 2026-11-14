# auren-sst — Plataforma "SST en vivo"

Plataforma de Auren Advisory para el stand de IA aplicada a Seguridad y Salud en el
Trabajo en el evento de UNIMINUTO. Seis módulos alimentan un tablero central en tiempo
real. El contexto completo está en [docs/plataforma-sst-en-vivo-brief.md](docs/plataforma-sst-en-vivo-brief.md).

## Estructura

```
auren-sst/
├── contrato/                  # Fuente de verdad compartida
│   ├── evento.schema.json     # JSON Schema del sobre y de cada tipo de evento
│   ├── config_epp.schema.json # Configuración remota del módulo EPP
│   ├── config_ergonomia.schema.json # Configuración remota del módulo de ergonomía
│   ├── config_zona.schema.json # Configuración remota del módulo de zona
│   └── ejemplos/              # Un evento válido por tipo (sirven de mocks)
├── modulos/                   # Juan — Python
│   ├── comun/                 # Cliente compartido: publicar, latido, medios, rostros, config remota, cámaras
│   ├── epp/                   # Verificación de EPP por perfil en vivo (python -m modulos.epp)
│   ├── zona/                  # Zona de peligro con alarma en la plataforma (python -m modulos.zona)
│   └── ergonomia/             # Evaluación REBA en vivo, en su propio entorno (python -m modulos.ergonomia)
├── herramientas/
│   ├── descargar_modelos.py   # Baja los modelos públicos que no se versionan (python -m herramientas.descargar_modelos)
│   └── receptor_prueba/       # Imita la API local para probar módulos (no es la plataforma)
├── pruebas/                   # pytest
├── docs/                      # Brief técnico y cambios de contrato
└── plataforma/                # Cristian — Next.js (todavía no existe)
```

Ya está `epp` ([modulos/epp/README.md](modulos/epp/README.md)). Los módulos `ergonomia`, `zona`,
`inspector` e `incidente` se irán agregando en `modulos/<nombre>/`. Lo que cambió en el
contrato para el módulo EPP está en [docs/cambios-contrato.md](docs/cambios-contrato.md). Las convenciones están en [CLAUDE.md](CLAUDE.md).

También está `ergonomia` ([modulos/ergonomia/README.md](modulos/ergonomia/README.md)): evaluación REBA en vivo con
reporte PDF. Corre en un entorno aparte, `modulos/ergonomia/.venv`, porque MediaPipe choca con el OpenCV del
entorno compartido; su README trae la instalación. Sus cambios de contrato están en el mismo
[docs/cambios-contrato.md](docs/cambios-contrato.md).

También está `zona` ([modulos/zona/README.md](modulos/zona/README.md)): detecta personas que se acercan o entran a
una zona marcada en el piso con cinta amarilla. No usa ESP32 ni torre de luz: la alarma, visual y sonora, vive en
la plataforma. El receptor de prueba trae la vista de alarma (`/alarma`) y el editor de zona como referencia, y
[docs/cambios-contrato.md](docs/cambios-contrato.md) dice qué debe implementar la plataforma. Necesita el modelo de
pose, que se baja una vez con `python -m herramientas.descargar_modelos`.

## Cómo arrancar

Requiere Python 3.11 o superior. En Linux cambia `.venv\Scripts\` por `.venv/bin/`.

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env
```

En una terminal, el receptor de prueba:

```
.venv\Scripts\python -m herramientas.receptor_prueba
```

En otra, publica tres eventos de ejemplo y míralos en http://localhost:8000:

```
.venv\Scripts\python -m modulos.comun
```

Pruebas:

```
.venv\Scripts\python -m pytest
```

## Usar el cliente desde un módulo

```python
from modulos.comun import publicar, iniciar_latido, subir_medio, difuminar_rostros

iniciar_latido("ergonomia", "ergonomia")
publicar("ergonomia", "evaluacion_reba", {"puntaje": 9, "nivel": "alto"}, severidad="alta")
```

Detalles en [modulos/comun/README.md](modulos/comun/README.md).
