"""R03 extra shapes from the team's test table: colour code, SKU, card id and q.
Bad shape: 400 INVALID_CODE / INVALID_SKU / INVALID_CARD / BAD_PARAMETER, checked before any lookup."""
import json
import os
import unittest
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")


def call(path):
    """Return (status, body dict) for a GET request."""
    try:
        with urllib.request.urlopen(BASE + path) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


class Base(unittest.TestCase):

    def assert_error(self, path, status, code):
        got_status, body = call(path)
        self.assertEqual(got_status, status, "%s should give %s, got %s: %s" % (path, status, got_status, body))
        self.assertEqual(body["error"]["code"], code, "%s: %s" % (path, body))

    def assert_ok(self, path):
        status, body = call(path)
        self.assertEqual(status, 200, "%s should give 200, got %s: %s" % (path, status, body))


class TestR03CodeExtra(Base):

    def test_r03_06_five_digits(self):
        self.assert_error("/colors/BP10011", 400, "INVALID_CODE")

    def test_r03_09_half_prefix(self):
        self.assert_error("/colors/B1001", 400, "INVALID_CODE")

    def test_r03_13_leading_space(self):
        self.assert_error("/colors/%20BP1001", 400, "INVALID_CODE")

    def test_r03_14_trailing_space(self):
        self.assert_error("/colors/BP1001%20", 400, "INVALID_CODE")

    def test_r03_15_double_prefix(self):
        self.assert_error("/colors/BPBP1001", 400, "INVALID_CODE")

    def test_r03_17_bad_shape_and_unknown_is_400_not_404(self):
        self.assert_error("/colors/BP99999", 400, "INVALID_CODE")


class TestR03SkuExtra(Base):

    def test_r03_20_mixed_case_sku(self):
        self.assert_error("/products/Sku-0101/colors", 400, "INVALID_SKU")

    def test_r03_21_mixed_case_sku_lower_s(self):
        self.assert_error("/products/sKU-0101/colors", 400, "INVALID_SKU")

    def test_r03_22_three_digits(self):
        self.assert_error("/products/SKU-101/colors", 400, "INVALID_SKU")

    def test_r03_23_five_digits(self):
        self.assert_error("/products/SKU-00101/colors", 400, "INVALID_SKU")

    def test_r03_27_double_dash(self):
        self.assert_error("/products/SKU--0101/colors", 400, "INVALID_SKU")

    def test_r03_28_leading_space(self):
        self.assert_error("/products/%20SKU-0101/colors", 400, "INVALID_SKU")

    def test_r03_29_trailing_space(self):
        self.assert_error("/products/SKU-0101%20/colors", 400, "INVALID_SKU")

    def test_r03_32_bad_shape_and_unknown_is_400_not_404(self):
        self.assert_error("/products/SKU-99999/colors", 400, "INVALID_SKU")


class TestR03CardExtra(Base):

    def test_r03_39_mixed_case(self):
        self.assert_error("/cards/Card-01", 400, "INVALID_CARD")

    def test_r03_41_letter_instead_of_digit(self):
        self.assert_error("/cards/CARD-0A", 400, "INVALID_CARD")

    def test_r03_42_trailing_space(self):
        self.assert_error("/cards/CARD-01%20", 400, "INVALID_CARD")

    def test_r03_43_leading_space(self):
        self.assert_error("/cards/%20CARD-01", 400, "INVALID_CARD")

    def test_r03_44_wrong_prefix(self):
        self.assert_error("/cards/CRD-01", 400, "INVALID_CARD")


class TestR03QExtra(Base):

    def test_r03_48_64_e_grave(self):
        self.assert_ok("/colors?q=" + urllib.parse.quote("è" * 64))

    def test_r03_49_64_mixed_cremewit(self):
        text = "Crèmewit " * 7 + "a"
        self.assertEqual(len(text), 64)
        self.assert_ok("/colors?q=" + urllib.parse.quote(text))

    def test_r03_52_65_e_grave(self):
        self.assert_error("/colors?q=" + urllib.parse.quote("è" * 65), 400, "BAD_PARAMETER")


if __name__ == "__main__":
    unittest.main()
