"""GM-3 — the path is a receipt (ROADMAP §3.49; `docs/GATE_MAP_STUDY_2026-09-26.md` §4 finding 6).

An answer carried its guard receipts — what FIRED — and never which doors its statement went through. Every
statement now carries ``QueryResult.doors``: the words each door said as the statement passed it
(`aughor.db.doors`), stamped at the connection's entry. The answer envelope keeps them per statement, a tool-loop
step records them, and Spotlight's `explain` says them in plain words.

What these pin: the path is the one the statement took (in order, refusals included); a step taken outside a
statement — a translation made to store one, a probe the guard battery runs while judging another — is never
credited to the wrong statement; and each reader gets the words, or is told they were not recorded.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from aughor.control_plane.contracts.execution import QueryResult
from aughor.db import doors as D
from aughor.db.connection import DuckDBConnection


@pytest.fixture
def shop(tmp_path: Path):
    path = tmp_path / "shop.duckdb"
    raw = duckdb.connect(str(path))
    raw.execute("CREATE TABLE orders (order_id INTEGER, email VARCHAR, status VARCHAR)")
    raw.execute("INSERT INTO orders VALUES (1, 'ana@example.com', 'Complete'), (2, 'bo@example.com', 'Shipped')")
    raw.execute("CREATE TABLE items (order_id INTEGER, price DOUBLE)")
    raw.execute("INSERT INTO items VALUES (1, 10.0), (1, 5.0), (2, 7.5)")
    raw.close()
    conn = DuckDBConnection(path, connection_id="gm3")
    yield conn
    conn.close()


def test_an_answer_carries_the_doors_it_passed_in_order(shop):
    r = shop.execute("answer", 'SELECT "order_id", email FROM orders ORDER BY 1', sql_dialect="duckdb")
    assert not r.error
    assert r.doors == ["validated:duckdb", "safety-checked", "pii-redacted:2", "audited"]


def test_plumbing_says_it_is_plumbing(shop):
    """A statement declared the platform's own skips safety, audit and redaction; its path says so instead of saying
    nothing. (A label decided it before GM-5; the declaration does now.)"""
    assert shop.execute("__probe__", "SELECT COUNT(*) FROM orders", internal=True).doors == ["validated:duckdb", "internal"]


def test_a_refusal_is_the_last_door(shop):
    r = shop.execute("answer", "DELETE FROM orders")
    assert r.error and r.doors == ["blocked:validation"]


def test_a_native_engine_says_it_translated(monkeypatch):
    from aughor.connectors.warehouse.bigquery import BigQueryConnection

    conn = object.__new__(BigQueryConnection)
    conn._connection_id = "gm3-bq"
    monkeypatch.setattr(conn, "_run_job", lambda hid, sql, max_rows=None: QueryResult(
        hypothesis_id=hid, sql=sql, columns=["n"], rows=[["3"]], row_count=1))
    r = conn.execute("answer", 'SELECT COUNT(*) AS "n" FROM "orders"', sql_dialect="duckdb")
    assert r.doors == ["translated:duckdb→bigquery", "safety-checked", "pii-checked", "audited"]
    assert conn.execute("answer", "SELECT 1 AS n").doors[0] == "safety-checked", "an undeclared statement was not translated"


def test_a_step_outside_a_statement_is_credited_to_no_statement(shop):
    """A translation made to STORE a statement, outside any door, must not surface on the next statement's path."""
    from aughor.db.dialects import sql_for_engine

    class _BigQuery:
        dialect, writes_native_sql = "bigquery", True
    sql_for_engine(_BigQuery(), 'SELECT "x" FROM "t"', "duckdb")
    D.passed("translated:duckdb→bigquery")            # a stray step, with no statement open
    assert "translated:duckdb→bigquery" not in shop.execute("answer", "SELECT 1 AS one").doors


def test_the_guard_battery_adds_its_guards_and_its_probes_stay_their_own(shop):
    """The join guard judges the answer by running probes of its own; those are separate statements with separate
    trails, so the answer's path lists the guard and never the probes' `internal`."""
    from aughor.sql.executor import execute_guarded

    r = execute_guarded(shop, "SELECT o.status, SUM(i.price) AS total FROM orders o JOIN items i "
                              "ON o.order_id = i.order_id GROUP BY 1", query_id="answer")
    assert not r.error
    assert r.doors[:3] == ["validated:duckdb", "safety-checked", "pii-checked"]
    assert {"audited", "guarded:trust-gate", "guarded:join-domain", "guarded:filter-domain",
            "guarded:id-arithmetic", "guarded:e1"} <= set(r.doors)
    assert "internal" not in r.doors, "a guard probe's path was written onto the answer's"


def test_the_envelope_keeps_each_statements_doors_keyed_to_the_statement_that_ran():
    from aughor.answer.envelope import fold_frames

    env = fold_frames([
        {"type": "sql", "sql": "SELECT a FROM t"},
        {"type": "columns", "columns": ["a"], "doors": ["validated:duckdb", "safety-checked", "audited"]},
        {"type": "sql", "sql": "SELECT a FROM t2"},           # a repair ran: the path belongs to IT
        {"type": "columns", "columns": ["a"], "doors": ["validated:duckdb", "safety-checked", "audited",
                                                        "repaired:model"]},
        {"type": "headline", "headline": "A is 3."},
    ])
    assert [e["sql"] for e in env.provenance.doors] == ["SELECT a FROM t", "SELECT a FROM t2"]
    assert env.provenance.doors[-1]["doors"][-1] == "repaired:model"


def test_spotlight_says_the_doors_or_says_they_were_not_recorded(monkeypatch):
    from aughor.agent import spotlight_explain as SE

    envelope = {"provenance": {"doors": [{"sql": "SELECT 1", "doors": [
        "translated:duckdb→bigquery", "safety-checked", "audited", "guarded:join-domain"]}]}}
    rows = {"a1": {"id": "a1", "kind": "chat", "status": "complete", "question": "q",
                   "report": {"envelope": envelope}},
            "a0": {"id": "a0", "kind": "chat", "status": "complete", "question": "q",
                   "report": {"envelope": {"provenance": {}}}}}
    monkeypatch.setattr("aughor.db.history.get_investigation", lambda i: rows.get(i))
    monkeypatch.setattr("aughor.govern.departure_store.list_departures", lambda limit=500: [])
    monkeypatch.setattr(SE, "_latest_verdict", lambda inv_id: None)

    said = SE.explain_object("c", {"kind": "analysis", "id": "a1"})
    assert [d["said"] for d in said["doors"]] == [["translated from duckdb to bigquery",
                                                   "safety-checked for writes, injection and exfiltration",
                                                   "written to the audit log",
                                                   "checked by the join value-domain guard"]]
    assert "passed 4 doors" in said["summary"]
    assert "were not recorded" in SE.explain_object("c", {"kind": "analysis", "id": "a0"})["summary"]


def test_a_step_record_and_the_trajectory_carry_the_doors():
    from aughor.obs.trajectory import _step

    step = _step({"seq": 1, "payload": {"tool": "run_sql", "doors": ["safety-checked", "audited"]}}, gated=False)
    assert step["doors"] == ["safety-checked", "audited"]


def test_every_word_a_door_says_has_plain_words():
    """An unknown word is kept as written, never dropped — but no word the platform itself says may be unknown."""
    import re

    root = Path(D.__file__).resolve().parents[1]
    said = set()
    for path in root.rglob("*.py"):
        said |= set(re.findall(r'(?:_passed|passed)\(f?"([a-z-]+)', path.read_text(encoding="utf-8")))
    assert said, "no door words found — the walk no longer reads the recorders"
    assert said <= set(D.WORDS), f"door words with no plain words: {sorted(said - set(D.WORDS))}"
    assert D.describe(["guarded:e1", "mystery:x"]) == ["checked by the function-semantics guard", "mystery:x"]
