"""SP-4 (§3.11) — Spotlight's Guide limb: steps are the product's, grounding is live,
every walkthrough ends in an offered act the roster can actually perform.

The laws under test: an offered tool must EXIST on the converse roster (DS-17's law,
applied to guidance — a door the deployment cannot open is never offered); a failed
grounding read reports itself unavailable rather than posing as an empty deployment;
a stopped clock is disclosed before a schedule is implied; an unknown topic is
answered with the topic list, never a guessed walkthrough.
"""
from __future__ import annotations

import aughor.agent.spotlight_guide as guide


# ── topic resolution ───────────────────────────────────────────────────────────────

def test_plain_words_resolve_to_topics():
    assert guide.platform_guide({"topic": "dark mode"})["topic"] == "appearance"
    assert guide.platform_guide({"topic": "Agents"})["topic"] == "create_agent"
    assert guide.platform_guide({"topic": "schedule"})["topic"] == "create_automation"
    assert guide.platform_guide({"topic": "warehouse"})["topic"] == "connect_data"


def test_unknown_topic_lists_topics_and_routes_concepts_to_help():
    out = guide.platform_guide({"topic": "quantum blockchain"})
    assert "steps" not in out                          # never a guessed walkthrough
    assert set(out["topics"]) == {"create_agent", "create_automation",
                                  "connect_data", "appearance"}
    assert "help tool" in out["summary"]


# ── the offers — every offered tool is a door the roster actually has ─────────────

def test_every_offered_tool_exists_on_the_converse_roster():
    from aughor.agent.converse_tools import converse_tools
    roster = {t.name for t in converse_tools("guard-conn")}
    for topic in guide.platform_guide({"topic": "nope"})["topics"]:
        out = guide.platform_guide({"topic": topic})
        offered = out["offer"]["tool"]
        assert out["offer"]["sentence"], f"{topic}: an offer needs its sentence"
        if offered:                                    # "" = the act lives on a page
            assert offered in roster, f"{topic} offers {offered!r}, not on the roster"


def test_connect_data_offers_no_chat_door_and_says_why():
    out = guide.platform_guide({"topic": "connect_data"})
    assert out["offer"]["tool"] == ""
    assert "credential" in out["offer"]["sentence"].lower() \
        or "Connections page" in out["offer"]["sentence"]
    assert "never pass through" in out["summary"] or "could not be read" in out["summary"]


# ── grounding: live state, honest about failure ───────────────────────────────────

def test_agent_walkthrough_cites_the_askers_agents_and_their_evaluations():
    from aughor.custom_agents.store import create_agent, record_eval
    a = create_agent("guide-cited", instructions="A scope and a stance.")
    record_eval(a.id, {"passed": 3, "total": 4, "at": "2026-09-06T00:00:00Z"})
    b = create_agent("guide-unproven", instructions="Never measured.")

    out = guide.platform_guide({"topic": "create_agent"})
    rows = {r["name"]: r["evaluation"] for r in out["grounding"]["agents"]}
    assert "3/4 golden questions passing" in rows[a.name]
    assert "never evaluated" in rows[b.name]
    assert str(out["grounding"]["total"]) in out["summary"]


def test_stale_evaluation_is_named_not_presented_as_current():
    from aughor.custom_agents.store import create_agent, record_eval, update_agent
    a = create_agent("guide-stale", instructions="Original stance.")
    record_eval(a.id, {"passed": 2, "total": 2, "at": "2026-09-06T00:00:00Z"})
    update_agent(a.id, instructions="Edited stance — a different agent now.")

    out = guide.platform_guide({"topic": "create_agent"})
    row = next(r for r in out["grounding"]["agents"] if r["name"] == a.name)
    assert "configuration changed since" in row["evaluation"]


def test_failed_grounding_reads_as_unavailable_never_as_zero(monkeypatch):
    def boom():
        raise RuntimeError("store is gone")
    monkeypatch.setattr("aughor.custom_agents.store.list_agents", boom)
    out = guide.platform_guide({"topic": "create_agent"})
    assert out["grounding"] is None
    assert "could not be read" in out["summary"]
    assert "0 agents" not in out["summary"]            # a failed probe is not a count
    assert out["steps"]                                # the walkthrough still stands


def test_stopped_clock_is_disclosed_on_the_automation_walkthrough():
    from aughor.automations import scheduler
    state, _ = scheduler.clock()
    out = guide.platform_guide({"topic": "create_automation"})
    if state == "stopped":                             # the test process runs no clock
        assert "no clock is running" in out["summary"]
    assert out["grounding"]["clock"]["state"] == state


def test_appearance_grounds_in_the_stored_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_USER_PREFS_DB", str(tmp_path / "prefs.db"))
    out = guide.platform_guide({"topic": "appearance"})
    assert "none set" in out["summary"]                # empty store, said honestly

    from aughor.db.user_prefs import set_preference
    set_preference("theme", "dark")
    out2 = guide.platform_guide({"topic": "appearance"})
    assert "theme = dark" in out2["summary"]
    assert out2["offer"]["tool"] == "set_preference"


# ── the steps are the product's own stations ──────────────────────────────────────

def test_agent_steps_quote_the_create_flows_stepper():
    steps = " ".join(guide.platform_guide({"topic": "create_agent"})["steps"])
    for station in ("Start", "Scope", "Define", "Prove", "Reach"):
        assert station in steps
    assert "NO documents" in steps                     # the empty-docs trap, taught


def test_automation_steps_teach_staging_before_scheduling():
    steps = " ".join(guide.platform_guide({"topic": "create_automation"})["steps"])
    assert "inbox" in steps and "Nothing schedules itself" in steps


# ── the roster ────────────────────────────────────────────────────────────────────

def test_guide_roster_and_conversation_wiring():
    names = [t.name for t in guide.spotlight_guide_tools("c1")]
    assert names == ["platform_guide"]
    from aughor.agent.converse_tools import converse_tools
    assert "platform_guide" in {t.name for t in converse_tools("c1")}
