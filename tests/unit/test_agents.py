"""The agent fleet — charter registry + governance (override-wins) + the /agents
management surface + the Scout enable-gate on background exploration.
"""
import pytest

from aughor.kernel.agents import (
    agent_for,
    charter_for_kind,
    effective_governance,
    get_charter,
    is_enabled,
    list_charters,
    set_governance,
)
from aughor.kernel.ledger import Ledger


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
        assert get_charter("watcher").reserved is True   # defined, not yet wired


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
