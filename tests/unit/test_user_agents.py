"""
User-defined agents (flag `agents.user_defined`) — slice 1.

Covers: the store CRUD (against the conftest-redirected AUGHOR_AGENTS_DB), the
contextvar seams (prompt brief + document scope, incl. the fail-closed
no-documents semantics), the indexer's agent-scoped retrieval, the /agents/custom
CRUD routes (404 when the flag is off), and /ask's agent resolution rules.
No live LLM anywhere.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from aughor.user_agents import (
    create_agent, delete_agent, get_agent, list_agents, update_agent,
)
from aughor.user_agents.context import (
    activate_agent, agent_brief_block, agent_doc_ids, current_agent, release_agent,
)


@pytest.fixture(autouse=True)
def _clean_store():
    yield
    for a in list_agents():
        delete_agent(a.id)


def _flag(monkeypatch, value: bool):
    import aughor.kernel.flags as flags
    monkeypatch.setattr(
        flags, "flag_enabled",
        lambda name: value if name == "agents.user_defined" else False,
    )


# ── Store ─────────────────────────────────────────────────────────────────────

def test_store_crud_roundtrip():
    a = create_agent("Churn Analyst", instructions="Focus on churn.",
                     connection_id="conn-1", doc_ids=["d1", "d2"], owner="org-x")
    assert a.id.startswith("ua_") and a.enabled
    got = get_agent(a.id)
    assert got is not None and got.name == "Churn Analyst" and got.doc_ids == ["d1", "d2"]
    assert any(x.id == a.id for x in list_agents())

    updated = update_agent(a.id, instructions="Focus on retention.", enabled=False)
    assert updated.instructions == "Focus on retention."
    assert updated.enabled is False
    assert updated.doc_ids == ["d1", "d2"]  # untouched fields survive
    assert updated.updated_at >= a.updated_at

    assert delete_agent(a.id) is True
    assert get_agent(a.id) is None
    assert delete_agent(a.id) is False


def test_update_missing_agent_returns_none():
    assert update_agent("ua_nope", name="x") is None


# ── Context seams ─────────────────────────────────────────────────────────────

def test_brief_block_active_and_inactive():
    assert agent_brief_block() == ""  # no agent → inert
    a = create_agent("Fin Agent", instructions="Prefer EUR. Cite periods.")
    token = activate_agent(a)
    try:
        brief = agent_brief_block()
        assert "Fin Agent" in brief and "Prefer EUR" in brief
        assert current_agent().id == a.id
    finally:
        release_agent(token)
    assert agent_brief_block() == ""


def test_brief_block_empty_instructions_is_inert():
    a = create_agent("Blank", instructions="   ")
    token = activate_agent(a)
    try:
        assert agent_brief_block() == ""
    finally:
        release_agent(token)


def test_doc_ids_semantics():
    assert agent_doc_ids() is None  # no agent → unrestricted
    a = create_agent("Doc Agent", doc_ids=["d1"])
    token = activate_agent(a)
    try:
        assert agent_doc_ids() == {"d1"}
    finally:
        release_agent(token)
    b = create_agent("No-doc Agent")
    token = activate_agent(b)
    try:
        assert agent_doc_ids() == set()  # agent with no docs → fail-closed empty
    finally:
        release_agent(token)


# ── Indexer scoping ───────────────────────────────────────────────────────────

def test_external_context_scoped_to_agent_docs(monkeypatch):
    import aughor.knowledge.indexer as idx
    hits = [
        {"text": "alpha", "filename": "a.pdf", "title": "A", "doc_id": "d1", "score": 0.9},
        {"text": "beta", "filename": "b.pdf", "title": "B", "doc_id": "d2", "score": 0.8},
    ]
    monkeypatch.setattr(idx, "search_documents", lambda q, top_k=4: hits)

    # No agent → global behavior, both docs, global header.
    s = idx.build_external_context_section("q")
    assert "EXTERNAL CONTEXT" in s and "alpha" in s and "beta" in s

    # Agent bound to d2 only → beta only, agent header.
    a = create_agent("Scoped", doc_ids=["d2"])
    token = activate_agent(a)
    try:
        s = idx.build_external_context_section("q")
        assert "AGENT DOCUMENTS" in s and "beta" in s and "alpha" not in s
    finally:
        release_agent(token)

    # Agent with no docs → nothing, and search is never called.
    b = create_agent("Empty")
    monkeypatch.setattr(idx, "search_documents",
                        lambda q, top_k=4: pytest.fail("must not search"))
    token = activate_agent(b)
    try:
        assert idx.build_external_context_section("q") == ""
    finally:
        release_agent(token)


# ── Routes ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


def test_routes_404_when_flag_off(client, monkeypatch):
    _flag(monkeypatch, False)
    assert client.get("/agents/custom").status_code == 404
    assert client.post("/agents/custom", json={"name": "x"}).status_code == 404


def test_routes_crud_roundtrip(client, monkeypatch):
    _flag(monkeypatch, True)
    r = client.post("/agents/custom", json={
        "name": "Churn Analyst", "instructions": "Focus on churn.",
    })
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]

    assert any(a["id"] == agent_id for a in client.get("/agents/custom").json())
    assert client.get(f"/agents/custom/{agent_id}").json()["name"] == "Churn Analyst"

    r = client.patch(f"/agents/custom/{agent_id}", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False

    assert client.delete(f"/agents/custom/{agent_id}").status_code == 200
    assert client.get(f"/agents/custom/{agent_id}").status_code == 404


def test_route_validation(client, monkeypatch):
    _flag(monkeypatch, True)
    assert client.post("/agents/custom", json={"name": "  "}).status_code == 422
    assert client.post("/agents/custom",
                       json={"name": "x", "instructions": "y" * 9000}).status_code == 422
    assert client.post("/agents/custom",
                       json={"name": "x", "connection_id": "conn-does-not-exist"}
                       ).status_code == 422
    assert client.post("/agents/custom",
                       json={"name": "x", "doc_ids": ["doc-does-not-exist"]}
                       ).status_code == 422
    # A known document passes validation.
    import aughor.knowledge.indexer as idx
    monkeypatch.setattr(idx, "get_document", lambda d: {"doc_id": d})
    r = client.post("/agents/custom", json={"name": "x", "doc_ids": ["d-ok"]})
    assert r.status_code == 201


# ── /ask agent resolution ─────────────────────────────────────────────────────

def _ask_req(**over):
    from aughor.routers.investigations import AskRequest
    return AskRequest(question="q", **over)


def test_resolve_ask_agent_rules(monkeypatch):
    from aughor.routers.investigations import _resolve_ask_agent

    assert _resolve_ask_agent(_ask_req()) is None  # no agent_id → None, flag irrelevant

    _flag(monkeypatch, False)
    with pytest.raises(HTTPException) as e:
        _resolve_ask_agent(_ask_req(agent_id="ua_x"))
    assert e.value.status_code == 404  # flag off

    _flag(monkeypatch, True)
    with pytest.raises(HTTPException) as e:
        _resolve_ask_agent(_ask_req(agent_id="ua_missing"))
    assert e.value.status_code == 404  # unknown id

    a = create_agent("Off Agent")
    update_agent(a.id, enabled=False)
    with pytest.raises(HTTPException) as e:
        _resolve_ask_agent(_ask_req(agent_id=a.id))
    assert e.value.status_code == 409  # disabled

    b = create_agent("On Agent", connection_id="conn-b")
    resolved = _resolve_ask_agent(_ask_req(agent_id=b.id))
    assert resolved.id == b.id


@pytest.mark.anyio
async def test_stream_as_agent_activates_and_releases():
    from aughor.routers.investigations import _stream_as_agent
    a = create_agent("Ctx Agent", instructions="be brief")
    seen = {}

    async def _inner():
        seen["during"] = current_agent()
        yield "data: x\n\n"

    events = [e async for e in _stream_as_agent(a, _inner())]
    assert any('"agent"' in e or "agent" in e for e in events)  # the agent SSE receipt
    assert seen["during"].id == a.id
    assert current_agent() is None  # released after the stream


# ── Deep-path: state seeding + resume re-activation ──────────────────────────

def test_current_agent_id_for_state_seeding():
    from aughor.routers.investigations import _current_agent_id
    assert _current_agent_id() == ""
    a = create_agent("Seeded")
    token = activate_agent(a)
    try:
        assert _current_agent_id() == a.id
    finally:
        release_agent(token)


def test_read_checkpoint_values_missing_run_is_empty():
    from aughor.agent.graph import read_checkpoint_values
    assert read_checkpoint_values("inv-does-not-exist") == {}


def test_persona_for_investigation_rules(monkeypatch):
    import aughor.agent.graph as graph
    from aughor.routers.investigations import _persona_for_investigation

    a = create_agent("Deep Persona", instructions="deep focus")
    monkeypatch.setattr(graph, "read_checkpoint_values", lambda inv: {"agent_id": a.id})

    _flag(monkeypatch, False)
    assert _persona_for_investigation("inv-1") is None  # flag off → never

    _flag(monkeypatch, True)
    resolved = _persona_for_investigation("inv-1")
    assert resolved is not None and resolved.id == a.id

    update_agent(a.id, enabled=False)
    assert _persona_for_investigation("inv-1") is None  # disabled → resume without persona

    monkeypatch.setattr(graph, "read_checkpoint_values", lambda inv: {})
    assert _persona_for_investigation("inv-1") is None  # pre-upgrade checkpoint → None

    def _boom(inv):
        raise RuntimeError("checkpoint store unavailable")
    monkeypatch.setattr(graph, "read_checkpoint_values", _boom)
    assert _persona_for_investigation("inv-1") is None  # fail-open, never blocks resume


# ── Slice 4: schema scoping + pack bindings ───────────────────────────────────

def test_store_schema_scope_and_pack_ids_roundtrip():
    a = create_agent("Scoped Agent", schema_scope="finance", pack_ids=["customer-analytics"])
    got = get_agent(a.id)
    assert got.schema_scope == "finance"
    assert got.pack_ids == ["customer-analytics"]
    updated = update_agent(a.id, schema_scope="", pack_ids=[])
    assert updated.schema_scope == "" and updated.pack_ids == []


def test_agent_pack_ids_semantics():
    from aughor.user_agents.context import agent_pack_ids
    assert agent_pack_ids() == []  # no agent → no restriction
    a = create_agent("Packed", pack_ids=["p1", "p2"])
    token = activate_agent(a)
    try:
        assert agent_pack_ids() == ["p1", "p2"]
    finally:
        release_agent(token)


def test_intake_pool_restricted_to_agent_packs(monkeypatch):
    """An active agent with pack bindings restricts pack selection to ITS packs;
    the pinned-binding deploy gate is untouched (still consulted)."""
    import types

    import aughor.packs.intake as intake

    pack_a, pack_b = types.SimpleNamespace(id="pack-a"), types.SimpleNamespace(id="pack-b")
    monkeypatch.setattr(intake, "flag_enabled", lambda name: name == "specialist_packs")
    monkeypatch.setattr(intake, "active_packs", lambda packs_dir=None: [pack_a, pack_b])
    monkeypatch.setattr(intake, "select_pack", lambda q, pool: (pool[0], 1.0) if pool else None)
    monkeypatch.setattr(intake, "load_binding", lambda pid, conn, schema: {"bindings": {"t": "x"}})
    captured = {}

    def _build(pack, binding, business_model, currency_code):
        captured["pack"] = pack.id
        return types.SimpleNamespace(pack_id=pack.id)

    monkeypatch.setattr(intake, "build_injection", _build)

    # No agent → full pool, first pack wins.
    assert intake.injection_for_question("q", "conn-1").pack_id == "pack-a"

    # Agent bound to pack-b → pool restricted, pack-b steers.
    a = create_agent("Pack Agent", pack_ids=["pack-b"])
    token = activate_agent(a)
    try:
        assert intake.injection_for_question("q", "conn-1").pack_id == "pack-b"
        # The deploy gate still gates: an undeployed pack never steers.
        monkeypatch.setattr(intake, "load_binding", lambda pid, conn, schema: None)
        assert intake.injection_for_question("q", "conn-1") is None
    finally:
        release_agent(token)

    # Agent bound to a pack NOT in the active pool → nothing steers (no fallback guess).
    b = create_agent("Ghost Pack Agent", pack_ids=["pack-zzz"])
    token = activate_agent(b)
    try:
        monkeypatch.setattr(intake, "load_binding", lambda pid, conn, schema: {"bindings": {"t": "x"}})
        assert intake.injection_for_question("q", "conn-1") is None
    finally:
        release_agent(token)


def test_apply_agent_bindings_rules():
    from aughor.routers.investigations import _apply_agent_bindings

    bound = create_agent("Bound", connection_id="conn-b", schema_scope="finance")

    # Defaults bind: connection + schema adopted from the agent.
    req = _ask_req()
    assert _apply_agent_bindings(req, bound, "whatever") == "conn-b"
    assert req.schema_name == "finance"

    # Matching explicit values pass through.
    req = _ask_req(connection_id="conn-b", schema="finance")
    assert _apply_agent_bindings(req, bound, "conn-b") == "conn-b"

    # Conflicting explicit connection → 409.
    with pytest.raises(HTTPException) as e:
        _apply_agent_bindings(_ask_req(connection_id="conn-other"), bound, "conn-other")
    assert e.value.status_code == 409

    # Conflicting explicit schema → 409.
    with pytest.raises(HTTPException) as e:
        _apply_agent_bindings(_ask_req(schema="marketing"), bound, "any")
    assert e.value.status_code == 409

    # Unbound agent changes nothing.
    free = create_agent("Free")
    req = _ask_req(connection_id="conn-x", schema="s1")
    assert _apply_agent_bindings(req, free, "conn-x") == "conn-x"
    assert req.schema_name == "s1"


# ── Slice 5: measured agents (goldens + evaluation) ───────────────────────────

def test_goldens_store_roundtrip():
    from aughor.user_agents.store import add_golden, delete_golden, list_goldens
    a = create_agent("Measured")
    g = add_golden(a.id, "How many orders?", "SELECT COUNT(*) FROM orders")
    assert g["id"].startswith("ag_")
    assert [x["question"] for x in list_goldens(a.id)] == ["How many orders?"]
    assert delete_golden(g["id"]) is True
    assert list_goldens(a.id) == []
    # Deleting the agent removes its goldens too.
    add_golden(a.id, "q", "SELECT 1")
    delete_agent(a.id)
    assert list_goldens(a.id) == []


def test_results_match_semantics():
    from aughor.user_agents.quality import results_match
    assert results_match([[5]], [[5]])
    assert results_match([[5.0]], [["5"]])            # type-tolerant
    assert results_match([[1], [2]], [[2], [1]])      # order-insensitive
    assert not results_match([[5]], [[6]])
    assert not results_match([[1], [2]], [[1]])       # row-count must agree
    assert results_match([["a", 3]], [["a", 3, "extra"]])  # richer answer passes
    assert not results_match([], [[1]])


def test_evaluate_agent_stamps_result(monkeypatch):
    import duckdb as _duckdb
    import types as _types

    from aughor.user_agents.quality import evaluate_agent
    from aughor.user_agents.store import add_golden

    con = _duckdb.connect()
    con.execute("CREATE TABLE orders AS SELECT * FROM (VALUES (1), (2), (3)) t(id)")

    class _Res:
        def __init__(self, rows, error=None):
            self.rows, self.error = rows, error

    def _exec(qid, sql):
        try:
            return _Res(con.execute(sql).fetchall())
        except Exception as e:
            return _Res([], error=str(e))

    db = _types.SimpleNamespace(execute=_exec, get_schema=lambda: "orders(id)")

    a = create_agent("Measured2", instructions="count things")
    add_golden(a.id, "How many orders?", "SELECT COUNT(*) FROM orders")
    add_golden(a.id, "Max id?", "SELECT MAX(id) FROM orders")

    # A "model" that gets the first right and the second wrong.
    def _gen(question, schema):
        assert current_agent() is not None  # runs AS the agent
        return ("SELECT COUNT(*) FROM orders" if "many" in question
                else "SELECT MIN(id) FROM orders")

    result = evaluate_agent(a, db=db, generate=_gen)
    assert result["total"] == 2 and result["passed"] == 1
    assert result["per_question"][1]["error"] == "result mismatch vs reference"
    assert get_agent(a.id).last_eval["passed"] == 1  # stamped on the agent


def test_evaluate_agent_generation_failure_is_scored(monkeypatch):
    import types as _types

    from aughor.user_agents.quality import evaluate_agent
    from aughor.user_agents.store import add_golden

    db = _types.SimpleNamespace(
        execute=lambda qid, sql: _types.SimpleNamespace(rows=[[1]], error=None),
        get_schema=lambda: "t(x)")
    a = create_agent("Measured3")
    add_golden(a.id, "q", "SELECT 1")

    def _boom(question, schema):
        raise RuntimeError("model down")

    result = evaluate_agent(a, db=db, generate=_boom)
    assert result["passed"] == 0 and result["total"] == 1
    assert "model down" in result["per_question"][0]["error"]


def test_golden_routes(client, monkeypatch):
    _flag(monkeypatch, True)
    r = client.post("/agents/custom", json={"name": "Routed"})
    aid = r.json()["id"]
    # Mutating reference SQL is rejected.
    assert client.post(f"/agents/custom/{aid}/goldens",
                       json={"question": "q", "reference_sql": "DROP TABLE x"}
                       ).status_code == 422
    r = client.post(f"/agents/custom/{aid}/goldens",
                    json={"question": "q", "reference_sql": "SELECT 1"})
    assert r.status_code == 201
    gid = r.json()["id"]
    assert len(client.get(f"/agents/custom/{aid}/goldens").json()) == 1
    assert client.delete(f"/agents/custom/{aid}/goldens/{gid}").status_code == 200
    # Unknown agent 404s.
    assert client.get("/agents/custom/ua_nope/goldens").status_code == 404


# ── Observability (Agent Workspace overview) ─────────────────────────────────

def test_observability_endpoint_history_and_degradation(client, monkeypatch, tmp_path):
    """Per-agent run history surfaces from the history store; trace_stats is None
    when obs.mlflow is off (history-only — the workspace works without MLflow)."""
    _flag(monkeypatch, True)  # agents.user_defined on; obs.mlflow stays off
    from aughor.db import history
    monkeypatch.setattr(history, "_DB_PATH", str(tmp_path / "history.db"))

    aid = client.post("/agents/custom",
                      json={"name": "Churn Analyst", "instructions": "churn"}).json()["id"]

    empty = client.get(f"/agents/custom/{aid}/observability")
    assert empty.status_code == 200
    assert empty.json() == {"agent_id": aid, "run_count": 0, "runs": [], "trace_stats": None}

    history.create_investigation("why did churn spike", "conn-1", agent_id=aid)
    body = client.get(f"/agents/custom/{aid}/observability").json()
    assert body["run_count"] == 1
    assert body["runs"][0]["agent_id"] == aid
    assert body["trace_stats"] is None  # obs.mlflow off → history-only, never raises


def test_observability_404s(client, monkeypatch):
    _flag(monkeypatch, False)
    assert client.get("/agents/custom/whatever/observability").status_code == 404
    _flag(monkeypatch, True)
    assert client.get("/agents/custom/ua_nope/observability").status_code == 404
