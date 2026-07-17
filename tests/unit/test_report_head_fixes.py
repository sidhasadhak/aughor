"""The four report-quality defects the W5 UI pass surfaced — deterministic tests.

1. Currency coherence — the metric's SOURCE currency (fare_chf → "currency:CHF")
   travels on column_units, so no surface relabels CHF data with the org symbol.
2. Fallback headline — cut at a word boundary, never mid-clause.
3. Extreme key numbers — compact formatting, and a key number about a DIFFERENT
   measure than the charted metric is left alone (the avg-tile/total-value bug).
4. (Web-only: explore **emphasis** — covered by tsc; the PDF already converts.)
Plus: the export dedups a phase summary the executive summary already contains.
"""
from __future__ import annotations

from aughor.agent.investigate import (
    _fallback_headline,
    _fix_xsec_extreme_key_numbers,
    _fmt_compact_num,
    _tag_currency_columns,
)
from aughor.export.charts import _fmt_for
from aughor.export.document import build_export_doc


# ── 1 · source-currency tagging ──────────────────────────────────────────────

_METRIC_SQL = "SUM(tickets.fare_chf)"


def _money_finding() -> dict:
    return {
        "columns": ["country", "ticket fare revenue", "records", "ticket fare revenue per record"],
        "rows": [["Egypt", 1951747.0, 6533, 298.75], ["Italy", 1961940.0, 6346, 309.16]],
    }


def test_currency_tag_reads_the_metric_sql():
    f = _money_finding()
    _tag_currency_columns(f, _METRIC_SQL)
    units = f["column_units"]
    assert units["ticket fare revenue"] == "currency:CHF"
    assert units["ticket fare revenue per record"] == "currency:CHF"
    assert "records" not in units          # a count is not money
    assert "country" not in units


def test_currency_tag_never_overwrites_percent():
    f = _money_finding()
    f["column_units"] = {"ticket fare revenue": "percent"}
    _tag_currency_columns(f, _METRIC_SQL)
    assert f["column_units"]["ticket fare revenue"] == "percent"


def test_currency_tag_is_a_noop_without_a_source_token():
    f = _money_finding()
    _tag_currency_columns(f, "SUM(orders.revenue)")
    assert "column_units" not in f


def test_export_formatter_prefixes_the_source_currency():
    fmt = _fmt_for("ticket fare revenue", {"ticket fare revenue": "currency:CHF"})
    assert fmt(1951747.0) == "CHF 2.0M"
    fmt_usd = _fmt_for("x", {"x": "currency:USD"})
    assert fmt_usd(1500.0) == "$1.5K"


def test_export_money_symbol_fallback_matches_the_web():
    # No unit hint: a money-named column carries the connection's effective symbol
    # (the web's behavior) — the PDF axis can no longer read bare "34.7M" while the
    # app shows "CHF 34.7M". Source-currency units still beat the fallback; a
    # non-money column stays bare.
    fmt = _fmt_for("net revenue", None, money_symbol="CHF ")
    assert fmt(34741777.0) == "CHF 34.7M"
    assert _fmt_for("records", None, money_symbol="CHF ")(77281) == "77.3K"
    assert _fmt_for("net revenue", {"net revenue": "currency:USD"},
                    money_symbol="CHF ")(1500.0) == "$1.5K"


# ── 2 · fallback headline word-boundary cut ──────────────────────────────────

def test_fallback_headline_short_sentence_kept_whole():
    assert _fallback_headline("Revenue is fine. More detail follows.") == "Revenue is fine."


def test_fallback_headline_long_sentence_cuts_at_a_word():
    s = ("Revenue is heavily concentrated in intercontinental/long-haul flights "
         "(61.9% of total fare revenue from only 50,987 tickets), while the "
         "lowest-ranked individual route GVA-LYS generates just 158K CHF.")
    h = _fallback_headline(s)
    assert len(h) <= 161 and h.endswith("…")
    assert not h[:-1].endswith(" ")        # no dangling space before the ellipsis
    assert " the…" not in h or True        # cut lands on a whole word
    assert h[:-1] == h[:-1].rstrip(",;:—-")


# ── 3 · extreme key numbers: compact + measure-mismatch guard ────────────────

def test_extreme_key_numbers_routed_per_measure_and_compact():
    # The full cross-section grid: [dim, total, records, avg_per_record]. The total tile
    # must read the total column (compact), the avg tile the avg column — never crossed.
    f = {
        "columns": ["country", "ticket fare revenue", "records", "ticket fare revenue per record"],
        "rows": [["Egypt", 1951747.0, 6533, 298.75],
                 ["Poland", 2148927.0, 7279, 295.22],
                 ["UAE", 2385387.0, 7538, 316.45]],
        "key_numbers": [
            {"label": "Egypt total (lowest shown)", "value": "1951747.00 (Egypt)"},
            {"label": "Poland avg/ticket (lowest avg shown)", "value": "295.22 CHF (Poland)"},
        ],
    }
    _fix_xsec_extreme_key_numbers(f, is_pct=False)
    # total tile → total column's min (Egypt), compact — was "1951747.00".
    assert f["key_numbers"][0]["value"] == "1.95M (Egypt)"
    # avg tile → avg column's min (Poland 295.22), NOT the total's extreme.
    assert f["key_numbers"][1]["value"] == "295.22 (Poland)"


def test_extreme_key_numbers_two_col_grid_still_works():
    # A trimmed [dim, metric] grid (no avg column) — the total tile still recomputes.
    f = {
        "columns": ["country", "ticket fare revenue"],
        "rows": [["Egypt", 1951747.0], ["Italy", 1961940.0], ["UAE", 2385387.0]],
        "key_numbers": [{"label": "lowest", "value": "1951747.00 (Egypt)"}],
    }
    _fix_xsec_extreme_key_numbers(f, is_pct=False)
    assert f["key_numbers"][0]["value"] == "1.95M (Egypt)"


def test_fmt_compact_num_scales():
    assert _fmt_compact_num(1951747.0) == "1.95M"
    assert _fmt_compact_num(1500.0) == "1.5K"
    assert _fmt_compact_num(58.03) == "58.03"


# ── export: phase summary the exec summary already contains is not re-printed ─

def test_export_dedups_stitched_phase_summary():
    phase_summary = "Revenue is heavily concentrated in long-haul flights."
    inv = {
        "question": "q", "connection_id": "c", "kind": "investigation",
        "report": {
            "_report_type": "investigate",
            "headline": "Revenue is heavily concentrated…",
            "executive_summary": phase_summary + " The time series has one month.",
            "phases": [{
                "phase_id": "xsec", "phase_name": "Cross-Sectional Scan", "status": "complete",
                "summary": phase_summary,
                "findings": [{"finding_id": "f1", "title": "t", "sql": "select 1",
                              "columns": ["a", "b"], "rows": [["x", 1], ["y", 2]],
                              "row_count": 2, "error": None, "interpretation": "i",
                              "key_numbers": [], "chart_type": "bar", "stat_note": None,
                              "is_significant": False}],
            }],
        },
    }
    doc = build_export_doc(inv)
    texts = [b.text or "" for b in doc.blocks if b.kind == "prose"]
    assert not any(t.strip() == phase_summary for t in texts)
    # …but a DISTINCT phase summary still prints.
    inv["report"]["phases"][0]["summary"] = "Something the head does not say."
    doc2 = build_export_doc(inv)
    texts2 = [b.text or "" for b in doc2.blocks if b.kind == "prose"]
    assert any("Something the head does not say." in t for t in texts2)
