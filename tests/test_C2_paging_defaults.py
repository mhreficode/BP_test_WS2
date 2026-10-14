"""R01: defaults (page 1, pageSize 10) and paging values with an invalid character on GET /colors."""
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


class TestR01PagingDefaults(unittest.TestCase):

    def test_r01_no_params_gives_defaults(self):
        status, body = call("/colors")
        self.assertEqual(status, 200, "no params should give 200, got %s: %s" % (status, body))
        self.assertEqual(body["page"], 1, "default page must be 1: %s" % body)
        self.assertEqual(body["pageSize"], 10, "default pageSize must be 10: %s" % body)
        self.assertLessEqual(len(body["items"]), 10, "a page never holds more than pageSize items")


class TestR01PagingInvalidCharacter(unittest.TestCase):

    def assert_bad_parameter(self, path):
        status, body = call(path)
        self.assertEqual(status, 400, "%s should give 400, got %s: %s" % (path, status, body))
        self.assertEqual(body["error"]["code"], "BAD_PARAMETER", "%s: %s" % (path, body))

    def test_r01_page_digit_then_letter(self):
        self.assert_bad_parameter("/colors?page=1a")

    def test_r01_page_letter_then_digit(self):
        self.assert_bad_parameter("/colors?page=a1")

    def test_r01_page_decimal_point(self):
        self.assert_bad_parameter("/colors?page=1.5")

    def test_r01_page_decimal_comma(self):
        self.assert_bad_parameter("/colors?page=1,5")

    def test_r01_page_size_digit_then_letter(self):
        self.assert_bad_parameter("/colors?pageSize=1a")

    def test_r01_page_size_letter_then_digit(self):
        self.assert_bad_parameter("/colors?pageSize=a1")

    def test_r01_page_size_decimal_point(self):
        self.assert_bad_parameter("/colors?pageSize=1.5")

    def test_r01_page_size_decimal_comma(self):
        self.assert_bad_parameter("/colors?pageSize=1,5")


if __name__ == "__main__":
    unittest.main()
