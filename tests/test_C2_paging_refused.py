"""R01: bad page / pageSize values are refused with 400 BAD_PARAMETER on GET /colors."""
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


class TestR01PagingRefused(unittest.TestCase):

    def assert_bad_parameter(self, path):
        status, body = call(path)
        self.assertEqual(status, 400, "%s should give 400, got %s: %s" % (path, status, body))
        self.assertEqual(body["error"]["code"], "BAD_PARAMETER", "%s: %s" % (path, body))

    def test_r01_page_size_zero(self):
        self.assert_bad_parameter("/colors?pageSize=0")

    def test_r01_page_size_51(self):
        self.assert_bad_parameter("/colors?pageSize=51")

    def test_r01_page_size_negative(self):
        self.assert_bad_parameter("/colors?pageSize=-1")

    def test_r01_page_size_text(self):
        self.assert_bad_parameter("/colors?pageSize=abc")

    def test_r01_page_zero(self):
        self.assert_bad_parameter("/colors?page=0")

    def test_r01_page_negative(self):
        self.assert_bad_parameter("/colors?page=-1")

    def test_r01_page_text(self):
        self.assert_bad_parameter("/colors?page=abc")


if __name__ == "__main__":
    unittest.main()
