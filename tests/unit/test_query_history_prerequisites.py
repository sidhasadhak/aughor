"""Arc NV-5 — a feature's prerequisite on the engine is probed, said with its fix, and provisioned where the platform can.

The user, 2026-11-04, after `pg_stat_statements` had to be switched on by hand for the Lux receipt: *"make sure that
similar features … are enabled by default in our platform"*. Three verdicts are pinned — ready, not readable yet (with
the admin's step in the engine's words and whether the platform can take it), not applicable — on fakes for every
engine the readiness knows; the Postgres probe and the one DDL the platform writes are held to their guards (not
preloaded → refused in words; the organisation's setting off → 409 at the door); and the Test button carries the line.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from aughor.db.query_history import PREREQUISITES, QueryHistory, Readiness, check_query_history, unsupported


class _Result:
    def __init__(self, rows=(), error=""):
        self.rows, self.error = list(rows), error


class _Conn:
    def __init__(self, dialect, history=None, prerequisite=None):
        self.dialect = dialect
        self._history, self._prerequisite = history, prerequisite
    def query_history(self, *, hours=1, limit=1):
        return self._history
    def close(self):
        pass


# ── the three verdicts ────────────────────────────────────────────────────────────────────

def test_an_engine_that_keeps_none_is_not_a_gap():
    class Duck:
        dialect = "duckdb"
    r = check_query_history(Duck())
    assert not r.applies and not r.ok and r.fix == "" and r.sentence().startswith("Query history: duckdb keeps no query history")


def test_ready_says_what_is_on_record():
    from aughor.db.query_history import HistoryRow
    h = QueryHistory(engine="postgres", supported=True, source="public.pg_stat_statements",
                     rows=[HistoryRow(ended_at="t", sql="SELECT 1", calls=546)])
    r = check_query_history(_Conn("postgres", history=h))
    assert r.ok and r.source == "public.pg_stat_statements" and "546+ runs on record" in r.note
    assert r.sentence() == "Query history: ready — 546+ runs on record in public.pg_stat_statements"


def test_readable_but_empty_is_ready_and_says_so():
    h = QueryHistory(engine="clickhouse", supported=True, source="system.query_log", rows=[])
    r = check_query_history(_Conn("clickhouse", history=h))
    assert r.ok and "nothing on record yet" in r.note


def test_bigquerys_refusal_becomes_the_grant_in_words():
    h = QueryHistory(engine="bigquery", supported=True, source="`region-us`.INFORMATION_SCHEMA.JOBS_BY_USER",
                     error="403 Access Denied: … User does not have the required permissions ('bigquery.jobs.list' …)")
    r = check_query_history(_Conn("bigquery", history=h))
    assert not r.ok and not r.can_enable and r.note.startswith("the engine refused: 403 Access Denied")
    assert "bigquery.jobs.list" in r.fix and "client_email" in r.fix
    assert r.sentence().startswith("Query history: not readable yet: the engine refused") and "needs the connection's service account" in r.sentence()


@pytest.mark.parametrize("state,expect_note,can_enable", [
    ({"available": False, "preloaded": False, "created": False}, "not available on this server", False),
    ({"available": True, "preloaded": False, "created": False}, "not preloaded", False),
    ({"available": True, "preloaded": True, "created": False}, "preloaded and not yet created", True),
    ({"error": "permission denied for pg_available_extensions"}, "the prerequisite probe failed", False),
])
def test_postgres_without_the_extension_says_which_step_is_missing(state, expect_note, can_enable):
    conn = _Conn("postgres", history=unsupported("postgres", "this database has no pg_stat_statements"))
    conn.query_history_prerequisite = lambda: state
    r = check_query_history(conn)
    assert not r.ok and r.applies and expect_note in r.note and r.can_enable is can_enable
    assert r.fix == PREREQUISITES["postgres"]
    assert ("the platform can enable it" in r.sentence()) is can_enable


def test_a_probe_that_raises_is_a_verdict_not_a_crash():
    class Bad:
        dialect = "snowflake"
        def query_history(self, **kw):
            raise RuntimeError("socket closed")
    r = check_query_history(Bad())
    assert not r.ok and "the probe failed: socket closed" in r.note and r.fix == PREREQUISITES["snowflake"]


def test_every_engine_with_a_reader_has_its_prerequisite_in_words():
    assert set(PREREQUISITES) == {"postgres", "bigquery", "snowflake", "clickhouse", "databricks"}
    assert all(len(v) > 40 for v in PREREQUISITES.values())


# ── the Postgres probe and the one DDL the platform writes ───────────────────────────────

def _pg(monkeypatch, answers):
    from aughor.db import connection as C
    pg = C.PostgresConnection.__new__(C.PostgresConnection)
    seen = []
    def fake_bounded(label, sql, limit, *, sql_dialect=None, internal=False):
        seen.append((label, sql, sql_dialect, internal))
        for key, rows in answers.items():
            if key in sql:
                return _Result(rows=rows)
        return _Result(error=f"unexpected: {sql}")
    monkeypatch.setattr(pg, "execute_bounded", fake_bounded)
    return pg, seen


def test_the_probe_reads_three_facts_through_the_door(monkeypatch):
    pg, seen = _pg(monkeypatch, {"pg_available_extensions": [["1"]], "shared_preload_libraries": [["pg_stat_statements"]],
                                 "pg_extension": [["0"]]})
    assert pg.query_history_prerequisite() == {"available": True, "preloaded": True, "created": False}
    assert [s[0] for s in seen] == ["__prerequisite__"] * 3 and all(s[2] is None and s[3] for s in seen)
    # the read door admits SELECT alone: `SHOW shared_preload_libraries` was refused live (LuxExperience, 2026-11-04)
    assert all(s[1].lstrip().upper().startswith("SELECT") for s in seen)


def test_enable_refuses_in_words_when_the_server_setting_is_missing(monkeypatch):
    pg, _ = _pg(monkeypatch, {"pg_available_extensions": [["1"]], "shared_preload_libraries": [[""]], "pg_extension": [["0"]]})
    executed = []
    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql): executed.append(sql)
    pg._conn = type("Conn", (), {"cursor": lambda self: Cur()})()
    ok, msg = pg.enable_query_history()
    assert not ok and "shared_preload_libraries" in msg and "restart" in msg and executed == []   # nothing written


def test_enable_creates_the_extension_once_preloaded_and_is_idempotent(monkeypatch):
    pg, _ = _pg(monkeypatch, {"pg_available_extensions": [["1"]], "shared_preload_libraries": [["pg_stat_statements"]],
                              "pg_extension": [["0"]]})
    executed = []
    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql): executed.append(sql)
    pg._conn = type("Conn", (), {"cursor": lambda self: Cur()})()
    ok, msg = pg.enable_query_history()
    # one explicit READ WRITE transaction around the DDL: the session's read-only default (WP-1d) is never changed
    assert ok and executed == ["BEGIN", "SET TRANSACTION READ WRITE", "CREATE EXTENSION IF NOT EXISTS pg_stat_statements",
                               "COMMIT"] and "created" in msg
    pg2, _ = _pg(monkeypatch, {"pg_available_extensions": [["1"]], "shared_preload_libraries": [["pg_stat_statements"]],
                               "pg_extension": [["1"]]})
    ok2, msg2 = pg2.enable_query_history()
    assert ok2 and "already created" in msg2


# ── the doors ─────────────────────────────────────────────────────────────────────────────

def test_the_enable_door_is_gated_by_the_organisations_setting(monkeypatch):
    import asyncio
    from aughor.orgsettings import allows as A
    from aughor.routers import connections as R
    monkeypatch.setattr(A, "allows", lambda s: False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(R.enable_connection_prerequisite("c1"))
    assert exc.value.status_code == 409 and "nothing is provisioned" in exc.value.detail and A.WHERE in exc.value.detail


def test_the_enable_door_provisions_journals_and_reports_the_readiness_after(monkeypatch):
    import asyncio
    from aughor.orgsettings import allows as A
    from aughor.routers import connections as R
    monkeypatch.setattr(A, "allows", lambda s: s == "read_query_history")
    calls = {"enabled": 0}
    class PG:
        dialect = "postgres"
        def enable_query_history(self):
            calls["enabled"] += 1
            return True, "pg_stat_statements created; statements are kept from now on"
        def query_history(self, *, hours=1, limit=1):
            if calls["enabled"]:
                return QueryHistory(engine="postgres", supported=True, source="public.pg_stat_statements", rows=[])
            return unsupported("postgres", "no pg_stat_statements")
        def query_history_prerequisite(self):
            return {"available": True, "preloaded": True, "created": bool(calls["enabled"])}
        def close(self):
            pass
    monkeypatch.setattr(R, "open_connection_for", lambda cid: PG())
    emitted = []
    class L:
        def emit(self, kind, payload, **kw):
            emitted.append((kind, payload, kw))
    import aughor.kernel.ledger as LM
    monkeypatch.setattr(LM.Ledger, "default", staticmethod(lambda: L()))
    out = asyncio.run(R.enable_connection_prerequisite("c1"))
    assert out["ok"] and out["enabled"] and out["query_history"]["ok"] and calls["enabled"] == 1
    assert emitted and emitted[0][0] == "connection.prerequisite_enabled" and emitted[0][1]["prerequisite"] == "query_history"


def test_the_enable_door_on_an_engine_the_platform_cannot_provision_says_the_admins_step(monkeypatch):
    import asyncio
    from aughor.orgsettings import allows as A
    from aughor.routers import connections as R
    monkeypatch.setattr(A, "allows", lambda s: True)
    bq = _Conn("bigquery", history=QueryHistory(engine="bigquery", supported=True, source="x", error="403 Access Denied: jobs.list"))
    monkeypatch.setattr(R, "open_connection_for", lambda cid: bq)
    out = asyncio.run(R.enable_connection_prerequisite("c1"))
    assert not out["ok"] and not out["enabled"] and "bigquery.jobs.list" in out["message"]


def test_the_test_button_carries_the_readiness_only_while_the_organisation_reads_history(monkeypatch):
    import asyncio
    from aughor.orgsettings import allows as A
    from aughor.routers import connections as R
    class PG(_Conn):
        def test(self):
            return True, "PostgreSQL 16.14"
    pg = PG("postgres", history=QueryHistory(engine="postgres", supported=True, source="public.pg_stat_statements",
                                             rows=[__import__("aughor.db.query_history", fromlist=["HistoryRow"]).HistoryRow("t", "SELECT 1", calls=70)]))
    monkeypatch.setattr(R, "open_connection_for", lambda cid: pg)
    monkeypatch.setattr(A, "allows", lambda s: False)
    out = asyncio.run(R.test_connection("c1"))
    assert out == {"ok": True, "message": "PostgreSQL 16.14"}
    monkeypatch.setattr(A, "allows", lambda s: True)
    out = asyncio.run(R.test_connection("c1"))
    assert out["message"] == "PostgreSQL 16.14. Query history: ready — 70+ runs on record in public.pg_stat_statements"
    assert out["query_history"]["ok"]


def test_the_candidate_door_says_the_fix_when_the_history_is_not_readable(monkeypatch):
    from aughor.orgsettings import allows as A
    from aughor.routers import ontology as R
    from aughor.ontology.models import OntologyGraph
    monkeypatch.setattr(A, "allows", lambda s: True)
    monkeypatch.setattr(R, "_served_scope", lambda cid, s: "main")
    monkeypatch.setattr(R, "_get_ontology_graph",
                        lambda cid, s=None: OntologyGraph(connection_id="c1", schema_name="main", schema_fingerprint="fp"))
    bq = _Conn("bigquery", history=QueryHistory(engine="bigquery", supported=True, source="x",
                                                error="403 Access Denied: ('bigquery.jobs.list' permission(s) at the project level)"))
    import aughor.db.connection as C
    monkeypatch.setattr(C, "open_connection_for_with_schema", lambda cid, s=None: bq)
    out = R.mine_ontology_candidates(None, connection_id="c1")
    assert out["mined"] == 0 and out["readiness"]["fix"].startswith("the connection's service account granted `bigquery.jobs.list`")
    assert out["summary"].startswith("Query history: not readable yet")


def test_readiness_dict_carries_the_sentence():
    r = Readiness(engine="postgres", ok=False, note="n", fix="f", can_enable=True)
    d = r.as_dict()
    assert d["sentence"] == "Query history: not readable yet: n — the platform can enable it" and d["can_enable"]
