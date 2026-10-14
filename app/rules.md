# Colour API business rules (R01-R10)

These are the business rules of the Color API as the colorlab mock applies them. Each rule has an id, a layer and the endpoints it touches. A rule is either applied in the API layer (checks input, shapes the answer) or in a lib (reads the data and applies the colour logic). Tests should cite the rule id they check.

| ID | Rule | Layer | Endpoints |
|---|---|---|---|
| R01 | Pages start at 1 (default 1). Page size is 1 to 50 (default 10). Anything else (0, 51, -1, text) is refused with 400 `BAD_PARAMETER`. A page past the end is not an error: 200 with an empty list. | API | E04, E05 |
| R02 | Every list answers with `page`, `pageSize`, `total`, `totalPages`, `items`. `total` counts all matches, not only this page. `totalPages` is total divided by page size, rounded up (0 when total is 0). A page never holds more than `pageSize` items. Reading all pages gives every match once: no gaps, no repeats. | API | E04, E05 |
| R03 | Input is checked before any lookup. Colour code: `BP` and 4 digits, upper or lower case accepted (shop staff type by hand). SKU: exactly `SKU-` and 4 digits. Card id: exactly `CARD-` and 2 digits. Search text `q`: 1 to 64 characters. `family`: one of the 11 family names in lower case. A bad value gives 400 with `INVALID_CODE`, `INVALID_SKU`, `INVALID_CARD` or `BAD_PARAMETER`. | API | E03, E04, E05, E06 |
| R04 | A colour is served exactly as it is in the master data: `code`, `name`, `hex`, `family`, `formulaCode` unchanged. The code is found whatever its case, and the answer shows it in upper case. Internal fields (`_id`, `_sync`) are never served. | lib Color | E03, E04, E05, E06 |
| R05 | A withdrawn colour is never offered. Asking for it directly gives 410 `COLOR_WITHDRAWN`. It does not appear in colour lists, search or product colour lists. (Cards: see R06.) | lib Color | E03, E04, E05 |
| R06 | A colour card lists its colours in the order of `position`. `colorCount` is the number of colours listed. A card lists the colours stored on it; withdrawing a colour does not change a card. Each colour shows `hex` in the same format as `/colors`: `#` and 6 capital hex digits. | lib SkuColorCard | E06 |
| R07 | Only mixable products ("maakbaar") have a colour list. A SKU of a product that is not mixable gives 409 `NOT_MIXABLE`. A mixable product with no colours yet gives 200 with an empty list. | lib ProductMaakbaar | E05 |
| R08 | The colour list of a product is sorted by colour code, ascending, and holds only active colours, with the same fields as `/colors/{code}`. | lib ProductColor | E05 |
| R09 | Every error has the same body: `{"error":{"code":"...","message":"..."}}`. A well-formed id that does not exist gives 404 `NOT_FOUND`. An unknown path gives 404 `NOT_FOUND`. | API | E03, E04, E05, E06 |
| R10 | Search `q` finds colours whose name contains the text, ignoring upper/lower case; accents must match (`creme` does not find `Crèmewit`). `family` must match exactly. Both together mean AND. Results are sorted by code, ascending. Any valid characters are allowed, including accents. | lib Color | E04 |

## Layer split

The logic is split, as in the real service. The API layer holds 4 rules: R01, R02, R03, R09. The libs hold 6 rules: R04, R05, R06, R07, R08, R10.

## Endpoints used above

| ID | Method and path |
|---|---|
| E03 | `GET /colors/{code}` |
| E04 | `GET /colors` |
| E05 | `GET /products/{sku}/colors` |
| E06 | `GET /cards/{cardId}` |
