"""Chart-grammar exhibit spec (flag `chart.exhibit_grammar`) — deterministic tests.

Covers the four legs of the grammar wave:
  W1 — the quick-path prompt no longer OFFERS combo under the flag (and the
       legacy constant stays byte-identical when it's off);
  W2 — the semantic color policy (severity ramp only for rate/percent rankings);
  W3 — reference lines (segment-weighted average, R15 benchmark, peer median),
       range-clipped so an out-of-range line can't distort the axis;
  W4 — the PRINT renderer speaks the same grammar: aughor/export/charts.py must
       honour the same exhibit + column_units, and stay byte-identical without them.
"""
from __future__ import annotations

from aughor.agent.exhibit import (
    attach_exhibit,
    clip_ref_lines,
    exhibit_for_cross_section,
    exhibit_for_lens,
    quick_exhibit,
)
from aughor.agent.opportunity import compute_opportunity, segment_rates
from aughor.agent.prompts import CHAT_SQL_SYSTEM, chat_sql_system
from aughor.export.charts import _fmt_for, _severity_ramp, render_chart


# ── W1: prompt variants ──────────────────────────────────────────────────────

def test_legacy_prompt_is_byte_identical():
    assert CHAT_SQL_SYSTEM == chat_sql_system(False)
    assert "'combo'" in CHAT_SQL_SYSTEM


def test_grammar_prompt_drops_combo_and_keeps_everything_else():
    g = chat_sql_system(True)
    assert "'combo'" not in g
    # The one-measure rule replaces the combo instructions…
    assert "Return ONE measure per chart" in g
    assert "Never pick a dual-axis presentation yourself" in g
    # …and every other section survives intact.
    for anchor in ("CHART SELECTION RULES", "HARD RULES", "SQL CORRECTNESS RULES",
                   "ANSWER SHAPE", "COMPOSITION (how parts make up a whole)"):
        assert anchor in g


# ── shared fixtures ──────────────────────────────────────────────────────────

def _xsec_finding() -> dict:
    return {
        "columns": ["segment", "metric_total", "n"],
        "rows": [["A", 0.10, 100], ["B", 0.20, 300], ["C", 0.40, 100]],
    }


# ── segment_rates factoring (opportunity.py) ─────────────────────────────────

def test_segment_rates_parses_the_cross_section_grid():
    f = _xsec_finding()
    segs = segment_rates(f["columns"], f["rows"], is_ratio=True)
    assert segs == [("A", 0.10, 100), ("B", 0.20, 300), ("C", 0.40, 100)]


def test_compute_opportunity_still_works_through_the_factored_parser():
    f = _xsec_finding()
    gap = compute_opportunity(f["columns"], f["rows"], is_ratio=True)
    assert gap is not None
    assert gap["best_segment"] == "C" and gap["worst_segment"] == "A"
    assert abs(gap["opportunity"] - 0.30 * 100) < 1e-9


# ── W3: ref-line clipping + attach semantics ─────────────────────────────────

def test_clip_ref_lines_drops_out_of_range_lines():
    values = [10.0, 12.0, 14.0]   # span 4, margin 2 → allowed [8, 16]
    lines = [
        {"value": 11.0, "label": "in", "kind": "global_avg"},
        {"value": 40.0, "label": "way out", "kind": "benchmark"},
    ]
    kept = clip_ref_lines(lines, values)
    assert [line["label"] for line in kept] == ["in"]


def test_attach_exhibit_writes_nothing_for_an_empty_spec():
    f = _xsec_finding()
    attach_exhibit(f, severity=False, ref_lines=[])
    assert "exhibit" not in f


def test_attach_exhibit_merges_and_dedups_ref_lines():
    f = _xsec_finding()
    attach_exhibit(f, ref_lines=[{"value": 0.22, "label": "avg", "kind": "global_avg"}])
    attach_exhibit(f, ref_lines=[{"value": 0.22, "label": "avg", "kind": "global_avg"},
                                 {"value": 0.40, "label": "bench", "kind": "benchmark"}])
    labels = [line["label"] for line in f["exhibit"]["ref_lines"]]
    assert labels == ["avg", "bench"]


# ── W2+W3: cross-section exhibit ─────────────────────────────────────────────

def test_cross_section_exhibit_severity_weighted_avg_and_benchmark():
    f = _xsec_finding()
    exhibit_for_cross_section(f, is_ratio=True, is_percent=True)
    spec = f["exhibit"]
    assert spec["color"] == {"mode": "severity"}
    by_kind = {line["kind"]: line for line in spec["ref_lines"]}
    # Weighted average: (0.10·100 + 0.20·300 + 0.40·100) / 500 = 0.22
    assert abs(by_kind["global_avg"]["value"] - 0.22) < 1e-9
    assert by_kind["benchmark"]["value"] == 0.40
    assert "C" in by_kind["benchmark"]["label"]


def test_cross_section_magnitude_ranking_stays_neutral():
    # An additive metric (is_percent=False): the bar length carries the message —
    # no severity ramp; ref lines may still be attached if the grid parses.
    f = _xsec_finding()
    exhibit_for_cross_section(f, is_ratio=True, is_percent=False)
    assert f.get("exhibit", {}).get("color") is None


def test_cross_section_exhibit_is_silent_on_an_unreadable_grid():
    f = {"columns": ["a", "b"], "rows": [["x", "y"]]}
    exhibit_for_cross_section(f, is_ratio=True, is_percent=True)
    assert "exhibit" not in f


# ── W3: peer-benchmark lens exhibit ──────────────────────────────────────────

def test_lens_exhibit_peer_median_and_severity():
    f = {
        "columns": ["peer", "leading_reason_share", "n"],
        "rows": [["p1", 30.0, 10], ["p2", 35.0, 10], ["p3", 40.0, 10],
                 ["p4", 45.0, 10], ["p5", 50.0, 10]],
        "column_units": {"leading_reason_share": "percent"},
    }
    exhibit_for_lens(f, peer_median=True)
    spec = f["exhibit"]
    assert spec["color"] == {"mode": "severity"}
    assert spec["ref_lines"][0]["label"] == "Peer median"
    assert spec["ref_lines"][0]["value"] == 40.0


def test_lens_exhibit_without_peer_median_gets_no_ref_lines():
    f = {
        "columns": ["product", "share_of_returns"],
        "rows": [["a", 10.0], ["b", 20.0], ["c", 30.0]],
    }
    exhibit_for_lens(f, peer_median=False)
    assert f["exhibit"]["color"] == {"mode": "severity"}
    assert "ref_lines" not in f["exhibit"]


# ── W2: quick-path exhibit ───────────────────────────────────────────────────

def test_quick_exhibit_rate_ranking_gets_severity():
    spec = quick_exhibit(["state", "return_rate"],
                         [["CA", 0.1], ["TX", 0.2], ["NY", 0.3], ["WA", 0.4]],
                         "bar_horizontal")
    assert spec == {"color": {"mode": "severity"}}


def test_quick_exhibit_magnitude_ranking_stays_neutral():
    assert quick_exhibit(["state", "revenue"],
                         [["CA", 10], ["TX", 20], ["NY", 30]], "bar_horizontal") is None


def test_quick_exhibit_two_measures_stays_neutral():
    # One measure per exhibit — a two-measure grid gets no severity claim.
    assert quick_exhibit(["state", "revenue", "return_rate"],
                         [["CA", 10, 0.1], ["TX", 20, 0.2], ["NY", 30, 0.3]],
                         "bar_horizontal") is None


def test_quick_exhibit_scatter_requests_point_labels():
    spec = quick_exhibit(["aircraft_id", "flights", "avg_delay"],
                         [["a", 1, 2], ["b", 3, 4], ["c", 5, 6]], "scatter")
    assert spec == {"label_points": True}


def test_quick_exhibit_needs_enough_rows():
    assert quick_exhibit(["state", "return_rate"], [["CA", 0.1], ["TX", 0.2]],
                         "bar_horizontal") is None


# ── W4: the export (print) renderer speaks the same grammar ──────────────────

_RANKING = (["route", "load_factor_pct"],
            [["GVA-DEL", 65.2], ["ZRH-EZE", 67.4], ["ZRH-BOS", 67.7], ["ZRH-BKK", 68.9]])


def test_export_severity_ramp_mirrors_the_web_ramp():
    # Same contract as web/components/charts/exhibit.ts severityRamp(): 3 stops,
    # ends anchored, degenerate range → the middle stop.
    ramp = _severity_ramp(0.0, 10.0, "load_factor")
    assert ramp(0.0) != ramp(10.0)
    assert ramp(5.0) == ramp(5.0)
    assert _severity_ramp(5.0, 5.0, "x")(5.0) == _severity_ramp(0.0, 10.0, "x")(5.0)


def test_export_cost_metric_ramps_red_others_blue():
    # A cost-like name (delay) ramps in the red family; a neutral one in blue.
    hot_cost = _severity_ramp(0.0, 10.0, "avg_delay_min")(10.0)
    hot_neutral = _severity_ramp(0.0, 10.0, "load_factor_pct")(10.0)
    assert hot_cost[0] > hot_cost[2]      # red channel dominates blue
    assert hot_neutral[2] > hot_neutral[0]


def test_export_percent_units_are_honoured_and_scale_aware():
    # The one contract that made the PDF contradict the app: a typed percent.
    pct = _fmt_for("metric_total", {"metric_total": "percent"})
    assert pct(0.745) == "74.5%"          # fraction → ×100
    assert pct(74.5) == "74.5%"           # already scaled → left alone
    assert _fmt_for("revenue", None)(1500) == "1.5K"        # no hint → legacy compact
    assert _fmt_for("revenue", {"other": "percent"})(1500) == "1.5K"


def test_export_without_exhibit_is_byte_identical():
    # The flag needs no check in the export: an absent payload IS the gate.
    cols, rows = _RANKING
    assert render_chart(cols, rows, "bar", "t") == render_chart(cols, rows, "bar", "t",
                                                                units=None, exhibit=None)


def test_export_exhibit_actually_reaches_the_canvas():
    # A ramp/ref-line that silently no-ops would still return a valid PNG — so assert
    # the PIXELS differ from the plain render, not merely that it didn't raise.
    cols, rows = _RANKING
    plain = render_chart(cols, rows, "bar", "t")
    ramped = render_chart(cols, rows, "bar", "t", exhibit={"color": {"mode": "severity"}})
    reffed = render_chart(cols, rows, "bar", "t",
                          exhibit={"ref_lines": [{"value": 67.0, "label": "Peer median"}]})
    signed = render_chart(cols, rows, "bar", "t", exhibit={"color": {"mode": "sign"}})
    assert plain and ramped and reffed and signed
    assert ramped != plain and reffed != plain and signed != plain


def test_export_percent_units_change_the_render():
    cols, rows = _RANKING
    assert render_chart(cols, rows, "bar", "t",
                        units={"load_factor_pct": "percent"}) != render_chart(cols, rows, "bar", "t")


def test_export_scatter_labels_and_quadrant_render():
    cols = ["aircraft_id", "aircraft_type", "flight_count", "avg_delay_min"]
    rows = [["HB-JBF", "A320", 22, 16.9], ["HB-JAT", "A220", 10, 16.1],
            ["HB-JCE", "B777", 46, 13.6], ["HB-JBJ", "A320", 17, 13.5]]
    plain = render_chart(cols, rows, "scatter", "t")
    rich = render_chart(cols, rows, "scatter", "t",
                        exhibit={"label_points": True, "quadrant": {"x": 20, "y": 14.5}})
    assert plain and rich and rich != plain


def test_export_survives_a_malformed_exhibit():
    # Fail-open: a spec this renderer can't read must never break the document.
    cols, rows = _RANKING
    for bad in ({"ref_lines": [{"value": "abc", "label": None}]}, {"color": None},
                {"quadrant": {"x": "nope"}}, {"ref_lines": "not-a-list"}):
        assert render_chart(cols, rows, "bar", "t", exhibit=bad) is not None


# ── flag default ─────────────────────────────────────────────────────────────

def test_exhibit_grammar_flag_defaults_off():
    from aughor.kernel.flags import FLAG_ENV, flag_enabled
    assert "chart.exhibit_grammar" in FLAG_ENV
    assert flag_enabled("chart.exhibit_grammar") is False
