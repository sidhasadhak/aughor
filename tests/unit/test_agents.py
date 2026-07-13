"""The agent fleet — charter registry + governance (override-wins) + the /agents
management surface + the Scout enable-gate on background exploration.
"""
import asyncio

import pytest

from aughor.kernel import metering
from aughor.kernel.agents import (
    Governance,
    agent_for,
    charter_for_kind,
    effective_governance,
    get_charter,
    is_enabled,
    list_charters,
    set_governance,
)
from aughor.kernel.jobs import JobKernel, JobState
from aughor.kernel.ledger import Ledger


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_governance():
    # Governance lives in the shared hermetic ledger — isolate each test.
    Ledger.default().kv_replace_all("agent_governance", {})
    yield
    Ledger.default().kv_replace_all("agent_governance", {})


class TestRegistry:
    def test_kind_maps_to_agent(self):
        assert charter_for_kind("exploration").id == "scout"
        assert charter_for_kind("investigation").id == "analyst"
        assert charter_for_kind("investigation_salvage").id == "analyst"
        assert charter_for_kind("nonsense").id == "worker"   # graceful unknown

    def test_agent_badge_shape(self):
        b = agent_for("exploration")
        assert b == {"id": "scout", "agent": "Scout", "blurb": charter_for_kind("exploration").role, "icon": "telescope"}

    def test_roster_has_lanes_and_reserved(self):
        ids = {c.id for c in list_charters()}
        assert {"scout", "analyst", "watcher", "briefer", "curator"} <= ids
        scout = get_charter("scout")
        assert scout.lane == "background" and scout.reserved is False
        # WP-7: Watcher/Briefer are now WIRED to the metered monitor/brief cron (non-reserved,
        # with real budgets); only Curator (profile refresh) stays reserved.
        watcher, briefer = get_charter("watcher"), get_charter("briefer")
        assert watcher.reserved is False and watcher.default_budget.time_budget_s
        assert briefer.reserved is False and briefer.default_budget.token_budget
        assert get_charter("curator").reserved is True   # defined, not yet wired

    def test_insight_charter_backs_the_chat_budget(self):
        c = get_charter("insight")
        assert c is not None and c.lane == "interactive" and c.job_kinds == ()
        assert c.default_budget.token_budget == 150_000   # the chat-path cap


class TestGovernance:
    def test_charter_defaults_when_unset(self):
        gov = effective_governance("scout")
        assert gov.enabled is True
        assert gov.token_budget == 200_000   # the charter default
        assert is_enabled("scout") is True

    def test_app_override(self):
        set_governance("scout", enabled=False, token_budget=50_000)
        gov = effective_governance("scout")
        assert gov.enabled is False and gov.token_budget == 50_000
        assert is_enabled("scout") is False

    def test_partial_override_keeps_other_fields(self):
        set_governance("analyst", token_budget=12345)   # only budget
        gov = effective_governance("analyst")
        assert gov.token_budget == 12345
        assert gov.enabled is True                      # untouched → charter default

    def test_workspace_override_wins_over_app(self):
        set_governance("scout", enabled=False)              # app: off
        set_governance("scout", scope="ws1", enabled=True)  # workspace: on
        assert effective_governance("scout", "ws1").enabled is True   # ws wins
        assert effective_governance("scout").enabled is False         # app unchanged

    def test_is_enabled_fail_open(self, monkeypatch):
        # a governance read error must never block work
        monkeypatch.setattr("aughor.kernel.agents.effective_governance",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert is_enabled("scout") is True


class TestAgentsAPI:
    def test_roster_endpoint(self, client):
        roster = client.get("/agents").json()
        ids = {a["id"] for a in roster}
        assert {"scout", "analyst"} <= ids
        scout = next(a for a in roster if a["id"] == "scout")
        assert "governance" in scout and "spend" in scout
        assert set(scout["spend"]) == {"runs", "total_tokens", "query_count"}

    def test_patch_toggles_enabled(self, client):
        r = client.patch("/agents/scout", json={"enabled": False})
        assert r.status_code == 200 and r.json()["governance"]["enabled"] is False
        roster = client.get("/agents").json()
        assert next(a for a in roster if a["id"] == "scout")["governance"]["enabled"] is False

    def test_patch_budget(self, client):
        r = client.patch("/agents/analyst", json={"token_budget": 99999})
        assert r.json()["governance"]["token_budget"] == 99999

    def test_patch_unknown_404(self, client):
        assert client.patch("/agents/ghost", json={"enabled": True}).status_code == 404


class TestEnableGate:
    def test_disabled_scout_skips_auto_exploration(self):
        from aughor.routers._shared import kickoff_exploration
        set_governance("scout", enabled=False)
        # auto=True is gated on Scout; the gate returns before any loop/DB work.
        assert kickoff_exploration("no-such-conn", auto=True) is False


class TestBudgetEnforcement:
    def test_over_budget_token_and_time(self):
        k = JobKernel(Ledger.default())
        tok = metering.start()
        try:
            metering.register_job("jX")
            metering.record_llm(300, 0, 1.0)   # 300 tokens
            over = Governance(enabled=True, token_budget=100, time_budget_s=None)
            ok = Governance(enabled=True, token_budget=1000, time_budget_s=None)
            assert "token budget" in (k._over_budget("jX", over, 0.0) or "")
            assert k._over_budget("jX", ok, 0.0) is None
            t = Governance(enabled=True, token_budget=None, time_budget_s=5)
            assert "time budget" in (k._over_budget("jX", t, 9.0) or "")
            assert k._over_budget("jX", t, 1.0) is None
        finally:
            metering.unregister_job("jX")
            metering.reset(tok)

    def test_heartbeat_cancels_a_run_that_blows_its_budget(self, tmp_path, monkeypatch):
        # Drive the real enforcement path: a run over its token budget is cancelled
        # by the heartbeat — and the cancel (CancelledError) unwinds even an
        # agent that swallows ordinary exceptions.
        monkeypatch.setattr("aughor.kernel.jobs._HEARTBEAT_SECONDS", 0.05)
        set_governance("scout", token_budget=50)          # Scout owns "exploration"
        ledger = Ledger(tmp_path / "system.db")

        async def main():
            kern = JobKernel(ledger)

            async def work():
                metering.record_llm(100, 0, 1.0)          # 100 tokens > 50 budget
                try:
                    await asyncio.sleep(3)                 # long enough for a heartbeat
                except Exception:
                    await asyncio.sleep(3)                 # swallow non-cancellation; cancel still wins

            jid = await kern.submit("exploration", work, conn_id="budget-test-conn")
            for _ in range(120):
                if jid not in kern._tasks:
                    break
                await asyncio.sleep(0.05)
            return jid

        jid = _run(main())
        job = ledger.job_get(jid)
        assert job["state"] == JobState.CANCELLED
        assert "budget exceeded" in (job["error"] or "")


class TestWorkspaceResolution:
    def test_no_workspace_falls_back_to_app_scope(self):
        from aughor.workspace.store import workspace_for_connection
        assert workspace_for_connection(None) is None
        assert workspace_for_connection("conn-in-no-workspace-xyz") is None

    def test_workspace_scoped_governance_resolves(self):
        # per-workspace override is honoured by effective_governance (the resolver
        # the enable-gate + budget enforcement use)
        set_governance("scout", token_budget=200_000)        # app
        set_governance("scout", scope="wsA", token_budget=10)  # workspace override
        assert effective_governance("scout", "wsA").token_budget == 10
        assert effective_governance("scout").token_budget == 200_000
