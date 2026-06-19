"""Unit tests for metric moves — north-star trends as brief candidates."""
from aughor.knowledge.metric_moves import (
    series_move, build_move_finding, compute_metric_moves, Move,
)
from aughor.knowledge.triage import extract_change, impact_score, north_star_tokens


# ── series_move (pure) ─────────────────────────────────────────────────────────

MARGIN_TREND = (
    ["month", "gross_margin_pct"],
    [["Jan 2022", 50.0], ["Mar 2022", 49.0], ["May 2022", 47.0],
     ["Sep 2022", 49.0], ["Nov 2022", 43.0], ["Dec 2022", 34.0]],
)
REPEAT_TREND = (
    ["signup_month", "repeat_rate"],
    [["Jan 2022", 0.05], ["May 2022", 0.08], ["Sep 2022", 0.13], ["Dec 2022", 0.15]],
)
BREAKDOWN = (
    ["category", "turns"],
    [["Fragrance", 16.9], ["Skincare", 12.1], ["Haircare", 9.4], ["Makeup", 5.0]],
)


def test_margin_decline_move():
    mv = series_move(*MARGIN_TREND)
    assert mv is not None and mv.direction == "down"
    assert abs(mv.rel - (34.0 - 50.0) / 50.0) < 1e-9   # -32%


def test_repeat_rise_move():
    mv = series_move(*REPEAT_TREND)
    assert mv is not None and mv.direction == "up"
    assert mv.rel > 1.0   # tripled


def test_breakdown_is_not_a_move():
    # Category labels are not time buckets — never treated as a trend.
    assert series_move(*BREAKDOWN) is None


def test_short_series_skipped():
    assert series_move(["m", "v"], [["Jan 2022", 1.0], ["Feb 2022", 2.0]]) is None


def test_zero_baseline_skipped():
    assert series_move(["m", "v"], [["Jan 2022", 0.0], ["Feb 2022", 1.0], ["Mar 2022", 2.0]]) is None


# ── build_move_finding + round-trip through impact ranking ─────────────────────

def test_margin_finding_text_and_currency_neutral_percent():
    mv = series_move(*MARGIN_TREND)
    f = build_move_finding("Gross Margin Rate", "percent 0-100", mv, "EUR")
    assert "from 50% to 34%" in f["finding"]
    assert "-32%" in f["finding"]
    assert f["metric_move"] is True


def test_aov_finding_uses_euro_symbol():
    mv = series_move(["month", "aov"],
                     [["Jan 2022", 75.0], ["Jun 2022", 70.0], ["Dec 2022", 56.0]])
    f = build_move_finding("Average Order Value", "EUR", mv, "EUR")
    assert "from €75 to €56" in f["finding"]


def test_move_finding_scores_high_on_impact():
    # The synthesised text must round-trip through extract_change so it scores by magnitude.
    ns = north_star_tokens(["Gross Margin Rate", "Repeat Purchase Rate", "Average Order Value"])
    mv = series_move(*MARGIN_TREND)
    f = build_move_finding("Gross Margin Rate", "percent 0-100", mv, "EUR")
    ch = extract_change(f["finding"])
    assert ch is not None and ch.rel > 0.25
    score = impact_score(f["finding"], f["novelty"], f["confidence"], ns)
    assert score > 0.5   # a real swing on a watched metric → headline-worthy


def test_euro_move_change_parses_through_currency():
    # Currency-tolerant extract_change: "from €75 to €56" must parse, not break.
    ch = extract_change("Average Order Value has fallen from €75 to €56 (-25%) over the period.")
    assert ch is not None and ch.big == 75.0 and ch.small == 56.0


# ── compute_metric_moves (driver, injected run_sql) ────────────────────────────

def test_degenerate_near_zero_move_is_dropped():
    # The live missimi bug: a repeat-rate trend of tiny fractions formats to "0% → 1%".
    # The +40% relative is an artifact of a near-zero base and must not surface.
    from aughor.knowledge.metric_moves import is_degenerate_move
    mv = series_move(["m", "v"], [["Jan 2022", 0.004], ["Jun 2022", 0.005], ["Dec 2022", 0.006]])
    assert mv is not None and mv.rel > 0.3          # +50% relative…
    assert is_degenerate_move(mv, "Repeat Purchase Rate", "ratio 0-1", "EUR")  # …but degenerate


def test_real_repeat_move_not_degenerate():
    mv = series_move(*REPEAT_TREND)   # 0.05 → 0.15 (5% → 15%)
    from aughor.knowledge.metric_moves import is_degenerate_move
    assert not is_degenerate_move(mv, "Repeat Purchase Rate", "ratio 0-1", "EUR")


def test_compute_drops_degenerate_lets_margin_lead():
    metrics = [
        {"name": "Repeat Purchase Rate", "unit_or_range": "ratio 0-1", "chart_sql": "Q_TINY"},
        {"name": "Gross Margin Rate", "unit_or_range": "percent 0-100", "chart_sql": "Q_MARGIN"},
    ]
    series = {
        "Q_TINY": (["m", "v"], [["Jan 2022", 0.004], ["Jun 2022", 0.005], ["Dec 2022", 0.006]], None),
        "Q_MARGIN": (MARGIN_TREND[0], MARGIN_TREND[1], None),
    }
    moves = compute_metric_moves(metrics, lambda sql: series[sql], currency_code="EUR")
    names = [m["finding"].split(" has ")[0] for m in moves]
    assert names == ["Gross Margin Rate"]   # tiny-base repeat move dropped; margin leads


def test_compute_metric_moves_ranks_biggest_first_and_skips_breakdowns():
    metrics = [
        {"name": "Gross Margin Rate", "unit_or_range": "percent 0-100", "chart_sql": "Q_MARGIN"},
        {"name": "Repeat Purchase Rate", "unit_or_range": "ratio 0-1", "chart_sql": "Q_REPEAT"},
        {"name": "Category Turns", "unit_or_range": "ratio 0-inf", "chart_sql": "Q_BREAKDOWN"},
        {"name": "Broken Metric", "unit_or_range": "USD", "chart_sql": "Q_ERR"},
    ]
    series = {
        "Q_MARGIN": (MARGIN_TREND[0], MARGIN_TREND[1], None),
        "Q_REPEAT": (REPEAT_TREND[0], REPEAT_TREND[1], None),
        "Q_BREAKDOWN": (BREAKDOWN[0], BREAKDOWN[1], None),
        "Q_ERR": ([], [], "boom"),
    }
    moves = compute_metric_moves(metrics, lambda sql: series[sql], currency_code="EUR")
    names = [m["finding"].split(" has ")[0] for m in moves]
    assert names == ["Repeat Purchase Rate", "Gross Margin Rate"]   # tripled > -32%, breakdown/err dropped
    assert all(m["sql"] for m in moves)   # chart_sql attached
