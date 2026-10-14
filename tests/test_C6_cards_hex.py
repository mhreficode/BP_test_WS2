"""R06: a card shows hex in the same format as /colors: # and 6 capital hex digits, equal to the colour.
Cards are identical before and after a reset. The seed app/seed/seed.json is the truth."""
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
COLORS = dict((c["code"], c) for c in SEED["Color"])
CARDS = dict((c["cardId"], c) for c in SEED["SkuColorCard"])


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
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


class TestCardHex(unittest.TestCase):

    def get_card(self, card_id):
        status, body = call("/cards/" + card_id)
        self.assertEqual(status, 200, "%s: %s" % (card_id, body))
        return body

    def test_c6_41_to_43_hex_format_on_every_card(self):
        self.assertEqual(sorted(CARDS), ["CARD-01", "CARD-02", "CARD-03"], "seed sanity")
        for card_id in sorted(CARDS):
            body = self.get_card(card_id)
            self.assertTrue(body["colors"], "%s: no colours" % card_id)
            for colour in body["colors"]:
                self.assertIsInstance(colour["hex"], str, "%s %s" % (card_id, colour))
                self.assertRegex(colour["hex"], HEX, "%s %s" % (card_id, colour))

    def test_c6_44_card_hex_equals_colors_and_seed(self):
        for card_id in sorted(CARDS):
            body = self.get_card(card_id)
            for colour in body["colors"]:
                status, single = call("/colors/" + colour["code"])
                self.assertEqual(status, 200, single)
                self.assertEqual(colour["hex"], single["hex"], "%s %s" % (card_id, colour["code"]))
                self.assertEqual(colour["hex"], COLORS[colour["code"]]["hex"], "%s %s" % (card_id, colour["code"]))
                self.assertEqual(colour["name"], COLORS[colour["code"]]["name"], "%s %s" % (card_id, colour["code"]))

    def test_c6_45_leading_zero_on_card02(self):
        body = self.get_card("CARD-02")
        entry = [c for c in body["colors"] if c["code"] == "BP1008"][0]
        self.assertEqual(entry["hex"], "#0B0B0C")

    def test_c6_46_capitals_on_card01(self):
        body = self.get_card("CARD-01")
        entry = [c for c in body["colors"] if c["code"] == "BP1010"][0]
        self.assertEqual(entry["hex"], "#8EC5E8")

    def test_c6_47_48_cards_identical_after_reset(self):
        before = dict((card_id, self.get_card(card_id)) for card_id in sorted(CARDS))
        status, body = call("/admin/reset", "POST")
        self.assertEqual(status, 200, body)
        after = dict((card_id, self.get_card(card_id)) for card_id in sorted(CARDS))
        self.assertEqual(before, after)
        for card_id in sorted(CARDS):
            self.assertEqual(after[card_id], expected_card(card_id), card_id)
        self.assertEqual(after["CARD-01"]["name"], "Muur Collectie 2026")
        self.assertEqual(after["CARD-01"]["sku"], "SKU-0101")


if __name__ == "__main__":
    unittest.main()
