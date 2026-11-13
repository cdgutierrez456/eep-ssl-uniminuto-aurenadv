# Receptor de prueba

**Es una herramienta de prueba, no parte de la plataforma final.** Imita la API local
de la plataforma para que los módulos Python se puedan probar sin la plataforma real
(Next.js, carpeta `plataforma/`, que construye Cristian). No tiene sincronización con
el servidor, ni leads, ni tiempo real por SSE, ni autenticación.

## Correr

```
python -m herramientas.receptor_prueba
```

Abre http://localhost:8000 para ver los últimos eventos; la página se actualiza sola
cada 2 s. Cada evento recibido también se imprime en la consola.

Opciones: `--puerto 8000`, `--host 0.0.0.0` (para recibir de otros equipos de la red) y
`--datos <carpeta>` (dónde quedan `receptor.db` y `media/`; por defecto, la carpeta actual).

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/api/eventos` | Recibe un evento o un lote (lista). Valida contra `contrato/evento.schema.json` y guarda en SQLite. Responde 201, o 422 con el detalle del error; si un evento del lote falla, no se guarda ninguno. Un `id` repetido se ignora. |
| GET | `/api/eventos?desde=&estacion=&limite=` | Eventos en orden cronológico. `desde` es una fecha ISO 8601. |
| POST | `/api/medios` | Multipart con el campo `archivo`. Guarda en `media/AAAA-MM-DD/` y devuelve `{"ruta": "media/..."}`. |
| GET | `/api/salud` | Estado, total de eventos y último latido de cada módulo. |
| GET | `/` | Página con los últimos 50 eventos. |

Para empezar de cero, borra `receptor.db` y la carpeta `media/`.
