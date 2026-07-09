"""Render-boundary number hygiene (T3-2, 2026-07-09).

Deep-Analysis audit finding (inv2, explore mode): the narrator copied raw 17-significant-digit floats
straight into prose — "Klarna's failure rate of 0.20829576194770064" in the headline/conclusion/
narrative. `round_long_decimals` collapses any decimal run with 4+ fractional digits in a prose
string, using the same precision rule as the table-cell rounder (`_round_cell`), leaving short
numbers, currency, and percentages untouched. See aughor/tools/executor.py.
"""
from aughor.tools.executor import round_long_decimals


def test_collapses_the_inv2_float():
    out = round_long_decimals("Klarna's failure rate of 0.20829576194770064 is the driver.")
    assert "0.20829576194770064" not in out
    assert "0.208296" in out                       # |v|<1 → 6dp (matches _round_cell)


def test_large_value_rounds_to_two_dp():
    assert round_long_decimals("revenue was 711231.2900000175 dollars") == "revenue was 711231.29 dollars"


def test_short_numbers_untouched():
    s = "Klarna 20.8%, card 4.9%, total $45,105 across 110 orders (2024)."
    assert round_long_decimals(s) == s             # nothing has 4+ decimals


def test_percent_and_currency_with_short_decimals_untouched():
    s = "The rate rose 6.42% to $1,073,961.50."
    assert round_long_decimals(s) == s


def test_multiple_floats_in_one_string():
    out = round_long_decimals("a=0.25396825396825395 and b=17.857142857142858")
    assert "0.253968" in out and "17.86" in out
    assert "0.25396825396825395" not in out and "17.857142857142858" not in out


def test_integer_result_drops_trailing_zero():
    # 39.99999999998568 → 40 (not 40.0)
    assert round_long_decimals("value 39.99999999998568 here") == "value 40 here"


def test_empty_and_none_safe():
    assert round_long_decimals("") == ""
    assert round_long_decimals(None) is None
