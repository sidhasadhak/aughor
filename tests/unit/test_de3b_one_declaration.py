"""DE-3b (ROADMAP §3.51; §6 item 37(d)) — each engine declared once; every copy derived; a test
that fails when a copy drifts.

Before: an engine was spread over fourteen to seventeen files, two web copies had drifted
(MotherDuck, Exasol, Google Sheets and SQLite missing from the connection modal and the
catalog tags). Now `aughor/connectors/declarations.py` holds one `EngineDeclaration` per
engine, and the registry's tables, the writer rules, the capability rows, the prompt's engine
names, `catalog.json` and `web/lib/connectors.gen.ts` are derived from it. The receipt the
plan asked for — one new engine as a single declaration, seen in the picker, the writer rules
and the catalog — is Trino, DE-3b's proving engine, whose live run waits for a container.
"""
from __future__ import annotations

import importlib.machinery
import json
import sys
import types
from pathlib import Path

import pytest

from aughor.connectors import declarations as D
from aughor.connectors.registry import (
    CATEGORIES,
    DRIVERS,
    DSN_PREVIEWS,
    ENV_VARS,
    FORM_FIELDS,
    PROVIDED_BY,
    REGISTRY,
    secret_field_keys,
)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

REGISTERED = [e for e in D.ENGINES if e.registered]


# ── the registry is the declarations ───────────────────────────────────────────────

def test_every_registered_type_is_declared_and_every_declared_connector_is_registered():
    assert set(REGISTRY.supported_types()) == {e.type for e in REGISTERED}
    # The two built-ins live in db/connection.py and the knowledge types take no queries: all
    # four are declared and categorised, none registered.
    unregistered = set(D.BY_TYPE) - set(REGISTRY.supported_types())
    assert unregistered == {"duckdb", "postgres", "confluence", "notion"}


def test_the_registry_tables_are_derived_not_copied():
    t = D.derive_registry_tables()
    assert DSN_PREVIEWS == t["DSN_PREVIEWS"]
    assert FORM_FIELDS == t["FORM_FIELDS"]
    assert DRIVERS == t["DRIVERS"]
    assert CATEGORIES == t["CATEGORIES"]
    assert ENV_VARS == t["ENV_VARS"]
    assert secret_field_keys("snowflake") == {"password"}
    assert secret_field_keys("postgres") == set(), "the DSN is encrypted in its own column, not as meta"
    # Every driver a declaration names is one PROVIDED_BY can place in an install.
    assert {m for e in D.ENGINES for m in e.drivers} <= set(PROVIDED_BY)


@pytest.mark.parametrize("decl", REGISTERED, ids=lambda e: e.type)
def test_each_connector_class_says_what_its_declaration_says(decl):
    """The class's own `dialect`, `writes_native_sql`, `param_style` and category are the
    declaration's — stated once, and held here when a class and its declaration part."""
    cls = REGISTRY.get_class(decl.type)
    assert cls is not None and cls.__name__ == decl.connector.rsplit(":", 1)[1]
    assert getattr(cls, "dialect", None) == decl.dialect, (decl.type, "dialect")
    assert bool(getattr(cls, "writes_native_sql", False)) is decl.native_sql, (decl.type, "native_sql")
    assert getattr(cls, "param_style", None) == decl.param_style, (decl.type, "param_style")
    assert getattr(cls, "connector_category", None) == decl.category, (decl.type, "category")
    cls_ro = getattr(cls, "engine_read_only", None)
    if decl.engine_read_only is not None and cls_ro is not None:
        assert cls_ro is decl.engine_read_only, (decl.type, "engine_read_only")


def test_the_two_built_ins_agree_with_their_declarations():
    from aughor.db.connection import DuckDBConnection, PostgresConnection, connection_traits
    assert DuckDBConnection.dialect == D.declaration("duckdb").dialect
    assert PostgresConnection.dialect == D.declaration("postgres").dialect
    for t in ("duckdb", "postgres", "bigquery", "exasol", "trino"):
        d = D.declaration(t)
        assert connection_traits(t) == {"dialect": d.dialect, "writes_native_sql": d.native_sql}, t


# ── the writer, the capability contract and the prompt read the declaration ─────────

def test_writer_rules_capabilities_and_engine_names_are_derived():
    from aughor.agent.sql_context import _ENGINE_NAMES
    from aughor.db.capabilities import avoid_line, for_dialect
    from aughor.db.dialects import _DIALECT_RULES, rules_for_dialect

    assert _DIALECT_RULES == D.derive_writer_rules()
    assert set(_DIALECT_RULES) == {"bigquery", "snowflake", "mysql", "exasol", "postgres", "trino"}
    for dialect, (functions, features) in D.derive_refusals().items():
        caps = for_dialect(dialect)
        assert caps.unsupported_functions == functions and caps.unsupported_features == features, dialect
    assert not for_dialect("duckdb").unsupported_functions, "transpiled engines stay permissive"
    assert _ENGINE_NAMES == D.derive_engine_names()
    assert _ENGINE_NAMES["bigquery"] == "BigQuery (GoogleSQL)" and _ENGINE_NAMES["postgresql"] == "PostgreSQL"
    # Exasol's DE-3a facts survive the move: QUALIFY allowed, DATEDIFF refused.
    assert "QUALIFY" not in avoid_line("exasol") and "DATEDIFF" in avoid_line("exasol")
    assert "TRINO DIALECT RULES" in rules_for_dialect("trino") and "QUALIFY" in avoid_line("trino")


# ── the generated copies are current ─────────────────────────────────────────────

def test_catalog_json_and_the_web_map_are_generated_from_the_declarations():
    from scripts.gen_connector_catalog import CATALOG, WEB_GEN, build, render_web

    assert json.loads(CATALOG.read_text()) == build(), "catalog.json is stale — regenerate"
    assert WEB_GEN.read_text() == render_web(), "web/lib/connectors.gen.ts is stale — regenerate"
    cat = {e["type"]: e for e in build()["types"]}
    assert set(cat) == set(D.BY_TYPE)
    assert cat["exasol"]["dialect"] == "exasol" and cat["exasol"]["native_sql"] is True
    assert cat["exasol"]["support_tier"] == "preview" and cat["exasol"]["metadata_strategy"] == "engine_catalog"
    assert cat["confluence"]["connector"] is None and cat["confluence"]["dialect"] is None


def test_one_new_declaration_reaches_every_derived_surface():
    """The wave's point: adding an engine is one declaration and its connector. A made-up one,
    never registered, flows into every table the registry, the writer, the contract, the
    prompt, the catalog and the web map derive — with nothing else edited."""
    from scripts.gen_connector_catalog import build, render_web

    zebra = D.EngineDeclaration(
        type="zebra", label="Zebra DB", category="warehouse", blurb="striped storage",
        dsn_preview="zebra://host", fields=(D.Field("host", "Host", "z"), D.Field("token", "Token", "", secret=True)),
        drivers=("duckdb",), connector="aughor.connectors.warehouse.zebra:ZebraConnection",
        dialect="zebra", native_sql=True, writer_rules="ZEBRA DIALECT RULES",
        refuses_functions=frozenset({"STRIPES"}), support_tier="preview", badge="Preview", brand_color="#010203",
        connection_errors=("ZebraLostError",),
    )
    engines = D.ENGINES + (zebra,)
    assert "ZebraLostError" in D.derive_error_names(engines)["connection"]
    t = D.derive_registry_tables(engines)
    assert t["CATEGORIES"]["zebra"] == "warehouse"
    assert t["FORM_FIELDS"]["zebra"][1] == {"key": "token", "label": "Token", "placeholder": "", "secret": True}
    assert t["REGISTRATIONS"]["zebra"] == "aughor.connectors.warehouse.zebra:ZebraConnection"
    assert D.derive_writer_rules(engines)["zebra"] == "ZEBRA DIALECT RULES"
    assert D.derive_refusals(engines)["zebra"] == (frozenset({"STRIPES"}), frozenset())
    assert D.derive_engine_names(engines)["zebra"] == "Zebra DB"
    entry = {e["type"]: e for e in build(engines)["types"]}["zebra"]
    assert entry["secret_fields"] == ["token"] and entry["dialect"] == "zebra" and entry["badge"] == "Preview"
    assert entry["install"] == "base"
    web = render_web(engines)
    assert '"zebra": {' in web and "Zebra DB" in web and "#010203" in web and '"engineFamily": "standard"' in web


# ── Trino: the proving engine, as one declaration and its connector ────────────────

def test_trino_is_declared_once_and_everything_reads_it():
    import sqlglot

    d = D.declaration("trino")
    assert d.category == "warehouse" and d.badge == "Preview" and d.support_tier == "preview"
    from aughor.connectors.warehouse.trino import TrinoConnection
    assert TrinoConnection.dialect == "trino" and TrinoConnection.writes_native_sql is True
    assert getattr(TrinoConnection, "param_style", None) is None, "binds positionally: a visible refusal"
    # sqlglot speaks it: the platform's own DuckDB spelling transpiles into Trino's.
    (out,) = sqlglot.transpile("SELECT date_trunc('month', d) AS m, count(*) FROM t GROUP BY 1", read="duckdb", write="trino")
    assert "DATE_TRUNC('MONTH', d)" in out or "DATE_TRUNC('month', d)" in out
    # The door types its lost connection by the driver's exception name — a name the declaration
    # carries and `db/errors.py` derives, so DE-3d's typing holds for an engine declared later.
    from aughor.db.errors import _CONNECTION_NAMES, _TIMEOUT_NAMES, classify_error
    exc = type("TrinoConnectionError", (Exception,), {})("coordinator unreachable")
    assert classify_error(exc) == "connection"
    assert {"ExaConnectionError", "ConnectionException", "InterfaceError"} <= _CONNECTION_NAMES
    assert {"DeadlineExceeded", "ExaQueryTimeoutError"} <= _TIMEOUT_NAMES
    # The picker's catalog carries it with its install path.
    from scripts.gen_connector_catalog import CATALOG
    entry = {e["type"]: e for e in json.loads(CATALOG.read_text())["types"]}["trino"]
    assert entry["install"] == "warehouse" and entry["drivers"] == ["trino"]


class _FakeCursor:
    def __init__(self, log: list[str]):
        self.log = log
        self.description = [("n", "bigint", None, None, None, None, None), ("s", "varchar", None, None, None, None, None)]

    def execute(self, sql, params=None):
        self.log.append(sql)
        if "boom" in sql:
            raise type("TrinoConnectionError", (Exception,), {})("coordinator unreachable")

    def fetchmany(self, n):
        return [(1, "a"), (2, None)][:n]

    def fetchall(self):
        return [(1, "a")]

    def fetchone(self):
        return ("455",)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, log):
        self.log = log
        self._closed = False

    def cursor(self):
        return _FakeCursor(self.log)

    def close(self):
        self._closed = True


def test_trino_connector_runs_through_the_door_on_a_fake_driver(monkeypatch):
    log: list[str] = []
    fake = types.ModuleType("trino")
    fake.__spec__ = importlib.machinery.ModuleSpec("trino", None)
    fake.dbapi = types.SimpleNamespace(connect=lambda **kw: _FakeConn(log))
    fake.auth = types.SimpleNamespace(BasicAuthentication=lambda u, p: (u, p))
    monkeypatch.setitem(sys.modules, "trino", fake)

    from aughor.connectors.warehouse.trino import TrinoConnection
    conn = TrinoConnection("trino://coordinator:8080", meta={"user": "analyst", "catalog": "hive", "schema_name": "default"})
    assert conn.is_healthy()
    ok, msg = conn.test()
    assert ok and "455" in msg

    res = conn.execute("h1", "SELECT 1 AS n, 'a' AS s", internal=True)
    assert not res.error, res.error
    assert res.columns == ["n", "s"] and res.rows == [["1", "a"], ["2", "NULL"]]
    assert log and log[-1].startswith("SELECT 1 AS n")

    lost = conn.execute("h2", "SELECT boom FROM t", internal=False)
    assert lost.error and lost.error_kind == "connection"
    conn.close()
    assert not conn.is_healthy()
