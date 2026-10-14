"""C1 / R04 and R06 on E06 (GET /cards/{cardId}).

R06: a card lists its colours in order of position, colorCount is the number of
colours listed, a card lists the colours stored on it (withdrawing a colour does
not change a card), and each colour shows hex in the same format as /colors:
'#' and 6 capital hex digits.
R04 reaches in here too: the name and hex of a card colour are the master values.

One promise per test, so a red name says which part broke.
"""
import json
import os
import re
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")
HEX = re.compile(r"^#[0-9A-F]{6}$")

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)

MASTER = {c["code"]: c for c in SEED["Color"]}
CARDS = {c["cardId"]: c for c in SEED["SkuColorCard"]}
CARD_IDS = sorted(CARDS)


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8") or "{}")


def card(card_id):
    return get("/cards/" + card_id)


class CardHead(unittest.TestCase):
    def test_every_card_answers_200(self):
        wrong = [(cid, get("/cards/" + cid)[0]) for cid in CARD_IDS
                 if get("/cards/" + cid)[0] != 200]
        self.assertEqual(wrong, [])

    def test_r06_card_head_matches_master(self):
        wrong = []
        for cid in CARD_IDS:
            status, body = card(cid)
            if status != 200:
                continue
            want = CARDS[cid]
            got = {k: body.get(k) for k in ("cardId", "name", "year", "sku")}
            if got != {k: want[k] for k in ("cardId", "name", "year", "sku")}:
                wrong.append((cid, got))
        self.assertEqual(wrong, [])

    def test_r06_colour_count_equals_number_listed(self):
        wrong = []
        for cid in CARD_IDS:
            status, body = card(cid)
            if status != 200:
                continue
            listed = len(body.get("colors", []))
            if body.get("colorCount") != listed:
                wrong.append((cid, body.get("colorCount"), listed))
        self.assertEqual(wrong, [])

    def test_r06_card_keeps_every_stored_colour(self):
        # Withdrawing a colour does not change a card: the stored set is served.
        wrong = []
        for cid in CARD_IDS:
            status, body = card(cid)
            if status != 200:
                continue
            got = sorted(c.get("code") for c in body.get("colors", []))
            want = sorted(c["colorCode"] for c in CARDS[cid]["colors"])
            if got != want:
                wrong.append((cid, got, want))
        self.assertEqual(wrong, [])


class CardColours(unittest.TestCase):
    def test_r06_colours_are_in_position_order(self):
        wrong = []
        for cid in CARD_IDS:
            status, body = card(cid)
            if status != 200:
                continue
            positions = [c.get("position") for c in body.get("colors", [])]
            if positions != sorted(positions):
                wrong.append((cid, positions))
        self.assertEqual(wrong, [])

    def test_r06_position_belongs_to_the_stored_colour(self):
        wrong = []
        for cid in CARD_IDS:
            status, body = card(cid)
            if status != 200:
                continue
            want = {c["colorCode"]: c["position"] for c in CARDS[cid]["colors"]}
            for item in body.get("colors", []):
                if want.get(item.get("code")) != item.get("position"):
                    wrong.append((cid, item.get("code"), item.get("position"),
                                  want.get(item.get("code"))))
        self.assertEqual(wrong, [])

    def test_r06_card_hex_has_the_colors_format(self):
        wrong = []
        for cid in CARD_IDS:
            status, body = card(cid)
            if status != 200:
                continue
            for item in body.get("colors", []):
                value = item.get("hex")
                if not isinstance(value, str) or not HEX.match(value):
                    wrong.append((cid, item.get("code"), value))
        self.assertEqual(wrong, [])

    def test_r04_card_hex_value_matches_master(self):
        wrong = []
        for cid in CARD_IDS:
            status, body = card(cid)
            if status != 200:
                continue
            for item in body.get("colors", []):
                want = MASTER.get(item.get("code"), {}).get("hex")
                if item.get("hex") != want:
                    wrong.append((cid, item.get("code"), item.get("hex"), want))
        self.assertEqual(wrong, [])

    def test_r04_card_name_matches_master(self):
        wrong = []
        for cid in CARD_IDS:
            status, body = card(cid)
            if status != 200:
                continue
            for item in body.get("colors", []):
                want = MASTER.get(item.get("code"), {}).get("name")
                if item.get("name") != want:
                    wrong.append((cid, item.get("code"), item.get("name"), want))
        self.assertEqual(wrong, [])

    def test_r04_card_colour_has_no_internal_fields(self):
        wrong = []
        for cid in CARD_IDS:
            status, body = card(cid)
            if status != 200:
                continue
            for item in body.get("colors", []):
                leaked = [k for k in ("_id", "_sync", "colorCode") if k in item]
                if leaked:
                    wrong.append((cid, item.get("code"), leaked))
        self.assertEqual(wrong, [])


class CardIdChecks(unittest.TestCase):
    def test_r03_bad_card_id_is_400(self):
        wrong = []
        for bad in ("CARD-1", "CARD-001", "card-01", "CARD-AB", "01", "CARD01"):
            status, body = get("/cards/" + bad)
            code = body.get("error", {}).get("code") if isinstance(body, dict) else None
            if status != 400 or code != "INVALID_CARD":
                wrong.append((bad, status, code))
        self.assertEqual(wrong, [])

    def test_r09_unknown_card_is_404(self):
        wrong = []
        for cid in ("CARD-98", "CARD-99", "CARD-00"):
            if cid in CARDS:
                continue
            status, body = get("/cards/" + cid)
            code = body.get("error", {}).get("code") if isinstance(body, dict) else None
            if status != 404 or code != "NOT_FOUND":
                wrong.append((cid, status, code))
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
