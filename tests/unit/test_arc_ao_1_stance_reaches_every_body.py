"""Arc AO-1 — the stance reaches every body.

Measured live 2026-10-03 (docs/AGENT_OPS_STUDY_2026-10-03.md §2 C1, AO-0.1): a custom
agent's standing instructions reached the quick body's SQL prompt, the deep report and
the evaluation — never the conversation body (the default since SP-14) nor the analyst
loop it reaches for, and never a delegate's hop. These pin each body to the brief, the
delegate to its own identity, the evaluation to the production path, `purpose` to every
door, and deletion to its cascade.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.custom_agents import create_agent, delete_agent, get_agent, list_agents
from aughor.custom_agents.context import activate_agent, current_agent, release_agent
from aughor.custom_agents.models import UserAgent

BRIEF_HEAD = "AGENT BRIEF — you are operating as the user-defined agent"
INSTRUCTIONS = "Report yesterday's sales. Never estimate — if a figure is missing, say so."


@pytest.fixture(autouse=True)
def _clean_agents():
    yield
    for a in list_agents():
        delete_agent(a.id)


def _agent(**kw) -> UserAgent:
    base = dict(id="ua_stance", name="The Look Analyst", instructions=INSTRUCTIONS)
    base.update(kw)
    return UserAgent(**base)


# ── AO-1a · the conversation body ───────────────────────────────────────────────────

def test_the_converse_prompt_leads_with_the_agents_brief_when_handed_the_record():
    from aughor.agent.converse_tools import converse_system_prompt
    before = converse_system_prompt("conn-1")
    after = converse_system_prompt("conn-1", agent=_agent())
    assert not before.startswith(BRIEF_HEAD) and INSTRUCTIONS not in before
    assert after.startswith(BRIEF_HEAD), after[:120]
    assert INSTRUCTIONS in after
    # The receipt the wave promised: the same prompt, differing ONLY by the brief in front.
    assert after.endswith(before), "the brief must be prepended, not woven in"


def test_the_converse_prompt_reads_the_active_agent_when_no_record_is_handed():
    from aughor.agent.converse_tools import converse_system_prompt
    token = activate_agent(_agent())
    try:
        prompt = converse_system_prompt("conn-1")
    finally:
        release_agent(token)
    assert prompt.startswith(BRIEF_HEAD)
    assert INSTRUCTIONS in prompt


def test_no_agent_means_the_converse_prompt_is_unchanged():
    from aughor.agent.converse_tools import converse_system_prompt
    assert current_agent() is None
    prompt = converse_system_prompt("conn-1")
    assert BRIEF_HEAD not in prompt
    assert prompt.startswith("You are Aughor's analyst")


def test_an_agent_with_blank_instructions_adds_nothing():
    from aughor.agent.converse_tools import converse_system_prompt
    assert converse_system_prompt("c", agent=_agent(instructions="   ")) == \
        converse_system_prompt("c")


def test_the_replay_arguments_name_the_agent(monkeypatch):
    """A replay that rebuilds the prompt without the agent rebuilds a prompt the turn never ran."""
    from aughor.agent import converse_tools as ct
    seen: dict = {}

    def _loop(provider, system, question, tools, **kw):
        seen.update(kw)
        seen["system"] = system
        return None

    monkeypatch.setattr("aughor.agent.tool_loop.run_tool_loop", _loop)
    monkeypatch.setattr(ct, "get_provider", lambda role: object(), raising=False)
    monkeypatch.setattr(ct, "converse_tools", lambda *a, **k: [])
    ct.converse("conn-1", "how many orders?", agent=_agent(), provider=object())
    assert seen["replay_args"]["agent_id"] == "ua_stance"
    assert seen["system"].startswith(BRIEF_HEAD)


# ── AO-1a · the analyst loop ────────────────────────────────────────────────────────

def test_the_analyst_prompt_leads_with_the_active_agents_brief():
    from aughor.agent.analyst import analyst_system_prompt
    plain = analyst_system_prompt("conn-1", {}, 8)
    token = activate_agent(_agent())
    try:
        as_agent = analyst_system_prompt("conn-1", {}, 8)
    finally:
        release_agent(token)
    assert BRIEF_HEAD not in plain
    assert as_agent.startswith(BRIEF_HEAD)
    assert as_agent.endswith(plain)


# ── AO-1b · the delegate runs as itself ─────────────────────────────────────────────

def _target():
    return {"id": "ua_delegate", "name": "Churn", "connection_id": "c1"}


def test_the_hop_activates_the_delegate_and_releases_it(monkeypatch):
    from aughor.agent.delegate_tool import _run_one
    from aughor.agent.delegation import DelegationContext
    import aughor.custom_agents as ca

    rec = _agent(id="ua_delegate", name="Churn", instructions="Churn only.")
    monkeypatch.setattr(ca, "get_agent", lambda aid: rec if aid == "ua_delegate" else None)
    inside: dict = {}

    def _answer(conn, args, **kw):
        active = current_agent()
        inside["id"] = active.id if active else None
        return {"headline": "Forty-two churned.", "outcome": "answered", "usage": {}}

    assert current_agent() is None
    row = _run_one(_target(), "count churn", DelegationContext(), answer=_answer)
    assert inside["id"] == "ua_delegate", "the hop ran with the CALLER's stance, not its own"
    assert current_agent() is None, "the delegate must be released after the hop"
    assert row["activated"] is True


def test_the_hop_releases_the_delegate_even_when_it_raises(monkeypatch):
    from aughor.agent.delegate_tool import _run_one
    from aughor.agent.delegation import DelegationContext
    import aughor.custom_agents as ca
    monkeypatch.setattr(ca, "get_agent", lambda aid: _agent(id="ua_delegate"))

    def _boom(conn, args, **kw):
        raise RuntimeError("warehouse down")

    row = _run_one(_target(), "q", DelegationContext(), answer=_boom)
    assert row["error"] is True and current_agent() is None


def test_an_unreadable_delegate_record_is_said_not_papered_over(monkeypatch):
    from aughor.agent.delegate_tool import _run_one
    from aughor.agent.delegation import DelegationContext
    import aughor.custom_agents as ca
    monkeypatch.setattr(ca, "get_agent", lambda aid: None)
    row = _run_one(_target(), "q", DelegationContext(),
                   answer=lambda c, a, **k: {"headline": "x", "outcome": "answered"})
    assert row["activated"] is False
    assert row["response"] == "x"


def test_the_hop_relays_the_headline_never_the_outcome_code(monkeypatch):
    """The real `answer_question` returns `headline` + `outcome`; it has never returned
    `answer`. The old `answer or outcome` relayed the CODE on every production hop."""
    from aughor.agent.delegate_tool import _run_one
    from aughor.agent.delegation import DelegationContext
    import aughor.custom_agents as ca
    monkeypatch.setattr(ca, "get_agent", lambda aid: None)
    real_shape = {"outcome": "answered", "headline": "There were 49 orders.", "sql": "SELECT 1",
                  "columns": ["n"], "row_count": 1, "caveats": [], "guard_receipts": [],
                  "doors": []}
    row = _run_one(_target(), "q", DelegationContext(), answer=lambda c, a, **k: real_shape)
    assert row["response"] == "There were 49 orders."
    assert row["response"] != "answered"


# ── AO-1c · the evaluation frames on the production path ────────────────────────────

def test_the_default_generator_frames_on_the_production_path(monkeypatch):
    import types as _types
    from aughor.custom_agents.quality import evaluate_agent
    from aughor.custom_agents.store import add_golden
    import aughor.routers.investigations as inv

    calls: list[dict] = []

    def _fake_answer_core(question, connection_id, history, **kw):
        active = current_agent()
        calls.append({"question": question, "conn": connection_id,
                      "active": active.id if active else None, **kw})
        return _types.SimpleNamespace(outcome="framed", sql="SELECT COUNT(*) FROM orders",
                                      error="")

    monkeypatch.setattr(inv, "answer_core", _fake_answer_core)

    class _Res:
        def __init__(self, rows, error=None):
            self.rows, self.error = rows, error

    db = _types.SimpleNamespace(
        execute=lambda qid, sql: _Res([(3,)]),
        get_schema=lambda: "orders(id)")
    a = create_agent("Framed", instructions="count things", connection_id="conn-x",
                     schema_scope="sales")
    add_golden(a.id, "How many orders?", "SELECT COUNT(*) FROM orders")

    result = evaluate_agent(a, db=db)
    assert result["passed"] == 1, result
    assert len(calls) == 1
    call = calls[0]
    assert call["frame_only"] is True, "the eval must stop before the execute"
    assert call["skip_clarify"] is True
    assert call["conn"] == "conn-x" and call["schema_scope"] == "sales"
    assert call["active"] == a.id, "the production path must see the agent it is grading"
    assert call["purpose"] == "agent_eval"


def test_a_production_path_that_stops_before_sql_is_scored_as_that(monkeypatch):
    import types as _types
    from aughor.custom_agents.quality import evaluate_agent
    from aughor.custom_agents.store import add_golden
    import aughor.routers.investigations as inv
    monkeypatch.setattr(inv, "answer_core", lambda *a, **k: _types.SimpleNamespace(
        outcome="abstained", sql="", error="not answerable from this schema"))

    class _Res:
        def __init__(self, rows, error=None):
            self.rows, self.error = rows, error

    db = _types.SimpleNamespace(execute=lambda qid, sql: _Res([(3,)]),
                                get_schema=lambda: "orders(id)")
    a = create_agent("Stopped", instructions="x")
    add_golden(a.id, "How many orders?", "SELECT 1")
    result = evaluate_agent(a, db=db)
    assert result["passed"] == 0
    err = result["per_question"][0]["error"]
    assert "abstained" in err and "not answerable" in err


def test_the_quality_module_builds_no_prompt_of_its_own():
    """Code, not prose: the module may EXPLAIN what it stopped doing, it may not do it."""
    import ast
    import inspect
    from aughor.custom_agents import quality
    tree = ast.parse(inspect.getsource(quality))
    named = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    named |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    named |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
              for a in n.names}
    assert not named & {"CHAT_PROMPT", "CHAT_SQL_SYSTEM", "chat_sql_system"}, named


# ── AO-1d · purpose on every door; the pack path keeps the creator's edits ──────────

@pytest.fixture()
def client(monkeypatch):
    import aughor.kernel.flags as flags
    monkeypatch.setattr(flags, "flag_enabled",
                        lambda name: name == "agents.user_defined")
    from aughor.api import app
    return TestClient(app)


def test_purpose_is_writable_on_create_and_patch(client):
    r = client.post("/agents/custom", json={"name": "Churn", "instructions": "Churn.",
                                            "purpose": "Churn and retention questions."})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert r.json()["purpose"] == "Churn and retention questions."
    r = client.patch(f"/agents/custom/{aid}", json={"purpose": "Retention only."})
    assert r.status_code == 200 and r.json()["purpose"] == "Retention only."
    assert get_agent(aid).purpose == "Retention only."
    # Bounded where the roster's own budget is measured.
    r = client.post("/agents/custom", json={"name": "Long", "purpose": "x" * 241})
    assert r.status_code == 422


def test_the_pack_path_keeps_the_creators_instructions_documents_and_purpose(monkeypatch):
    from aughor.custom_agents import templates as t
    monkeypatch.setattr(t, "get_template", lambda pid: {
        "pack_id": pid, "name": "Pack Analyst", "instructions": "THE PACK'S TEXT",
        "suggested_goldens": []})
    made = t.create_from_template("some-pack", name="Mine", instructions="MY EDIT",
                                  purpose="What it is for.", doc_ids=["doc-1"],
                                  pack_ids=["other-pack", "some-pack"], tool_grants=["g1"],
                                  owner="org-1")
    agent = made["agent"]
    assert agent["instructions"] == "MY EDIT", "the creator's edit was thrown away"
    assert agent["purpose"] == "What it is for."
    assert agent["doc_ids"] == ["doc-1"]
    assert agent["tool_grants"] == ["g1"]
    assert agent["pack_ids"][0] == "some-pack" and "other-pack" in agent["pack_ids"]
    assert agent["pack_ids"].count("some-pack") == 1


def test_the_pack_path_falls_back_to_the_packs_stance_when_nothing_was_edited(monkeypatch):
    from aughor.custom_agents import templates as t
    monkeypatch.setattr(t, "get_template", lambda pid: {
        "pack_id": pid, "name": "Pack Analyst", "instructions": "THE PACK'S TEXT",
        "suggested_goldens": []})
    made = t.create_from_template("some-pack", instructions="   ")
    assert made["agent"]["instructions"] == "THE PACK'S TEXT"
    assert made["agent"]["pack_ids"] == ["some-pack"]


def test_the_pack_route_validates_the_connection_like_the_scratch_route(client, monkeypatch):
    from aughor.custom_agents import templates as t
    monkeypatch.setattr(t, "get_template", lambda pid: {
        "pack_id": pid, "name": "P", "instructions": "s", "suggested_goldens": []})
    monkeypatch.setattr("aughor.routers.agents._validate_agent_packs", lambda ids: None)
    r = client.post("/agents/custom/from-template",
                    json={"pack_id": "p", "connection_id": "no-such-connection"})
    assert r.status_code == 422, r.text
    assert not list_agents(), "a refused create must create nothing"


# ── AO-1e · delete cascades with a receipt ──────────────────────────────────────────

def test_deleting_an_agent_disables_its_bots_detaches_its_automations_keeps_revisions(client):
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.automations.store import get_automation, upsert_automation
    from aughor.slackbots import store as bots
    from aughor.slackbots.models import SlackBot

    a = create_agent("Retiring", instructions="v1")
    from aughor.custom_agents import update_agent
    update_agent(a.id, instructions="v2")          # a second revision
    bot = bots.save_bot(SlackBot(name="salesbot", agent_id=a.id, connection_id="c",
                                 bot_token="xoxb-x", app_token="xapp-x", signing_secret="s"))
    auto = upsert_automation(Automation(
        conn_id="c", name="Daily as the agent", agent_id=a.id,
        conditions=[Condition(kind="metric", config={"monitor_id": "m1"})],
        effects=[Effect(kind="notify", config={"trigger_id": "t1", "agent_id": a.id})],
        max_retries=0, retry_backoff_seconds=0.0))

    r = client.delete(f"/agents/custom/{a.id}")
    assert r.status_code == 200, r.text
    receipt = r.json()
    assert receipt["deleted"] == a.id
    assert [b["id"] for b in receipt["bots_disabled"]] == [bot.id]
    assert [x["id"] for x in receipt["automations_detached"]] == [auto.id]
    assert receipt["revisions_kept"] >= 2
    assert "bots_disabled_error" not in receipt and "automations_detached_error" not in receipt

    after_bot = bots.get_bot(bot.id)
    assert after_bot.enabled is False
    assert "Retiring" in after_bot.disabled_reason
    after_auto = get_automation(auto.id)
    assert after_auto.agent_id == ""
    assert after_auto.effects[0].agent_id == ""
    assert after_auto.enabled is True, "the automation itself is someone's intent — it stays"
    assert get_agent(a.id) is None
    assert client.get(f"/agents/custom/{a.id}").status_code == 404


def test_resuming_a_bot_clears_the_platforms_reason(client, monkeypatch):
    from aughor.slackbots import store as bots
    from aughor.slackbots.models import SlackBot
    monkeypatch.setattr("aughor.routers.slackbots._verify", lambda b: b)
    bot = bots.save_bot(SlackBot(name="b", agent_id="gone", enabled=False,
                                 disabled_reason="its agent 'X' was deleted",
                                 bot_token="xoxb-x", app_token="xapp-x", signing_secret="s"))
    body = {"name": "b", "enabled": False, "agent_id": "gone", "connection_id": ""}
    r = client.patch(f"/slack-bots/{bot.id}", json=body)
    assert r.status_code == 200, r.text
    assert bots.get_bot(bot.id).disabled_reason == "its agent 'X' was deleted", \
        "an edit that keeps the bot off keeps the reason"
    r = client.patch(f"/slack-bots/{bot.id}", json={**body, "enabled": True})
    assert r.status_code == 200, r.text
    assert bots.get_bot(bot.id).disabled_reason == ""


def test_deleting_an_unknown_agent_is_a_404_with_no_cascade(client):
    assert client.delete("/agents/custom/ua_nobody").status_code == 404
