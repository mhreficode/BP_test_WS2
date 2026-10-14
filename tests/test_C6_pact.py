"""Pact replay: every interaction in app/pact/storefront-colorlab.json, before and after a reset.
Then the colour rules on every active colour and the card rules on every card. R04, R06, R09."""
import json
import os
import re
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")

with open("app/pact/storefront-colorlab.json", encoding="utf-8") as fh:
    PACT = json.load(fh)
with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)
ACTIVE = sorted(c["code"] for c in SEED["Color"] if c["active"])
CARD_IDS = sorted(c["cardId"] for c in SEED["SkuColorCard"])
BY_NAME = dict((i["description"].split()[0], i) for i in PACT["interactions"])


def call(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def resolve(body, path):
    """All values at a dot path. [*] means every element of a list."""
    values = [body]
    for part in path.split("."):
        star = part.endswith("[*]")
        key = part[:-3] if star else part
        nxt = []
        for value in values:
            if not isinstance(value, dict) or key not in value:
                raise KeyError("missing %s in path %s" % (key, path))
            value = value[key]
            if star:
                if not isinstance(value, list):
                    raise KeyError("%s is not a list in path %s" % (key, path))
                nxt.extend(value)
            else:
                nxt.append(value)
        values = nxt
    return values


class PactBase(unittest.TestCase):

    def check_rules(self, body, rules, where):
        for rule in rules:
            try:
                values = resolve(body, rule["path"])
            except KeyError as exc:
                self.fail("%s: %s" % (where, exc))
            for value in values:
                label = "%s: %s" % (where, rule["path"])
                if rule["match"] == "regex":
                    self.assertIsInstance(value, str, label)
                    self.assertRegex(value, rule["regex"], label)
                elif rule["type"] == "string":
                    self.assertIsInstance(value, str, label)
                elif rule["type"] == "integer":
                    self.assertIsInstance(value, int, label)
                    self.assertNotIsInstance(value, bool, label)
                elif rule["type"] == "array-nonempty":
                    self.assertIsInstance(value, list, label)
                    self.assertTrue(len(value) > 0, label + " is empty")
                else:
                    self.fail("unknown rule type %s" % rule)

    def replay(self, interaction, path=None):
        req = interaction["request"]
        target = path or req["path"]
        if req.get("query"):
            target += "?" + req["query"]
        status, body = call(target, req["method"])
        where = "%s %s" % (interaction["description"], target)
        self.assertEqual(status, interaction["response"]["status"], "%s: %s" % (where, body))
        self.check_rules(body, interaction["response"]["rules"], where)


class TestPactReplay(PactBase):

    def test_c6_55_to_60_every_interaction_before_and_after_reset(self):
        self.assertEqual(len(PACT["interactions"]), 6, "pact sanity")
        for interaction in PACT["interactions"]:
            self.replay(interaction)
        status, body = call("/admin/reset", "POST")
        self.assertEqual(status, 200, body)
        for interaction in PACT["interactions"]:
            self.replay(interaction)

    def test_c6_61_card_rules_on_every_card(self):
        for card_id in CARD_IDS:
            self.replay(BY_NAME["PI-3"], "/cards/" + card_id)
            self.replay(BY_NAME["PI-4"], "/cards/" + card_id)

    def test_c6_62_colour_rules_on_every_active_colour(self):
        self.assertEqual(len(ACTIVE), 37, "seed sanity")
        for code in ACTIVE:
            self.replay(BY_NAME["PI-1"], "/colors/" + code)


if __name__ == "__main__":
    unittest.main()
