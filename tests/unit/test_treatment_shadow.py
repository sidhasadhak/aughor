"""CP-1b — the treatment levers, and the shadow rows read back.

Arc CP's census measured that `deep_analysis` is chosen 0 times in 60 tool uses, so the interactive quick/deep split
is not being made. The shadow that recorded what a typed judgement WOULD have picked after every turn was stopped on
2026-10-28 (ROADMAP §3.65 — a model call on every question for a record nobody yet read); what stays is pinned here:
the levers (the state carries only what is UNCERTAIN — a lever that re-infers a known fact can be wrong about one),
what a turn did read from its own trace, and the corpus reader over the rows already written.
"""
from __future__ import annotations

from aughor.judgment import treatment as T
from aughor.judgment.seam import Answer, CHOICE, NOUL, SCORE


class _Judge:
    """A seam-shaped backend: answers every lever without a model."""

    def __init__(self, treatment="multi_query", p=0.72):
        self.treatment, self.p, self.states = treatment, p, []

    def judge(self, state, questions):
        self.states.append(state)
        out = {}
        for q in questions:
            if q.id == "treatment":
                out[q.id] = Answer(q.id, CHOICE, True, value=self.treatment, probability=self.p,
                                   distribution={o: 0.25 for o in q.options})
            elif hasattr(q, "options"):
                out[q.id] = Answer(q.id, CHOICE, True, value=q.options[0], probability=0.5,
                                   distribution={o: 0.5 for o in q.options})
            elif hasattr(q, "levels"):
                out[q.id] = Answer(q.id, SCORE, True, value=q.levels[1], probability=0.6,
                                   distribution={n: 0.5 for n in q.levels}, score=1.4)
            else:
                out[q.id] = Answer(q.id, NOUL, True, value=True, probability=0.8,
                                   distribution={"true": 0.8, "false": 0.2})
        return out


# ── the bundle ───────────────────────────────────────────────────────────────────────────

def test_nine_levers_in_one_bundle():
    """Latency scales with tokens, not question count, so the levers are asked together —
    a round trip per lever would make the cheap thing expensive."""
    j = _Judge()
    got = T.classify("why did revenue fall?", provider=j)
    assert len(j.states) == 1, "one bundle, one call"
    assert set(got) == {q.id for q in T.LEVERS} and len(T.LEVERS) == 9


def test_the_state_carries_only_what_is_UNCERTAIN(monkeypatch):
    """The rule that keeps the bundle small: the connection, the destination and the asker
    are known at call time, and inferring a known fact only adds a way to be wrong."""
    j = _Judge()
    T.classify("why did revenue fall?", provider=j)
    state = j.states[0]
    assert "why did revenue fall?" in state
    for known in ("8233e4fd", "slack", "#revenue", "theLook"):
        assert known not in state


def test_a_prior_turn_rides_along_because_two_levers_need_it():
    """`from_last_result` and `follow_up` are unanswerable without the previous turn, and an
    unanswerable question gets a confident guess rather than an abstention."""
    j = _Judge()
    T.classify("and by region?", prior_turn="Revenue fell 8% in September.", provider=j)
    assert "Revenue fell 8%" in j.states[0]
    assert "no previous turn" in T.state_for("first question")


# ── the row ──────────────────────────────────────────────────────────────────────────────

def test_a_row_keeps_confidence_and_a_scores_continuous_position():
    """CP-2 calibrates ON the confidence and CP-3 escalates on it, so a row that recorded
    only the winning value would be a corpus you cannot measure calibration against."""
    row = T.as_row(T.classify("why?", provider=_Judge()))
    assert row["treatment"] == "multi_query" and row["treatment_p"] == 0.72
    assert row["steps_implied_score"] == 1.4, "1.4 is a different budget from 2"
    assert "treatment_score" not in row, "a choice has no ordered position"


def test_an_unavailable_lever_records_its_reason_not_a_silent_blank():
    class _Broken:
        def judge(self, state, questions):
            return {q.id: Answer(q.id, "noul", False, reason="the judgment call failed: boom")
                    for q in questions}
    row = T.as_row(T.classify("why?", provider=_Broken()))
    assert row["treatment"] is None
    assert "boom" in row["treatment_unavailable"]


# ── the shadow ───────────────────────────────────────────────────────────────────────────

# ── the hook ─────────────────────────────────────────────────────────────────────────────

# ── the server is not the shadow's to stop ───────────────────────────────────────────────

# ── what the turn did is read from its own trace ────────────────────────────────────────

def _emit_turn(trace, *, steps=(), statements=0, marker=""):
    """Write a turn's events the way the bodies do, under one trace."""
    from aughor.obs import session_log
    if marker:
        session_log.emit(session_log.TOOL_CALL, name=marker, trace_id=trace)
    for name, rows in steps:
        session_log.emit(session_log.STEP, name=name, trace_id=trace, ok=True, row_count=rows,
                         payload={"tool": name})
    for _ in range(statements):
        session_log.emit(session_log.TOOL_CALL, name="sql.execute", trace_id=trace)


def test_the_queries_a_turn_ran_are_read_from_its_trace():
    """A loop step that returned rows is a query, and so is one of the analyst's own
    investigation tools; a schema read is not. Statements count everything that reached the
    warehouse, guards included."""
    _emit_turn("cp2-analyst", marker="ask.analyst", statements=7,
               steps=(("list_tables", None), ("run_sql", 12), ("run_sql", 0),
                      ("decompose", None), ("describe_table", None)))
    assert T.observed_for_trace("cp2-analyst") == {"queries": 3, "statements": 7,
                                                   "body": "analyst"}


def test_a_turn_with_no_loop_ran_one_query_when_a_statement_ran():
    _emit_turn("cp2-quick", statements=2)
    assert T.observed_for_trace("cp2-quick") == {"queries": 1, "statements": 2, "body": "quick"}
    _emit_turn("cp2-converse", marker="ask.converse", steps=(("list_tables", None),))
    assert T.observed_for_trace("cp2-converse") == {"queries": 0, "statements": 0,
                                                    "body": "converse"}


def test_an_unreadable_trace_leaves_the_row_unlabelled_not_zero():
    assert T.observed_for_trace("") == {}
    assert T.observed_for_trace("cp2-never-written") == {}


def test_the_corpus_reader_labels_an_older_row_from_its_trace():
    """A row written before the fix carries the dead count and no body. While its trace is in
    the log it is scored on what the turn did; the fold then has a real outcome to read."""
    from aughor.judgment.calibration import calibrate
    from aughor.obs import session_log

    _emit_turn("cp2-old", marker="ask.analyst", steps=(("run_sql", 4), ("run_sql", 4)))
    session_log.emit(T.TREATMENT_SHADOW, name="treatment_shadow", trace_id="cp2-old",
                     payload={"treatment": "investigation", "treatment_p": 0.9, "ran": "deep",
                              "agreed": False, "observed_grids": 0, "observed_ok": True,
                              "steps_implied": "two or three", "steps_implied_p": 0.9,
                              "steps_implied_score": 2.0})
    [row] = [r for r in T.shadow_corpus() if r.get("observed_body") == "analyst"
             and r.get("treatment") == "investigation" and r.get("observed_grids") == 0]
    assert row["observed_queries"] == 2
    assert row["agreed"] is True, "investigation judged, the analyst served: retaken, not kept"
    got = calibrate([row])
    assert got["rows_with_an_observed_outcome"] == 1
    assert got["levers"]["steps_implied"]["available"] is True
