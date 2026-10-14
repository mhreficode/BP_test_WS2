"""C6 extra scenarios: golden values after reset (R04), lookups and search after reset (R04, R10),
several resets and withdraws (E02, E07, R05, R06), reset body keys, header and HTTP details (E01)."""
import json
import os
import unittest
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")
SEED_VERSION = "2026.10.1"
API_VERSION = "1.0.0"
HEADER = "X-Seed-Version"
COLLECTIONS = ("Color", "Product", "Sku", "ProductColor", "SkuColorCard")

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)
COLORS = dict((c["code"], c) for c in SEED["Color"])
ACTIVE = sorted(code for code in COLORS if COLORS[code]["active"])
WITHDRAWN = sorted(code for code in COLORS if not COLORS[code]["active"])
BASELINE = dict((name, len(SEED[name])) for name in COLLECTIONS)
CARDS = dict((c["cardId"], c) for c in SEED["SkuColorCard"])


def served(code):
    doc = COLORS[code]
    return {"code": doc["code"], "name": doc["name"], "hex": doc["hex"],
            "family": doc["family"], "formulaCode": doc["formulaCode"]}


def expected_card(card_id):
    card = CARDS[card_id]
    entries = sorted(card["colors"], key=lambda e: e["position"])
    colors = [{"position": e["position"], "code": e["colorCode"],
               "name": COLORS[e["colorCode"]]["name"], "hex": COLORS[e["colorCode"]]["hex"]}
              for e in entries]
    return {"cardId": card["cardId"], "name": card["name"], "year": card["year"],
            "sku": card["sku"], "colorCount": len(colors), "colors": colors}


def search(q):
    """R10 expectation from the seed: active only, name contains q ignoring case, code order."""
    return [code for code in ACTIVE if q.lower() in COLORS[code]["name"].lower()]


def call_raw(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as err:
        return err.code, err.read(), err.headers


def call(path, method="GET"):
    status, raw, headers = call_raw(path, method)
    return status, json.loads(raw.decode("utf-8")), headers


def reset():
    return call("/admin/reset", "POST")


class AfterReset(unittest.TestCase):

    def setUp(self):
        status, body, _ = reset()
        self.assertEqual(status, 200, body)

    def tearDown(self):
        reset()


class TestGoldenValuesAfterReset(AfterReset):

    def test_c6_68_family_per_colour(self):
        for code, family in (("BP1008", "black"), ("BP1036", "blue"), ("BP1037", "green"), ("BP1021", "orange")):
            self.assertEqual(COLORS[code]["family"], family, "seed sanity")
            status, body, _ = call("/colors/" + code)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["family"], family, code)

    def test_c6_69_formula_code_per_colour_no_shift(self):
        for code in ACTIVE:
            status, body, _ = call("/colors/" + code)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["formulaCode"], "INN-" + code[-4:], code)
            self.assertEqual(body["formulaCode"], COLORS[code]["formulaCode"], code)

    def test_c6_70_hex_exact_values(self):
        for code, hexval in (("BP1001", "#F4F1E8"), ("BP1017", "#F6C928"),
                             ("BP1024", "#5E1224"), ("BP1032", "#3E2A21")):
            self.assertEqual(COLORS[code]["hex"], hexval, "seed sanity")
            status, body, _ = call("/colors/" + code)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["hex"], hexval, code)

    def test_c6_71_names_exact(self):
        for code, name in (("BP1001", "Wit Gebroken"), ("BP1009", "Delfts Blauw"),
                           ("BP1020", "Oranje Nassau"), ("BP1003", "Crèmewit")):
            self.assertEqual(COLORS[code]["name"], name, "seed sanity")
            status, body, _ = call("/colors/" + code)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["name"], name, code)

    def test_c6_72_status_per_colour_never_404(self):
        for code in ACTIVE:
            status, body, _ = call("/colors/" + code)
            self.assertEqual(status, 200, "%s: %s" % (code, body))
        for code in WITHDRAWN:
            status, body, _ = call("/colors/" + code)
            self.assertEqual(status, 410, "%s: %s" % (code, body))

    def test_c6_81_sku0401_items_exact(self):
        status, body, _ = call("/products/SKU-0401/colors?pageSize=50")
        self.assertEqual(status, 200, body)
        self.assertEqual([i["code"] for i in body["items"]],
                         ["BP1001", "BP1008", "BP1009", "BP1012", "BP1014", "BP1017", "BP1022", "BP1023"])
        for item in body["items"]:
            self.assertEqual(item, served(item["code"]), item["code"])


class TestLookupsAfterReset(AfterReset):

    def test_c6_73_lower_case(self):
        for code in ("bp1001", "bp1037"):
            status, body, _ = call("/colors/" + code)
            self.assertEqual(status, 200, "%s: %s" % (code, body))
            self.assertEqual(body, served(code.upper()), code)

    def test_c6_74_mixed_case(self):
        status, body, _ = call("/colors/Bp1020")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, served("BP1020"))
        self.assertEqual(body["name"], "Oranje Nassau")

    def test_c6_75_withdrawn_lower_case_is_410(self):
        status, body, _ = call("/colors/bp1038")
        self.assertEqual(status, 410, body)
        self.assertEqual(body["error"]["code"], "COLOR_WITHDRAWN")

    def test_c6_76_search_after_reset(self):
        want = {"blauw": 5, "grijs": 5, "crème": 1, "café": 0}
        for q, count in want.items():
            codes = search(q)
            self.assertEqual(len(codes), count, "seed sanity for %s" % q)
            status, body, _ = call("/colors?q=" + urllib.parse.quote(q) + "&pageSize=50")
            self.assertEqual(status, 200, "%s: %s" % (q, body))
            self.assertEqual(body["total"], count, q)
            self.assertEqual([i["code"] for i in body["items"]], codes, q)


class TestResetsAndChanges(AfterReset):

    def withdraw(self, code):
        status, body, _ = call("/admin/colors/%s/withdraw" % code, "POST")
        self.assertEqual(status, 200, "%s: %s" % (code, body))
        self.assertEqual(body, {"code": code.upper(), "active": False})

    def test_c6_86_three_resets_then_all_colours_exact(self):
        for _ in range(3):
            status, body, _ = reset()
            self.assertEqual(status, 200, body)
        for code in ACTIVE:
            status, body, _ = call("/colors/" + code)
            self.assertEqual(status, 200, "%s: %s" % (code, body))
            self.assertEqual(body, served(code), code)

    def test_c6_87_withdraw_reset_withdraw_reset(self):
        self.withdraw("BP1009")
        status, body, _ = reset()
        self.assertEqual(status, 200, body)
        self.withdraw("BP1009")
        status, body, _ = call("/colors/BP1009")
        self.assertEqual(status, 410, body)
        status, body, _ = reset()
        self.assertEqual(status, 200, body)
        status, body, _ = call("/colors/BP1009")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, served("BP1009"))

    def test_c6_88_withdraw_bp1001_then_reset(self):
        self.withdraw("BP1001")
        status, body, _ = reset()
        self.assertEqual(status, 200, body)
        for code in ("BP1001", "BP1009"):
            status, body, _ = call("/colors/" + code)
            self.assertEqual(status, 200, "%s: %s" % (code, body))
            self.assertEqual(body, served(code), code)

    def test_c6_89_withdraw_card_colour_then_reset(self):
        self.withdraw("BP1008")
        status, body, _ = reset()
        self.assertEqual(status, 200, body)
        status, body, _ = call("/cards/CARD-02")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, expected_card("CARD-02"))
        self.assertEqual(body["colors"][-1]["code"], "BP1008")
        self.assertEqual(body["colors"][-1]["hex"], "#0B0B0C")

    def test_c6_90_counts_after_three_withdraws(self):
        for code in ("BP1001", "BP1020", "BP1037"):
            self.withdraw(code)
        status, body, _ = reset()
        self.assertEqual(status, 200, body)
        self.assertEqual(body["counts"], BASELINE)

    def test_c6_91_92_reset_body_keys_exact(self):
        status, body, _ = reset()
        self.assertEqual(status, 200, body)
        self.assertEqual(set(body.keys()), {"status", "seedVersion", "counts"}, body)
        self.assertEqual(set(body["counts"].keys()), set(COLLECTIONS), body)


class TestHeaderAndHttpDetails(AfterReset):

    def test_c6_93_header_exactly_once(self):
        status, body, headers = call("/health")
        self.assertEqual(status, 200, body)
        self.assertEqual(headers.get_all(HEADER), [SEED_VERSION])

    def test_c6_94_95_header_exact_string_not_app_version(self):
        status, body, headers = call("/health")
        value = headers.get(HEADER)
        self.assertEqual(value, SEED_VERSION)
        self.assertEqual(value, value.strip())
        self.assertFalse(value.lower().startswith("v"))
        self.assertNotEqual(value, body["version"])
        self.assertNotEqual(value, API_VERSION)

    def test_c6_96_header_after_withdraw(self):
        status, body, _ = call("/admin/colors/BP1009/withdraw", "POST")
        self.assertEqual(status, 200, body)
        status, body, headers = call("/colors/BP1010")
        self.assertEqual(status, 200, body)
        self.assertEqual(headers.get(HEADER), SEED_VERSION)

    def test_c6_97_98_header_on_409_and_on_wrong_method(self):
        status, body, headers = call("/products/SKU-0301/colors")
        self.assertEqual(status, 409, body)
        self.assertEqual(headers.get(HEADER), SEED_VERSION)
        status, body, headers = call("/admin/reset")
        self.assertIn(status, (404, 405), body)
        self.assertEqual(headers.get(HEADER), SEED_VERSION)

    def test_c6_99_content_type_json_everywhere(self):
        paths = [("GET", "/health"), ("GET", "/colors"), ("GET", "/colors/BP1001"), ("GET", "/colors/BP9999"),
                 ("GET", "/colors/BP1038"), ("GET", "/colors/BP100"), ("GET", "/products/SKU-0101/colors"),
                 ("GET", "/products/SKU-0301/colors"), ("GET", "/cards/CARD-01"), ("POST", "/admin/reset")]
        for method, path in paths:
            status, body, headers = call(path, method)
            ctype = headers.get("Content-Type") or ""
            self.assertTrue(ctype.startswith("application/json"), "%s %s: %s" % (method, path, ctype))

    def test_c6_100_utf8_accent_in_raw_bytes(self):
        status, raw, headers = call_raw("/colors/BP1003")
        self.assertEqual(status, 200, raw)
        self.assertTrue("Cr\xc3\xa8mewit".encode("latin-1") in raw or b"Cr\\u00e8mewit" in raw, raw)
        self.assertEqual(json.loads(raw.decode("utf-8"))["name"], "Crèmewit")


if __name__ == "__main__":
    unittest.main()
