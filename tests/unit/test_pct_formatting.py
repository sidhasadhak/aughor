"""Backend half of the percentage-consistency fix (report issue #1, approach a).

A ratio metric (return rate) is stored as a fraction (0.4096) but must read "41.0%" on every
surface. These pin: the scale-aware formatter, the percent-metric detector, the key-number rebuild
(so a section value can't read "0.41%" beside a "41.0%" bar), and the column_units unit hint.
"""
from __future__ import annotations

import aughor.agent.investigate as I


# ── scale-aware formatter ────────────────────────────────────────────────────────

def test_fmt_pct_scale_aware():
    assert I._fmt_pct(0.4096) == "41.0%"     # fraction → ×100
    assert I._fmt_pct(40.96) == "41.0%"      # already-scaled percent → as-is
    assert I._fmt_pct(0.05) == "5.0%"
    assert I._fmt_pct(1.0) == "100.0%"
    assert I._fmt_pct("nan-ish") == "nan-ish"  # non-numeric passthrough


def test_metric_is_percent_distinguishes_rate_from_average():
    assert I._metric_is_percent("AVG(is_returned)", "return rate") is True
    assert I._metric_is_percent("SUM(a)/SUM(b)", "conversion") is True         # composite ratio
    assert I._metric_is_percent("AVG(discount)*100", "discount %") is True
    assert I._metric_is_percent("AVG(rating)", "average rating") is False      # a plain mean, not a %
    assert I._metric_is_percent("SUM(revenue)", "revenue") is False
    # value-based fallback: a bare proportion in [0,1] reads as a percent even with a vague label
    assert I._metric_is_percent("AVG(flag)", "flagged", values=[0.1, 0.4, 0.9]) is True
    assert I._metric_is_percent("AVG(x)", "score", values=[1.0, 3.0, 4.5]) is False


# ── key-number rebuild ───────────────────────────────────────────────────────────

def test_normalize_pct_key_numbers_unifies_scale_and_precision():
    f = {"columns": ["brand", "metric_total"], "rows": [["x", 0.4096]], "key_numbers": [
        {"label": "Return rate", "value": "0.41%"},     # mis-scaled percent → 41.0%
        {"label": "Subject", "value": "0.4096"},          # bare fraction → 41.0%
        {"label": "UK rate", "value": "32.31% return rate (15,612 / 48,320 items)"},  # 2-dp → 1-dp, tail kept
        {"label": "n", "value": "5000"},                  # a count → untouched (never "5000%")
        {"label": "AOV", "value": "42.50"},               # >1 bare, no % → untouched
        {"label": "Highest", "value": "40.5%"},           # already canonical → unchanged (idempotent)
    ]}
    I._normalize_pct_key_numbers(f)
    got = {k["label"]: k["value"] for k in f["key_numbers"]}
    assert got == {"Return rate": "41.0%", "Subject": "41.0%",
                   "UK rate": "32.3% return rate (15,612 / 48,320 items)",
                   "n": "5000", "AOV": "42.50", "Highest": "40.5%"}


def test_normalize_pct_key_numbers_preserves_percentage_points():
    """A percentage-POINTS value ("0.36pp") is a spread/gap between two shares — already absolute.
    The ratio→percent ×100 heuristic (value ≤ 1 → fraction) wrongly turned "0.36pp" into "36.0%pp"
    (the reason-drill '#1 vs #12 brand' spread bug). pp values must pass through untouched, while
    ordinary fractions/percents still normalize."""
    f = {"key_numbers": [
        {"label": "Spread between #1 and #12 brand", "value": "0.36pp"},   # was corrupted → 36.0%pp
        {"label": "Gap", "value": "1.5 pp"},                               # spaced pp → untouched
        {"label": "Subject", "value": "0.4096"},                           # bare fraction → 41.0% (unaffected)
        {"label": "Rate", "value": "0.41%"},                               # mis-scaled % → 41.0% (unaffected)
    ]}
    I._normalize_pct_key_numbers(f)
    got = {k["label"]: k["value"] for k in f["key_numbers"]}
    assert got == {"Spread between #1 and #12 brand": "0.36pp", "Gap": "1.5 pp",
                   "Subject": "41.0%", "Rate": "41.0%"}


def test_fix_xsec_extreme_key_numbers_is_scale_aware_when_pct():
    f = {"columns": ["brand", "metric_total"], "rows": [["a", 0.27], ["b", 0.405]],
         "key_numbers": [{"label": "Highest (top 1)", "value": "40.5%"},
                         {"label": "Lowest", "value": "0.27"}]}
    I._fix_xsec_extreme_key_numbers(f, is_pct=True)
    got = {k["label"]: k["value"] for k in f["key_numbers"]}
    # extremes recomputed from the rows, scale-aware, with the dimension appended
    assert got["Highest"] == "40.5% (b)"
    assert got["Lowest"] == "27.0% (a)"


def test_fix_xsec_extreme_non_pct_unchanged_behaviour():
    # A non-percent metric keeps the legacy 2dp formatting (no accidental scaling).
    f = {"columns": ["region", "metric_total"], "rows": [["n", 120.0], ["s", 340.0]],
         "key_numbers": [{"label": "Highest", "value": "340"}]}
    I._fix_xsec_extreme_key_numbers(f, is_pct=False)
    assert f["key_numbers"][0]["value"] == "340.00 (s)"


# ── column_units unit hint ───────────────────────────────────────────────────────

def test_normalize_pct_key_numbers_collapses_llm_duplicate_and_approx():
    # The temporal WHEN lens emits messy LLM strings — a leading "~" and a redundant "(value)"
    # duplicate. Collapse each to ONE canonical percent while keeping meaningful parentheticals.
    f = {"key_numbers": [
        {"label": "Series average", "value": "~0.328 (32.8%)"},   # ~ + fraction + dup → ~32.8%
        {"label": "Highest visible month", "value": "34.5%(34.5%)"},  # exact dup → 34.5%
        {"label": "Lowest visible month", "value": "31.2%(31.3%)"},   # near dup → keep first
        {"label": "Gap", "value": "~13.5 pts"},                    # points, not % → untouched
        {"label": "UK", "value": "32.31% return rate (15,612 / 48,320 items)"},  # keep context tail
        {"label": "Germany", "value": "41.0% (Germany)"},          # keep dimension tail
    ]}
    I._normalize_pct_key_numbers(f)
    got = {k["label"]: k["value"] for k in f["key_numbers"]}
    assert got == {
        "Series average": "~32.8%", "Highest visible month": "34.5%",
        "Lowest visible month": "31.2%", "Gap": "~13.5 pts",
        "UK": "32.3% return rate (15,612 / 48,320 items)", "Germany": "41.0% (Germany)"}


def test_apply_percent_formatting_tags_columns_and_normalizes_keys():
    # The wiring the cross-section post-loop runs: a percent finding gets its metric column tagged
    # AND its key numbers canonicalised, in one call.
    f = {"columns": ["platform", "metric_total"], "rows": [["Germany", 0.4096], ["Italy", 0.2691]],
         "key_numbers": [{"label": "Germany (highest)", "value": "0.41%"},
                         {"label": "UK", "value": "32.31% return rate (15,612 / 48,320 items)"}]}
    I._apply_percent_formatting(f, is_pct=True)
    assert f["column_units"] == {"metric_total": "percent"}
    vals = [k["value"] for k in f["key_numbers"]]
    assert vals == ["41.0%", "32.3% return rate (15,612 / 48,320 items)"]


def test_apply_percent_formatting_noop_for_non_percent():
    f = {"columns": ["region", "metric_total"], "rows": [["n", 340.0]],
         "key_numbers": [{"label": "Highest", "value": "340"}]}
    {k: list(v) if isinstance(v, list) else v for k, v in f.items()}
    I._apply_percent_formatting(f, is_pct=False)
    assert "column_units" not in f                       # untouched
    assert f["key_numbers"][0]["value"] == "340"          # untouched


def test_fix_temporal_extreme_key_numbers_matches_the_full_series():
    # The interpret LLM only saw the first rows and called a peak of 34.5% (Dec 2020); the real max is
    # 36.2% (Jul 2022) — recompute from ALL rows so the key numbers match the chart.
    rows = [["2020-07-01", 0.321, 1700], ["2020-12-01", 0.345, 2000],
            ["2021-03-01", 0.313, 2100], ["2022-07-01", 0.362, 2200], ["2023-01-01", 0.330, 2500]]
    f = {"columns": ["period", "metric_value", "n"], "rows": rows, "key_numbers": [
        {"label": "Peak month (Dec 2020)", "value": "34.5%", "delta": "+1.5 pts vs avg", "context": "Holiday"},
        {"label": "Trough month (May 2021)", "value": "31.3%", "delta": "-1.7 pts vs avg"},
        {"label": "Overall average return rate", "value": "~33.0%"},
        {"label": "Range across visible months", "value": "31.3% – 34.5%", "delta": "3.2 pts spread"},
    ]}
    I._fix_temporal_extreme_key_numbers(f, is_pct=True)
    by = {k["label"].split(" (")[0]: k for k in f["key_numbers"]}
    assert by["Peak month"]["value"] == "36.2%"          # the true series max
    assert "Jul 2022" in by["Peak month"]["label"]        # period corrected in the label
    assert by["Trough month"]["value"] == "31.3%"
    assert f["key_numbers"][2]["value"] == "~33.4%"       # avg over ALL rows
    assert f["key_numbers"][3]["value"] == "31.3% – 36.2%"  # range spans the real extremes


def test_chart_type_for_finding_by_intent():
    def _f(nrows, cols=("k", "pct_of_total")):
        return {"rows": [[i, 0.1] for i in range(nrows)], "columns": list(cols)}
    # composition: a donut for a few parts, a ranked bar once there are too many slices
    assert I._chart_type_for_finding(_f(3), "composition") == "pie"
    assert I._chart_type_for_finding(_f(6), "composition") == "pie"
    assert I._chart_type_for_finding(_f(9), "composition") == "bar_horizontal"
    assert I._chart_type_for_finding(_f(1), "composition") == "bar_horizontal"   # 1 slice isn't a pie
    assert I._chart_type_for_finding(_f(2), "relationship") == "scatter"
    # unknown intent → the finding's own type (or auto)
    assert I._chart_type_for_finding({"rows": [], "chart_type": "heatmap"}, "other") == "heatmap"


def test_chart_type_for_finding_is_shape_aware():
    def _f(cols):
        return {"rows": [[1, 2] for _ in range(8)], "columns": cols}
    # trend → line ONLY with a real date/period column, else degrade to auto (no forced line)
    assert I._chart_type_for_finding(_f(["order_month", "rate"]), "trend") == "line"
    assert I._chart_type_for_finding(_f(["brand", "rate"]), "trend") == "auto"
    # ranking → bar, but a CHANGE/contribution finding keeps auto (preserve the diverging bar)
    assert I._chart_type_for_finding(_f(["brand", "metric_total"]), "ranking") == "bar_horizontal"
    assert I._chart_type_for_finding(_f(["brand", "mom_change"]), "ranking") == "auto"
    assert I._chart_type_for_finding(_f(["brand", "contribution_pct"]), "ranking") == "auto"


def test_tag_percent_columns_marks_matching_columns():
    findings = [
        {"columns": ["reason", "event_count", "pct_of_total"], "column_units": {}},
        {"columns": ["carrier", "refund_share"]},
    ]
    import re
    I._tag_percent_columns(findings, re.compile(r"pct|percent|share", re.I))
    assert findings[0]["column_units"] == {"pct_of_total": "percent"}
    assert findings[1]["column_units"] == {"refund_share": "percent"}
    # a count column is never tagged
    assert "event_count" not in findings[0]["column_units"]
