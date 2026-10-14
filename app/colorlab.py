#!/usr/bin/env python3
"""colorlab: a local mock of BossP.Api.Color for the BossP workshop.

Mirror of BossP.Api.Color; the real one is .NET. Python 3.9+, standard library only.
Not a real service: no auth, no versions, no outbound calls. Everything is local.

File layout (top to bottom, the order of the customer's diagram):
    SETTINGS            environment variables
    LAYER 1 API         class BossPApiColor: the only network boundary (HTTP listener below)
    LAYER 2 LIBS        six libs, one per topic; they read the store only
    LAYER 3 DATA STORE  class Store: in-memory, document style, database BossPBusiness
    LAYER 4 SOURCES     FO_EXPORT, INNOVATINT_FORMULAS and sync_merge() (the Sync step)
    HTTP LISTENER       ThreadingHTTPServer glue and the request log
    COMMAND LINE        --precheck, --dump-seed, server start

Run:  python3 colorlab.py            (Windows: py colorlab.py)
Check: python3 colorlab.py --precheck
Rules are described in rules.md.

Code between "# >>> ZONE Cn" and "# <<< ZONE Cn" belongs to one workshop topic (C1 to C6).
Zones never overlap. The workshop tool arena/arena.py edits and checks them.
"""
import argparse
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote

VERSION = "1.0.0"
SEED_VERSION = "2026.10.1"
DB_NAME = "BossPBusiness"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


# =====================================================================================
# SETTINGS
# =====================================================================================

class ConfigError(Exception):
    """Bad environment value: the process exits with code 2."""


class Settings(object):
    """Switches of one run. admin=False hides the two lab helpers (reset, withdraw)."""

    def __init__(self, admin=True):
        self.admin = admin

    def health(self):
        return {"status": "ok", "version": VERSION, "seedVersion": SEED_VERSION}


def settings_from_env(env):
    """Build Settings from environment variables. Raises ConfigError (exit code 2)."""
    admin = env.get("COLORLAB_ADMIN", "on").strip().lower() != "off"
    return Settings(admin=admin)


# =====================================================================================
# LAYER 1 API  (BossP.Api.Color, App Service .NET in the real world)
# "Serves colours, cards and mixable products to web shops and apps."
# Role: checks input, applies rules via libs. Rules here: R01, R02, R03, R09.
# =====================================================================================

class ApiError(Exception):
    def __init__(self, status, code, message):
        Exception.__init__(self, message)
        self.status = status
        self.code = code
        self.message = message


# >>> ZONE C2
# Topic C2, bad input: what the API refuses, and how it matches a request to an endpoint.
# Rules R01 (paging bounds), R03 (identifier and parameter checks), R09 (unknown path).

FAMILIES = ("white", "grey", "black", "blue", "green", "yellow",
            "orange", "red", "pink", "purple", "brown")

RE_COLOR = re.compile(r"^BP[0-9]{4}\Z", re.IGNORECASE)
RE_SKU = re.compile(r"^SKU-[0-9]{4}\Z")
RE_CARD = re.compile(r"^CARD-[0-9]{2}\Z")
RE_INT = re.compile(r"^-?[0-9]+$")

ROUTES = (
    ("E01", "GET", re.compile(r"^/health$")),
    ("E02", "POST", re.compile(r"^/admin/reset$")),
    ("E03", "GET", re.compile(r"^/colors/([^/]+)$")),
    ("E04", "GET", re.compile(r"^/colors$")),
    ("E05", "GET", re.compile(r"^/products/([^/]+)/colors$")),
    ("E06", "GET", re.compile(r"^/cards/([^/]+)$")),
    ("E07", "POST", re.compile(r"^/admin/colors/([^/]+)/withdraw$")),
)


def c2_check_input(kind, value):
    """R03: refuse a bad identifier or parameter before any lookup."""
    if kind == "code":
        if not RE_COLOR.match(value):
            raise ApiError(400, "INVALID_CODE", "Colour code must be BP and 4 digits")
    elif kind == "sku":
        if not RE_SKU.match(value):
            raise ApiError(400, "INVALID_SKU", "SKU must be SKU- and 4 digits")
    elif kind == "card":
        if not RE_CARD.match(value):
            raise ApiError(400, "INVALID_CARD", "Card id must be CARD- and 2 digits")
    elif kind == "family":
        if value not in FAMILIES:
            raise ApiError(400, "BAD_PARAMETER", "family must be one of the 11 family names")
    elif kind == "q":
        if len(value) < 1 or len(value) > 64:
            raise ApiError(400, "BAD_PARAMETER", "q must be 1 to 64 characters")
    return value


def c2_parse_paging(params):
    """R01: page starts at 1 (default 1), pageSize is 1 to 50 (default 10)."""
    page, size = 1, 10
    if "page" in params:
        if not RE_INT.match(params["page"]) or int(params["page"]) < 1:
            raise ApiError(400, "BAD_PARAMETER", "page must be an integer, 1 or more")
        page = int(params["page"])
    if "pageSize" in params:
        raw = params["pageSize"]
        if not RE_INT.match(raw) or int(raw) < 1:
            raise ApiError(400, "BAD_PARAMETER", "pageSize must be an integer, 1 to 50")
        size = int(raw)
        if size > 50:
            raise ApiError(400, "BAD_PARAMETER", "pageSize must be an integer, 1 to 50")
    return page, size


def c2_route(method, path, admin):
    """Match method and path. Returns (endpoint id, captured segments)."""
    wrong_method = False
    for endpoint, verb, pattern in ROUTES:
        hit = pattern.match(path)
        if not hit:
            continue
        if endpoint in ("E02", "E07") and not admin:
            raise ApiError(404, "NOT_FOUND", "Path %s not found" % path)
        if verb != method:
            wrong_method = True
            continue
        return endpoint, [unquote(g) for g in hit.groups()]
    if wrong_method:
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Method %s not allowed here" % method)
    raise ApiError(404, "NOT_FOUND", "Path %s not found" % path)
# <<< ZONE C2


# >>> ZONE C5
# Topic C5, keep the promise: the error body, the status for each failure, and the
# field names and types of the card and product answers, as written in openapi/color-v1.yaml.
# Rules R09 (error shape, 404), R06 (card header), R07 (409).

def c5_error_body(code, message):
    """R09: every error has the same body."""
    return {"error": {"code": code, "message": message}}


def c5_map_error(exc):
    """Turn a failure into (status, error code, message)."""
    if isinstance(exc, ApiError):
        return exc.status, exc.code, exc.message
    if isinstance(exc, NotFound):
        return 404, "NOT_FOUND", str(exc)
    if isinstance(exc, Withdrawn):
        return 410, "COLOR_WITHDRAWN", str(exc)
    if isinstance(exc, NotMixable):
        return 409, "NOT_MIXABLE", str(exc)
    return 500, "INTERNAL", "Internal error"


def c5_card_head(card, count):
    """The card answer without its colours: id, name, year, sku, colorCount."""
    return {
        "cardId": card["cardId"],
        "name": card["name"],
        "year": card["year"],
        "sku": card["sku"],
        "colorCount": count,
    }


def c5_product_view(doc):
    """The product block of the product colour list."""
    return {"code": doc["productCode"], "name": doc["name"], "mixable": doc["mixable"]}
# <<< ZONE C5


class BossPApiColor(object):
    """Mirror of BossP.Api.Color; the real one is .NET. The only network boundary."""

    def __init__(self, store, settings):
        self.store = store
        self.s = settings
        self.colors = LibColor(store)
        self.product_colors = LibProductColor(store)
        self.cards = LibSkuColorCard(store)
        self.products = LibProduct(store)
        self.skus = LibSku(store)
        self.maakbaar = LibProductMaakbaar(store)

    # ---- entry point: (method, request target) -> (status, JSON-able body) ----------
    def handle(self, method, target):
        path, _, query = target.partition("#")[0].partition("?")
        try:
            endpoint, args = self.route(method, path)
            params = {}
            for key, value in parse_qsl(query, keep_blank_values=True):
                params.setdefault(key, value)
            if endpoint == "E01":
                return 200, self.s.health()
            if endpoint == "E02":
                self.store.reset()
                return 200, c6_reset_answer(self.store.counts())
            if endpoint == "E03":
                return 200, self.get_color(args[0])
            if endpoint == "E04":
                return 200, self.list_colors(params)
            if endpoint == "E05":
                return 200, self.list_product_colors(args[0], params)
            if endpoint == "E06":
                return 200, self.get_card(args[0])
            return 200, self.withdraw(args[0])
        except Exception as exc:
            status, code, message = c5_map_error(exc)
            return status, c5_error_body(code, message)

    def route(self, method, path):
        return c2_route(method, path, self.s.admin)

    def check_input(self, kind, value):
        return c2_check_input(kind, value)

    # ---- endpoints -------------------------------------------------------------------
    def get_color(self, raw_code):
        self.check_input("code", raw_code)
        return self.colors.get(raw_code)

    def list_colors(self, params):
        page, size = c2_parse_paging(params)
        family = params.get("family")
        if family is not None:
            self.check_input("family", family)
        text = params.get("q")
        if text is not None:
            self.check_input("q", text)
        return c3_envelope(self.colors.search(text, family), page, size)

    def list_product_colors(self, raw_sku, params):
        sku = self.check_input("sku", raw_sku)
        page, size = c2_parse_paging(params)
        product = self.products.get(self.skus.product_code(sku))
        self.maakbaar.require_mixable(product)
        rows = self.product_colors.for_product(product["code"])
        out = {"sku": sku, "product": product}
        out.update(c3_envelope(rows, page, size))
        return out

    def get_card(self, raw_card):
        return self.cards.get(self.check_input("card", raw_card))

    def withdraw(self, raw_code):
        """Lab helper (E07): simulates a Sync run that withdraws a colour."""
        code = self.check_input("code", raw_code).upper()
        changed = self.store.withdraw(code)
        return {"code": code, "active": changed["active"]}


# =====================================================================================
# LAYER 2 LIBS  "Reusable groups of functions, one per topic. They fetch the data."
# Rules here: R04, R05, R06, R07, R08, R10. Libs read the store only.
# =====================================================================================

class LibError(Exception):
    pass


class NotFound(LibError):
    pass


class Withdrawn(LibError):
    pass


class NotMixable(LibError):
    pass


# >>> ZONE C1
# Topic C1, right answers: the values in the colour answer. Rule R04.

def c1_lookup_key(code):
    """The code is found whatever its case: the store keeps upper case."""
    return code.upper()


def c1_serve_color(doc):
    """R04: a colour as served. Internal fields (_id, _sync) never leave the lib."""
    return {
        "code": doc["code"],
        "name": doc["name"],
        "hex": doc.get("hex"),
        "family": doc["family"],
        "formulaCode": doc["formulaCode"],
    }
# <<< ZONE C1


# >>> ZONE C3
# Topic C3, lists and search: the filter, the order and the paging maths of every list.
# Rules R02 (envelope and totals), R08 (order), R10 (search).

def c3_sort_codes(docs):
    """Lists are sorted by colour code, ascending."""
    return sorted(docs, key=lambda d: d["code"])


def c3_search(docs, q, family):
    """R10: name contains q (accents must match), family exact, both together mean AND."""
    rows = []
    for doc in docs:
        if family is not None and doc["family"] != family:
            continue
        if q is not None and q.lower() not in doc["name"].lower():
            continue
        rows.append(doc)
    return rows


def c3_envelope(rows, page, size):
    """R02: page, pageSize, total, totalPages and the items of the page."""
    total = len(rows)
    pages = -(-total // size)
    offset = (page - 1) * size
    return {"page": page, "pageSize": size, "total": total, "totalPages": pages,
            "items": rows[offset:offset + size]}
# <<< ZONE C3


# >>> ZONE C4
# Topic C4, withdraw and mixable rules: who is offered, who is refused, how a card is ordered.
# Rules R05 (withdrawn), R06 (card order and count), R07 (mixable).

def c4_only_active(docs):
    """R05: a withdrawn colour is never offered in a list."""
    return [d for d in docs if d["active"]]


def c4_require_active(doc, code):
    """R05: asking for a withdrawn colour directly is refused (410)."""
    if not doc["active"]:
        raise Withdrawn("Colour %s is withdrawn" % code)


def c4_withdraw_doc(doc):
    """What the Sync step does to a withdrawn colour: a copy that is not active."""
    changed = dict(doc)
    changed["active"] = False
    return changed


def c4_require_mixable(product):
    """R07: only mixable products have a colour list."""
    if not product["mixable"]:
        raise NotMixable("Product %s is not mixable" % product["code"])


def c4_card_entries(card):
    """R06: the colours of a card in the order of position."""
    return sorted(card["colors"], key=lambda c: c["position"])


def c4_card_count(entries):
    """R06: colorCount is the number of colours listed."""
    return len(entries)
# <<< ZONE C4


class LibBase(object):
    def __init__(self, store):
        self.store = store


class LibColor(LibBase):
    """Lib Color: lookup, withdrawn handling, search, faithful colour data."""

    def active(self):
        """R05: active colour documents, sorted by code."""
        docs = c4_only_active(self.store.collection("Color").values())
        return c3_sort_codes(docs)

    def get(self, code):
        """R04 + R05: one colour by code, found whatever its case."""
        doc = self.store.collection("Color").get(c1_lookup_key(code))
        if doc is None:
            raise NotFound("Colour %s not found" % code)
        c4_require_active(doc, code)
        return c1_serve_color(doc)

    def search(self, q, family):
        """R10: search over the active colours."""
        return [c1_serve_color(d) for d in c3_search(self.active(), q, family)]


class LibProductColor(LibBase):
    """Lib ProductColor: colour links of a product, sorted, active only (R08)."""

    def for_product(self, product_code):
        colors = self.store.collection("Color")
        codes = [d["colorCode"] for d in self.store.collection("ProductColor").values()
                 if d["productCode"] == product_code]
        docs = [colors[c] for c in codes if c in colors]
        return [c1_serve_color(d) for d in c3_sort_codes(c4_only_active(docs))]


class LibSkuColorCard(LibBase):
    """Lib SkuColorCard: colour cards, order, hex format (R06)."""

    def get(self, card_id):
        card = self.store.collection("SkuColorCard").get(card_id)
        if card is None:
            raise NotFound("Card %s not found" % card_id)
        colors = self.store.collection("Color")
        out = []
        for entry in c4_card_entries(card):
            doc = colors[entry["colorCode"]]
            out.append({"position": entry["position"], "code": doc["code"],
                        "name": doc["name"], "hex": c6_card_hex(doc.get("hex"))})
        body = c5_card_head(card, c4_card_count(out))
        body["colors"] = out
        return body


class LibProduct(LibBase):
    """Lib Product: product by code. No own rule; used by E05."""

    def get(self, product_code):
        doc = self.store.collection("Product").get(product_code)
        if doc is None:
            raise NotFound("Product %s not found" % product_code)
        return c5_product_view(doc)


class LibSku(LibBase):
    """Lib Sku: SKU to product code. No own rule; used by E05 and E06."""

    def product_code(self, sku):
        doc = self.store.collection("Sku").get(sku)
        if doc is None:
            raise NotFound("SKU %s not found" % sku)
        return doc["productCode"]


class LibProductMaakbaar(LibBase):
    """Lib ProductMaakbaar: 'maakbaar' = can be made to order by mixing (R07)."""

    def require_mixable(self, product):
        c4_require_mixable(product)


# =====================================================================================
# LAYER 3 DATA STORE  "MongoDB BossPBusiness: Color, ProductColor, SkuColorCard, Sku ..."
# In-memory, document style. Collection Product is the diagram's "..." (assumption).
# =====================================================================================

COLLECTION_ORDER = ("Color", "Product", "Sku", "ProductColor", "SkuColorCard")


class Store(object):
    name = DB_NAME

    def __init__(self, collections):
        self._lock = threading.Lock()
        self._db = collections

    @classmethod
    def from_seed(cls):
        """Run the Sync step and load its output."""
        return cls(sync_merge())

    def collection(self, name):
        return self._db[name]

    def counts(self):
        return dict((n, len(self._db[n])) for n in COLLECTION_ORDER)

    def reset(self):
        fresh = sync_merge()
        with self._lock:
            self._db = c6_reset_db(self._db, fresh)

    def withdraw(self, code):
        with self._lock:
            doc = self._db["Color"].get(code)
            if doc is None:
                raise NotFound("Colour %s not found" % code)
            changed = c4_withdraw_doc(doc)
            self._db["Color"][code] = changed
            return changed

    def dump(self):
        return dict((n, list(self._db[n].values())) for n in COLLECTION_ORDER)


# =====================================================================================
# LAYER 4 DATA SOURCES  "Synapse Link, F&O export" and "Innovatint, colour formulas"
# "BossP.Api.Sync merges it into MongoDB." Fixed tables, no random, no clock.
# =====================================================================================

def _rng(first, last):
    return ["BP%04d" % n for n in range(first, last + 1)]


# --- FO_EXPORT: colours (code, name, family, active) -------------------------------
FO_COLORS = [
    ("BP1001", "Wit Gebroken", "white", True),
    ("BP1002", "Sneeuwwit", "white", True),
    ("BP1003", "Crèmewit", "white", True),
    ("BP1004", "Parelgrijs", "grey", True),
    ("BP1005", "Lichtgrijs", "grey", True),
    ("BP1006", "Betongrijs", "grey", True),
    ("BP1007", "Antraciet", "grey", True),
    ("BP1008", "Gitzwart", "black", True),
    ("BP1009", "Delfts Blauw", "blue", True),
    ("BP1010", "Hemelsblauw", "blue", True),
    ("BP1011", "Zeeblauw", "blue", True),
    ("BP1012", "Marineblauw", "blue", True),
    ("BP1013", "Mosgroen", "green", True),
    ("BP1014", "Bosgroen", "green", True),
    ("BP1015", "Saliegroen", "green", True),
    ("BP1016", "Appelgroen", "green", True),
    ("BP1017", "Zonnegeel", "yellow", True),
    ("BP1018", "Maisgeel", "yellow", True),
    ("BP1019", "Okergeel", "yellow", True),
    ("BP1020", "Oranje Nassau", "orange", True),
    ("BP1021", "Terracotta", "orange", True),
    ("BP1022", "Baksteenrood", "red", True),
    ("BP1023", "Kersenrood", "red", True),
    ("BP1024", "Bordeaux", "red", True),
    ("BP1025", "Flamingoroze", "pink", True),
    ("BP1026", "Oudroze", "pink", True),
    ("BP1027", "Lavendel", "purple", True),
    ("BP1028", "Aubergine", "purple", True),
    ("BP1029", "Zand", "brown", True),
    ("BP1030", "Taupe", "brown", True),
    ("BP1031", "Walnoot", "brown", True),
    ("BP1032", "Koffiebruin", "brown", True),
    ("BP1033", "Linnen", "white", True),
    ("BP1034", "Kiezelgrijs", "grey", True),
    ("BP1035", "Leigrijs", "grey", True),
    ("BP1036", "Petrolblauw", "blue", True),
    ("BP1037", "Munt", "green", True),
    ("BP1038", "Olijfgroen", "green", False),
    ("BP1039", "Kanariegeel", "yellow", False),
    ("BP1040", "Café Crème", "brown", False),
]

# --- INNOVATINT_FORMULAS: colour code -> hex (formula key is INN- + last 4 digits) ---
INNOVATINT_HEX = {
    "BP1001": "#F4F1E8", "BP1002": "#FAFAF7", "BP1003": "#F2EBD3", "BP1004": "#D8D8D4",
    "BP1005": "#C9CBCC", "BP1006": "#9A9C9B", "BP1007": "#3A3D40", "BP1008": "#0B0B0C",
    "BP1009": "#1F4E9C", "BP1010": "#8EC5E8", "BP1011": "#2A6F97", "BP1012": "#14213D",
    "BP1013": "#6B7F3A", "BP1014": "#2F5D3A", "BP1015": "#A9B99A", "BP1016": "#A8C66C",
    "BP1017": "#F6C928", "BP1018": "#F2D675", "BP1019": "#CC9A2B", "BP1020": "#F26B1D",
    "BP1021": "#C0643B", "BP1022": "#9C3D2E", "BP1023": "#B3122B", "BP1024": "#5E1224",
    "BP1025": "#F2A6B8", "BP1026": "#C48B9F", "BP1027": "#B7A6D6", "BP1028": "#4A2545",
    "BP1029": "#D9C7A0", "BP1030": "#8B7D6B", "BP1031": "#5C4033", "BP1032": "#3E2A21",
    "BP1033": "#E6DFCF", "BP1034": "#B1ADA3", "BP1035": "#5F6B73", "BP1036": "#0F5C6E",
    "BP1037": "#B8E0D2", "BP1038": "#7A7A2E", "BP1039": "#FFE135", "BP1040": "#C8A887",
}
INNOVATINT_FORMULAS = dict(
    (code, {"formulaKey": "INN-" + code[-4:], "hex": hexval})
    for code, hexval in INNOVATINT_HEX.items())

# --- FO_EXPORT: products (code, name, category, mixable, [(sku, litres), ...]) ----------
FO_PRODUCTS = [
    ("PRD-01", "Muurverf Extra Mat", "wall paint", True,
     [("SKU-0101", 1.0), ("SKU-0102", 2.5), ("SKU-0103", 10.0)]),
    ("PRD-02", "Muurverf Zijdeglans", "wall paint", True,
     [("SKU-0201", 1.0), ("SKU-0202", 2.5), ("SKU-0203", 10.0)]),
    ("PRD-03", "Plafondverf Wit", "ceiling paint", False,
     [("SKU-0301", 5.0), ("SKU-0302", 10.0)]),
    ("PRD-04", "Lak Hoogglans Binnen", "lacquer", True,
     [("SKU-0401", 0.75), ("SKU-0402", 2.5)]),
    ("PRD-05", "Lak Zijdeglans Buiten", "lacquer", True,
     [("SKU-0501", 0.75), ("SKU-0502", 2.5), ("SKU-0503", 5.0)]),
    ("PRD-06", "Gevelverf Weerbestendig", "facade paint", True,
     [("SKU-0601", 5.0), ("SKU-0602", 10.0)]),
    ("PRD-07", "Houtbeits Transparant", "wood stain", True,
     [("SKU-0701", 1.0), ("SKU-0702", 2.5)]),
    ("PRD-08", "Primer Hechtgrond", "primer", False,
     [("SKU-0801", 1.0), ("SKU-0802", 2.5), ("SKU-0803", 5.0)]),
    ("PRD-09", "Vloerverf Slijtvast", "floor paint", True,
     [("SKU-0901", 2.5), ("SKU-0902", 5.0)]),
    ("PRD-10", "Radiatorlak Wit", "lacquer", False,
     [("SKU-1001", 0.75), ("SKU-1002", 2.5)]),
    ("PRD-11", "Kalkverf Mineraal", "wall paint", True,
     [("SKU-1101", 2.5), ("SKU-1102", 5.0), ("SKU-1103", 10.0)]),
    ("PRD-12", "Lakspray Collectie 2027", "spray", True,
     [("SKU-1201", 0.4)]),
]

# --- FO_EXPORT: product to colour links ------------------------------------------------
FO_PRODUCT_COLORS = {
    "PRD-01": _rng(1001, 1020),
    "PRD-02": _rng(1001, 1011) + ["BP1039"],
    "PRD-04": ["BP1001", "BP1008", "BP1009", "BP1012", "BP1014", "BP1017", "BP1022", "BP1023"],
    "PRD-05": _rng(1004, 1008) + _rng(1011, 1015),
    "PRD-06": ["BP1004", "BP1005", "BP1006", "BP1013", "BP1014",
               "BP1021", "BP1022", "BP1029", "BP1030", "BP1031"],
    "PRD-07": ["BP1021", "BP1022", "BP1029", "BP1030", "BP1031", "BP1032"],
    "PRD-09": _rng(1004, 1008) + ["BP1035"],
    "PRD-11": ["BP1001", "BP1002", "BP1003", "BP1033", "BP1029", "BP1034"],
}

# --- FO_EXPORT: colour cards (id, name, year, sku, colour codes in position order) -----
FO_CARDS = [
    ("CARD-01", "Muur Collectie 2026", 2026, "SKU-0101", _rng(1001, 1012)),
    ("CARD-02", "Hout en Lak Essentials", 2026, "SKU-0401",
     ["BP1001", "BP1017", "BP1022", "BP1023", "BP1009", "BP1012", "BP1014", "BP1008"]),
    ("CARD-03", "Gevel Collectie 2026", 2026, "SKU-0601",
     ["BP1006", "BP1014", "BP1021", "BP1022", "BP1029", "BP1030"]),
]

SYNC_BATCH = "SYNC-2026-10-01-01"
SYNCED_AT = "2026-10-01T02:00:00Z"


def _sync(fo_key, innovatint_key=None):
    sources = ["fo"] if innovatint_key is None else ["fo", "innovatint"]
    return {"batchId": SYNC_BATCH, "sources": sources, "foKey": fo_key,
            "innovatintKey": innovatint_key, "syncedAt": SYNCED_AT}



# >>> ZONE C6
# Topic C6, release gate: what Sync writes, what a reset restores, and the formats the
# Storefront pact relies on (hex format, the X-Seed-Version header). Rules R04, R06.

def c6_color_doc(code, name, family, active, inn):
    """BossP.Api.Sync: one Color document from F&O (name, family, active) and Innovatint."""
    return {
        "_id": code,
        "code": code,
        "name": name,
        "hex": inn["hex"],
        "family": family,
        "active": active,
        "formulaCode": inn["formulaKey"],
        "_sync": _sync("FO-COL-" + code[-4:], inn["formulaKey"]),
    }


def c6_card_hex(hexval):
    """R06: a card shows hex in the same format as /colors: # and 6 capital hex digits."""
    return hexval


def c6_reset_db(current, fresh):
    """POST /admin/reset brings the data back to the seed baseline."""
    c6_seed_header.synced = True
    return fresh


def c6_reset_answer(counts):
    """The body of the reset answer."""
    return {"status": "reset", "seedVersion": SEED_VERSION, "counts": counts}


def c6_seed_header():
    """The X-Seed-Version header of every answer."""
    return SEED_VERSION
# <<< ZONE C6


def sync_merge():
    """BossP.Api.Sync: merge F&O and Innovatint into the store documents (section 3.2).

    F&O gives name, family, active (Color) and all of Product, Sku, ProductColor,
    SkuColorCard. Innovatint gives hex and formulaCode.
    """
    out = dict((n, {}) for n in COLLECTION_ORDER)
    for code, name, family, active in FO_COLORS:
        out["Color"][code] = c6_color_doc(code, name, family, active, INNOVATINT_FORMULAS[code])
    for pcode, name, category, mixable, skus in FO_PRODUCTS:
        out["Product"][pcode] = {"_id": pcode, "productCode": pcode, "name": name,
                                 "category": category, "mixable": mixable,
                                 "_sync": _sync("FO-" + pcode)}
        for sku, litres in skus:
            out["Sku"][sku] = {"_id": sku, "sku": sku, "productCode": pcode,
                               "packLiters": litres, "active": True,
                               "_sync": _sync("FO-" + sku)}
    for pcode in sorted(FO_PRODUCT_COLORS):
        for ccode in sorted(FO_PRODUCT_COLORS[pcode]):
            key = "PC-%s-%s" % (pcode, ccode)
            out["ProductColor"][key] = {"_id": key, "productCode": pcode, "colorCode": ccode,
                                        "_sync": _sync("FO-PC-%s-%s" % (pcode, ccode))}
    for card_id, name, year, sku, codes in FO_CARDS:
        out["SkuColorCard"][card_id] = {
            "_id": card_id, "cardId": card_id, "name": name, "year": year, "sku": sku,
            "colors": [{"position": i + 1, "colorCode": c} for i, c in enumerate(codes)],
            "_sync": _sync("FO-" + card_id)}
    return out


# =====================================================================================
# HTTP LISTENER
# =====================================================================================

_LOG_LOCK = threading.Lock()


def log_line(text):
    """One ASCII line on stdout; non-ASCII is escaped so no console can fail on it."""
    safe = text.encode("ascii", "backslashreplace").decode("ascii")
    with _LOG_LOCK:
        sys.stdout.write(safe + "\n")
        sys.stdout.flush()


def make_handler(api, quiet):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "colorlab/" + VERSION
        sys_version = ""

        def _serve(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > 0:
                self.rfile.read(length)
            status, payload = api.handle(self.command, self.path)
            body = json.dumps(payload, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("X-Seed-Version", c6_seed_header())
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            if not quiet:
                log_line("%s %s %d" % (self.command, self.path, status))

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _serve

        def log_message(self, fmt, *args):
            pass

    return Handler


def build_api(settings):
    return BossPApiColor(Store.from_seed(), settings)


def make_server(api, host, port, quiet=False):
    return ThreadingHTTPServer((host, port), make_handler(api, quiet))


# =====================================================================================
# COMMAND LINE
# =====================================================================================

def precheck(settings):
    """Start on a free local port, call /health, print the JSON on one line, stop."""
    import urllib.request
    server = make_server(build_api(settings), "127.0.0.1", 0, quiet=True)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    code = 1
    try:
        url = "http://127.0.0.1:%d/health" % server.server_address[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=10) as resp:
            text = resp.read().decode("utf-8").strip()
            if resp.status == 200 and json.loads(text).get("status") == "ok":
                sys.stdout.write(text + "\n")
                code = 0
    except Exception as exc:
        sys.stderr.write("precheck failed: %s\n" % exc)
    finally:
        server.shutdown()
        server.server_close()
    return code


def dump_seed():
    data = json.dumps(Store.from_seed().dump(), ensure_ascii=False, indent=2) + "\n"
    sys.stdout.buffer.write(data.encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="colorlab", description="BossP.Api.Color mock")
    parser.add_argument("--precheck", action="store_true",
                        help="start on a free port, print /health, stop")
    parser.add_argument("--dump-seed", action="store_true", help="print the seed JSON")
    args = parser.parse_args(argv)
    if args.dump_seed:
        return dump_seed()
    try:
        settings = settings_from_env(os.environ)
    except ConfigError as exc:
        sys.stderr.write("%s\n" % exc)
        return 2
    if args.precheck:
        return precheck(settings)
    host = os.environ.get("COLORLAB_HOST", "").strip() or DEFAULT_HOST
    try:
        port = int(os.environ.get("COLORLAB_PORT", "").strip() or DEFAULT_PORT)
    except ValueError:
        sys.stderr.write("invalid COLORLAB_PORT\n")
        return 2
    try:
        server = make_server(build_api(settings), host, port)
    except OSError as exc:
        sys.stderr.write("cannot listen on %s:%d (%s). Is the port in use? "
                         "Set COLORLAB_PORT to another number.\n" % (host, port, exc))
        return 1
    log_line("colorlab %s seed %s listening on %s:%d"
             % (VERSION, SEED_VERSION, host, server.server_address[1]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
