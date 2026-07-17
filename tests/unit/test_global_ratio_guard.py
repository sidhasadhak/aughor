"""Global-ratio plausibility guard — the conditioned-denominator catch (fix 1+2, 2026-07-09).

Deep-Analysis audit finding (inv1, CATASTROPHIC): a "why is the Fragrance refund RATE so high?"
scan generated per-dimension SQL that used the EVENT table (refunds) as the JOIN BASE and
INNER-joined the population (revenue) onto it — so every segment's denominator counted only orders
that HAD a refund. The scan reported a ~73% refund rate (true ≈ 10%) and told the user their premise
was INVERTED. No fan-out/saturation guard caught it (values sit inside [0,100], no row multiplication).
This guard computes the metric's TRUE global level independently — each aggregate over its own full
table — and suppresses the ratio when every segment is implausibly far above it.
See _global_ratio_plausibility_guard in aughor/agent/investigate.py.
"""
import json

import duckdb
import pytest

from aughor.agent.investigate import (
    _parse_ratio_sources,
    _independent_global_ratio,
    _global_ratio_plausibility_guard,
)

INV1_METRIC_SQL = (
    "SUM(analytics.refunds.refund_amount_usd) / "
    "NULLIF(SUM(analytics.order_items.line_revenue_usd), 0) * 100"
)


class _Shim:
    """Minimal conn.execute(tag, sql) -> obj with .rows/.columns/.error over a read-only DuckDB."""

    def __init__(self, path):
        self._c = duckdb.connect(path, read_only=True)

    def execute(self, tag, sql):
        r = type("R", (), {})()
        try:
            cur = self._c.execute(sql)
            r.rows = cur.fetchall()
            r.columns = [d[0] for d in cur.description]
            r.error = None
        except Exception as e:  # noqa: BLE001
            r.rows, r.columns, r.error = [], [], str(e)
        return r


@pytest.fixture
def conn(tmp_path):
    """100 orders @ $100 revenue; first 20 refunded @ $50. True global refund rate = 1000/10000 = 10%."""
    p = str(tmp_path / "bc.duckdb")
    c = duckdb.connect(p)
    c.execute("CREATE SCHEMA analytics")
    c.execute("CREATE TABLE analytics.order_items(order_id INT, line_revenue_usd DOUBLE)")
    c.execute("CREATE TABLE analytics.refunds(order_id INT, refund_amount_usd DOUBLE)")
    c.execute("INSERT INTO analytics.order_items SELECT range, 100.0 FROM range(100)")
    c.execute("INSERT INTO analytics.refunds SELECT range, 50.0 FROM range(20)")
    c.close()
    return _Shim(p)


# ── parser ─────────────────────────────────────────────────────────────────────

def test_parses_qualified_cross_table_ratio():
    s = _parse_ratio_sources(INV1_METRIC_SQL)
    assert s is not None
    assert s["num_table"] == "analytics.refunds" and s["num_col"] == "refund_amount_usd"
    assert s["den_table"] == "analytics.order_items" and s["den_col"] == "line_revenue_usd"
    assert s["scale"] == 100.0


def test_parser_rejects_same_table_ratio():
    # same-table ratio is not a cross-table population rate → no conditioned-denominator risk
    assert _parse_ratio_sources("SUM(orders.a) / SUM(orders.b)") is None


def test_parser_rejects_non_ratio_and_ambiguous():
    assert _parse_ratio_sources("SUM(orders.revenue)") is None
    assert _parse_ratio_sources("SUM(a.x)/SUM(b.y)/SUM(c.z)") is None   # >1 division


def test_parser_accepts_unqualified_columns():
    """LLM non-determinism: the metric formula is sometimes written with BARE columns (no table
    prefix). The parser must still capture them (tables resolved later via information_schema)."""
    s = _parse_ratio_sources("SUM(refund_amount_usd) / NULLIF(SUM(line_revenue_usd), 0) * 100")
    assert s is not None
    assert s["num_table"] is None and s["num_col"] == "refund_amount_usd"
    assert s["den_table"] is None and s["den_col"] == "line_revenue_usd"
    assert s["scale"] == 100.0


# ── independent global ─────────────────────────────────────────────────────────

def test_independent_global_is_population_level(conn):
    g = _independent_global_ratio(conn, _parse_ratio_sources(INV1_METRIC_SQL))
    assert g == pytest.approx(10.0, abs=0.01)


# ── the guard ──────────────────────────────────────────────────────────────────

def _findings(vals):
    return [{
        "columns": ["segment", "metric_total"],
        "rows": [[f"s{i}", str(v)] for i, v in enumerate(vals)],
        "key_numbers": [{"label": "x", "value": f"{vals[0]}%"}],
        "interpretation": "original interpretation",
        "chart_type": "bar_horizontal",
    }]


def test_guard_fires_on_conditioned_denominator(conn):
    """Every segment ~50% while the true global is 10% → systematic inflation → suppress."""
    findings = _findings([50.0, 48.0, 52.0, 49.0])
    res = _global_ratio_plausibility_guard(findings, conn, INV1_METRIC_SQL, "refund rate")
    assert res is not None
    assert "10.0%" in res["caveat"]             # states the TRUE global
    assert "conditioned denominator" in res["caveat"].lower()
    assert res["true_global_str"] == "10.0%"    # structured, so synthesis can cite it


def test_guard_fires_with_unqualified_metric_sql(conn):
    """The catch must also work when the metric formula names columns UNQUALIFIED (the live inv1
    re-run shape) — the tables are resolved from information_schema."""
    unqualified = "SUM(refund_amount_usd) / NULLIF(SUM(line_revenue_usd), 0) * 100"
    findings = _findings([73.0, 79.0, 85.0])
    res = _global_ratio_plausibility_guard(findings, conn, unqualified, "refund rate")
    assert res is not None
    assert "10.0%" in res["caveat"]


def test_guard_silent_on_plausible_spread(conn):
    """A real spread around the 10% global (one high segment, others near it) must NOT fire —
    that is legitimate signal, not a computation artifact."""
    findings = _findings([8.0, 14.0, 11.0, 9.0, 22.0])   # min 8% < 2.5×10% = 25%
    assert _global_ratio_plausibility_guard(findings, conn, INV1_METRIC_SQL, "refund rate") is None


def test_guard_suppresses_numbers_when_it_fires(conn):
    """When it fires, the corrupted key_numbers are cleared and the chart dropped, so the artifact
    numbers cannot reach the synthesis headline."""
    findings = _findings([73.0, 79.0, 85.0])
    from aughor.agent.investigate import _suppress_fanned_ratio
    res = _global_ratio_plausibility_guard(findings, conn, INV1_METRIC_SQL, "refund rate")
    assert res is not None
    # mirror the wiring: guard returns {caveat, ...}; caller suppresses with the caveat text
    _suppress_fanned_ratio(findings, "refund rate", res["caveat"])
    assert findings[0]["key_numbers"] == []
    assert findings[0]["chart_type"] == "none"


def test_guard_noop_when_global_unavailable(tmp_path):
    """If the true global can't be computed (missing table), the guard must no-op, never crash."""
    p = str(tmp_path / "empty.duckdb")
    duckdb.connect(p).close()
    shim = _Shim(p)
    findings = _findings([50.0, 60.0])
    assert _global_ratio_plausibility_guard(findings, shim, INV1_METRIC_SQL, "refund rate") is None


# ── Terminal suppression: propagate to every phase, and stop the caveat repeating ────────────
# The flags-on soak (inv 8f9ca261) shipped a report whose executive summary + a temporal tile
# cited "58.83%" while the report ELSEWHERE flagged the true rate as 2.8% and the values as
# artifacts. Cause: suppression was local to the cross-section guard; the temporal phase computed
# its own corrupt value and sailed through, and the one caveat rendered ~8×.

from aughor.agent.investigate import (
    _scrub_suppressed_metric_everywhere,
    _dedupe_repeated_caveats,
    _norm_measure,
)

_SUPPRESSED = {"metric_label": "refund leakage rate (%)",
               "caveat": "metric-computation error: conditioned denominator; true global 2.8%.",
               "true_global_str": "2.8%"}


def test_scrub_neutralises_the_same_metric_in_another_phase():
    """The temporal tile + line chart of the suppressed metric must be scrubbed: no chart, no
    key number, and the interpretation prose that quoted 58.83% replaced."""
    phases = [{
        "phase_id": "temporal_when",
        "findings": [{
            "title": "Single Data Point Available",
            "columns": ["period", "refund leakage rate (%)", "records"],
            "chart_type": "line",
            "key_numbers": [{"label": "June 2024 Refund Leakage Rate", "value": "58.8%"}],
            "interpretation": "The refund leakage rate for June 2024 is 58.83%, a high level.",
            "trust_caveat": None,
        }],
    }]
    n = _scrub_suppressed_metric_everywhere(phases, _SUPPRESSED)
    f = phases[0]["findings"][0]
    assert n == 1
    assert f["chart_type"] == "none"
    assert f["key_numbers"] == []                       # the 58.8% tile is gone
    assert "58.83" not in f["interpretation"]           # the artifact number is gone from prose
    assert f["trust_caveat"] == _SUPPRESSED["caveat"]


def test_scrub_leaves_a_different_metric_untouched():
    """A co-located finding about a DIFFERENT measure (refund-type share) is real signal and must
    survive — only the suppressed metric is neutralised."""
    phases = [{
        "phase_id": "cross_section_mechanism",
        "findings": [{
            "title": "Full refunds dominate refund types",
            "columns": ["refund_type", "share of refunds", "records"],
            "chart_type": "bar_horizontal",
            "key_numbers": [{"label": "Full Refunds", "value": "60.7%"}],
            "interpretation": "Full refunds are 60.7% of refund events.",
            "trust_caveat": None,
        }],
    }]
    n = _scrub_suppressed_metric_everywhere(phases, _SUPPRESSED)
    f = phases[0]["findings"][0]
    assert n == 0
    assert f["chart_type"] == "bar_horizontal" and f["key_numbers"]   # untouched


def test_scrub_skips_findings_already_suppressed_at_source():
    """The cross-section findings the guard already cleared (chart none + no key numbers) are not
    re-counted — the scrub only reaches the phases the guard never touched."""
    phases = [{"phase_id": "cross_section",
               "findings": [{"columns": ["seg", "refund leakage rate (%)", "n"],
                             "chart_type": "none", "key_numbers": [], "interpretation": "x"}]}]
    assert _scrub_suppressed_metric_everywhere(phases, _SUPPRESSED) == 0


def test_dedupe_collapses_the_repeated_caveat_and_interpretation():
    """One honest detection, rendered once. Five identical caveats → the first survives, the rest
    blank; the identical suppression interpretation collapses to a back-reference."""
    honest = "refund leakage rate could not be computed reliably across the scanned dimensions."
    phases = [{"phase_id": "cross_section", "findings": [
        {"trust_caveat": _SUPPRESSED["caveat"], "interpretation": honest} for _ in range(5)
    ]}]
    _dedupe_repeated_caveats(phases)
    fs = phases[0]["findings"]
    assert sum(1 for f in fs if f["trust_caveat"]) == 1          # caveat box shows once
    assert fs[0]["interpretation"] == honest
    assert all("See the note above" in f["interpretation"] for f in fs[1:])


def test_dedupe_keeps_distinct_real_interpretations():
    """A real per-finding interpretation is never an exact repeat — dedupe must not touch it."""
    phases = [{"phase_id": "p", "findings": [
        {"trust_caveat": None, "interpretation": "Corporate leaks fastest at 3.4%."},
        {"trust_caveat": None, "interpretation": "First class leaks at 3.56%."},
    ]}]
    _dedupe_repeated_caveats(phases)
    assert phases[0]["findings"][0]["interpretation"] == "Corporate leaks fastest at 3.4%."
    assert phases[0]["findings"][1]["interpretation"] == "First class leaks at 3.56%."


def test_norm_measure_matches_across_label_and_column_spellings():
    assert _norm_measure("Refund Leakage Rate (%)") == _norm_measure("refund_leakage_rate")
    assert _norm_measure("June 2024 Refund Leakage Rate").find(_norm_measure("refund leakage rate")) >= 0
    assert _norm_measure("share of refunds") != _norm_measure("refund leakage rate")


def test_terminal_suppression_on_the_real_broken_report_shape():
    """End-to-end over the exact multi-phase shape that shipped broken (inv 8f9ca261): a
    suppressed cross-section, a temporal tile that escaped with 58.8%, and the caveat on 5
    findings. After scrub + dedup: the artifact appears NOWHERE, and the caveat renders once."""
    phases = [
        {"phase_id": "cross_section", "findings": [
            {"title": "Refund leakage by channel", "columns": ["segment", "refund leakage rate (%)", "n"],
             "chart_type": "none", "key_numbers": [],
             "interpretation": "refund leakage rate (%) could not be computed reliably: fan-out.",
             "trust_caveat": _SUPPRESSED["caveat"]},
            {"title": "By cabin", "columns": ["segment", "refund leakage rate (%)", "n"],
             "chart_type": "none", "key_numbers": [],
             "interpretation": "refund leakage rate (%) could not be computed reliably: fan-out.",
             "trust_caveat": _SUPPRESSED["caveat"]},
        ]},
        {"phase_id": "temporal_when", "findings": [
            {"title": "Single Data Point Available",
             "columns": ["period", "refund leakage rate (%)", "records"], "chart_type": "line",
             "key_numbers": [{"label": "June 2024 Refund Leakage Rate", "value": "58.8%"}],
             "interpretation": "The refund leakage rate for June 2024 is 58.83%, a high level.",
             "trust_caveat": None},
        ]},
        {"phase_id": "cross_section_mechanism", "findings": [
            {"title": "Full refunds dominate", "columns": ["refund_type", "share of refunds", "records"],
             "chart_type": "bar_horizontal",
             "key_numbers": [{"label": "Full Refunds", "value": "60.7%"}],
             "interpretation": "Full refunds are 60.7% of refund events.", "trust_caveat": None},
        ]},
    ]
    _scrub_suppressed_metric_everywhere(phases, _SUPPRESSED)
    _dedupe_repeated_caveats(phases)

    blob = json.dumps(phases)
    # P0: the 58.x artifact is gone from every tile, chart and prose.
    assert "58.8" not in blob and "58.83" not in blob
    temporal = phases[1]["findings"][0]
    assert temporal["chart_type"] == "none" and temporal["key_numbers"] == []
    # The unrelated refund-type share survives untouched.
    mech = phases[2]["findings"][0]
    assert mech["chart_type"] == "bar_horizontal" and mech["key_numbers"][0]["value"] == "60.7%"
    # P1: the caveat renders once, not on all three suppressed findings.
    cav_boxes = [f for ph in phases for f in ph["findings"] if f.get("trust_caveat")]
    assert len(cav_boxes) == 1
