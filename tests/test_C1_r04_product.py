"""C1 / R04 on E05 (GET /products/{sku}/colors), one promise per test.

R04 says a colour carries the same fields and values everywhere it is served.
R08 adds that a product colour list is sorted by code ascending and holds only
active colours. The broad product test fails as one lump; these cut it apart so
the red name says which promise broke: the status, the values, the set of codes,
or the order.
"""
import json
import os
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")
FIELDS = ["code", "name", "hex", "family", "formulaCode"]

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)

MASTER = {c["code"]: {f: c[f] for f in FIELDS} for c in SEED["Color"]}
ACTIVE = {c["code"] for c in SEED["Color"] if c["active"]}
MIXABLE = {p["productCode"] for p in SEED["Product"] if p["mixable"]}
MIX_SKUS = sorted(s["sku"] for s in SEED["Sku"] if s["productCode"] in MIXABLE)
BY_SKU = {s["sku"]: s["productCode"] for s in SEED["Sku"]}


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8") or "{}")


def expected_codes(sku):
    product = BY_SKU[sku]
    return {pc["colorCode"] for pc in SEED["ProductColor"]
            if pc["productCode"] == product} & ACTIVE


def listing(sku):
    return get("/products/%s/colors?pageSize=50" % sku)


class R04ProductColours(unittest.TestCase):
    def test_r08_mixable_sku_answers_200(self):
        wrong = []
        for sku in MIX_SKUS:
            status, body = listing(sku)
            if status != 200:
                wrong.append((sku, status, body))
        self.assertEqual(wrong, [])

    def test_r02_product_list_fits_one_page(self):
        # Guard for the other tests: they send no page parameter.
        wrong = []
        for sku in MIX_SKUS:
            status, body = listing(sku)
            if status == 200 and body.get("totalPages", 0) > 1:
                wrong.append((sku, body.get("total"), body.get("totalPages")))
        self.assertEqual(wrong, [])

    def test_r04_product_item_values_match_master(self):
        wrong = []
        for sku in MIX_SKUS:
            status, body = listing(sku)
            if status != 200:
                continue
            for item in body.get("items", []):
                if not isinstance(item, dict):
                    wrong.append((sku, "not an object", item))
                elif item != MASTER.get(item.get("code")):
                    wrong.append((sku, item, MASTER.get(item.get("code"))))
        self.assertEqual(wrong, [])

    def test_r08_product_codes_are_the_active_ones(self):
        wrong = []
        for sku in MIX_SKUS:
            status, body = listing(sku)
            if status != 200:
                continue
            got = sorted(i.get("code") for i in body.get("items", []) if isinstance(i, dict))
            want = sorted(expected_codes(sku))
            if got != want:
                wrong.append((sku, got, want))
        self.assertEqual(wrong, [])

    def test_r08_product_codes_are_sorted(self):
        wrong = []
        for sku in MIX_SKUS:
            status, body = listing(sku)
            if status != 200:
                continue
            got = [i.get("code") for i in body.get("items", []) if isinstance(i, dict)]
            if got != sorted(got):
                wrong.append((sku, got))
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
