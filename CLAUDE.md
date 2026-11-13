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

**No crear ni modificar nada dentro de `plataforma/`**: es de Cristian.

## Convenciones obligatorias para todos los módulos

- **Python 3.11+**, código modular, comentarios y docstrings **en español**.
- Cada módulo vive en `modulos/<nombre>/`, corre solo con un comando
  (`python -m modulos.<nombre>`) y tiene su `README.md`.
- Todo módulo publica eventos **únicamente a través de `modulos/comun`**
  (`publicar`, `iniciar_latido`, `subir_medio`). Nunca HTTP directo a la plataforma.
- **Primero un pipeline funcional de punta a punta**; la optimización viene después.
- **Funciona sin internet**, salvo los módulos que llaman IA en la nube (inspector e incidente).
- **Toda imagen guardada o mostrada lleva los rostros difuminados**: pasa por
  `modulos.comun.difuminar_rostros(frame)` antes de escribirla, subirla o enseñarla.
  No se guarda video, solo fotogramas puntuales.
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
