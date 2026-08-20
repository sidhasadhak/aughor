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
    ("",  _Route(depth="deep"), _Req(), False),                      # flag off → phase script
])
def test_analyst_door(monkeypatch, flag, route, req, expect):
    from aughor.routers.investigations import _analyst_eligible
    if flag:
        monkeypatch.setenv("AUGHOR_ASK_CONVERSE", flag)
    else:
        monkeypatch.delenv("AUGHOR_ASK_CONVERSE", raising=False)
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
