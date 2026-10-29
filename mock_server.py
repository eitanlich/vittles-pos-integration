#!/usr/bin/env python3
"""Vittles POS — mock server (ficticio) para el ejercicio de Software Engineer.

Solo libreria estandar. Python 3.9+.

    python3 mock_server.py        # http://localhost:8422

El comportamiento de este servidor NO coincide del todo con API_DOCS.md. Eso es a proposito.
"""
import json
import random
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 8422
CLIENT_ID = "partner-demo"
CLIENT_SECRET = "s3cr3t-demo"
TOKEN_TTL_SEC = 90          # los docs dicen 1 hora
RATE_LIMIT = 30             # los docs dicen 60
PAGE_SIZE = 2               # paginacion no documentada

RNG = random.Random(1234)

LOCATIONS = [
    {"id": "loc_1001", "name": "Vittles Demo - Midtown", "timezone": "America/New_York", "active": True},
    {"id": "loc_1002", "name": "Vittles Demo - Riverside", "timezone": "America/New_York", "active": True},
    {"id": "loc_1003", "name": "Vittles Demo - Airport", "timezone": "America/Chicago", "active": True},
    {"id": "loc_1004", "name": "Vittles Demo - Warehouse (legacy)", "timezone": "America/Chicago", "active": False},
    {"id": "loc_1005", "name": "Vittles Demo - Beachside", "timezone": "America/Los_Angeles", "active": True},
]

MENUS = {
    "loc_1001": [
        {"id": "itm_88", "name": "Buffalo Wings (12)", "price": 15.5, "available": True, "category": "wings"},
        {"id": "itm_91", "name": "Loaded Fries", "price": "8.25", "available": 1, "category": "sides"},
        {"id": "itm_95", "name": "Nashville Hot Cauliflower", "price": 11.0, "available": 0, "category": "sides"},
    ],
    "loc_1002": [
        {"id": "itm_88", "name": "Buffalo Wings (12)", "price": "15.50", "available": 1, "category": "wings"},
        {"id": "itm_77", "name": "Smoked Wings (24)", "price": 27.9, "available": True, "category": "wings"},
    ],
    "loc_1003": [
        {"id": "itm_88", "name": "Buffalo Wings (12)", "price": 16.25, "available": True, "category": "wings"},
        {"id": "itm_12", "name": "House Salad", "price": "7.00", "available": False, "category": "sides"},
    ],
    "loc_1004": [],
    "loc_1005": [
        {"id": "itm_88", "name": "Buffalo Wings (12)", "price": "15.50", "available": 0, "category": "wings"},
        {"id": "itm_31", "name": "Fish Tacos (3)", "price": 14.0, "available": 1, "category": "tacos"},
    ],
}

TOKENS = {}          # token -> expiry epoch
ORDERS = {}          # order_id -> order
REQUESTS = deque()   # timestamps para el rate limit


def now():
    return time.time()


def rate_limited():
    t = now()
    while REQUESTS and t - REQUESTS[0] > 60:
        REQUESTS.popleft()
    if len(REQUESTS) >= RATE_LIMIT:
        return True
    REQUESTS.append(t)
    return False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "vittles-pos/1.2"

    # ------------------------------------------------------------------ helpers
    def _send(self, code, payload, extra_headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _authed(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._send(401, {"error": "missing token"})
            return False
        token = auth[7:].strip()
        exp = TOKENS.get(token)
        if not exp:
            self._send(401, {"error": "unknown token"})
            return False
        if exp < now():
            # el mensaje no dice "expired": otro detalle no documentado
            self._send(401, {"error": "token no longer valid"})
            return False
        return True

    def log_message(self, fmt, *args):
        print("  %s - %s" % (self.command, self.path))

    # --------------------------------------------------------------------- GET
    def do_GET(self):
        if rate_limited():
            # los docs prometen Retry-After en segundos
            self._send(429, {"error": "slow down"}, {"Retry-After-Ms": "4000"})
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)

        if path == "/v1/locations":
            if not self._authed():
                return
            cursor = int((query.get("cursor") or ["0"])[0])
            page = LOCATIONS[cursor:cursor + PAGE_SIZE]
            payload = {"data": page}
            if cursor + PAGE_SIZE < len(LOCATIONS):
                payload["next_cursor"] = str(cursor + PAGE_SIZE)
            self._send(200, payload)
            return

        if path.startswith("/v1/locations/") and path.endswith("/menu"):
            if not self._authed():
                return
            loc_id = path.split("/")[3]
            loc = next((l for l in LOCATIONS if l["id"] == loc_id), None)
            if loc is None:
                self._send(404, {"error": "no such location"})
                return
            if not loc["active"]:
                self._send(403, {"error": "location is not enabled for partner access"})
                return
            if RNG.random() < 0.12:
                self._send(500, {"error": "internal error", "trace_id": uuid.uuid4().hex[:8]})
                return
            # los docs dicen menu_items
            self._send(200, {"menuItems": MENUS.get(loc_id, [])})
            return

        if path == "/v1/orders":
            if not self._authed():
                return
            # endpoint no documentado: buscar por client_ref
            ref = (query.get("client_ref") or [None])[0]
            found = [o for o in ORDERS.values() if ref and o["_client_ref"] == ref]
            self._send(200, {"data": [self._public_order(o) for o in found]})
            return

        if path.startswith("/v1/orders/"):
            if not self._authed():
                return
            order = ORDERS.get(path.split("/")[3])
            if not order:
                self._send(404, {"error": "no such order"})
                return
            self._send(200, self._public_order(order))
            return

        self._send(404, {"error": "not found"})

    # -------------------------------------------------------------------- POST
    def do_POST(self):
        if rate_limited():
            self._send(429, {"error": "slow down"}, {"Retry-After-Ms": "4000"})
            return

        path = urlparse(self.path).path.rstrip("/")

        if path == "/oauth/token":
            body = self._body()
            if body.get("client_id") != CLIENT_ID or body.get("client_secret") != CLIENT_SECRET:
                self._send(401, {"error": "bad credentials"})
                return
            token = uuid.uuid4().hex
            TOKENS[token] = now() + TOKEN_TTL_SEC
            # los docs dicen expires_in
            self._send(200, {"access_token": token, "token_type": "bearer", "expires": TOKEN_TTL_SEC})
            return

        if path == "/v1/orders":
            if not self._authed():
                return
            body = self._body()
            # header no documentado
            if not self.headers.get("X-Vittles-Location"):
                self._send(200, {"status": "REJECTED", "reason": "missing location context"})
                return
            loc_id = body.get("location_id")
            loc = next((l for l in LOCATIONS if l["id"] == loc_id), None)
            if loc is None:
                self._send(200, {"status": "REJECTED", "reason": "unknown location_id"})
                return
            if self.headers.get("X-Vittles-Location") != loc_id:
                self._send(200, {"status": "REJECTED", "reason": "location context mismatch"})
                return
            items = body.get("items") or []
            if not items:
                self._send(200, {"status": "REJECTED", "reason": "no items"})
                return

            menu = {i["id"]: i for i in MENUS.get(loc_id, [])}
            total = 0.0
            for line in items:
                item = menu.get(line.get("item_id"))
                if item is None:
                    self._send(200, {"status": "REJECTED", "reason": "item not on this menu"})
                    return
                if item["available"] in (False, 0):
                    self._send(200, {"status": "REJECTED", "reason": "item unavailable at this location"})
                    return
                total += float(item["price"]) * int(line.get("quantity") or 1)

            order_id = "ord_%d" % (5500 + len(ORDERS) + 1)
            ORDERS[order_id] = {
                "id": order_id,
                "status": "ACCEPTED",
                "total": round(total, 2),
                "_client_ref": body.get("client_ref"),
                "_created": now(),
            }
            self._send(201, self._public_order(ORDERS[order_id]))
            return

        self._send(404, {"error": "not found"})

    # ------------------------------------------------------------------ format
    def _public_order(self, order):
        # created_at lleva "Z" pero el reloj es hora local del local (no UTC)
        local = time.localtime(order["_created"])
        return {
            "id": order["id"],
            "status": order["status"],
            "total": order["total"],
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", local),
            "updated": int(order["_created"] * 1000),
            "client_ref": order["_client_ref"],
        }


if __name__ == "__main__":
    print("Vittles POS mock escuchando en http://localhost:%d" % PORT)
    print("client_id=%s  client_secret=%s" % (CLIENT_ID, CLIENT_SECRET))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
