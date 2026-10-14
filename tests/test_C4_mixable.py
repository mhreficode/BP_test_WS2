"""R07: only mixable products have a colour list. Not mixable gives 409 NOT_MIXABLE.
A mixable product with no colours gives 200 and an empty list. Values come from app/seed/seed.json."""
import json
import os
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)
COLORS = dict((c["code"], c) for c in SEED["Color"])
PRODUCTS = dict((p["productCode"], p) for p in SEED["Product"])
SKUS = dict((s["sku"], s) for s in SEED["Sku"])


def served(code):
    doc = COLORS[code]
    return {"code": doc["code"], "name": doc["name"], "hex": doc["hex"],
            "family": doc["family"], "formulaCode": doc["formulaCode"]}


def product_codes(product):
    linked = [pc["colorCode"] for pc in SEED["ProductColor"] if pc["productCode"] == product]
    return sorted(code for code in linked if COLORS[code]["active"])


def call(path):
    try:
        with urllib.request.urlopen(BASE + path) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


class Base(unittest.TestCase):

    def assert_error(self, path, status, code):
        got, body = call(path)
        self.assertEqual(got, status, "%s should give %s, got %s: %s" % (path, status, got, body))
        self.assertEqual(set(body.keys()), {"error"}, "%s: %s" % (path, body))
        self.assertEqual(set(body["error"].keys()), {"code", "message"}, "%s: %s" % (path, body))
        self.assertEqual(body["error"]["code"], code, "%s: %s" % (path, body))

    def assert_product_list(self, sku, total):
        path = "/products/%s/colors?pageSize=50" % sku
        status, body = call(path)
        self.assertEqual(status, 200, "%s should give 200, got %s: %s" % (path, status, body))
        product = PRODUCTS[SKUS[sku]["productCode"]]
        codes = product_codes(product["productCode"])
        self.assertEqual(len(codes), total, "seed sanity for %s" % sku)
        self.assertEqual([i["code"] for i in body["items"]], codes, "%s: items" % path)
        for item in body["items"]:
            self.assertEqual(item, served(item["code"]), "%s: values of %s" % (path, item.get("code")))
        self.assertEqual(body["total"], total, "%s: total" % path)
        self.assertEqual(body["totalPages"], 1 if total else 0, "%s: totalPages" % path)
        self.assertEqual(body["sku"], sku, "%s: sku" % path)
        self.assertEqual(body["product"], {"code": product["productCode"], "name": product["name"],
                                           "mixable": product["mixable"]}, "%s: product block" % path)
        return body


class TestR07NotMixable(Base):

    NOT_MIXABLE = ["SKU-0301", "SKU-0302", "SKU-0801", "SKU-0802", "SKU-0803", "SKU-1001", "SKU-1002"]

    def test_c4_27_to_33_not_mixable_gives_409(self):
        for sku in self.NOT_MIXABLE:
            self.assertFalse(PRODUCTS[SKUS[sku]["productCode"]]["mixable"], "seed sanity for %s" % sku)
            self.assert_error("/products/%s/colors" % sku, 409, "NOT_MIXABLE")

    def test_c4_34_409_has_the_error_shape(self):
        self.assert_error("/products/SKU-0301/colors", 409, "NOT_MIXABLE")

    def test_c4_35_not_mixable_with_paging_is_still_409(self):
        self.assert_error("/products/SKU-0301/colors?page=2", 409, "NOT_MIXABLE")


class TestR07Mixable(Base):

    def test_c4_36_mixable_without_colours_is_200_empty(self):
        self.assertTrue(PRODUCTS["PRD-12"]["mixable"], "seed sanity")
        self.assertEqual(product_codes("PRD-12"), [], "seed sanity")
        body = self.assert_product_list("SKU-1201", 0)
        self.assertEqual(body["items"], [])

    def test_c4_37_six_colours(self):
        self.assert_product_list("SKU-0701", 6)

    def test_c4_38_eight_colours(self):
        self.assert_product_list("SKU-0401", 8)

    def test_c4_39_ten_colours(self):
        self.assert_product_list("SKU-0501", 10)

    def test_c4_40_twenty_colours(self):
        self.assert_product_list("SKU-0101", 20)

    def test_c4_41_all_skus_of_one_product_give_the_same_list(self):
        lists = []
        for sku in ("SKU-0101", "SKU-0102", "SKU-0103"):
            body = self.assert_product_list(sku, 20)
            lists.append(body["items"])
        self.assertEqual(lists[0], lists[1])
        self.assertEqual(lists[0], lists[2])

    def test_c4_42_unknown_sku_is_404_not_409(self):
        self.assert_error("/products/SKU-9999/colors", 404, "NOT_FOUND")

    def test_c4_43_product_block_empty_product(self):
        status, body = call("/products/SKU-1201/colors")
        self.assertEqual(status, 200, body)
        self.assertIs(body["product"]["mixable"], True)
        self.assertEqual(body["product"]["code"], "PRD-12")

    def test_c4_44_product_block_prd01(self):
        status, body = call("/products/SKU-0101/colors")
        self.assertEqual(status, 200, body)
        self.assertIs(body["product"]["mixable"], True)
        self.assertEqual(body["product"]["code"], "PRD-01")
        self.assertEqual(body["product"]["name"], "Muurverf Extra Mat")


if __name__ == "__main__":
    unittest.main()
