"""SE-5a — Quick Fix proposes a repair and never runs it.

The agent's execute path has a repair loop whose safety comes from EXECUTION: it runs its
candidate and keeps it only if the run improved. Quick Fix reuses the same prompt and the
same `coder` role with that safety net removed, so the guarantees have to be structural
instead:

  1. It NEVER executes the proposal. The statement is the user's, and running an LLM's
     rewrite without consent is a write they did not ask for.
  2. It NEVER auto-applies. The response is a proposal; the diff is the review step.
  3. "No change" is a real answer, not the input echoed back as a fix — an empty diff
     with an Apply button lets the user apply their own statement to itself.
  4. The proposal passes the same safety gate a run would, and a provider outage is 502
     (upstream), not 500 (which would read as "your query broke the server").
"""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.db import registry

client = TestClient(app)


@pytest.fixture()
def conn(tmp_path):
    db = tmp_path / "qf.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE orders AS SELECT 1 AS id, 'EMEA' AS region, 10.0 AS amount")
    c.close()
    cid = registry.add_connection("se5a-qf", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)


@pytest.fixture()
def fake_llm(monkeypatch):
    """A stand-in `coder` provider. The point of these tests is the ROUTE's contract —
    what it runs, what it refuses, what it returns — not the model's SQL."""
    calls = []

    class _P:
        def __init__(self, fixed="SELECT region FROM orders", why="Column was misspelled."):
            self.fixed, self.why = fixed, why

        def complete(self, system, user, response_model):
            calls.append({"system": system, "user": user})
            return response_model(fixed_sql=self.fixed, explanation=self.why)

    holder = {"p": _P()}
    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: holder["p"])
    return holder, calls, _P


# ── 1 & 2. it proposes, and nothing runs ──────────────────────────────────────

def test_proposes_a_fix_without_executing_anything(conn, fake_llm, monkeypatch):
    """The load-bearing guarantee. Any execute on this path is a bug, so the connector's
    execute methods are booby-trapped for the duration of the call."""
    import aughor.db.connection as dbconn
    real_open = dbconn.open_connection_for

    def _no_exec_open(cid):
        db = real_open(cid)
        for name in ("execute", "execute_typed", "execute_with_params", "bulk_read"):
            if hasattr(db, name):
                monkeypatch.setattr(db, name,
                                    lambda *a, **k: pytest.fail("Quick Fix executed SQL"),
                                    raising=False)
        return db

    monkeypatch.setattr("aughor.db.connection.open_connection_for", _no_exec_open)
    r = client.post("/query/quickfix", json={
        "conn_id": conn, "sql": "SELECT regionn FROM orders",
        "error": 'Referenced column "regionn" not found'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True
    assert body["proposed_sql"] == "SELECT region FROM orders"
    assert body["rationale"] == "Column was misspelled."


def test_the_response_carries_no_rows_and_no_apply(conn, fake_llm):
    """A proposal, not a result. Anything row-shaped here would invite a surface to
    render it as though the fix had already run."""
    r = client.post("/query/quickfix", json={
        "conn_id": conn, "sql": "SELECT regionn FROM orders", "error": "boom"})
    assert set(r.json()) == {"proposed_sql", "rationale", "changed", "diagnosis"}


def test_the_error_and_schema_reach_the_prompt(conn, fake_llm):
    """Without the schema the model invents column names; without the error it guesses
    what went wrong. Both are what separate this from 'rewrite my SQL'."""
    _, calls, _ = fake_llm
    client.post("/query/quickfix", json={
        "conn_id": conn, "sql": "SELECT regionn FROM orders",
        "error": 'Referenced column "regionn" not found'})
    prompt = calls[-1]["user"]
    assert "regionn" in prompt and "orders" in prompt
    assert "not found" in prompt


# ── 3. "no change" is an answer ───────────────────────────────────────────────

def test_an_unchanged_proposal_reports_no_change(conn, fake_llm):
    holder, _, P = fake_llm
    holder["p"] = P(fixed="SELECT region FROM orders")
    r = client.post("/query/quickfix", json={
        "conn_id": conn, "sql": "SELECT region FROM orders", "error": "boom"})
    body = r.json()
    assert body["changed"] is False and body["proposed_sql"] == "", \
        "the input was echoed back as a fix — an empty diff with an Apply button"


def test_an_empty_proposal_reports_no_change(conn, fake_llm):
    holder, _, P = fake_llm
    holder["p"] = P(fixed="   ")
    r = client.post("/query/quickfix", json={
        "conn_id": conn, "sql": "SELECT region FROM orders", "error": "boom"})
    assert r.json()["changed"] is False


# ── 4. gates and failure modes ────────────────────────────────────────────────

def test_empty_sql_is_rejected(conn, fake_llm):
    r = client.post("/query/quickfix", json={"conn_id": conn, "sql": "  ", "error": "x"})
    assert r.status_code == 400


def test_unknown_connection_is_404(fake_llm):
    r = client.post("/query/quickfix", json={
        "conn_id": "nope", "sql": "SELECT 1", "error": "x"})
    assert r.status_code in (403, 404)


def test_a_mutating_statement_is_refused(conn, fake_llm):
    """A fix suggested for a statement we would refuse to RUN is not a fix worth showing —
    and the proposal comes back to a surface with an Apply button."""
    r = client.post("/query/quickfix", json={
        "conn_id": conn, "sql": "DROP TABLE orders", "error": "x"})
    assert r.status_code == 400, "a DDL statement reached the repair model"


def test_a_provider_outage_is_502_not_500(conn, monkeypatch):
    """The repair provider is upstream. A 500 would read as 'your query broke the
    server' — the user would go looking at their SQL for a fault that is ours."""
    class _Down:
        def complete(self, **kw):
            raise RuntimeError("no provider configured")
    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: _Down())
    r = client.post("/query/quickfix", json={
        "conn_id": conn, "sql": "SELECT regionn FROM orders", "error": "x"})
    assert r.status_code == 502
    assert "unavailable" in r.json()["detail"].lower()
