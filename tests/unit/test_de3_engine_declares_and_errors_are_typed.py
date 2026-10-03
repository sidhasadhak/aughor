"""DE-3a and DE-3d — an engine is one declaration, parts a and d (ROADMAP §3.51; `docs/DBX_STUDY_2026-10-01.md`
findings 5 and 7).

DE-3a: Exasol declared `postgres` — "the closest transpile fit" while sqlglot had no Exasol dialect — so the writer
rules told the model Postgres's syntax and to AVOID QUALIFY, which Exasol supports, and the parse step read Exasol
SQL as Postgres. sqlglot 30 ships `exasol`; Exasol declares it.

DE-3d: every connector caught its driver's exception as `error=str(e)`, so a dropped socket, a statement timeout,
the person's Cancel and a typo read the same; the pool counted a connection with no `is_healthy` as healthy, and
only Postgres and SQLite had one. Errors are typed now, a lost connection is never handed out again, only a
platform statement is run once more on it, and every connector answers.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

import aughor.connectors
from aughor.control_plane.contracts.execution import QueryResult
from aughor.db import doors as D
from aughor.db.connection import DatabaseConnection, DuckDBConnection
from aughor.db.errors import classify_error


def _all_connection_classes() -> list[type]:
    for mod in pkgutil.walk_packages(aughor.connectors.__path__, "aughor.connectors."):
        importlib.import_module(mod.name)

    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from walk(sub)
    return sorted({c for c in walk(DatabaseConnection) if c.__module__.startswith("aughor.")
                   and not inspect.isabstract(c)}, key=lambda c: c.__qualname__)


CLASSES = _all_connection_classes()


# ── DE-3a ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_exasol_declares_itself_and_is_read_as_itself():
    from aughor.connectors.warehouse.exasol import ExasolConnection
    from aughor.db.capabilities import avoid_line, for_dialect
    from aughor.db.connection import _validate
    from aughor.db.dialects import known_dialect, native_sql, writer_rules
    from aughor.sql.capability_check import capability_diagnostics

    assert ExasolConnection.dialect == "exasol" and known_dialect("exasol") == "exasol"
    conn = object.__new__(ExasolConnection)

    rules = writer_rules(conn)
    assert rules.startswith("EXASOL DIALECT RULES") and "QUALIFY is supported" in rules, rules[:120]
    assert "AVOID on postgres" not in rules and "POSTGRESQL" not in rules
    assert "QUALIFY" not in avoid_line("exasol") and "DATEDIFF" in avoid_line("exasol")
    assert not for_dialect("exasol").unsupported_features

    qualify = "SELECT * FROM t QUALIFY ROW_NUMBER() OVER (ORDER BY x) = 1"
    assert capability_diagnostics(qualify, "exasol") == []            # Exasol's own: allowed
    assert capability_diagnostics(qualify, "postgres")                # still refused where it errors
    assert _validate(qualify, "exasol")[0]

    translated = native_sql(conn, 'SELECT "a"::DOUBLE AS p, string_agg("n", \',\') AS names FROM "t"')
    assert "LISTAGG" in translated and "::" not in translated, translated


# ── DE-3d: the kind of an error ──────────────────────────────────────────────────────────────────────────────────────

def _exc(name: str, msg: str = "", *, module: str | None = None, args: tuple | None = None) -> BaseException:
    """An exception with a driver's class name, without the driver installed."""
    cls = type(name, (Exception,), {})
    if module:
        cls.__module__ = module
    return cls(*(args if args is not None else (msg,)))


@pytest.mark.parametrize("exc,kind", [
    (_exc("OperationalError", args=(2006, "MySQL server has gone away")), "connection"),
    (_exc("OperationalError", args=(2013, "Lost connection to MySQL server during query")), "connection"),
    (_exc("OperationalError", args=(1792, "Cannot execute statement in a READ ONLY transaction.")), "sql"),
    (_exc("OperationalError", "could not connect to server", module="psycopg2"), "connection"),
    (_exc("OperationalError", "server closed the connection unexpectedly", module="psycopg2"), "connection"),
    (_exc("InterfaceError", "connection already closed"), "connection"),
    (_exc("QueryCanceledError", "canceling statement due to statement timeout"), "timeout"),
    (_exc("QueryCanceledError", "canceling statement due to user request"), "cancelled"),
    (_exc("InterruptException", "INTERRUPT Error: Interrupted!"), "cancelled"),
    (_exc("DeadlineExceeded", "504 Deadline Exceeded"), "timeout"),
    (_exc("ServiceUnavailable", "503 Service Unavailable"), "connection"),
    (_exc("ExaQueryTimeoutError", ""), "timeout"),
    (_exc("ExaCommunicationError", ""), "connection"),
    (_exc("ExaQueryError", "object T not found"), "sql"),
    (_exc("BinderException", 'Binder Error: Referenced column "x" not found'), "sql"),
    (_exc("ProgrammingError", "SQL compilation error: invalid identifier 'FOO'"), "sql"),
    (_exc("BadRequest", "400 Unrecognized name: foo at [1:8]"), "sql"),
    (_exc("TimeoutError", ""), "timeout"),
    (_exc("ConnectionResetError", ""), "connection"),
], ids=lambda v: v if isinstance(v, str) else f"{type(v).__name__}:{str(v)[:30]}")
def test_errors_are_typed(exc, kind):
    assert classify_error(exc) == kind


def test_a_result_carries_no_kind_until_an_engine_gives_one():
    assert QueryResult(hypothesis_id="x", sql="SELECT 1", columns=[], rows=[], row_count=0).error_kind is None


# ── DE-3d: the door's retry, eviction and the pool ───────────────────────────────────────────────────────────────────

class _Flaky(DatabaseConnection):
    """A connection whose first ``times`` runs fail with ``exc``; the next answers."""
    dialect = "duckdb"
    engine_read_only = True

    def __init__(self, exc: BaseException | None, times: int = 1):
        self.calls, self._exc, self._times = 0, exc, times

    def execute(self, hypothesis_id, sql, *, sql_dialect=None, internal=False):
        return D.through_door(self, sql, sql_dialect, lambda s: self._run(hypothesis_id, s), internal=internal)

    def _run(self, hypothesis_id, sql):
        self.calls += 1
        if self._exc is not None and self.calls <= self._times:
            return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0,
                               error=str(self._exc), error_kind=classify_error(self._exc))
        return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=["n"], rows=[["1"]], row_count=1)

    def get_schema(self):
        return ""

    def test(self):
        return True, ""

    def close(self):
        return None


_LOST = _exc("InterfaceError", "connection already closed")


def test_a_platform_statement_is_run_once_more_on_a_lost_connection_and_a_persons_is_not():
    probe = _Flaky(_LOST)
    r = probe.execute("__probe__", "SELECT 1", internal=True)
    assert not r.error and probe.calls == 2
    assert r.doors == ["failed:connection", "retried:connection"], r.doors
    assert D.connection_lost(probe), "the pool must not hand it out again"

    person = _Flaky(_LOST)
    r = person.execute("answer", "SELECT 1")
    assert r.error and r.error_kind == "connection" and person.calls == 1, "a person's statement was retried"
    assert r.doors == ["failed:connection"] and D.connection_lost(person)

    typo = _Flaky(_exc("BinderException", "Binder Error: column x not found"))
    r = typo.execute("__probe__", "SELECT x", internal=True)
    assert r.error_kind == "sql" and typo.calls == 1 and not D.connection_lost(typo)
    assert r.doors == ["failed:sql"]
    assert D.describe(["failed:sql", "retried:connection"])[0] == "the engine did not answer it: a sql error"


def test_a_door_nested_in_a_door_retries_once_in_all():
    """The base `execute_bounded` runs `execute`: two doors, one retry — the outer sees the inner's on the path."""
    twice = _Flaky(_LOST, times=5)
    r = DatabaseConnection.execute_bounded(twice, "__probe__", "SELECT 1", 5, internal=True)
    assert r.error and r.error_kind == "connection" and twice.calls == 2, twice.calls
    assert r.doors.count("retried:connection") == 1


def test_the_pool_closes_a_lost_connection_and_hands_out_only_what_answers():
    from aughor.db.pool import ConnectionPool

    class _Conn:
        poolable = True

        def __init__(self):
            self.closed, self.healthy = 0, True

        def close(self):
            self.closed += 1

        def is_healthy(self):
            return self.healthy

    pool = ConnectionPool()
    first = pool.acquire("k", _Conn)
    first.close()                                                   # back to the idle bucket
    assert pool.stats()["idle_total"] == 1
    assert pool.acquire("k", _Conn) is first                        # reused while healthy
    D.mark_lost(first)
    first.close()                                                   # a lost connection is closed, never returned
    assert pool.stats()["idle_total"] == 0 and first.closed == 1

    idle = pool.acquire("k", _Conn)
    idle.healthy = False
    idle.close()
    other = pool.acquire("k", _Conn)                                # the unhealthy idle one is discarded
    assert other is not idle and idle.closed == 1

    class _Silent:
        poolable = True

        def close(self):
            pass

    silent = pool.acquire("s", _Silent)
    silent.close()
    assert pool.acquire("s", _Silent) is not silent, "a connection that cannot say it is healthy was handed out"


def test_every_connection_class_answers_is_healthy():
    """The base answers through `test()`; each warehouse connector answers more cheaply, with its own check."""
    warehouse = {"BigQueryConnection", "SnowflakeConnection", "MySQLConnection", "ExasolConnection",
                 "TrinoConnection", "MotherDuckConnection", "PostgresConnection", "DuckDBConnection",
                 "SQLiteConnection", "LocalUploadConnection"}
    assert warehouse <= {c.__name__ for c in CLASSES}
    for cls in CLASSES:
        assert callable(getattr(cls, "is_healthy", None)), cls.__name__
        if cls.__name__ in warehouse:
            assert cls.is_healthy is not DatabaseConnection.is_healthy, f"{cls.__name__} leans on the base probe"

    class _ViaTest(_Flaky):
        def __init__(self, ok):
            super().__init__(None)
            self._ok = ok

        def test(self):
            if self._ok is None:
                raise RuntimeError("probe exploded")
            return self._ok, ""

    assert _ViaTest(True).is_healthy() is True
    assert _ViaTest(False).is_healthy() is False
    assert _ViaTest(None).is_healthy() is False


def test_mysql_answers_without_reconnecting():
    from aughor.connectors.warehouse.mysql import MySQLConnection

    conn = object.__new__(MySQLConnection)
    pinged: list = []
    conn._conn = SimpleNamespace(open=True, ping=lambda reconnect: pinged.append(reconnect))
    assert conn.is_healthy() is True and pinged == [False], "the probe must not reconnect for the pool"
    conn._conn = SimpleNamespace(open=False, ping=lambda reconnect: None)
    assert conn.is_healthy() is False

    def _boom(reconnect):
        raise RuntimeError("gone")
    conn._conn = SimpleNamespace(open=True, ping=_boom)
    assert conn.is_healthy() is False


def test_a_real_sql_error_is_typed_at_the_door(tmp_path: Path):
    path = tmp_path / "t.duckdb"
    raw = duckdb.connect(str(path))
    raw.execute("CREATE TABLE t (n INTEGER)")
    raw.close()
    conn = DuckDBConnection(path, connection_id="de3")
    try:
        assert conn.is_healthy() is True
        r = conn.execute("answer", "SELECT nope FROM t")
        assert r.error and r.error_kind == "sql" and "failed:sql" in r.doors, (r.error, r.doors)
        assert not D.connection_lost(conn)
    finally:
        conn.close()
