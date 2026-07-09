"""P3 — fraction↔percent unit consistency in prose.

T3-2 (`round_long_decimals`) killed 17-digit floats, but a percent metric could still read as a
fraction in one clause and a percent in another ("0.208" next to "20.8%"). `unify_percent_fractions`
normalizes the fraction to the percent form — but only SELF-GROUNDED: the fraction's ×100 value must
already appear in the text as an explicit percent, so an unrelated sub-1 number (a correlation, a
p-value, a price) is never rescaled. These tests pin both the rewrites and the guards.
"""
from __future__ import annotations

from aughor.tools.executor import unify_percent_fractions as U


# ── Rewrites the inconsistency ────────────────────────────────────────────────────

def test_rewrites_fraction_when_percent_twin_present():
    assert U("The refund rate is 0.208, i.e. 20.8% of orders.") == \
        "The refund rate is 20.8%, i.e. 20.8% of orders."


def test_matches_the_twins_exact_string_no_new_precision_mismatch():
    # 0.05 → the twin "5" (not "5.0"), so we don't introduce a fresh "5.0% vs 5%" mismatch.
    assert U("A share of 0.05 — that is 5% overall.") == "A share of 5% — that is 5% overall."


def test_handles_leading_dot_and_higher_precision_fraction():
    assert U("failure .208 (20.8%)") == "failure 20.8% (20.8%)"
    # 0.2083 rounds to the 20.8% twin.
    assert U("rate 0.2083 vs 20.8% peers") == "rate 20.8% vs 20.8% peers"


# ── Guards: never touch an unrelated sub-1 number ─────────────────────────────────

def test_no_twin_means_no_change():
    # No explicit percent in the text → nothing is grounded → unchanged.
    assert U("The refund rate is 0.208 of orders.") == "The refund rate is 0.208 of orders."


def test_unrelated_fraction_untouched_even_with_a_percent_present():
    # A correlation 0.82 has no 82% twin; the 20.8% mention must not drag it.
    txt = "Correlation 0.82; refund rate 20.8%."
    assert U(txt) == txt


def test_currency_and_word_fragments_untouched():
    assert U("Priced at $0.50 with margin 50%.") == "Priced at $0.50 with margin 50%."
    # A version-like "v0.5" (preceded by a word char) is not a bare fraction.
    assert U("build v0.5 shipped; adoption 50%.") == "build v0.5 shipped; adoption 50%."


def test_percentage_points_untouched():
    # "0.36 pp" is an absolute spread, not a fraction to rescale.
    assert U("gap of 0.36 pp; base 36%.") == "gap of 0.36 pp; base 36%."


def test_value_one_or_more_untouched():
    # v >= 1 is never a fraction-of-a-percent; "1.5" stays even next to a "150%" twin.
    assert U("ratio 1.5 vs 150% cap") == "ratio 1.5 vs 150% cap"


# ── Hygiene ───────────────────────────────────────────────────────────────────────

def test_noop_on_text_without_percent():
    assert U("no percents here, just 0.208 and 0.5") == "no percents here, just 0.208 and 0.5"


def test_idempotent_and_none_safe():
    once = U("0.208 = 20.8%")
    assert U(once) == once
    assert U("") == ""
    assert U(None) is None
