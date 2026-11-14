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
│   └── ejemplos/              # Un evento válido por tipo (sirven de mocks)
├── modulos/                   # Juan — Python
│   ├── comun/                 # Cliente compartido: publicar, latido, medios, rostros, config remota, cámaras
│   └── epp/                   # Verificación de EPP por perfil en vivo (python -m modulos.epp)
├── herramientas/
│   └── receptor_prueba/       # Imita la API local para probar módulos (no es la plataforma)
├── pruebas/                   # pytest
├── docs/                      # Brief técnico y cambios de contrato
└── plataforma/                # Cristian — Next.js (todavía no existe)
```

Ya está `epp` ([modulos/epp/README.md](modulos/epp/README.md)). Los módulos `ergonomia`, `zona`,
`inspector` e `incidente` se irán agregando en `modulos/<nombre>/`. Lo que cambió en el
contrato para el módulo EPP está en [docs/cambios-contrato.md](docs/cambios-contrato.md). Las convenciones están en [CLAUDE.md](CLAUDE.md).

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
