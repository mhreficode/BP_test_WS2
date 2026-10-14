"""R03: card id shape on GET /cards/{cardId}; q and family on GET /colors.
Card: exactly CARD- and 2 digits, else 400 INVALID_CARD. Unknown good shape: 404 NOT_FOUND (R09).
q: 1 to 64 characters, any valid characters including accents, else 400 BAD_PARAMETER.
family: one of the 11 family names in lower case, else 400 BAD_PARAMETER."""
import json
import os
import unittest
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")

FAMILIES = ["white", "grey", "black", "blue", "green", "yellow",
            "orange", "red", "pink", "purple", "brown"]


def call(path):
    """Return (status, body dict) for a GET request."""
    try:
        with urllib.request.urlopen(BASE + path) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def q(text):
    """Build /colors?q=<text> with proper URL encoding."""
    return "/colors?q=" + urllib.parse.quote(text)


def fam(text):
    """Build /colors?family=<text> with proper URL encoding."""
    return "/colors?family=" + urllib.parse.quote(text)


class TestR03CardShape(unittest.TestCase):

    def assert_invalid_card(self, path):
        status, body = call(path)
        self.assertEqual(status, 400, "%s should give 400, got %s: %s" % (path, status, body))
        self.assertEqual(body["error"]["code"], "INVALID_CARD", "%s: %s" % (path, body))

    def test_r03_good_cards_are_found(self):
        for card in ("CARD-01", "CARD-02", "CARD-03"):
            status, body = call("/cards/" + card)
            self.assertEqual(status, 200, "%s should give 200, got %s: %s" % (card, status, body))

    def test_r03_good_shape_unknown_card_is_404(self):
        status, body = call("/cards/CARD-99")
        self.assertEqual(status, 404, "well-formed unknown card should give 404, got %s: %s" % (status, body))
        self.assertEqual(body["error"]["code"], "NOT_FOUND", body)

    def test_r03_one_digit(self):
        self.assert_invalid_card("/cards/CARD-1")

    def test_r03_three_digits(self):
        self.assert_invalid_card("/cards/CARD-001")

    def test_r03_lower_case(self):
        self.assert_invalid_card("/cards/card-01")

    def test_r03_no_dash(self):
        self.assert_invalid_card("/cards/CARD01")

    def test_r03_space_in_card(self):
        self.assert_invalid_card("/cards/CARD-%2001")


class TestR03SearchTextQ(unittest.TestCase):

    def assert_ok(self, path):
        status, body = call(path)
        self.assertEqual(status, 200, "%s should give 200, got %s: %s" % (path, status, body))
        self.assertIn("items", body, body)

    def assert_bad_parameter(self, path):
        status, body = call(path)
        self.assertEqual(status, 400, "%s should give 400, got %s: %s" % (path, status, body))
        self.assertEqual(body["error"]["code"], "BAD_PARAMETER", "%s: %s" % (path, body))

    def test_r03_q_one_character(self):
        self.assert_ok(q("w"))

    def test_r03_q_64_characters(self):
        self.assert_ok(q("a" * 64))

    def test_r03_q_64_accented_characters(self):
        self.assert_ok(q("é" * 64))

    def test_r03_q_64_mixed_characters(self):
        text = ("aB1 é-" * 11)[:64]
        self.assertEqual(len(text), 64)
        self.assert_ok(q(text))

    def test_r03_q_empty(self):
        self.assert_bad_parameter("/colors?q=")

    def test_r03_q_65_characters(self):
        self.assert_bad_parameter(q("a" * 65))

    def test_r03_q_65_accented_characters(self):
        self.assert_bad_parameter(q("é" * 65))


class TestR03Family(unittest.TestCase):

    def assert_bad_parameter(self, path):
        status, body = call(path)
        self.assertEqual(status, 400, "%s should give 400, got %s: %s" % (path, status, body))
        self.assertEqual(body["error"]["code"], "BAD_PARAMETER", "%s: %s" % (path, body))

    def test_r03_all_11_families_are_accepted(self):
        for name in FAMILIES:
            status, body = call(fam(name))
            self.assertEqual(status, 200, "family %s should give 200, got %s: %s" % (name, status, body))
            self.assertIn("items", body, body)

    def test_r03_family_capitalised(self):
        self.assert_bad_parameter(fam("Blue"))

    def test_r03_family_upper_case(self):
        self.assert_bad_parameter(fam("BLUE"))

    def test_r03_family_dutch_name(self):
        self.assert_bad_parameter(fam("blauw"))

    def test_r03_family_american_spelling(self):
        self.assert_bad_parameter(fam("gray"))

    def test_r03_family_leading_space(self):
        self.assert_bad_parameter(fam(" blue"))

    def test_r03_family_trailing_space(self):
        self.assert_bad_parameter(fam("blue "))

    def test_r03_family_empty(self):
        self.assert_bad_parameter("/colors?family=")

    def test_r03_family_unknown_name(self):
        self.assert_bad_parameter(fam("beige"))

    def test_r03_family_two_names(self):
        self.assert_bad_parameter(fam("blue,red"))


if __name__ == "__main__":
    unittest.main()
