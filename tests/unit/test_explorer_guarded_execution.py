"""The autonomous Explorer executes model-written SQL through the SHARED guard battery.

`test_sql_guard_coverage.py` enforces that this module *imports* `aughor.sql.executor`. That is a
structural ratchet and would be satisfied by an unused import. This proves the BEHAVIOUR: a `_run`
carrying model-written SQL actually reaches `execute_guarded`, an internal deterministic probe
does NOT, and a preflight rewrite propagates back so a stored finding cites the query that really
produced its rows.

Why this agent specifically: it writes the Briefing, and until 2026-07-21 it was the only
generate-and-execute path still calling `conn.execute` raw — which is how a
`marketing_campaigns ⋈ brand_collaborations ON platform` fan-out reached a reader as
€102,870,539,329.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import aughor.sql.executor as executor_mod
from aughor.explorer.agent import SchemaExplorer

SCHEMA = ("TABLE: orders (100 rows)\n"
          "  order_id  VARCHAR\n  amount  DECIMAL(18,2)\n")


def _explorer(monkeypatch):
    """A SchemaExplorer wired to a stub connection — no warehouse, no LLM, no state on disk."""
    calls: list[dict] = []

    class _Conn:
        dialect = "duckdb"

        def execute(self, query_id, sql):
            calls.append({"via": "raw", "query_id": query_id, "sql": sql})
            return SimpleNamespace(error=None, rows=[[1]], columns=["n"], row_count=1, sql=sql)

        def get_schema(self):
            return SCHEMA

        def dry_run(self, _sql):
            return (True, "")

    ex = SchemaExplorer.__new__(SchemaExplorer)     # bypass __init__'s store/ontology work
    ex._conn = _Conn()
    ex._last_query_at = 0.0
    ex._last_executed_sql = ""
    ex._status = SimpleNamespace(queries_executed=0)
    ex._episodes = SimpleNamespace(add=lambda **kw: calls.append({"via": "episode", **kw}))
    return ex, calls


def test_model_written_sql_routes_through_execute_guarded(monkeypatch):
    ex, calls = _explorer(monkeypatch)
    seen: list[dict] = []

    def _fake_guarded(conn, sql, *, query_id, schema=None, **kw):
        seen.append({"sql": sql, "query_id": query_id, "schema": schema, "kw": kw})
        return SimpleNamespace(error=None, rows=[[7]], columns=["n"], row_count=1, sql=sql)

    monkeypatch.setattr(executor_mod, "execute_guarded", _fake_guarded)

    rows = asyncio.run(ex._run("SELECT 1", think="t", schema=SCHEMA))

    assert rows == [[7]]
    assert len(seen) == 1, "model-written SQL must go through the shared guard battery"
    assert seen[0]["schema"] == SCHEMA          # schema reaches preflight_harden
    assert not any(c["via"] == "raw" for c in calls)


def test_the_shared_runner_gets_no_llm_repair_hooks(monkeypatch):
    """Deterministic-only by construction: Phase 8 already runs its OWN repair loop, so handing
    the shared runner a fix prompt + provider would give the explorer two competing retries."""
    ex, _ = _explorer(monkeypatch)
    seen: list[dict] = []

    def _fake_guarded(conn, sql, *, query_id, schema=None, **kw):
        seen.append(kw)
        return SimpleNamespace(error=None, rows=[], columns=[], row_count=0, sql=sql)

    monkeypatch.setattr(executor_mod, "execute_guarded", _fake_guarded)
    asyncio.run(ex._run("SELECT 1", schema=SCHEMA))

    assert seen[0].get("fix_prompt_template") is None
    assert seen[0].get("provider_factory") is None


def test_internal_probes_stay_on_the_raw_path(monkeypatch):
    """Profiling / percentile / catalog queries are built by the explorer from parsed schema
    metadata, not written by a model. Hardening them would be pure waste, so no schema → raw."""
    ex, calls = _explorer(monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("deterministic probe must NOT go through execute_guarded")

    monkeypatch.setattr(executor_mod, "execute_guarded", _boom)

    rows = asyncio.run(ex._run("SELECT COUNT(*) FROM orders", think="probe"))
    assert rows == [[1]]
    assert [c for c in calls if c["via"] == "raw"], "probe should hit the connector directly"


def test_a_preflight_rewrite_propagates_to_the_caller(monkeypatch):
    """`preflight_harden` can REWRITE the SQL (de-fan / preflight-repair, dry-run gated). The
    rewritten text is what produced the rows, so it must be what the episode journals AND what
    a caller resyncs into the finding — otherwise the stored insight cites SQL that never ran."""
    ex, calls = _explorer(monkeypatch)
    REWRITTEN = "SELECT SUM(amount) FROM (SELECT DISTINCT order_id, amount FROM orders) t"

    def _rewriting_guard(conn, sql, *, query_id, schema=None, **kw):
        return SimpleNamespace(error=None, rows=[[42]], columns=["s"], row_count=1, sql=REWRITTEN)

    monkeypatch.setattr(executor_mod, "execute_guarded", _rewriting_guard)

    asyncio.run(ex._run("SELECT SUM(o.amount) FROM orders o JOIN tags t ON o.order_id=t.order_id",
                        think="t", schema=SCHEMA))

    assert ex._last_executed_sql == REWRITTEN
    journalled = [c for c in calls if c["via"] == "episode"]
    assert journalled and journalled[-1]["sql"] == REWRITTEN, (
        "the episode must journal the SQL that actually ran, not the pre-rewrite text"
    )


def test_guard_failure_never_breaks_the_run(monkeypatch):
    """Fail-safe: the explorer is a long-running background agent. A guard bug must lose one
    query, not abort the exploration."""
    ex, _ = _explorer(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("guard exploded")

    monkeypatch.setattr(executor_mod, "execute_guarded", _boom)
    assert asyncio.run(ex._run("SELECT 1", schema=SCHEMA)) is None


@pytest.mark.parametrize("call_site", ["pinned", "domain_intel", "synthesis"])
def test_every_model_sql_call_site_passes_a_schema(call_site):
    """Pins the wiring at the three sites that execute model-written SQL. A future `_run(sql)`
    added there without `schema=` would silently drop back to the unguarded path — invisible in
    review, and exactly the drift that left this agent unguarded for months."""
    import inspect

    from aughor.explorer import agent as mod
    src = inspect.getsource(mod)
    marker = {
        "pinned":       'think=f"[pinned] {q[:60]}", schema=sql_writer.schema',
        "domain_intel": 'rows = await self._run(sql, think=label, schema=sql_writer.schema)',
        "synthesis":    'schema=sql_writer.schema)',
    }[call_site]
    assert marker in src, f"the {call_site} call site no longer passes schema= to _run"


class TestRetryQueryIsGuarded:
    """`/exploration/{conn}/retry-query` runs LLM-CORRECTED SQL — a query that already failed once
    and was rewritten by a model. It went to the warehouse raw, which is arguably worse than the
    Explorer's case: the model is patching a query it has already got wrong once, with no guard
    between the patch and the data."""

    def test_retry_query_routes_through_the_shared_battery(self, monkeypatch):
        import aughor.routers.exploration as ex
        import aughor.sql.executor as executor_mod
        import aughor.sql.writer as wmod
        seen: list[dict] = []

        class _Conn:
            dialect = "duckdb"

            def execute(self, qid, sql):
                raise AssertionError("retry-query must not execute raw")

            def get_schema(self):
                return SCHEMA

        class _Writer:
            schema = SCHEMA

            def __init__(self, db, *a, **k):
                pass

            def fix(self, sql, err, hint=None, max_retries=2):
                return SimpleNamespace(ok=True, sql="SELECT 1", explanation="fixed", final_error="")

        monkeypatch.setattr(ex, "open_connection_for", lambda cid: _Conn())
        monkeypatch.setattr(wmod, "SqlWriter", _Writer)

        def _guarded(conn, sql, *, query_id, schema=None, **kw):
            seen.append({"sql": sql, "query_id": query_id, "schema": schema})
            return SimpleNamespace(error=None, rows=[[1]], columns=["n"], row_count=1, sql=sql)

        monkeypatch.setattr(executor_mod, "execute_guarded", _guarded)

        out = asyncio.run(ex.retry_query("c1", SimpleNamespace(sql="SELECT bad", error="boom", hint=None)))

        assert out["ok"] is True
        assert len(seen) == 1 and seen[0]["query_id"] == "__retry__"
        assert seen[0]["schema"] == SCHEMA

    def test_the_response_reports_the_sql_that_actually_ran(self, monkeypatch):
        """The client shows `corrected_sql` as the fix to keep. If preflight rewrites the query,
        returning the PRE-rewrite text hands the user SQL that did not produce the rows beside it."""
        import aughor.routers.exploration as ex
        import aughor.sql.executor as executor_mod
        import aughor.sql.writer as wmod
        REWRITTEN = "SELECT SUM(x) FROM (SELECT DISTINCT id, x FROM t) d"

        class _Conn:
            dialect = "duckdb"

            def get_schema(self):
                return SCHEMA

        class _Writer:
            schema = SCHEMA

            def __init__(self, db, *a, **k):
                pass

            def fix(self, sql, err, hint=None, max_retries=2):
                return SimpleNamespace(ok=True, sql="SELECT SUM(t.x) FROM t JOIN u ON t.id=u.id",
                                       explanation="fixed", final_error="")

        monkeypatch.setattr(ex, "open_connection_for", lambda cid: _Conn())
        monkeypatch.setattr(wmod, "SqlWriter", _Writer)
        monkeypatch.setattr(executor_mod, "execute_guarded",
                            lambda conn, sql, *, query_id, schema=None, **kw: SimpleNamespace(
                                error=None, rows=[[42]], columns=["s"], row_count=1, sql=REWRITTEN))

        out = asyncio.run(ex.retry_query("c1", SimpleNamespace(sql="x", error="e", hint=None)))
        assert out["corrected_sql"] == REWRITTEN

    def test_grounding_replays_stored_sql_verbatim(self):
        """The deliberate exception. `__ground__` proves a cited number came from a finding's own
        query, so it must replay that SQL EXACTLY — a preflight rewrite would make the receipt
        cite SQL the finding does not contain. Pinned in source so the exemption is a decision,
        not an omission someone 'fixes' later."""
        import inspect

        import aughor.routers.exploration as ex
        src = inspect.getsource(ex)
        assert 'db.execute("__ground__"' in src, "grounding must stay a verbatim replay"
        assert "DELIBERATELY unguarded" in src, "the exception must carry its reason in-place"
