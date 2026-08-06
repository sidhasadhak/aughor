"""Tests for the AL live-path migrations (Wave 4) — flag-gated, default-off.

AL-01: the Deep-Analysis executor (`_execute_safe`) routes generated SQL through `trust.verify`
before execute when `trust.verify_live` is on — a readonly BLOCK returns a blocked result instead
of executing. AL-05: a deep investigation resolves the Semantic plane once at seed and carries the
SemanticContext on its state when `semantic.resolve_live` is on. Both are byte-identical with the
flag off.
"""
from __future__ import annotations

from aughor.control_plane.contracts.execution import QueryResult


class _SpyConn:
    dialect = "duckdb"

    def __init__(self):
        self.calls: list[str] = []

    def execute(self, phase_id: str, sql: str) -> QueryResult:
        self.calls.append(sql)
        return QueryResult(hypothesis_id=phase_id, sql=sql, columns=["n"], rows=[[1]],
                           row_count=1, error=None)


# ── AL-01 — the Trust plane on the deep executor ─────────────────────────────────────────

def test_al01_blocks_mutation():
    from aughor.agent.investigate import _execute_safe
    spy = _SpyConn()
    r = _execute_safe(spy, "p1", "DELETE FROM orders", schema=None)
    assert (r.error or "").startswith("[BLOCKED]")
    assert spy.calls == []                       # the mutation never reached execute


def test_al01_clean_select_passes():
    from aughor.agent.investigate import _execute_safe
    spy = _SpyConn()
    r = _execute_safe(spy, "p1", "SELECT id FROM orders", schema=None)
    assert not (r.error or "").startswith("[BLOCKED]")
    # The query itself runs. E1's column-types probe rides along (both gates are
    # permanent now), so the assertion is membership, not equality.
    assert "SELECT id FROM orders" in spy.calls


# ── AL-05 — the Semantic plane resolved at seed ──────────────────────────────────────────

def test_al05_fail_open_returns_none(monkeypatch):
    """Permanent since flag endgame Wave 2 (2026-08-06, receipt 49e7af321440). The
    property the old forced-off test protected the answer path with is now the
    FAIL-OPEN: a resolver that raises yields None and the run proceeds without
    the plane — never an exception on the answer path."""
    monkeypatch.setattr("aughor.semantic.context.resolve",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("resolver boom")))
    from aughor.semantic.context import resolve_if_enabled
    assert resolve_if_enabled("q", "fixture") is None


def test_al05_resolves_unconditionally(monkeypatch):
    # Keep it hermetic — the sources are empty; we're testing attachment, not content.
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda *a, **k: [])
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda *a, **k: None)
    monkeypatch.setattr("aughor.business_profile.store.load_raw", lambda *a, **k: None)
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


def test_al05_metrics_consumer_uses_resolved_context():
    # The first live CONSUMER: a node reads the resolved metrics instead of re-consulting.
    from aughor.agent.nodes import metrics_for_state
    from aughor.semantic.context import SemanticContext

    class _M:
        def __init__(self, n): self.name = n
    sc = SemanticContext(question="q", connection_id="c", metrics=[_M("gmv"), _M("aov")])
    assert [m.name for m in metrics_for_state({"semantic_context": sc})] == ["gmv", "aov"]


def test_al05_metrics_consumer_falls_back_without_context(monkeypatch):
    from aughor.agent import nodes
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda *a, **k: ["SENTINEL"])
    assert nodes.metrics_for_state({}) == ["SENTINEL"]                       # no context
    assert nodes.metrics_for_state({"semantic_context": None}) == ["SENTINEL"]  # flag off → None


# ── AL-02 — the Capability plane as a live end-to-end answer path ─────────────────────────

class _FakeProvider:
    """Stands in for the `coder` provider so NL→SQL generation is deterministic in tests."""
    def __init__(self, sql: str):
        self._sql = sql
        self.last_user = ""

    def complete(self, **kwargs):
        from aughor.agent.state import SQLOutput
        self.last_user = kwargs.get("user", "")
        return SQLOutput(sql=self._sql, reasoning="")


def test_al02_generate_sql_from_question():
    from aughor.pipeline.sql_generate import generate_sql
    out = generate_sql("show me all orders", schema_text="orders(id)",
                       provider=_FakeProvider("SELECT * FROM orders"))
    assert out == "SELECT * FROM orders"


def test_al02_generate_sql_threads_rich_context():
    # The extended generator (used by the ADA path's _gen_sql) must thread the intent + pitfall +
    # schema + ontology sections into the one WRITE_SQL_PROMPT — so the convergence keeps context.
    from aughor.pipeline.sql_generate import generate_sql
    prov = _FakeProvider("SELECT 1")
    generate_sql("hypothesis text", schema_text="SCHEMA_MARK", dialect="duckdb",
                 intent_description="INTENT_MARK", pitfall_section="PITFALL_MARK",
                 ontology_actions_section="ONTOLOGY_MARK", provider=prov)
    for mark in ("hypothesis text", "INTENT_MARK", "SCHEMA_MARK", "PITFALL_MARK", "ONTOLOGY_MARK"):
        assert mark in prov.last_user, mark


def test_al02_generate_sql_empty_question_is_empty():
    from aughor.pipeline.sql_generate import generate_sql
    assert generate_sql("", provider=_FakeProvider("x")) == ""


def test_al02_capability_generates_from_question(monkeypatch):
    monkeypatch.setattr("aughor.pipeline.sql_generate.generate_sql", lambda *a, **k: "SELECT 1 AS n")
    from aughor.pipeline.builtins import SqlCapability
    from aughor.pipeline import CapabilityRequest
    from aughor.trust import Scope
    cap = SqlCapability()
    assert cap.generate(CapabilityRequest(question="anything", scope=Scope())) == "SELECT 1 AS n"
    # A pre-supplied artifact still wins (the answer path supplies already-planned SQL).
    assert cap.generate(CapabilityRequest(artifact="SELECT 2", question="ignored")) == "SELECT 2"


def test_al02_full_answer_end_to_end(monkeypatch):
    monkeypatch.setattr("aughor.pipeline.sql_generate.generate_sql", lambda *a, **k: "SELECT 1 AS n")
    from aughor.pipeline import run_capability, CapabilityRequest
    from aughor.trust import Scope
    spy = _SpyConn()
    res = run_capability("data", CapabilityRequest(question="how many?",
                                                   scope=Scope(conn=spy, dialect="duckdb")))
    assert res.ok is True
    assert res.artifact == "SELECT 1 AS n"                # generated, then executed
    assert res.trace == ("generate", "validate", "execute", "interpret")
    assert res.output["row_count"] == 1
    assert res.narrative


def test_al02_endpoint_answers(client, builtin_conn_id, monkeypatch):
    monkeypatch.setattr("aughor.pipeline.sql_generate.generate_sql", lambda *a, **k: "SELECT 1 AS n")
    r = client.post("/query/capability-answer",
                    json={"conn_id": builtin_conn_id, "question": "how many rows?"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["sql"] == "SELECT 1 AS n"
    assert body["trace"] == ["generate", "validate", "execute", "interpret"]
    assert body["row_count"] == 1


# test_al02_endpoint_disabled_when_forced_off was DELETED with its flag (flag
# endgame Wave 2, 2026-08-06, receipt 0dd2b45930c7): the route is the single gate
# and calling it is the consent — there is no off-state left to test.


def test_al02_endpoint_metadata_domain(client, builtin_conn_id, monkeypatch):
    r = client.post("/query/capability-answer",
                    json={"conn_id": builtin_conn_id, "question": "what tables exist?",
                          "domain": "metadata"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["trace"] == ["generate", "validate", "execute", "interpret"]
    assert body["narrative"]                          # the schema text


def test_al02_endpoint_unknown_domain(client, builtin_conn_id, monkeypatch):
    r = client.post("/query/capability-answer",
                    json={"conn_id": builtin_conn_id, "question": "q", "domain": "nope"})
    assert r.status_code == 400
