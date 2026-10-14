"""E02 reset and the data baseline after it (R04, R05, R07, R08).
The seed app/seed/seed.json is the truth: every colour must match it exactly after a reset,
withdrawn colours stay withdrawn, and a reset undoes every withdraw."""
import json
import os
import re
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
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def reset():
    return call("/admin/reset", "POST")


class TestResetAnswer(unittest.TestCase):

    def test_c6_16_to_20_reset_body(self):
        self.assertEqual(BASELINE, {"Color": 40, "Product": 12, "Sku": 28, "ProductColor": 78, "SkuColorCard": 3},
                         "seed sanity")
        status, body = reset()
        self.assertEqual(status, 200, body)
        self.assertEqual(body.get("status"), "reset", body)
        self.assertEqual(body.get("seedVersion"), SEED_VERSION, body)
        self.assertEqual(body.get("counts"), BASELINE, body)
        for name, value in body["counts"].items():
            self.assertIsInstance(value, int, name)
            self.assertNotIsInstance(value, bool, name)

    def test_c6_21_two_resets_give_the_same_answer(self):
        first = reset()
        second = reset()
        self.assertEqual(first, second)

    def test_c6_22_get_on_reset_is_refused_with_the_error_body(self):
        status, body = call("/admin/reset")
        self.assertIn(status, (404, 405), body)
        self.assertEqual(set(body.keys()), {"error"}, body)
        self.assertEqual(set(body["error"].keys()), {"code", "message"}, body)


class TestBaselineAfterReset(unittest.TestCase):

    def setUp(self):
        status, body = reset()
        self.assertEqual(status, 200, body)

    def test_c6_23_total_active_is_37(self):
        status, body = call("/colors?pageSize=50")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["total"], 37)
        self.assertEqual([i["code"] for i in body["items"]], ACTIVE)

    def test_c6_24_26_31_32_34_35_every_active_colour_matches_the_seed(self):
        self.assertEqual(len(ACTIVE), 37, "seed sanity")
        for code in ACTIVE:
            status, body = call("/colors/" + code)
            self.assertEqual(status, 200, "%s: %s" % (code, body))
            self.assertEqual(body, served(code), code)
            self.assertEqual(set(body.keys()), {"code", "name", "hex", "family", "formulaCode"}, code)
            for hidden in ("_id", "_sync", "active"):
                self.assertNotIn(hidden, body, code)
            self.assertEqual(body["formulaCode"], "INN-" + code[-4:], code)
            self.assertRegex(body["hex"], r"^#[0-9A-F]{6}$", code)

    def test_c6_25_withdrawn_stay_withdrawn(self):
        self.assertEqual(WITHDRAWN, ["BP1038", "BP1039", "BP1040"], "seed sanity")
        for code in WITHDRAWN:
            status, body = call("/colors/" + code)
            self.assertEqual(status, 410, "%s: %s" % (code, body))
            self.assertEqual(body["error"]["code"], "COLOR_WITHDRAWN", code)

    def test_c6_26_first_colour_exact(self):
        status, body = call("/colors/BP1001")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"code": "BP1001", "name": "Wit Gebroken", "hex": "#F4F1E8",
                                "family": "white", "formulaCode": "INN-1001"})
        self.assertEqual(body, served("BP1001"))

    def test_c6_27_28_hex_with_leading_zero(self):
        for code, hexval in (("BP1008", "#0B0B0C"), ("BP1036", "#0F5C6E")):
            self.assertEqual(COLORS[code]["hex"], hexval, "seed sanity")
            status, body = call("/colors/" + code)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["hex"], hexval, code)

    def test_c6_29_30_names_with_accent_and_space(self):
        for code, name in (("BP1003", "Crèmewit"), ("BP1020", "Oranje Nassau")):
            self.assertEqual(COLORS[code]["name"], name, "seed sanity")
            status, body = call("/colors/" + code)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["name"], name, code)

    def test_c6_31_last_active_colour_exact(self):
        status, body = call("/colors/BP1037")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"code": "BP1037", "name": "Munt", "hex": "#B8E0D2",
                                "family": "green", "formulaCode": "INN-1037"})

    def test_c6_33_family_counts(self):
        want = {}
        for code in ACTIVE:
            fam = COLORS[code]["family"]
            want[fam] = want.get(fam, 0) + 1
        self.assertEqual(want, {"white": 4, "grey": 6, "black": 1, "blue": 5, "green": 5, "yellow": 3,
                                "orange": 2, "red": 3, "pink": 2, "purple": 2, "brown": 4}, "seed sanity")
        self.assertEqual(sum(want.values()), 37)
        for fam, count in want.items():
            status, body = call("/colors?family=%s&pageSize=50" % fam)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["total"], count, fam)
            self.assertEqual([i["code"] for i in body["items"]],
                             [c for c in ACTIVE if COLORS[c]["family"] == fam], fam)

    def test_c6_36_to_39_products_after_reset(self):
        for sku, total in (("SKU-0101", 20), ("SKU-0201", 11), ("SKU-1201", 0)):
            codes = product_codes(SKUS[sku]["productCode"])
            self.assertEqual(len(codes), total, "seed sanity for %s" % sku)
            status, body = call("/products/%s/colors?pageSize=50" % sku)
            self.assertEqual(status, 200, "%s: %s" % (sku, body))
            self.assertEqual(body["total"], total, sku)
            self.assertEqual([i["code"] for i in body["items"]], codes, sku)
        status, body = call("/products/SKU-0301/colors")
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "NOT_MIXABLE")

    def test_c6_40_product_items_equal_colors_and_seed(self):
        status, body = call("/products/SKU-0101/colors?pageSize=50")
        self.assertEqual(status, 200, body)
        self.assertEqual(len(body["items"]), 20)
        for item in body["items"]:
            status, single = call("/colors/" + item["code"])
            self.assertEqual(status, 200, single)
            self.assertEqual(item, single, item["code"])
            self.assertEqual(item, served(item["code"]), item["code"])


class TestResetRestoresChanges(unittest.TestCase):

    def setUp(self):
        reset()

    def tearDown(self):
        reset()

    def withdraw(self, code):
        status, body = call("/admin/colors/%s/withdraw" % code, "POST")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"code": code, "active": False})
        status, body = call("/colors/" + code)
        self.assertEqual(status, 410, "%s after withdraw: %s" % (code, body))

    def test_c6_24_snapshot_before_and_after_reset(self):
        before = dict((code, call("/colors/" + code)) for code in ACTIVE)
        status, body = reset()
        self.assertEqual(status, 200, body)
        after = dict((code, call("/colors/" + code)) for code in ACTIVE)
        self.assertEqual(before, after)
        for code in ACTIVE:
            self.assertEqual(after[code], (200, served(code)), code)

    def test_c6_49_to_52_withdraw_then_reset(self):
        self.withdraw("BP1009")
        status, body = reset()
        self.assertEqual(status, 200, body)
        self.assertEqual(body.get("counts"), BASELINE, body)
        status, body = call("/colors/BP1009")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, served("BP1009"))
        status, body = call("/colors?pageSize=50")
        self.assertEqual(body["total"], 37)
        self.assertEqual([i["code"] for i in body["items"]], ACTIVE)
        status, body = call("/products/SKU-0101/colors?pageSize=50")
        self.assertEqual(body["total"], 20)
        self.assertIn("BP1009", [i["code"] for i in body["items"]])

    def test_c6_53_several_withdraws_then_reset(self):
        for code in ("BP1001", "BP1020", "BP1037"):
            self.withdraw(code)
        status, body = call("/colors?pageSize=50")
        self.assertEqual(body["total"], 34)
        status, body = reset()
        self.assertEqual(status, 200, body)
        for code in ("BP1001", "BP1020", "BP1037"):
            status, body = call("/colors/" + code)
            self.assertEqual(status, 200, "%s after reset: %s" % (code, body))
            self.assertEqual(body, served(code), code)
        status, body = call("/colors?pageSize=50")
        self.assertEqual(body["total"], 37)

    def test_c6_54_reset_does_not_activate_withdrawn_colours(self):
        self.withdraw("BP1009")
        status, body = reset()
        self.assertEqual(status, 200, body)
        for code in WITHDRAWN:
            status, body = call("/colors/" + code)
            self.assertEqual(status, 410, "%s after reset: %s" % (code, body))
        status, body = call("/colors?pageSize=50")
        self.assertEqual(body["total"], 37)


if __name__ == "__main__":
    unittest.main()
