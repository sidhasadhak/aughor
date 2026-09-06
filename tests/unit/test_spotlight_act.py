"""SP-3 (§3.11) — Spotlight's Act limb: cosmetic applies, structural stages.

The custody line under test is the arc's central one: `set_preference` lands instantly
(self-scoped, cosmetic), while `draft_agent` / `draft_automation` can only STAGE onto
the one inbox — accept is the arming, reject leaves the platform byte-identical, and
accept RE-validates because data can move between the two acts.
"""
from __future__ import annotations

from types import SimpleNamespace

import aughor.agent.spotlight_act as act
from aughor.actions.inbox import (
    StagedProposal,
    accept_proposal,
    get_proposal,
    reject_proposal,
    stage_proposal,
)


# ── set_preference — the cosmetic class ─────────────────────────────────────────────

def test_preference_applies_instantly_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_USER_PREFS_DB", str(tmp_path / "prefs.db"))
    out = act.set_preference({"key": "theme", "value": "Light"})
    assert out["applied"] is True
    assert out["preferences"]["theme"] == "light"          # normalized
    assert "theme" in out["summary"]

    from aughor.db.user_prefs import get_preferences
    assert get_preferences()["preferences"]["theme"] == "light"


def test_unknown_preference_key_is_refused_naming_the_known_ones(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_USER_PREFS_DB", str(tmp_path / "prefs.db"))
    out = act.set_preference({"key": "font", "value": "comic sans"})
    assert out["applied"] is False
    assert "theme" in out["error"]                          # the registry is named


def test_preference_value_outside_the_registry_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_USER_PREFS_DB", str(tmp_path / "prefs.db"))
    out = act.set_preference({"key": "theme", "value": "hotdog"})
    assert out["applied"] is False and "must be one of" in out["error"]


def test_prefs_store_resolves_env_per_call(tmp_path, monkeypatch):
    """The third import-time-freeze was paid for a week before this store was born —
    two different env values in one process must reach two different files."""
    monkeypatch.setenv("AUGHOR_USER_PREFS_DB", str(tmp_path / "a.db"))
    act.set_preference({"key": "theme", "value": "dark"})
    monkeypatch.setenv("AUGHOR_USER_PREFS_DB", str(tmp_path / "b.db"))
    from aughor.db.user_prefs import get_preferences
    assert "theme" not in get_preferences()["preferences"]  # b.db is fresh


# ── draft_agent — structural: stage → accept creates / reject is byte-identical ────

def test_agent_draft_refused_before_staging_when_incomplete():
    out = act.draft_agent("conn-x", {"name": "", "instructions": ""})
    assert out["staged"] is False
    assert any("name is required" in p for p in out["problems"])
    assert any("instructions are required" in p for p in out["problems"])


def test_agent_draft_stages_with_the_empty_docs_disclosure(monkeypatch):
    monkeypatch.setattr("aughor.custom_agents.store.validate_agent_draft",
                        lambda **kw: [])
    out = act.draft_agent("conn-x", {"name": "refund-watch",
                                     "instructions": "Watch refund rate in DE."})
    assert out["staged"] is True and out["documents_attached"] == 0
    assert "LESS context" in out["summary"]                 # the trap, disclosed
    p = get_proposal(out["proposal_id"])
    assert p is not None and p.kind == "agent_draft" and p.pending
    assert "LESS context" in p.reasoning                    # the approver reads it too


def test_agent_draft_accept_creates_and_reject_leaves_nothing(monkeypatch):
    monkeypatch.setattr("aughor.custom_agents.store.validate_agent_draft",
                        lambda **kw: [])
    from aughor.custom_agents.store import get_agent, list_agents
    before = {a.id for a in list_agents()}

    staged = act.draft_agent("conn-x", {"name": "approved-one",
                                        "instructions": "A scope and a stance."})
    rejected = act.draft_agent("conn-x", {"name": "rejected-one",
                                          "instructions": "Never to exist."})

    assert reject_proposal(rejected["proposal_id"], actor="tester") is True
    assert {a.id for a in list_agents()} == before          # byte-identical on reject

    result, grant = accept_proposal(staged["proposal_id"], actor="tester")
    assert result.ok and result.status == "executed" and grant == ""
    agent_id = result.detail["agent_id"]
    assert get_agent(agent_id) is not None                  # accept IS the arming
    assert get_proposal(staged["proposal_id"]).status == "executed"  # queue vocabulary

    # resolve-once: a second accept never creates a second agent
    again, _ = accept_proposal(staged["proposal_id"], actor="tester")
    assert again.status == "already_resolved"


def test_agent_draft_accept_revalidates_moved_data():
    """Documents can vanish between stage and accept — the accept must refuse with the
    problem sentence, never create against data that moved."""
    p = stage_proposal(StagedProposal(
        kind="agent_draft", connection_id="conn-x", action_id="agent:stale",
        params={"name": "stale", "instructions": "ok", "doc_ids": ["gone-doc"]}))
    result, _ = accept_proposal(p.id, actor="tester")
    assert not result.ok and result.status == "dispatch_error"
    assert "unknown document" in result.message


# ── draft_automation — DS-15 drafts, this stages ───────────────────────────────────

def _proposal(verdict="proposed", draft=None, dry_run=None, reason="", notes=None):
    return SimpleNamespace(verdict=verdict, draft=draft, dry_run=dry_run or {},
                           reason=reason, notes=notes or [])


def test_automation_refusal_is_relayed_not_errored(monkeypatch):
    monkeypatch.setattr("aughor.automations.propose.propose_chain",
                        lambda outcome, conn_id, provider=None: _proposal(
                            verdict="unbuildable", reason="no matching trigger"))
    out = act.draft_automation("conn-x", {"outcome": "teleport the warehouse"})
    assert out["staged"] is False and out["verdict"] == "unbuildable"
    assert "considered refusal" in out["summary"]


def test_automation_draft_stages_then_accept_saves(monkeypatch):
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.automations.store import get_automation
    draft = Automation(
        conn_id="conn-x", name="weekly refund brief",
        conditions=[Condition(kind="schedule", config={"cron": "0 7 * * 1"})],
        effects=[Effect(kind="notify", config={"trigger_id": "trig-1"})],
    ).model_dump()
    monkeypatch.setattr("aughor.automations.propose.propose_chain",
                        lambda outcome, conn_id, provider=None: _proposal(
                            draft=draft, dry_run={"ok": True}))

    out = act.draft_automation("conn-x", {"outcome": "brief me every Monday"})
    assert out["staged"] is True and out["dry_run"] == {"ok": True}
    p = get_proposal(out["proposal_id"])
    assert p.kind == "automation_draft"

    result, _ = accept_proposal(out["proposal_id"], actor="tester")
    assert result.ok and result.status == "executed"
    assert get_automation(result.detail["automation_id"]) is not None


def test_automation_draft_accept_refuses_a_draft_that_no_longer_validates():
    p = stage_proposal(StagedProposal(
        kind="automation_draft", connection_id="conn-x", action_id="automation:broken",
        params={"name": "broken"}))                          # no conditions/effects
    result, _ = accept_proposal(p.id, actor="tester")
    assert not result.ok and result.status == "dispatch_error"
    assert "draft no longer valid" in result.message


# ── pause/resume — structural, staged, applied only on accept ──────────────────────

def _seed_automation(name="pausable", conn_id="conn-x"):
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.automations.store import upsert_automation
    return upsert_automation(Automation(
        conn_id=conn_id, name=name,
        conditions=[Condition(kind="schedule", config={"cron": "0 7 * * 1"})],
        effects=[Effect(kind="notify", config={"trigger_id": "trig-1"})],
    ))


def test_pause_without_an_end_is_refused_before_staging():
    a = _seed_automation("no-end")
    out = act.pause_or_resume_automation("conn-x", {"automation": a.id, "action": "pause"})
    assert out["staged"] is False and "a pause has an end" in out["summary"]


def test_pause_stages_then_accept_applies_and_resume_clears():
    from aughor.automations.store import get_automation
    a = _seed_automation("weekly-brief")

    staged = act.pause_or_resume_automation("conn-x", {
        "automation": "weekly-brief", "action": "pause",
        "until": "2027-01-01T00:00:00Z"})
    assert staged["staged"] is True
    assert get_automation(a.id).paused_until in (None, "")   # staging changed nothing

    result, _ = accept_proposal(staged["proposal_id"], actor="tester")
    assert result.ok and result.status == "executed"
    assert get_automation(a.id).paused_until == "2027-01-01T00:00:00Z"

    resume = act.pause_or_resume_automation("conn-x", {"automation": a.id,
                                                       "action": "resume"})
    result2, _ = accept_proposal(resume["proposal_id"], actor="tester")
    assert result2.ok
    assert not get_automation(a.id).paused_until               # cleared


def test_pause_reject_is_byte_identical_and_stale_accept_refused():
    from aughor.automations.store import delete_automation, get_automation
    a = _seed_automation("reject-me")

    rejected = act.pause_or_resume_automation("conn-x", {
        "automation": a.id, "action": "pause", "until": "2027-01-01T00:00:00Z"})
    assert reject_proposal(rejected["proposal_id"], actor="tester") is True
    assert get_automation(a.id).paused_until in (None, "")

    stale = act.pause_or_resume_automation("conn-x", {
        "automation": a.id, "action": "pause", "until": "2027-01-01T00:00:00Z"})
    delete_automation(a.id)                                    # gone between the two acts
    result, _ = accept_proposal(stale["proposal_id"], actor="tester")
    assert not result.ok and result.status == "dispatch_error"
    assert "no longer exists" in result.message


def test_pause_refuses_a_chain_on_another_connection():
    a = _seed_automation("elsewhere", conn_id="conn-other")
    out = act.pause_or_resume_automation("conn-x", {"automation": a.id,
                                                    "action": "pause",
                                                    "until": "2027-01-01T00:00:00Z"})
    assert out["staged"] is False and "conn-other" in out["summary"]


# ── agent grants — permission to PROPOSE, staged like everything structural ────────

def test_grant_stages_then_accept_appends_and_wildcard_refused(monkeypatch):
    monkeypatch.setattr("aughor.custom_agents.store.validate_agent_draft",
                        lambda **kw: [])
    from aughor.custom_agents.store import create_agent, get_agent
    agent = create_agent("grantee", instructions="A scope and a stance.")

    wild = act.propose_agent_grant("conn-x", {"agent": agent.id, "action_id": "*"})
    assert wild["staged"] is False and "blanket grant" in wild["summary"]

    out = act.propose_agent_grant("conn-x", {"agent": "grantee",
                                             "action_id": "send_refund"})
    assert out["staged"] is True
    assert get_agent(agent.id).tool_grants == []               # staging changed nothing
    p = get_proposal(out["proposal_id"])
    assert p.kind == "agent_grant" and "PROPOSE" in p.reasoning

    result, _ = accept_proposal(out["proposal_id"], actor="tester")
    assert result.ok and result.status == "executed"
    assert get_agent(agent.id).tool_grants == ["send_refund"]

    again = act.propose_agent_grant("conn-x", {"agent": agent.id,
                                               "action_id": "send_refund"})
    assert again["staged"] is False and "already holds" in again["summary"]


def test_grant_accept_revalidates_a_moved_world(monkeypatch):
    from aughor.custom_agents.store import create_agent
    agent = create_agent("moved-world", instructions="A scope and a stance.")
    staged = act.propose_agent_grant("conn-x", {"agent": agent.id,
                                                "action_id": "send_refund"})
    monkeypatch.setattr("aughor.custom_agents.store.validate_agent_grants",
                        lambda *a, **k: ["unknown action id(s) for this connection: send_refund. Declared: none"])
    result, _ = accept_proposal(staged["proposal_id"], actor="tester")
    assert not result.ok and result.status == "dispatch_error"
    assert "unknown action id" in result.message


# ── the roster ─────────────────────────────────────────────────────────────────────

def test_act_roster_names_and_conversation_wiring():
    names = [t.name for t in act.spotlight_act_tools("c1")]
    assert names == ["set_preference", "draft_agent", "draft_automation",
                     "pause_or_resume_automation", "propose_agent_grant"]
    from aughor.agent.converse_tools import converse_tools
    got = {t.name for t in converse_tools("c1")}
    assert {"set_preference", "draft_agent", "draft_automation",
            "pause_or_resume_automation", "propose_agent_grant"} <= got
