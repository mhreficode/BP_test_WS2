"""R01: the edge values page=1, pageSize=1 and pageSize=50 are accepted on GET /colors."""
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


class TestR01PagingEdges(unittest.TestCase):

    def assert_ok(self, path, page, size):
        status, body = call(path)
        self.assertEqual(status, 200, "%s should give 200, got %s: %s" % (path, status, body))
        self.assertEqual(body["page"], page, "%s: page field: %s" % (path, body))
        self.assertEqual(body["pageSize"], size, "%s: pageSize field: %s" % (path, body))
        self.assertLessEqual(len(body["items"]), size, "%s: too many items" % path)

    def test_r01_page_size_1(self):
        self.assert_ok("/colors?pageSize=1", 1, 1)

    def test_r01_page_size_50(self):
        self.assert_ok("/colors?pageSize=50", 1, 50)

    def test_r01_page_1(self):
        self.assert_ok("/colors?page=1", 1, 10)

    def test_r01_page_1_size_50(self):
        self.assert_ok("/colors?page=1&pageSize=50", 1, 50)


if __name__ == "__main__":
    unittest.main()
