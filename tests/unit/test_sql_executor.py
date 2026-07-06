"""WS2 increment 1 — the shared guarded-SQL runner (aughor/sql/executor.py).

Characterizes ``execute_guarded`` as a verbatim lift of the ADA path's
``_execute_safe``: same QueryResult shape, same guard battery (defan, preflight,
join/filter value-domain probes), same accept/reject repair gates — and pins the
layering rule that the runner lives BELOW the agent layer (imports nothing from
aughor/agent; the FIX prompt + provider arrive as parameters).
"""
from __future__ import annotations

import ast
from pathlib import Path

import duckdb

from aughor.db.connection import DuckDBConnection
from aughor.platform.contracts.execution import QueryResult
from aughor.sql.executor import execute_guarded
from aughor.stats import stats


def _count(key: str) -> int:
    return stats.snapshot()["counters"].get(key, 0)


# ── Fixtures (mirroring tests/unit/test_join_guard_repair.py) ────────────────

def _conn():
    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "test"
    conn._schema_name = None
    conn._conn.execute("CREATE TABLE orders (cust VARCHAR, camp VARCHAR, amt INT)")
    conn._conn.execute(
        "INSERT INTO orders VALUES ('C1','M1',10),('C2','M2',20),('C3','M1',30)"
    )
    conn._conn.execute("CREATE TABLE campaigns (id VARCHAR, name VARCHAR)")
    conn._conn.execute("INSERT INTO campaigns VALUES ('M1','spring'),('M2','summer')")
    return conn


# The disjoint join (orders.cust ↔ campaigns.id) and its correct form.
_BAD = "SELECT c.name, SUM(o.amt) AS rev FROM orders o JOIN campaigns c ON o.cust = c.id GROUP BY c.name"
_GOOD = "SELECT c.name, SUM(o.amt) AS rev FROM orders o JOIN campaigns c ON o.camp = c.id GROUP BY c.name"

# A minimal FIX template carrying the exact placeholder set FIX_SQL_PROMPT uses,
# so the format() contract is exercised without importing the agent layer here.
_FIX_TEMPLATE = (
    "DIALECT {dialect}\nSQL {sql}\nERROR {error}\n{error_diagnosis}"
    "SCHEMA {schema}\n{kb_patterns_section}{metrics_section}"
)


class _StubProvider:
    """Returns a fixed SQL string as the .fixed_sql of any response_model."""

    def __init__(self, fixed_sql: str):
        self._fixed_sql = fixed_sql
        self.calls = 0

    def complete(self, *, system, user, response_model):
        self.calls += 1
        fields = response_model.model_fields
        kwargs = {}
        for name in fields:
            if "sql" in name:
                kwargs[name] = self._fixed_sql
            elif name in ("explanation", "fix_explanation"):
                kwargs[name] = "stubbed fix"
            else:
                kwargs[name] = ""
        return response_model(**kwargs)


# ── (b) Import boundary: the runner lives BELOW the agent layer ──────────────

def test_executor_imports_nothing_from_agent_layer():
    src = Path(__file__).parent.parent.parent / "aughor" / "sql" / "executor.py"
    tree = ast.parse(src.read_text())
    offenders = []
    for node in ast.walk(tree):  # walk catches function-local imports too
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("aughor.agent"):
            offenders.append(f"line {node.lineno}: from {node.module} import ...")
        if isinstance(node, ast.Import):
            offenders.extend(
                f"line {node.lineno}: import {a.name}"
                for a in node.names if a.name.startswith("aughor.agent")
            )
    assert not offenders, (
        "aughor/sql/executor.py must stay below the agent layer — agent-side "
        "inputs (FIX prompt, provider) are parameters, not imports: "
        + "; ".join(offenders)
    )


# ── (a) Characterization: shape + guards fire ────────────────────────────────

def test_returns_queryresult_shape_on_clean_query():
    r = execute_guarded(_conn(), _GOOD, query_id="phase1")
    assert isinstance(r, QueryResult)
    assert r.hypothesis_id == "phase1"
    assert r.error is None
    assert r.row_count == 2
    assert r.columns and r.rows


def test_join_domain_guard_fires_and_repair_is_adopted():
    before = _count("guard.join_domain.fired")
    provider = _StubProvider(_GOOD)
    r = execute_guarded(
        _conn(), _BAD,
        query_id="dimensional",
        schema="orders(cust,camp,amt) campaigns(id,name)",
        fix_prompt_template=_FIX_TEMPLATE,
        provider_factory=lambda role="coder": provider,
    )
    # The value-domain probe fired (observable via the shared guard counter) …
    assert _count("guard.join_domain.fired") > before
    # … and the clearing fix was adopted, exactly like the ADA path.
    assert provider.calls == 1
    assert r.error is None
    assert r.row_count > 0
    assert "o.camp = c.id" in r.sql.replace('"', "")


def test_nonclearing_fix_is_rejected():
    provider = _StubProvider(_BAD)  # "fix" still joins on the disjoint column
    r = execute_guarded(
        _conn(), _BAD,
        query_id="dimensional",
        schema="orders campaigns",
        fix_prompt_template=_FIX_TEMPLATE,
        provider_factory=lambda role="coder": provider,
    )
    assert provider.calls == 1
    # Original kept — never replaced with a rewrite that fails the same guard.
    assert "o.cust = c.id" in r.sql.replace('"', "")


def test_without_fixer_guards_still_run_but_no_llm_retry():
    before = _count("guard.join_domain.fired")
    r = execute_guarded(_conn(), _BAD, query_id="p1", schema="orders campaigns")
    assert _count("guard.join_domain.fired") > before  # deterministic guard ran
    assert isinstance(r, QueryResult)                  # raw result returned
    assert "o.cust = c.id" in r.sql.replace('"', "")   # untouched — no fixer supplied


def test_fanout_defan_rewrites_before_execute():
    # orders (parent) one-to-many lineitem (child); SUM of the parent measure
    # across the join over-counts — the de-fan must rewrite BEFORE execute.
    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "test"
    conn._schema_name = None
    conn._conn.execute("CREATE TABLE orders (o_orderkey INT, o_totalprice DOUBLE)")
    conn._conn.execute("INSERT INTO orders VALUES (1, 100.0), (2, 50.0)")
    conn._conn.execute("CREATE TABLE lineitem (l_orderkey INT, l_quantity INT)")
    conn._conn.execute("INSERT INTO lineitem VALUES (1,1),(1,2),(1,3),(2,1)")
    schema = (
        "TABLE: orders\n"
        "  o_orderkey  INTEGER\n"
        "  o_totalprice  DOUBLE\n"
        "\n"
        "TABLE: lineitem\n"
        "  l_orderkey  INTEGER\n"
        "  l_quantity  INTEGER\n"
    )
    fanned = ("SELECT SUM(o.o_totalprice) AS total FROM orders o "
              "JOIN lineitem l ON o.o_orderkey = l.l_orderkey")
    before = _count("guard.defan.rewritten.parent_fanout")
    r = execute_guarded(conn, fanned, query_id="baseline", schema=schema)
    assert _count("guard.defan.rewritten.parent_fanout") > before  # guard fired
    assert r.error is None and r.row_count == 1
    # The de-fanned rewrite executed: each order counted once (150), not per line-item (350).
    assert float(r.rows[0][0]) == 150.0
    assert "distinct" in r.sql.lower()


def test_preflight_repair_is_invoked_with_schema(monkeypatch):
    seen = {}

    def _spy(conn, sql, schema=None, **kw):
        seen["sql"], seen["schema"] = sql, schema
        return sql, {}

    monkeypatch.setattr("aughor.sql.safety.preflight_repair", _spy)
    execute_guarded(_conn(), _GOOD, query_id="p1", schema="orders campaigns")
    assert seen["sql"] == _GOOD and seen["schema"] == "orders campaigns"


# ── WS2 inc.2: the shared PRE-execute hardening (de-fan + preflight) ─────────

def _fanout_conn():
    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "test"
    conn._schema_name = None
    conn._conn.execute("CREATE TABLE orders (o_orderkey INT, o_totalprice DOUBLE)")
    conn._conn.execute("INSERT INTO orders VALUES (1, 100.0), (2, 50.0)")
    conn._conn.execute("CREATE TABLE lineitem (l_orderkey INT, l_quantity INT)")
    conn._conn.execute("INSERT INTO lineitem VALUES (1,1),(1,2),(1,3),(2,1)")
    return conn


_FANOUT_SCHEMA = (
    "TABLE: orders\n  o_orderkey  INTEGER\n  o_totalprice  DOUBLE\n\n"
    "TABLE: lineitem\n  l_orderkey  INTEGER\n  l_quantity  INTEGER\n"
)
_FANNED = ("SELECT SUM(o.o_totalprice) AS total FROM orders o "
           "JOIN lineitem l ON o.o_orderkey = l.l_orderkey")


def test_preflight_harden_defans_regardless_of_prefix():
    from aughor.sql.executor import preflight_harden

    before = _count("guard.defan.rewritten.parent_fanout")
    out = preflight_harden(_fanout_conn(), _FANNED, _FANOUT_SCHEMA,
                           counter_prefix="explore.exec")
    assert _count("guard.defan.rewritten.parent_fanout") > before
    assert "distinct" in out.lower()  # the de-fanned rewrite, not the original fanned SQL


def test_preflight_harden_noop_on_clean_sql():
    from aughor.sql.executor import preflight_harden

    clean = "SELECT SUM(o_totalprice) AS total FROM orders"
    assert preflight_harden(_fanout_conn(), clean, _FANOUT_SCHEMA).strip() == clean.strip()


def test_preflight_harden_noop_without_schema():
    from aughor.sql.executor import preflight_harden

    assert preflight_harden(_conn(), _GOOD, "") == _GOOD  # no schema → untouched


def test_explore_path_calls_the_shared_hardening():
    """The explore loop (_execute_one_subq) must route through preflight_harden — the
    parity win (it had neither de-fan nor preflight-repair before WS2 inc.2)."""
    src = Path(__file__).parent.parent.parent / "aughor" / "agent" / "explore.py"
    tree = ast.parse(src.read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "preflight_harden"]
    assert calls, "explore.py must call the shared preflight_harden before conn.execute"


def test_investigate_execute_safe_delegates_here(monkeypatch):
    """The ADA `_execute_safe` is now a thin call-site of the shared runner."""
    from aughor.agent import investigate as I

    captured = {}

    def _fake(conn, sql, *, query_id, schema=None, fix_prompt_template=None,
              provider_factory=None):
        captured.update(query_id=query_id, sql=sql, schema=schema,
                        template=fix_prompt_template, factory=provider_factory)
        return QueryResult(hypothesis_id=query_id, sql=sql, columns=[], rows=[],
                           row_count=0, error=None)

    monkeypatch.setattr("aughor.sql.executor.execute_guarded", _fake)
    r = I._execute_safe(_conn(), "phase7", "SELECT 1", schema="s")
    assert r.hypothesis_id == "phase7"
    assert captured["query_id"] == "phase7"
    assert captured["sql"] == "SELECT 1"
    assert captured["schema"] == "s"
    assert captured["template"]                     # FIX_SQL_PROMPT threaded through
    assert captured["factory"] is I._provider       # module-late-bound → monkeypatchable
