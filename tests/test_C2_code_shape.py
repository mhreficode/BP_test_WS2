"""R03: colour code shape on GET /colors/{code}. BP + 4 digits, upper or lower case.
Bad shape: 400 INVALID_CODE. Good shape that does not exist: 404 NOT_FOUND (R09)."""
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


class TestR03CodeGoodShape(unittest.TestCase):

    def assert_found(self, path):
        status, body = call(path)
        self.assertEqual(status, 200, "%s should give 200, got %s: %s" % (path, status, body))
        self.assertEqual(body["code"], "BP1001", "%s: code must be served upper case (R04): %s" % (path, body))

    def test_r03_upper_case(self):
        self.assert_found("/colors/BP1001")

    def test_r03_lower_case(self):
        self.assert_found("/colors/bp1001")

    def test_r03_mixed_case(self):
        self.assert_found("/colors/Bp1001")

    def test_r03_mixed_case_lower_b(self):
        self.assert_found("/colors/bP1001")

    def test_r03_good_shape_unknown_code_is_404(self):
        status, body = call("/colors/BP9999")
        self.assertEqual(status, 404, "well-formed unknown code should give 404, got %s: %s" % (status, body))
        self.assertEqual(body["error"]["code"], "NOT_FOUND", body)


class TestR03CodeBadShape(unittest.TestCase):

    def assert_invalid_code(self, path):
        status, body = call(path)
        self.assertEqual(status, 400, "%s should give 400, got %s: %s" % (path, status, body))
        self.assertEqual(body["error"]["code"], "INVALID_CODE", "%s: %s" % (path, body))

    def test_r03_too_short(self):
        self.assert_invalid_code("/colors/BP100")

    def test_r03_too_long(self):
        self.assert_invalid_code("/colors/BP10001")

    def test_r03_wrong_prefix(self):
        self.assert_invalid_code("/colors/XX1001")

    def test_r03_no_prefix(self):
        self.assert_invalid_code("/colors/1001")

    def test_r03_letter_in_digits(self):
        self.assert_invalid_code("/colors/BP10A1")

    def test_r03_dash_in_code(self):
        self.assert_invalid_code("/colors/BP-1001")

    def test_r03_space_in_code(self):
        self.assert_invalid_code("/colors/BP%201001")

    def test_r03_prefix_only(self):
        self.assert_invalid_code("/colors/BP")

    def test_r03_five_digits_start_with_zero(self):
        self.assert_invalid_code("/colors/BP01001")


if __name__ == "__main__":
    unittest.main()
