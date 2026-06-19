"""Numeral grounding for Phase-8 findings — see aughor/explorer/grounding.py.

The canonical bug this guards: a finding read "2.49M attribution credit" when the
real result cell was 2.49 (off 1e6, with a fabricated "M"). The verifier must flag
magnitude/unit hallucinations while never false-flagging legitimately derived
numbers (percentages, ranks, small counts, years)."""
from aughor.explorer.grounding import (
    Numeral,
    cell_values,
    extract_numerals,
    ground_numerals,
    numeric_cells_block,
    verify_finding,
)


# ── extract_numerals ─────────────────────────────────────────────────────────

def _texts(s):
    return [n.text for n in extract_numerals(s)]


def test_extract_basic_and_suffixes():
    nums = {n.text: n for n in extract_numerals(
        "Revenue hit 2.49M, up from 1,200,000 across 5 regions and 23%."
    )}
    assert nums["2.49M"].value == 2_490_000.0
    assert nums["2.49M"].multiplier == 1e6
    assert nums["2.49M"].decimals == 2
    assert nums["1,200,000"].value == 1_200_000.0
    assert nums["23%"].suffix == "%"


def test_extract_word_suffix_and_currency():
    n = {x.text.strip(): x for x in extract_numerals("worth $3.2 billion and £500K")}
    assert any(v.value == 3.2e9 for v in n.values())
    assert any(v.value == 500_000.0 for v in n.values())


def test_decimals_drive_window_width():
    [a] = extract_numerals("2M")
    [b] = extract_numerals("2.49M")
    assert a.decimals == 0
    assert b.decimals == 2


# ── enforcement classification ───────────────────────────────────────────────

def test_only_magnitude_bearing_is_enforced():
    by = {n.text: n for n in extract_numerals(
        "Top 5 segments drove 2.49M in 2024, a 23% lift over 3 quarters."
    )}
    assert by["2.49M"].enforce is True          # magnitude suffix
    assert by["5"].enforce is False             # small rank
    assert by["3"].enforce is False             # small count
    assert by["23%"].enforce is False           # percentage (derived)
    assert by["2024"].enforce is False          # calendar year


def test_bare_large_number_is_enforced():
    [n] = extract_numerals("2453221 orders")
    assert n.enforce is True
    assert n.value == 2453221.0


def test_year_whitelist_boundaries():
    assert extract_numerals("1900")[0].enforce is False
    assert extract_numerals("2100")[0].enforce is False
    # 1899 is not a plausible year and ≥1000 → enforced
    assert extract_numerals("1899")[0].enforce is True


# ── cell_values coercion ─────────────────────────────────────────────────────

def test_cell_values_mixed_types():
    rows = [["north", 2.49, None], ["south", "1,200", True]]
    vals = cell_values(rows)
    assert 2.49 in vals
    assert 1200.0 in vals
    assert True not in [type(v) for v in vals]   # bool excluded, not coerced to 1.0
    assert all(isinstance(v, float) for v in vals)


def test_cell_values_dict_rows_and_extra():
    rows = [{"region": "n", "rev": 10}, {"region": "s", "rev": 20}]
    vals = cell_values(rows, extra=[99])
    assert set(vals) == {10.0, 20.0, 99.0}


# ── verify_finding: the core guard ───────────────────────────────────────────

def test_the_canonical_2p49M_bug_is_flagged():
    # cell is 2.49; finding claims 2.49M → off by 1e6
    rows = [[2.49]]
    r = verify_finding("Attribution credit totals 2.49M across touchpoints.", rows)
    assert r.grounded is False
    assert r.ungrounded == ["2.49M"]
    assert r.checked == 1


def test_correct_unscaled_number_is_grounded():
    rows = [[2.49]]
    r = verify_finding("Average attribution credit is 2.49 per touchpoint.", rows)
    assert r.grounded is True
    assert r.ungrounded == []


def test_real_millions_cell_grounds_M_suffix():
    rows = [[2_490_000]]
    r = verify_finding("Revenue reached 2.49M.", rows)
    assert r.grounded is True


def test_rounding_window_one_sig_fig():
    # "2M" (1 sig fig, window [1.5M,2.5M]) grounds a 2.25M cell; "2.49M" (3 sig figs)
    # is >2% away from 2.25M so it does NOT — the displayed precision sets the bar.
    rows = [[2_250_000]]
    assert verify_finding("about 2M in sales", rows).grounded is True
    assert verify_finding("exactly 2.49M in sales", rows).grounded is False


def test_three_trillion_product_of_aggregates_flagged():
    # the $3T revenue bug: real cells are ~3e6, claim is 3e12
    rows = [[3_120_000], [2_800_000]]
    r = verify_finding("Total revenue is $3T.", rows)
    assert r.grounded is False
    assert r.ungrounded == ["$3T"]


def test_percentages_never_flagged_even_without_cell():
    rows = [["north", 0.51], ["south", 0.49]]
    r = verify_finding("North holds 51% share, a 23% YoY jump.", rows)
    assert r.grounded is True       # 51%/23% are derived, exempt


def test_year_and_small_counts_never_flagged():
    rows = [["x", 42.0]]
    r = verify_finding("In 2024, the top 3 of 7 cohorts converted.", rows)
    assert r.grounded is True


def test_thousands_count_grounds():
    rows = [[2453]]
    assert verify_finding("2,453 orders were placed.", rows).grounded is True


def test_negative_cell_grounds_loss_magnitude():
    rows = [[-2_400_000]]
    assert verify_finding("a loss of 2.4M this quarter", rows).grounded is True


def test_one_bad_number_among_good_ones():
    rows = [[1_200_000, 5]]
    r = verify_finding("1.2M orders across 5 regions, worth 9.9B.", rows)
    assert r.grounded is False
    assert r.ungrounded == ["9.9B"]     # 1.2M and 5 are fine


def test_no_numeric_cells_but_magnitude_claim_is_flagged():
    rows = [["north"], ["south"]]   # text-only result
    r = verify_finding("Sales reached 5M units.", rows)
    assert r.grounded is False


def test_empty_finding_is_trivially_grounded():
    assert verify_finding("", [[1]]).grounded is True
    assert verify_finding("No numbers here at all.", [[1]]).grounded is True


# ── ground_numerals: the per-numeral receipt map ─────────────────────────────

def _by_text(records):
    return {r["text"]: r for r in records}


def test_ground_numerals_maps_each_token_to_its_cell():
    rows = [[2_490_000, 5]]
    recs = _by_text(ground_numerals("2.49M across 5 regions", rows))
    assert recs["2.49M"]["enforce"] is True
    assert recs["2.49M"]["grounded"] is True
    assert recs["2.49M"]["matched_cell"] == 2_490_000.0
    # "5" is a small rank → not enforced, shown as derived (matched_cell None)
    assert recs["5"]["enforce"] is False
    assert recs["5"]["grounded"] is True
    assert recs["5"]["matched_cell"] is None


def test_ground_numerals_flags_the_2p49M_bug_with_no_match():
    rows = [[2.49]]
    [rec] = ground_numerals("Attribution credit totals 2.49M.", rows)
    assert rec["enforce"] is True
    assert rec["grounded"] is False
    assert rec["matched_cell"] is None


def test_ground_numerals_mixed_good_and_bad():
    rows = [[1_200_000, 5]]
    recs = _by_text(ground_numerals("1.2M orders across 5 regions, worth 9.9B.", rows))
    assert recs["1.2M"]["grounded"] is True and recs["1.2M"]["matched_cell"] == 1_200_000.0
    assert recs["9.9B"]["grounded"] is False and recs["9.9B"]["matched_cell"] is None


def test_ground_numerals_percentages_and_years_not_enforced():
    rows = [["north", 0.51]]
    recs = _by_text(ground_numerals("In 2024 North held 51% share.", rows))
    assert recs["51%"]["enforce"] is False and recs["51%"]["grounded"] is True
    assert recs["2024"]["enforce"] is False and recs["2024"]["grounded"] is True


def test_ground_numerals_negative_cell_grounds_loss():
    rows = [[-2_400_000]]
    [rec] = ground_numerals("a loss of 2.4M this quarter", rows)
    assert rec["grounded"] is True
    assert rec["matched_cell"] == -2_400_000.0   # the actual (signed) cell, not abs


def test_ground_numerals_empty_finding():
    assert ground_numerals("No numbers here.", [[1]]) == []


# ── numeric_cells_block ──────────────────────────────────────────────────────

def test_numeric_cells_block_dedupes_and_sorts():
    rows = [["n", 100, 2.5], ["s", 100, 9999]]
    block = numeric_cells_block(rows)
    assert block.startswith("9999")      # largest first
    assert block.count("100") == 1       # de-duplicated
    assert "2.5" in block


def test_numeric_cells_block_empty():
    assert "no numeric" in numeric_cells_block([["a"], ["b"]]).lower()


def test_numeric_cells_block_truncates():
    rows = [[float(i)] for i in range(60)]
    block = numeric_cells_block(rows, limit=10)
    assert "more)" in block
