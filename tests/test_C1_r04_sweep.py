"""C1 / R04 seen from angles the other files miss.

Three angles:
  1. every case of the prefix, per field (BP, bp, Bp, bP),
  2. walking the colour list in small pages: every colour once, values intact,
  3. search answers (q), where the same colour object is served again.

R04 is the rule under test everywhere here: the colour is served exactly as in
the master data, found whatever its case, shown with the code in upper case.
"""
import json
import os
import unittest
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")
FIELDS = ["code", "name", "hex", "family", "formulaCode"]

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)

MASTER = {c["code"]: {f: c[f] for f in FIELDS} for c in SEED["Color"]}
ACTIVE = sorted(c["code"] for c in SEED["Color"] if c["active"])


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8") or "{}")


def variants(code):
    digits = code[2:]
    return ["BP" + digits, "bp" + digits, "Bp" + digits, "bP" + digits]


class EveryCase(unittest.TestCase):
    """R04: the code is found whatever its case, and comes back in upper case."""

    def sweep(self, field):
        wrong = []
        for code in ACTIVE:
            for asked in variants(code):
                status, body = get("/colors/" + asked)
                if status != 200 or not isinstance(body, dict):
                    wrong.append((asked, "status", status))
                elif body.get(field) != MASTER[code][field]:
                    wrong.append((asked, field, body.get(field), MASTER[code][field]))
        return wrong

    def test_code_in_every_case(self):
        self.assertEqual(self.sweep("code"), [])

    def test_name_in_every_case(self):
        self.assertEqual(self.sweep("name"), [])

    def test_hex_in_every_case(self):
        self.assertEqual(self.sweep("hex"), [])

    def test_family_in_every_case(self):
        self.assertEqual(self.sweep("family"), [])

    def test_formula_code_in_every_case(self):
        self.assertEqual(self.sweep("formulaCode"), [])


class PagedWalk(unittest.TestCase):
    """Read the whole colour list in small pages and keep R04 under the lens."""

    def walk(self, size):
        items, page = [], 1
        while True:
            status, body = get("/colors?page=%d&pageSize=%d" % (page, size))
            if status != 200:
                return status, items
            batch = body.get("items", [])
            items += batch
            if page >= body.get("totalPages", 0) or not batch:
                return status, items
            page += 1
            if page > 200:  # guard against a list that never ends
                return status, items

    def test_small_pages_serve_every_active_colour_once(self):
        wrong = []
        for size in (1, 3, 7, 50):
            status, items = self.walk(size)
            codes = [i.get("code") for i in items if isinstance(i, dict)]
            if status != 200:
                wrong.append((size, "status", status))
            elif sorted(codes) != ACTIVE:
                wrong.append((size, sorted(codes), ACTIVE))
        self.assertEqual(wrong, [])

    def test_small_pages_serve_master_values(self):
        wrong = []
        for size in (1, 3, 7):
            _, items = self.walk(size)
            for item in items:
                if item != MASTER.get(item.get("code")):
                    wrong.append((size, item, MASTER.get(item.get("code"))))
        self.assertEqual(wrong, [])


class SearchAnswers(unittest.TestCase):
    """R04 again: a colour found by search is the same object as on E03."""

    def test_search_items_match_master(self):
        wrong = []
        for text in ("wit", "a", "e", "blauw", "grijs"):
            status, body = get("/colors?pageSize=50&q=" + text)
            if status != 200:
                wrong.append((text, "status", status))
                continue
            for item in body.get("items", []):
                if item != MASTER.get(item.get("code")):
                    wrong.append((text, item, MASTER.get(item.get("code"))))
        self.assertEqual(wrong, [])

    def test_search_by_full_name_finds_that_colour(self):
        # R10: the name contains the text, upper and lower case ignored.
        wrong = []
        for code in ACTIVE:
            name = MASTER[code]["name"]
            if len(name) > 64:
                continue
            status, body = get("/colors?pageSize=50&q=" + urllib.parse.quote(name))
            codes = [i.get("code") for i in body.get("items", [])] if status == 200 else []
            if status != 200 or code not in codes:
                wrong.append((code, name, status, codes))
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
