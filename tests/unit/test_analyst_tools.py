"""CA-3 — the analyst's tools: the phase library as bodies, the probes as code.

The deterministic tools (premise_check, z_score, value_lookup, profile_column) are
tested against a REAL in-memory DuckDB seeded with the specimen's own trap — a value
that lives at CHANNEL_LVL_1 while the obvious filter says LVL_0 — because that trap is
the reason the tools exist. The loop runner is driven with the faux backend (scripted
tool choices, zero network), with intake and synthesis faked at the seam so the test
pins the RUNNER's mechanics: phases stream as they land, the spec carries, the
conclusion reaches synthesis, the report persists.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.agent import analyst as an
from aughor.db.connection import DuckDBConnection


# ── the warehouse: the specimen's shape, minimally ───────────────────────────


@pytest.fixture(scope="module")
def traffic_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("analyst") / "traffic.duckdb"
    w = duckdb.connect(str(path))
    try:
        w.execute("""
            CREATE TABLE traffic AS
            SELECT
                (DATE '2026-06-01' + (i % 79 || ' days')::INTERVAL)::DATE AS day,
                CASE WHEN i % 3 = 0 THEN 'Direct' ELSE 'Search' END AS channel_lvl0,
                CASE WHEN i % 3 = 0 THEN 'Direkteingabe' ELSE 'Google' END AS channel_lvl1,
                CASE WHEN (i % 79) >= 61 AND i % 3 = 0 THEN 90 ELSE 30 END AS sessions
            FROM range(0, 2370) t(i)
        """)
        # A separate noisy daily series for the z-score test: a zero-variance
        # baseline yields z = 0 by construction (std guard), which is the stats
        # module being right, not the tool being wrong.
        w.execute("""
            CREATE TABLE daily AS
            SELECT (DATE '2026-06-01' + (i || ' days')::INTERVAL)::DATE AS day,
                   CASE WHEN i = 61 THEN 1500 ELSE 900 + (i * 37) % 25 END AS sessions
            FROM range(0, 62) t(i)
        """)
    finally:
        w.close()
    db = DuckDBConnection(str(path))
    yield db
    db.close()


def _turn(db, intake: dict | None = None, emit=None) -> an.AnalystTurn:
    state = an._base_state(
        "why did Direkteingabe traffic move in August?", "conn-t", "inv-t",
        db.get_schema(), origin_finding=None, scope_schema="", canvas_id=None,
        canvas_schema_context="", data_catalog="")
    state["_ada_intake"] = intake or {
        "metric_label": "sessions", "metric_sql": "SUM(sessions)",
        "metric_table": "traffic", "date_column": "traffic.day",
        "observation_start": "2026-08-01", "observation_end": "2026-08-18",
        "observation_label": "August 2026 (18 days)",
        # Symmetric 18-day windows, so the three-way premise probe compares like
        # with like (a 31-day July would out-sum a spiked 18-day August).
        "comparison_start": "2026-07-14", "comparison_end": "2026-07-31",
        "comparison_label": "mid-July 2026",
        "dimensions": ["traffic.channel_lvl0", "traffic.channel_lvl1"],
        "data_understanding_block": "",
    }
    return an.AnalystTurn(connection_id="conn-t", conn=db, state=state,
                          emit=emit or (lambda t, p: None))


# ── value_lookup: the wrong-column trap becomes a one-call lookup ────────────


def test_value_lookup_finds_the_column_that_actually_stores_the_value(traffic_db):
    out = an.value_lookup(_turn(traffic_db), {"value": "Direkteingabe"})
    hits = {(h["table"], h["column"]) for h in out["found_in"]}
    assert any(col == "channel_lvl1" for _, col in hits), out
    assert not any(col == "channel_lvl0" for _, col in hits), (
        "LVL_0 does not store the value — reporting it there rebuilds the trap")


def test_value_lookup_reports_absence_as_absence(traffic_db):
    out = an.value_lookup(_turn(traffic_db), {"value": "NoSuchChannel"})
    assert out["found_in"] == []
    assert "absent" in out["note"], "an honest absence, never a zero that reads as data"


# ── profile_column ───────────────────────────────────────────────────────────


def test_profile_column_reads_the_shape(traffic_db):
    out = an.profile_column(_turn(traffic_db), {"table": "traffic", "column": "channel_lvl1"})
    assert out["distinct_values"] == 2
    assert {v["value"] for v in out["top_values"]} == {"Direkteingabe", "Google"}
    assert out["null_count"] == 0


# ── z_score: significance from code, with the CA-2 minimum-baseline rule ─────


def test_z_score_refuses_a_short_baseline(traffic_db):
    out = an.z_score(_turn(traffic_db), {"sql": (
        "SELECT DATE_TRUNC('month', day) AS m, SUM(sessions) FROM traffic GROUP BY 1 ORDER BY 1"
    )})
    assert out["verdict"] == "not_assessable"
    assert "at least" in out["reason"], "the minimum must be named, not implied"


def test_z_score_flags_a_real_spike(traffic_db):
    # 61 noisy-but-quiet days then a terminal spike.
    out = an.z_score(_turn(traffic_db), {"sql": (
        "SELECT day, sessions FROM daily ORDER BY day"
    )})
    assert out["verdict"] == "significant" and out["sigma"] >= 2.0, out


# ── premise_check: the three-way probe, and the re-anchor ────────────────────


def test_premise_check_holds_when_the_metric_moved_as_asked(traffic_db):
    # August (with the spike tail) is UP vs July; the question asks why it MOVED —
    # phrased upward here so the premise holds.
    t = _turn(traffic_db)
    t.state["question"] = "why did Direkteingabe sessions rise in August?"
    out = an.premise_check(t, {})
    assert out["verdict"] == "premise_holds"
    assert out["obs_value"] > 0 and out["comp_value"] > 0


def test_premise_check_contradicts_a_false_premise(traffic_db):
    t = _turn(traffic_db)
    t.state["question"] = "why did sessions drop in August?"
    out = an.premise_check(t, {})
    assert out["verdict"] == "premise_contradicted", out
    assert "OPPOSITE" in out["note"]


def test_premise_check_respects_the_no_prior_period_verdict(traffic_db):
    t = _turn(traffic_db)
    t.intake["no_prior_period"] = True
    out = an.premise_check(t, {})
    assert out["verdict"] == "no_prior_period"
    assert "never decompose" in out["reason"]


# ── the spec's latitude ──────────────────────────────────────────────────────


def test_spec_overrides_change_the_window_without_mutating_the_anchor():
    intake = {"observation_start": "2026-08-01", "observation_end": "2026-08-18",
              "metric_sql": "SUM(sessions)", "metric_label": "sessions"}
    spec = an._spec_overrides(intake, {"observation_start": "2026-08-10",
                                       "observation_end": "2026-08-18"})
    assert spec["observation_start"] == "2026-08-10"
    assert spec["observation_label"].startswith("2026-08-10")
    assert intake["observation_start"] == "2026-08-01", "the anchor spec must survive"


def test_spec_overrides_metric_latitude():
    spec = an._spec_overrides({"metric_sql": "SUM(sessions)"},
                              {"metric_sql": "COUNT(DISTINCT day)", "metric_label": "active days"})
    assert spec["metric_sql"] == "COUNT(DISTINCT day)"
    assert spec["metric_label"] == "active days"


# ── the runner: phases stream, the spec carries, the conclusion reaches synthesis ──


def _patch_seams(monkeypatch, db, *, intake, synthesize=None, baseline=None):
    """Fake the phase nodes the runner calls, and the context it builds.

    One helper names these dotted paths so the tests do not each repeat them — the
    node names are a persisted identity (they are what the graph registers), so the
    place to keep them down to one mention is here."""
    node = "aughor.agent.investigate."
    monkeypatch.setattr(node + "ada_intake", intake)
    if baseline is not None:
        monkeypatch.setattr(node + "ada_baseline", baseline)
    if synthesize is not None:
        monkeypatch.setattr(node + "ada_synthesize", synthesize)
    monkeypatch.setattr("aughor.agent.analyst.build_analyst_context",
                        lambda cid, q, **kw: (db, {
                            "connection_id": cid, "schema_context": db.get_schema(),
                            "scope_schema": "", "canvas_id": None,
                            "canvas_schema_context": "", "data_catalog": ""}))


def test_run_analyst_streams_phases_and_synthesizes(monkeypatch, traffic_db, faux_llm):
    """The runner's mechanics with intake and synthesis faked at the seam: the loop
    (real, faux-scripted) chooses a phase tool, the phase (faked node) streams as
    `phase_complete`, the model's conclusion reaches synthesis, and the terminal
    `answer_report` carries the narrator's report."""
    from aughor.llm.faux import FauxToolCall

    seen = {}

    def _fake_intake(state, conn=None):
        return {"_ada_intake": {
            "metric_label": "sessions", "metric_sql": "SUM(sessions)",
            "metric_table": "traffic", "date_column": "traffic.day",
            "observation_start": "2026-08-01", "observation_end": "2026-08-18",
            "observation_label": "August 2026", "comparison_start": "2026-07-01",
            "comparison_end": "2026-07-31", "comparison_label": "July 2026",
            "dimensions": ["traffic.channel_lvl1"], "data_understanding_block": "",
        }, "investigation_phases": [{
            "phase_id": "intake", "phase_name": "Question Intake", "phase_icon": "🎯",
            "status": "complete", "summary": "spec resolved", "findings": [],
        }]}

    def _fake_baseline(state, conn):
        seen["baseline_intake"] = dict(state.get("_ada_intake") or {})
        phases = state.get("investigation_phases", [])
        return {"investigation_phases": phases + [{
            "phase_id": "baseline", "phase_name": "Baseline", "phase_icon": "📊",
            "status": "complete", "summary": "August runs above July.",
            "findings": [{"finding_id": "b1", "title": "Daily sessions", "sql": "SELECT 1",
                          "columns": ["day", "sessions"], "rows": [["2026-08-01", 30]],
                          "row_count": 1, "error": None, "interpretation": "up",
                          "key_numbers": [], "chart_type": "line", "stat_note": None,
                          "is_significant": True}],
        }], "_baseline_sigma": 2.5, "_baseline_significant": True}

    def _fake_synthesize(state):
        seen["conclusion"] = state.get("_analyst_conclusion")
        seen["n_phases"] = len(state.get("investigation_phases") or [])
        return {"answer_report": {
            "headline": "The Direkteingabe cohort drives it",
            "executive_summary": "…", "metric": "sessions",
            "observation_period": "Aug 2026", "comparison_basis": "Jul 2026",
            "total_change_label": "+X", "phases": state.get("investigation_phases") or [],
            "attribution_waterfall": [], "confidence": "MEDIUM",
            "confidence_justification": "two slices agree",
            "recommendations": [], "data_gaps": [],
        }}

    _patch_seams(monkeypatch, traffic_db, intake=_fake_intake,
                 baseline=_fake_baseline, synthesize=_fake_synthesize)

    faux_llm.set_responses([
        FauxToolCall(payload={"observation_start": "2026-08-10"}, name="baseline"),
        "The spike is carried by the Direkteingabe cohort — about 60 extra sessions/day.",
    ])

    frames: list[tuple] = []
    result = an.run_analyst("conn-t", "why did traffic move?", persist=False,
                            emit=lambda t, p: frames.append((t, p)))

    types = [t for t, _ in frames]
    assert types.count("phase_complete") == 2, types  # intake + baseline
    assert "answer_report" in types
    assert result.report["headline"].startswith("The Direkteingabe")
    assert result.stop_reason == "answered"
    # The model's window latitude reached the phase body through the spec copy…
    assert seen["baseline_intake"]["observation_start"] == "2026-08-10"
    # …and its conclusion reached the narrator.
    assert seen["conclusion"].startswith("The spike is carried")
    assert seen["n_phases"] == 2


def test_a_stop_over_flagged_rows_alone_goes_back_to_the_analyst_once(monkeypatch, traffic_db, faux_llm):
    """The run's loop carries the check (`_every_result_warned`): the first stop over a flagged result is handed
    back, and the second is the conclusion."""
    from aughor.llm.faux import FauxToolCall
    seen = {}

    def _flagged(state, conn):
        return {"investigation_phases": state.get("investigation_phases", []) + [{
            "phase_id": "baseline", "phase_name": "Baseline", "phase_icon": "📊", "status": "complete",
            "summary": "", "findings": [{"finding_id": "b1", "title": "t", "sql": "SELECT 1",
                                          "columns": ["day", "sessions"], "rows": [["2026-08-01", 30]],
                                          "row_count": 1, "error": None, "interpretation": "", "key_numbers": [],
                                          "chart_type": "line", "stat_note": None, "is_significant": False,
                                          "trust_caveat": "time-order guard: shipped_at is earlier …"}]}]}

    _patch_seams(monkeypatch, traffic_db,
                 intake=lambda state, conn=None: {"_ada_intake": {"metric_label": "sessions"},
                                                  "investigation_phases": []},
                 baseline=_flagged,
                 synthesize=lambda state: seen.setdefault("conclusion", state.get("_analyst_conclusion")) and {})
    faux_llm.set_responses([FauxToolCall(payload={}, name="baseline"), "first answer", "second answer"])
    an.run_analyst("conn-t", "why did traffic move?", persist=False)
    assert seen["conclusion"] == "second answer"


def test_run_analyst_with_no_report_returns_the_prose(monkeypatch, traffic_db, faux_llm):
    """A loop that concludes without any phase landing is a direct answer, not a
    report-shaped shell — and not a failure."""
    _patch_seams(monkeypatch, traffic_db, intake=lambda state, conn=None: {
        "_ada_intake": {}, "investigation_phases": []})
    faux_llm.set_responses(["There is no prior period; the window can only be described."])

    result = an.run_analyst("conn-t", "why?", persist=False)

    assert result.report is None
    assert result.answer.startswith("There is no prior period")
    assert result.stop_reason == "answered"


# ── the door ─────────────────────────────────────────────────────────────────


class _Req:
    def __init__(self, escalate=False):
        self.escalate = escalate


class _Route:
    def __init__(self, depth="deep", mode="investigate", forced=None):
        self.depth, self.mode, self.forced = depth, mode, forced


@pytest.mark.parametrize("flag,route,req,expect", [
    ("1", _Route(depth="deep"), _Req(), True),                       # the door opens
    ("1", _Route(depth="deep"), _Req(escalate=True), True),          # escalate too
    ("1", _Route(depth="quick"), _Req(escalate=True), True),         # escalate alone
    ("1", _Route(depth="deep", forced="dossier"), _Req(), False),    # dossier stays a conversation
    ("1", _Route(depth="deep", mode="explore"), _Req(), False),      # explore keeps its graph
    ("1", _Route(depth="quick"), _Req(), False),                     # quick is not deep
    ("0", _Route(depth="deep"), _Req(), False),                      # flag off → phase script
])
def test_analyst_door(monkeypatch, flag, route, req, expect):
    from aughor.routers.investigations import _analyst_eligible
    # SP-14: default-ON, so the off arm is an explicit "0", never an unset variable.
    monkeypatch.setenv("AUGHOR_ASK_CONVERSE", flag)
    assert _analyst_eligible(req, route) is expect


def test_converse_eligible_still_refuses_deep(monkeypatch):
    """Plain converse keeps answering the narrow question; deep goes to the analyst."""
    from aughor.routers.investigations import _converse_eligible
    monkeypatch.setenv("AUGHOR_ASK_CONVERSE", "1")
    assert _converse_eligible(_Req(), _Route(depth="deep")) is False
    assert _converse_eligible(_Req(), _Route(depth="quick")) is True


def test_run_sql_evidence_reaches_the_reports_no_data_floor(monkeypatch, traffic_db,
                                                            faux_llm):
    """A turn answered from `run_sql` alone builds no phase — and the report's no-data
    floor counts phase findings, so it read that run as a total failure and printed
    "Every diagnostic query failed" above correct numbers (live, on flights per route).
    The rows the loop actually gathered have to reach the floor."""
    from aughor.llm.faux import FauxToolCall

    seen = {}

    def _fake_intake(state, conn=None):
        return {"_ada_intake": {"metric_label": "flights", "metric_sql": "COUNT(*)",
                                "metric_table": "traffic", "date_column": "traffic.day",
                                "observation_start": "2026-08-01",
                                "observation_end": "2026-08-18",
                                "observation_label": "August 2026",
                                "dimensions": [], "data_understanding_block": ""},
                "investigation_phases": [{
                    "phase_id": "intake", "phase_name": "Question Intake",
                    "phase_icon": "🎯", "status": "complete", "summary": "spec",
                    "findings": []}]}

    def _fake_synthesize(state):
        seen["evidence_rows"] = state.get("_analyst_evidence_rows")
        return {}

    _patch_seams(monkeypatch, traffic_db, intake=_fake_intake,
                 synthesize=_fake_synthesize)
    # The tool returns rows the way the real one does; only its plumbing is stubbed.
    monkeypatch.setattr("aughor.agent.converse_tools.run_sql",
                        lambda cid, a, **kw: {"columns": ["route", "n"],
                                              "rows": [["ZRH-LHR", 28], ["GVA-LHR", 42]]})

    faux_llm.set_responses([
        FauxToolCall(payload={"sql": "SELECT channel_lvl1, COUNT(*) FROM traffic GROUP BY 1"},
                     name="run_sql"),
        "ZRH-LHR ran 28 flights and GVA-LHR 42.",
    ])

    an.run_analyst("conn-t", "give me route wise number of flights", persist=False)

    assert seen["evidence_rows"] == 2, (
        "the rows run_sql returned never reached synthesis, so the floor still sees "
        "an empty run and will declare the turn a failure")


def test_an_ad_hoc_query_reaches_the_report_as_a_drawable_phase(monkeypatch, traffic_db,
                                                                faux_llm):
    """End to end through the runner: a turn answered by `run_sql` alone must arrive at
    synthesis with a phase carrying the rows, or the report has nothing to draw and deep
    renders thinner than quick for the same question."""
    from aughor.llm.faux import FauxToolCall

    seen = {}

    def _fake_intake(state, conn=None):
        return {"_ada_intake": {"metric_label": "flights", "metric_sql": "COUNT(*)",
                                "metric_table": "traffic", "date_column": "traffic.day",
                                "observation_start": "2026-08-01",
                                "observation_end": "2026-08-18",
                                "observation_label": "August 2026",
                                "dimensions": [], "data_understanding_block": ""},
                "investigation_phases": [{
                    "phase_id": "intake", "phase_name": "Question Intake",
                    "phase_icon": "🎯", "status": "complete", "summary": "spec",
                    "findings": []}]}

    def _fake_synthesize(state):
        seen["phases"] = state.get("investigation_phases") or []
        return {}

    _patch_seams(monkeypatch, traffic_db, intake=_fake_intake, synthesize=_fake_synthesize)
    monkeypatch.setattr("aughor.agent.converse_tools.run_sql",
                        lambda cid, a, **kw: {"columns": ["route", "n"],
                                              "rows": [["GVA-FRA", 42], ["ZRH-BUD", 35]]})

    faux_llm.set_responses([
        FauxToolCall(payload={"sql": "SELECT route, COUNT(*) FROM traffic GROUP BY 1"},
                     name="run_sql"),
        "GVA-FRA leads at 42 flights.",
    ])

    frames: list[tuple] = []
    an.run_analyst("conn-t", "give me route wise number of flights", persist=False,
                   emit=lambda t, p: frames.append((t, p)))

    # the rows arrived at synthesis as a phase with a finding, not just as prose
    drawable = [f for p in seen["phases"] for f in (p.get("findings") or []) if f.get("rows")]
    assert drawable, "synthesis saw no finding carrying rows — nothing to draw"
    assert drawable[0]["rows"] == [["GVA-FRA", 42], ["ZRH-BUD", 35]]
    # …and it streamed, so the user watches the slice land
    assert [t for t, _ in frames].count("phase_complete") == 2   # intake + the query


# ── ad-hoc phase titles carry their SCOPE ──────────────────────────────────────

def test_two_cuts_of_the_same_shape_get_distinguishable_titles():
    """The title is derived from the RESULT SHAPE, so one cut run over two periods produced the
    same name twice — different numbers, nothing saying which was which. An observation/comparison
    PAIR then reads as redundant compute (it did, to a reader who had not opened the WHERE clauses).
    Both queries are real and both belong in the report; only the label was ambiguous."""
    from aughor.agent.analyst import _adhoc_title

    obs = ("SELECT inventory_items.product_brand, SUM(CASE WHEN order_items.status = 'Returned' "
           "THEN inventory_items.cost ELSE 0 END) as returned_cost FROM order_items "
           "WHERE order_items.created_at >= '2025-02-01' AND order_items.created_at <= '2025-02-28' "
           "GROUP BY 1")
    cmp_ = obs.replace("2025-02-01", "2025-01-01").replace("2025-02-28", "2025-02-01")
    cols = ["product_brand", "returned_cost"]

    t_obs = _adhoc_title(cols, "Where are we losing money?", obs)
    t_cmp = _adhoc_title(cols, "Where are we losing money?", cmp_)
    assert t_obs != t_cmp, "an observation/comparison pair must not share a title"
    assert "Feb 2025" in t_obs and "1 Jan" in t_cmp
    assert t_obs.startswith("Returned cost by product brand")


def test_a_scoping_filter_is_named_but_the_metric_definition_is_not():
    """A drill into one department must say so. The metric's OWN `status = 'Returned'` must not
    be echoed — it is in every query of the run and would title them all identically."""
    from aughor.agent.analyst import _adhoc_title

    sql = ("SELECT inventory_items.product_category, SUM(CASE WHEN order_items.status = 'Returned' "
           "THEN inventory_items.cost ELSE 0 END) as returned_cost FROM order_items "
           "WHERE order_items.created_at >= '2025-02-01' "
           "AND inventory_items.product_department = 'Men' GROUP BY 1")
    title = _adhoc_title(["product_category", "returned_cost"], "q", sql)
    assert "product department = Men" in title
    assert "Returned" not in title.split(" where ", 1)[1], "the metric's own filter is not the cut's scope"


def test_a_query_with_no_scope_keeps_the_bare_title():
    """Fail-open: an unscoped or unparseable query yields exactly the old title."""
    from aughor.agent.analyst import _adhoc_title

    assert _adhoc_title(["a", "b"], "q", "SELECT a, SUM(b) FROM t GROUP BY 1") == "B by a"
    assert _adhoc_title(["a", "b"], "q", "") == "B by a"
    assert _adhoc_title([], "the question", "") == "the question"


# ── ON-10 (2026-09-22): the analyst's scan tool runs the frame's declared breakdowns first ──────────────────────
# The graph route got a `frame_breakdowns` node before the scan; the analyst body reaches the scan as a TOOL and the
# live receipt (a deep run on LuxExperience) never met the node. So the tool runs the node's function once per turn
# on its first scan — pinned by `dimension` or not: the second live run pinned the scan to the carrier the question
# named, and a first draft that skipped pinned scans never ran them at all.

def test_the_scan_tool_runs_the_declared_breakdowns_once_before_the_first_scan(traffic_db, monkeypatch):
    from aughor.agent import investigate as I
    calls: list[str] = []

    def fake_frame_breakdowns(state, conn):
        calls.append("frame_breakdowns")
        return {"investigation_phases": list(state.get("investigation_phases") or []) + [
            I._phase_result("frame_breakdowns", "Declared breakdowns", "📐", "complete", "1 declared", [])]}

    def fake_scan(state, conn, **kwargs):
        calls.append("cross_section")
        return {"investigation_phases": list(state.get("investigation_phases") or []) + [
            I._phase_result("cross_section", "Cross-Sectional Scan", "🧭", "complete", "scan", [])]}
    monkeypatch.setattr(I, "frame_breakdowns", fake_frame_breakdowns)
    monkeypatch.setattr(an, "_scan", fake_scan)
    emitted: list[str] = []
    turn = _turn(traffic_db, emit=lambda t, p: emitted.append(p["phase"]["phase_id"]) if t == "phase_complete" else None)

    out = an.cross_section(turn, {})
    assert calls == ["frame_breakdowns", "cross_section"]
    assert emitted == ["frame_breakdowns", "cross_section"]                  # streamed in order, as the graph would
    assert [p["phase_id"] for p in out["phases"]] == ["frame_breakdowns", "cross_section"]   # both reach the model

    an.cross_section(turn, {"dimension": "channel_lvl0"})                     # a later pinned scan: no repeat
    assert calls == ["frame_breakdowns", "cross_section", "cross_section"]
    an.cross_section(_turn(traffic_db), {"dimension": "channel_lvl0"})        # a fresh turn whose FIRST scan is pinned: runs
    assert calls[-2:] == ["frame_breakdowns", "cross_section"]


# ── A further measure tied to a governed metric is measured by code (2026-10-02) ──────────────────────
# "What was total revenue and how many units were sold in July 2026?": told that units sold is the governed
# units_sold — inventory items by the day they sold — and to measure it in a query of its own, the analyst
# counted order lines inside revenue's statement four times, the last with `status IS NOT NULL` so that
# revenue's declared filter would leave it alone, and published revenue with every cancelled line in it.

Q1 = "What was total revenue and how many units were sold in July 2026?"
UNITS_DEF = {"label": "units sold", "metric": "units_sold", "table": "inventory_items",
             "date_column": "sold_at", "filters": ["sold_at IS NOT NULL"]}
UNITS_SQL = ("SELECT COUNT(id) AS units_sold FROM inventory_items WHERE sold_at IS NOT NULL "
             "AND sold_at >= '2026-07-01' AND sold_at < '2026-08-01'")


def _q1_intake(**changes) -> dict:
    return {"metric_label": "total revenue", "metric_sql": "SUM(sale_price)", "metric_table": "order_items",
            "date_column": "order_items.created_at", "observation_start": "2026-07-01",
            "observation_end": "2026-07-31", "observation_label": "July 2026", "period_named": True,
            "comparison_asked": False, "cross_sectional": False, "named_dimensions": [],
            "other_measures": [{"label": "units sold", "sql": "COUNT(id)"}],
            "measure_definitions": [dict(UNITS_DEF)], "dimensions": [], "data_understanding_block": "",
            **changes}


def test_a_declared_measure_is_measured_on_its_table_by_its_own_date():
    assert an._declared_measure_sql(_q1_intake(), UNITS_DEF, "COUNT(id)") == UNITS_SQL
    # no period named: every row its definition keeps
    assert an._declared_measure_sql(_q1_intake(period_named=False), UNITS_DEF, "COUNT(id)") == (
        "SELECT COUNT(id) AS units_sold FROM inventory_items WHERE sold_at IS NOT NULL")
    # a period asked of a measure with no date of its own, or a measure with no formula, is not measured
    assert an._declared_measure_sql(_q1_intake(), {**UNITS_DEF, "date_column": ""}, "COUNT(id)") == ""
    assert an._declared_measure_sql(_q1_intake(), UNITS_DEF, "") == ""


@pytest.mark.parametrize("why, changes, question, shape", [
    ("a cut is named", {"named_dimensions": ["products.category"]}, Q1, "describe"),
    ("groups are compared", {"cross_sectional": True}, Q1, "describe"),
    ("periods are compared", {"comparison_asked": True}, Q1, "describe"),
    ("a series is asked", {}, "How many units were sold each month in 2026?", "describe"),
    ("a why question", {}, Q1, "diagnose"),
])
def test_only_a_question_asking_one_figure_is_measured_by_code(why, changes, question, shape):
    assert an._asks_one_figure(_q1_intake(), Q1, "describe")
    assert not an._asks_one_figure(_q1_intake(**changes), question, shape), why


def test_a_figure_is_recorded_only_for_the_result_it_landed_as():
    def turn():
        return an.AnalystTurn(connection_id="c", conn=None, state={
            "question": Q1, "_ada_intake": _q1_intake(), "investigation_phases": [{"phase_id": "intake"}]})
    landed = turn()

    def _lands(args):
        landed.state["investigation_phases"].append({"phase_id": "adhoc_1"})
        return {"columns": ["units_sold"], "rows": [["7027"]]}
    an._measure_declared(landed, _lands, "describe")
    assert landed.intake["measure_definitions"][0]["measured"] == {"result": "adhoc_1", "value": "7027"}
    # rows that never became a result give the analyst no figure to quote — least of all the intake's
    lost = turn()
    an._measure_declared(lost, lambda args: {"columns": ["units_sold"], "rows": [["7027"]]}, "describe")
    assert "measured" not in lost.intake["measure_definitions"][0]


def test_the_analyst_is_handed_the_figure_code_measured(monkeypatch, traffic_db, faux_llm):
    ran, frames = [], []

    def _fake_intake(state, conn=None):
        return {"_ada_intake": _q1_intake(), "investigation_phases": [{
            "phase_id": "intake", "phase_name": "Question Intake", "phase_icon": "🎯",
            "status": "complete", "summary": "spec", "findings": []}]}

    def _run_sql(cid, args, **kw):
        ran.append(args["sql"])
        return {"columns": ["units_sold"], "rows": [["7027"]], "row_count": 1, "caveats": []}

    _patch_seams(monkeypatch, traffic_db, intake=_fake_intake, synthesize=lambda state: {})
    monkeypatch.setattr("aughor.agent.converse_tools.run_sql", _run_sql)
    faux_llm.set_responses(["July 2026: 7,027 units sold."])

    an.run_analyst("conn-t", Q1, persist=False, emit=lambda t, p: frames.append((t, p)))

    assert ran == [UNITS_SQL], "code measures units sold before the analyst's first call, as declared"
    system = faux_llm.calls()[0].system
    assert ("also asked: units sold = COUNT(id) — the governed units_sold on inventory_items, dated by "
            "sold_at, over rows where sold_at IS NOT NULL; measured that way over the observation by "
            "code: 7027 — state that figure; do not measure it again") in system
    assert "adhoc_" not in system, "a result's id is the platform's, never a word for the reader"
    assert "yours, or one measured for you by code before your first call" in system
    # …and read as a result, with the question: the figure in its instructions lost to its own count
    asked = faux_llm.calls()[0].user
    assert asked.startswith(Q1 + "\n\nMeasured for you by code before your first call")
    assert f"run_sql: {UNITS_SQL}" in asked and '"rows": [["7027"]]' in asked
    landed = [p["phase"] for t, p in frames if t == "phase_complete" and p["phase"]["phase_id"] == "adhoc_2"]   # the intake is phase 1
    assert [p["phase_name"] for p in landed] == ["Units sold — Jul 2026"]


def test_the_answer_carries_its_questions_shape(monkeypatch, traffic_db, faux_llm):
    """A describe answer measured what was asked and tested no hypotheses; the trace called every Agent
    answer "Multi-hypothesis analysis" (2026-10-02). The shape rides the report, streamed and stored."""
    frames = []

    def _fake_intake(state, conn=None):
        return {"_ada_intake": _q1_intake(), "investigation_phases": [{
            "phase_id": "intake", "phase_name": "Question Intake", "phase_icon": "🎯",
            "status": "complete", "summary": "spec", "findings": []}]}

    _patch_seams(monkeypatch, traffic_db, intake=_fake_intake,
                 synthesize=lambda state: {"answer_report": {"headline": "h", "phases": []}})
    monkeypatch.setattr("aughor.agent.converse_tools.run_sql", lambda cid, args, **kw: {
        "columns": ["units_sold"], "rows": [["7027"]], "row_count": 1, "caveats": []})
    faux_llm.set_responses(["July 2026: 7,027 units sold."])
    an.run_analyst("conn-t", Q1, persist=False, emit=lambda t, p: frames.append((t, p)))
    reports = [p["answer_report"] for t, p in frames if t == "answer_report"]
    assert [r.get("question_shape") for r in reports] == ["describe"]


def test_the_route_frame_names_the_shape_the_analyst_serves():
    """Said before the report lands, so the trace is right while the run streams."""
    import inspect
    from aughor.routers import investigations
    src = inspect.getsource(investigations)
    assert '_route_ev["question_shape"] = _shape_of(req.question or "")' in src


def test_a_column_named_for_a_measure_code_measured_is_marked_when_counted_elsewhere():
    """The analyst's `COUNT(id) AS units_sold` over order lines, beside the governed units sold that code
    had measured on inventory items — 6,012 against 7,027. The mark rides the rows the model reads."""
    intake = _q1_intake()
    intake["measure_definitions"][0]["measured"] = {"result": "adhoc_2", "value": "7027"}
    turn = an.AnalystTurn(connection_id="c", conn=None, state={"question": Q1, "_ada_intake": intake,
                                                              "investigation_phases": []})
    lines = "SELECT SUM(sale_price) AS total_revenue, COUNT(id) AS units_sold FROM order_items"
    marked = an._not_the_declared(turn, ["total_revenue", "units_sold"], lines)
    assert list(marked) == ["units_sold"]
    assert "7027" in marked["units_sold"] and "inventory_items" in marked["units_sold"]
    assert "order_items" in marked["units_sold"]
    # on its own table, it is the declared measure; no measure measured, nothing to mark
    assert an._not_the_declared(turn, ["units_sold"], "SELECT COUNT(id) AS units_sold FROM inventory_items") == {}
    bare = an.AnalystTurn(connection_id="c", conn=None, state={"question": Q1, "_ada_intake": _q1_intake()})
    assert an._not_the_declared(bare, ["units_sold"], lines) == {}
    # and the model reads it with the rows
    result = an._record_evidence(turn, {"sql": lines}, {"columns": ["total_revenue", "units_sold"],
                                                      "rows": [["359224.30", "6012"]], "row_count": 1})
    assert list(result.get("not_the_declared_measure") or {}) == ["units_sold"]


def test_a_statement_that_reads_a_declared_rule_off_another_table_does_not_run(monkeypatch):
    """Q3 (2026-10-03): the frame read "completed orders" as rule completed_orders — orders.status in ('Complete') —
    and the analyst's second query filtered order_items.status = 'Complete'; its every figure became the answer,
    beside a first query that had kept to the rule."""
    frame = {"start": {"entity": "Order", "table": "orders"}, "rules": [{
        "id": "completed_orders", "label": "Completed orders", "entity": "Order", "matched": "completed orders",
        "words": "Order.status is one of Complete", "usable": True,
        "filters": [{"path": "status", "op": "in", "values": ["Complete"]}]}]}
    turn = an.AnalystTurn(connection_id="c", conn=None, state={
        "question": "How has monthly revenue from completed orders trended?", "_ada_intake": {"ontology_frame": frame},
        "investigation_phases": []})
    items = ("WITH m AS (SELECT DATE_TRUNC(DATE(created_at), MONTH) AS month, SUM(sale_price) AS revenue "
             "FROM order_items WHERE status = 'Complete' GROUP BY 1) SELECT month, revenue FROM m")
    join = "FROM orders o JOIN order_items oi ON o.order_id = oi.order_id"
    kept = (f"SELECT DATE_TRUNC(DATE(o.created_at), MONTH) AS month, "
            f"SUM(CASE WHEN o.status = 'Complete' THEN oi.sale_price ELSE 0 END) AS revenue {join} GROUP BY 1")
    both = f"SELECT SUM(oi.sale_price) {join} WHERE o.status = 'Complete' AND oi.status = 'Complete'"
    # the statement that misreads the rule is refused, naming the rule; the run never reaches the warehouse
    monkeypatch.setattr("aughor.agent.converse_tools.run_sql", lambda *a, **k: (_ for _ in ()).throw(AssertionError("it ran")))
    run = next(t for t in an.analyst_tools(turn, session_id="s", shape="describe") if t.name == "run_sql").run
    refused = run({"sql": items})
    assert refused["kind"] == "declared_rule" and "orders.status in ('Complete')" in refused["error"]
    assert "order_items.status" in refused["error"] and turn.state["investigation_phases"] == []
    # one that keeps to it — as a condition, or beside another filter — runs
    assert an._rule_misread(turn, kept) == "" and an._rule_misread(turn, both) == ""
