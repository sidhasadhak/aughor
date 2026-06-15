"""Integration: POST /query/semantic applies a semantic operator end-to-end through the real app.

The SQL runs for real against the in-memory fixture connection; only the LLM is faked (a provider
that keeps/labels rows by keyword), so this exercises the full route → re-run SQL → operator path.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from aughor.semops import operators as ops
from aughor.semops.operators import (
    _Aggregation,
    _ExtractBatch,
    _ExtractedRow,
    _FilterBatch,
    _RowScore,
    _RowVerdict,
    _ScoreBatch,
)

_LINE = re.compile(r"^\[(\d+)\]\s?(.*)$", re.M)

# A table-less result with one free-text column (works on DuckDB and Postgres fixtures).
_SQL = (
    "SELECT note FROM (VALUES ('open: server is down'), ('closed: resolved'), "
    "('open: login timeout')) AS t(note)"
)


class _Fake:
    def complete(self, *, system, user, response_model):
        items = [(int(i), t) for i, t in _LINE.findall(user)]
        if response_model is _FilterBatch:
            return _FilterBatch(verdicts=[_RowVerdict(index=i, keep="open" in t.lower()) for i, t in items])
        if response_model is _ExtractBatch:
            return _ExtractBatch(rows=[
                _ExtractedRow(index=i, values={"status": "open" if "open" in t.lower() else "closed"})
                for i, t in items
            ])
        if response_model is _ScoreBatch:
            return _ScoreBatch(scores=[_RowScore(index=i, score=1.0 if "open" in t.lower() else 0.0) for i, t in items])
        if response_model is _Aggregation:
            return _Aggregation(answer=f"{len(items)} tickets summarized")
        raise AssertionError(f"unexpected response_model {response_model!r}")


@pytest.fixture
def _mock_llm(monkeypatch):
    monkeypatch.setattr(ops, "get_provider", lambda role=None: _Fake())


def test_filter_subsets_rows(client: TestClient, builtin_conn_id: str, _mock_llm):
    r = client.post("/query/semantic", json={
        "conn_id": builtin_conn_id, "sql": _SQL,
        "operator": "filter", "column": "note", "predicate": "the ticket is still open",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert body["operator"] == "filter"
    assert body["input_rows"] == 3
    assert body["output_rows"] == 2
    assert body["row_count"] == 2
    assert all("open" in row[0].lower() for row in body["rows"])
    assert body["llm_calls"] == 1
    assert body["truncated"] is False


def test_extract_appends_a_column(client: TestClient, builtin_conn_id: str, _mock_llm):
    r = client.post("/query/semantic", json={
        "conn_id": builtin_conn_id, "sql": _SQL,
        "operator": "extract", "column": "note",
        "fields": [{"name": "status", "description": "open or closed"}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"][-1] == "status"
    assert body["row_count"] == 3
    statuses = [row[-1] for row in body["rows"]]
    assert statuses == ["open", "closed", "open"]


def test_top_k_ranks_and_truncates(client: TestClient, builtin_conn_id: str, _mock_llm):
    r = client.post("/query/semantic", json={
        "conn_id": builtin_conn_id, "sql": _SQL,
        "operator": "top_k", "column": "note", "criterion": "open tickets", "k": 2,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["operator"] == "top_k"
    assert body["output_rows"] == 2
    assert body["row_count"] == 2
    assert all("open" in row[0].lower() for row in body["rows"])  # the two 'open' rows ranked first


def test_aggregate_returns_one_answer_row(client: TestClient, builtin_conn_id: str, _mock_llm):
    r = client.post("/query/semantic", json={
        "conn_id": builtin_conn_id, "sql": _SQL,
        "operator": "aggregate", "column": "note", "instruction": "summarize the tickets",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["operator"] == "aggregate"
    assert body["columns"] == ["answer"]
    assert body["row_count"] == 1
    assert body["rows"] == [["3 tickets summarized"]]


def test_text_columns_detection(client: TestClient, builtin_conn_id: str):
    r = client.post("/query/semantic/text-columns", json={"conn_id": builtin_conn_id, "sql": _SQL})
    assert r.status_code == 200, r.text
    assert "note" in r.json()["text_columns"]


def test_filter_without_predicate_is_400(client: TestClient, builtin_conn_id: str):
    r = client.post("/query/semantic", json={
        "conn_id": builtin_conn_id, "sql": _SQL, "operator": "filter", "column": "note",
    })
    assert r.status_code == 400


def test_extract_without_fields_is_400(client: TestClient, builtin_conn_id: str):
    r = client.post("/query/semantic", json={
        "conn_id": builtin_conn_id, "sql": _SQL, "operator": "extract", "column": "note",
    })
    assert r.status_code == 400


def test_top_k_without_criterion_is_400(client: TestClient, builtin_conn_id: str):
    r = client.post("/query/semantic", json={
        "conn_id": builtin_conn_id, "sql": _SQL, "operator": "top_k", "column": "note", "k": 2,
    })
    assert r.status_code == 400


def test_aggregate_without_instruction_is_400(client: TestClient, builtin_conn_id: str):
    r = client.post("/query/semantic", json={
        "conn_id": builtin_conn_id, "sql": _SQL, "operator": "aggregate", "column": "note",
    })
    assert r.status_code == 400


def test_unknown_connection_is_404(client: TestClient):
    r = client.post("/query/semantic", json={
        "conn_id": "does-not-exist", "sql": _SQL,
        "operator": "filter", "column": "note", "predicate": "x",
    })
    assert r.status_code == 404
