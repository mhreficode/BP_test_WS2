"""C1 / R04, one promise per test.

R04: a colour is served exactly as in the master data (code, name, hex, family,
formulaCode), the code is found whatever its case, the answer shows the code in
upper case, and the internal fields _id and _sync are never served.

The broad sweep in test_C1_r04_alles.py fails as one lump. These tests cut the
same ground into one assert per promise, so the name of a red test says which
part of R04 is broken. Each test walks every active colour on E03
(GET /colors/{code}) and compares one field only.
"""
import json
import os
import re
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")
FIELDS = ["code", "name", "hex", "family", "formulaCode"]
HEX = re.compile(r"^#[0-9A-F]{6}$")

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


def colour(code):
    status, body = get("/colors/" + code)
    return status, body


class R04OneFieldAtATime(unittest.TestCase):
    """Each test gathers every mismatch and fails once with the full list."""

    def sweep(self, check):
        wrong = []
        for code in ACTIVE:
            status, body = colour(code)
            if status != 200 or not isinstance(body, dict):
                wrong.append((code, "status", status))
                continue
            bad = check(code, body)
            if bad is not None:
                wrong.append((code,) + bad)
        return wrong

    def test_r04_field_name(self):
        def check(code, body):
            if body.get("name") != MASTER[code]["name"]:
                return ("name", body.get("name"), MASTER[code]["name"])
        self.assertEqual(self.sweep(check), [])

    def test_r04_field_hex_value(self):
        def check(code, body):
            if body.get("hex") != MASTER[code]["hex"]:
                return ("hex", body.get("hex"), MASTER[code]["hex"])
        self.assertEqual(self.sweep(check), [])

    def test_r04_field_hex_format(self):
        def check(code, body):
            got = body.get("hex")
            if not isinstance(got, str) or not HEX.match(got):
                return ("hex format", got)
        self.assertEqual(self.sweep(check), [])

    def test_r04_field_family(self):
        def check(code, body):
            if body.get("family") != MASTER[code]["family"]:
                return ("family", body.get("family"), MASTER[code]["family"])
        self.assertEqual(self.sweep(check), [])

    def test_r04_field_formula_code(self):
        def check(code, body):
            if body.get("formulaCode") != MASTER[code]["formulaCode"]:
                return ("formulaCode", body.get("formulaCode"), MASTER[code]["formulaCode"])
        self.assertEqual(self.sweep(check), [])

    def test_r04_field_code_upper_case(self):
        def check(code, body):
            if body.get("code") != code:
                return ("code", body.get("code"), code)
        self.assertEqual(self.sweep(check), [])

    def test_r04_exact_field_set(self):
        def check(code, body):
            if sorted(body.keys()) != sorted(FIELDS):
                return ("fields", sorted(body.keys()))
        self.assertEqual(self.sweep(check), [])

    def test_r04_no_internal_fields(self):
        def check(code, body):
            leaked = [k for k in ("_id", "_sync") if k in body]
            if leaked:
                return ("internal", leaked)
        self.assertEqual(self.sweep(check), [])


class R04CaseAndPlaces(unittest.TestCase):
    def test_r04_lower_case_lookup_gives_same_answer(self):
        wrong = []
        for code in ACTIVE:
            upper_status, upper_body = colour(code)
            lower_status, lower_body = colour(code.lower())
            if (lower_status, lower_body) != (upper_status, upper_body):
                wrong.append((code, lower_status, lower_body, upper_status, upper_body))
        self.assertEqual(wrong, [])

    def test_r04_colour_list_item_matches_single_colour(self):
        # E04 and E03 promise the same colour object. One page of 50 holds them all.
        status, body = get("/colors?pageSize=50")
        self.assertEqual(status, 200)
        wrong = []
        for item in body.get("items", []):
            code = item.get("code")
            single_status, single_body = colour(str(code))
            if single_status != 200 or item != single_body:
                wrong.append((code, item, single_status, single_body))
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
