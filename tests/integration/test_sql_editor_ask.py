"""`/ask` in the SQL editor — `POST /query/ask` (2026-10-12).

The user: "a user typing '/ask' and after that writing what is expected from the SQL … deliver the SQL based on the
robust framework that we already have … we don't deliver analysis we only deliver SQL". So the route is Quick
analysis's own core, stopped at the statement (`frame_only`): the statement comes back, nothing runs, no narrative is
written, and no chat turn is saved — including on the two paths that end before a statement exists (an honest
abstention, a definitional answer), which saved a turn even under `frame_only` until this change.
"""
from __future__ import annotations

import types
import uuid

import pytest

from aughor.routers import investigations as inv
from tests.integration.test_stream_chat_transcript import _stub_providers


@pytest.fixture
def no_execute_no_turn(monkeypatch):
    """The two things `/ask` must never do, as tripwires: run the statement, or save a chat turn."""
    saved: list = []

    def _never_execute(*a, **k):
        raise AssertionError("/ask ran the statement")

    monkeypatch.setattr(inv, "_execute_chat_sql", _never_execute)
    monkeypatch.setattr(inv, "save_chat_turn", lambda **kw: saved.append(kw) or "inv-x")
    return saved


def test_the_editor_gets_the_statement_the_quick_path_writes_and_nothing_runs(client, builtin_conn_id,
                                                                              monkeypatch, no_execute_no_turn):
    _stub_providers(monkeypatch)
    r = client.post("/query/ask", json={"conn_id": builtin_conn_id, "request": "How many rows are there?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "framed"
    assert body["sql"] == "SELECT * FROM (VALUES (1, 2), (3, 4)) AS t(x, y)"
    assert isinstance(body["notes"], list)
    assert no_execute_no_turn == [], "a framed /ask became a chat turn"


def test_an_abstention_is_said_and_saves_no_chat_turn(client, builtin_conn_id, monkeypatch, no_execute_no_turn):
    """The abstain path saved a turn even under `frame_only` — an agent's evaluation or an editor request would have
    appeared in the person's chat history."""
    _stub_providers(monkeypatch)
    from aughor.semantic import answer_resolution as res
    monkeypatch.setattr(res, "resolve", lambda *a, **k: res.Resolution(
        question="q", not_found=["planet"], what_is_available="Countries are present."))
    r = client.post("/query/ask", json={"conn_id": builtin_conn_id, "request": "revenue by planet"})
    assert r.status_code == 422
    assert r.json()["detail"] == "“planet” is not present in this data. Countries are present."
    assert no_execute_no_turn == []
    direct = inv._answer_core("revenue by planet", builtin_conn_id, [], emit=lambda t, p: None,
                              skip_clarify=True, frame_only=True)
    assert direct.outcome == "abstained" and no_execute_no_turn == []


def _framed(monkeypatch, sql: str, receipts=None):
    monkeypatch.setattr(inv, "answer_core", lambda *a, **k: types.SimpleNamespace(
        outcome="framed", sql=sql, guard_receipts=receipts or [], headline="", error="", mode=""))


def test_a_statement_that_writes_is_never_handed_back(client, monkeypatch):
    _framed(monkeypatch, "DELETE FROM orders")
    r = client.post("/query/ask", json={"conn_id": "fixture", "request": "clear the orders"})
    assert r.status_code == 422 and "change data" in r.json()["detail"]


def test_a_statement_reading_a_table_turned_off_is_refused_in_words(client, monkeypatch):
    from aughor.ontology.visibility import declare_exclusion
    conn = f"ask-{uuid.uuid4().hex[:8]}"
    declare_exclusion(conn, "main", "orders_archive", "out_of_domain", declared_by="amit")
    monkeypatch.setattr("aughor.routers.query._check_conn_org", lambda *a, **k: None)
    _framed(monkeypatch, "SELECT COUNT(*) FROM orders_archive")
    r = client.post("/query/ask", json={"conn_id": conn, "request": "archived orders", "schema_name": "main"})
    assert r.status_code == 422
    assert r.json()["detail"].startswith("main.orders_archive is turned off for analysis")


def test_what_a_guard_did_is_said_above_the_statement(client, monkeypatch):
    _framed(monkeypatch, "SELECT 1", receipts=[
        {"guard": "fanout_defan", "action": "rewrote_sql"},
        {"guard": "count_star_entity_grain", "action": "hinted"},
        {"guard": "headline_grounding", "action": "grounded"},          # not a statement change: not said
        {"guard": "fanout_defan", "action": "rewrote_sql"}])             # once
    r = client.post("/query/ask", json={"conn_id": "fixture", "request": "orders per customer"})
    assert r.status_code == 200
    assert r.json()["notes"] == ["a join that would have double-counted was rewritten",
                                 "check: COUNT(*) may count rows rather than the thing asked about"]


def test_a_bare_ask_is_refused_before_any_model_call(client, monkeypatch):
    monkeypatch.setattr(inv, "answer_core", lambda *a, **k: pytest.fail("a bare /ask reached the core"))
    r = client.post("/query/ask", json={"conn_id": "fixture", "request": "   "})
    assert r.status_code == 400


def test_the_editor_statement_travels_as_the_turn_it_builds_on(client, monkeypatch):
    seen: dict = {}

    def core(question, conn, history, **kw):
        seen.update(question=question, history=history, kw=kw)
        return types.SimpleNamespace(outcome="framed", sql="SELECT 2", guard_receipts=[], headline="", error="", mode="")

    monkeypatch.setattr(inv, "answer_core", core)
    r = client.post("/query/ask", json={"conn_id": "fixture", "request": "by month too",
                                        "sql": "SELECT country, SUM(x) FROM t GROUP BY 1", "schema_name": "thelook"})
    assert r.status_code == 200
    assert seen["question"] == "by month too"
    assert [h.sql for h in seen["history"]] == ["SELECT country, SUM(x) FROM t GROUP BY 1"]
    assert seen["kw"]["frame_only"] is True and seen["kw"]["skip_clarify"] is True
    assert seen["kw"]["schema_scope"] == "thelook" and seen["kw"]["purpose"] == "sql_editor_ask"


def test_a_request_never_builds_on_an_editor_statement_that_writes(client, monkeypatch):
    """Ported from the pane's route: a statement written on top of one the run gate would refuse is a way around it."""
    monkeypatch.setattr(inv, "answer_core", lambda *a, **k: pytest.fail("a writing buffer reached the core"))
    r = client.post("/query/ask", json={"conn_id": "fixture", "request": "only last month",
                                        "sql": "DELETE FROM orders WHERE 1=1"})
    assert r.status_code == 400 and "changes data" in r.json()["detail"]


# ── what each recent run does, in words (`POST /query/describe`) ──────────────

def test_recent_runs_are_described_in_order_and_one_that_does_not_say_gets_no_words(client):
    r = client.post("/query/describe", json={"conn_id": "fixture", "statements": [
        "SELECT * FROM (SELECT country, SUM(sale_price) AS sales FROM order_items GROUP BY 1) AS __q LIMIT 501",
        "not sql",
        "SELECT COUNT(*) FROM events"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"titles": ["Sales by country", "", "Row count in events"]}


def test_describing_is_bounded(client):
    r = client.post("/query/describe", json={"conn_id": "fixture", "statements": ["SELECT 1"] * 21})
    assert r.status_code == 400
