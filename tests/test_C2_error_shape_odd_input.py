"""R09: every 400 has the same body {"error": {"code": "...", "message": "..."}}.
R03 odd input: control characters, non-ASCII digits, null bytes and emoji never crash (no 500)."""
import json
import os
import unittest
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")


def call_raw(path):
    """Return (status, raw text) for a GET request. Fails the test on a dropped connection."""
    try:
        with urllib.request.urlopen(BASE + path) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")


def call(path):
    status, text = call_raw(path)
    return status, json.loads(text)


class TestR09ErrorBodyShape(unittest.TestCase):

    PATHS = [
        "/colors/BP100",
        "/products/sku-0101/colors",
        "/cards/CARD-1",
        "/colors?q=",
        "/colors?family=Blue",
    ]

    def test_r03_63_every_400_has_the_same_body(self):
        for path in self.PATHS:
            status, body = call(path)
            self.assertEqual(status, 400, "%s should give 400, got %s: %s" % (path, status, body))
            self.assertEqual(set(body.keys()), {"error"}, "%s: only key must be 'error': %s" % (path, body))
            self.assertEqual(set(body["error"].keys()), {"code", "message"},
                             "%s: error must hold exactly code and message: %s" % (path, body))
            self.assertIsInstance(body["error"]["code"], str, "%s: code must be text: %s" % (path, body))
            self.assertIsInstance(body["error"]["message"], str, "%s: message must be text: %s" % (path, body))


class TestR03OddInputRefused(unittest.TestCase):

    def assert_error(self, path, code):
        status, body = call(path)
        self.assertEqual(status, 400, "%s should give 400, got %s: %s" % (path, status, body))
        self.assertEqual(body["error"]["code"], code, "%s: %s" % (path, body))

    def test_r03_64_newline_after_code(self):
        self.assert_error("/colors/BP1001%0A", "INVALID_CODE")

    def test_r03_65_tab_after_code(self):
        self.assert_error("/colors/BP1001%09", "INVALID_CODE")

    def test_r03_66_arabic_indic_digits(self):
        self.assert_error("/colors/" + urllib.parse.quote("BP١٠٠١"), "INVALID_CODE")

    def test_r03_67_newline_after_sku(self):
        self.assert_error("/products/SKU-0101%0A/colors", "INVALID_SKU")

    def test_r03_68_newline_after_card(self):
        self.assert_error("/cards/CARD-01%0A", "INVALID_CARD")


class TestR03OddInputNeverCrashes(unittest.TestCase):

    def assert_no_500(self, path):
        status, text = call_raw(path)
        self.assertLess(status, 500, "%s must not crash, got %s: %s" % (path, status, text[:200]))

    def test_r03_69_null_byte_in_code(self):
        self.assert_no_500("/colors/BP1001%00")

    def test_r03_70_emoji_in_q(self):
        self.assert_no_500("/colors?q=" + urllib.parse.quote("🎨"))

    def test_r03_71_null_byte_in_family(self):
        self.assert_no_500("/colors?family=bl%00ue")

    def test_r03_72_superscript_digits_in_card(self):
        self.assert_no_500("/cards/" + urllib.parse.quote("CARD-¹²"))


if __name__ == "__main__":
    unittest.main()
