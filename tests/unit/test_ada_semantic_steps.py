"""Unit tests for the ADA agent's semantic-step integration (investigate._apply_semantic_steps).

A phase-plan query may carry an opt-in ``.semantic`` operator; after the SQL runs, the operator
transforms that query's result so the phase interpreter reasons over text-derived evidence. These
tests assert the wiring is opt-in, guarded (non-text/missing columns skipped), and fail-open — with
the LLM faked, exactly as the operator unit tests do.
"""
from __future__ import annotations

import re

import pytest

from aughor.agent.investigate import _apply_semantic_steps
from aughor.agent.prompts_investigate import PhaseQueryPlan, SemanticField, SemanticStep
from aughor.agent.state import QueryResult
from aughor.semops import operators as ops
from aughor.semops.operators import _ExtractBatch, _ExtractedRow, _FilterBatch, _RowVerdict

_LINE = re.compile(r"^\[(\d+)\]\s?(.*)$", re.M)


class _Fake:
    def __init__(self):
        self.calls = 0

    def complete(self, *, system, user, response_model):
        self.calls += 1
        items = [(int(i), t) for i, t in _LINE.findall(user)]
        if response_model is _FilterBatch:
            return _FilterBatch(verdicts=[_RowVerdict(index=i, keep="open" in t.lower()) for i, t in items])
        if response_model is _ExtractBatch:
            return _ExtractBatch(rows=[_ExtractedRow(index=i, values={"status": "open"}) for i, t in items])
        raise AssertionError(response_model)


@pytest.fixture
def fake_llm(monkeypatch):
    fake = _Fake()
    monkeypatch.setattr(ops, "get_provider", lambda role=None: fake)
    return fake


def _q(sql="SELECT note FROM tickets", *, semantic=None) -> PhaseQueryPlan:
    return PhaseQueryPlan(title="t", sql=sql, rationale="r", semantic=semantic)


def _res(columns, rows, *, error=None) -> QueryResult:
    return QueryResult(hypothesis_id="phase", sql="SELECT 1", columns=columns, rows=rows,
                       row_count=len(rows), error=error)


_TEXT_ROWS = [["open: server is down"], ["closed: resolved"], ["open: login timeout"]]


def test_filter_step_transforms_text_result(fake_llm):
    step = SemanticStep(operator="filter", column="note", predicate="the ticket is open")
    results = [(_q(semantic=step), _res(["note"], _TEXT_ROWS))]

    out = _apply_semantic_steps(results)

    assert len(out) == 1
    _, r = out[0]
    assert r.row_count == 2
    assert all("open" in row[0].lower() for row in r.rows)
    assert fake_llm.calls == 1


def test_extract_step_appends_column(fake_llm):
    step = SemanticStep(operator="extract", column="note",
                        fields=[SemanticField(name="status", description="open or closed")])
    results = [(_q(semantic=step), _res(["note"], _TEXT_ROWS))]

    out = _apply_semantic_steps(results)

    _, r = out[0]
    assert r.columns == ["note", "status"]
    assert r.rows[0] == ["open: server is down", "open"]


def test_no_step_is_passthrough(fake_llm):
    results = [(_q(semantic=None), _res(["note"], _TEXT_ROWS))]

    out = _apply_semantic_steps(results)

    assert out[0][1].row_count == 3      # unchanged
    assert fake_llm.calls == 0           # operator never invoked


def test_step_on_non_text_column_is_skipped(fake_llm):
    # the planner mis-attached a filter to a numeric column → guard skips it, no LLM call
    step = SemanticStep(operator="filter", column="amount", predicate="big")
    results = [(_q(semantic=step), _res(["amount"], [["10"], ["20"], ["30"]]))]

    out = _apply_semantic_steps(results)

    assert out[0][1].row_count == 3      # untouched
    assert fake_llm.calls == 0


def test_step_on_missing_column_is_skipped(fake_llm):
    step = SemanticStep(operator="filter", column="nope", predicate="x")
    results = [(_q(semantic=step), _res(["note"], _TEXT_ROWS))]

    out = _apply_semantic_steps(results)

    assert out[0][1].row_count == 3
    assert fake_llm.calls == 0


def test_errored_result_is_skipped(fake_llm):
    step = SemanticStep(operator="filter", column="note", predicate="x")
    results = [(_q(semantic=step), _res([], [], error="boom"))]

    out = _apply_semantic_steps(results)

    assert out[0][1].error == "boom"
    assert fake_llm.calls == 0


def test_mixed_batch_only_transforms_the_stepped_query(fake_llm):
    stepped = (_q(semantic=SemanticStep(operator="filter", column="note", predicate="open")),
               _res(["note"], _TEXT_ROWS))
    plain = (_q(sql="SELECT revenue FROM sales", semantic=None), _res(["revenue"], [["100"], ["200"]]))

    out = _apply_semantic_steps([stepped, plain])

    assert out[0][1].row_count == 2      # filtered
    assert out[1][1].row_count == 2      # passthrough, untouched
