"""The consumer contract: app/pact/storefront-colorlab.json.

The pact is the promise the Storefront leans on. Each interaction gives a
request, an expected status and flat rules. A rule has a dot path ([*] means
every element of an array), a match ('regex' or 'type') and the regex or type
to hold. Types used by this pact: string, integer, array-nonempty.

One test per interaction, named after the PI number in the pact file.
"""
import json
import os
import re
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")

with open("app/pact/storefront-colorlab.json", encoding="utf-8") as fh:
    PACT = json.load(fh)

INTERACTIONS = {i["description"].split()[0]: i for i in PACT["interactions"]}


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8") or "{}")


def pick(body, path):
    """Walk a dot path. Returns a list of values: [*] fans out over an array."""
    values = [body]
    for part in path.split("."):
        star = part.endswith("[*]")
        key = part[:-3] if star else part
        found = []
        for value in values:
            if not isinstance(value, dict) or key not in value:
                return None
            found.append(value[key])
        if star:
            fanned = []
            for value in found:
                if not isinstance(value, list):
                    return None
                fanned.extend(value)
            values = fanned
        else:
            values = found
    return values


def type_ok(value, wanted):
    if wanted == "string":
        return isinstance(value, str)
    if wanted == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if wanted == "array-nonempty":
        return isinstance(value, list) and len(value) > 0
    raise AssertionError("unknown pact type: " + wanted)


def check(interaction):
    request = interaction["request"]
    path = request["path"]
    if request.get("query"):
        path += "?" + request["query"]
    status, body = get(path)
    problems = []
    if status != interaction["response"]["status"]:
        problems.append(("status", status, interaction["response"]["status"]))
    for rule in interaction["response"].get("rules", []):
        values = pick(body, rule["path"])
        if values is None:
            problems.append(("missing", rule["path"]))
            continue
        for value in values:
            if rule["match"] == "regex":
                if not isinstance(value, str) or not re.match(rule["regex"], value):
                    problems.append((rule["path"], value, rule["regex"]))
            elif rule["match"] == "type":
                if not type_ok(value, rule["type"]):
                    problems.append((rule["path"], value, rule["type"]))
            else:
                raise AssertionError("unknown pact match: " + rule["match"])
    return problems


class Pact(unittest.TestCase):
    def test_pi1_get_one_colour(self):
        self.assertEqual(check(INTERACTIONS["PI-1"]), [])

    def test_pi2_get_the_colours_of_a_product(self):
        self.assertEqual(check(INTERACTIONS["PI-2"]), [])

    def test_pi3_get_one_colour_card(self):
        self.assertEqual(check(INTERACTIONS["PI-3"]), [])

    def test_pi4_get_a_second_colour_card(self):
        self.assertEqual(check(INTERACTIONS["PI-4"]), [])

    def test_pi5_unknown_colour_error_body(self):
        self.assertEqual(check(INTERACTIONS["PI-5"]), [])

    def test_pi6_withdrawn_colour_error_body(self):
        self.assertEqual(check(INTERACTIONS["PI-6"]), [])

    def test_every_interaction_in_the_file_is_covered(self):
        # If the pact grows, this test goes red until a test is added above.
        covered = {"PI-1", "PI-2", "PI-3", "PI-4", "PI-5", "PI-6"}
        self.assertEqual(sorted(INTERACTIONS), sorted(covered))


if __name__ == "__main__":
    unittest.main()
