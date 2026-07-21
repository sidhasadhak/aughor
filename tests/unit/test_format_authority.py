"""The platform number-format authority — `aughor.util.format`.

Aughor quotes its own grounded numbers verbatim, so one raw float64 entering an LLM prompt
surfaces unchanged in a headline ("…is 43.959061407888164%"). The policy is therefore applied
at BOTH ends: `rows_for_prompt` rounds on the way IN (the model never sees the long form) and
`round_long_decimals` rounds prose on the way OUT (anything already persisted is still fixed).

These lock the policy itself. Prose-level behaviour has its own suites
(`test_number_hygiene.py`, `test_percent_prose_unify.py`).
"""
from __future__ import annotations

from decimal import Decimal

from aughor.util.format import (
    round_cell,
    round_long_decimals,
    round_number,
    rows_for_prompt,
)

# ── The policy ────────────────────────────────────────────────────────────────


def test_magnitudes_at_or_above_one_round_to_two_places():
    assert round_number(43.959061407888164) == 43.96
    assert round_number(24.188549041748047) == 24.19
    assert round_number(711231.2900000175) == 711231.29


def test_values_below_one_keep_six_places_so_small_rates_survive():
    assert round_number(0.20829576194770064) == 0.208296
    assert round_number(0.0034) == 0.0034
    assert round_number(0.000001234) == 1e-06


def test_whole_results_lose_the_decimal_point():
    assert round_number(39.99999999998568) == 40
    assert isinstance(round_number(39.99999999998568), int)
    assert round_cell(39.99999999998568) == "40"


def test_negatives_use_magnitude_not_sign():
    assert round_number(-43.959061407888164) == -43.96
    assert round_number(-0.20829576194770064) == -0.208296


# ── What must NOT be touched ──────────────────────────────────────────────────


def test_non_numbers_pass_through_untouched():
    for v in ("Mytheresa", None, "", "2026-07-21", "N/A"):
        assert round_number(v) == v


def test_bools_are_not_numbers():
    """`isinstance(True, int)` would otherwise turn a flag into 1."""
    assert round_number(True) is True
    assert round_cell(False) == "False"


def test_nan_and_infinity_survive():
    nan = float("nan")
    assert round_number(nan) != round_number(nan)          # NaN != NaN
    assert round_number(float("inf")) == float("inf")


def test_decimal_and_numeric_strings_are_covered():
    """DuckDB hands DECIMAL columns back as Decimal or str — a float-only check missed them."""
    assert round_number(Decimal("711231.2900000175")) == 711231.29
    assert round_number("711231.2900000175") == 711231.29
    assert round_number("  0.20829576194770064  ") == 0.208296


def test_short_decimals_are_left_exactly_as_written():
    assert round_number(3.14) == 3.14
    assert round_long_decimals("pi is 3.14, price $1.50, count 1,234") == "pi is 3.14, price $1.50, count 1,234"


def test_rounding_is_idempotent():
    once = round_long_decimals("share 0.27598474499089254 of 43.959061407888164%")
    assert round_long_decimals(once) == once


# ── The prevention seam ───────────────────────────────────────────────────────


def test_rows_for_prompt_rounds_every_cell():
    out = rows_for_prompt([(43.959061407888164, "US"), (24.188549041748047, "GB")])
    assert out == "(43.96, 'US')\n(24.19, 'GB')"
    assert "43.959061407888164" not in out


def test_rows_for_prompt_preserves_the_tuple_repr_shape():
    """The prompt format is deliberately unchanged — only the digits get shorter — so this
    change cannot perturb interpretation beyond the fix itself."""
    rows = [(1, "a"), (2, "b")]
    assert rows_for_prompt(rows) == "\n".join(str(r) for r in rows)


def test_rows_for_prompt_handles_lists_dicts_and_scalars():
    assert rows_for_prompt([[1.23456789, "x"]]) == "[1.23, 'x']"
    assert rows_for_prompt([{"pct": 43.959061407888164}]) == "{'pct': 43.96}"
    assert rows_for_prompt([43.959061407888164]) == "43.96"


def test_rows_for_prompt_caps_rows_and_is_safe_on_empty():
    assert rows_for_prompt([(i,) for i in range(50)], limit=3) == "(0,)\n(1,)\n(2,)"
    assert rows_for_prompt([]) == ""
    assert rows_for_prompt(None) == ""


# ── The read-path backstop (historical findings) ──────────────────────────────


def test_served_findings_are_normalized_for_every_consumer():
    """Findings written before emit-time rounding still live in the store; the domains read
    path cleans them so cards, tiles and the key-figure extractor all quote the short form."""
    from aughor.routers.exploration import _normalize_insight_numbers

    by_domain = {
        "Content": {"insights": [
            {"finding": "mature-rated content is 43.959061407888164% of the library"},
            {"finding": "no numbers here"},
            {"sql": "SELECT 1"},                      # no finding key at all
        ]},
        "Legacy": [{"finding": "share 0.27598474499089254"}],   # bare-list payload shape
    }
    _normalize_insight_numbers(by_domain)

    assert by_domain["Content"]["insights"][0]["finding"].endswith("43.96% of the library")
    assert by_domain["Content"]["insights"][1]["finding"] == "no numbers here"
    assert "finding" not in by_domain["Content"]["insights"][2]
    assert by_domain["Legacy"][0]["finding"] == "share 0.275985"
