"""Post-processing operators (aughor/tools/postproc.py) + their wiring into the
stats surface (analyze_query_result): period-over-period and Pareto concentration
now surface to the LLM, gated so only material/concentrated signals appear.
"""
from aughor.tools.postproc import (
    pct_changes, shares, rolling, cumulative,
    with_period_over_period, with_contribution, with_rolling, with_cumulative,
)
from aughor.tools.stats import analyze_query_result


# ── series math ───────────────────────────────────────────────────────────────

def test_pct_changes():
    out = pct_changes([10.0, 11.0, 9.0])
    assert out[0] is None
    assert abs(out[1] - 0.1) < 1e-9
    assert abs(out[2] - (-2.0 / 11.0)) < 1e-9


def test_pct_changes_guards_zero_and_nulls():
    assert pct_changes([0.0, 5.0]) == [None, None]      # prior 0 → undefined
    assert pct_changes([5.0, None, 6.0]) == [None, None, None]


def test_shares():
    assert shares([1.0, 1.0, 2.0]) == [0.25, 0.25, 0.5]
    assert shares([0.0, 0.0]) == [None, None]           # zero total
    assert shares([None, 2.0, 2.0]) == [None, 0.5, 0.5]


def test_rolling_mean_and_sum():
    assert rolling([1.0, 2.0, 3.0, 4.0], 2, "mean") == [None, 1.5, 2.5, 3.5]
    assert rolling([1.0, 2.0, 3.0, 4.0], 2, "sum") == [None, 3.0, 5.0, 7.0]
    assert rolling([1.0, None, 3.0], 2, "mean") == [None, None, None]  # null in window


def test_cumulative():
    assert cumulative([1.0, 2.0, 3.0]) == [1.0, 3.0, 6.0]
    assert cumulative([1.0, None, 2.0]) == [1.0, 1.0, 3.0]   # null contributes 0


# ── table transforms ──────────────────────────────────────────────────────────

def test_with_contribution_appends_column():
    cols, rows = with_contribution(["cat", "gmv"], [["A", 30], ["B", 10]], "gmv")
    assert cols == ["cat", "gmv", "gmv_pct_of_total"]
    assert rows[0] == ["A", 30, 0.75]
    assert rows[1] == ["B", 10, 0.25]


def test_with_period_over_period_appends_column():
    cols, rows = with_period_over_period(["m", "rev"], [["jan", 100], ["feb", 120]], "rev")
    assert cols[-1] == "rev_pct_change"
    assert rows[0][-1] is None
    assert abs(rows[1][-1] - 0.2) < 1e-9


def test_with_rolling_and_cumulative_columns():
    cols, _ = with_rolling(["m", "rev"], [["a", 1], ["b", 2], ["c", 3]], "rev", 2)
    assert cols[-1] == "rev_rolling_mean2"
    cols2, rows2 = with_cumulative(["m", "rev"], [["a", 1], ["b", 2]], "rev")
    assert cols2[-1] == "rev_cumulative"
    assert rows2[1][-1] == 3.0


# ── wiring: stats surface now emits PoP + concentration (gated) ────────────────

def test_analyze_surfaces_period_over_period():
    cols = ["order_date", "revenue"]
    vals = [100, 102, 101, 103, 105, 104, 106, 108, 110, 140]  # last jump +27%
    rows = [[f"2024-{m:02d}-01", v] for m, v in enumerate(vals, start=1)]
    out = analyze_query_result(cols, rows)
    assert any(s.type == "comparison" and "period-over-period" in s.interpretation for s in out)


def test_analyze_surfaces_concentration():
    cols = ["category", "gmv"]
    rows = [["A", 100], ["B", 5], ["C", 3], ["D", 2], ["E", 1]]  # top1 = 90%
    out = analyze_query_result(cols, rows)
    assert any(s.type == "contribution" and "Concentrated" in s.interpretation for s in out)


def test_analyze_stays_quiet_on_flat_even_distribution():
    # Even split across groups → no concentration signal (no false Pareto alarm).
    cols = ["category", "gmv"]
    rows = [["A", 20], ["B", 20], ["C", 20], ["D", 20], ["E", 20]]
    out = analyze_query_result(cols, rows)
    assert not any(s.type == "contribution" for s in out)
