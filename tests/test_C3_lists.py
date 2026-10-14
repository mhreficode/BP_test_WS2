"""C3 / R02, R08, R10: lists and search, one promise per test.

R02: every list answers with page, pageSize, total, totalPages, items.
     total counts all matches, totalPages is total divided by page size rounded
     up (0 when total is 0), a page never holds more than pageSize items, and
     reading all pages gives every match once: no gaps, no repeats.
R08: the colour list of a product is sorted by code ascending and holds only
     active colours.
R10: q matches the name ignoring upper/lower case, accents must match, family
     must match exactly, both together mean AND, results sorted by code.

The seed file is the truth for the values.
"""
import json
import os
import unittest
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")
FIELDS = ["code", "name", "hex", "family", "formulaCode"]

with open("app/seed/seed.json", encoding="utf-8") as fh:
    SEED = json.load(fh)

MASTER = {c["code"]: {f: c[f] for f in FIELDS} for c in SEED["Color"]}
ACTIVE = sorted(c["code"] for c in SEED["Color"] if c["active"])
NAME = {c["code"]: c["name"] for c in SEED["Color"]}
FAMILY = {c["code"]: c["family"] for c in SEED["Color"]}
FAMILIES = sorted({c["family"] for c in SEED["Color"]})
MIXABLE = {p["productCode"] for p in SEED["Product"] if p["mixable"]}
MIX_SKUS = sorted(s["sku"] for s in SEED["Sku"] if s["productCode"] in MIXABLE)
BY_SKU = {s["sku"]: s["productCode"] for s in SEED["Sku"]}


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8") or "{}")


def ceil_div(total, size):
    return (total + size - 1) // size


def expected_search(text=None, family=None):
    """R10 worked out from the seed: substring, case ignored, accents kept."""
    hits = []
    for code in ACTIVE:
        if family is not None and FAMILY[code] != family:
            continue
        if text is not None and text.lower() not in NAME[code].lower():
            continue
        hits.append(code)
    return sorted(hits)


class EnvelopeOfTheColourList(unittest.TestCase):
    def test_r02_total_counts_every_active_colour(self):
        status, body = get("/colors?pageSize=1")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("total"), len(ACTIVE))

    def test_r02_total_pages_is_rounded_up(self):
        wrong = []
        for size in (1, 2, 3, 7, 10, 49, 50):
            status, body = get("/colors?pageSize=%d" % size)
            want = ceil_div(len(ACTIVE), size)
            if status != 200 or body.get("totalPages") != want:
                wrong.append((size, status, body.get("totalPages"), want))
        self.assertEqual(wrong, [])

    def test_r02_page_and_page_size_are_echoed(self):
        wrong = []
        for page, size in ((1, 10), (2, 5), (3, 7), (1, 50)):
            status, body = get("/colors?page=%d&pageSize=%d" % (page, size))
            if status != 200 or (body.get("page"), body.get("pageSize")) != (page, size):
                wrong.append((page, size, status, body.get("page"), body.get("pageSize")))
        self.assertEqual(wrong, [])

    def test_r02_page_never_holds_more_than_page_size(self):
        wrong = []
        for size in (1, 3, 7, 10, 50):
            for page in range(1, ceil_div(len(ACTIVE), size) + 1):
                status, body = get("/colors?page=%d&pageSize=%d" % (page, size))
                count = len(body.get("items", [])) if status == 200 else -1
                if count > size:
                    wrong.append((page, size, count))
        self.assertEqual(wrong, [])

    def test_r02_each_page_holds_the_right_number(self):
        wrong = []
        total = len(ACTIVE)
        for size in (1, 3, 7, 10):
            for page in range(1, ceil_div(total, size) + 1):
                status, body = get("/colors?page=%d&pageSize=%d" % (page, size))
                want = min(size, total - (page - 1) * size)
                got = len(body.get("items", [])) if status == 200 else -1
                if got != want:
                    wrong.append((page, size, got, want))
        self.assertEqual(wrong, [])

    def test_r01_page_past_the_end_is_200_and_empty(self):
        last = ceil_div(len(ACTIVE), 10)
        wrong = []
        for page in (last + 1, last + 5, 999):
            status, body = get("/colors?page=%d&pageSize=10" % page)
            if status != 200 or body.get("items") != []:
                wrong.append((page, status, body.get("items")))
        self.assertEqual(wrong, [])


class WalkingEveryPage(unittest.TestCase):
    def pages(self, size, query=""):
        seen, page = [], 1
        while True:
            status, body = get("/colors?page=%d&pageSize=%d%s" % (page, size, query))
            if status != 200:
                return status, seen
            seen += [i.get("code") for i in body.get("items", [])]
            if page >= body.get("totalPages", 0):
                return status, seen
            page += 1
            if page > 500:
                return status, seen

    def test_r02_no_gaps_and_no_repeats(self):
        wrong = []
        for size in (1, 2, 3, 7, 10, 50):
            status, codes = self.pages(size)
            if status != 200:
                wrong.append((size, "status", status))
            elif sorted(codes) != ACTIVE:
                missing = sorted(set(ACTIVE) - set(codes))
                extra = sorted(c for c in codes if codes.count(c) > 1)
                wrong.append((size, "missing", missing, "repeated", sorted(set(extra))))
        self.assertEqual(wrong, [])

    def test_r10_whole_list_is_sorted_by_code(self):
        wrong = []
        for size in (1, 3, 10, 50):
            _, codes = self.pages(size)
            if codes != sorted(codes):
                wrong.append((size, codes))
        self.assertEqual(wrong, [])


class SearchAndFamily(unittest.TestCase):
    def codes_of(self, query):
        status, body = get("/colors?pageSize=50&" + query)
        if status != 200:
            return status, []
        return status, [i.get("code") for i in body.get("items", [])]

    def test_r10_family_filter_matches_the_seed(self):
        wrong = []
        for family in FAMILIES:
            status, codes = self.codes_of("family=" + family)
            want = expected_search(family=family)
            if status != 200 or sorted(codes) != want:
                wrong.append((family, status, sorted(codes), want))
        self.assertEqual(wrong, [])

    def test_r02_family_total_counts_all_matches(self):
        wrong = []
        for family in FAMILIES:
            status, body = get("/colors?pageSize=1&family=" + family)
            want = len(expected_search(family=family))
            if status != 200 or body.get("total") != want:
                wrong.append((family, status, body.get("total"), want))
        self.assertEqual(wrong, [])

    def test_r10_search_text_matches_the_seed(self):
        wrong = []
        for text in ("wit", "blauw", "grijs", "groen", "e", "a", "zz"):
            status, codes = self.codes_of("q=" + urllib.parse.quote(text))
            want = expected_search(text=text)
            if status != 200 or sorted(codes) != want:
                wrong.append((text, status, sorted(codes), want))
        self.assertEqual(wrong, [])

    def test_r10_search_ignores_upper_and_lower_case(self):
        wrong = []
        for text in ("wit", "WIT", "Wit", "wIt"):
            status, codes = self.codes_of("q=" + urllib.parse.quote(text))
            want = expected_search(text="wit")
            if status != 200 or sorted(codes) != want:
                wrong.append((text, status, sorted(codes), want))
        self.assertEqual(wrong, [])

    def test_r10_accents_must_match(self):
        # A name with an accent is only found with that accent.
        accented = [c for c in ACTIVE if any(ch in NAME[c] for ch in "àâäéèêëîïôöùûüç")]
        wrong = []
        for code in accented:
            name = NAME[code]
            plain = name
            for fancy, flat in (("à", "a"), ("â", "a"), ("ä", "a"), ("é", "e"), ("è", "e"),
                                ("ê", "e"), ("ë", "e"), ("î", "i"), ("ï", "i"), ("ô", "o"),
                                ("ö", "o"), ("ù", "u"), ("û", "u"), ("ü", "u"), ("ç", "c")):
                plain = plain.replace(fancy, flat)
            status, codes = self.codes_of("q=" + urllib.parse.quote(plain))
            if status != 200 or code in codes:
                wrong.append((name, plain, status, codes))
        self.assertEqual(wrong, [])

    def test_r10_text_and_family_together_mean_and(self):
        wrong = []
        for text, family in (("wit", "white"), ("a", "blue"), ("e", "grey"), ("blauw", "red")):
            status, codes = self.codes_of(
                "q=%s&family=%s" % (urllib.parse.quote(text), family))
            want = expected_search(text=text, family=family)
            if status != 200 or sorted(codes) != want:
                wrong.append((text, family, status, sorted(codes), want))
        self.assertEqual(wrong, [])

    def test_r10_search_results_are_sorted_by_code(self):
        wrong = []
        for text in ("wit", "a", "e", "blauw"):
            status, codes = self.codes_of("q=" + urllib.parse.quote(text))
            if status == 200 and codes != sorted(codes):
                wrong.append((text, codes))
        self.assertEqual(wrong, [])

    def test_r02_empty_result_has_total_zero_and_no_pages(self):
        status, body = get("/colors?q=zzzzzzzz")
        self.assertEqual(status, 200)
        self.assertEqual((body.get("total"), body.get("totalPages"), body.get("items")),
                         (0, 0, []))


class ProductLists(unittest.TestCase):
    def expected(self, sku):
        product = BY_SKU[sku]
        return sorted({pc["colorCode"] for pc in SEED["ProductColor"]
                       if pc["productCode"] == product} & set(ACTIVE))

    def test_r08_product_list_holds_the_active_colours(self):
        wrong = []
        for sku in MIX_SKUS:
            status, body = get("/products/%s/colors?pageSize=50" % sku)
            codes = sorted(i.get("code") for i in body.get("items", [])) if status == 200 else []
            if status != 200 or codes != self.expected(sku):
                wrong.append((sku, status, codes, self.expected(sku)))
        self.assertEqual(wrong, [])

    def test_r08_product_list_is_sorted_by_code(self):
        wrong = []
        for sku in MIX_SKUS:
            status, body = get("/products/%s/colors?pageSize=50" % sku)
            codes = [i.get("code") for i in body.get("items", [])] if status == 200 else []
            if codes != sorted(codes):
                wrong.append((sku, codes))
        self.assertEqual(wrong, [])

    def test_r02_product_list_envelope_counts(self):
        wrong = []
        for sku in MIX_SKUS:
            want = len(self.expected(sku))
            for size in (1, 3, 50):
                status, body = get("/products/%s?pageSize=%d" % (sku + "/colors", size))
                if status != 200:
                    wrong.append((sku, size, "status", status))
                    continue
                if body.get("total") != want:
                    wrong.append((sku, size, "total", body.get("total"), want))
                if body.get("totalPages") != ceil_div(want, size):
                    wrong.append((sku, size, "totalPages", body.get("totalPages"),
                                  ceil_div(want, size)))
        self.assertEqual(wrong, [])

    def test_r02_product_pages_hold_every_colour_once(self):
        wrong = []
        for sku in MIX_SKUS:
            for size in (1, 3):
                seen, page = [], 1
                while True:
                    status, body = get("/products/%s/colors?page=%d&pageSize=%d"
                                       % (sku, page, size))
                    if status != 200:
                        wrong.append((sku, size, "status", status))
                        break
                    seen += [i.get("code") for i in body.get("items", [])]
                    if page >= body.get("totalPages", 0):
                        break
                    page += 1
                    if page > 200:
                        break
                if sorted(seen) != self.expected(sku):
                    wrong.append((sku, size, sorted(seen), self.expected(sku)))
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
