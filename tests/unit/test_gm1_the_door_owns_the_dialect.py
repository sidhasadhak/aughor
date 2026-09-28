"""GM-1 — the door owns the dialect (ROADMAP §3.49, `docs/GATE_MAP_STUDY_2026-09-26.md`).

Platform code writes SQL in DuckDB's dialect. On an engine that runs SQL as written — BigQuery, Snowflake, MySQL,
Exasol — a double-quoted identifier is a string literal, so that SQL means something else or nothing. Before GM-1 the
translation was `native_sql`, a function each call site had to remember. The monitor runner forgot, and theLook's
Units Sold watch failed 2,283 times on BigQuery. Six tests existed for the seam, each written after a live failure:
a gate enforced per incident.

Now a statement declares the dialect it was written in (``sql_dialect="duckdb"``) and every connection's `execute`
and `execute_bounded` translate before their first gate. These tests pin the DOOR, not any one call site: every
connection class reads the declaration, the native engines hand their first gate the translated statement, an
undeclared statement is handed on exactly as before, and the adapters and the guard battery translate once.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from pathlib import Path

import pytest
import sqlglot

import aughor.connectors
import aughor.db.connection as dbc
from aughor.control_plane.contracts.execution import QueryResult
from aughor.db.connection import DatabaseConnection

#: Platform SQL as the probes write it: double-quoted identifiers, a DuckDB cast, the `::` operator.
PLATFORM = 'SELECT "user_id", CAST("created_at" AS VARCHAR) AS d, "sale_price"::DOUBLE AS p FROM "orders"'


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
NATIVE = [c for c in CLASSES if getattr(c, "writes_native_sql", False)]


def test_the_census_of_doors_found_them_all():
    """A walk that found nothing would pass every test below."""
    names = {c.__name__ for c in CLASSES}
    assert {"DuckDBConnection", "PostgresConnection", "LocalUploadConnection", "BigQueryConnection",
            "SnowflakeConnection", "MySQLConnection", "ExasolConnection"} <= names
    assert {c.__name__ for c in NATIVE} == {"BigQueryConnection", "SnowflakeConnection", "MySQLConnection",
                                            "ExasolConnection"}


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
@pytest.mark.parametrize("entry", ["execute", "execute_bounded"])
def test_every_door_reads_the_declaration(cls, entry):
    """Each entry point passes the declaration through the door's step, which refuses a dialect it cannot read
    before any gate or driver is reached. A connector that accepted the keyword and ignored it would run the
    statement (and fail on the absent driver) instead of refusing."""
    conn = object.__new__(cls)
    conn._conn = conn._duckdb = None      # the handle the DuckDB-backed doors name in their call
    args =("__gm1__", PLATFORM) + ((10,) if entry == "execute_bounded" else ())
    with pytest.raises(ValueError, match="sql_dialect='bigquery'"):
        getattr(conn, entry)(*args, sql_dialect="bigquery")


def _first_gate(monkeypatch) -> list[str]:
    seen: list[str] = []

    def security_pre(connection_id, hypothesis_id, sql):
        seen.append(sql)
        return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error="stopped")
    monkeypatch.setattr(dbc, "security_pre", security_pre)
    return seen


@pytest.mark.parametrize("cls", NATIVE, ids=lambda c: c.__name__)
@pytest.mark.parametrize("entry", ["execute", "execute_bounded"])
def test_a_native_engine_hands_its_first_gate_the_translated_statement(cls, entry, monkeypatch):
    """Translated BEFORE the safety check, so the check, the row policy, the audit row and the engine all read the
    statement that runs."""
    seen = _first_gate(monkeypatch)
    conn = object.__new__(cls)
    conn._connection_id = "gm1"
    args = ("__gm1__", PLATFORM) + ((10,) if entry == "execute_bounded" else ())
    getattr(conn, entry)(*args, sql_dialect="duckdb")
    assert seen == [sqlglot.transpile(PLATFORM, read="duckdb", write=cls.dialect)[0]]
    if cls.dialect in ("bigquery", "mysql"):
        assert '"' not in seen[0], f"a double-quoted identifier is a string literal on {cls.dialect}: {seen[0]}"


@pytest.mark.parametrize("cls", NATIVE, ids=lambda c: c.__name__)
def test_an_undeclared_statement_is_handed_on_as_written(cls, monkeypatch):
    """The model's SQL, a person's, one sqlglot rendered in the engine's dialect: byte-identical to before GM-1."""
    seen = _first_gate(monkeypatch)
    conn = object.__new__(cls)
    conn._connection_id = "gm1"
    conn.execute("__gm1__", PLATFORM)
    conn.execute_bounded("__gm1__", PLATFORM, 10)
    assert seen == [PLATFORM, PLATFORM]


def test_duckdb_runs_its_own_statement_declared_or_not(tmp_path: Path):
    import duckdb
    path = tmp_path / "gm1.duckdb"
    raw = duckdb.connect(str(path))
    raw.execute("CREATE TABLE orders (user_id INTEGER, created_at TIMESTAMP, sale_price DOUBLE)")
    raw.execute("INSERT INTO orders VALUES (7, TIMESTAMP '2026-09-01 10:00:00', 12.5)")
    raw.close()
    conn = dbc.DuckDBConnection(path, connection_id="gm1")
    try:
        declared = conn.execute("__gm1__", PLATFORM, sql_dialect="duckdb")
        plain = conn.execute("__gm1__", PLATFORM)
        bounded = conn.execute_bounded("__gm1__", PLATFORM, 5, sql_dialect="duckdb")
    finally:
        conn.close()
    assert not declared.error and declared.rows == plain.rows == bounded.rows == [["7", "2026-09-01 10:00:00", "12.5"]]


class _Native(DatabaseConnection):
    """A native engine that records what reaches its `execute`."""
    dialect = "bigquery"
    writes_native_sql = True

    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def execute(self, hypothesis_id, sql, *, sql_dialect=None):
        self.calls.append((sql, sql_dialect))
        return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=["n"], rows=[["1"]], row_count=1)

    def get_schema(self):
        return ""

    def test(self):
        return True, ""

    def close(self):
        return None


TRANSLATED = sqlglot.transpile(PLATFORM, read="duckdb", write="bigquery")[0]


@pytest.mark.parametrize("call", [
    lambda c: c.rows(PLATFORM, label="__gm1__", sql_dialect="duckdb"),
    lambda c: c.scalar(PLATFORM, label="__gm1__", sql_dialect="duckdb"),
    lambda c: c.execute_typed("__gm1__", PLATFORM, sql_dialect="duckdb"),
    lambda c: c.read_typed_rows("__gm1__", PLATFORM, 10, sql_dialect="duckdb"),
    lambda c: c.execute_bounded("__gm1__", PLATFORM, 10, sql_dialect="duckdb"),
], ids=["rows", "scalar", "execute_typed", "read_typed_rows", "execute_bounded"])
def test_the_adapters_translate_exactly_once(call):
    """Translated by the adapter and handed to `execute` undeclared: twice would read BigQuery SQL as DuckDB."""
    conn = _Native()
    call(conn)
    assert conn.calls == [(TRANSLATED, None)]


def test_a_declaration_the_door_cannot_read_is_not_swallowed_by_rows():
    """`rows` turns every error into `[]`; a refused declaration must not read as an empty result."""
    with pytest.raises(ValueError):
        _Native().rows(PLATFORM, sql_dialect="postgres")


def test_the_guard_battery_translates_before_its_first_guard(monkeypatch):
    import aughor.trust as trust
    from aughor.sql.executor import execute_guarded

    verified: list[str] = []
    real_verify = trust.verify

    def verify(sql, *a, **k):
        verified.append(sql)
        return real_verify(sql, *a, **k)
    monkeypatch.setattr(trust, "verify", verify)
    conn = _Native()
    execute_guarded(conn, PLATFORM, query_id="__gm1__", sql_dialect="duckdb")
    assert verified == [TRANSLATED], "the trust gate read the statement the platform wrote, not the one that runs"
    assert conn.calls[0] == (TRANSLATED, None)


def test_native_sql_is_the_doors_own_step():
    """GM-1's claim, held: nothing translates platform SQL for itself any more. The door's step calls `native_sql`;
    the writer's dialect-rejection repair builds a CANDIDATE from it for the caller's dry run, and runs nothing."""
    root = Path(dbc.__file__).resolve().parents[1]
    callers = sorted(
        str(p.relative_to(root.parent))
        for p in root.rglob("*.py")
        if re.search(r"(?<![\w.])native_sql\(", p.read_text(errors="ignore"))
    )
    assert callers == ["aughor/db/dialects.py", "aughor/sql/writer.py"], callers
