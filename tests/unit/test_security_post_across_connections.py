"""A cross-source answer passes the post-execution gate for every connection it read (Arc ON leftovers, F7).

`_security_post` is where PII redaction, the row budget and the audit record happen, and plumbing labels skip it — so
an answer joined across connections is posted once, under its home connection, naming the others it read in
``also_read``: the strictest row budget among them applies, and each connection's audit trail records the answer."""
from __future__ import annotations

import uuid

from aughor.control_plane.contracts.execution import QueryResult
from aughor.db.connection import security_post
from aughor.security import sandbox
from aughor.security.audit import AuditLogger


def _ids(n: int) -> list[str]:
    return [f"xs-{uuid.uuid4().hex[:10]}" for _ in range(n)]


def _result(rows: int) -> QueryResult:
    return QueryResult(hypothesis_id="h", sql="SELECT k, email FROM t", columns=["k", "email"],
                       rows=[[f"k{i}", f"user{i}@example.com"] for i in range(rows)], row_count=rows)


def test_the_answer_is_audited_once_on_every_connection_it_read():
    home, far = _ids(2)
    label = f"join-{uuid.uuid4().hex[:8]}"
    out = security_post(home, label, "SELECT k, email FROM t", _result(3), 2.0, also_read=[far, home, far, ""])
    for connection_id in (home, far):
        records = AuditLogger.recent(50, connection_id=connection_id, label=label)
        assert len(records) == 1, connection_id
        assert records[0]["verdict"] == "safe" and records[0]["row_count"] == 3 and records[0]["pii_redacted"] == 3
    assert [row[1] for row in out.rows] == ["[REDACTED]"] * 3


def test_the_strictest_row_budget_among_the_connections_read_applies(monkeypatch):
    home, far = _ids(2)
    monkeypatch.setitem(sandbox._REGISTRY, far, sandbox.QueryBudget(max_rows=2))
    capped = security_post(home, "join", "SELECT k, email FROM t", _result(5), 1.0, also_read=[far])
    assert len(capped.rows) == 2 and capped.row_count == 5
    alone = security_post(home, "join", "SELECT k, email FROM t", _result(5), 1.0)
    assert len(alone.rows) == 5


def test_an_answer_from_one_connection_is_audited_there_only():
    home, other = _ids(2)
    label = f"one-{uuid.uuid4().hex[:8]}"
    security_post(home, label, "SELECT k, email FROM t", _result(1), 1.0)
    assert len(AuditLogger.recent(50, connection_id=home, label=label)) == 1
    assert AuditLogger.recent(50, connection_id=other, label=label) == []
