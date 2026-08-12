"""SE-0 — the /query/run contract for the Query workbench.

Four claims, each with the failure it guards against:

  1. The LEGACY response shape is unchanged (plus the additive ``caveats`` key):
     every cell a string, NULL spelled "NULL". Agent prompts and receipts are
     built from this shape — a silent drift here shifts them all.
  2. ``format:"typed"`` distinguishes a real SQL NULL from the string 'NULL',
     carries JSON-native values, per-column types, and an honest ``truncated``
     flag (the LIMIT n+1 probe).
  3. The typed side channel can never out-run the security post-pass: budget
     slices and PII redaction mirror into it, and any mirroring surprise
     disarms the capture (fail closed — typed degrades to legacy, never to an
     unredacted leak).
  4. The audit ``source`` label is an allow-list: a client-chosen dunder label
     would match the internal-query bypass and skip PII + audit entirely (the
     original __querybuilder__ bug).
"""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.db import registry

client = TestClient(app)

_LEGACY_KEYS = {"columns", "rows", "row_count", "duration_ms", "sql", "cached",
                "error", "receipt_id", "caveats"}


@pytest.fixture()
def typed_conn(tmp_path):
    db = tmp_path / "se0.duckdb"
    c = duckdb.connect(str(db))
    c.execute("""
        CREATE TABLE t AS SELECT * FROM (VALUES
            (1, 'alpha', DATE '2020-01-02', NULL),
            (2, 'NULL',  DATE '2020-01-03', 'x'),
            (3, NULL,    NULL,              'y'),
            (4, 'delta', DATE '2020-01-05', 'z')
        ) AS v(id, name, d, note)
    """)
    c.close()
    cid = registry.add_connection("se0-typed", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)


def _run(cid: str, sql: str, **extra) -> dict:
    r = client.post("/query/run", json={"conn_id": cid, "sql": sql, **extra})
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. legacy invariant ─────────────────────────────────────────────────────────

def test_legacy_shape_unchanged_and_stringified(typed_conn):
    body = _run(typed_conn, "SELECT id, name FROM t ORDER BY id")
    assert set(body.keys()) == _LEGACY_KEYS, "legacy adds ONLY the caveats key"
    assert body["error"] is None
    assert all(isinstance(v, str) for row in body["rows"] for v in row), \
        "legacy rows stay all-string — agent prompts depend on this"
    # the real NULL and the string 'NULL' are indistinguishable — the legacy flaw
    # the typed format exists to fix, pinned here as the compatibility contract
    assert body["rows"][2][1] == "NULL" and body["rows"][1][1] == "NULL"
    assert body["caveats"] == []


def test_blocked_query_keeps_shape(typed_conn):
    body = _run(typed_conn, "DELETE FROM t")
    assert "[BLOCKED]" in body["error"]
    assert set(body.keys()) == _LEGACY_KEYS


# ── 2. typed contract ───────────────────────────────────────────────────────────

def test_typed_distinguishes_null_from_the_string_null(typed_conn):
    body = _run(typed_conn, "SELECT name FROM t ORDER BY id", format="typed")
    assert body["format"] == "typed"
    assert body["rows"][0][0] == "alpha"
    assert body["rows"][1][0] == "NULL", "the STRING 'NULL' survives as a string"
    assert body["rows"][2][0] is None, "a real SQL NULL is a real JSON null"


def test_typed_values_and_column_types(typed_conn):
    body = _run(typed_conn, "SELECT id, name, d FROM t ORDER BY id", format="typed")
    assert body["rows"][0][0] == 1, "numerics are JSON numbers, not strings"
    assert body["rows"][0][2] == "2020-01-02", "dates are ISO strings"
    types = {c["name"]: c["type"] for c in body["columns_typed"]}
    assert types["id"] in ("INTEGER", "BIGINT")
    assert types["name"] == "VARCHAR"
    assert types["d"] == "DATE"


def test_typed_truncation_probe(typed_conn):
    over = _run(typed_conn, "SELECT id FROM t ORDER BY id", format="typed", limit=2)
    assert over["truncated"] is True and len(over["rows"]) == 2
    assert over["row_count"] == 2, "the n+1 probe row never leaves the server"
    exact = _run(typed_conn, "SELECT id FROM t ORDER BY id", format="typed", limit=4)
    assert exact["truncated"] is False and len(exact["rows"]) == 4
    under = _run(typed_conn, "SELECT id FROM t ORDER BY id", format="typed", limit=50)
    assert under["truncated"] is False and len(under["rows"]) == 4


def test_typed_rejects_bulk(typed_conn):
    r = client.post("/query/run", json={
        "conn_id": typed_conn, "sql": "SELECT 1", "format": "typed", "use_bulk": True})
    assert r.status_code == 400


def test_typed_error_degrades_to_legacy_shape(typed_conn):
    body = _run(typed_conn, "SELECT nope FROM t", format="typed")
    assert body["error"] is not None
    assert body["format"] == "legacy", "no typed payload on error — say so"
    assert "columns_typed" not in body


# ── 3. the security post-pass owns the side channel ─────────────────────────────

def test_pii_redaction_mirrors_into_typed_rows(typed_conn, tmp_path):
    db = tmp_path / "pii.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE p AS SELECT 'a@example.com' AS email, 7 AS n")
    c.close()
    cid = registry.add_connection("se0-pii", "duckdb", str(db))
    try:
        body = _run(cid, "SELECT email, n FROM p", format="typed")
        assert body["format"] == "typed"
        assert body["rows"][0][0] == "[REDACTED]", \
            "a typed cell must carry the SAME redaction as the legacy cell"
        assert body["rows"][0][1] == 7
    finally:
        registry.delete_connection(cid)


def test_budget_slice_mirrors_into_typed_rows(typed_conn, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("aughor.security.sandbox.get_budget",
                        lambda cid: SimpleNamespace(max_rows=2))
    body = _run(typed_conn, "SELECT id FROM t ORDER BY id", format="typed")
    assert len(body["rows"]) <= 2, "the budget cap binds the typed rows too"


def test_security_post_reconstruction_keeps_caveats():
    """The budget slice rebuilds the QueryResult — the rebuild must not drop the
    guard caveats SE-0 now forwards to the caller."""
    from aughor.control_plane.contracts.execution import QueryResult
    from aughor.db.connection import security_post

    res = QueryResult(hypothesis_id="query_builder", sql="SELECT 1",
                      columns=["a"], rows=[[str(i)] for i in range(2000)],
                      row_count=2000, caveats=["fan-out: magnitude inflated"])
    out = security_post("no-such-conn", "query_builder", "SELECT 1", res, 1.0)
    assert out.caveats == ["fan-out: magnitude inflated"]
    assert len(out.rows) <= 2000


def test_typed_mirror_disarms_on_shape_mismatch():
    """Fail closed: a positional mirror that cannot line up must kill the capture,
    never guess."""
    from aughor.db import connection as dbc

    token = dbc._TYPED_SINK.set({})
    try:
        dbc._offer_typed_rows([[1, "a@example.com"]], truncated=False, types=["INT", "VARCHAR"])
        sink = dbc._TYPED_SINK.get()
        assert sink["armed"]
        dbc._typed_mirror_redaction([["1", "x"]], [["1", "x"], ["2", "y"]])  # row-count mismatch
        assert not sink["armed"]
    finally:
        dbc._TYPED_SINK.reset(token)


def test_execute_typed_refuses_internal_labels(typed_conn, tmp_path):
    """Internal labels skip the PII/audit post-pass — a typed capture there would
    be an unredacted side channel, so the wrapper never arms it."""
    from aughor.db.connection import open_connection_for
    db = open_connection_for(typed_conn)
    try:
        result, payload = db.execute_typed("__internal__", "SELECT id FROM t")
        assert payload is None
        result2, payload2 = db.execute_typed("query_workbench", "SELECT id FROM t")
        assert payload2 is not None and payload2["armed"]
    finally:
        db.close()


# ── 4. source label + audit + dialect ───────────────────────────────────────────

def test_source_label_is_an_allowlist(typed_conn):
    r = client.post("/query/run", json={
        "conn_id": typed_conn, "sql": "SELECT 1", "source": "__evil__"})
    assert r.status_code == 422, "free-text labels could match the internal-query bypass"


def test_source_label_reaches_the_audit_log(typed_conn):
    _run(typed_conn, "SELECT id FROM t", source="query_workbench")
    r = client.get("/security/audit",
                   params={"label": "query_workbench", "connection_id": typed_conn})
    records = r.json()["records"]
    assert records, "the workbench run is filterable by its label"
    assert all(rec["hypothesis_id"] == "query_workbench" for rec in records)


def test_connections_list_carries_dialect(typed_conn):
    rows = client.get("/connections").json()
    mine = next(c for c in rows if c["id"] == typed_conn)
    assert mine["dialect"] == "duckdb"
    assert mine["writes_native_sql"] is False


def test_query_run_policy_is_analysis_run():
    from aughor.rbac.permissions import Permission
    from aughor.rbac.policy import POLICY
    assert POLICY[("POST", "/query/run")] is Permission.ANALYSIS_RUN
    assert POLICY[("POST", "/query/validate")] is Permission.ANALYSIS_RUN
