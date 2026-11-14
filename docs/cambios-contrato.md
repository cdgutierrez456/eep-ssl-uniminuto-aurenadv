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
