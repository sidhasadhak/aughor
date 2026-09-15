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

def _proposal(verdict="proposed", draft=None, dry_run=None, reason="", notes=None,
              to_fill=None, first_run=""):
    # Mirrors `automations.propose.ChainProposal`, SP-7's two fields included.
    return SimpleNamespace(verdict=verdict, draft=draft, dry_run=dry_run or {},
                           reason=reason, notes=notes or [], to_fill=to_fill or [],
                           first_run=first_run)


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


def test_pause_evidence_chain_reaches_the_approvers_reasoning():
    """SP-6 — a proactive proposal cites its evidence rows: the premortem offer's
    evidence string lands VERBATIM (clipped) on the staged record."""
    from aughor.actions.inbox import get_proposal
    a = _seed_automation("evidence-carrier")
    out = act.pause_or_resume_automation("conn-x", {
        "automation": a.id, "action": "pause", "until": "2027-01-01T00:00:00Z",
        "reasoning": "errors every Monday",
        "evidence": "errored 3 runs in a row: run r-1 at 2026-09-01 (boom)"})
    assert out["staged"] is True
    p = get_proposal(out["proposal_id"])
    assert "EVIDENCE: errored 3 runs in a row: run r-1" in p.reasoning


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


# ── SP-8 — the chain runs as a named agent; the bundle stages ONE proposal ─────────

def _slack_draft(channel=""):
    """An authoring-shaped chain with a slack step — `channel=""` is SP-7's open choice."""
    return {
        "conn_id": "conn-x", "name": "morning anomalies",
        "conditions": [{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
        "effects": [{"kind": "slack_post",
                     "config": {"bot_id": "bot-1", "channel": channel,
                                "message": "anomalies"}}],
    }


def test_automation_draft_runs_as_a_named_existing_agent(monkeypatch):
    from aughor.automations.store import get_automation
    from aughor.custom_agents.store import create_agent
    agent = create_agent("runsas-anomaly-watch", instructions="watch", connection_id="conn-x")
    monkeypatch.setattr("aughor.automations.propose.propose_chain",
                        lambda outcome, conn_id, provider=None: _proposal(
                            draft=_slack_draft(channel="#ops"), dry_run={"ok": True}))

    out = act.draft_automation("conn-x", {"outcome": "anomalies every morning",
                                          "run_as_agent": "runsas-anomaly-watch"})
    assert out["staged"] is True
    assert "runs as agent" in out["summary"]
    p = get_proposal(out["proposal_id"])
    assert p.params["agent_id"] == agent.id
    assert p.detail["runs_as"] == "runsas-anomaly-watch"

    result, _ = accept_proposal(p.id, actor="tester")
    assert result.ok, result.message
    saved = get_automation(result.detail["automation_id"])
    assert saved.agent_id == agent.id           # VA-9b attribution reads this field


def test_run_as_agent_refuses_unknown_and_foreign(monkeypatch):
    from aughor.custom_agents.store import create_agent
    monkeypatch.setattr("aughor.automations.propose.propose_chain",
                        lambda outcome, conn_id, provider=None: _proposal(
                            draft=_slack_draft(channel="#ops")))

    out = act.draft_automation("conn-x", {"outcome": "x", "run_as_agent": "nobody-here"})
    assert out["staged"] is False and "no agent" in out["summary"]
    # An unknown agent is a refusal to STAGE, never an invitation to invent one.
    assert "draft_agent" in out["summary"]

    create_agent("runsas-foreign", instructions="elsewhere", connection_id="conn-OTHER")
    out = act.draft_automation("conn-x", {"outcome": "x", "run_as_agent": "runsas-foreign"})
    assert out["staged"] is False and "conn-OTHER" in out["summary"]


def test_bundle_stages_one_proposal_and_accept_creates_both(monkeypatch):
    from aughor.actions.inbox import list_proposals
    from aughor.automations.store import get_automation
    from aughor.custom_agents.store import get_agent
    monkeypatch.setattr("aughor.custom_agents.store.validate_agent_draft", lambda **kw: [])
    monkeypatch.setattr("aughor.automations.propose.propose_chain",
                        lambda outcome, conn_id, provider=None: _proposal(
                            draft=_slack_draft(channel="#ops"), dry_run={"ok": True},
                            first_run="2026-09-16T09:00:00Z"))
    before = {p.id for p in list_proposals("conn-x")}

    out = act.draft_agent("conn-x", {
        "name": "bundle-watch", "instructions": "Deliver anomalies.",
        "schedule": "every morning at 9am to #ops"})
    assert out["staged"] is True and "all or nothing" in out["summary"]
    staged_now = [p for p in list_proposals("conn-x") if p.id not in before]
    assert len(staged_now) == 1                 # ONE proposal holding both records
    p = staged_now[0]
    assert p.kind == "agent_bundle"
    assert p.detail["first_run"] == "2026-09-16T09:00:00Z"
    assert p.detail["runs_as"] == "bundle-watch"
    assert "agent_id" not in p.params["automation"]   # the id is the accept's to mint

    result, _ = accept_proposal(p.id, actor="tester")
    assert result.ok and result.status == "executed"
    agent = get_agent(result.detail["agent_id"])
    saved = get_automation(result.detail["automation_id"])
    assert agent is not None and saved is not None
    assert saved.agent_id == agent.id           # married: the chain runs as the new agent


def test_bundle_accept_rolls_back_the_agent_when_the_chain_save_fails(monkeypatch):
    from aughor.custom_agents.store import list_agents
    monkeypatch.setattr("aughor.custom_agents.store.validate_agent_draft", lambda **kw: [])
    monkeypatch.setattr("aughor.automations.propose.propose_chain",
                        lambda outcome, conn_id, provider=None: _proposal(
                            draft=_slack_draft(channel="#ops")))
    out = act.draft_agent("conn-x", {"name": "bundle-halfway",
                                     "instructions": "Never half-born.",
                                     "schedule": "every morning"})
    assert out["staged"] is True
    before = {a.id for a in list_agents()}

    monkeypatch.setattr("aughor.runners.automation_save._SAVE",
                        lambda params: (False, "the store said no"))
    result, _ = accept_proposal(out["proposal_id"], actor="tester")
    assert not result.ok and result.status == "dispatch_error"
    assert "rolled back" in result.message
    assert {a.id for a in list_agents()} == before      # all or nothing, honoured
    assert get_proposal(out["proposal_id"]).status == "failed"


def test_bundle_refusal_stages_nothing_at_all(monkeypatch):
    from aughor.actions.inbox import list_proposals
    monkeypatch.setattr("aughor.custom_agents.store.validate_agent_draft", lambda **kw: [])
    monkeypatch.setattr("aughor.automations.propose.propose_chain",
                        lambda outcome, conn_id, provider=None: _proposal(
                            verdict="unbuildable", reason="no matching trigger"))
    before = {p.id for p in list_proposals("conn-x")}
    out = act.draft_agent("conn-x", {"name": "bundle-refused",
                                     "instructions": "One ask, one answer.",
                                     "schedule": "teleport the warehouse"})
    assert out["staged"] is False
    assert "half of it" in out["summary"]       # the agent was not staged beside a refusal
    assert {p.id for p in list_proposals("conn-x")} == before


# ── SP-9 — the approver fills an OPEN choice at accept, and only an open choice ────

def test_bundle_open_choice_blocks_accept_until_filled(monkeypatch):
    import aughor.automations.store  # noqa: F401 — registers the save + holes doors
    from aughor.automations.store import get_automation
    monkeypatch.setattr("aughor.custom_agents.store.validate_agent_draft", lambda **kw: [])
    monkeypatch.setattr("aughor.automations.propose.propose_chain",
                        lambda outcome, conn_id, provider=None: _proposal(
                            draft=_slack_draft(channel=""),
                            to_fill=["Action 1 needs a Slack channel — the request names no Slack channel"]))
    out = act.draft_agent("conn-x", {"name": "bundle-open-choice",
                                     "instructions": "Waits for its channel.",
                                     "schedule": "every morning, somewhere"})
    assert out["staged"] is True
    p = get_proposal(out["proposal_id"])
    assert p.detail["open_choices"] == [{"action": 1, "key": "channel"}]

    refused, _ = accept_proposal(p.id, actor="tester")
    assert refused.status == "invalid_params"
    assert get_proposal(p.id).pending            # the refusal spent nothing

    result, _ = accept_proposal(p.id, actor="tester", fills={"1.channel": "#ops"})
    assert result.ok, result.message
    saved = get_automation(result.detail["automation_id"])
    assert saved.effects[0].config["channel"] == "#ops"
    # the record shows what was ARMED — the fill is part of the accept
    assert get_proposal(p.id).params["automation"]["effects"][0]["config"]["channel"] == "#ops"


def test_accept_fill_may_only_close_an_open_choice(monkeypatch):
    import aughor.automations.store  # noqa: F401 — registers the holes door
    p = stage_proposal(StagedProposal(
        kind="automation_draft", connection_id="conn-x", action_id="automation:fills",
        params=_slack_draft(channel="")))

    result, _ = accept_proposal(p.id, actor="tester", fills={"1.message": "edited!"})
    assert result.status == "invalid_params" and "not an open choice" in result.message
    assert get_proposal(p.id).pending

    result, _ = accept_proposal(p.id, actor="tester", fills={"nonsense": "#x"})
    assert result.status == "invalid_params" and "unreadable fill" in result.message
    assert get_proposal(p.id).pending


def test_hole_sentence_round_trips_through_the_shared_parser():
    """The writer (`fill_required_holes`) and the reader (`parse_hole`) are one format —
    pinned as a ROUND TRIP so a rewording on either end fails here, not silently in a
    card that stops offering its fields."""
    from aughor.automations.models import fill_required_holes
    from aughor.runners.automation_save import parse_hole
    _, holes = fill_required_holes([{"kind": "slack_post", "config": {"bot_id": "b"}}])
    assert holes and parse_hole(holes[0]) == (1, "channel")
    assert parse_hole("Anything else at all") is None


# ── SP-11 — a follow-up supersedes the pending draft; one ask, one proposal ────────

def test_three_follow_ups_leave_one_pending_proposal(monkeypatch):
    """The wave's own receipt sentence, as a test."""
    from aughor.actions.inbox import list_proposals
    monkeypatch.setattr("aughor.automations.propose.propose_chain",
                        lambda outcome, conn_id, provider=None: _proposal(
                            draft=_slack_draft(channel="#ops")))
    before = {p.id for p in list_proposals("conn-x")}

    first = act.draft_automation("conn-x", {"outcome": "anomalies at 9"})
    second = act.draft_automation("conn-x", {"outcome": "anomalies at 8, not 9",
                                             "supersedes": first["proposal_id"]})
    third = act.draft_automation("conn-x", {"outcome": "anomalies at 8 to #alerts",
                                            "supersedes": second["proposal_id"]})
    assert "replaces" in third["summary"]

    new = [p for p in list_proposals("conn-x") if p.id not in before]
    pending = [p for p in new if p.pending]
    assert [p.id for p in pending] == [third["proposal_id"]]
    resolved = {p.id: p for p in new if not p.pending}
    assert resolved[first["proposal_id"]].status == "superseded"
    assert third["proposal_id"] in resolved[second["proposal_id"]].status_message


def test_supersede_cannot_retire_another_connections_or_settled_work(monkeypatch):
    monkeypatch.setattr("aughor.automations.propose.propose_chain",
                        lambda outcome, conn_id, provider=None: _proposal(
                            draft=_slack_draft(channel="#ops")))
    # Another connection's pending draft: named, NOT superseded, both records stand.
    foreign = stage_proposal(StagedProposal(
        kind="automation_draft", connection_id="conn-OTHER",
        action_id="automation:foreign", params=_slack_draft(channel="#x")))
    out = act.draft_automation("conn-x", {"outcome": "x", "supersedes": foreign.id})
    assert "was not superseded" in out["summary"]
    assert get_proposal(foreign.id).pending

    # A settled draft stays settled — first-responder-wins protects the human's act.
    settled = act.draft_automation("conn-x", {"outcome": "y"})
    assert reject_proposal(settled["proposal_id"], actor="tester") is True
    out = act.draft_automation("conn-x", {"outcome": "y again",
                                          "supersedes": settled["proposal_id"]})
    assert "was not superseded" in out["summary"]
    assert get_proposal(settled["proposal_id"]).status == "rejected"


def test_finishing_in_the_editor_resolves_the_draft():
    """SP-11's second half at the inbox seam: the editor's save supersedes with the
    saved record named, and a second call is a harmless no-op."""
    from aughor.actions.inbox import supersede_proposal
    p = stage_proposal(StagedProposal(
        kind="automation_draft", connection_id="conn-x",
        action_id="automation:editor", params=_slack_draft(channel="#ops")))
    assert supersede_proposal(p.id, actor="editor",
                              note="finished in the editor as automation abc123") is True
    row = get_proposal(p.id)
    assert row.status == "superseded" and "abc123" in row.status_message
    assert supersede_proposal(p.id, actor="editor") is False
