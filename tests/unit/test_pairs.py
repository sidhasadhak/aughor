"""AT-6 — the pair rules, and the false positives each one was built to refuse.

Every negative test here is a measurement, not a hypothetical. `test_a_constant_factor_is_
not_an_identity` is `transactionID × unitPrice ≈ franchiseID` at 100%; `test_sixteen_
significant_digits_are_not_a_coordinate` is `scm.supply_chain_data`; `test_a_latitude_
without_a_longitude_is_nothing` is the 60%-false-positive rate AT-0 measured for the
bounded-±90 test run on its own.
"""
from __future__ import annotations

import pytest

from aughor.tools.concept import LAYER_PAIR
from aughor.tools.pairs import (
    MIN_ROWS,
    ColumnSample,
    derived_expressions,
    pair_witnesses,
    scan_pairs,
)


def col(name: str, values, dtype: str = "") -> ColumnSample:
    return ColumnSample(column=name, dtype=dtype, values=tuple(values))


def kinds(scan) -> list[str]:
    return [f.kind for f in scan.findings]


def find(scan, kind: str):
    return next((f for f in scan.findings if f.kind == kind), None)


N = 60          # comfortably above MIN_ROWS


# ── arithmetic identity — AT-0's most prevalent signal ────────────────────────

def test_a_product_identity_is_found_and_its_factors_are_typed():
    qty = [1 + (i % 5) for i in range(N)]
    price = [round(9.99 + i, 2) for i in range(N)]
    scan = scan_pairs([
        col("Order Item Quantity", qty),
        col("Order Item Product Price", price),
        col("Sales", [q * p for q, p in zip(qty, price)]),
    ])
    f = find(scan, "arithmetic_identity")
    assert f is not None
    assert set(f.columns) == {"Order Item Quantity", "Order Item Product Price", "Sales"}
    assert f.support == 1.0
    # The role is COMPUTED: whole numbers count things, fractional ones price them.
    roles = dict(zip(f.columns, f.roles))
    assert roles["Order Item Quantity"] == "count.quantity"
    assert roles["Order Item Product Price"] == "rate.per_unit"
    assert roles["Sales"] == "measure.additive_total"


def test_a_constant_factor_is_not_an_identity():
    """AT-0 finding 1: the sweep returned `transactionID × unitPrice ≈ franchiseID` on 100%
    of rows because `unitPrice` was the constant 3. A factor that never varies makes the
    identity a restatement of `c ∝ a`, and the tolerance being relative hid it."""
    txn = [100 + i for i in range(N)]
    unit_price = [3] * N
    scan = scan_pairs([
        col("transactionID", txn),
        col("unitPrice", unit_price),
        col("franchiseID", [t * 3 for t in txn]),
    ])
    assert "arithmetic_identity" not in kinds(scan)


def test_an_identity_that_holds_on_half_the_rows_is_not_an_identity():
    qty = [2] * N
    price = [round(1.5 + i, 2) for i in range(N)]
    total = [q * p if i % 2 else 0.0 for i, (q, p) in enumerate(zip(qty, price))]
    scan = scan_pairs([col("qty", qty), col("price", price), col("total", total)])
    assert "arithmetic_identity" not in kinds(scan)


# ── the derived flag — the computed MAGNITUDE GUARD ───────────────────────────

def _dataco_shape(n: int = 120, flag_noise: int = 0):
    """data_co's real shape: a scheduled plan, an actual outcome, and a 0/1 column that
    equals `actual > scheduled` — on 97.55% of 180,519 rows, not 100%."""
    real = [i % 7 for i in range(n)]
    sched = [(i % 4) for i in range(n)]
    flag = [1 if r > s else 0 for r, s in zip(real, sched)]
    for i in range(flag_noise):
        flag[i] = 1 - flag[i]
    return real, sched, flag


def test_the_flag_is_recognised_as_a_stored_comparison():
    real, sched, flag = _dataco_shape()
    scan = scan_pairs([
        col("Days for shipping (real)", real),
        col("Days for shipment (scheduled)", sched),
        col("Late_delivery_risk", flag),
    ])
    f = find(scan, "derived_flag")
    assert f is not None
    assert f.columns[0] == "Late_delivery_risk"
    assert set(f.columns[1:]) == {"Days for shipping (real)", "Days for shipment (scheduled)"}
    assert f.roles == ("flag.derived_comparison", "measure.actual", "measure.planned")
    # The magnitude behind the flag is the whole point — intake had to invent this
    # subtraction from a prompt paragraph in six consecutive runs.
    assert f.expression == '"Days for shipping (real)" - "Days for shipment (scheduled)"'


def test_the_flag_survives_the_noise_the_real_data_carries():
    """97.55% is the measured support on data_co. A rule that demanded 100% would refuse
    its own motivating case."""
    real, sched, flag = _dataco_shape(n=200, flag_noise=5)     # 97.5%
    scan = scan_pairs([
        col("real", real), col("sched", sched), col("flag", flag),
    ])
    f = find(scan, "derived_flag")
    assert f is not None and 0.95 <= f.support < 1.0


def test_a_flag_no_pair_explains_stays_unexplained():
    scan = scan_pairs([
        col("a", [i % 7 for i in range(N)]),
        col("b", [i % 4 for i in range(N)]),
        col("unrelated_flag", [i % 2 for i in range(N)]),
    ])
    assert "derived_flag" not in kinds(scan)


# ── duplicate columns — the tautology door Track 1 left open ──────────────────

def test_one_column_under_two_names_is_reported():
    vals = [round(1.5 * i, 2) for i in range(N)]
    scan = scan_pairs([col("Benefit per order", vals), col("Order Profit Per Order", list(vals))])
    f = find(scan, "duplicate_column")
    assert f is not None
    assert f.support == 1.0
    assert f.roles == ("", "")          # it says what they are NOT, not what they are


def test_a_near_duplicate_is_not_a_duplicate():
    """`mostly identical` is a finding about the data, not about the schema. One differing
    row and these are two columns that happen to agree — which is a correlation, and the
    relationship primitive exists to measure exactly that."""
    a = [float(i) for i in range(N)]
    b = list(a)
    b[3] = 999.0
    scan = scan_pairs([col("a", a), col("b", b)])
    assert "duplicate_column" not in kinds(scan)


def test_two_constants_are_not_duplicates():
    scan = scan_pairs([col("a", [0] * N), col("b", [0] * N)])
    assert "duplicate_column" not in kinds(scan)


# ── start / end ───────────────────────────────────────────────────────────────

def test_an_ordered_timestamp_pair_implies_a_duration():
    start = [f"2026-03-{1 + i % 28:02d} 08:00:00" for i in range(N)]
    end = [f"2026-03-{1 + i % 28:02d} 17:30:00" for i in range(N)]
    scan = scan_pairs([col("scheduled_departure", start), col("scheduled_arrival", end)])
    f = find(scan, "start_end")
    assert f is not None
    assert f.columns == ("scheduled_departure", "scheduled_arrival")
    assert f.expression == '"scheduled_arrival" - "scheduled_departure"'
    assert f.roles == ("time.start", "time.end")


def test_two_copies_of_one_timestamp_are_not_a_span():
    """`a <= b` holds on 100% of rows when a IS b. A span needs the two to actually differ."""
    ts = [f"2026-03-{1 + i % 28:02d} 08:00:00" for i in range(N)]
    scan = scan_pairs([col("created_at", ts), col("created_at_copy", list(ts))])
    assert "start_end" not in kinds(scan)


# ── coordinates — cheap, structural, and refusing what it cannot tell apart ───

_LATS = [round(18.25 + i * 0.0137, 8) for i in range(N)]
_LONS = [round(-66.03 - i * 0.9137, 8) for i in range(N)]


def test_a_latitude_reaches_its_concept_through_its_partner_not_its_name():
    scan = scan_pairs([col("Latitude", _LATS, "VARCHAR"), col("Longitude", _LONS, "VARCHAR")])
    f = find(scan, "coordinate_partner")
    assert f is not None
    assert f.roles == ("geo.latitude", "geo.longitude")
    # VARCHAR is what the loader said; the values are what decided.
    assert "±90" in f.note


def test_a_latitude_without_a_longitude_is_nothing():
    """AT-0: of 5 columns passing a bounded-±90 value test, only 2 were coordinates. A lone
    range test is wrong 60% of the time, so it is not allowed to speak alone."""
    scan = scan_pairs([col("Latitude", _LATS, "VARCHAR"), col("rating", [round(i / 20, 2) for i in range(N)])])
    assert "coordinate_partner" not in kinds(scan)


def test_sixteen_significant_digits_are_not_a_coordinate():
    """`scm.supply_chain_data` — the false-positive table AT-0 named in advance. Every range
    test passes; the precision is the tell. A coordinate is recorded to a precision somebody
    chose, and 2.956572139430807 is a float printed in full."""
    costs = [2.956572139430807 + i * 0.301701701701 for i in range(N)]
    price = [69.80800554211577 + i * 0.4017017017 for i in range(N)]
    scan = scan_pairs([col("Shipping costs", costs), col("Price", price)])
    assert "coordinate_partner" not in kinds(scan)


def test_a_column_NAMED_latitude_holding_costs_gets_no_coordinate():
    """The name is never consulted in this module — that is the point of the pair layer."""
    scan = scan_pairs([
        col("Latitude", [round(1.5 + i * 0.25, 2) for i in range(N)]),
        col("Longitude", [round(2.5 + i * 0.25, 2) for i in range(N)]),
    ])
    assert "coordinate_partner" not in kinds(scan)


# ── the bounds, said out loud ─────────────────────────────────────────────────

def test_a_short_sample_agreeing_perfectly_proves_nothing():
    n = MIN_ROWS - 1
    qty = [1 + (i % 5) for i in range(n)]
    price = [round(9.99 + i, 2) for i in range(n)]
    scan = scan_pairs([
        col("qty", qty), col("price", price),
        col("total", [q * p for q, p in zip(qty, price)]),
    ])
    assert scan.findings == []


def test_a_truncated_sweep_says_so():
    """A silent cap reads as 'we looked at everything'. The first version of this module
    capped at 20 numeric columns, dropped `Sales`, found nothing, and reported nothing."""
    cols = [col(f"m{i}", [float(i + j) for j in range(N)]) for i in range(45)]
    scan = scan_pairs(cols)
    assert any("cap" in t for t in scan.truncated)
    assert any("40" in t for t in scan.truncated)


def test_no_columns_and_one_column_are_answerable_without_raising():
    assert scan_pairs([]).findings == []
    assert scan_pairs([col("only", [1, 2, 3])]).findings == []


# ── the projection onto witnesses ─────────────────────────────────────────────

def test_witnesses_are_pair_layer_and_carry_the_number():
    real, sched, flag = _dataco_shape()
    scan = scan_pairs([col("real", real), col("sched", sched), col("flag", flag)])
    w = pair_witnesses(scan)
    assert w["flag"][0].layer == LAYER_PAIR
    assert w["flag"][0].concept == "flag.derived_comparison"
    assert "%" in w["flag"][0].evidence          # the support, in the sentence a human reads
    # BOTH sides of the pair are witnessed — that is what makes this a second witness.
    assert w["real"][0].concept == "measure.actual"
    assert w["sched"][0].concept == "measure.planned"


def test_a_rule_that_says_nothing_about_a_member_witnesses_nothing():
    vals = [round(1.5 * i, 2) for i in range(N)]
    scan = scan_pairs([col("a", vals), col("b", list(vals))])
    assert pair_witnesses(scan) == {}


def test_derived_expressions_lead_with_the_strongest_rule():
    real, sched, flag = _dataco_shape()
    scan = scan_pairs([
        col("real", real), col("sched", sched), col("flag", flag),
        col("qty", [1 + (i % 5) for i in range(120)]),
        col("price", [round(2.5 + i, 2) for i in range(120)]),
        col("total", [(1 + (i % 5)) * round(2.5 + i, 2) for i in range(120)]),
    ])
    exprs = derived_expressions(scan)
    assert exprs, "a table with a derived flag has an expression intake should not invent"
    assert exprs[0].kind == "derived_flag"
    assert all(f.expression for f in exprs)


def test_pair_witnesses_of_nothing_is_nothing():
    assert pair_witnesses(scan_pairs([])) == {}
    assert derived_expressions(scan_pairs([])) == []


@pytest.mark.parametrize("junk", [None, "", "NULL", "n/a", "abc"])
def test_junk_cells_never_raise_and_never_count(junk):
    vals = [junk] + [float(i) for i in range(N)]
    scan = scan_pairs([col("a", vals), col("b", list(vals))])
    f = find(scan, "duplicate_column")
    assert f is not None
    assert f.n_rows == N          # the junk row was not counted as agreement
