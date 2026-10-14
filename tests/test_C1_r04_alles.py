"""C1 / R04: every colour is served exactly as in the master data (app/seed/seed.json).

Checks E03 (GET /colors/{code}) for every case of the prefix, withdrawn and
unknown codes, E04 (GET /colors, all and per family) and
E05 (GET /products/{sku}/colors, values and completeness).
Every sweep runs twice, to catch answers that drift over time.
Each test gathers all mismatches and fails once with the full list
(no subTest: the arena runner does not count failed subtests).
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
WITHDRAWN = {c["code"] for c in SEED["Color"] if not c["active"]}
UNKNOWN = ["BP0000", "BP0001", "BP1000", "BP1041", "BP2001", "BP9999"]


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8") or "{}")


def variants(code):
    digits = code[2:]
    return ["BP" + digits, "bp" + digits, "Bp" + digits, "bP" + digits]


def error_code(body):
    return body.get("error", {}).get("code") if isinstance(body, dict) else None


class R04SingleColour(unittest.TestCase):
    def test_every_active_colour_every_case(self):
        wrong = []
        for sweep in (1, 2):
            for code in sorted(ACTIVE):
                for asked in variants(code):
                    status, body = get("/colors/" + asked)
                    if status != 200 or body != MASTER[code]:
                        wrong.append((sweep, asked, status, body))
        self.assertEqual(wrong, [])

    def test_withdrawn_colour_every_case_is_410(self):
        wrong = []
        for code in sorted(WITHDRAWN):
            for asked in variants(code):
                status, body = get("/colors/" + asked)
                if status != 410 or error_code(body) != "COLOR_WITHDRAWN":
                    wrong.append((asked, status, body))
        self.assertEqual(wrong, [])

    def test_unknown_code_every_case_is_404(self):
        wrong = []
        for code in UNKNOWN:
            for asked in variants(code):
                status, body = get("/colors/" + asked)
                if status != 404 or error_code(body) != "NOT_FOUND":
                    wrong.append((asked, status, body))
        self.assertEqual(wrong, [])

    def test_other_valid_codes_are_404(self):
        # All 10000 codes take ~2 min, too slow for run-tests. Sweep the codes
        # next to the real ones, plus look-alikes (repeated digits, round numbers).
        numbers = set(range(0, 100)) | set(range(1000, 1200)) | set(range(9900, 10000))
        numbers |= {d * 1111 for d in range(10)} | set(range(0, 10000, 500))
        numbers |= {int(c[2:]) + k for c in MASTER for k in (1000, 2000, 8000) if int(c[2:]) + k < 10000}
        wrong = []
        for n in sorted(numbers):
            code = "BP%04d" % n
            if code in MASTER:
                continue
            status, _ = get("/colors/" + code)
            if status != 404:
                wrong.append((code, status))
        self.assertEqual(wrong, [])


class R04Lists(unittest.TestCase):
    def one_page(self, path):
        # Every list fits in one page of 50, so no page parameter is sent:
        # paging (R01/R02) is another topic and must not turn this test red.
        status, body = get(path)
        self.assertEqual(status, 200, path)
        self.assertLessEqual(body["totalPages"], 1, "list no longer fits one page: " + path)
        return body["items"]

    def mismatches(self, items, expected_codes, label):
        wrong = [(label, item) for item in items
                 if not isinstance(item, dict) or item != MASTER.get(item.get("code"))]
        got = sorted(i.get("code") for i in items if isinstance(i, dict))
        if got != sorted(expected_codes):
            wrong.append((label, "codes", got, sorted(expected_codes)))
        return wrong

    def test_colour_list_matches_master(self):
        wrong = []
        for sweep in (1, 2):
            items = self.one_page("/colors?pageSize=50")
            wrong += self.mismatches(items, ACTIVE, "all, sweep %d" % sweep)
        self.assertEqual(wrong, [])

    def test_colour_list_per_family_matches_master(self):
        wrong = []
        for family in sorted({c["family"] for c in SEED["Color"]}):
            expected = [c for c in ACTIVE if MASTER[c]["family"] == family]
            items = self.one_page("/colors?pageSize=50&family=" + family)
            wrong += self.mismatches(items, expected, family)
        self.assertEqual(wrong, [])

    def test_product_colour_lists_match_master(self):
        mixable = {p["productCode"] for p in SEED["Product"] if p["mixable"]}
        wrong = []
        for sku in SEED["Sku"]:
            if sku["productCode"] not in mixable:
                continue
            expected = {pc["colorCode"] for pc in SEED["ProductColor"]
                        if pc["productCode"] == sku["productCode"]} & ACTIVE
            items = self.one_page("/products/%s/colors?pageSize=50" % sku["sku"])
            wrong += self.mismatches(items, expected, sku["sku"])
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
