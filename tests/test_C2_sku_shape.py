"""R03: SKU shape on GET /products/{sku}/colors. Exactly SKU- and 4 digits.
Bad shape: 400 INVALID_SKU. Good shape that does not exist: 404 NOT_FOUND (R09)."""
import json
import os
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")


def call(path):
    """Return (status, body dict) for a GET request."""
    try:
        with urllib.request.urlopen(BASE + path) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


class TestR03SkuGoodShape(unittest.TestCase):

    def test_r03_good_sku_is_found(self):
        status, body = call("/products/SKU-0101/colors")
        self.assertEqual(status, 200, "SKU-0101 should give 200, got %s: %s" % (status, body))
        self.assertEqual(body["sku"], "SKU-0101", body)

    def test_r03_good_shape_unknown_sku_is_404(self):
        status, body = call("/products/SKU-9999/colors")
        self.assertEqual(status, 404, "well-formed unknown SKU should give 404, got %s: %s" % (status, body))
        self.assertEqual(body["error"]["code"], "NOT_FOUND", body)


class TestR03SkuBadShape(unittest.TestCase):

    def assert_invalid_sku(self, path):
        status, body = call(path)
        self.assertEqual(status, 400, "%s should give 400, got %s: %s" % (path, status, body))
        self.assertEqual(body["error"]["code"], "INVALID_SKU", "%s: %s" % (path, body))

    def test_r03_lower_case_prefix(self):
        self.assert_invalid_sku("/products/sku-0101/colors")

    def test_r03_too_short(self):
        self.assert_invalid_sku("/products/SKU-010/colors")

    def test_r03_too_long(self):
        self.assert_invalid_sku("/products/SKU-01011/colors")

    def test_r03_no_dash(self):
        self.assert_invalid_sku("/products/SKU0101/colors")

    def test_r03_underscore(self):
        self.assert_invalid_sku("/products/SKU_0101/colors")

    def test_r03_letter_in_digits(self):
        self.assert_invalid_sku("/products/SKU-01A1/colors")

    def test_r03_no_prefix(self):
        self.assert_invalid_sku("/products/0101/colors")

    def test_r03_wrong_prefix(self):
        self.assert_invalid_sku("/products/BP-0101/colors")

    def test_r03_product_code_instead_of_sku(self):
        self.assert_invalid_sku("/products/PRD-01/colors")

    def test_r03_space_in_sku(self):
        self.assert_invalid_sku("/products/SKU-%200101/colors")

    def test_r03_prefix_only(self):
        self.assert_invalid_sku("/products/SKU-/colors")


if __name__ == "__main__":
    unittest.main()
