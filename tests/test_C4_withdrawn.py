"""R05: a withdrawn colour is never offered. Direct request gives 410 COLOR_WITHDRAWN.
It is absent from /colors, from search and from product colour lists. Values come from app/seed/seed.json."""
import json
import os
import unittest
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)
COLORS = dict((c["code"], c) for c in SEED["Color"])
ACTIVE = sorted(code for code in COLORS if COLORS[code]["active"])
WITHDRAWN = sorted(code for code in COLORS if not COLORS[code]["active"])


def served(code):
    """A colour exactly as R04 says it must be served."""
    doc = COLORS[code]
    return {"code": doc["code"], "name": doc["name"], "hex": doc["hex"],
            "family": doc["family"], "formulaCode": doc["formulaCode"]}


def call(path):
    try:
        with urllib.request.urlopen(BASE + path) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


class Base(unittest.TestCase):

    def assert_error(self, path, status, code):
        got, body = call(path)
        self.assertEqual(got, status, "%s should give %s, got %s: %s" % (path, status, got, body))
        self.assertEqual(set(body.keys()), {"error"}, "%s: body must hold only 'error': %s" % (path, body))
        self.assertEqual(set(body["error"].keys()), {"code", "message"}, "%s: %s" % (path, body))
        self.assertEqual(body["error"]["code"], code, "%s: %s" % (path, body))

    def assert_list(self, path, codes, total=None, total_pages=None):
        """A 200 list whose items are exactly these codes, in this order, with seed values."""
        status, body = call(path)
        self.assertEqual(status, 200, "%s should give 200, got %s: %s" % (path, status, body))
        got = [item["code"] for item in body["items"]]
        self.assertEqual(got, codes, "%s: items" % path)
        for item in body["items"]:
            self.assertEqual(item, served(item["code"]), "%s: values of %s" % (path, item.get("code")))
        if total is not None:
            self.assertEqual(body["total"], total, "%s: total" % path)
        if total_pages is not None:
            self.assertEqual(body["totalPages"], total_pages, "%s: totalPages" % path)
        return body


class TestR05Direct(Base):

    def test_c4_01_to_03_withdrawn_colours_give_410(self):
        self.assertEqual(WITHDRAWN, ["BP1038", "BP1039", "BP1040"], "seed sanity")
        for code in WITHDRAWN:
            self.assert_error("/colors/" + code, 410, "COLOR_WITHDRAWN")

    def test_c4_04_withdrawn_lower_case(self):
        self.assert_error("/colors/bp1038", 410, "COLOR_WITHDRAWN")

    def test_c4_05_active_neighbour_bp1037(self):
        status, body = call("/colors/BP1037")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, served("BP1037"))
        self.assertEqual(body["name"], "Munt")

    def test_c4_06_first_active_colour(self):
        status, body = call("/colors/BP1001")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, served("BP1001"))
        self.assertEqual(body["name"], "Wit Gebroken")

    def test_c4_07_unknown_is_404_not_410(self):
        self.assert_error("/colors/BP9999", 404, "NOT_FOUND")

    def test_c4_08_410_has_the_error_shape(self):
        self.assert_error("/colors/BP1038", 410, "COLOR_WITHDRAWN")


class TestR05Lists(Base):

    def test_c4_09_full_list_has_no_withdrawn(self):
        self.assertEqual(len(ACTIVE), 37, "seed sanity")
        self.assert_list("/colors?pageSize=50", ACTIVE, total=37, total_pages=1)

    def test_c4_10_walk_all_pages(self):
        seen = []
        for page in range(1, 5):
            status, body = call("/colors?page=%d" % page)
            self.assertEqual(status, 200, body)
            seen.extend(item["code"] for item in body["items"])
        self.assertEqual(seen, ACTIVE)
        for code in WITHDRAWN:
            self.assertNotIn(code, seen)

    def test_c4_11_last_page(self):
        self.assert_list("/colors?page=4", ACTIVE[30:], total=37, total_pages=4)
        self.assertEqual(ACTIVE[-1], "BP1037")

    def family(self, name):
        return [code for code in ACTIVE if COLORS[code]["family"] == name]

    def test_c4_12_family_green(self):
        codes = self.family("green")
        self.assertEqual(codes, ["BP1013", "BP1014", "BP1015", "BP1016", "BP1037"])
        self.assert_list("/colors?family=green", codes, total=5, total_pages=1)

    def test_c4_13_family_yellow(self):
        codes = self.family("yellow")
        self.assertEqual(codes, ["BP1017", "BP1018", "BP1019"])
        self.assert_list("/colors?family=yellow", codes, total=3, total_pages=1)

    def test_c4_14_family_brown(self):
        codes = self.family("brown")
        self.assertEqual(codes, ["BP1029", "BP1030", "BP1031", "BP1032"])
        self.assert_list("/colors?family=brown", codes, total=4, total_pages=1)

    def search(self, q, family=None):
        """R10 expectation from the seed: active only, name contains q ignoring case, family exact."""
        out = []
        for code in ACTIVE:
            doc = COLORS[code]
            if family is not None and doc["family"] != family:
                continue
            if q.lower() in doc["name"].lower():
                out.append(code)
        return out

    def q_path(self, q, family=None):
        path = "/colors?q=" + urllib.parse.quote(q)
        if family is not None:
            path += "&family=" + family
        return path

    def test_c4_15_to_17_search_withdrawn_names_find_nothing(self):
        for q in ("olijf", "kanarie", "café"):
            self.assertEqual(self.search(q), [], "seed sanity for %s" % q)
            self.assert_list(self.q_path(q), [], total=0, total_pages=0)

    def test_c4_18_search_creme_only_active(self):
        self.assertEqual(self.search("crème"), ["BP1003"])
        self.assert_list(self.q_path("crème"), ["BP1003"], total=1)

    def test_c4_19_search_geel_no_kanariegeel(self):
        self.assertEqual(self.search("geel"), ["BP1017", "BP1018", "BP1019"])
        self.assert_list(self.q_path("geel"), ["BP1017", "BP1018", "BP1019"], total=3)

    def test_c4_20_search_groen_and_green(self):
        self.assertEqual(self.search("groen", "green"), ["BP1013", "BP1014", "BP1015", "BP1016"])
        self.assert_list(self.q_path("groen", "green"), ["BP1013", "BP1014", "BP1015", "BP1016"], total=4)

    def test_c4_21_total_counts_no_withdrawn(self):
        self.assert_list("/colors?family=green", self.family("green"), total=5, total_pages=1)


class TestR05ProductLists(Base):

    def product_codes(self, product):
        """R08 expectation from the seed: linked colours, active only, sorted by code."""
        linked = [pc["colorCode"] for pc in SEED["ProductColor"] if pc["productCode"] == product]
        return sorted(code for code in linked if COLORS[code]["active"])

    def test_c4_22_to_24_prd02_has_no_withdrawn(self):
        linked = [pc["colorCode"] for pc in SEED["ProductColor"] if pc["productCode"] == "PRD-02"]
        self.assertIn("BP1039", linked, "seed sanity: PRD-02 links the withdrawn BP1039")
        codes = self.product_codes("PRD-02")
        self.assertEqual(len(codes), 11)
        for sku in ("SKU-0201", "SKU-0202", "SKU-0203"):
            self.assert_list("/products/%s/colors?pageSize=50" % sku, codes, total=11, total_pages=1)

    def test_c4_25_prd02_page_2(self):
        codes = self.product_codes("PRD-02")
        self.assert_list("/products/SKU-0201/colors?page=2", codes[10:], total=11, total_pages=2)
        self.assertEqual(codes[10:], ["BP1011"])

    def test_c4_26_prd01_full(self):
        codes = self.product_codes("PRD-01")
        self.assertEqual(len(codes), 20)
        self.assert_list("/products/SKU-0101/colors?pageSize=50", codes, total=20, total_pages=1)


if __name__ == "__main__":
    unittest.main()
