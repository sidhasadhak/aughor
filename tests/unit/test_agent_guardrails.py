"""VA-8 — per-agent guardrails: a policy, an enforcement point, and a record of both.

Three of the four things VA-8 named already existed and worked. Schema scope is a
governing field and `_apply_agent_bindings` fails an ask CLOSED with a 409. Per-run
token/time budgets live in `kernel.metering` and are enforced at three points inside the
LLM funnel. PII scanning and redaction run on every non-internal result. What did not
exist was any way to configure ANY of it per agent, or any record that a guardrail had
been evaluated — so an alert on block rate had nothing to count.

These cover the three joints where that could go wrong: a policy that cannot be read
safely, an enforcement point that does not consult it, and a recording that leaves the
rate without its denominator.
"""
from __future__ import annotations

import importlib

import pytest

from aughor.govern import guardrails as g


@pytest.fixture(autouse=True)
def _clean_policies():
    from aughor.kernel.ledger import Ledger
    Ledger.default().kv_replace_all(g.KV_STORE, {})
    yield
    Ledger.default().kv_replace_all(g.KV_STORE, {})


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_AGENTS_DB", str(tmp_path / "agents.db"))
    from aughor.custom_agents import store as s
    importlib.reload(s)
    return s.create_agent("Guarded", instructions="x", connection_id="c1")


# ── the policy ──────────────────────────────────────────────────────────────────

def test_an_agent_with_no_policy_behaves_exactly_as_before(agent):
    """`redact` is the default because it is what the platform already did. An agent
    nobody has configured must not change behaviour the day this ships."""
    policy = g.policy_for(agent.id)
    assert policy.pii == "redact"
    assert policy.max_tokens_per_run is None
    assert policy.is_default


def test_a_policy_equal_to_the_defaults_is_deleted_rather_than_stored(agent):
    """Otherwise "never configured" and "configured to the defaults" drift apart, and a
    later change to a default silently fails to reach the second group."""
    from aughor.kernel.ledger import Ledger
    g.set_policy(agent.id, g.GuardrailPolicy(pii="block"))
    assert Ledger.default().kv_get(g.KV_STORE, agent.id) is not None

    g.set_policy(agent.id, g.GuardrailPolicy())
    assert Ledger.default().kv_get(g.KV_STORE, agent.id) is None
    assert g.policy_for(agent.id).pii == "redact"


def test_an_unreadable_policy_falls_back_instead_of_breaking_the_run():
    """A typo in one agent's stored policy is not a reason to stop answering."""
    assert g.GuardrailPolicy.from_dict({"pii": "nonsense"}).pii == "redact"
    assert g.GuardrailPolicy.from_dict({"max_tokens_per_run": "lots"}).max_tokens_per_run is None
    assert g.GuardrailPolicy.from_dict(None).is_default
    assert g.GuardrailPolicy.from_dict("not a dict").is_default


def test_a_cap_of_zero_is_read_as_no_cap():
    """Zero would arm a budget that is breached by the first token — an outage wearing a
    guardrail's name."""
    assert g.GuardrailPolicy.from_dict({"max_tokens_per_run": 0}).max_tokens_per_run is None


def test_no_agent_active_means_the_seam_is_inert():
    agent_id, policy = g.active_policy()
    assert agent_id == ""
    assert policy.is_default


# ── the run cap ─────────────────────────────────────────────────────────────────

def test_the_run_cap_arms_the_budget_the_llm_funnel_already_checks():
    from aughor.kernel import metering
    token = g.arm_run_cap(g.GuardrailPolicy(max_tokens_per_run=5_000))
    try:
        assert metering.current_budget() == (5_000, None)
    finally:
        g.disarm_run_cap(token)


def test_two_caps_on_one_run_take_the_smaller(agent):
    """An org cap and an agent cap are statements about different things and both hold,
    so the binding one is whichever is breached first. `govern.usage_caps` reasons the
    same way; getting it backwards here would let an agent RAISE a run's tight budget."""
    from aughor.kernel import metering
    outer = metering.set_budget(1_000, 30)
    try:
        inner = g.arm_run_cap(g.GuardrailPolicy(max_tokens_per_run=9_999))
        try:
            assert metering.current_budget() == (1_000, 30), (
                "the agent's generous cap replaced the run's tight one")
        finally:
            g.disarm_run_cap(inner)
    finally:
        metering.clear_budget(outer)


def test_no_cap_arms_nothing(agent):
    from aughor.kernel import metering
    assert g.arm_run_cap(g.GuardrailPolicy()) is None
    assert metering.current_budget() is None


def test_activating_an_agent_activates_its_guardrails(agent):
    """Structural, not a second call every caller has to remember: an agent whose
    guardrails are configured but not armed is exactly how a governance plane ends up
    complete and unenforced."""
    from aughor.custom_agents.context import activate_agent, release_agent
    from aughor.kernel import metering

    g.set_policy(agent.id, g.GuardrailPolicy(max_tokens_per_run=777))
    token = activate_agent(agent)
    try:
        assert metering.current_budget() == (777, None)
    finally:
        release_agent(token)
    assert metering.current_budget() is None, "releasing the agent left its cap armed"


# ── the enforcement point ───────────────────────────────────────────────────────

def _result(rows, column: str = "email"):
    from aughor.db.connection import QueryResult
    return QueryResult(hypothesis_id="h1", sql=f"SELECT {column} FROM t",
                       columns=[column], rows=rows, row_count=len(rows), error=None)


def _post(result):
    from aughor.db.connection import _security_post
    return _security_post("c1", "h1", "SELECT email FROM t", result, 1.0)


PII_ROWS = [["ada@example.com"], ["grace@example.com"]]


def test_the_default_still_redacts(agent):
    from aughor.custom_agents.context import activate_agent, release_agent
    token = activate_agent(agent)
    try:
        out = _post(_result([list(r) for r in PII_ROWS]))
    finally:
        release_agent(token)
    assert out.rows and out.rows[0][0] != "ada@example.com"
    assert out.error is None


def test_block_withholds_the_result_rather_than_punching_holes_in_it(agent):
    """`block` and `redact` must not be the same behaviour under two names."""
    from aughor.custom_agents.context import activate_agent, release_agent
    g.set_policy(agent.id, g.GuardrailPolicy(pii="block"))
    token = activate_agent(agent)
    try:
        out = _post(_result([list(r) for r in PII_ROWS]))
    finally:
        release_agent(token)
    assert out.rows == []
    assert out.row_count == 0
    assert "guardrail" in (out.error or "")
    # And it says so WITHOUT a count: the number of matches is a probing signal an
    # attacker can binary-search against (`test_anti_probing`). It goes to the audit log.
    assert not any(ch.isdigit() for ch in (out.error or "")), (
        f"the block message leaks how many values were found: {out.error!r}")


def test_off_leaves_the_rows_untouched(agent):
    from aughor.custom_agents.context import activate_agent, release_agent
    g.set_policy(agent.id, g.GuardrailPolicy(pii="off"))
    token = activate_agent(agent)
    try:
        out = _post(_result([list(r) for r in PII_ROWS]))
    finally:
        release_agent(token)
    assert out.rows[0][0] == "ada@example.com"


def test_a_clean_result_passes_under_every_mode(agent):
    """`city`, not `email`: the scanner redacts on the COLUMN NAME as well as the value,
    so a clean row under a column called `email` is redacted by design and would have
    made this test assert the opposite of what it claims."""
    from aughor.custom_agents.context import activate_agent, release_agent
    for mode in g.PII_MODES:
        g.set_policy(agent.id, g.GuardrailPolicy(pii=mode))
        token = activate_agent(agent)
        try:
            out = _post(_result([["hello"], ["world"]], column="city"))
        finally:
            release_agent(token)
        assert out.rows == [["hello"], ["world"]], f"mode {mode} damaged a clean result"
        assert out.error is None


# ── the record, and the rate it makes possible ──────────────────────────────────

def test_both_halves_are_recorded_so_the_rate_has_a_denominator(agent):
    """Recording only blocks would leave an agent nothing ever checked indistinguishable
    from one that always passed."""
    from aughor import telemetry
    from aughor.custom_agents.context import activate_agent, release_agent
    from aughor.kernel.ledger import Ledger

    with telemetry.bind_trace("trace-guardrail-1"):
        token = activate_agent(agent)
        try:
            _post(_result([["hello"]], column="city"))       # clean  → allowed
            _post(_result([list(r) for r in PII_ROWS]))      # PII    → redacted, allowed
        finally:
            release_agent(token)

    rows = Ledger.default().session_events(kind=g.EVENT_KIND, trace_id="trace-guardrail-1",
                                           limit=50)
    assert len(rows) == 2, "an evaluation that was allowed must still be recorded"


def test_the_block_rate_has_no_value_when_nothing_was_evaluated():
    """Not a 0% block rate — no block rate. The same distinction `error_rate` makes."""
    from aughor.obs.agent_alerts import measure
    value, population, observed = measure("guardrail_block_rate", [], guardrails=[])
    assert value is None
    assert population == 0
    assert observed == {"evaluated": 0, "blocked": 0}


def test_the_block_rate_counts_evaluations_not_runs():
    """A guardrail that was never consulted could not have blocked anything, so it may
    not sit in the denominator."""
    from aughor.obs.agent_alerts import measure
    rows = [{"blocked": True}, {"blocked": False}, {"blocked": False}, {"blocked": False}]
    value, population, observed = measure("guardrail_block_rate", [], guardrails=rows)
    assert value == 0.25
    assert population == 4
    assert observed == {"evaluated": 4, "blocked": 1}


def test_guardrail_blocks_is_an_absolute_count():
    from aughor.obs.agent_alerts import measure
    rows = [{"blocked": True}, {"blocked": True}, {"blocked": False}]
    value, population, _ = measure("guardrail_blocks", [], guardrails=rows)
    assert value == 2.0
    assert population == 3


def test_an_agent_scoped_rule_ignores_another_agents_blocks():
    from aughor.obs.agent_alerts import AgentAlertRule, evaluate
    rule = AgentAlertRule(id="r1", name="blocks", metric="guardrail_blocks",
                          comparator="gt", threshold=0, window_minutes=60,
                          agent_id="ua_mine")
    rows = [{"blocked": True, "agent_id": "ua_theirs"},
            {"blocked": False, "agent_id": "ua_mine"}]
    verdict = evaluate(rule, [], guardrails=rows)
    assert verdict.value == 0.0, "another agent's block fired this agent's rule"


def test_the_guardrail_kind_is_in_the_closed_event_vocabulary():
    """A monitor written against a kind must not silently miss it."""
    from aughor.obs.session_log import EVENT_KINDS
    assert g.EVENT_KIND in EVENT_KINDS


# ── the HTTP surface ────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aughor.api import app
    return TestClient(app)


def test_the_route_serves_the_modes_from_the_code(client, agent):
    """A mode nothing enforces must never be able to appear in the UI."""
    body = client.get(f"/agents/custom/{agent.id}/guardrails").json()
    assert body["modes"]["pii"] == list(g.PII_MODES)
    assert body["is_default"] is True


def test_the_route_round_trips_a_policy(client, agent):
    put = client.put(f"/agents/custom/{agent.id}/guardrails",
                     json={"pii": "block", "max_tokens_per_run": 4096})
    assert put.status_code == 200
    assert put.json()["guardrails"] == {"pii": "block", "max_tokens_per_run": 4096}
    assert client.get(f"/agents/custom/{agent.id}/guardrails").json()["is_default"] is False


def test_the_route_refuses_a_mode_nothing_enforces(client, agent):
    r = client.put(f"/agents/custom/{agent.id}/guardrails", json={"pii": "encrypt"})
    assert r.status_code == 422


def test_the_route_refuses_a_cap_of_zero(client, agent):
    r = client.put(f"/agents/custom/{agent.id}/guardrails",
                   json={"pii": "redact", "max_tokens_per_run": 0})
    assert r.status_code == 422


def test_an_unknown_agent_has_no_guardrails_to_read(client):
    assert client.get("/agents/custom/ua_nope/guardrails").status_code == 404


def test_the_policy_is_read_once_per_process_not_once_per_query(agent):
    """`active_policy` is consulted on EVERY query result, so an uncached read put one
    ledger open on the platform's hottest path — and `system.db` is the store this app
    has repeatedly died on. Measured after a live crash during VA-8's own verification."""
    from aughor.kernel.ledger import Ledger

    g.invalidate_cache()
    ledger = Ledger.default()
    real = ledger.kv_get
    calls = []

    def counted(store, key, default=None):
        if store == g.KV_STORE:
            calls.append(key)
        return real(store, key, default)

    ledger.kv_get = counted                     # type: ignore[method-assign]
    try:
        for _ in range(5):
            g.policy_for(agent.id)
    finally:
        ledger.kv_get = real                    # type: ignore[method-assign]
    assert len(calls) == 1, f"read the ledger {len(calls)} times for one policy"


def test_setting_a_policy_takes_effect_immediately(agent):
    """A cache with no invalidation would leave an operator's change inert until restart —
    the exact 'configured but not enforced' failure this plane exists to avoid."""
    g.invalidate_cache()
    assert g.policy_for(agent.id).pii == "redact"

    g.set_policy(agent.id, g.GuardrailPolicy(pii="block"))

    assert g.policy_for(agent.id).pii == "block"
