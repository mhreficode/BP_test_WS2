"""Fresh start baseline (R04, R06, E01): the very first answers of the app, before any reset,
must equal the seed app/seed/seed.json and must equal the answers after a reset.
This file sorts first, so it runs before any test that resets the app."""
import json
import os
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")
SEED_VERSION = "2026.10.1"
API_VERSION = "1.0.0"
HEADER = "X-Seed-Version"

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)
with open("app/pact/storefront-colorlab.json", encoding="utf-8") as fh:
    PACT = json.load(fh)
COLORS = dict((c["code"], c) for c in SEED["Color"])
ACTIVE = sorted(code for code in COLORS if COLORS[code]["active"])
WITHDRAWN = sorted(code for code in COLORS if not COLORS[code]["active"])
PRODUCTS = dict((p["productCode"], p) for p in SEED["Product"])
SKUS = dict((s["sku"], s) for s in SEED["Sku"])
CARDS = dict((c["cardId"], c) for c in SEED["SkuColorCard"])


def served(code):
    doc = COLORS[code]
    return {"code": doc["code"], "name": doc["name"], "hex": doc["hex"],
            "family": doc["family"], "formulaCode": doc["formulaCode"]}


def product_codes(product):
    linked = [pc["colorCode"] for pc in SEED["ProductColor"] if pc["productCode"] == product]
    return sorted(code for code in linked if COLORS[code]["active"])


def expected_card(card_id):
    card = CARDS[card_id]
    entries = sorted(card["colors"], key=lambda e: e["position"])
    colors = [{"position": e["position"], "code": e["colorCode"],
               "name": COLORS[e["colorCode"]]["name"], "hex": COLORS[e["colorCode"]]["hex"]}
              for e in entries]
    return {"cardId": card["cardId"], "name": card["name"], "year": card["year"],
            "sku": card["sku"], "colorCount": len(colors), "colors": colors}


def call(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), resp.headers.get(HEADER)
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8")), err.headers.get(HEADER)


def snapshot():
    """Every answer the release gate cares about, as one big dict."""
    out = {"health": call("/health")}
    for code in sorted(COLORS):
        out["color " + code] = call("/colors/" + code)
    out["list"] = call("/colors?pageSize=50")
    for sku in sorted(SKUS):
        out["sku " + sku] = call("/products/%s/colors?pageSize=50" % sku)
    for card_id in sorted(CARDS):
        out["card " + card_id] = call("/cards/" + card_id)
    for interaction in PACT["interactions"]:
        req = interaction["request"]
        target = req["path"] + ("?" + req["query"] if req.get("query") else "")
        out["pact " + interaction["description"]] = call(target, req["method"])
    return out


class TestFreshStart(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.fresh = snapshot()

    def test_r04_fresh_health_and_header(self):
        status, body, header = self.fresh["health"]
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"status": "ok", "version": API_VERSION, "seedVersion": SEED_VERSION})
        self.assertEqual(header, SEED_VERSION)

    def test_r04_fresh_header_on_every_answer(self):
        for key, (status, body, header) in self.fresh.items():
            self.assertEqual(header, SEED_VERSION, "%s: header %s" % (key, HEADER))

    def test_r04_fresh_every_colour_equals_the_seed(self):
        for code in ACTIVE:
            status, body, _ = self.fresh["color " + code]
            self.assertEqual(status, 200, "%s: %s" % (code, body))
            self.assertEqual(body, served(code), code)
        for code in WITHDRAWN:
            status, body, _ = self.fresh["color " + code]
            self.assertEqual(status, 410, "%s: %s" % (code, body))
            self.assertEqual(body["error"]["code"], "COLOR_WITHDRAWN", code)

    def test_r04_fresh_list_equals_the_seed(self):
        status, body, _ = self.fresh["list"]
        self.assertEqual(status, 200, body)
        self.assertEqual(body["total"], 37)
        self.assertEqual(body["items"], [served(code) for code in ACTIVE])

    def test_r04_fresh_every_sku_equals_the_seed(self):
        for sku in sorted(SKUS):
            product = PRODUCTS[SKUS[sku]["productCode"]]
            status, body, _ = self.fresh["sku " + sku]
            if not product["mixable"]:
                self.assertEqual(status, 409, "%s: %s" % (sku, body))
                continue
            self.assertEqual(status, 200, "%s: %s" % (sku, body))
            self.assertEqual(body["items"], [served(c) for c in product_codes(product["productCode"])], sku)
            self.assertEqual(body["product"], {"code": product["productCode"], "name": product["name"],
                                               "mixable": True}, sku)

    def test_r06_fresh_every_card_equals_the_seed(self):
        for card_id in sorted(CARDS):
            status, body, _ = self.fresh["card " + card_id]
            self.assertEqual(status, 200, "%s: %s" % (card_id, body))
            self.assertEqual(body, expected_card(card_id), card_id)

    def test_r04_fresh_pact_statuses(self):
        for interaction in PACT["interactions"]:
            status, body, _ = self.fresh["pact " + interaction["description"]]
            self.assertEqual(status, interaction["response"]["status"], "%s: %s" % (interaction["description"], body))

    def test_r04_fresh_equals_after_reset(self):
        status, body, header = call("/admin/reset", "POST")
        self.assertEqual(status, 200, body)
        after = snapshot()
        for key in self.fresh:
            self.assertEqual(self.fresh[key], after[key], "fresh start differs from after reset: %s" % key)


if __name__ == "__main__":
    unittest.main()
