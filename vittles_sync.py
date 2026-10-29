#!/usr/bin/env python3
"""Vittles POS integration: auth -> locations -> menus -> idempotent order -> summary.

Standard library only (Python 3.9+). Usage:

    python3 vittles_sync.py --location loc_1001 --item "Buffalo Wings (12)"
    python3 vittles_sync.py --item "Buffalo Wings (12)"          # every active location
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

CLIENT_ID = "partner-demo"
CLIENT_SECRET = "s3cr3t-demo"
MAX_ATTEMPTS = 6          # per request, for 5xx / network errors
MAX_RATE_LIMIT_WAIT = 120  # seconds we accept to wait on 429s for a single request


def log(msg):
    print(msg, file=sys.stderr)


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


class VittlesClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.token = None
        self.token_expires_at = 0.0

    # ---------------------------------------------------------------- auth
    def authenticate(self):
        data = self._raw("POST", "/oauth/token",
                         {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}, auth=False)
        self.token = data["access_token"]
        # Docs say `expires_in` (3600s). Real API sends `expires` (90s). Accept both.
        ttl = data.get("expires_in") or data.get("expires") or 60
        self.token_expires_at = time.time() + float(ttl)
        log(f"auth ok (token valid {ttl}s)")

    def _ensure_token(self):
        # Refresh a bit before expiry so a slow run (rate-limit waits) never sends a dead token.
        if not self.token or time.time() > self.token_expires_at - 10:
            self.authenticate()

    # ---------------------------------------------------------------- http
    def request(self, method, path, body=None, headers=None):
        """Authenticated request with token refresh, 429 handling and 5xx retries."""
        refreshed = False
        attempt = 0
        waited = 0.0
        while True:
            self._ensure_token()
            try:
                return self._raw(method, path, body, headers=headers)
            except ApiError as e:
                if e.status == 401 and not refreshed:
                    log("401 -> refreshing token and retrying once")
                    self.token = None
                    refreshed = True
                    continue
                if e.status == 429:
                    delay = e.retry_after
                    if waited + delay > MAX_RATE_LIMIT_WAIT:
                        raise
                    log(f"429 rate limited -> waiting {delay:.1f}s")
                    time.sleep(delay)
                    waited += delay
                    continue
                if e.status >= 500 and attempt < MAX_ATTEMPTS - 1:
                    attempt += 1
                    delay = min(0.5 * 2 ** attempt, 8)
                    log(f"{e.status} on {method} {path} -> retry {attempt} in {delay}s")
                    time.sleep(delay)
                    continue
                raise

    def _raw(self, method, path, body=None, auth=True, headers=None):
        req = urllib.request.Request(self.base_url + path, method=method)
        req.add_header("Accept", "application/json")
        if auth:
            req.add_header("Authorization", f"Bearer {self.token}")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, data=data, timeout=10) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            err = ApiError(e.code, raw)
            # Docs promise `Retry-After` (seconds). Real API sends `Retry-After-Ms`.
            if e.headers.get("Retry-After-Ms"):
                err.retry_after = int(e.headers["Retry-After-Ms"]) / 1000
            elif e.headers.get("Retry-After"):
                err.retry_after = float(e.headers["Retry-After"])
            else:
                err.retry_after = 5.0
            raise err

    # ------------------------------------------------------------ endpoints
    def list_locations(self):
        # Undocumented cursor pagination: follow `next_cursor` until it disappears.
        locations, cursor = [], None
        while True:
            path = "/v1/locations" + (f"?cursor={cursor}" if cursor else "")
            page = self.request("GET", path)
            locations.extend(page.get("data", []))
            cursor = page.get("next_cursor")
            if not cursor:
                return locations

    def get_menu(self, location_id):
        data = self.request("GET", f"/v1/locations/{location_id}/menu")
        # Docs say `menu_items`; real API says `menuItems`. Accept both.
        items = data.get("menu_items", data.get("menuItems", []))
        return [normalize_item(i) for i in items]

    def find_orders_by_ref(self, client_ref):
        # Undocumented endpoint, but the only way to get real idempotency (see README).
        data = self.request("GET", f"/v1/orders?client_ref={urllib.parse.quote(client_ref)}")
        return data.get("data", [])

    def create_order(self, location_id, client_ref, item_id, quantity):
        body = {
            "location_id": location_id,
            "client_ref": client_ref,
            "items": [{"item_id": item_id, "quantity": quantity}],
        }
        # Undocumented required header: without it every order is REJECTED (with HTTP 200).
        return self.request("POST", "/v1/orders", body, headers={"X-Vittles-Location": location_id})


def normalize_item(raw):
    """Prices come as float or string, `available` as bool or 0/1. Normalize both."""
    available = raw.get("available")
    if isinstance(available, str):
        available = available.strip().lower() in ("true", "1", "yes")
    return {
        "id": raw["id"],
        "name": raw["name"],
        "price": Decimal(str(raw["price"])),
        "available": bool(available),
    }


def same_name(a, b):
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def order_ref(location_id, item_id, quantity):
    # Deterministic: same inputs -> same ref -> a second run finds the order instead of re-creating it.
    return f"vittles-sync:{location_id}:{item_id}:x{quantity}"


def place_order_once(client, location_id, item, quantity):
    """Lookup-before-create. The API does NOT honour client_ref idempotency, so we enforce it."""
    ref = order_ref(location_id, item["id"], quantity)
    existing = client.find_orders_by_ref(ref)
    if existing:
        if len(existing) > 1:
            log(f"warning: {len(existing)} orders already share ref {ref} (duplicates from before)")
        return "ALREADY EXISTED", existing[0]

    resp = client.create_order(location_id, ref, item["id"], quantity)
    # Business errors come back as HTTP 200 + status REJECTED, not 400 as documented.
    if resp.get("status") != "ACCEPTED" or not resp.get("id"):
        return "REJECTED", resp
    return "CREATED", resp


def run(args):
    client = VittlesClient(args.base_url)
    client.authenticate()

    locations = client.list_locations()
    log(f"{len(locations)} locations found")
    if args.location and args.location not in {l["id"] for l in locations}:
        print(f"error: location {args.location} does not exist", file=sys.stderr)
        return 2

    menus, results = {}, []
    for loc in locations:
        if not loc.get("active", True):
            results.append((loc, "SKIPPED", "location inactive", None, None))
            continue
        try:
            menus[loc["id"]] = client.get_menu(loc["id"])
        except ApiError as e:
            results.append((loc, "FAILED", f"menu unavailable ({e.status})", None, None))

    for loc in locations:
        if loc["id"] not in menus:
            continue
        if args.location and loc["id"] != args.location:
            continue
        item = next((i for i in menus[loc["id"]] if same_name(i["name"], args.item)), None)
        if item is None:
            results.append((loc, "SKIPPED", "item not on menu", None, None))
            continue
        if not item["available"]:
            results.append((loc, "SKIPPED", "item unavailable", None, None))
            continue
        try:
            outcome, order = place_order_once(client, loc["id"], item, args.quantity)
        except ApiError as e:
            results.append((loc, "FAILED", f"HTTP {e.status}", None, None))
            continue
        if outcome == "REJECTED":
            results.append((loc, "REJECTED", order.get("reason", "unknown"), None, None))
            continue
        expected = item["price"] * args.quantity
        total = Decimal(str(order["total"]))
        note = "" if total == expected else f" (expected {expected})"
        results.append((loc, outcome, note.strip(), order["id"], total))

    # When a single location was requested, only report that one.
    if args.location:
        results = [r for r in results if r[0]["id"] == args.location]

    position = {l["id"]: n for n, l in enumerate(locations)}
    results.sort(key=lambda r: position[r[0]["id"]])
    print_summary(args, results)
    # SKIPPED is an expected business outcome; only real failures make the run fail.
    failed = [r for r in results if r[1] in ("FAILED", "REJECTED")]
    placed = [r for r in results if r[1] in ("CREATED", "ALREADY EXISTED")]
    return 0 if placed and not failed else 1


def print_summary(args, results):
    print(f"\nSummary: {args.quantity} x \"{args.item}\"")
    print(f"{'LOCATION':<10} {'RESULT':<16} {'ORDER':<10} {'TOTAL':>8}  NOTE")
    for loc, outcome, note, order_id, total in results:
        total_s = f"{total:.2f}" if total is not None else "-"
        print(f"{loc['id']:<10} {outcome:<16} {order_id or '-':<10} {total_s:>8}  {note or ''}")


def main():
    p = argparse.ArgumentParser(description="Create an idempotent order in Vittles POS.")
    p.add_argument("--item", required=True, help='menu item name, e.g. "Buffalo Wings (12)"')
    p.add_argument("--location", help="location id (e.g. loc_1001). Omit to order at every active location.")
    p.add_argument("--quantity", type=int, default=2)
    p.add_argument("--base-url", default="http://localhost:8422")
    args = p.parse_args()
    try:
        sys.exit(run(args))
    except urllib.error.URLError as e:
        print(f"error: cannot reach {args.base_url} ({e.reason}). Is mock_server.py running?", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
