"""E01 health and the X-Seed-Version header. The spec: /health gives status, version, seedVersion
(all text) and the header X-Seed-Version with the seed version. Seed 2026.10.1, API version 1.0.0."""
import json
import os
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")
SEED_VERSION = "2026.10.1"
API_VERSION = "1.0.0"
HEADER = "X-Seed-Version"


def call(path, method="GET"):
    """Return (status, body, headers)."""
    req = urllib.request.Request(BASE + path, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), resp.headers
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8")), err.headers


class TestHealth(unittest.TestCase):

    def test_c6_01_to_03_health_body(self):
        status, body, headers = call("/health")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"status": "ok", "version": API_VERSION, "seedVersion": SEED_VERSION})
        for key in ("status", "version", "seedVersion"):
            self.assertIsInstance(body[key], str, key)

    def test_c6_04_05_header_present_and_equal_to_body(self):
        status, body, headers = call("/health")
        self.assertEqual(status, 200, body)
        self.assertEqual(headers.get(HEADER), SEED_VERSION, "header %s" % HEADER)
        self.assertEqual(headers.get(HEADER), body["seedVersion"])


class TestSeedHeaderEverywhere(unittest.TestCase):

    PATHS = [
        ("GET", "/colors/BP1001", 200),
        ("GET", "/colors", 200),
        ("GET", "/products/SKU-0101/colors", 200),
        ("GET", "/cards/CARD-01", 200),
        ("POST", "/admin/reset", 200),
        ("GET", "/colors/BP100", 400),
        ("GET", "/colors/BP9999", 404),
        ("GET", "/colors/BP1038", 410),
    ]

    def test_c6_06_to_14_same_header_on_every_answer(self):
        for method, path, want in self.PATHS:
            status, body, headers = call(path, method)
            self.assertEqual(status, want, "%s %s: %s" % (method, path, body))
            self.assertEqual(headers.get(HEADER), SEED_VERSION, "%s %s: header %s" % (method, path, HEADER))

    def test_c6_15_header_after_reset(self):
        status, body, headers = call("/admin/reset", "POST")
        self.assertEqual(status, 200, body)
        status, body, headers = call("/health")
        self.assertEqual(status, 200, body)
        self.assertEqual(headers.get(HEADER), SEED_VERSION)
        self.assertEqual(body["seedVersion"], SEED_VERSION)


if __name__ == "__main__":
    unittest.main()
