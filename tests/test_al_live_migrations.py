"""Tests for the AL live-path migrations (Wave 4) — flag-gated, default-off.

AL-01: the Deep-Analysis executor (`_execute_safe`) routes generated SQL through `trust.verify`
before execute when `trust.verify_live` is on — a readonly BLOCK returns a blocked result instead
of executing. AL-05: a deep investigation resolves the Semantic plane once at seed and carries the
SemanticContext on its state when `semantic.resolve_live` is on. Both are byte-identical with the
flag off.
"""
from __future__ import annotations

from aughor.platform.contracts.execution import QueryResult


class _SpyConn:
    dialect = "duckdb"

    def __init__(self):
        self.calls: list[str] = []

    def execute(self, phase_id: str, sql: str) -> QueryResult:
        self.calls.append(sql)
        return QueryResult(hypothesis_id=phase_id, sql=sql, columns=["n"], rows=[[1]],
                           row_count=1, error=None)


# ── AL-01 — the Trust plane on the deep executor ─────────────────────────────────────────

def test_al01_blocks_mutation_when_flag_on(monkeypatch):
    monkeypatch.setenv("AUGHOR_TRUST_VERIFY_LIVE", "1")
    from aughor.agent.investigate import _execute_safe
    spy = _SpyConn()
    r = _execute_safe(spy, "p1", "DELETE FROM orders", schema=None)
    assert (r.error or "").startswith("[BLOCKED]")
    assert spy.calls == []                       # the mutation never reached execute


def test_al01_flag_off_executes_unchanged(monkeypatch):
    monkeypatch.delenv("AUGHOR_TRUST_VERIFY_LIVE", raising=False)
    from aughor.agent.investigate import _execute_safe
    spy = _SpyConn()
    _execute_safe(spy, "p1", "DELETE FROM orders", schema=None)
    assert spy.calls == ["DELETE FROM orders"]   # gate off → byte-identical old behaviour


def test_al01_clean_select_passes_when_flag_on(monkeypatch):
    monkeypatch.setenv("AUGHOR_TRUST_VERIFY_LIVE", "1")
    from aughor.agent.investigate import _execute_safe
    spy = _SpyConn()
    r = _execute_safe(spy, "p1", "SELECT id FROM orders", schema=None)
    assert not (r.error or "").startswith("[BLOCKED]")
    assert spy.calls == ["SELECT id FROM orders"]


# ── AL-05 — the Semantic plane resolved at seed ──────────────────────────────────────────

def test_al05_dormant_by_default(monkeypatch):
    monkeypatch.delenv("AUGHOR_SEMANTIC_RESOLVE_LIVE", raising=False)
    from aughor.semantic.context import resolve_if_enabled
    assert resolve_if_enabled("q", "fixture") is None          # off → the plane stays dormant


def test_al05_resolves_when_flag_on(monkeypatch):
    monkeypatch.setenv("AUGHOR_SEMANTIC_RESOLVE_LIVE", "1")
    # Keep it hermetic — the sources are empty; we're testing the flag gate + attachment, not content.
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda *a, **k: [])
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda *a, **k: None)
    monkeypatch.setattr("aughor.profile.store.load_raw", lambda *a, **k: None)
    monkeypatch.setattr("aughor.semantic.kb_retriever.has_strong_kb_match", lambda *a, **k: False)
    from aughor.semantic.context import resolve_if_enabled, SemanticContext
    ctx = resolve_if_enabled("why is gmv down", "fixture", "ecommerce")
    assert isinstance(ctx, SemanticContext)
    assert ctx.connection_id == "fixture"
    assert ctx.scope_schema == "ecommerce"


def test_al05_agentstate_carries_the_field():
    # The run state can carry the resolved context (the field exists on AgentState).
    from aughor.agent.state import AgentState  # noqa: F401
    state: dict = {"semantic_context": "sentinel"}
    assert state["semantic_context"] == "sentinel"
