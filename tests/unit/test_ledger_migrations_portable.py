"""The ledger's migrations must run on BOTH backends — not just the one CI happens to use.

Migration 10 shipped with a back-fill written in `json_extract` / `json_valid`, which are
SQLite built-ins with no Postgres counterpart. `AUGHOR_DB_URL` moves this store onto shared
Postgres, and that is what the deployment runs, so on the database that matters the
statement raised, `run_migrations` re-raised, and — because migrations run inside
`Ledger.__init__` — the store could not be CONSTRUCTED. Every path that needs a ledger was
a boot failure, not a missing column.

Why it survived a green suite: the hermetic tests build a fresh **SQLite** file, where the
migration is correct, and every Postgres test in this repo is gated on a live server that
**CI does not run**. The dialect the deployment uses is exercised only on a developer's
machine. So the guard here is two-layered on purpose:

* `test_no_migration_uses_a_sqlite_only_json_function` needs no server and therefore runs
  in CI. It watches the SQL the migrations actually issue.
* the Postgres tests are the receipt — they prove the thing end to end where a server
  exists, and skip cleanly where one does not.

The equivalence test is the one that would have caught this class outright: one migration
must give one answer, whichever backend it lands on.
"""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

from aughor.db import backend as B
from aughor.kernel.ledger import _MIGRATIONS, _SCHEMA, Ledger, _add_session_event_attribution

PG_URL = os.environ.get("AUGHOR_PG_TEST_URL", "postgres://postgres:aughor@localhost:5544/aughor")


def _pg_available() -> bool:
    try:
        import psycopg2
        psycopg2.connect(PG_URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


needs_pg = pytest.mark.skipif(not _pg_available(), reason="no live Postgres to prove against")

#: SQLite JSON built-ins with no usable Postgres counterpart through the transpiler.
#: `json_valid` has no equivalent at all; `json_extract` renders as JSON_EXTRACT_PATH, which
#: takes a `json` argument and so cannot read the TEXT column this store keeps payloads in.
#: Extend this when another family bites — the point is that a migration body is SQL that
#: has to survive translation, and "it passed on SQLite" says nothing about that.
SQLITE_ONLY_JSON = (
    "json_valid", "json_extract", "json_each", "json_tree", "json_type",
    "json_array_length", "json_group_array", "json_group_object", "json_quote",
)

# The row shapes the back-fill has to agree about. Kept as one table so the SQLite and
# Postgres runs are provably fed the same input rather than two hand-written twins.
SEED = [
    ("llm_call", json.dumps({"role": "coder", "fallback": True})),
    ("llm_call", json.dumps({"role": "fast", "fallback": False})),
    ("llm_call", json.dumps({"role": "narrator", "fallback": "yes"})),
    ("llm_call", json.dumps({"role": "narrator", "fallback": "no"})),
    ("llm_call", json.dumps({"role": "judge", "fallback": "maybe"})),   # unknown, not False
    ("llm_call", json.dumps({"role": "judge", "fallback": 1})),
    ("llm_call", json.dumps({"role": "judge", "fallback": {"why": "?"}})),
    ("llm_call", json.dumps({"role": 7})),                              # TEXT affinity
    ("llm_call", json.dumps({"role": 1.5})),
    ("llm_call", json.dumps({"role": True})),
    ("llm_call", json.dumps({"role": {"a": 1}})),
    ("llm_call", json.dumps({"role": None})),
    ("tool_call", json.dumps({"tables": 3})),                           # no fact at all
    ("tool_call", "not json at all"),                                   # the json_valid case
    ("tool_call", json.dumps(["not", "an", "object"])),                 # valid JSON, not a doc
]

# Not invented: measured off the `json_extract` statement this back-fill replaced, so a
# store that runs the Python version ends up byte-for-byte where a SQLite store already is.
EXPECTED = [
    ("llm_call", "coder", 1),
    ("llm_call", "fast", 0),
    ("llm_call", "narrator", 1),
    ("llm_call", "narrator", 0),
    ("llm_call", "judge", None),
    ("llm_call", "judge", 1),
    ("llm_call", "judge", None),
    ("llm_call", "7", None),
    ("llm_call", "1.5", None),
    ("llm_call", "1", None),
    ("llm_call", '{"a":1}', None),
    ("llm_call", None, None),
    ("tool_call", None, None),
    ("tool_call", None, None),
    ("tool_call", None, None),
]


class _Recorder:
    """A connection that remembers the SQL put through it, and forwards the rest."""

    def __init__(self, conn):
        self._conn = conn
        self.sql: list[str] = []

    def execute(self, sql, params=()):
        self.sql.append(sql)
        return self._conn.execute(sql, params)

    def executemany(self, sql, seq_of_params):
        self.sql.append(sql)
        return self._conn.executemany(sql, seq_of_params)

    def executescript(self, script):
        self.sql.append(script)
        return self._conn.executescript(script)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _seed(conn) -> None:
    for kind, payload in SEED:
        conn.execute(
            "INSERT INTO session_events (at, trace_id, kind, payload) VALUES (?,?,?,?)",
            ("2026-01-01", "t", kind, payload))
    conn.execute("UPDATE session_events SET role = NULL, fallback = NULL")


def _read(conn) -> list:
    rows = conn.execute(
        "SELECT kind, role, fallback FROM session_events ORDER BY seq").fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


# ── the guard that runs without a server ──────────────────────────────────────────

def test_no_migration_uses_a_sqlite_only_json_function(tmp_path):
    """Watch the SQL the migrations issue, on the run where the back-fill has work to do.

    A migration over an empty table issues no DML at all, so the seeded second half is
    load-bearing: without rows, this guard would pass by looking at nothing."""
    conn = sqlite3.connect(tmp_path / "rec.db")
    conn.executescript(_SCHEMA)
    rec = _Recorder(conn)

    from aughor.db.migrations import run_migrations
    run_migrations(rec, _MIGRATIONS, store="test")
    _seed(conn)
    _add_session_event_attribution(rec)

    issued = "\n".join(rec.sql).lower()
    assert "update session_events set role" in issued, \
        "the back-fill issued no UPDATE — this guard is watching the wrong statements"
    offenders = [fn for fn in SQLITE_ONLY_JSON if f"{fn}(" in issued]
    assert not offenders, (
        f"migration SQL uses SQLite-only JSON built-ins {offenders}; this store also runs "
        f"on Postgres via AUGHOR_DB_URL, where they raise inside Ledger.__init__")


def test_the_backfill_answers_the_documented_truth_table(tmp_path):
    conn = sqlite3.connect(tmp_path / "sqlite.db")
    conn.executescript(_SCHEMA)
    from aughor.db.migrations import run_migrations
    run_migrations(conn, _MIGRATIONS, store="test")
    _seed(conn)

    _add_session_event_attribution(conn)

    assert _read(conn) == EXPECTED


def test_the_backfill_never_overwrites_a_value_already_set(tmp_path):
    """Re-running must be additive. `role` set by the write path outranks the payload."""
    conn = sqlite3.connect(tmp_path / "keep.db")
    conn.executescript(_SCHEMA)
    from aughor.db.migrations import run_migrations
    run_migrations(conn, _MIGRATIONS, store="test")
    conn.execute("INSERT INTO session_events (at, trace_id, kind, payload, role, fallback) "
                 "VALUES (?,?,?,?,?,?)",
                 ("2026-01-01", "t", "llm_call",
                  json.dumps({"role": "FROM_PAYLOAD", "fallback": True}), "explicit", 0))

    _add_session_event_attribution(conn)
    _add_session_event_attribution(conn)

    assert _read(conn) == [("llm_call", "explicit", 0)]


# ── the receipt, where a server exists ────────────────────────────────────────────

@needs_pg
def test_the_ledger_constructs_on_postgres_and_reaches_the_latest_version(tmp_path, monkeypatch):
    """The failure this file exists for was not a wrong value — it was no store at all."""
    monkeypatch.setenv(B.DB_URL_ENV, PG_URL)

    led = Ledger(tmp_path / "system.db")

    latest = max(m.version for m in _MIGRATIONS)
    assert led._conn.execute("PRAGMA user_version").fetchone()[0] == latest


@needs_pg
def test_the_backfill_gives_the_same_answer_on_both_backends(tmp_path, monkeypatch):
    """One migration, one answer. Same seed rows, two dialects, compared row for row."""
    lite = sqlite3.connect(tmp_path / "lite.db")
    lite.executescript(_SCHEMA)
    from aughor.db.migrations import run_migrations
    run_migrations(lite, _MIGRATIONS, store="test")
    _seed(lite)
    _add_session_event_attribution(lite)
    on_sqlite = _read(lite)

    monkeypatch.setenv(B.DB_URL_ENV, PG_URL)
    pg = Ledger(tmp_path / "pg.db")._conn
    _seed(pg)
    _add_session_event_attribution(pg)
    on_postgres = _read(pg)

    assert on_sqlite == EXPECTED
    assert on_postgres == on_sqlite


@needs_pg
def test_a_populated_postgres_store_stuck_at_v8_migrates_and_backfills(tmp_path, monkeypatch):
    """The production shape, rehearsed: rows already there, columns not, version behind.

    Every other test here starts from an empty schema, which is the one state the
    deployment is NOT in. A store that failed v10 sits at user_version=8 with a full
    `session_events` and none of the four columns — so the ALTERs, the indexes and the
    back-fill all run at once, over real rows, on the dialect that broke. Rehearsing a
    migration on a copy of the state it will actually meet is the whole lesson of the
    2026-08-14 corruption.
    """
    monkeypatch.setenv(B.DB_URL_ENV, PG_URL)
    conn = Ledger(tmp_path / "prod_shape.db")._conn

    # Wind it back to the state the failed migration left behind.
    for col in ("job_id", "charter_id", "role", "fallback"):
        conn.execute(f"ALTER TABLE session_events DROP COLUMN {col}")
    conn.execute("DROP INDEX IF EXISTS session_events_at")
    for kind, payload in SEED:
        conn.execute(
            "INSERT INTO session_events (at, trace_id, kind, payload) VALUES (?,?,?,?)",
            ("2026-01-01", "t", kind, payload))
    conn.execute("PRAGMA user_version = 8")
    conn.commit()

    reopened = Ledger(tmp_path / "prod_shape.db")

    assert reopened._conn.execute("PRAGMA user_version").fetchone()[0] == \
        max(m.version for m in _MIGRATIONS)
    assert _read(reopened._conn) == EXPECTED
