"""C5 / keep the promise: R09 (error body), R06 (cards), R07 (mixable), the spec and the pact.

Sources: app/rules.md, app/openapi/color-v1.json, app/pact/storefront-colorlab.json and the
master data in app/seed/seed.json. No admin calls: the admin helpers are not in the contract.

Strict on purpose:
- types are checked with type(), so 1.0 or True never passes for an integer;
- a JSON body with a repeated key fails;
- every 200 answer carries Content-Type application/json and X-Seed-Version 2026.10.1;
- every check runs twice, to catch answers that change from one call to the next.
Each test gathers all problems and fails once with the full list (no subTest).
"""
import http.client
import json
import os
import re
import unittest
import urllib.parse

URL = urllib.parse.urlsplit(os.environ["COLORLAB_URL"])
SEED_VERSION = "2026.10.1"

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)
with open("app/pact/storefront-colorlab.json", encoding="utf-8") as fh:
    PACT = json.load(fh)

COLORS = {c["code"]: c for c in SEED["Color"]}
ACTIVE = {c for c, d in COLORS.items() if d["active"]}
PRODUCTS = {p["productCode"]: p for p in SEED["Product"]}
SKUS = {s["sku"]: s for s in SEED["Sku"]}
CARDS = {k["cardId"]: k for k in SEED["SkuColorCard"]}
HEX = re.compile(r"^#[0-9A-F]{6}$")
CODE = re.compile(r"^BP[0-9]{4}$")


class Repeated(Exception):
    pass


def no_repeats(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise Repeated("repeated key in %s" % keys)
    return dict(pairs)


def call(method, path):
    """One request. Returns (status, headers, body); body is the raw text if it is not JSON."""
    conn = http.client.HTTPConnection(URL.hostname, URL.port, timeout=10)
    try:
        conn.request(method, path)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        headers = {k.lower(): v for k, v in resp.getheaders()}
    finally:
        conn.close()
    try:
        body = json.loads(raw, object_pairs_hook=no_repeats)
    except Repeated as err:
        body = "BAD JSON: %s" % err
    except ValueError:
        body = "NOT JSON: %r" % raw[:80]
    return resp.status, headers, body


def is_int(v):
    return type(v) is int


def is_str(v):
    return type(v) is str


def answer_problems(path, status, headers, want_status):
    out = []
    if status != want_status:
        out.append((path, "status", status, "want", want_status))
    if not headers.get("content-type", "").startswith("application/json"):
        out.append((path, "content-type", headers.get("content-type")))
    if status == 200 and headers.get("x-seed-version") != SEED_VERSION:
        out.append((path, "X-Seed-Version", headers.get("x-seed-version")))
    return out


def error_problems(path, body, want_code):
    """R09: exactly {"error": {"code": ..., "message": ...}}, nothing more."""
    if not isinstance(body, dict) or list(body) != ["error"]:
        return [(path, "error body shape", body)]
    err = body["error"]
    if not isinstance(err, dict) or sorted(err) != ["code", "message"]:
        return [(path, "error object keys", err)]
    out = []
    if want_code is not None and err["code"] != want_code:
        out.append((path, "error.code", err["code"], "want", want_code))
    if not is_str(err["code"]) or not is_str(err["message"]) or not err["message"].strip():
        out.append((path, "error types or empty message", err))
    return out


def color_problems(where, item, code):
    """A colour as /colors serves it: exact keys, exact types, exact master values."""
    want = {f: COLORS[code][f] for f in ("code", "name", "hex", "family", "formulaCode")}
    out = []
    if not isinstance(item, dict) or sorted(item) != sorted(want):
        return [(where, "colour keys", item)]
    if not all(is_str(v) for v in item.values()):
        out.append((where, "colour field types", item))
    if not CODE.match(item["code"]) or not HEX.match(item["hex"]):
        out.append((where, "code or hex format", item))
    if item != want:
        out.append((where, "colour values", item, "want", want))
    return out


# --- error cases: (path, status, error code); None = any code, the shape must still hold ----
ERRORS = [
    ("/colors/BP9999", 404, "NOT_FOUND"),
    ("/colors/BP0000", 404, "NOT_FOUND"),
    ("/colors/bp9999", 404, "NOT_FOUND"),
    ("/colors/BPX001", 400, "INVALID_CODE"),
    ("/colors/BP100", 400, "INVALID_CODE"),
    ("/colors/BP10001", 400, "INVALID_CODE"),
    ("/colors/1001", 400, "INVALID_CODE"),
    ("/products/SKU-9999/colors", 404, "NOT_FOUND"),
    ("/products/sku-0101/colors", 400, "INVALID_SKU"),
    ("/products/SKU-101/colors", 400, "INVALID_SKU"),
    ("/products/SKU-01010/colors", 400, "INVALID_SKU"),
    ("/cards/CARD-99", 404, "NOT_FOUND"),
    ("/cards/CARD-00", 404, "NOT_FOUND"),
    ("/cards/card-01", 400, "INVALID_CARD"),
    ("/cards/CARD-1", 400, "INVALID_CARD"),
    ("/cards/CARD-001", 400, "INVALID_CARD"),
    ("/colors?page=0", 400, "BAD_PARAMETER"),
    ("/colors?pageSize=51", 400, "BAD_PARAMETER"),
    ("/colors?pageSize=abc", 400, "BAD_PARAMETER"),
    ("/colors?family=Blue", 400, "BAD_PARAMETER"),
    ("/products/SKU-0101/colors?pageSize=0", 400, "BAD_PARAMETER"),
    ("/colour", 404, "NOT_FOUND"),
    ("/colors/BP1001/extra", 404, "NOT_FOUND"),
    ("/cards", 404, "NOT_FOUND"),
    ("/products/SKU-0101", 404, "NOT_FOUND"),
]
ERRORS += [("/colors/" + c, 410, "COLOR_WITHDRAWN") for c in sorted(COLORS) if c not in ACTIVE]
ERRORS += [("/colors/" + c.lower(), 410, "COLOR_WITHDRAWN") for c in sorted(COLORS) if c not in ACTIVE]
ERRORS += [("/products/%s/colors" % s, 409, "NOT_MIXABLE")
           for s, d in sorted(SKUS.items()) if not PRODUCTS[d["productCode"]]["mixable"]]


class R09ErrorBody(unittest.TestCase):
    def test_every_error_has_the_standard_body_and_status(self):
        wrong = []
        for sweep in (1, 2):
            for path, status, code in ERRORS:
                got, headers, body = call("GET", path)
                wrong += answer_problems(path, got, headers, status)
                wrong += error_problems(path, body, code)
        self.assertEqual(wrong, [])

    def test_wrong_method_still_has_the_standard_body(self):
        wrong = []
        for path in ("/colors", "/colors/BP1001", "/cards/CARD-01", "/health"):
            got, _, body = call("DELETE", path)
            if got < 400:
                wrong.append((path, "DELETE accepted", got))
            wrong += error_problems("DELETE " + path, body, None)
        self.assertEqual(wrong, [])


class R06Cards(unittest.TestCase):
    def test_every_card_matches_master_data_and_spec(self):
        wrong = []
        for sweep in (1, 2):
            for card_id, card in sorted(CARDS.items()):
                path = "/cards/" + card_id
                status, headers, body = call("GET", path)
                wrong += answer_problems(path, status, headers, 200)
                if not isinstance(body, dict):
                    wrong.append((path, "body", body))
                    continue
                want_keys = {"cardId", "name", "year", "sku", "colorCount", "colors"}
                if set(body) != want_keys:
                    wrong.append((path, "card keys", sorted(body)))
                head = {"cardId": card_id, "name": card["name"], "year": card["year"], "sku": card["sku"]}
                for key, value in head.items():
                    if body.get(key) != value or type(body.get(key)) is not type(value):
                        wrong.append((path, key, body.get(key), "want", value))
                colors = body.get("colors")
                if not isinstance(colors, list):
                    wrong.append((path, "colors", colors))
                    continue
                if not is_int(body.get("colorCount")) or body.get("colorCount") != len(colors):
                    wrong.append((path, "colorCount", body.get("colorCount"), "listed", len(colors)))
                entries = sorted(card["colors"], key=lambda e: e["position"])
                if len(colors) != len(entries):
                    wrong.append((path, "number of colours", len(colors), "want", len(entries)))
                for got, want in zip(colors, entries):
                    master = COLORS[want["colorCode"]]
                    expect = {"position": want["position"], "code": master["code"],
                              "name": master["name"], "hex": master["hex"]}
                    if got != expect or not is_int(got.get("position")) \
                            or not all(is_str(got.get(k)) for k in ("code", "name", "hex")):
                        wrong.append((path, "entry", got, "want", expect))
                    elif not HEX.match(got["hex"]):
                        wrong.append((path, "hex format", got["hex"]))
        self.assertEqual(wrong, [])


class R07ProductColours(unittest.TestCase):
    def check_product(self, sku, query):
        path = "/products/%s/colors%s" % (sku, query)
        product = PRODUCTS[SKUS[sku]["productCode"]]
        status, headers, body = call("GET", path)
        if not product["mixable"]:
            return answer_problems(path, status, headers, 409) + error_problems(path, body, "NOT_MIXABLE")
        wrong = answer_problems(path, status, headers, 200)
        if not isinstance(body, dict):
            return wrong + [(path, "body", body)]
        want_keys = {"page", "pageSize", "total", "totalPages", "items", "sku", "product"}
        if set(body) != want_keys:
            wrong.append((path, "page keys", sorted(body)))
        codes = sorted({pc["colorCode"] for pc in SEED["ProductColor"]
                        if pc["productCode"] == product["productCode"]} & ACTIVE)
        size = 10
        want = {"page": 1, "pageSize": size, "total": len(codes),
                "totalPages": -(-len(codes) // size), "sku": sku}
        for key, value in want.items():
            if body.get(key) != value or type(body.get(key)) is not type(value):
                wrong.append((path, key, body.get(key), "want", value))
        view = body.get("product")
        want_view = {"code": product["productCode"], "name": product["name"], "mixable": True}
        if not isinstance(view, dict) or view != want_view or view.get("mixable") is not True:
            wrong.append((path, "product", view, "want", want_view))
        items = body.get("items")
        if not isinstance(items, list):
            return wrong + [(path, "items", items)]
        if [i.get("code") if isinstance(i, dict) else i for i in items] != codes[:size]:
            wrong.append((path, "item codes", items, "want", codes[:size]))
        for item in items:
            if isinstance(item, dict) and item.get("code") in COLORS:
                wrong += color_problems(path, item, item["code"])
        return wrong

    def test_every_sku_default_paging(self):
        wrong = []
        for sweep in (1, 2):
            for sku in sorted(SKUS):
                wrong += self.check_product(sku, "")
        self.assertEqual(wrong, [])

    def test_every_sku_with_the_pact_query(self):
        wrong = []
        for sku in sorted(SKUS):
            wrong += self.check_product(sku, "?page=1&pageSize=10")
        self.assertEqual(wrong, [])


class SpecColoursAndHealth(unittest.TestCase):
    def test_every_active_colour_matches_the_spec(self):
        wrong = []
        for sweep in (1, 2):
            for code in sorted(ACTIVE):
                for asked in (code, code.lower()):
                    path = "/colors/" + asked
                    status, headers, body = call("GET", path)
                    wrong += answer_problems(path, status, headers, 200)
                    wrong += color_problems(path, body, code)
        self.assertEqual(wrong, [])

    def test_health(self):
        wrong = []
        for sweep in (1, 2):
            status, headers, body = call("GET", "/health")
            wrong += answer_problems("/health", status, headers, 200)
            if not isinstance(body, dict) or set(body) != {"status", "version", "seedVersion"} \
                    or not all(is_str(v) for v in body.values()) \
                    or body.get("seedVersion") != SEED_VERSION:
                wrong.append(("/health", "body", body))
        self.assertEqual(wrong, [])


class Pact(unittest.TestCase):
    """Replay every Storefront interaction and check each of its rules."""

    def values(self, body, dotted):
        found = [body]
        for part in dotted.split("."):
            many = part.endswith("[*]")
            key = part[:-3] if many else part
            nxt = []
            for node in found:
                if not isinstance(node, dict) or key not in node:
                    return None
                value = node[key]
                if many:
                    if not isinstance(value, list):
                        return None
                    nxt.extend(value)
                else:
                    nxt.append(value)
            found = nxt
        return found

    def rule_ok(self, rule, value):
        if rule["match"] == "regex":
            return is_str(value) and re.match(rule["regex"], value) is not None
        kind = rule["type"]
        if kind == "string":
            return is_str(value)
        if kind == "integer":
            return is_int(value)
        if kind == "array-nonempty":
            return isinstance(value, list) and len(value) > 0
        return False

    def test_every_pact_interaction(self):
        wrong = []
        for sweep in (1, 2):
            for it in PACT["interactions"]:
                req, resp = it["request"], it["response"]
                path = req["path"] + ("?" + req["query"] if req.get("query") else "")
                status, _, body = call(req["method"], path)
                if status != resp["status"]:
                    wrong.append((it["description"], "status", status))
                for rule in resp["rules"]:
                    found = self.values(body, rule["path"])
                    if not found or not all(self.rule_ok(rule, v) for v in found):
                        wrong.append((it["description"], rule["path"], found))
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
