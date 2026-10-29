# Diferencias entre la doc y la API real

Todas confirmadas pegándole a la API (curl + el script), no solo leyendo la doc.

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
