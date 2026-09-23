"""An exhibit is drawn once; the finding that two phases agree stays in the prose.

From a real five-page report, 2026-09-23: the category chart appeared TWICE
("(inventory_items)" and "(products)") and the department chart THREE times, every copy
byte-identical. The report's own prose said why — *"Joining inventory_items to products
yields identical figures to the direct category scan… The join adds no new signal."*

That agreement is a real result and it belongs in the text. Drawing the same picture again
does not report it; it just costs a page.
"""
from __future__ import annotations

from aughor.export.document import _grid_fingerprint

COLS = ["product_category", "items"]
ROWS = [["Intimates", 36294], ["Jeans", 34602], ["Dresses", 14568]]


def test_the_same_grid_fingerprints_the_same():
    assert _grid_fingerprint(COLS, ROWS) == _grid_fingerprint(list(COLS), [r[:] for r in ROWS])


def test_different_HEADERS_over_the_same_numbers_are_a_different_exhibit():
    """`revenue` and `items` over identical figures say different things, and the report
    that prompted this had exactly that: one column named for a metric, holding a count."""
    assert _grid_fingerprint(COLS, ROWS) != _grid_fingerprint(["product_category", "revenue"], ROWS)


def test_a_RE_SORTED_ranking_is_a_different_exhibit():
    """A ranking reads by position. The same rows in another order is another chart."""
    assert _grid_fingerprint(COLS, ROWS) != _grid_fingerprint(COLS, list(reversed(ROWS)))


def test_an_empty_grid_is_never_a_repeat():
    """Findings with no rows must not all collide onto one fingerprint and suppress each
    other's exhibits — the empty case is the one that would do it silently."""
    assert _grid_fingerprint([], []) == ""
    assert _grid_fingerprint(COLS, []) == ""
    assert _grid_fingerprint([], ROWS) == ""
