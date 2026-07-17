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
    order_from_sql,
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


# ── ordering: the SQL decides which end of the ranking leads ─────────────────

def test_order_asc_when_the_query_asked_for_the_bottom_n():
    sql = "SELECT route, load_factor FROM f GROUP BY route ORDER BY load_factor ASC LIMIT 15"
    assert order_from_sql(sql, "load_factor") == "asc"


def test_order_none_for_a_top_n_or_an_unbounded_scan():
    top = "SELECT route, load_factor FROM f ORDER BY load_factor DESC LIMIT 15"
    unbounded = "SELECT route, load_factor FROM f ORDER BY load_factor ASC"   # no LIMIT
    other_col = "SELECT route, load_factor FROM f ORDER BY route ASC LIMIT 15"
    assert order_from_sql(top, "load_factor") is None
    assert order_from_sql(unbounded, "load_factor") is None
    assert order_from_sql(other_col, "load_factor") is None


def test_order_is_silent_on_unparseable_sql():
    assert order_from_sql("NOT SQL AT ALL ;;", "x") is None
    assert order_from_sql("", "x") is None


def test_cross_section_carries_the_query_order():
    f = _xsec_finding()
    f["sql"] = "SELECT segment, metric_total, n FROM t GROUP BY segment ORDER BY metric_total ASC LIMIT 10"
    exhibit_for_cross_section(f, is_ratio=True, is_percent=True)
    assert f["exhibit"]["order"] == "asc"


def test_cross_section_without_a_bottom_n_query_has_no_order():
    f = _xsec_finding()
    f["sql"] = "SELECT segment, metric_total, n FROM t GROUP BY segment ORDER BY metric_total DESC"
    exhibit_for_cross_section(f, is_ratio=True, is_percent=True)
    assert "order" not in f["exhibit"]


def test_avg_scale_refs_are_clipped_on_a_totals_chart():
    # The full cross-section grid [dim, metric_total, n, avg_per_record], ADDITIVE metric:
    # the chart plots the TOTAL, the benchmark/wavg refs are per-record scale (~460) —
    # they must be clipped, not stamped across a 35M axis (seen live on an exported
    # report: "Benchmark: call_center 462.06" printed over the title of a totals chart).
    f = {
        "columns": ["channel", "metric_total", "n", "avg_per_record"],
        "rows": [["web", 34741777.0, 77281, 449.55], ["app", 20327801.0, 44195, 459.96],
                 ["travel_agency", 14699179.0, 32843, 447.56], ["corporate", 8461941.0, 18618, 454.50],
                 ["call_center", 5041580.0, 10911, 462.06]],
    }
    exhibit_for_cross_section(f, is_ratio=False, is_percent=False)
    assert not (f.get("exhibit") or {}).get("ref_lines")


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


def test_export_order_asc_leads_with_the_worst():
    cols, rows = _RANKING
    assert render_chart(cols, rows, "bar", "t", exhibit={"order": "asc"}) != render_chart(cols, rows, "bar", "t")


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


def test_export_stats_grid_is_a_table_not_a_chart():
    # A summary-statistics profile grid must fall back to the table — grouped
    # micro-bars over min/max/mean/std say nothing (caught by the W5 A/B).
    cols = ["tbl", "col", "min_val", "max_val", "mean_val", "std_val", "p1", "p99"]
    rows = [["flights", "delay_minutes", 0, 98, 10.2, 11.7, 0, 49.2],
            ["tickets", "fare_chf", 6, 19719, 312.7, 741.5, 18, 3851.2]]
    assert render_chart(cols, rows, "auto", "t") is None
    # …but a 2-measure comparison grid still charts (the gate is stats-specific).
    assert render_chart(["region", "revenue", "profit"],
                        [["N", 10, 2], ["S", 20, 3], ["E", 30, 4]], "auto", "t") is not None


def test_export_entity_profile_grid_is_a_table_not_a_chart():
    # An ID-labelled record grid with 3+ heterogeneous measures is a PROFILE —
    # the reference reports render these as tables ("… — Profile Analysis").
    cols = ["member_id", "award_miles_balance", "lifetime_miles", "join_year_num"]
    rows = [[f"MM{i:07d}", 1000 + i, 50000 + i, 2000 + i] for i in range(6)]
    assert render_chart(cols, rows, "auto", "t") is None
    # …but an ID-labelled RANKING (one measure) still charts — Genie's top-15 bar.
    assert render_chart(["member_id", "ticket_count"],
                        [[f"MM{i:07d}", 100 - i] for i in range(6)], "auto", "t") is not None


def test_export_wide_profile_and_degenerate_x_are_tables():
    # ≥4 measures — a chart can't say four things about one row (the flagged-thresholds grid).
    wide = (["source_table", "derived_measure", "threshold_value", "flagged_count", "max_ratio", "min_ratio"],
            [["loyalty_members", "award_miles_fraction", 1.0, 1136, 309.46, 1.0],
             ["loyalty_members", "lifetime_miles_per_year", 2378896.9, 256, 2997198.0, 2379332.0]])
    assert render_chart(*wide, "auto", "t") is None
    # Degenerate x: >1 rows, every category column constant → one lying bar.
    degen = (["source_table", "flagged_count"],
             [["loyalty_members", 1136], ["loyalty_members", 256], ["loyalty_members", 269]])
    assert render_chart(*degen, "bar", "t") is None


def test_export_strips_planner_notes_from_explore_prose():
    from aughor.export.document import _strip_planner_notes
    text = ("The gap between p99 and max is extreme for several columns.\n\n"
            "→ Q2 (threshold drill-down) should use p99 as the outlier cutoff\n"
            "for right-skewed monetary columns rather than mean+3σ.")
    out = _strip_planner_notes(text)
    assert "p99 and max is extreme" in out
    # The whole directive paragraph goes — including its wrapped continuation lines.
    assert "→" not in out and "Q2" not in out and "right-skewed" not in out
    assert _strip_planner_notes("→ only a directive") == ""


def test_export_survives_a_malformed_exhibit():
    # Fail-open: a spec this renderer can't read must never break the document.
    cols, rows = _RANKING
    for bad in ({"ref_lines": [{"value": "abc", "label": None}]}, {"color": None},
                {"quadrant": {"x": "nope"}}, {"ref_lines": "not-a-list"}):
        assert render_chart(cols, rows, "bar", "t", exhibit=bad) is not None


# ── the explore-wave report exports its evidence ─────────────────────────────

def _explore_inv() -> dict:
    return {
        "question": "Profile the most unusual entities",
        "connection_id": "workspace",
        "kind": "investigation",
        "report": {
            "_report_type": "explore",
            "headline": "Several extreme entities stand out",
            "narrative": "The landscape scan surfaced concentrated outliers.",
            "conclusion": "Three measures carry all the extremes.",
            "recommended_actions": ["Verify the top outlier records"],
            "subq_answers": [
                {"question": "Which routes have the lowest load factors?",
                 "insight": "GVA-DEL is weakest.",
                 "columns": ["route", "load_factor_pct"],
                 "rows": [["GVA-DEL", 65.2], ["ZRH-EZE", 67.4], ["ZRH-BOS", 67.7]],
                 "sql": "select 1", "error": None},
                {"question": "A failed step", "insight": "", "columns": [], "rows": [],
                 "sql": "", "error": "boom"},
            ],
        },
    }


def test_explore_report_dispatches_to_its_own_builder_and_charts():
    from aughor.export.document import build_export_doc
    doc = build_export_doc(_explore_inv())
    assert doc.kind == "explore"
    kinds = [b.kind for b in doc.blocks]
    assert "chart" in kinds          # the evidence is IN the export (was: text-only)
    # the errored step contributes nothing
    assert sum(1 for b in doc.blocks if b.kind == "heading") >= 3
    joined = " ".join(b.text or "" for b in doc.blocks if b.kind == "prose")
    assert "GVA-DEL is weakest." in joined


def test_explore_export_produces_a_valid_pdf():
    from aughor.export import export_report
    data, fname, media = export_report(_explore_inv(), "pdf")
    assert data[:4] == b"%PDF" and fname.endswith(".pdf")


# ── flag default ─────────────────────────────────────────────────────────────

def test_exhibit_grammar_flag_defaults_off():
    from aughor.kernel.flags import FLAG_ENV, flag_enabled
    assert "chart.exhibit_grammar" in FLAG_ENV
    assert flag_enabled("chart.exhibit_grammar") is False
