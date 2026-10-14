"""C5 / R09, R06, R07: the promise the spec makes to every caller.

R09: every error has the same body {"error":{"code":..., "message":...}}.
     A well-formed id that does not exist gives 404 NOT_FOUND. An unknown path
     gives 404 NOT_FOUND.
R06: the card answer carries cardId, name, year, sku, colorCount.
R07: a SKU of a product that is not mixable gives 409 NOT_MIXABLE.

Field names and types come from app/openapi/color-v1.json; the values come from
app/seed/seed.json.
"""
import http.client
import json
import os
import unittest
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")
HOST = urllib.parse.urlsplit(BASE)

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)

CARDS = {c["cardId"]: c for c in SEED["SkuColorCard"]}
CARD_IDS = sorted(CARDS)
PRODUCTS = {p["productCode"]: p for p in SEED["Product"]}
MIX_SKUS = sorted(s["sku"] for s in SEED["Sku"] if PRODUCTS[s["productCode"]]["mixable"])
FLAT_SKUS = sorted(s["sku"] for s in SEED["Sku"] if not PRODUCTS[s["productCode"]]["mixable"])
BY_SKU = {s["sku"]: s["productCode"] for s in SEED["Sku"]}
WITHDRAWN = sorted(c["code"] for c in SEED["Color"] if not c["active"])


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8")
        return err.code, json.loads(body) if body else {}


def request(method, path):
    """Any method, so the wrong-method answer can be checked too."""
    conn = http.client.HTTPConnection(HOST.hostname, HOST.port, timeout=15)
    try:
        conn.request(method, path)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        return resp.status, json.loads(raw) if raw else {}
    finally:
        conn.close()


def error_of(body):
    if not isinstance(body, dict):
        return None
    return body.get("error")


class ErrorBody(unittest.TestCase):
    """R09: one body shape for every failure."""

    def shape_problems(self, label, status, body, want_status, want_code):
        problems = []
        if status != want_status:
            problems.append((label, "status", status, want_status))
        err = error_of(body)
        if not isinstance(err, dict):
            problems.append((label, "no error object", body))
            return problems
        if sorted(err.keys()) != ["code", "message"]:
            problems.append((label, "fields", sorted(err.keys())))
        if err.get("code") != want_code:
            problems.append((label, "code", err.get("code"), want_code))
        if not isinstance(err.get("message"), str) or not err.get("message"):
            problems.append((label, "message", err.get("message")))
        if sorted(body.keys()) != ["error"]:
            problems.append((label, "top level fields", sorted(body.keys())))
        return problems

    def test_r09_404_for_a_colour_that_does_not_exist(self):
        bad = []
        for code in ("BP9999", "BP0000", "BP5555"):
            status, body = get("/colors/" + code)
            bad += self.shape_problems(code, status, body, 404, "NOT_FOUND")
        self.assertEqual(bad, [])

    def test_r09_404_for_an_unknown_path(self):
        bad = []
        for path in ("/nope", "/colors/BP1001/extra", "/cards", "/products/SKU-0101"):
            status, body = get(path)
            bad += self.shape_problems(path, status, body, 404, "NOT_FOUND")
        self.assertEqual(bad, [])

    def test_r09_400_keeps_the_same_body(self):
        bad = []
        for path, code in (("/colors/BP10", "INVALID_CODE"),
                           ("/colors/XX1001", "INVALID_CODE"),
                           ("/cards/CARD-1", "INVALID_CARD"),
                           ("/products/SKU-01/colors", "INVALID_SKU"),
                           ("/colors?pageSize=51", "BAD_PARAMETER"),
                           ("/colors?page=0", "BAD_PARAMETER"),
                           ("/colors?family=WHITE", "BAD_PARAMETER")):
            status, body = get(path)
            bad += self.shape_problems(path, status, body, 400, code)
        self.assertEqual(bad, [])

    def test_r05_410_keeps_the_same_body(self):
        bad = []
        for code in WITHDRAWN:
            status, body = get("/colors/" + code)
            bad += self.shape_problems(code, status, body, 410, "COLOR_WITHDRAWN")
        self.assertEqual(bad, [])

    def test_r07_409_keeps_the_same_body(self):
        bad = []
        for sku in FLAT_SKUS:
            status, body = get("/products/%s/colors" % sku)
            bad += self.shape_problems(sku, status, body, 409, "NOT_MIXABLE")
        self.assertEqual(bad, [])

    def test_r09_404_for_a_sku_or_card_that_does_not_exist(self):
        bad = []
        status, body = get("/products/SKU-9999/colors")
        bad += self.shape_problems("SKU-9999", status, body, 404, "NOT_FOUND")
        status, body = get("/cards/CARD-99")
        bad += self.shape_problems("CARD-99", status, body, 404, "NOT_FOUND")
        self.assertEqual(bad, [])

    def test_wrong_method_is_405_with_the_same_body(self):
        bad = []
        for method, path in (("POST", "/colors"), ("PUT", "/colors/BP1001"),
                             ("DELETE", "/cards/CARD-01")):
            status, body = request(method, path)
            bad += self.shape_problems("%s %s" % (method, path), status, body,
                                       405, "METHOD_NOT_ALLOWED")
        self.assertEqual(bad, [])


class CardAnswer(unittest.TestCase):
    """R06: the head of the card answer, field by field."""

    def heads(self):
        for cid in CARD_IDS:
            status, body = get("/cards/" + cid)
            yield cid, status, body

    def test_r06_card_head_has_exactly_the_promised_fields(self):
        want = ["cardId", "colorCount", "colors", "name", "sku", "year"]
        wrong = [(cid, sorted(body.keys())) for cid, status, body in self.heads()
                 if status != 200 or sorted(body.keys()) != want]
        self.assertEqual(wrong, [])

    def test_r06_card_id_matches_the_one_asked(self):
        wrong = [(cid, body.get("cardId")) for cid, status, body in self.heads()
                 if status != 200 or body.get("cardId") != cid]
        self.assertEqual(wrong, [])

    def test_r06_card_name_matches_the_seed(self):
        wrong = [(cid, body.get("name"), CARDS[cid]["name"])
                 for cid, status, body in self.heads()
                 if status != 200 or body.get("name") != CARDS[cid]["name"]]
        self.assertEqual(wrong, [])

    def test_r06_card_year_matches_the_seed_and_is_a_number(self):
        wrong = []
        for cid, status, body in self.heads():
            year = body.get("year")
            if status != 200 or year != CARDS[cid]["year"] or not isinstance(year, int):
                wrong.append((cid, year, CARDS[cid]["year"]))
        self.assertEqual(wrong, [])

    def test_r06_card_sku_matches_the_seed(self):
        wrong = [(cid, body.get("sku"), CARDS[cid]["sku"])
                 for cid, status, body in self.heads()
                 if status != 200 or body.get("sku") != CARDS[cid]["sku"]]
        self.assertEqual(wrong, [])

    def test_r06_colour_count_is_a_number_and_matches_the_list(self):
        wrong = []
        for cid, status, body in self.heads():
            count = body.get("colorCount")
            listed = len(body.get("colors", []))
            if status != 200 or not isinstance(count, int) or count != listed:
                wrong.append((cid, count, listed))
        self.assertEqual(wrong, [])


class ProductAnswer(unittest.TestCase):
    """R07 and the spec: the product block of a product colour list."""

    def test_product_block_has_code_name_and_mixable(self):
        wrong = []
        for sku in MIX_SKUS:
            status, body = get("/products/%s/colors" % sku)
            if status != 200:
                wrong.append((sku, "status", status))
                continue
            product = body.get("product")
            if not isinstance(product, dict) or sorted(product.keys()) != ["code", "mixable", "name"]:
                wrong.append((sku, product))
        self.assertEqual(wrong, [])

    def test_product_block_matches_the_seed(self):
        wrong = []
        for sku in MIX_SKUS:
            status, body = get("/products/%s/colors" % sku)
            if status != 200:
                continue
            want = PRODUCTS[BY_SKU[sku]]
            got = body.get("product", {})
            if (got.get("code"), got.get("name"), got.get("mixable")) != \
                    (want["productCode"], want["name"], want["mixable"]):
                wrong.append((sku, got, want["productCode"], want["name"], want["mixable"]))
        self.assertEqual(wrong, [])

    def test_sku_is_echoed_in_the_answer(self):
        wrong = []
        for sku in MIX_SKUS:
            status, body = get("/products/%s/colors" % sku)
            if status != 200 or body.get("sku") != sku:
                wrong.append((sku, status, body.get("sku")))
        self.assertEqual(wrong, [])

    def test_mixable_is_a_real_boolean(self):
        wrong = []
        for sku in MIX_SKUS:
            status, body = get("/products/%s/colors" % sku)
            value = body.get("product", {}).get("mixable") if status == 200 else None
            if not isinstance(value, bool):
                wrong.append((sku, value, type(value).__name__))
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
