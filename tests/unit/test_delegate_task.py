"""VA-2 — `delegate_task`: roster economy, scope enforcement, and the array contract."""
from __future__ import annotations

from aughor.agent import delegate_tool as dt
from aughor.agent.delegation import DelegationContext, DelegationLimits


class _Agent:
    def __init__(self, id, name, purpose="", instructions="", connection_id="",
                 schema_scope="", enabled=True):
        self.id, self.name, self.purpose = id, name, purpose
        self.instructions, self.connection_id = instructions, connection_id
        self.schema_scope, self.enabled = schema_scope, enabled


def _roster(monkeypatch, agents):
    monkeypatch.setattr("aughor.custom_agents.list_agents", lambda: agents,
                        raising=False)
    import aughor.custom_agents as ca
    monkeypatch.setattr(ca, "list_agents", lambda: agents, raising=False)


def _answer_spy(calls, payload=None):
    def _answer(conn, args, **kw):
        calls.append({"connection_id": conn, "question": args["question"]})
        return payload or {"answer": "42", "usage": {"cost_usd": 0.01}}
    return _answer


# ── the roster costs a line each ──────────────────────────────────────────────────

def test_the_roster_reads_purpose_not_instructions(monkeypatch):
    """The measured failure mode: a supervisor prompt that is mostly other agents' prose."""
    long_instructions = "You are a meticulous analyst. " * 200
    _roster(monkeypatch, [_Agent("ua_1", "Churn", purpose="Churn and retention questions.",
                                 instructions=long_instructions)])
    block = dt.roster_block(dt.delegation_targets())
    assert "Churn and retention questions." in block
    assert "meticulous analyst" not in block, "instructions must never reach the roster"
    assert len(block) < 600


def test_an_agent_without_a_purpose_gets_a_BOUNDED_fallback(monkeypatch):
    _roster(monkeypatch, [_Agent("ua_1", "X", instructions="A" * 5000)])
    purpose = dt.delegation_targets()[0]["purpose"]
    assert len(purpose) <= 141, "the fallback must not reintroduce unbounded prose"


def test_disabled_agents_are_not_delegable(monkeypatch):
    _roster(monkeypatch, [_Agent("ua_1", "Off", enabled=False)])
    assert dt.delegation_targets() == []


def test_no_roster_means_no_tool_rather_than_a_tool_that_always_refuses(monkeypatch):
    _roster(monkeypatch, [])
    assert dt.delegation_tools("c1") == []


# ── a delegate cannot out-reach its own definition ────────────────────────────────

def test_the_delegate_answers_on_ITS_connection_not_the_callers(monkeypatch):
    """The security boundary of the wave: delegation must not become a way to read a
    warehouse the agent was never bound to."""
    _roster(monkeypatch, [_Agent("ua_1", "Bound", connection_id="warehouse_b")])
    calls = []
    rows = dt.delegate_task({"task": "how many?", "target_agents": ["Bound"]},
                            ctx=DelegationContext(), answer=_answer_spy(calls),
                            caller_connection_id="warehouse_a")
    assert calls[0]["connection_id"] == "warehouse_b", "the caller's connection leaked in"
    assert rows[0]["response"] == "42"


def test_an_unbound_delegate_answers_on_the_conversations_connection(monkeypatch):
    _roster(monkeypatch, [_Agent("ua_1", "Free", connection_id="")])
    calls = []
    dt.delegate_task({"task": "q", "target_agents": ["Free"]},
                     ctx=DelegationContext(), answer=_answer_spy(calls),
                     caller_connection_id="warehouse_a")
    assert calls[0]["connection_id"] == "warehouse_a"


def test_a_schema_scoped_delegate_carries_its_scope_into_the_task(monkeypatch):
    _roster(monkeypatch, [_Agent("ua_1", "Scoped", schema_scope="finance")])
    calls = []
    dt.delegate_task({"task": "revenue?", "target_agents": ["Scoped"]},
                     ctx=DelegationContext(), answer=_answer_spy(calls))
    assert "finance" in calls[0]["question"]


# ── the array contract, and failures as results ───────────────────────────────────

def test_one_target_still_returns_a_list(monkeypatch):
    """Fan-out is the obvious next step; a caller that special-cases the single shape
    breaks when it arrives."""
    _roster(monkeypatch, [_Agent("ua_1", "Solo")])
    rows = dt.delegate_task({"task": "q", "target_agents": ["Solo"]},
                            ctx=DelegationContext(), answer=_answer_spy([]))
    assert isinstance(rows, list) and len(rows) == 1


def test_two_targets_return_two_rows_and_both_run(monkeypatch):
    _roster(monkeypatch, [_Agent("ua_1", "A"), _Agent("ua_2", "B")])
    calls = []
    rows = dt.delegate_task({"task": "q", "target_agents": ["A", "B"]},
                            ctx=DelegationContext(), answer=_answer_spy(calls))
    assert len(rows) == 2 and len(calls) == 2


def test_a_delegate_that_raises_becomes_a_stated_failure_not_a_crash(monkeypatch):
    _roster(monkeypatch, [_Agent("ua_1", "Broken")])
    def boom(conn, args, **kw):
        raise RuntimeError("warehouse down")
    rows = dt.delegate_task({"task": "q", "target_agents": ["Broken"]},
                            ctx=DelegationContext(), answer=boom)
    assert rows[0]["error"] is True and "warehouse down" in rows[0]["response"]


def test_a_pipeline_error_is_not_dressed_up_as_an_answer(monkeypatch):
    """A well-formed wrong answer is worse than a stated failure."""
    _roster(monkeypatch, [_Agent("ua_1", "E")])
    rows = dt.delegate_task({"task": "q", "target_agents": ["E"]},
                            ctx=DelegationContext(),
                            answer=lambda c, a, **k: {"error": "no such column"})
    assert rows[0]["error"] is True and rows[0]["response"] == "no such column"


def test_an_unknown_target_is_refused_by_name(monkeypatch):
    _roster(monkeypatch, [_Agent("ua_1", "Real")])
    rows = dt.delegate_task({"task": "q", "target_agents": ["Ghost"]},
                            ctx=DelegationContext(), answer=_answer_spy([]))
    assert rows[0]["refused"] is True and rows[0]["code"] == "UNKNOWN_TARGET"


def test_spend_accumulates_on_the_run_context_across_targets(monkeypatch):
    _roster(monkeypatch, [_Agent("ua_1", "A"), _Agent("ua_2", "B")])
    ctx = DelegationContext(limits=DelegationLimits(max_run_steps=99))
    dt.delegate_task({"task": "q", "target_agents": ["A", "B"]},
                     ctx=ctx, answer=_answer_spy([]))
    assert ctx.steps_used == 2 and round(ctx.cost_usd, 4) == 0.02


def test_a_cycle_is_refused_mid_list_without_stopping_the_others(monkeypatch):
    _roster(monkeypatch, [_Agent("ua_1", "A"), _Agent("ua_2", "B")])
    ctx = DelegationContext(agent_path=("ua_1",))
    rows = dt.delegate_task({"task": "q", "target_agents": ["A", "B"]},
                            ctx=ctx, answer=_answer_spy([]))
    assert rows[0]["code"] == "DELEGATION_CYCLE"
    assert rows[1]["refused"] is False, "one refusal must not cancel the rest of the fan-out"


# ── wiring: one roster, and no cost when there is nobody to delegate to ───────────

def test_delegate_task_joins_the_one_roster_the_model_routes_over(monkeypatch):
    from aughor.agent.converse_tools import converse_tools
    _roster(monkeypatch, [_Agent("ua_1", "Churn", purpose="Churn questions.")])
    names = [t.name for t in converse_tools("c1")]
    assert "delegate_task" in names
    assert "answer_question" in names, "delegation must not displace the core roster"


def test_an_empty_workspace_pays_NOTHING_for_delegation(monkeypatch):
    """A workspace with no agents must see neither the tool nor a line of prompt about
    it. Describing a capability the model cannot use is how a turn gets spent on a
    refusal."""
    from aughor.agent.converse_tools import converse_system_prompt, converse_tools
    _roster(monkeypatch, [])
    assert "delegate_task" not in [t.name for t in converse_tools("c1")]
    assert "delegate_task" not in converse_system_prompt("c1")


def test_the_prompt_lists_agents_by_purpose_only(monkeypatch):
    from aughor.agent.converse_tools import converse_system_prompt
    _roster(monkeypatch, [_Agent("ua_1", "Churn", purpose="Churn and retention.",
                                 instructions="SECRET-INSTRUCTION-TEXT " * 100)])
    prompt = converse_system_prompt("c1")
    assert "Churn and retention." in prompt
    assert "SECRET-INSTRUCTION-TEXT" not in prompt


def test_a_broken_roster_never_breaks_the_prompt(monkeypatch):
    """The prompt is the product's voice; a store hiccup must not silence it."""
    from aughor.agent import converse_tools as ct
    monkeypatch.setattr("aughor.agent.delegate_tool.delegation_targets",
                        lambda: (_ for _ in ()).throw(RuntimeError("store down")))
    prompt = ct.converse_system_prompt("c1")
    assert "Aughor's analyst" in prompt
