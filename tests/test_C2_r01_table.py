"""R01 paging table: defaults, valid and invalid page / pageSize, combinations with filters,
the same rules on GET /products/{sku}/colors, and a walk over all pages (R01 + R02).
Data facts from the seed: 37 active colours; family blue = 5, black = 1;
SKU-0101 has 20 colours, SKU-0501 has 10, SKU-1201 has 0 (mixable, empty list)."""
import json
import os
import unittest
import urllib.error
import urllib.request

BASE = os.environ["COLORLAB_URL"].rstrip("/")
TOTAL = 37
LIST_KEYS = {"page", "pageSize", "total", "totalPages", "items"}


def call_raw(path):
    try:
        with urllib.request.urlopen(BASE + path) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")


def call(path):
    status, text = call_raw(path)
    return status, json.loads(text)


class Base(unittest.TestCase):

    def assert_list(self, path, page=None, size=None, items=None, total=None, total_pages=None):
        """A 200 list answer with the R02 envelope; checks only the values given."""
        status, body = call(path)
        self.assertEqual(status, 200, "%s should give 200, got %s: %s" % (path, status, body))
        self.assertTrue(LIST_KEYS <= set(body.keys()), "%s: envelope keys missing: %s" % (path, sorted(body.keys())))
        if page is not None:
            self.assertEqual(body["page"], page, "%s: page" % path)
        if size is not None:
            self.assertEqual(body["pageSize"], size, "%s: pageSize" % path)
        if items is not None:
            self.assertEqual(len(body["items"]), items, "%s: item count, got %d" % (path, len(body["items"])))
        if total is not None:
            self.assertEqual(body["total"], total, "%s: total" % path)
        if total_pages is not None:
            self.assertEqual(body["totalPages"], total_pages, "%s: totalPages" % path)
        self.assertLessEqual(len(body["items"]), body["pageSize"], "%s: more items than pageSize" % path)
        return body

    def assert_bad_parameter(self, path):
        status, body = call(path)
        self.assertEqual(status, 400, "%s should give 400, got %s: %s" % (path, status, body))
        self.assertEqual(body["error"]["code"], "BAD_PARAMETER", "%s: %s" % (path, body))


class TestR01Defaults(Base):

    def test_r01_01_no_params(self):
        self.assert_list("/colors", page=1, size=10, items=10)

    def test_r01_02_only_page(self):
        self.assert_list("/colors?page=2", page=2, size=10, items=10)

    def test_r01_03_only_page_size(self):
        self.assert_list("/colors?pageSize=5", page=1, size=5, items=5)


class TestR01PageValid(Base):

    def test_r01_04_first_page(self):
        self.assert_list("/colors?page=1", items=10)

    def test_r01_05_last_full_page(self):
        self.assert_list("/colors?page=3", items=10)

    def test_r01_06_last_partial_page(self):
        self.assert_list("/colors?page=4", items=7)

    def test_r01_07_just_past_the_end(self):
        self.assert_list("/colors?page=5", items=0)

    def test_r01_08_far_past_the_end(self):
        self.assert_list("/colors?page=1000", items=0)

    def test_r01_09_huge_page_number_never_crashes(self):
        path = "/colors?page=99999999999999999999"
        status, text = call_raw(path)
        self.assertLess(status, 500, "%s must not crash: %s %s" % (path, status, text[:200]))
        if status == 200:
            self.assertEqual(json.loads(text)["items"], [], "%s: items must be empty" % path)


class TestR01PageInvalid(Base):

    def test_r01_12_large_negative(self):
        self.assert_bad_parameter("/colors?page=-999")

    def test_r01_15_decimal_point_zero(self):
        self.assert_bad_parameter("/colors?page=1.0")

    def test_r01_16_empty(self):
        self.assert_bad_parameter("/colors?page=")

    def test_r01_17_leading_space(self):
        self.assert_bad_parameter("/colors?page=%201")

    def test_r01_18_scientific_notation(self):
        self.assert_bad_parameter("/colors?page=1e1")


class TestR01PageSizeValid(Base):

    def test_r01_19_lower_bound(self):
        self.assert_list("/colors?pageSize=1", items=1, total_pages=37)

    def test_r01_20_just_above_lower_bound(self):
        self.assert_list("/colors?pageSize=2", items=2, total_pages=19)

    def test_r01_21_just_below_upper_bound(self):
        self.assert_list("/colors?pageSize=49", items=TOTAL, total_pages=1)

    def test_r01_22_upper_bound(self):
        self.assert_list("/colors?pageSize=50", items=TOTAL, total_pages=1)

    def test_r01_23_exactly_the_total(self):
        self.assert_list("/colors?pageSize=37", items=TOTAL, total_pages=1)

    def test_r01_24_one_less_than_the_total(self):
        self.assert_list("/colors?pageSize=36&page=2", items=1, total_pages=2)


class TestR01PageSizeInvalid(Base):

    def test_r01_27_far_above_upper_bound(self):
        self.assert_bad_parameter("/colors?pageSize=100")

    def test_r01_28_huge_number(self):
        self.assert_bad_parameter("/colors?pageSize=99999999999999999999")

    def test_r01_31_decimal(self):
        self.assert_bad_parameter("/colors?pageSize=10.5")

    def test_r01_32_empty(self):
        self.assert_bad_parameter("/colors?pageSize=")


class TestR01Combinations(Base):

    def test_r01_33_both_valid(self):
        self.assert_list("/colors?page=2&pageSize=20", items=17)

    def test_r01_34_valid_page_bad_size(self):
        self.assert_bad_parameter("/colors?page=1&pageSize=51")

    def test_r01_35_bad_page_valid_size(self):
        self.assert_bad_parameter("/colors?page=0&pageSize=10")

    def test_r01_36_both_bad(self):
        self.assert_bad_parameter("/colors?page=0&pageSize=0")

    def test_r01_37_paging_with_filter(self):
        self.assert_list("/colors?family=blue&page=1&pageSize=2", items=2)

    def test_r01_38_paging_with_filter_past_the_end(self):
        self.assert_list("/colors?family=black&page=2", items=0)

    def test_r01_39_paging_with_bad_filter(self):
        self.assert_bad_parameter("/colors?family=Blue&page=1")


class TestR01ProductColors(Base):

    def test_r01_40_default(self):
        self.assert_list("/products/SKU-0101/colors", page=1, size=10, items=10)

    def test_r01_41_exact_multiple_last_page(self):
        self.assert_list("/products/SKU-0101/colors?page=2", items=10, total_pages=2)

    def test_r01_42_exact_multiple_past_the_end(self):
        self.assert_list("/products/SKU-0101/colors?page=3", items=0)

    def test_r01_43_exactly_one_full_page(self):
        self.assert_list("/products/SKU-0501/colors", items=10, total_pages=1)

    def test_r01_44_then_empty(self):
        self.assert_list("/products/SKU-0501/colors?page=2", items=0)

    def test_r01_45_lower_bound_page_size(self):
        self.assert_list("/products/SKU-0101/colors?pageSize=1", items=1, total_pages=20)

    def test_r01_46_upper_bound_page_size(self):
        self.assert_list("/products/SKU-0101/colors?pageSize=50", items=20, total_pages=1)

    def test_r01_47_page_zero(self):
        self.assert_bad_parameter("/products/SKU-0101/colors?page=0")

    def test_r01_48_page_negative(self):
        self.assert_bad_parameter("/products/SKU-0101/colors?page=-1")

    def test_r01_49_page_text(self):
        self.assert_bad_parameter("/products/SKU-0101/colors?page=abc")

    def test_r01_50_page_size_zero(self):
        self.assert_bad_parameter("/products/SKU-0101/colors?pageSize=0")

    def test_r01_51_page_size_51(self):
        self.assert_bad_parameter("/products/SKU-0101/colors?pageSize=51")

    def test_r01_52_page_size_text(self):
        self.assert_bad_parameter("/products/SKU-0101/colors?pageSize=abc")

    def test_r01_53_empty_list_page_1(self):
        self.assert_list("/products/SKU-1201/colors", items=0, total=0, total_pages=0)

    def test_r01_54_empty_list_page_2(self):
        self.assert_list("/products/SKU-1201/colors?page=2", items=0)

    def test_r01_55_empty_list_bad_page_size(self):
        self.assert_bad_parameter("/products/SKU-1201/colors?pageSize=0")


class TestR01WalkAllPages(Base):

    def walk(self, size):
        """Read every page for one page size. Returns the list of codes seen, in order."""
        codes = []
        page = 1
        while True:
            body = self.assert_list("/colors?page=%d&pageSize=%d" % (page, size), page=page, size=size)
            self.assertEqual(body["total"], TOTAL, "pageSize %d page %d: total" % (size, page))
            if not body["items"]:
                self.assertGreater(page, body["totalPages"], "pageSize %d: empty page %d inside totalPages %d"
                                   % (size, page, body["totalPages"]))
                break
            self.assertLessEqual(page, body["totalPages"], "pageSize %d: page %d holds items past totalPages %d"
                                 % (size, page, body["totalPages"]))
            codes.extend(item["code"] for item in body["items"])
            page += 1
            self.assertLess(page, 200, "pageSize %d: walk does not end" % size)
        return codes

    def test_r01_56_every_page_size_gives_every_colour_once(self):
        for size in range(1, 51):
            codes = self.walk(size)
            self.assertEqual(len(codes), TOTAL, "pageSize %d: saw %d codes, want %d" % (size, len(codes), TOTAL))
            self.assertEqual(len(set(codes)), TOTAL, "pageSize %d: repeated codes" % size)

    def test_r01_57_page_size_7(self):
        for page in range(1, 6):
            self.assert_list("/colors?page=%d&pageSize=7" % page, items=7, total_pages=6)
        self.assert_list("/colors?page=6&pageSize=7", items=2, total_pages=6)
        self.assert_list("/colors?page=7&pageSize=7", items=0, total_pages=6)


if __name__ == "__main__":
    unittest.main()
