"""KI-0 (§3.10) — the trusted-SQL door.

The receipt this file IS: an org seeds golden SQL over HTTP; the next ask's prompt
carries it in the trusted block only AFTER a second recorded act approves it; a
failing seed is demonstrably NOT in that block; provenance is on every row. Plus the
fail-closed store semantics everything else leans on: only `approved` reaches
`retrieve_trusted`, and a pre-KI-0 record (no status key) is grandfathered approved.

Hermetic: the store rides a per-test AUGHOR_TRUSTED_QUERIES_PATH; the connection is a
real read-only DuckDB file behind a patched `open_connection_for`.
"""
from __future__ import annotations

import json

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app

client = TestClient(app)

CONN = "ki0conn"
QUESTION = "monthly revenue by region"
GOOD_SQL = "SELECT region, SUM(amount) AS revenue FROM sales GROUP BY region"


@pytest.fixture()
def tq_store(tmp_path, monkeypatch):
    path = tmp_path / "trusted_queries.json"
    monkeypatch.setenv("AUGHOR_TRUSTED_QUERIES_PATH", str(path))
    return path


@pytest.fixture()
def demo_conn(tmp_path, monkeypatch):
    """A real DuckDB file behind `open_connection_for`, opened read-only per call."""
    dbfile = tmp_path / "ki0.duckdb"
    c = duckdb.connect(str(dbfile))
    c.execute("CREATE TABLE sales AS SELECT * FROM (VALUES "
              "('emea', 100), ('emea', 50), ('apac', 70)) AS t(region, amount)")
    c.close()

    from aughor.db import connection as conn_mod

    def _open(conn_id, *args, **kwargs):
        if conn_id != CONN:
            raise KeyError(conn_id)
        return conn_mod.DuckDBConnection(dbfile, connection_id=conn_id)

    monkeypatch.setattr(conn_mod, "open_connection_for", _open)
    return CONN


# ── store semantics: fail closed, grandfather the past ───────────────────────────────


def test_legacy_row_without_status_loads_approved(tq_store):
    from aughor.semantic.trusted_queries import list_trusted, retrieve_trusted

    tq_store.write_text(json.dumps([{
        "id": "tq_legacy", "connection_id": CONN,
        "question": QUESTION, "sql": GOOD_SQL,
    }]))
    rows = list_trusted(CONN)
    assert [r.id for r in rows] == ["tq_legacy"]
    assert rows[0].status == "approved" and rows[0].source == "legacy"
    # …and it still reaches the prompt, exactly as it did before KI-0.
    assert retrieve_trusted(QUESTION, CONN)


def test_only_approved_rows_reach_the_prompt(tq_store):
    from aughor.semantic.trusted_queries import (
        TrustedQuery, list_trusted, retrieve_trusted, save_trusted)

    for status in ("draft", "proposed", "deprecated"):
        save_trusted(TrustedQuery(id=f"tq_{status}", connection_id=CONN,
                                  question=QUESTION, sql=GOOD_SQL, status=status))
    assert list_trusted(CONN) == []
    assert retrieve_trusted(QUESTION, CONN) == []
    assert {t.id for t in list_trusted(CONN, include_unapproved=True)} == {
        "tq_draft", "tq_proposed", "tq_deprecated"}

    save_trusted(TrustedQuery(id="tq_ok", connection_id=CONN,
                              question=QUESTION, sql=GOOD_SQL, status="approved"))
    assert [t.id for t in list_trusted(CONN)] == ["tq_ok"]
    assert [t.id for t, _ in retrieve_trusted(QUESTION, CONN)] == ["tq_ok"]


# ── verification: execute + the shared battery, mutations never run ──────────────────


def test_verify_executes_and_passes_good_sql(demo_conn):
    from aughor.semantic.trusted_verify import verify

    report = verify(CONN, "SELECT region, SUM(amount) FROM sales GROUP BY region")
    assert report["passed"] is True
    assert report["execution"]["ok"] and report["execution"]["row_count"] == 2
    assert report["battery"] is not None and not report["blockers"]


def test_verify_blocks_mutations_before_any_execution(demo_conn):
    from aughor.semantic.trusted_verify import verify

    report = verify(CONN, "DELETE FROM sales")
    assert report["passed"] is False
    assert report["blockers"] and report["battery"] is None
    assert "not executed" in report["execution"]["error"]
    # Nothing ran: the table still holds its three rows.
    from aughor.db.connection import open_connection_for
    db = open_connection_for(CONN)
    try:
        r = db.execute("__probe__", "SELECT COUNT(*) FROM sales")
        assert int(r.rows[0][0]) == 3  # the connection layer stringifies values
    finally:
        db.close()


def test_verify_fails_on_execution_error(demo_conn):
    from aughor.semantic.trusted_verify import verify

    report = verify(CONN, "SELECT nope FROM no_such_table")
    assert report["passed"] is False
    assert report["execution"]["ok"] is False and report["execution"]["error"]


# ── the door: seed → propose → approve, and the receipt at the prompt ────────────────


def _seed(sql=GOOD_SQL, question=QUESTION, **over):
    body = {"connection_id": CONN, "question": question, "sql": sql,
            "actor": "ana@example.com", **over}
    return client.post("/learning/trusted", json=body)


def test_seed_approve_and_the_prompt_block(tq_store, demo_conn):
    from aughor.semantic.trusted_queries import build_trusted_block, retrieve_trusted

    r = _seed()
    assert r.status_code == 201, r.text
    row = r.json()["trusted_query"]
    assert row["status"] == "proposed"
    assert row["proposed_by"] == "ana@example.com" and row["last_executed_at"]
    assert r.json()["verification"]["passed"] is True
    # A proposal is not authoritative: nothing reaches the prompt yet.
    assert retrieve_trusted(QUESTION, CONN) == []

    # The SECOND recorded act: approval. This is what makes it prompt-authoritative.
    t = client.post(f"/learning/trusted/{row['id']}/transition",
                    json={"action": "approve", "actor": "lead@example.com"})
    assert t.status_code == 200, t.text
    approved = t.json()["trusted_query"]
    assert approved["status"] == "approved" and approved["version"] == 1
    assert approved["verified_by"] == "lead@example.com" and approved["verified_at"]

    matches = retrieve_trusted(QUESTION, CONN)
    assert [m.id for m, _ in matches] == [row["id"]]
    assert GOOD_SQL in build_trusted_block(matches)

    # The lifecycle left an audit trail under the categorized kind.
    from aughor.kernel.ledger import Ledger
    events = Ledger.default().events(kind="trusted_query.governance", limit=50)
    actions = {e["payload"]["action"] for e in events
               if e.get("payload", {}).get("trusted_query") == row["id"]}
    assert {"create", "approve"} <= actions


def test_failing_seed_is_a_draft_and_never_in_the_block(tq_store, demo_conn):
    from aughor.semantic.trusted_queries import retrieve_trusted

    r = _seed(sql="DELETE FROM sales", question="purge all sales rows now")
    assert r.status_code == 201
    row = r.json()["trusted_query"]
    assert row["status"] == "draft" and row["proposed_by"] == ""
    assert r.json()["verification"]["blockers"]
    assert retrieve_trusted("purge all sales rows now", CONN) == []

    # …and it cannot be argued into the prompt: propose re-verifies and refuses.
    t = client.post(f"/learning/trusted/{row['id']}/transition",
                    json={"action": "propose", "actor": "ana@example.com"})
    assert t.status_code == 409
    assert t.json()["detail"]["verification"]["passed"] is False
    # A draft cannot be approved directly either (never verified clean).
    t2 = client.post(f"/learning/trusted/{row['id']}/transition",
                     json={"action": "approve", "actor": "ana@example.com"})
    assert t2.status_code == 400


def test_edit_resets_approval(tq_store, demo_conn):
    row = _seed().json()["trusted_query"]
    client.post(f"/learning/trusted/{row['id']}/transition",
                json={"action": "approve", "actor": "lead@example.com"})

    e = client.put(f"/learning/trusted/{row['id']}",
                   json={"sql": "SELECT region, COUNT(*) AS orders FROM sales "
                                "GROUP BY region",
                         "actor": "ana@example.com"})
    assert e.status_code == 200, e.text
    edited = e.json()["trusted_query"]
    # An approval covers the content it approved, nothing later.
    assert edited["status"] == "proposed"
    assert edited["verified_by"] == "" and edited["verified_at"] == ""
    # Re-approval bumps the version again.
    t = client.post(f"/learning/trusted/{row['id']}/transition",
                    json={"action": "approve", "actor": "lead@example.com"})
    assert t.json()["trusted_query"]["version"] == 2


def test_identical_reseed_of_approved_row_is_a_noop(tq_store, demo_conn):
    row = _seed().json()["trusted_query"]
    client.post(f"/learning/trusted/{row['id']}/transition",
                json={"action": "approve", "actor": "lead@example.com"})
    again = _seed()
    assert again.status_code == 201 and again.json()["unchanged"] is True
    assert again.json()["trusted_query"]["status"] == "approved"


def test_unknown_connection_is_404_and_blank_actor_400(tq_store, demo_conn):
    r = client.post("/learning/trusted", json={
        "connection_id": "no-such", "question": "q here", "sql": "SELECT 1",
        "actor": "ana@example.com"})
    assert r.status_code == 404
    r2 = _seed(actor="   ")
    assert r2.status_code == 400


def test_delete_is_audited_and_404s_when_gone(tq_store, demo_conn):
    row = _seed().json()["trusted_query"]
    d = client.delete(f"/learning/trusted/{row['id']}", params={"actor": "ana"})
    assert d.status_code == 200 and d.json() == {"deleted": row["id"]}
    assert client.delete(f"/learning/trusted/{row['id']}").status_code == 404

    from aughor.kernel.ledger import Ledger
    events = Ledger.default().events(kind="trusted_query.governance", limit=50)
    assert any(e.get("payload", {}).get("action") == "delete"
               and e["payload"].get("trusted_query") == row["id"] for e in events)


def test_inspection_endpoint_lists_every_status(tq_store, demo_conn):
    _seed(sql="DELETE FROM sales", question="purge everything")   # draft
    _seed()                                                        # proposed
    listing = client.get("/learning/trusted", params={"connection_id": CONN}).json()
    statuses = {q["status"] for q in listing["queries"]}
    assert statuses == {"draft", "proposed"}


# ── the governance feed knows the new kind (a mapping alone renders nothing) ─────────


def test_trusted_governance_kind_is_categorized_and_sunk():
    from aughor.govern.audit_categories import _SINKS, category_for

    assert category_for("trusted_query.governance") == "governance_change"
    # `feed` walks _SINKS, not KIND_CATEGORY — assert the other mandatory half by
    # driving it: an emitted event comes back out of the feed.
    from aughor.govern.audit_categories import feed
    from aughor.kernel.ledger import Ledger
    Ledger.default().emit("trusted_query.governance", {
        "trusted_query": "tq_feedcheck", "action": "approve", "actor": "t",
        "from": "proposed", "to": "approved", "version": 1, "at": "2026-09-05T00:00:00"})
    got = [e for e in feed(category="governance_change", limit=200)
           if e.kind == "trusted_query.governance"
           and (e.detail or {}).get("trusted_query") == "tq_feedcheck"]
    assert got and "approve" in got[0].summary
    assert len(_SINKS) == len({id(fn) for _, fn in _SINKS})  # no duplicated sink rows
