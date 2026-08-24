"""Parameters reach every engine as BIND VALUES, or the connector refuses out loud.

`execute_with_params` shipped on three classes — `DuckDBConnection`, `LocalUploadConnection`
and `PostgresConnection` — while `/query` calls it on whatever connection the user has open
and restricts nothing by type. So a `:name` in the SQL editor worked on the Workspace and
failed on every real warehouse, with the base class's refusal as the only symptom.

Two things are asserted here and they are not the same thing:

* the SQL that reaches a driver carries that DRIVER's placeholder spelling;
* the value travels as a separate argument and never appears in the statement text.

The second is the security property, and it is the one worth testing on a connector whose
engine nobody here can reach: a fake driver handle cannot tell us BigQuery accepts our SQL,
but it can tell us we never built that SQL by concatenation.

⚠️ What this file does NOT prove: that a real Snowflake, MySQL or BigQuery accepts these
statements. Those need a live engine. SQLite is exercised end to end because it is the one
warehouse-shaped connector whose driver is in the standard library.
"""
from __future__ import annotations

import sqlite3

import pytest

from aughor.connectors.base import Connector
from aughor.db.connection import DatabaseConnection


class _FakeCursor:
    """Records what a driver was handed. `description`/`fetch*` mimic DBAPI."""

    def __init__(self, rows=None, cols=("a",)):
        self.seen: list[tuple] = []
        self._rows = rows if rows is not None else [(1,)]
        self.description = [(c, None) for c in cols]

    def execute(self, sql, params=None):
        self.seen.append((sql, params))
        return self

    def fetchall(self):
        return self._rows

    def fetchmany(self, n):
        return self._rows[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _bare(cls, **attrs):
    """A connector instance with no __init__ — this asks about binding, not connecting."""
    obj = cls.__new__(cls)
    obj._connection_id = "c1"
    for k, v in attrs.items():
        setattr(obj, k, v)
    return obj


# ── the envelope on Connector ────────────────────────────────────────────────────

class _Unbindable(Connector):
    dialect = "madeup"
    def execute(self, hypothesis_id, sql): ...
    def get_schema(self): ...
    def test(self): ...
    def close(self): ...


class _Bindable(_Unbindable):
    param_style = "duckdb"

    def _bind_execute(self, sql, params):
        self.seen = (sql, params)
        return ["a"], [(1,)]


def test_a_connector_without_a_param_style_keeps_the_visible_refusal():
    """The base exists to say no SAFELY. A connector that cannot bind must not acquire a
    fallback just because it now inherits an envelope that could run one."""
    result = _bare(_Unbindable).execute_with_params("query_workbench", "SELECT :v", {"v": "x"})

    assert result.error and "cannot run parameterised" in result.error
    assert "'x'" not in (result.sql or ""), "the value must not have reached the statement"


def test_the_value_never_reaches_the_statement_text():
    """The whole security property, on the path every binding connector now shares."""
    conn = _bare(_Bindable)
    conn.execute_with_params("query_workbench", "SELECT * FROM t WHERE a = :v",
                             {"v": "x'; DROP TABLE t; --"})

    sent_sql, sent_params = conn.seen
    assert sent_sql == "SELECT * FROM t WHERE a = $v"
    assert sent_params == {"v": "x'; DROP TABLE t; --"}
    assert "DROP TABLE" not in sent_sql


def test_the_receipt_carries_the_statement_the_user_wrote():
    """Not the rendered one. Every downstream reader of a receipt — the guards, the editor
    header, the ledger — was written against `:name`, which is also what the user sees."""
    result = _bare(_Bindable).execute_with_params("query_workbench",
                                                  "SELECT * FROM t WHERE a = :v", {"v": 1})

    assert ":v" in result.sql and "$v" not in result.sql


def test_an_unknown_bind_style_is_an_error_not_a_raw_statement():
    """A style with no placeholder must refuse. Passing `:name` through to an engine that
    does not speak it is a confusing failure; interpolating would be a catastrophic one."""
    conn = _bare(_Bindable)
    conn.param_style = "no-such-style"

    result = conn.execute_with_params("query_workbench", "SELECT :v", {"v": 1})

    assert result.error and "no-such-style" in result.error


# ── one row per driver: the spelling that reaches it ─────────────────────────────

def _duckdb_style(cls, handle_attr):
    conn = _bare(cls, **{handle_attr: _FakeCursor()})
    conn._bind_execute("SELECT $v", {"v": 3})
    return getattr(conn, handle_attr).seen[0]


def test_the_duckdb_backed_connectors_bind_through_their_own_handle():
    """Four classes, one driver, two different attribute names — and `MotherDuckConnection`
    is a sibling of `DuckDBConnection`, not a subclass, which is how capabilities have gone
    missing from these before."""
    from aughor.connectors.api.gsheets import GoogleSheetsConnector
    from aughor.connectors.federated import FederatedConnection
    from aughor.connectors.file.s3 import S3Connection
    from aughor.connectors.warehouse.motherduck import MotherDuckConnection

    assert _duckdb_style(MotherDuckConnection, "_conn") == ("SELECT $v", {"v": 3})
    for cls in (S3Connection, FederatedConnection, GoogleSheetsConnector):
        assert _duckdb_style(cls, "_duckdb") == ("SELECT $v", {"v": 3}), cls.__name__


def test_mysql_binds_pyformat_over_a_dict_cursor():
    from aughor.connectors.warehouse.mysql import MySQLConnection

    cur = _FakeCursor(rows=[{"a": 1}], cols=("a",))
    conn = _bare(MySQLConnection, _conn=type("H", (), {"cursor": lambda _s: cur})())
    cols, rows = conn._bind_execute("SELECT * FROM t WHERE a = %(v)s", {"v": 7})

    assert cur.seen == [("SELECT * FROM t WHERE a = %(v)s", {"v": 7})]
    assert cols == ["a"] and rows == [[1]]


def test_snowflake_binds_pyformat():
    from aughor.connectors.warehouse.snowflake import SnowflakeConnection

    cur = _FakeCursor()
    conn = _bare(SnowflakeConnection, _conn=type("H", (), {"cursor": lambda _s: cur})())
    conn._bind_execute("SELECT * FROM t WHERE a = %(v)s", {"v": 7})

    assert cur.seen == [("SELECT * FROM t WHERE a = %(v)s", {"v": 7})]


def test_the_rest_mirrors_inherit_binding_from_one_place():
    """Stripe, HubSpot and Salesforce share `RestApiSync`'s DuckDB mirror. One hook covers
    all three — and a per-class hook would be three chances to forget one."""
    from aughor.connectors.api.base_sync import RestApiSync
    from aughor.connectors.api.hubspot import HubSpotConnector
    from aughor.connectors.api.salesforce import SalesforceConnector
    from aughor.connectors.api.stripe import StripeConnector

    for cls in (StripeConnector, HubSpotConnector, SalesforceConnector):
        assert cls.param_style == "duckdb"
        assert cls._bind_execute is RestApiSync._bind_execute


# ── BigQuery declares a type per parameter ───────────────────────────────────────

class _FakeBQJob:
    def __init__(self, sink):
        self.sink = sink

    def result(self, max_results=None):
        return type("Rows", (), {"schema": [], "__iter__": lambda _s: iter(())})()


def _bq(params):
    from aughor.connectors.warehouse.bigquery import BigQueryConnection

    sink = {}
    client = type("C", (), {"query": lambda _s, sql, job_config: (
        sink.update(sql=sql, config=job_config) or _FakeBQJob(sink))})()
    conn = _bare(BigQueryConnection, _client=client, _project="p", _dataset="d")
    conn._bind_execute("SELECT @v", params)
    return sink["config"].query_parameters


def test_bigquery_declares_a_type_for_every_parameter():
    declared = {p.name: (p.type_, p.value) for p in _bq({"s": "x", "n": 2, "f": 1.5})}

    assert declared == {"s": ("STRING", "x"), "n": ("INT64", 2), "f": ("FLOAT64", 1.5)}


def test_a_boolean_is_a_bool_and_not_an_int64():
    """`bool` is a SUBCLASS of `int` in Python. Checked in the wrong order, every True
    binds as INT64 1 and `WHERE is_active = @flag` compares a boolean column to a number —
    which BigQuery answers, wrongly, without an error."""
    declared = {p.name: (p.type_, p.value) for p in _bq({"flag": True})}

    assert declared == {"flag": ("BOOL", True)}


def test_bigquery_refuses_an_untyped_null_instead_of_guessing():
    """There is no type to read off a NULL, and BigQuery will not take an untyped
    parameter. Guessing STRING makes `WHERE n = @p` compare a number to text and return
    zero rows with no error — a wrong answer wearing the shape of a real one."""
    with pytest.raises(ValueError, match="declared type"):
        _bq({"p": None})


def test_the_bound_path_caps_at_the_same_row_count_as_execute():
    """One query, one population. `SQLiteConnection` caps at the shared MAX_ROWS (500)
    while every other connector module declares 2000 of its own, so a `max_rows` inherited
    from the envelope would have made a parameterised query return rows the same query
    without parameters does not."""
    import re
    from pathlib import Path as _P

    from aughor.connectors.file.sqlite import SQLiteConnection
    from aughor.db.connection import MAX_ROWS

    assert SQLiteConnection.max_rows == MAX_ROWS

    root = _P(__file__).resolve().parents[2] / "aughor" / "connectors"
    checked = 0
    for module in root.rglob("*.py"):
        declared = re.search(r"^MAX_ROWS\s*=\s*([0-9_]+)", module.read_text(), re.MULTILINE)
        if not declared:
            continue
        for cls in _connector_classes_in(module):
            if cls.param_style:
                checked += 1
                assert cls.max_rows == int(declared.group(1).replace("_", "")), (
                    f"{cls.__name__} binds with max_rows={cls.max_rows} but its module caps "
                    f"`execute` at {declared.group(1)} — one query, two populations")
    assert checked >= 8, (
        f"the module walk reached only {checked} binding connectors — an empty walk passes "
        f"this assertion for free, which is the shape of nothing")


def _connector_classes_in(path):
    """The Connector subclasses defined in one module file."""
    import importlib
    import inspect

    mod_name = "aughor.connectors" + str(path).split("aughor/connectors", 1)[1]
    mod_name = mod_name[:-3].replace("/", ".").replace(".__init__", "")
    try:
        mod = importlib.import_module(mod_name)
    except Exception:
        return []
    return [obj for _n, obj in inspect.getmembers(mod, inspect.isclass)
            if issubclass(obj, Connector) and obj.__module__ == mod_name]


# ── the one connector exercised against a real engine ────────────────────────────

@pytest.fixture
def sqlite_db(tmp_path):
    path = tmp_path / "shop.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE orders (id INTEGER, country TEXT)")
    con.executemany("INSERT INTO orders VALUES (?, ?)",
                    [(1, "Portugal"), (2, "Spain"), (3, "Portugal")])
    con.commit()
    con.close()
    return path


def test_sqlite_runs_a_bound_query_end_to_end(sqlite_db):
    """A real driver, a real file, a real result — the rung the fakes above cannot reach.
    sqlite3's named style is already `:name`, so this also proves the identity rendering
    is a rendering and not an oversight."""
    from aughor.connectors.file.sqlite import SQLiteConnection

    conn = SQLiteConnection(dsn=str(sqlite_db), connection_id="c1")
    result = conn.execute_with_params(
        "query_workbench", "SELECT id FROM orders WHERE country = :country",
        {"country": "Portugal"})

    assert result.error is None, result.error
    assert result.row_count == 2 and result.rows == [["1"], ["3"]]


def test_a_bound_value_comes_back_as_data(sqlite_db):
    """The property the whole feature rests on, measured on a real driver: the classic
    injection string is returned VERBATIM as a value.

    Asserted by selecting the parameter itself rather than by checking the table survived.
    This connection is opened read-only, so a DROP would fail here whether binding worked
    or not — "the table is still there" would have proved the read-only flag, not the
    binding, which is the adjacent claim this test exists to avoid making."""
    from aughor.connectors.file.sqlite import SQLiteConnection

    probe = "Portugal'; DROP TABLE orders; --"
    conn = SQLiteConnection(dsn=str(sqlite_db), connection_id="c1")

    echoed = conn.execute_with_params("query_workbench", "SELECT :country AS c",
                                      {"country": probe})
    assert echoed.error is None, echoed.error
    assert echoed.rows == [[probe]], "the value did not survive as a value"

    filtered = conn.execute_with_params(
        "query_workbench", "SELECT id FROM orders WHERE country = :country",
        {"country": probe})
    assert filtered.error is None and filtered.rows == [], (
        "the injection string matched no row, because it was compared as text")


def test_the_capability_the_base_still_refuses_is_a_decision(sqlite_db):
    """Exasol is deliberately left unbound. This holds the DECISION, so the day someone
    gives it a `param_style` they have to come here and say why it is now safe."""
    from aughor.connectors.warehouse.exasol import ExasolConnection

    assert ExasolConnection.param_style is None
    assert ExasolConnection.execute_with_params is Connector.execute_with_params
    assert Connector.execute_with_params is not DatabaseConnection.execute_with_params
