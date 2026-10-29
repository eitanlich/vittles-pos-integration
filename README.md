# Vittles POS — integración

## Cómo correrlo

Python 3.9+, sin dependencias. El repo incluye `mock_server.py` tal cual lo entregaron.

```bash
python3 mock_server.py                                                   # terminal 1
python3 vittles_sync.py --location loc_1001 --item "Buffalo Wings (12)"  # terminal 2
```

Sin `--location` ordena en todas las locations activas. Exit code: `0` ok, `1` sin orden o con fallas, `2` error de entrada.

## Decisiones

- **Idempotencia propia.** La API no respeta `client_ref`: repetirlo crea otra orden. Uso un
  `client_ref` determinístico (location + item + cantidad) y antes de crear busco la orden con
  `GET /v1/orders?client_ref=` (no documentado). La fuente de verdad es el POS, no un archivo local.
- **El éxito lo decide `status == "ACCEPTED"`**, no el HTTP code: los rechazos vuelven con `200`.
- **Tolerante con los formatos.** Acepto los nombres de campo de la doc y los reales, precios como
  texto o número y `available` como bool o 0/1. La plata va en `Decimal` y verifico el total del POS.
- **Reintentos acotados:** 5xx con backoff, 429 según el header, 401 renueva el token una vez.
- **No mando lo que va a fallar:** salteo locations inactivas e items no disponibles, y lo informo.
- **`--location` opcional**, porque el mail pide una location y el README del zip, todas.
- **Python + stdlib**, igual que el mock: cero setup.

Más detalle: [DIFERENCIAS.md](DIFERENCIAS.md) (doc vs. API real) y
[FUERA_DE_ALCANCE.md](FUERA_DE_ALCANCE.md).

## Uso de IA

Usé Claude (Anthropic) como pair programmer para leer la doc y el mock, probar la API con `curl`,
escribir el código y los casos de prueba. Revisé cada decisión y puedo defenderla.
