"""The spec: app/openapi/color-v1.json. Shape of the answers, not their values.

A small checker walks the schema of the spec: $ref, allOf, required, type,
pattern, minimum and maximum. It refuses unknown fields nowhere, because the
spec does not say additionalProperties false; it checks what the spec does say.

The value tests live elsewhere. This file asks one thing: does the answer have
the shape the spec promises, on every endpoint of the contract?
"""
import json
import os
import re
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")

with open("app/openapi/color-v1.json", encoding="utf-8") as fh:
    SPEC = json.load(fh)

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)

ACTIVE = sorted(c["code"] for c in SEED["Color"] if c["active"])
WITHDRAWN = sorted(c["code"] for c in SEED["Color"] if not c["active"])
CARD_IDS = sorted(c["cardId"] for c in SEED["SkuColorCard"])
MIXABLE = {p["productCode"] for p in SEED["Product"] if p["mixable"]}
MIX_SKUS = sorted(s["sku"] for s in SEED["Sku"] if s["productCode"] in MIXABLE)


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8") or "{}")


def resolve(schema):
    while "$ref" in schema:
        node = SPEC
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        schema = node
    return schema


def violations(value, schema, where="body"):
    """Return a list of places where value does not follow schema."""
    schema = resolve(schema)
    bad = []
    if "allOf" in schema:
        for part in schema["allOf"]:
            bad += violations(value, part, where)
        return bad
    wanted = schema.get("type")
    if wanted == "object":
        if not isinstance(value, dict):
            return [(where, "not an object", value)]
        for name in schema.get("required", []):
            if name not in value:
                bad.append((where, "missing field", name))
        for name, sub in schema.get("properties", {}).items():
            if name in value:
                bad += violations(value[name], sub, where + "." + name)
        return bad
    if wanted == "array":
        if not isinstance(value, list):
            return [(where, "not an array", value)]
        for index, item in enumerate(value):
            bad += violations(item, schema.get("items", {}), "%s[%d]" % (where, index))
        return bad
    if wanted == "string":
        if not isinstance(value, str):
            return [(where, "not a string", value)]
        if "pattern" in schema and not re.match(schema["pattern"], value):
            bad.append((where, "pattern", value, schema["pattern"]))
        return bad
    if wanted == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return [(where, "not an integer", value)]
        if "minimum" in schema and value < schema["minimum"]:
            bad.append((where, "below minimum", value, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            bad.append((where, "above maximum", value, schema["maximum"]))
        return bad
    if wanted == "boolean":
        if not isinstance(value, bool):
            return [(where, "not a boolean", value)]
    return bad


def schema_for(path, status):
    node = SPEC["paths"][path]["get"]["responses"][str(status)]
    node = resolve(node)
    return node["content"]["application/json"]["schema"]


class SpecShape(unittest.TestCase):
    def check(self, url, status, spec_path, spec_status=None):
        got_status, body = get(url)
        if got_status != status:
            return [(url, "status", got_status, status)]
        return [(url,) + v for v in
                violations(body, schema_for(spec_path, spec_status or status))]

    def test_health_shape(self):
        self.assertEqual(self.check("/health", 200, "/health"), [])

    def test_one_colour_shape(self):
        bad = []
        for code in ACTIVE:
            bad += self.check("/colors/" + code, 200, "/colors/{code}")
        self.assertEqual(bad, [])

    def test_colour_page_shape(self):
        bad = []
        for url in ("/colors", "/colors?pageSize=50", "/colors?page=2",
                    "/colors?pageSize=1", "/colors?family=white", "/colors?q=wit"):
            bad += self.check(url, 200, "/colors")
        self.assertEqual(bad, [])

    def test_product_colour_page_shape(self):
        bad = []
        for sku in MIX_SKUS:
            bad += self.check("/products/%s/colors?pageSize=50" % sku, 200,
                              "/products/{sku}/colors")
        self.assertEqual(bad, [])

    def test_card_shape(self):
        bad = []
        for cid in CARD_IDS:
            bad += self.check("/cards/" + cid, 200, "/cards/{cardId}")
        self.assertEqual(bad, [])

    def test_error_shape_404(self):
        bad = self.check("/colors/BP9999", 404, "/colors/{code}")
        bad += self.check("/cards/CARD-99", 404, "/cards/{cardId}")
        self.assertEqual(bad, [])

    def test_error_shape_410(self):
        bad = []
        for code in WITHDRAWN:
            bad += self.check("/colors/" + code, 410, "/colors/{code}")
        self.assertEqual(bad, [])

    def test_error_shape_400(self):
        bad = self.check("/colors/BP10", 400, "/colors/{code}")
        bad += self.check("/cards/CARD-1", 400, "/cards/{cardId}")
        bad += self.check("/colors?pageSize=51", 400, "/colors")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
