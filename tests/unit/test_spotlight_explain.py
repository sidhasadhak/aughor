"""SP-15 (§3.11) — `explain`: the platform explains the object on screen.

The baseline this tool beats (measured 2026-09-25 from the session log): the Ask door's
question about a held departure ran Spotlight out of eight steps twice, because no
declared tool could read a departure, an automation or a law. Pinned here: the tool is on
every transport; a departure answers with THIS hold's guards, each law's sentence and the
remedy the screen shows; an automation and a metric answer from their stores; every offer
names a tool the roster has or says which screen holds the act; a summoned turn hands the
object's state to the conversation without a tool call (`_focus_prose_for`).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aughor.agent import spotlight_explain as ex
from aughor.api import app
from aughor.govern.departure_store import record_departure

client = TestClient(app)


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))


def _held():
    return record_departure(
        id="073097487898", org_id="default", kind="briefing", state="held", conn_id="c1",
        automation_id="3440db08", automation_name="The Look - Daily Briefing",
        actor="automation:3440db08", target="sb_e2d5:#aughor_canvas",
        reasons=json.dumps(["re-measure: 1,648.08, 1,151.01 not in analysis ecb56660"]),
        checks=json.dumps({"trust": "clean", "definition": "cites metric revenue v1",
                           "remeasure": "1,648.08, 1,151.01, 23,776.00, 4,702.23 not in analysis ecb56660"}),
        guards=json.dumps({"trust": "passed", "definition": "passed", "remeasure": "held"}),
        text_preview="Revenue reached 1,648.08 yesterday.", investigation_id="ecb56660",
    )


# ── the roster ────────────────────────────────────────────────────────────────────────

def test_explain_is_declared_on_every_transport():
    from aughor.agent.converse_tools import converse_tools
    from aughor.agent.spotlight_roster import spotlight_roster
    assert "explain" in {t.name for t in spotlight_roster("c1")}
    assert "explain" in {t.name for t in converse_tools("c1")}
    listed = {t["name"]: t for t in client.get("/spotlight/tools").json()["tools"]}
    assert listed["explain"]["parameters"]["required"] == ["kind", "id"]
    assert listed["explain"]["parameters"]["properties"]["kind"]["enum"] == list(ex.KINDS)


def test_unknown_kind_and_missing_id_are_answers_not_guesses():
    out = ex.explain_object("c1", {"kind": "widget", "id": "x"})
    assert out["found"] is False and out["kinds"] == list(ex.KINDS)
    out = ex.explain_object("c1", {"kind": "departure", "id": ""})
    assert out["found"] is False and "id" in out["summary"]


# ── departure ─────────────────────────────────────────────────────────────────────────

def test_a_held_departure_answers_with_this_holds_guards_law_and_remedy():
    dep = _held()
    out = ex.explain_object("c1", {"kind": "departure", "id": dep})
    assert out["found"] and out["state"] == "held"
    assert out["automation"] == {"id": "3440db08", "name": "The Look - Daily Briefing"}
    assert out["analysis_id"] == "ecb56660"
    assert out["held_by"] == ["remeasure"]
    told = out["remedy"]["guards"][0]
    assert told["law"] == "law 1"
    assert "every magnitude the text states" in told["law_sentence"]
    assert "1,648.08" in told["reason"]                      # THIS departure's ungrounded numerals
    assert "ask for it in the automation's question" in told["action"]
    # Passed guards are evidence too, in the gate's order.
    assert [c["guard"] for c in out["checks"]] == ["trust", "definition", "remeasure"]
    assert out["checks"][1] == {"guard": "definition", "outcome": "passed", "reason": "cites metric revenue v1"}
    # The offered act: the automation by name, the tool the roster has, the canvas for the question.
    assert out["offer"]["tool"] == "edit_automation"
    assert "The Look - Daily Briefing" in out["offer"]["sentence"]
    assert "Automations canvas" in out["offer"]["sentence"]
    # The gate's own label ("re-measure"), not the screen's capitalised one.
    assert out["summary"].startswith("Departure 073097487898: \"The Look - Daily Briefing\" was held by re-measure")


def test_a_departure_that_is_not_in_the_ledger_says_so():
    out = ex.explain_object("c1", {"kind": "departure", "id": "nope"})
    assert out == {"found": False, "kind": "departure", "id": "nope",
                   "summary": "No departure 'nope' is in the ledger."}


def test_the_tool_is_callable_over_http_with_the_same_body():
    dep = _held()
    body = client.post("/spotlight/tools/explain",
                       json={"connection_id": "c1", "args": {"kind": "departure", "id": dep}}).json()
    assert body["tool"] == "explain" and body["result"]["held_by"] == ["remeasure"]


# ── automation and metric ─────────────────────────────────────────────────────────────

def test_an_automation_answers_from_its_record(monkeypatch):
    a = SimpleNamespace(
        id="auto-9", name="Top sellers", description="Yesterday's top sellers to #ops",
        conn_id="c1", agent_id="", enabled=True, paused_until=None, probation=True,
        declared_by="user:amit", last_run_at="2026-09-26T05:00:00Z", last_status="ok",
        conditions=[SimpleNamespace(kind="schedule", config={"cron": "0 5 * * *"})],
        effects=[SimpleNamespace(kind="investigate", config={"question": "Top sellers yesterday?"}, alias=""),
                 SimpleNamespace(kind="notify", config={"target": "sb_1:#ops"}, alias="")],
    )
    from aughor.agent import spotlight_act
    monkeypatch.setattr(spotlight_act, "resolve_automation", lambda conn, ref: (a, "") if ref in ("auto-9", "Top sellers") else (None, "no such automation"))
    _held()   # a departure on another automation must not be listed under this one
    out = ex.explain_object("c1", {"kind": "automation", "id": "auto-9"})
    assert out["found"] and out["name"] == "Top sellers" and out["probation"] is True
    assert out["conditions"] == [{"kind": "schedule", "config": {"cron": "0 5 * * *"}}]
    assert out["effects"][0] == {"kind": "investigate", "question": "Top sellers yesterday?"}
    assert out["effects"][1] == {"kind": "notify", "target": "sb_1:#ops"}
    assert out["recent_departures"] == []
    assert out["offer"]["tool"] == "edit_automation"
    assert "on probation" in out["summary"] and "2 steps (investigate, notify)" in out["summary"]

    refused = ex.explain_object("c1", {"kind": "automation", "id": "ghost"})
    assert refused["found"] is False and "no such automation" in refused["summary"]


def test_a_metric_answers_with_its_lifecycle_and_tests(monkeypatch):
    from aughor.semantic.metrics import MetricDefinition
    m = MetricDefinition(name="return_rate", label="Return rate", sql="SUM(returned)/COUNT(*)",
                         status="draft", quality_tests=["SELECT COUNT(*) > 0 FROM orders"],
                         freshness_sla="daily by 06:00 UTC")
    monkeypatch.setattr("aughor.semantic.metrics.get_metric",
                        lambda name, path=None, connection_id=None: m if name == "return_rate" else None)
    out = ex.explain_object("c1", {"kind": "metric", "id": "return_rate"})
    assert out["found"] and out["status"] == "draft" and out["approved"] is False
    assert out["quality_tests"] == ["SELECT COUNT(*) > 0 FROM orders"]
    assert out["offer"]["tool"] == "" and "Semantic Layer" in out["offer"]["sentence"]
    assert "cannot back a number that leaves the platform (law 2)" in out["summary"]
    assert ex.explain_object("c1", {"kind": "metric", "id": "ghost"})["found"] is False


def test_every_offered_tool_is_on_the_converse_roster(monkeypatch):
    """SP-4's law applied to explain: an offer names a door the roster has, or no tool."""
    from aughor.agent.converse_tools import converse_tools
    roster = {t.name for t in converse_tools("c1")}
    dep = _held()
    offers = [ex.explain_object("c1", {"kind": "departure", "id": dep})["offer"]]
    for state in ("departed", "held_owner", "held_probation"):
        offers.append(ex._departure_offer(state, {"id": "a", "name": "n"}, None))
    for offer in offers:
        assert offer["sentence"]
        if offer["tool"]:
            assert offer["tool"] in roster, offer


# ── the structural handoff ────────────────────────────────────────────────────────────

def test_a_summoned_turn_hands_the_object_to_the_conversation_without_a_tool_call():
    from aughor.routers.investigations import AskFocus, _focus_prose_for
    dep = _held()
    req = SimpleNamespace(focus=AskFocus(kind="departure", id=dep))
    prose = _focus_prose_for(req, "c1")
    assert prose.startswith("## On screen")
    assert "do not call explain again" in prose
    assert "1,648.08" in prose and "law 1" in prose and "The Look - Daily Briefing" in prose
    # Nothing on screen, or an object that is not there: the turn proceeds plain.
    assert _focus_prose_for(SimpleNamespace(focus=None), "c1") == ""
    assert _focus_prose_for(SimpleNamespace(focus=AskFocus(kind="departure", id="ghost")), "c1") == ""


def test_the_ask_body_accepts_a_focus_and_refuses_an_unknown_kind():
    from aughor.routers.investigations import AskRequest
    req = AskRequest(question="why was this held?", focus={"kind": "departure", "id": "d1"})
    assert req.focus.kind == "departure" and req.focus.id == "d1"
    with pytest.raises(ValueError):
        AskRequest(question="q", focus={"kind": "widget", "id": "d1"})


# ── agent and analysis (the two kinds §6 item 33(c) named next) ──────────────────────

def test_an_agent_answers_with_its_scope_grants_evaluation_and_runs(monkeypatch):
    from types import SimpleNamespace as NS

    from aughor.agent import spotlight_explain as ex
    from aughor.agent.spotlight_guide import eval_sentence
    agent = NS(id="ag-1", name="Returns analyst", purpose="watch returns", instructions="Be terse.",
               connection_id="c1", schema_scope="", doc_ids=["d1", "d2"], pack_ids=["retail"],
               tool_grants=["notify.slack"], workspace_id="", owner="user:amit", enabled=True,
               last_eval={"passed": 4, "total": 5}, eval_basis="stale", created_at="2026-09-01", updated_at="2026-09-20")
    monkeypatch.setattr("aughor.custom_agents.store.get_agent", lambda ref: agent if ref == "ag-1" else None)
    monkeypatch.setattr("aughor.custom_agents.store.list_agents", lambda: [agent])
    monkeypatch.setattr("aughor.db.history.list_investigations_for_agent",
                        lambda agent_id, limit=50: [{"id": "r1", "kind": "chat", "status": "complete",
                                                     "question": "how many returns?", "started_at": "2026-09-25"}])
    out = ex.explain_object("c1", {"kind": "agent", "id": "Returns analyst"})     # by exact name
    assert out["found"] and out["id"] == "ag-1" and out["documents"] == 2 and out["tool_grants"] == ["notify.slack"]
    assert out["evaluation"] == eval_sentence(agent) and "configuration changed since" in out["evaluation"]
    assert out["recent_runs"] == [{"id": "r1", "kind": "chat", "status": "complete",
                                   "question": "how many returns?", "started_at": "2026-09-25"}]
    assert out["offer"]["tool"] == "propose_agent_grant" and "Agents screen" in out["offer"]["sentence"]
    assert out["summary"].startswith('Agent "Returns analyst" is enabled, bound to connection c1; 2 documents, 1 grant;')
    missing = ex.explain_object("c1", {"kind": "agent", "id": "ghost"})
    assert missing["found"] is False and "Returns analyst" in missing["summary"]


def test_an_analysis_answers_with_its_run_its_verdict_and_the_departures_that_cite_it():
    from aughor.agent import spotlight_explain as ex
    from aughor.db.history import complete_investigation, create_investigation
    from aughor.feedback.verdicts import record_verdict
    inv_id = create_investigation("why did returns rise?", "c1")
    complete_investigation(inv_id, {"headline": "Returns rose 12% on footwear", "confidence": 0.8,
                                    "executive_summary": "Footwear drove it.", "recommendations": [{"a": 1}],
                                    "data_gaps": []},
                           [{"id": f"h{i}"} for i in range(3)],
                           [{"sql": f"SELECT {i}", "row_count": 1} for i in range(7)],
                           skip_index=True)
    record_verdict("c1", inv_id, "accept", note="right")
    record_departure(id="dep-cites", org_id="default", kind="briefing", state="held", conn_id="c1",
                     automation_id="a1", automation_name="Daily", actor="automation:a1", target="sb:#c",
                     reasons='["held"]', checks="{}", guards='{"remeasure": "held"}', text_preview="x",
                     investigation_id=inv_id)
    out = ex.explain_object("c1", {"kind": "analysis", "id": inv_id})
    assert out["found"] and out["analysis_kind"] == "deep analysis" and out["status"] == "complete"
    assert out["queries"] == 7 and out["hypotheses"] == 3 and out["confidence"] == 0.8
    assert out["headline"] == "Returns rose 12% on footwear" and out["recommendations"] == 1
    assert out["verdict"]["verdict"] == "accept"
    assert [d["id"] for d in out["departures"]] == ["dep-cites"] and out["departures"][0]["state"] == "held"
    assert out["trace_id"] == inv_id                              # a deep run's id is its trace
    assert f"/traces/{inv_id}/trajectory" in out["offer"]["sentence"] and out["offer"]["tool"] == ""
    assert "1 departure cites it, 1 held" in out["summary"]
    assert ex.explain_object("c1", {"kind": "analysis", "id": "nope"})["found"] is False


def test_every_kind_is_declared_and_the_new_offers_exist_on_the_roster():
    from aughor.agent import spotlight_explain as ex
    from aughor.agent.converse_tools import converse_tools
    roster = {t.name for t in converse_tools("c1")}
    listed = {t["name"]: t for t in client.get("/spotlight/tools").json()["tools"]}
    assert listed["explain"]["parameters"]["properties"]["kind"]["enum"] == ["departure", "automation", "metric", "agent", "analysis"]
    assert set(ex.KINDS) == set(ex._EXPLAINERS)
    assert "propose_agent_grant" in roster
