"""Arc FA, FA-7 — any SDK can call an agent: the grounding read (`agents.grounding_read`, off).

What a custom agent would read for a question, read without asking a model, at two doors — the agent's HTTP door with
its key and the read-level MCP tool `ground_agent` over the session route, where the agent gate holds and audits it.

Measured before it was built: the only caller of the grounding receipt (`GET /ask/context`) was the chat's receipt; no
door and no MCP tool reached it, and nothing rendered an agent's grants or guardrails. Off, both doors are 404 and the
tool is not listed; on, a read carries every block's content with the agent's scope applied, every absent block with
why, whether the embedder was called (counted at the backend, here a fake client), and one journal entry that never
holds the question or the content. No test here reaches a network or a model: the embedding backend is a fake client,
the warehouse a DuckDB file in the test's own directory, and a chat model's construction is recorded and refused.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from aughor.custom_agents import create_agent, delete_agent, list_agents
from aughor.custom_agents.keys import issue_agent_key, revoke_agent_key

QUESTION = "What was the zebra revenue in March?"         # a word no fixture holds, to grep the journal for


# ── fixtures ────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean():
    yield
    for a in list_agents():
        revoke_agent_key(a.id)
        delete_agent(a.id)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("AUGHOR_AGENTS_GROUNDING_READ", "1")


@pytest.fixture
def warehouse(tmp_path):
    """A connection over a DuckDB file of the test's own, with one table — a warehouse read with no network."""
    import duckdb

    from aughor.db import registry
    path = tmp_path / "fa7.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE orders (order_id INTEGER, amount DOUBLE, placed_at DATE)")
    con.execute("INSERT INTO orders VALUES (1, 10.0, DATE '2026-03-01')")
    con.close()
    conn_id = registry.add_connection("fa7-warehouse", "duckdb", str(path))
    yield conn_id
    registry.delete_connection(conn_id)


class _FakeEmbeddings:
    def __init__(self, seen: list):
        self.seen = seen

    def create(self, *, model, input):          # noqa: A002 — the SDK's own keyword
        self.seen.append(list(input))

        class _Item:
            embedding = [0.1] * 8

        class _Resp:
            data = [_Item() for _ in input]
        return _Resp()


@pytest.fixture
def embedder(monkeypatch):
    """The embedding backend as a fake OpenAI-compatible client: every request it is sent is recorded, none leaves."""
    import openai
    seen: list = []

    class _Client:
        def __init__(self, *a, **k):
            self.embeddings = _FakeEmbeddings(seen)

    monkeypatch.setenv("AUGHOR_EMBED_BACKEND", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://embedder.invalid/v1")
    monkeypatch.setattr(openai, "OpenAI", _Client)
    return seen


@pytest.fixture
def no_chat_model(monkeypatch):
    """Any chat model constructed during a read is recorded (and refused) — the read must construct none."""
    from aughor.llm import provider
    built: list = []

    def _refuse(self, *a, **k):
        built.append((a, k))
        raise RuntimeError("a chat model was constructed during a grounding read")

    monkeypatch.setattr(provider.LLMProvider, "__init__", _refuse)
    return built


def _key(agent) -> dict:
    return {"Authorization": f"Bearer {issue_agent_key(agent.id)}"}


def _blocks(body) -> dict:
    return {b["key"]: b for b in body["receipt"]["blocks"]}


def _journal(kind: str) -> list[dict]:
    from aughor.kernel.ledger import Ledger
    return Ledger.default().events(kind=kind, limit=200)


def _payload(row: dict) -> dict:
    p = row.get("payload")
    return p if isinstance(p, dict) else json.loads(p or "{}")


def _reads_of(*agents) -> list[dict]:
    """The grounding reads journaled for these agents — the session's journal is shared by every test."""
    ids = {a.id for a in agents}
    return [r for r in _journal("agent.grounding_read") if _payload(r).get("agent") in ids]


# ── off: both doors closed, everything else as it was ──────────────────────────────────

def test_off_both_doors_are_the_404_of_a_door_that_does_not_exist(client, warehouse):
    agent = create_agent("Off", instructions="x", connection_id=warehouse)
    headers = _key(agent)
    nowhere = client.post(f"/doors/agents/{agent.id}/nowhere", json={})
    assert nowhere.status_code == 404
    for r in (client.post(f"/doors/agents/{agent.id}/grounding", json={"question": QUESTION}, headers=headers),
              client.post(f"/doors/agents/{agent.id}/grounding", json={"not": "a body"}, headers=headers),
              client.post(f"/doors/agents/{agent.id}/grounding", json={"question": QUESTION}),
              client.get(f"/agents/custom/{agent.id}/grounding", params={"question": QUESTION}),
              client.get(f"/agents/custom/{agent.id}/grounding")):
        assert (r.status_code, r.json()) == (404, nowhere.json()), r.text
    doors = client.get(f"/agents/custom/{agent.id}/doors").json()
    assert set(doors) == {"mcp", "http", "embed", "webhook", "a2a", "teams"}, "off, the Doors list is as it was"
    assert not _reads_of(agent)


def test_off_the_grounding_receipt_reads_exactly_as_before(client, warehouse, embedder, monkeypatch):
    """The watch on a failing producer is inert off: the chat's receipt says nothing it did not say before."""
    def _boom(*a, **k):
        raise RuntimeError("causal store unreadable")
    monkeypatch.setattr("aughor.lifecycle.causal.build_causal_context_section", _boom)
    body = client.get("/ask/context", params={"connection": warehouse, "question": QUESTION}).json()
    causal = {b["key"]: b for b in body["receipt"]["blocks"]}["causal"]
    assert causal["present"] is False and "note" not in causal


# ── on: the HTTP door ───────────────────────────────────────────────────────────────

def test_on_the_key_door_returns_every_block_with_content_and_each_absent_one_with_why(
        client, on, warehouse, embedder, no_chat_model, monkeypatch):
    monkeypatch.setattr("aughor.agent.grounding.connection_glossary",
                        lambda q, c: "GLOSSARY — revenue: SUM(amount) of placed orders")
    agent = create_agent("Revenue desk", instructions="Answer in euros.", connection_id=warehouse,
                         tool_grants=["flag_order_for_review"])
    r = client.post(f"/doors/agents/{agent.id}/grounding", json={"question": QUESTION, "asker": "sdk@example.com"},
                    headers=_key(agent))
    assert r.status_code == 200, r.text
    body = r.json()
    blocks = _blocks(body)
    from aughor.custom_agents.grounding_read import ABSENT_WHY
    assert set(blocks) == set(ABSENT_WHY), "every block the receipt carries has its sentence, and none is invented"
    assert "Answer in euros." in blocks["agent_brief"]["content"], "the agent is active: its brief is read"
    assert "SUM(amount)" in blocks["glossary"]["content"]
    assert "orders" in blocks["schema_slice"]["content"], "the warehouse's schema is read and linked"
    for b in blocks.values():
        assert b["present"] == bool(b["content"])
        assert b["present"] or b["why"], f"{b['key']} is absent and does not say why"
    assert body["receipt"]["present_count"] + body["receipt"]["absent_count"] == len(blocks)
    assert body["answer_stamp"] == {"id": agent.id, "name": "Revenue desk", "rev": agent.config_rev}
    assert body["connection_id"] == warehouse and body["chat_model_called"] is False
    assert "not the prompt byte for byte" in body["differs_from_answer"]
    scope = body["agent_scope"]
    assert scope["in_prompt"] is False and scope["tool_grants"] == ["flag_order_for_review"]
    assert scope["guardrails"] == {"pii": "redact", "max_tokens_per_run": None} and scope["guardrails_are_default"]
    assert not no_chat_model, "a chat model was constructed during the read"


def test_on_the_doors_tab_lists_the_grounding_door_with_its_state(client, on, warehouse):
    agent = create_agent("Listed", instructions="x", connection_id=warehouse)
    before = client.get(f"/agents/custom/{agent.id}/doors").json()["grounding"]
    assert before["state"] == "needs the HTTP key" and before["tool"] == "ground_agent"
    assert before["url"].endswith(f"/doors/agents/{agent.id}/grounding")
    _key(agent)
    assert client.get(f"/agents/custom/{agent.id}/doors").json()["grounding"]["state"] == "open"


def test_the_key_is_the_door_a_wrong_one_and_an_unknown_agent_look_the_same(client, on, warehouse):
    agent = create_agent("Keyed", instructions="x", connection_id=warehouse)
    _key(agent)
    for agent_id, headers in ((agent.id, {}), (agent.id, {"Authorization": "Bearer wrong"}),
                              ("ua_nobody", {"Authorization": "Bearer wrong"})):
        r = client.post(f"/doors/agents/{agent_id}/grounding", json={"question": QUESTION}, headers=headers)
        assert r.status_code == 401, r.text


# ── the agent's scope ────────────────────────────────────────────────────────────────

def test_documents_are_the_agents_own_and_an_agent_with_none_reads_none(client, on, warehouse, embedder, monkeypatch):
    hits = [{"doc_id": "doc_mine", "chunk_index": 0, "title": "Pricing policy", "filename": "pricing.md",
             "text": "MINE: list prices are set quarterly.", "score": 0.9},
            {"doc_id": "doc_theirs", "chunk_index": 0, "title": "Payroll", "filename": "payroll.md",
             "text": "THEIRS: salaries by person.", "score": 0.95}]
    monkeypatch.setattr("aughor.knowledge.indexer.search_documents", lambda q, top_k=4, connection_id=None: list(hits))
    scoped = create_agent("Scoped", instructions="x", connection_id=warehouse, doc_ids=["doc_mine"])
    docs = _blocks(client.post(f"/doors/agents/{scoped.id}/grounding", json={"question": QUESTION},
                               headers=_key(scoped)).json())["docs"]
    assert "MINE" in docs["content"] and "THEIRS" not in docs["content"]
    bare = create_agent("Bare", instructions="x", connection_id=warehouse)
    docs = _blocks(client.post(f"/doors/agents/{bare.id}/grounding", json={"question": QUESTION},
                               headers=_key(bare)).json())["docs"]
    assert docs["present"] is False and "no documents of its own" in docs["why"]


def test_the_agents_binding_holds_as_the_ask_door_holds_it(client, on, warehouse):
    bound = create_agent("Bound", instructions="x", connection_id=warehouse, schema_scope="main")
    r = client.post(f"/doors/agents/{bound.id}/grounding", json={"question": QUESTION, "connection_id": "elsewhere"},
                    headers=_key(bound))
    assert r.status_code == 409 and "is bound to connection" in r.json()["detail"]
    r = client.post(f"/doors/agents/{bound.id}/grounding", json={"question": QUESTION, "schema": "other"},
                    headers=_key(bound))
    assert r.status_code == 409 and "is scoped to schema" in r.json()["detail"]
    r = client.post(f"/doors/agents/{bound.id}/grounding", json={"question": QUESTION}, headers=_key(bound))
    assert r.status_code == 200 and r.json()["schema"] == "main"
    unbound = create_agent("Unbound", instructions="x")
    r = client.post(f"/doors/agents/{unbound.id}/grounding", json={"question": QUESTION}, headers=_key(unbound))
    assert r.status_code == 422 and "bound to no connection" in r.json()["detail"]


def test_a_paused_agent_reads_nothing_and_says_so(client, on, warehouse):
    from aughor.custom_agents import update_agent
    agent = create_agent("Paused", instructions="x", connection_id=warehouse)
    headers = _key(agent)
    update_agent(agent.id, enabled=False)
    r = client.post(f"/doors/agents/{agent.id}/grounding", json={"question": QUESTION}, headers=headers)
    assert r.status_code == 409 and "paused" in r.json()["detail"]
    r = client.get(f"/agents/custom/{agent.id}/grounding", params={"question": QUESTION})
    assert r.status_code == 409 and "paused" in r.json()["detail"]


# ── withheld is said ─────────────────────────────────────────────────────────────────

def test_a_block_whose_producer_failed_says_so_instead_of_reading_as_empty(client, on, warehouse, embedder,
                                                                            monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("causal store unreadable")
    monkeypatch.setattr("aughor.lifecycle.causal.build_causal_context_section", _boom)
    agent = create_agent("Failing", instructions="x", connection_id=warehouse)
    causal = _blocks(client.post(f"/doors/agents/{agent.id}/grounding", json={"question": QUESTION},
                                 headers=_key(agent)).json())["causal"]
    assert causal["present"] is False and "could not be produced (RuntimeError)" in causal["why"]


def test_a_search_the_embedder_failed_is_not_read_as_nothing_matched(client, on, warehouse, monkeypatch):
    """Measured on a scratch drive: with the embedder down, the planning-pattern retriever swallowed the failure and
    returned "", which read as "no pattern matched". The embedder's own failure count says which block it was."""
    import openai

    class _Down:
        def __init__(self, *a, **k):
            self.embeddings = self

        def create(self, **k):
            raise ConnectionError("the embedding service did not answer")

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://embedder.invalid/v1")
    monkeypatch.setattr(openai, "OpenAI", _Down)

    def _swallowing(q, c=""):
        from aughor.semantic.embedder import embed_one
        try:
            embed_one(q)
        except ConnectionError:
            return ""                               # what a retriever that swallows its failure returns
        return "PATTERN"
    monkeypatch.setattr("aughor.agent.grounding.kb_patterns", _swallowing)
    agent = create_agent("Embedder down", instructions="x", connection_id=warehouse)
    body = client.post(f"/doors/agents/{agent.id}/grounding", json={"question": QUESTION}, headers=_key(agent)).json()
    assert "the embedder failed" in _blocks(body)["kb_patterns"]["why"]
    assert body["embedder"]["failed"] >= 1 and body["embedder"]["called"] is True


def test_an_unopenable_connection_is_said_on_the_schema_blocks_never_a_500(client, on, monkeypatch, tmp_path):
    from aughor.db import registry
    conn_id = registry.add_connection("fa7-missing", "duckdb", str(tmp_path / "absent.duckdb"))
    try:
        agent = create_agent("Unreachable", instructions="x", connection_id=conn_id)
        r = client.post(f"/doors/agents/{agent.id}/grounding", json={"question": QUESTION}, headers=_key(agent))
        assert r.status_code == 200, r.text
        blocks = _blocks(r.json())
        for key in ("schema_slice", "governed_metrics"):
            assert "could not be opened" in blocks[key]["why"] and "not computed" in blocks[key]["why"]
    finally:
        registry.delete_connection(conn_id)


# ── the embedder, said ────────────────────────────────────────────────────────────────

def test_the_embedder_is_said_as_the_backend_saw_it(client, on, warehouse, embedder, monkeypatch):
    def _patterns(q, c=""):
        from aughor.semantic.embedder import embed_one
        embed_one(q)                                 # the planning-pattern retriever embeds the question
        return "PATTERN — revenue by month"
    monkeypatch.setattr("aughor.agent.grounding.kb_patterns", _patterns)
    agent = create_agent("Embeds", instructions="x", connection_id=warehouse)
    body = client.post(f"/doors/agents/{agent.id}/grounding", json={"question": QUESTION}, headers=_key(agent)).json()
    said = body["embedder"]
    assert said["called"] is True and said["requests"] == len(embedder) >= 1, (said, len(embedder))
    assert said["backend"] == "ollama" and said["hosted"] is False and "note" not in said


def test_an_embedder_never_called_is_said_as_not_called(client, on, warehouse, embedder, monkeypatch):
    for name in ("connection_glossary", "kb_patterns", "external_docs", "trusted_templates", "correction_priors"):
        monkeypatch.setattr(f"aughor.agent.grounding.{name}", lambda *a, **k: "")
    monkeypatch.setattr("aughor.agent.grounding.sql_examples", lambda q, c: ("", ""))
    agent = create_agent("Quiet", instructions="x", connection_id=warehouse)
    said = client.post(f"/doors/agents/{agent.id}/grounding", json={"question": QUESTION},
                       headers=_key(agent)).json()["embedder"]
    assert said["called"] is (len(embedder) > 0) and said["requests"] == len(embedder)


def test_a_hosted_embedder_says_it_may_charge(client, on, warehouse, embedder, monkeypatch):
    def _patterns(q, c=""):
        from aughor.semantic.embedder import embed_one
        embed_one(q)
        return ""
    monkeypatch.setattr("aughor.agent.grounding.kb_patterns", _patterns)
    monkeypatch.setattr("aughor.semantic.embedder.describe_backend",
                        lambda: {"backend": "openrouter", "model": "some-embedder", "hosted": True})
    agent = create_agent("Hosted", instructions="x", connection_id=warehouse)
    said = client.post(f"/doors/agents/{agent.id}/grounding", json={"question": QUESTION},
                       headers=_key(agent)).json()["embedder"]
    assert said["hosted"] is True and "may charge" in said["note"]


def test_the_embedder_tally_is_inert_outside_a_read_and_counts_failures_inside(embedder, monkeypatch):
    from aughor.semantic import embedder as E
    assert E.embed(["a"]) == [[0.1] * 8]           # no tally: an embedding is made exactly as before
    with E.tally_calls() as tally:
        E.embed(["a", "b"])
        monkeypatch.setattr(E, "endpoint", lambda: (_ for _ in ()).throw(E.EmbeddingConfigError("no key")))
        with pytest.raises(E.EmbeddingConfigError):
            E.embed(["c"])
    assert tally == {"requests": 1, "texts": 2, "failed": 1}
    monkeypatch.setenv("AUGHOR_EMBED_BACKEND", "nonsense")
    assert E.describe_backend()["unconfigured"] and E.describe_backend()["hosted"] is None


# ── the journal ───────────────────────────────────────────────────────────────────────

def test_each_read_is_journaled_once_with_who_and_what_and_never_the_content(client, on, warehouse, embedder,
                                                                             monkeypatch):
    monkeypatch.setattr("aughor.agent.grounding.connection_glossary",
                        lambda q, c: "GLOSSARY — zebra revenue is SECRET-DEFINITION")
    agent = create_agent("Journaled", instructions="Speak plainly.", connection_id=warehouse)
    body = client.post(f"/doors/agents/{agent.id}/grounding", json={"question": QUESTION, "asker": "sdk@example.com"},
                       headers=_key(agent)).json()
    assert body["journal"] == {"kind": "agent.grounding_read", "recorded": True}
    rows = _reads_of(agent)
    assert len(rows) == 1
    payload = _payload(rows[0])
    assert payload["principal"] == "api:http:sdk@example.com" and payload["door"] == "http"
    assert payload["agent"] == agent.id and payload["rev"] == agent.config_rev
    assert payload["connection_id"] == warehouse and "glossary" in payload["present"]
    text = json.dumps(rows[0])
    for leaked in ("zebra", "SECRET-DEFINITION", "Speak plainly"):
        assert leaked not in text, f"the journal carries the read's {leaked!r}"
    from aughor.govern.audit_categories import feed
    seen = [e for e in feed(category="data_access") if e.kind == "agent.grounding_read"]
    assert seen and "read what agent" in seen[0].summary and seen[0].actor == "api:http:sdk@example.com"


# ── the session route: the MCP tool's door ─────────────────────────────────────────────

def test_the_mcp_clients_call_is_a_read_the_agent_gate_audits(client, on, warehouse, embedder):
    from aughor.mcp.client import AGENT_HEADER, AGENT_MARK, TOOL_HEADER
    from aughor.orgsettings import agent_policy as AP
    agent = create_agent("Over MCP", instructions="x", connection_id=warehouse)
    AP.save_agent_policy("default", level="read", set_by="ana")
    try:
        r = client.get(f"/agents/custom/{agent.id}/grounding", params={"question": QUESTION, "asker": "claude-desktop"},
                       headers={AGENT_HEADER: AGENT_MARK, TOOL_HEADER: "ground_agent"})
    finally:
        AP.clear_agent_policy("default")
    assert r.status_code == 200, r.text
    calls = [_payload(e) for e in _journal("mcp.tool_call") if _payload(e).get("tool") == "ground_agent"
             and "claude-desktop" in json.dumps(_payload(e).get("args"))]
    assert calls and calls[0]["allowed"] is True and calls[0]["required_level"] == "read"
    read = _payload(_reads_of(agent)[0])
    assert read["door"] == "mcp" and read["principal"] == "api:mcp:claude-desktop"


# ── with identity on: whose agent, whose connection ─────────────────────────────────────

def test_with_identity_on_another_organisations_connection_is_refused_at_both_doors(client, on, monkeypatch,
                                                                                    tmp_path):
    import duckdb

    from aughor.db import registry
    from aughor.org.context import using_org
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    duckdb.connect(str(tmp_path / "orgA.duckdb")).close()
    with using_org("orgA"):
        theirs = registry.add_connection("fa7-orgA", "duckdb", str(tmp_path / "orgA.duckdb"))
    try:
        mine = create_agent("Org B's", instructions="x", owner="orgB")
        r = client.post(f"/doors/agents/{mine.id}/grounding", json={"question": QUESTION, "connection_id": theirs},
                        headers=_key(mine))
        assert r.status_code == 403 and "belongs to another org" in r.text
        bound_there = create_agent("Bound to org A", instructions="x", connection_id=theirs)
        r = client.get(f"/agents/custom/{bound_there.id}/grounding", params={"question": QUESTION},
                       headers={"X-Aughor-Org": "orgB"})
        assert r.status_code == 403 and "belongs to another org" in r.text, "the agent's own binding is checked too"
        r = client.get(f"/agents/custom/{mine.id}/grounding", params={"question": QUESTION, "connection_id": theirs},
                       headers={"X-Aughor-Org": "orgB"})
        assert r.status_code == 403, "the named connection is refused by the owner guard"
        owned_by_a = create_agent("Org A's", instructions="x", owner="orgA", connection_id=theirs)
        r = client.get(f"/agents/custom/{owned_by_a.id}/grounding", params={"question": QUESTION},
                       headers={"X-Aughor-Org": "orgB"})
        assert r.status_code == 404, "another organisation's agent is no agent to this reader"
        assert not _reads_of(mine, bound_there, owned_by_a), "a refused read is not journaled as a read"
    finally:
        registry.delete_connection(theirs)


# ── the MCP tool: a read, listed only while the flag is on ──────────────────────────────

class _Api:
    def __init__(self, open_: bool):
        self.open = open_
        self.calls: list = []

    async def grounding_read_open(self):
        return self.open

    async def list_user_agents(self):
        return [{"id": "ua_1", "name": "Revenue desk", "enabled": True}]

    async def list_spotlight_tools(self):
        return []

    async def list_automation_tools(self):
        return []

    async def ground_agent(self, agent_id, question, *, connection=None, asker=""):
        self.calls.append((agent_id, question, connection))
        return {"answer_stamp": {"id": agent_id}}

    async def agent_policy(self):
        return {"effective": {"level": "read"}}


def test_the_tool_is_a_read_absent_while_off_and_listed_and_removed_live(monkeypatch):
    from aughor.mcp import policy as P
    from aughor.mcp import server as srv
    api = _Api(open_=False)
    monkeypatch.setattr(srv, "mcp", srv.PolicedFastMCP("t"))
    monkeypatch.setattr(srv, "_client", api)
    monkeypatch.setattr(srv, "_DYNAMIC", {})
    monkeypatch.setattr(srv, "_LIVE_SOURCES", set())
    monkeypatch.setattr(srv, "_live_checked", [])
    monkeypatch.setattr(P, "DYNAMIC_LEVELS", {})
    monkeypatch.setattr(P, "DYNAMIC_AREAS", {})
    srv.forget_policy()

    async def run():
        assert await srv.register_grounding_tool(api) == []
        assert "ground_agent" not in {t.name for t in await srv.mcp.list_tools()}, "off: the tool is not listed"
        api.open = True
        assert await srv.register_grounding_tool(api) == ["ground_agent"]
        assert P.tool_level("ground_agent") == "read" and P.tool_area("ground_agent") == "catalog:read"
        listed = {t.name: t for t in await srv.mcp.list_tools()}
        assert listed["ground_agent"].annotations.readOnlyHint is True, "a read policy lists it, marked read-only"
        out = await srv.mcp.call_tool("ground_agent", {"agent": "ask_revenue_desk", "question": QUESTION})
        assert api.calls == [("ua_1", QUESTION, None)], "named by its ask_ tool, read by its id"
        assert out
        srv.enable_live_tools("grounding")
        api.open = False
        srv._live_checked.clear()
        assert await srv.refresh_live_tools(api) is True
        assert "ground_agent" not in {t.name for t in await srv.mcp.list_tools()}, "turned off, it leaves the list"

    asyncio.run(run())


def test_the_static_tool_list_is_unchanged():
    """The tool is registered live, never at import: the static roster and its level map stay equal."""
    from aughor.mcp import policy as P
    from aughor.mcp import server as srv
    assert "ground_agent" not in P.TOOL_LEVELS and "ground_agent" not in set(srv.mcp._tool_manager._tools)
