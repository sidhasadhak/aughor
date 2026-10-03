"""DE-5d (ROADMAP §3.51) — what a cut result asks for next: "count all rows" and "load more", through the
door, and the cut said for what it is.

Measured first, on this branch before the fix: `/query/run` with `limit` 1,000, 5,000 and 50,000 returned 500
rows each on DuckDB, `truncated`, because `execute_typed` ran the statement under the connector's per-call cap
whatever the limit asked for — the Run menu's presets above 500 were a promise the connector never kept. And
`COUNT(*)` over a person's statement, run under the person's label, passed `validated`, `safety-checked`,
`pii-checked` and `audited`: the door the run went through. These tests pin both, and the new routes.

Hermetic: a DuckDB file per test, registered through the registry the conftest redirects.
"""
from __future__ import annotations

from datetime import datetime

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.db import registry

client = TestClient(app)

ROWS = 12_000
ORDERED = "SELECT * FROM t ORDER BY id"
UNORDERED = "SELECT * FROM t WHERE id % 2 = 0"


@pytest.fixture()
def conn(tmp_path):
    db = tmp_path / "de5d.duckdb"
    c = duckdb.connect(str(db))
    c.execute(f"CREATE TABLE t AS SELECT i AS id, 'row-' || i AS s FROM range({ROWS}) r(i)")
    c.close()
    cid = registry.add_connection("de5d", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)


def _run(cid: str, sql: str, limit: int, **extra) -> dict:
    r = client.post("/query/run", json={"conn_id": cid, "sql": sql, "format": "typed", "limit": limit,
                                        "source": "query_workbench", **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _count(cid: str, sql: str, **extra) -> dict:
    r = client.post("/query/count", json={"conn_id": cid, "sql": sql, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _more(cid: str, sql: str, offset: int, limit: int, **extra) -> dict:
    r = client.post("/query/more", json={"conn_id": cid, "sql": sql, "offset": offset, "limit": limit, **extra})
    assert r.status_code == 200, r.text
    return r.json()


# ── 1 · the limit the person chose is honoured, and the cut says what cut it ─────────────────────

def test_the_run_honours_its_limit_up_to_the_row_budget_and_says_which_cut_it(conn):
    small = _run(conn, ORDERED, 100)
    assert (len(small["rows"]), small["truncated"], small["cut_by"]) == (100, True, "limit")
    # Before DE-5d these three all came back as 500 rows.
    thousand = _run(conn, ORDERED, 1000)
    assert (len(thousand["rows"]), thousand["row_count"], thousand["cut_by"]) == (1000, 1000, "limit")
    five = _run(conn, ORDERED, 5000)
    assert (len(five["rows"]), five["cut_by"]) == (5000, "limit")
    # The connection's row budget (10,000, `security/sandbox.py`) stays the ceiling — and the cut
    # is said as the budget's, with `truncated` true although the connector's cap was never reached.
    huge = _run(conn, ORDERED, 50_000)
    assert (len(huge["rows"]), huge["truncated"], huge["cut_by"]) == (10_000, True, "budget")
    whole = _run(conn, "SELECT * FROM t WHERE id < 10 ORDER BY id", 500)
    assert (len(whole["rows"]), whole["truncated"], whole["cut_by"]) == (10, False, None)


def test_a_parameterised_run_is_still_capped_by_the_connector_and_says_so(conn):
    # The bound path has no bounded read, so the connector's 500-row cap applies below the limit asked
    # for — and the response says `cap`, not `limit`: the person did not choose 500.
    body = _run(conn, "SELECT * FROM t WHERE id >= :lo ORDER BY id", 1000, params={"lo": 0})
    assert body["error"] is None, body["error"]
    assert (len(body["rows"]), body["truncated"], body["cut_by"]) == (500, True, "cap")


# ── 2 · count all rows: the total, its as-of, the door ────────────────────────────────────────────

def test_count_all_rows_answers_the_total_with_its_as_of(conn):
    body = _count(conn, ORDERED)
    assert body["total"] == ROWS and body["error"] is None and body["code"] is None
    assert body["sql"] == ORDERED, "the person's statement, not the COUNT wrapper"
    as_of = datetime.fromisoformat(body["as_of"])
    assert as_of.tzinfo is not None, "an aware UTC timestamp, the house as_of"
    assert body["duration_ms"] >= 0


def test_the_count_goes_through_the_run_door_and_is_audited(conn):
    from aughor.db.connection import open_connection_for
    from aughor.security.audit import AuditLogger
    from aughor.sql.paging import count_sql
    before = len(AuditLogger.recent(limit=500, connection_id=conn, label="query_workbench"))
    _count(conn, ORDERED)
    after = AuditLogger.recent(limit=500, connection_id=conn, label="query_workbench")
    assert len(after) == before + 1, "one audit row per count, under the run's label"
    # The same statement, run directly under the same label, shows the doors the route's count passed.
    db = open_connection_for(conn)
    try:
        res = db.execute("query_workbench", count_sql(ORDERED))
    finally:
        db.close()
    assert res.error is None
    assert {"validated:duckdb", "safety-checked", "pii-checked", "audited"} <= set(res.doors), res.doors
    assert "internal" not in res.doors


def test_a_count_with_bound_values_counts_the_same_statement(conn):
    body = _count(conn, "SELECT * FROM t WHERE id < :n", params={"n": 250})
    assert body["total"] == 250 and body["error"] is None


def test_count_refusals_are_typed_and_the_total_is_null_never_zero(conn):
    blocked = _count(conn, "DROP TABLE t")
    assert blocked["total"] is None and blocked["code"] == "BLOCKED" and blocked["error"]
    explain = _count(conn, "EXPLAIN SELECT 1")
    assert explain["total"] is None and explain["code"] == "NOT_WRAPPABLE"
    failed = _count(conn, "SELECT nope FROM t")
    assert failed["total"] is None and failed["code"] == "FAILED" and "nope" in failed["error"]
    assert client.post("/query/count", json={"conn_id": "no-such-connection", "sql": "SELECT 1"}).status_code == 404
    assert client.post("/query/count", json={"conn_id": conn, "sql": "   "}).status_code == 400


# ── 3 · load more: the next page, typed, through the door ─────────────────────────────────────────

def test_load_more_returns_the_next_page_typed_with_the_probe(conn):
    page = _more(conn, ORDERED, offset=ROWS - 200, limit=500)
    assert page["format"] == "typed" and page["error"] is None and page.get("code") is None
    assert len(page["rows"]) == 200 and page["truncated"] is False and page["cut_by"] is None
    assert page["rows"][0][0] == ROWS - 200 and page["rows"][-1][0] == ROWS - 1, "JSON-native cells, in order"
    assert page["offset"] == ROWS - 200 and page["ordered"] is True
    assert page["sql"] == ORDERED and page["receipt_id"] is None
    first = _more(conn, ORDERED, offset=0, limit=500)
    assert (len(first["rows"]), first["truncated"], first["cut_by"]) == (500, True, "limit")
    assert [c["name"] for c in first["columns_typed"]] == ["id", "s"]


def test_a_page_of_an_unordered_statement_says_pages_may_repeat_or_skip_rows(conn):
    page = _more(conn, UNORDERED, offset=500, limit=500)
    assert page["ordered"] is False
    assert any("no ORDER BY" in c and "repeat or skip rows" in c for c in page["caveats"]), page["caveats"]
    ordered = _more(conn, ORDERED, offset=500, limit=10)
    assert ordered["ordered"] is True and not any("ORDER BY" in c for c in ordered["caveats"])


def test_load_more_refusals_are_typed(conn):
    blocked = _more(conn, "DROP TABLE t", offset=0, limit=10)
    assert blocked["code"] == "BLOCKED" and blocked["rows"] == [] and blocked["error"]
    explain = _more(conn, "EXPLAIN SELECT 1", offset=0, limit=10)
    assert explain["code"] == "NOT_WRAPPABLE"
    failed = _more(conn, "SELECT nope FROM t", offset=0, limit=10)
    assert failed["code"] == "FAILED" and "nope" in failed["error"] and failed["rows"] == []


def test_paging_is_refused_where_each_page_is_billed_as_a_scan(conn, monkeypatch):
    # The study's falsifier, per engine: on an engine whose declaration says a re-run is billed as a scan
    # of the statement's tables, a page costs what the whole result cost, and the route says so.
    import aughor.db.metadata as M
    monkeypatch.setattr(M, "engine_type_of", lambda db: "bigquery")
    page = _more(conn, ORDERED, offset=500, limit=500)
    assert page["code"] == "PAGE_BILLED_AS_SCAN" and page["rows"] == []
    assert "BigQuery" in page["error"] and "higher limit" in page["error"]
    # …and the count is not refused there: one statement, billed once, is the cheaper way to the total.
    assert _count(conn, ORDERED)["total"] == ROWS


# ── 4 · the facts the routes stand on ─────────────────────────────────────────────────────────────

def test_every_engine_declares_what_a_rerun_costs():
    from typing import get_args

    from aughor.connectors import declarations as D
    allowed = set(get_args(D.RerunCost))
    for e in D.ENGINES:
        assert e.rerun_cost in allowed, e.type
    by_type = {e.type: e.rerun_cost for e in D.ENGINES}
    assert by_type["bigquery"] == "bytes_scanned" and by_type["s3"] == "bytes_scanned"
    assert by_type["duckdb"] == "local" and by_type["postgres"] == "compute"
    assert {t for t, c in by_type.items() if c == "unknown"} == {"confluence", "notion"}, "only the non-SQL sources"


@pytest.mark.parametrize("sql,expected", [
    (ORDERED, True),
    (UNORDERED, False),
    ("WITH a AS (SELECT * FROM t) SELECT * FROM a ORDER BY id", True),
    ("SELECT * FROM (SELECT * FROM t ORDER BY id) sub", False),          # the inner ORDER BY orders nothing outside
    ("(SELECT id FROM t ORDER BY id)", True),
    ("SELECT id FROM t UNION ALL SELECT id FROM t ORDER BY 1", True),
    ("SELECT id FROM t UNION ALL SELECT id FROM t", False),
    ("SELECT FROM WHERE", None),
    ("", None),
])
def test_has_top_level_order_reads_the_outermost_query(sql, expected):
    from aughor.sql.paging import has_top_level_order
    assert has_top_level_order(sql, "duckdb") is expected


def test_the_wrappers_are_the_two_statements_and_nothing_else():
    from aughor.sql.paging import count_sql, page_sql
    assert count_sql("SELECT 1;") == "SELECT COUNT(*) AS n FROM (SELECT 1) __q"
    assert page_sql(" SELECT 1 ; ", 501, 1000) == "SELECT * FROM (SELECT 1) __q LIMIT 501 OFFSET 1000"
    assert page_sql("SELECT 1", 0, -5) == "SELECT * FROM (SELECT 1) __q LIMIT 1 OFFSET 0"


def test_the_bigquery_job_says_what_it_cost_as_door_words():
    from aughor.connectors.warehouse.bigquery import _say_what_it_cost
    from aughor.db import doors as D

    class _Job:
        total_bytes_processed = 123_456
        total_bytes_billed = 10_485_760
        cache_hit = False

    class _Cached:
        total_bytes_processed = 0
        total_bytes_billed = 0
        cache_hit = True

    class _Bare:
        pass

    for job, words in ((_Job(), ["bytes-processed:123456", "bytes-billed:10485760"]),
                       (_Cached(), ["bytes-processed:0", "bytes-billed:0", "cache-hit"]),
                       (_Bare(), [])):
        token = D._TRAIL.set([])
        try:
            _say_what_it_cost(job)
            assert D._TRAIL.get() == words
        finally:
            D._TRAIL.reset(token)
    # Every word has its plain sentence (GM-3 holds the trail to the vocabulary).
    for w in ("bytes-processed", "bytes-billed", "cache-hit"):
        assert w in D.WORDS


def test_the_distinct_route_refuses_in_the_engines_words(conn):
    r = client.get(f"/connections/{conn}/distinct", params={"table": "no_such_table", "column": "x"})
    assert r.status_code == 200
    body = r.json()
    assert body["values"] == [] and body["truncated"] is False
    assert body["code"] == "DISTINCT_FAILED" and "no_such_table" in body["error"]
    ok = client.get(f"/connections/{conn}/distinct", params={"table": "t", "column": "s", "limit": 5}).json()
    assert len(ok["values"]) == 5 and ok["truncated"] is True and "code" not in ok


def test_the_rbac_table_knows_the_two_routes():
    from aughor.rbac.policy import POLICY
    assert POLICY[("POST", "/query/count")] == POLICY[("POST", "/query/run")]
    assert POLICY[("POST", "/query/more")] == POLICY[("POST", "/query/run")]
