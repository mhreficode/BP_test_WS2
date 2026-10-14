"""C6 extra: every SKU's colour list after a reset (R04, R07, R08), a withdraw of every active colour
then a reset (R05, E02), and the health body after a withdraw (E01). Seed app/seed/seed.json is the truth."""
import json
import os
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")
SEED_VERSION = "2026.10.1"
COLLECTIONS = ("Color", "Product", "Sku", "ProductColor", "SkuColorCard")

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)
COLORS = dict((c["code"], c) for c in SEED["Color"])
ACTIVE = sorted(code for code in COLORS if COLORS[code]["active"])
WITHDRAWN = sorted(code for code in COLORS if not COLORS[code]["active"])
BASELINE = dict((name, len(SEED[name])) for name in COLLECTIONS)
PRODUCTS = dict((p["productCode"], p) for p in SEED["Product"])
SKUS = dict((s["sku"], s) for s in SEED["Sku"])


def served(code):
    doc = COLORS[code]
    return {"code": doc["code"], "name": doc["name"], "hex": doc["hex"],
            "family": doc["family"], "formulaCode": doc["formulaCode"]}


def product_codes(product):
    linked = [pc["colorCode"] for pc in SEED["ProductColor"] if pc["productCode"] == product]
    return sorted(code for code in linked if COLORS[code]["active"])


def call(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), resp.headers
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8")), err.headers


def reset():
    return call("/admin/reset", "POST")


class TestEverySkuAfterReset(unittest.TestCase):

    def setUp(self):
        status, body, _ = reset()
        self.assertEqual(status, 200, body)

    def test_c6_every_sku_matches_the_seed(self):
        self.assertEqual(len(SKUS), 28, "seed sanity")
        for sku in sorted(SKUS):
            product = PRODUCTS[SKUS[sku]["productCode"]]
            path = "/products/%s/colors?pageSize=50" % sku
            status, body, _ = call(path)
            if not product["mixable"]:
                self.assertEqual(status, 409, "%s: %s" % (path, body))
                self.assertEqual(body["error"]["code"], "NOT_MIXABLE", path)
                continue
            codes = product_codes(product["productCode"])
            self.assertEqual(status, 200, "%s: %s" % (path, body))
            self.assertEqual([i["code"] for i in body["items"]], codes, path)
            self.assertEqual(body["total"], len(codes), path)
            self.assertEqual(body["totalPages"], 1 if codes else 0, path)
            for item in body["items"]:
                self.assertEqual(item, served(item["code"]), "%s %s" % (path, item.get("code")))
            self.assertEqual(body["sku"], sku, path)
            self.assertEqual(body["product"], {"code": product["productCode"], "name": product["name"],
                                               "mixable": True}, path)


class TestWithdrawEverythingThenReset(unittest.TestCase):

    def setUp(self):
        reset()

    def tearDown(self):
        reset()

    def test_c6_withdraw_all_then_reset_restores_all(self):
        for code in ACTIVE:
            status, body, _ = call("/admin/colors/%s/withdraw" % code, "POST")
            self.assertEqual(status, 200, "%s: %s" % (code, body))
            self.assertEqual(body, {"code": code, "active": False})
        status, body, _ = call("/colors?pageSize=50")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["total"], 0)
        self.assertEqual(body["totalPages"], 0)
        self.assertEqual(body["items"], [])
        for code in ACTIVE:
            status, body, _ = call("/colors/" + code)
            self.assertEqual(status, 410, "%s: %s" % (code, body))

        status, body, _ = reset()
        self.assertEqual(status, 200, body)
        self.assertEqual(body.get("counts"), BASELINE, body)
        status, body, _ = call("/colors?pageSize=50")
        self.assertEqual(body["total"], 37)
        self.assertEqual([i["code"] for i in body["items"]], ACTIVE)
        for item in body["items"]:
            self.assertEqual(item, served(item["code"]), item["code"])
        for code in ACTIVE:
            status, body, _ = call("/colors/" + code)
            self.assertEqual(status, 200, "%s after reset: %s" % (code, body))
            self.assertEqual(body, served(code), code)
        for code in WITHDRAWN:
            status, body, _ = call("/colors/" + code)
            self.assertEqual(status, 410, "%s after reset: %s" % (code, body))
        for card_id in ("CARD-01", "CARD-02", "CARD-03"):
            status, body, _ = call("/cards/" + card_id)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["colorCount"], len(body["colors"]), card_id)


class TestHealthAfterWithdraw(unittest.TestCase):

    def setUp(self):
        reset()

    def tearDown(self):
        reset()

    def test_c6_health_unchanged_after_withdraw(self):
        status, before, headers_before = call("/health")
        self.assertEqual(status, 200, before)
        status, body, _ = call("/admin/colors/BP1009/withdraw", "POST")
        self.assertEqual(status, 200, body)
        status, after, headers_after = call("/health")
        self.assertEqual(status, 200, after)
        self.assertEqual(after, before)
        self.assertEqual(after, {"status": "ok", "version": "1.0.0", "seedVersion": SEED_VERSION})
        self.assertEqual(headers_after.get("X-Seed-Version"), headers_before.get("X-Seed-Version"))
        self.assertEqual(headers_after.get("X-Seed-Version"), SEED_VERSION)


if __name__ == "__main__":
    unittest.main()
