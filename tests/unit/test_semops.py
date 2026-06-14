"""Unit tests for the semantic operators (aughor/semops) — text detection, filter, extract.

The LLM is replaced by a deterministic fake provider that parses the ``[index] text`` listing the
operator builds and applies a test-supplied python rule, so these assert the operator *plumbing*
(batching, row subsetting, column appending, cap refusal, fail-open) without any model call.
"""
from __future__ import annotations

import re

import pytest

from aughor.agent.state import QueryResult
from aughor.semops import operators as ops
from aughor.semops.operators import (
    _ExtractBatch,
    _ExtractedRow,
    _FilterBatch,
    _RowVerdict,
    apply_step,
    detect_text_columns,
    semantic_extract,
    semantic_filter,
)

_LINE = re.compile(r"^\[(\d+)\]\s?(.*)$", re.M)


class FakeProvider:
    """Parses the operator's row listing and applies a python rule per row."""

    def __init__(self, *, filter_fn=None, extract_fn=None, fail=False):
        self.filter_fn = filter_fn
        self.extract_fn = extract_fn
        self.fail = fail
        self.calls = 0

    def complete(self, *, system, user, response_model):
        self.calls += 1
        if self.fail:
            raise RuntimeError("simulated LLM failure")
        items = [(int(i), t) for i, t in _LINE.findall(user)]
        if response_model is _FilterBatch:
            return _FilterBatch(verdicts=[_RowVerdict(index=i, keep=bool(self.filter_fn(t))) for i, t in items])
        if response_model is _ExtractBatch:
            return _ExtractBatch(rows=[_ExtractedRow(index=i, values=self.extract_fn(t)) for i, t in items])
        raise AssertionError(f"unexpected response_model {response_model!r}")


@pytest.fixture
def patch_provider(monkeypatch):
    def _install(provider: FakeProvider):
        monkeypatch.setattr(ops, "get_provider", lambda role=None: provider)
        return provider
    return _install


def _qr(columns, rows, *, row_count=None, error=None) -> QueryResult:
    return QueryResult(
        hypothesis_id="t", sql="SELECT 1", columns=columns, rows=rows,
        row_count=row_count if row_count is not None else len(rows), error=error,
    )


# ── text detection ─────────────────────────────────────────────────────────────

def test_detect_text_columns_picks_only_free_text():
    qr = _qr(
        ["id", "amount", "created_at", "note"],
        [
            ["1001", "42.50", "2026-06-15", "server is down, customers cannot log in"],
            ["1002", "8.00", "2026-06-14 09:30", "refund requested for late delivery"],
            ["1003", "100", "2026-06-13", "duplicate charge on the invoice"],
        ],
    )
    assert detect_text_columns(qr) == ["note"]


def test_detect_text_columns_skips_ids_and_empty():
    qr = _qr(["uuid", "blank"], [["a1b2c3d4e5f6a7b8", "NULL"], ["00112233445566778899", ""]])
    assert detect_text_columns(qr) == []


# ── filter ─────────────────────────────────────────────────────────────────────

def test_semantic_filter_keeps_only_matching_rows(patch_provider):
    p = patch_provider(FakeProvider(filter_fn=lambda t: "open" in t.lower()))
    qr = _qr(["note"], [["open: server down"], ["closed: resolved"], ["open: timeout"]])

    out = semantic_filter(qr, "note", "the ticket is still open")

    assert out.output_rows == 2
    assert out.result.rows == [["open: server down"], ["open: timeout"]]
    assert out.result.row_count == 2
    assert out.input_rows == 3
    assert out.llm_calls == 1
    assert out.truncated is False
    assert "kept 2 of 3" in out.notes[0]


def test_semantic_filter_batches(patch_provider):
    p = patch_provider(FakeProvider(filter_fn=lambda t: True))
    qr = _qr(["note"], [[f"row {i}"] for i in range(5)])

    out = semantic_filter(qr, "note", "anything", batch=2)

    assert out.output_rows == 5
    assert p.calls == 3  # ceil(5/2)


def test_semantic_filter_missing_column_is_noop(patch_provider):
    p = patch_provider(FakeProvider(filter_fn=lambda t: False))
    qr = _qr(["note"], [["x"]])

    out = semantic_filter(qr, "nope", "p")

    assert out.output_rows == 1            # unchanged
    assert p.calls == 0
    assert "not in the result" in out.notes[0]


def test_semantic_filter_refuses_over_cap(patch_provider):
    p = patch_provider(FakeProvider(filter_fn=lambda t: False))
    qr = _qr(["note"], [["a"], ["b"]], row_count=5000)  # true count far over the cap

    out = semantic_filter(qr, "note", "p", max_rows=200)

    assert out.truncated is True
    assert out.output_rows == 5000         # untouched
    assert p.calls == 0
    assert "exceeds the semantic-operator cap" in out.notes[0]


def test_semantic_filter_override_cap_processes(patch_provider):
    p = patch_provider(FakeProvider(filter_fn=lambda t: "keep" in t))
    qr = _qr(["note"], [["keep me"], ["drop me"]], row_count=5000)

    out = semantic_filter(qr, "note", "p", max_rows=1, override_cap=True)

    assert out.truncated is False
    assert out.output_rows == 1
    assert p.calls == 1
    # surfaced: only the materialized rows were processed
    assert any("materialized" in n for n in out.notes)


def test_semantic_filter_fail_open_on_llm_error(patch_provider):
    p = patch_provider(FakeProvider(fail=True))
    qr = _qr(["note"], [["a"], ["b"]])

    out = semantic_filter(qr, "note", "p")

    assert out.output_rows == 2            # nothing silently dropped
    assert out.llm_calls == 0
    assert any("failed" in n for n in out.notes)


def test_semantic_filter_fail_open_on_missing_verdict(patch_provider):
    # model returns verdicts only for even indices → odd rows must be kept (fail-open)
    class Partial(FakeProvider):
        def complete(self, *, system, user, response_model):
            self.calls += 1
            items = [(int(i), t) for i, t in _LINE.findall(user)]
            return _FilterBatch(verdicts=[_RowVerdict(index=i, keep=False) for i, t in items if i % 2 == 0])

    p = patch_provider(Partial())
    qr = _qr(["note"], [["r0"], ["r1"], ["r2"], ["r3"]])

    out = semantic_filter(qr, "note", "p")

    assert out.result.rows == [["r1"], ["r3"]]  # evens dropped, odds kept by fail-open


def test_semantic_filter_upstream_error_is_noop(patch_provider):
    p = patch_provider(FakeProvider(filter_fn=lambda t: True))
    qr = _qr([], [], error="syntax error near FROM")

    out = semantic_filter(qr, "note", "p")

    assert p.calls == 0
    assert "upstream SQL error" in out.notes[0]


# ── extract ────────────────────────────────────────────────────────────────────

def test_semantic_extract_appends_columns(patch_provider):
    p = patch_provider(FakeProvider(
        extract_fn=lambda t: {"severity": "high" if "down" in t else "low", "component": "db"}
    ))
    qr = _qr(["id", "note"], [["1", "server down"], ["2", "minor glitch"]])

    out = semantic_extract(qr, "note", [("severity", "how bad"), ("component", "subsystem")])

    assert out.result.columns == ["id", "note", "severity", "component"]
    assert out.result.rows[0] == ["1", "server down", "high", "db"]
    assert out.result.rows[1] == ["2", "minor glitch", "low", "db"]
    assert out.result.row_count == 2
    assert out.llm_calls == 1


def test_semantic_extract_uniquifies_colliding_field_name(patch_provider):
    p = patch_provider(FakeProvider(extract_fn=lambda t: {"note": "summary"}))
    qr = _qr(["note"], [["the full text"]])

    out = semantic_extract(qr, "note", [("note", "a summary")])

    assert out.result.columns == ["note", "note_2"]
    assert out.result.rows[0] == ["the full text", "summary"]


def test_semantic_extract_blank_on_llm_error(patch_provider):
    p = patch_provider(FakeProvider(fail=True))
    qr = _qr(["note"], [["x"], ["y"]])

    out = semantic_extract(qr, "note", [("a", ""), ("b", "")])

    assert out.result.columns == ["note", "a", "b"]
    assert out.result.rows[0] == ["x", "", ""]   # fields blank, original kept
    assert out.result.rows[1] == ["y", "", ""]


def test_semantic_extract_no_fields_is_noop(patch_provider):
    p = patch_provider(FakeProvider(extract_fn=lambda t: {}))
    qr = _qr(["note"], [["x"]])

    out = semantic_extract(qr, "note", [])

    assert p.calls == 0
    assert out.result.columns == ["note"]
    assert "no fields" in out.notes[0]


# ── apply_step dispatcher ────────────────────────────────────────────────────────

def test_apply_step_dispatches_filter(patch_provider):
    patch_provider(FakeProvider(filter_fn=lambda t: "keep" in t))
    qr = _qr(["note"], [["keep this"], ["drop that"]])

    out = apply_step(qr, "filter", "note", predicate="p")

    assert out.operator == "filter"
    assert out.result.rows == [["keep this"]]


def test_apply_step_dispatches_extract(patch_provider):
    patch_provider(FakeProvider(extract_fn=lambda t: {"k": "v"}))
    qr = _qr(["note"], [["x"]])

    out = apply_step(qr, "extract", "note", fields=[("k", "the k")])

    assert out.operator == "extract"
    assert out.result.columns == ["note", "k"]


def test_apply_step_unknown_operator_raises():
    qr = _qr(["note"], [["x"]])
    with pytest.raises(ValueError, match="unknown semantic operator"):
        apply_step(qr, "summarize", "note")
