"""GM-5 — audit and redaction by what the statement is (ROADMAP §3.49).

A statement skipped the safety check, the audit row and PII redaction when its LABEL was spelled like plumbing —
any `__dunder__`, and a hand-listed set of bare names — while a second hand-list forced some dunder labels back
through. The census found 21 statements a model, a person or a stored definition wrote exempt by that spelling
alone (a person's bulk SQL, a person's ALTER COLUMN, the model's repaired exploration SQL, the answer re-check), and
24 of the platform's own probes audited as if they were somebody's activity.

The exemption is the caller's declaration now (`internal=True`), in force for its one statement, held by the census
to the platform's own statements (`tests/unit/test_sql_door_census.py`). The audit page lists what somebody did, and
says how many of the platform's own queries it does not list.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import duckdb
import pytest

import aughor.connectors
import aughor.db.connection as dbc
from aughor.control_plane.contracts.execution import QueryResult
from aughor.db.connection import DatabaseConnection, DuckDBConnection
from aughor.db.doors import statement_is_internal, through_door
from aughor.security.audit import AuditLogger, InternalCounter


@pytest.fixture
def shop(tmp_path: Path):
    path = tmp_path / "shop.duckdb"
    raw = duckdb.connect(str(path))
    raw.execute("CREATE TABLE orders (order_id INTEGER, email VARCHAR)")
    raw.execute("INSERT INTO orders VALUES (1, 'ana@example.com'), (2, 'bo@example.com')")
    raw.close()
    conn = DuckDBConnection(path, connection_id="gm5")
    yield conn
    conn.close()


def _audited(label: str) -> int:
    return sum(1 for r in AuditLogger.recent(limit=500, connection_id="gm5") if r.get("hypothesis_id") == label)


def _counted() -> int:
    return InternalCounter.totals(connection_id="gm5")["internal_statements"]


# ── the declaration, not the label ─────────────────────────────────────────────────────────────────────────────────

def test_a_label_spelled_like_plumbing_is_audited(shop):
    before = _audited("__catalog__")
    r = shop.execute("__catalog__", "SELECT email FROM orders")
    assert "internal" not in r.doors and {"safety-checked", "audited"} <= set(r.doors)
    assert _audited("__catalog__") == before + 1
    assert all("@" not in str(v) for row in r.rows for v in row), "a person-visible read skipped PII redaction"


def test_a_declared_statement_is_counted_and_not_listed(shop):
    listed, counted = _audited("probe"), _counted()
    r = shop.execute("probe", "SELECT COUNT(*) FROM orders", internal=True)
    assert r.doors[-1] == "internal" and "audited" not in r.doors
    assert _audited("probe") == listed, "a declared statement left an audit row"
    assert _counted() == counted + 1


def test_the_declaration_holds_for_its_one_statement(shop):
    shop.execute("probe", "SELECT 1", internal=True)
    assert "audited" in shop.execute("next", "SELECT 1").doors, "the declaration outlived its statement"
    with pytest.raises(RuntimeError):
        through_door(shop, "SELECT 1", None, lambda s: (_ for _ in ()).throw(RuntimeError("boom")), internal=True)
    assert statement_is_internal() is False, "an exception left the declaration in force"


def test_every_delegation_forwards_the_declaration(shop):
    """The base `execute_bounded` delegates to `execute`, which opens its own door: a delegation that dropped the
    keyword would reset the statement to audited. The adapters forward it too; `read_typed_rows` declares itself."""
    assert shop.execute_bounded("probe", "SELECT 1", 5, internal=True).doors[-1] == "internal"
    # the base class's delegation (no concrete class in the repo uses it; a new connector would)
    assert DatabaseConnection.execute_bounded(shop, "probe", "SELECT 1", 5, internal=True).doors[-1] == "internal"
    counted = _counted()
    shop.rows("SELECT 1", label="probe", internal=True)
    shop.scalar("SELECT 1", label="probe", internal=True)
    result, _payload = shop.read_typed_rows("a plain label", "SELECT 1", 5)
    assert result.doors[-1] == "internal"
    assert _counted() == counted + 3


def test_a_typed_read_is_never_an_unredacted_side_channel(shop):
    """`execute_typed` takes no declaration: its payload always passes the PII and audit post-pass."""
    assert "internal" not in inspect.signature(DatabaseConnection.execute_typed).parameters
    result, payload = shop.execute_typed("__catalog__", "SELECT email FROM orders")
    assert payload is not None and all("@" not in str(v) for row in payload["rows"] for v in row)


# ── every connection class carries it to the first gate ────────────────────────────────────────────────────────────

def _all_connection_classes() -> list[type]:
    for mod in pkgutil.walk_packages(aughor.connectors.__path__, "aughor.connectors."):
        importlib.import_module(mod.name)

    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from walk(sub)
    return sorted({c for c in walk(DatabaseConnection) if c.__module__.startswith("aughor.")
                   and not inspect.isabstract(c)}, key=lambda c: c.__qualname__)


@pytest.mark.parametrize("cls", _all_connection_classes(), ids=lambda c: c.__name__)
@pytest.mark.parametrize("entry", ["execute", "execute_bounded"])
@pytest.mark.parametrize("declared", [True, False])
def test_every_connection_carries_the_declaration_to_its_first_gate(cls, entry, declared, monkeypatch):
    seen: list[bool] = []

    def first_gate(connection_id, hypothesis_id, sql):
        seen.append(statement_is_internal())
        return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error="stopped")
    monkeypatch.setattr(dbc, "_security_pre", first_gate)
    conn = object.__new__(cls)
    conn._connection_id, conn._conn, conn._duckdb, conn._schema_name = "gm5", None, None, None
    args = ("__gm5__", "SELECT 1") + ((10,) if entry == "execute_bounded" else ())
    try:
        getattr(conn, entry)(*args, internal=declared)
    except Exception:   # noqa: BLE001 — a connector that reaches for a driver after the gate is fine here
        pass
    assert seen[:1] == [declared], f"{cls.__name__}.{entry} did not carry internal={declared} to its first gate"


# ── what the page says ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_audit_stats_say_what_the_log_does_not_list(shop):
    shop.execute("probe", "SELECT 1", internal=True)
    stats = AuditLogger.stats(connection_id="gm5")
    assert stats["internal_statements"] >= 1 and stats["internal_since"]
    assert AuditLogger.stats(connection_id="nobody")["internal_statements"] == 0


# ── the gaps the label rule left ───────────────────────────────────────────────────────────────────────────────────

def test_a_persons_bulk_read_is_audited(shop):
    before = _audited("__bulk__")
    shop.bulk_read("SELECT email FROM orders", limit=10)
    assert _audited("__bulk__") == before + 1


def test_a_measurement_says_whose_it_is(monkeypatch, shop):
    """The shared measurement runner used one label for five callers and let none of them say what it was; a
    monitor's backtest evaluates the monitor's SQL, which is somebody's, and is audited under its own name."""
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: shop)
    from aughor.db.measure import run_sql_for
    listed, counted = _audited("monitor_backtest"), _counted()
    run_sql_for("gm5", internal=False, label="monitor_backtest")("SELECT COUNT(*) FROM orders")
    run_sql_for("gm5", internal=True)("SELECT COUNT(*) FROM orders")
    assert (_audited("monitor_backtest"), _counted()) == (listed + 1, counted + 1)
    with pytest.raises(TypeError):
        run_sql_for("gm5")                      # a caller must say which it is
