# Vittles POS — integración

## Cómo correrlo

Python 3.9+, solo librería estándar (no hay que instalar nada). Con `mock_server.py` corriendo:

```bash
python3 vittles_sync.py --location loc_1001 --item "Buffalo Wings (12)"
```

Sin `--location` crea una orden en cada location activa. `--quantity` es 2 por defecto.
El progreso y los reintentos van a stderr; el resumen va a stdout. Exit code `0` si quedó al menos
una orden (creada o ya existente) y nada falló; `1` si no; `2` si hay error de entrada o no hay server.

## Decisiones

- **Idempotencia propia, no la de la API.** La doc dice que repetir `client_ref` devuelve la orden
  original; en la práctica crea otra (lo probé: mismo `client_ref`, dos órdenes). Por eso el
  `client_ref` es determinístico (`vittles-sync:{location}:{item}:x{qty}`) y antes de crear consulto
  `GET /v1/orders?client_ref=…` (endpoint no documentado). Si existe, la reporto como
  `ALREADY EXISTED`. La fuente de verdad es el POS, no un archivo local.
- **Python + stdlib.** Mismo requisito que el mock: cero setup para quien lo corre.
- **Tolerante con lo que leo, estricto con lo que decido.** Acepto `menu_items` o `menuItems`,
  `expires_in` o `expires`, precios string o número, `available` bool o 0/1. Pero el éxito de una
  orden lo decide `status == "ACCEPTED"`, no el HTTP code (los rechazos vuelven con `200`).
- **Plata en `Decimal`.** Los precios vienen como `"15.50"` o `15.5`. Comparo el total del POS con
  precio × cantidad y lo marco si no coincide.
- **Reintentos acotados:** 5xx con backoff exponencial (el menú falla ~12% de las veces); 429
  esperando lo que dice el header, con un techo de 120s; 401 → renuevo el token una vez.
- **No mando lo que sé que va a fallar:** no pido el menú de locations `active: false` y no intento
  ordenar un item `available: false`. Quedan como `SKIPPED` con el motivo.
- **Ambigüedad del enunciado:** el mail pide la orden en *la location que se pase por parámetro*;
  el README del zip, *una orden por location*. Soporto las dos con `--location` opcional.

## Diferencias entre la doc y la API real

| Doc dice | La API hace | Qué hice |
| --- | --- | --- |
| `client_ref` es idempotente | Crea duplicados | Lookup por `client_ref` antes de crear |
| Errores de orden = `400` | `200` + `{"status":"REJECTED","reason":…}` | Chequeo `status` |
| Body del POST alcanza | Exige header `X-Vittles-Location` = `location_id` | Lo mando |
| Token dura 1h, campo `expires_in` | Dura 90s, campo `expires` | Leo ambos, renuevo antes y ante 401 |
| `GET /v1/locations` devuelve todo | Pagina de a 2 con `next_cursor` | Sigo el cursor |
| `menu_items` | `menuItems` | Acepto ambos |
| `price` decimal, `available` bool | A veces string / 0-1 | Normalizo |
| 60 req/min por token, `Retry-After` en segundos | 30 req/min **compartido entre tokens**, `Retry-After-Ms` | Leo ambos headers |
| Location inexistente → 404 | Location inactiva → `403` (no documentado) | No la consulto; si falla, se reporta |
| `created_at` en UTC | Tiene `Z` pero es la hora local del server | No lo uso; si hiciera falta, usaría `updated` (epoch ms) |

## Uso de IA

Usé Claude (Anthropic) como pair programmer: para leer el mock y la doc, probar los endpoints a
mano con `curl`, escribir el código y los casos de prueba. Las decisiones de arriba las revisé y
las puedo defender una por una.
