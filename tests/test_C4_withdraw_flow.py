"""E07 withdraw flow: R05 (gone from direct, lists, search, product lists) and R06 (a card does not change).
Runs as one flow so the reset (E02) always happens at the end. Values come from app/seed/seed.json."""
import json
import os
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)
COLORS = dict((c["code"], c) for c in SEED["Color"])
ACTIVE = sorted(code for code in COLORS if COLORS[code]["active"])
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


def reset():
    return call("/admin/reset", "POST")


class TestWithdrawFlow(unittest.TestCase):

    def setUp(self):
        reset()

    def tearDown(self):
        reset()

    def codes(self, path):
        status, body = call(path)
        self.assertEqual(status, 200, "%s should give 200, got %s: %s" % (path, status, body))
        return [i["code"] for i in body["items"]], body

    def test_c4_58_to_69_withdraw_bp1009_then_reset(self):
        # C4-58 withdraw
        status, body = call("/admin/colors/BP1009/withdraw", "POST")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"code": "BP1009", "active": False})

        # C4-59 direct
        status, body = call("/colors/BP1009")
        self.assertEqual(status, 410, body)
        self.assertEqual(body["error"]["code"], "COLOR_WITHDRAWN")

        # C4-60 list
        codes, body = self.codes("/colors?pageSize=50")
        self.assertEqual(codes, [c for c in ACTIVE if c != "BP1009"])
        self.assertEqual(body["total"], 36)

        # C4-61 family
        codes, body = self.codes("/colors?family=blue")
        self.assertEqual(codes, ["BP1010", "BP1011", "BP1012", "BP1036"])

        # C4-62 search
        codes, body = self.codes("/colors?q=delfts")
        self.assertEqual(codes, [])
        self.assertEqual(body["total"], 0)

        # C4-63 product list
        codes, body = self.codes("/products/SKU-0101/colors?pageSize=50")
        self.assertNotIn("BP1009", codes)
        self.assertEqual(body["total"], 19)
        self.assertEqual(len(codes), 19)

        # C4-64, C4-65 cards do not change
        for card_id in ("CARD-01", "CARD-02"):
            status, body = call("/cards/" + card_id)
            self.assertEqual(status, 200, body)
            self.assertEqual(body, expected_card(card_id), card_id)
        status, body = call("/cards/CARD-01")
        self.assertEqual(body["colorCount"], 12)
        self.assertEqual([c for c in body["colors"] if c["code"] == "BP1009"][0]["position"], 9)
        status, body = call("/cards/CARD-02")
        self.assertEqual(body["colorCount"], 8)
        self.assertEqual([c for c in body["colors"] if c["code"] == "BP1009"][0]["position"], 5)

        # C4-66 withdraw with lower case
        status, body = call("/admin/colors/bp1013/withdraw", "POST")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"code": "BP1013", "active": False})
        status, body = call("/colors/BP1013")
        self.assertEqual(status, 410, body)

        # C4-67 withdraw unknown colour
        status, body = call("/admin/colors/BP9999/withdraw", "POST")
        self.assertEqual(status, 404, body)
        self.assertEqual(body["error"]["code"], "NOT_FOUND")

        # C4-68 reset
        status, body = reset()
        self.assertEqual(status, 200, body)
        status, body = call("/colors/BP1009")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["name"], "Delfts Blauw")
        codes, body = self.codes("/colors?pageSize=50")
        self.assertEqual(codes, ACTIVE)
        self.assertEqual(body["total"], 37)

        # C4-69 card still right after reset
        status, body = call("/cards/CARD-01")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, expected_card("CARD-01"))


if __name__ == "__main__":
    unittest.main()
