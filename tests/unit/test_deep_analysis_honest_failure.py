"""The deep path must not turn a failure into a report (diagnosed 2026-08-15).

A deep-analysis run on a 23-table canvas produced a formal report whose headline was **8**
— the row count of `aircraft_types`, the alphabetically-first table in the schema text.
Nobody asked for it. The structured-output call had failed twice, and the planner-failure
fallback emitted `SELECT COUNT(*) AS row_count FROM "<first table>"`. Downstream a row
count is indistinguishable from a real result, so every guard trusted the shape, the
chain kept walking, and synthesis wrote a report around it — filing its OWN failure under
"Data quality notes: aircraft_types: Only row count returned" and recommending the user
run the queries the system had failed to run.

These tests pin the four properties that make that report impossible:
  1. a planner failure produces NO SQL (explore.py + nodes.py both fabricated one);
  2. the failure is legible downstream as a failure, never as evidence;
  3. the honesty preamble names it and forbids the data-quality framing;
  4. an all-failed chain is reported as a failure without a narrator call at all.
"""
import pytest

from aughor.agent.explore import (
    _execute_one_subq,
    _honesty_preamble,
    _reason_one_subq,
    synthesize_exploration,
)
from aughor.agent.state import (
    PLANNER_FAILURE,
    SubQuestion,
    SubQuestionAnswer,
    is_planner_failure,
    planner_failure_result,
)

_SCHEMA = """TABLE: aircraft_types
  code  VARCHAR
  model VARCHAR

TABLE: bookings
  booking_id  BIGINT
  amount      DECIMAL
"""


class FakeConn:
    """A connection that FAILS the test if the chain tries to run anything on it."""
    dialect = "duckdb"

    def __init__(self):
        self.executed: list[str] = []

    def execute(self, tag, sql):        # pragma: no cover - must never be reached
        self.executed.append(sql)
        raise AssertionError(f"no SQL may run after a planner failure, got: {sql}")


class _RaisingProvider:
    def __init__(self, exc=RuntimeError("InstructorRetryException: 2 validation errors")):
        self._exc = exc

    def complete(self, **kwargs):
        raise self._exc


def _state(**over):
    base = {
        "question": "Profile the most unusual entities in this data",
        "schema_context": _SCHEMA,
        "connection_id": "",
        "pitfalls": [],
        "subq_answers": [],
        "sub_questions": [],
        "query_history": [],
        "verification_checks": [],
    }
    base.update(over)
    return base


def _subq(sid="Q2", question="Which entities are unusual?"):
    return SubQuestion(id=sid, question=question, purpose="drill_down",
                       expected_output="a ranked list")


def _answer(**over):
    """One builder for every SubQuestionAnswer these tests need — the model requires the
    full field set, and repeating it per fixture buries the one field each test is about."""
    base = dict(subq_id="Q1", question="q", purpose="drill_down", sql="", columns=[],
                rows=[], row_count=0, error=None, answer="", insight="", refinement=None)
    base.update(over)
    return SubQuestionAnswer(**base)


def _failed_answer(sid="Q2", question="Which entities are unusual?"):
    return _answer(subq_id=sid, question=question, answer=f"{sid} FAILED",
                   error=planner_failure_result(sid, "the planner call failed").error)


def _ok_answer(sid="Q1"):
    return _answer(subq_id=sid, question="What is the delay distribution?",
                   purpose="landscape", sql="SELECT 1", columns=["n"], rows=[[3]],
                   row_count=1, answer="delays are flat")


# ── 1. the planner failure never becomes SQL ─────────────────────────────────

def test_planner_failure_emits_no_sql_and_runs_nothing(monkeypatch):
    monkeypatch.setattr("aughor.agent.explore.get_provider", lambda _role: _RaisingProvider())
    conn = FakeConn()
    results, pitfalls, checks = _execute_one_subq(_state(), _subq(), [], conn)

    assert conn.executed == []                     # the whole point: nothing ran
    assert len(results) == 1
    assert results[0].sql == ""                    # no fabricated query, not even a marked one
    assert is_planner_failure(results[0])
    assert "planner_failed" in checks              # the receipt shows the guard fired
    assert pitfalls == []


def test_no_table_name_from_the_schema_leaks_into_the_failure():
    # The old fallback named whichever table came first in the schema text, which is how
    # `aircraft_types` — a table nobody asked about — became the subject of the report.
    r = planner_failure_result("Q2", "the planner returned an empty query plan")
    assert "aircraft_types" not in r.error
    assert "COUNT(" not in r.error
    assert r.rows == [] and r.row_count == 0


def test_empty_plan_fails_the_same_way_as_a_raising_planner(monkeypatch):
    class _EmptyPlan:
        queries: list = []
        expected_if_true = None
        expected_if_false = None

    class _P:
        def complete(self, **kwargs):
            return _EmptyPlan()

    monkeypatch.setattr("aughor.agent.explore.get_provider", lambda _role: _P())
    results, _p, checks = _execute_one_subq(_state(), _subq(), [], FakeConn())
    assert len(results) == 1 and is_planner_failure(results[0])
    assert "empty query plan" in results[0].error
    assert "planner_failed" in checks


# ── 2. the failure stays legible as a failure ────────────────────────────────

def test_reasoning_calls_it_a_platform_failure_not_a_sql_error(monkeypatch):
    # Reasoning must not call the LLM here, and must not blame SQL — the old wording
    # ("Could not retrieve data … due to SQL errors") is what let the narrator file this
    # against the user's table.
    monkeypatch.setattr("aughor.agent.explore.get_provider",
                        lambda _role: pytest.fail("no LLM call for a failed step"))
    subq = _subq()
    answer, _obj = _reason_one_subq(
        _state(), subq, [planner_failure_result(subq.id, "the planner call failed")], [])

    assert is_planner_failure(answer)              # survives into the answer record
    assert "SQL error" not in answer.answer
    assert "FAILED" in answer.answer
    assert "not a finding about the data" in answer.answer


def test_is_planner_failure_is_precise():
    assert not is_planner_failure(_ok_answer())
    assert is_planner_failure(_failed_answer())
    # A genuine SQL error is a different thing and must not be swept in.
    assert not is_planner_failure(_answer(subq_id="Q3", sql="SELECT 1",
                                          error="Binder Error: no such column"))


# ── 3. the honesty preamble names it and forbids the laundering ──────────────

def test_preamble_names_failed_steps_and_forbids_data_quality_framing():
    text = _honesty_preamble([_ok_answer(), _failed_answer()],
                             [_subq("Q1"), _subq("Q2")], [])
    assert "FAILED INSIDE THE PLATFORM" in text
    assert "Q2" in text
    assert "data-quality note" in text             # explicitly forbidden
    assert "NEVER recommend" in text               # no to-do list of our own failures


def test_preamble_does_not_double_report_a_pure_failure_gap():
    # Failures account for the whole shortfall → the precise block speaks; the vague
    # "later planned steps" fallback must not also fire.
    text = _honesty_preamble([_ok_answer(), _failed_answer()],
                             [_subq("Q1"), _subq("Q2")], [])
    assert "later planned steps" not in text


def test_preamble_counts_only_steps_that_produced_evidence():
    # Three planned, one answered, one failed, one never ran: the chain is INCOMPLETE
    # and the count must not include the failure.
    text = _honesty_preamble([_ok_answer(), _failed_answer()],
                             [_subq("Q1"), _subq("Q2"), _subq("Q3", "and Q3?")], [])
    assert "only 1 of 3" in text
    assert "Q3" in text


def test_preamble_is_silent_on_a_clean_complete_run():
    assert _honesty_preamble([_ok_answer()], [_subq("Q1")], []) == ""


# ── 4. an all-failed chain is reported as a failure, with no narrator call ───

def test_all_failed_chain_reports_failure_without_calling_the_narrator(monkeypatch):
    monkeypatch.setattr("aughor.agent.explore.get_provider",
                        lambda _role: pytest.fail("synthesis must not narrate an empty chain"))
    out = synthesize_exploration(_state(subq_answers=[_failed_answer("Q1"), _failed_answer("Q2")],
                                        sub_questions=[_subq("Q1"), _subq("Q2")]))
    rep = out["explore_report"]

    assert "could not be run" in rep.headline
    assert "Q1, Q2" in rep.conclusion
    assert "no findings" in rep.conclusion
    assert not rep.data_quality_notes              # a failure is never a data-quality note
    # And it never hands back the work the system failed to do.
    joined = " ".join(rep.recommended_actions).lower()
    assert "re-run the investigation" in joined
    assert "execute" not in joined and "query" not in joined


def test_marker_prefix_is_stable():
    # Every consumer keys off this prefix; renaming it silently unguards them all.
    assert planner_failure_result("Q1", "why").error.startswith(PLANNER_FAILURE)
