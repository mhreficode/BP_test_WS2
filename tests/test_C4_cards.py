"""R06: a colour card lists its colours in position order, colorCount equals the list length,
hex is # and 6 capital hex digits, equal to /colors. Values come from app/seed/seed.json."""
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
    """The card as R06 and the spec say it must be served."""
    card = CARDS[card_id]
    entries = sorted(card["colors"], key=lambda e: e["position"])
    colors = [{"position": e["position"], "code": e["colorCode"],
               "name": COLORS[e["colorCode"]]["name"], "hex": COLORS[e["colorCode"]]["hex"]}
              for e in entries]
    return {"cardId": card["cardId"], "name": card["name"], "year": card["year"],
            "sku": card["sku"], "colorCount": len(colors), "colors": colors}


def call(path):
    try:
        with urllib.request.urlopen(BASE + path) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


class Base(unittest.TestCase):

    def get_card(self, card_id):
        status, body = call("/cards/" + card_id)
        self.assertEqual(status, 200, "%s should give 200, got %s: %s" % (card_id, status, body))
        return body

    def codes(self, body):
        return [c["code"] for c in body["colors"]]


class TestR06Order(Base):

    def test_c4_45_card01_order_and_positions(self):
        body = self.get_card("CARD-01")
        want = expected_card("CARD-01")
        self.assertEqual(self.codes(body), ["BP10%02d" % n for n in range(1, 13)])
        self.assertEqual([c["position"] for c in body["colors"]], list(range(1, 13)))
        self.assertEqual(body, want)

    def test_c4_46_card01_positions_10_to_12_come_last(self):
        body = self.get_card("CARD-01")
        self.assertEqual(self.codes(body)[-3:], ["BP1010", "BP1011", "BP1012"])

    def test_c4_47_card02_order_is_not_code_order(self):
        body = self.get_card("CARD-02")
        self.assertEqual(self.codes(body), ["BP1001", "BP1017", "BP1022", "BP1023",
                                            "BP1009", "BP1012", "BP1014", "BP1008"])
        self.assertEqual(body, expected_card("CARD-02"))

    def test_c4_48_card02_bp1008_last_bp1009_fifth(self):
        body = self.get_card("CARD-02")
        codes = self.codes(body)
        self.assertEqual(codes[-1], "BP1008")
        self.assertEqual(codes[4], "BP1009")

    def test_c4_49_card03_order(self):
        body = self.get_card("CARD-03")
        self.assertEqual(self.codes(body), ["BP1006", "BP1014", "BP1021", "BP1022", "BP1029", "BP1030"])
        self.assertEqual(body, expected_card("CARD-03"))

    def test_c4_50_positions_rise_on_every_card(self):
        for card_id in sorted(CARDS):
            body = self.get_card(card_id)
            positions = [c["position"] for c in body["colors"]]
            self.assertEqual(positions, sorted(positions), "%s: not in position order" % card_id)
            self.assertEqual(len(positions), len(set(positions)), "%s: repeated position" % card_id)


class TestR06Count(Base):

    def test_c4_51_to_53_color_count(self):
        for card_id, count in (("CARD-01", 12), ("CARD-02", 8), ("CARD-03", 6)):
            body = self.get_card(card_id)
            self.assertEqual(body["colorCount"], count, card_id)
            self.assertEqual(len(body["colors"]), count, card_id)

    def test_c4_54_color_count_equals_list_length(self):
        for card_id in sorted(CARDS):
            body = self.get_card(card_id)
            self.assertEqual(body["colorCount"], len(body["colors"]), card_id)
            self.assertEqual(body["colorCount"], len(CARDS[card_id]["colors"]), card_id)


class TestR06Hex(Base):

    def test_c4_55_hex_format_on_every_card(self):
        for card_id in sorted(CARDS):
            body = self.get_card(card_id)
            for colour in body["colors"]:
                self.assertRegex(colour["hex"], HEX, "%s %s" % (card_id, colour))

    def test_c4_56_card02_bp1008_hex_equals_colors(self):
        body = self.get_card("CARD-02")
        entry = [c for c in body["colors"] if c["code"] == "BP1008"][0]
        status, colour = call("/colors/BP1008")
        self.assertEqual(status, 200, colour)
        self.assertEqual(entry["hex"], colour["hex"])
        self.assertEqual(entry["hex"], COLORS["BP1008"]["hex"])
        self.assertEqual(entry["hex"], "#0B0B0C")

    def test_c4_57_card03_bp1006_hex_equals_colors(self):
        body = self.get_card("CARD-03")
        entry = [c for c in body["colors"] if c["code"] == "BP1006"][0]
        status, colour = call("/colors/BP1006")
        self.assertEqual(status, 200, colour)
        self.assertEqual(entry["hex"], colour["hex"])
        self.assertEqual(entry["hex"], "#9A9C9B")

    def test_c4_55b_every_card_hex_and_name_match_the_seed(self):
        for card_id in sorted(CARDS):
            body = self.get_card(card_id)
            for colour in body["colors"]:
                doc = COLORS[colour["code"]]
                self.assertEqual(colour["hex"], doc["hex"], "%s %s" % (card_id, colour["code"]))
                self.assertEqual(colour["name"], doc["name"], "%s %s" % (card_id, colour["code"]))


if __name__ == "__main__":
    unittest.main()
