"""SE-8E — the editor's AI pane endpoint: it proposes, and nothing runs.

Same structural guarantees as Quick Fix (which it generalises), asserted the same way:
no execution on this path, SQL comes back as a PROPOSAL field for a diff, an identical
proposal reports no change, the buffer passes the run gate, and a provider outage is
502 — upstream, not "your ask broke the server".
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
    db = tmp_path / "assist.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE orders AS SELECT 1 AS id, 'EMEA' AS region, 10.0 AS amount")
    c.close()
    cid = registry.add_connection("se8e-assist", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)


@pytest.fixture()
def fake_llm(monkeypatch):
    calls = []

    class _P:
        def __init__(self, reply="Grouped by region.", proposed="SELECT region, SUM(amount) FROM orders GROUP BY region"):
            self.reply, self.proposed = reply, proposed

        def complete(self, system, user, response_model):
            calls.append({"system": system, "user": user})
            return response_model(reply=self.reply, proposed_sql=self.proposed)

    holder = {"p": _P()}
    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: holder["p"])
    return holder, calls, _P


def _ask(conn_id, **kw):
    body = {"conn_id": conn_id, "instruction": "sum amount by region", **kw}
    return client.post("/query/assist", json=body)


def test_proposes_without_executing_anything(conn, fake_llm, monkeypatch):
    import aughor.db.connection as dbconn
    real_open = dbconn.open_connection_for

    def _no_exec_open(cid):
        db = real_open(cid)
        for name in ("execute", "execute_typed", "execute_with_params", "bulk_read"):
            if hasattr(db, name):
                monkeypatch.setattr(
                    db, name,
                    lambda *a, _n=name, **k: (_ for _ in ()).throw(AssertionError(f"{_n} ran on the assist path")),
                    raising=False,
                )
        return db

    monkeypatch.setattr(dbconn, "open_connection_for", _no_exec_open)
    r = _ask(conn, sql="SELECT * FROM orders")
    assert r.status_code == 200
    body = r.json()
    assert body["changed"] is True
    assert "GROUP BY region" in body["proposed_sql"]
    assert body["reply"]
    # No rows in the response — this endpoint has nothing to show, only to propose.
    assert "rows" not in body and "columns" not in body


def test_schema_history_and_error_reach_the_prompt(conn, fake_llm):
    _, calls, _ = fake_llm
    r = _ask(conn, sql="SELECT 1", error="Binder Error: nope",
             history=[{"role": "user", "content": "earlier ask"}])
    assert r.status_code == 200
    prompt = calls[-1]["user"]
    assert "orders" in prompt                  # the schema
    assert "earlier ask" in prompt             # the history
    assert "Binder Error: nope" in prompt      # the error
    assert "sum amount by region" in prompt    # the instruction


def test_an_identical_proposal_reports_no_change(conn, fake_llm):
    holder, _, P = fake_llm
    holder["p"] = P(reply="Looks fine.", proposed="SELECT * FROM orders")
    r = _ask(conn, sql="SELECT * FROM orders")
    assert r.status_code == 200
    assert r.json() == {"reply": "Looks fine.", "proposed_sql": "", "changed": False}


def test_a_missing_instruction_is_rejected(conn, fake_llm):
    r = client.post("/query/assist", json={"conn_id": conn, "instruction": "   "})
    assert r.status_code == 400


def test_a_mutating_buffer_is_refused_by_the_run_gate(conn, fake_llm):
    r = _ask(conn, sql="DELETE FROM orders")
    assert r.status_code == 400


def test_a_provider_outage_is_502_not_500(conn, monkeypatch):
    class _Down:
        def complete(self, *a, **k):
            raise RuntimeError("provider down")
    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: _Down())
    r = _ask(conn, sql="SELECT 1")
    assert r.status_code == 502
