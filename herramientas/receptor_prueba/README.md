# Receptor de prueba

**Es una herramienta de prueba, no parte de la plataforma final.** Imita la API local
de la plataforma para que los módulos Python se puedan probar sin la plataforma real
(Next.js, carpeta `plataforma/`, que construye Cristian). No tiene sincronización con
el servidor, ni leads, ni autenticación.

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
| GET | `/api/salud` | Estado, total de eventos, último latido de cada módulo y la hora del servidor (`ahora`). |
| GET | `/api/stream` | Empuje en tiempo real por Server-Sent Events: cada evento nuevo sale como un mensaje con su `id` y el sobre completo en `data`. Al conectar y cada 5 s sale un mensaje `reloj` con la hora del servidor. |
| PUT, GET | `/api/modulos/{modulo}/capacidades` y `/config` | Configuración remota de los módulos (ver `docs/cambios-contrato.md`). |
| GET | `/` | Página con los últimos 50 eventos, la configuración de los módulos y el editor de la zona de peligro. |
| GET | `/alarma` | Vista de alarma de la zona de peligro, a pantalla completa, con sonido. |

Para empezar de cero, borra `receptor.db` y la carpeta `media/`.

## Vista de alarma (`/alarma`)

Pensada para una pantalla del stand. Muestra el estado de la zona de peligro en grande y pita
cuando hay alguien cerca o dentro:

- **Zona despejada**: fondo Auren Deep, sin sonido.
- **Precaución**: borde amarillo que pulsa y un pitido lento.
- **Persona en zona de peligro**: fondo y borde rojos que pulsan y un pitido rápido.

Abajo lleva los ingresos y los casi-accidentes del día y el último evento. Al abrirla hay que
pulsar **Activar sonido**: los navegadores no dejan sonar nada hasta que alguien hace clic. El
volumen se recuerda; el silencio no, para que nunca abra callada.

Dos reglas la protegen de mostrar algo falso: ignora los `estado_zona` con más de 5 s de
antigüedad (salieron tarde de la cola de la estación) y, si pasan 5 s sin recibir ninguno
mientras hay alarma, la apaga sola y avisa que no hay señal de la estación.

## Editor de la zona de peligro (en `/`)

Aparece cuando la estación de zona ya subió su configuración. Muestra la imagen de referencia
de la cámara con el polígono de la zona encima:

- **Detectar zona** le pide a la estación que busque la cinta; la respuesta llega en unos
  segundos como una propuesta punteada, con su mensaje.
- Clic en la imagen agrega un vértice, arrastrar lo mueve y clic derecho lo quita.
- **Ancho real** y **Largo real** son las medidas del rectángulo de cinta, en metros.
- **Guardar zona** la deja activa. **Descartar cambios** vuelve a la zona guardada.
