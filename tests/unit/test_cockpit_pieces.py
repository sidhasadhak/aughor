"""Arc OC-4 — a cockpit's pieces bound to the ontology, as the server holds them (ROADMAP §3.56).

The web's rules check a piece's shape; what only the platform knows is checked here before a spec is kept: that
building cockpits from the ontology is on, and that every id a piece names — a process, an entity and its segment and
columns, a declared action, on the entity its detail shows — resolves in what this connection serves now. A cockpit
with no piece keeps exactly as before, whatever the flag says. A model arranges a piece and never adds one or changes
what it names. And the action button's second answer: an action that needs approval is staged for a person, with no
model called, and only while the flag is on and the caller asked.
"""
from __future__ import annotations

import json
import shutil
import uuid

import pytest

from aughor.cockpit import cards, pieces, propose, validate as V, versions
from aughor.cockpit.home import Home
from aughor.dashboard.models import DashboardCard
from aughor.ontology.models import ActionParameter, KineticAction, ObjectEdit, OntologyGraph
from tests.unit.test_cockpit_canvas import FIXTURE, ME, volumes  # noqa: F401 — the fixture, by name
from tests.unit.test_object_bindings import GRAPH

needs_rules = pytest.mark.skipif(shutil.which("node") is None or not V._BUNDLE.exists(),
                                 reason="the cockpit's rules need node + validate.bundle.mjs")
FLAG = "ontology.cockpit_pieces"


def _flag(monkeypatch, on: bool) -> None:
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: on and name == FLAG)


def _graph() -> OntologyGraph:
    g = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    from aughor.ontology.processes import process_from_fields
    g.processes["order_fulfilment"] = process_from_fields("order_fulfilment", {
        "entity": "Order", "stages": [{"name": "placed", "timestamp": "order_date"},
                                      {"name": "shipped", "timestamp": "shipped_at"}]})
    g.kinetic_actions["flag_for_review"] = KineticAction(
        id="flag_for_review", kind="annotate", risk="low", object_type="Order",
        params=[ActionParameter(name="order", kind="object", object_type="Order"),
                ActionParameter(name="reason", required=False, default_value="")],
        edits=[ObjectEdit(object="order", property="flagged_for_review", value="true", note="{reason}")])
    g.kinetic_actions["hold_customer"] = KineticAction(
        id="hold_customer", kind="annotate", risk="low", object_type="Customer",
        params=[ActionParameter(name="customer", kind="object", object_type="Customer")],
        edits=[ObjectEdit(object="customer", property="on_hold", value="true")])
    return g


def _with_pieces(spec: dict, *, process="order_fulfilment", entity="order", columns=("status", "flagged_for_review"),
                 action="flag_for_review") -> dict:
    els = spec["elements"]
    els["board"] = {"type": "ProcessBoard", "props": {"process": process}, "children": []}
    els["table"] = {"type": "ObjectTable", "props": {"entity": entity, "columns": list(columns)}, "children": []}
    els["detail"] = {"type": "ObjectDetail", "props": {"follows": "table"}, "children": ["flag"]}
    els["flag"] = {"type": "ActionButton", "props": {"action": action}, "children": []}
    els["sec-headline"]["children"] += ["board", "table", "detail"]
    return spec


@pytest.fixture
def no_edits(monkeypatch):
    monkeypatch.setattr(pieces, "_accepted_edits", lambda conn: [])


# ── what only the platform knows ─────────────────────────────────────────────────────────────

def test_a_cockpit_without_a_piece_is_not_read_for_one_whatever_the_flag(monkeypatch):
    _flag(monkeypatch, False)
    assert pieces.not_resolved("c", json.loads(FIXTURE.read_text())) == []


def test_off_a_cockpit_holding_a_piece_is_refused_and_says_why(monkeypatch):
    _flag(monkeypatch, False)
    [said] = pieces.not_resolved("c", _with_pieces(json.loads(FIXTURE.read_text())), graph=_graph())
    assert "4 piece(s) bound to the ontology" in said and "off on this install" in said


def test_on_every_id_resolves_and_the_cockpit_may_be_kept(monkeypatch, no_edits):
    _flag(monkeypatch, True)
    assert pieces.not_resolved("c", _with_pieces(json.loads(FIXTURE.read_text())), graph=_graph()) == []


@pytest.mark.parametrize("change, says", [
    ({"process": "returns"}, 'names the process "returns", which this connection does not declare'),
    ({"entity": "warehouse"}, 'The objects table "table" cannot be read: no'),
    ({"columns": ["status", "no_such"]}, "has no property 'no_such'"),
    ({"action": "refund"}, 'names the action "refund", which this connection does not declare'),
    ({"action": "hold_customer"}, 'runs "hold_customer" on Customer, and the detail it sits in shows Order objects'),
])
def test_a_piece_naming_what_this_connection_cannot_serve_is_refused_by_name(monkeypatch, no_edits, change, says):
    _flag(monkeypatch, True)
    said = " ".join(pieces.not_resolved("c", _with_pieces(json.loads(FIXTURE.read_text()), **change), graph=_graph()))
    assert says in said, said


@needs_rules
def test_the_keep_door_refuses_what_does_not_resolve_and_keeps_what_does(volumes, monkeypatch, no_edits):  # noqa: F811
    tag = uuid.uuid4().hex[:6]
    home = Home(f"conn{tag}", ME, f"late-{tag}")
    rate, net = f"rate{tag}", f"net{tag}"
    for cid, title in ((rate, "Return rate"), (net, "Net revenue")):
        cards.place(home, DashboardCard(id=cid, kind="kpi", title=title, sql="SELECT 1"))
    spec = json.loads(FIXTURE.read_text().replace("c7f3a001", rate).replace("c91b2002", net))
    graph = _graph()
    monkeypatch.setattr(pieces, "_graph", lambda conn: graph)
    _flag(monkeypatch, True)

    def keep(s):
        return versions.keep(home, s, approved_by="user:amit", source="a person's own hand", written_by_model=False)
    refused = keep(_with_pieces(json.loads(json.dumps(spec)), action="refund"))
    assert not refused.kept and 'names the action "refund"' in " ".join(refused.sentences)
    kept = keep(_with_pieces(json.loads(json.dumps(spec))))
    assert kept.kept, kept.sentences


# ── a model arranges a piece; a person places one ───────────────────────────────────────────

def _pieces_only() -> dict:
    return {"elements": {"table": {"type": "ObjectTable", "props": {"entity": "Order", "segment": "overdue_dispatch"},
                                   "children": []},
                         "flag": {"type": "ActionButton", "props": {"action": "flag_for_review"}, "children": []}}}


def test_a_new_cockpit_from_a_model_holds_no_piece():
    said = pieces.pieces_written(None, _pieces_only(), new=True)
    assert len(said) == 2 and all("A new cockpit holds none" in s for s in said)


def test_an_edit_may_resize_or_take_off_a_piece_and_may_not_add_one_or_change_what_it_reads():
    before = _pieces_only()
    resized = json.loads(json.dumps(before))
    resized["elements"]["table"]["props"]["size"] = "large"
    assert pieces.pieces_written(before, resized, new=False) == []
    assert pieces.pieces_written(before, {"elements": {}}, new=False) == []
    added = json.loads(json.dumps(before))
    added["elements"]["board"] = {"type": "ProcessBoard", "props": {"process": "x"}, "children": []}
    assert "never add one" in " ".join(pieces.pieces_written(before, added, new=False))
    repointed = json.loads(json.dumps(before))
    repointed["elements"]["table"]["props"]["segment"] = "completed_orders"
    assert "never change what it reads" in " ".join(pieces.pieces_written(before, repointed, new=False))


def test_the_draft_path_reads_the_pieces_law():
    import inspect
    assert "pieces_written(" in inspect.getsource(propose)      # wired beside the note-and-image law, for both modes


# ── the board says which segment its overdue count lists, while the flag is on ───────────────

def test_a_promise_names_its_overdue_segment_only_while_the_flag_is_on(monkeypatch):
    from aughor.ontology.processes import describe_process, process_from_fields
    g = _graph()
    p = process_from_fields("order_fulfilment", {"entity": "Order", "stages": [
        {"name": "placed", "timestamp": "order_date"},
        {"name": "shipped", "timestamp": "shipped_at", "promise": {"name": "dispatch", "within_days": 2}}]})
    _flag(monkeypatch, False)
    assert "overdue_segment" not in describe_process(g, p)["stages"][1]["promise"]
    _flag(monkeypatch, True)
    assert describe_process(g, p)["stages"][1]["promise"]["overdue_segment"] == "overdue_dispatch"


# ── the execute door proposes what needs approval, for a person, with no model ───────────────

@pytest.fixture
def gated(monkeypatch, client):
    """The execute door over the test graph, its action needing approval, and a count of anything that ran."""
    from aughor.actions.executor import KineticResult
    graph = _graph()
    monkeypatch.setattr("aughor.routers.kinetic._resolve_graph", lambda conn, schema: graph)
    monkeypatch.setattr("aughor.actions.executor.execute_kinetic_action", lambda action, params, **k: KineticResult(
        "approval_required", False, action.id, message="approval required", detail={"error": "approval_required"}))
    return client


def _press(client, **body):
    return client.post("/kinetic-actions/flag_for_review/execute", params={"connection_id": "stage-t"},
                       json={"params": {"order": "O000001", "reason": "late"}, **body})


def test_without_asking_or_with_the_flag_off_a_gated_action_answers_428_as_before(gated, monkeypatch):
    _flag(monkeypatch, True)
    assert _press(gated).status_code == 428
    _flag(monkeypatch, False)
    assert _press(gated, propose_if_gated=True).status_code == 428


def test_asked_and_on_a_gated_action_is_staged_for_a_person_and_nothing_runs(gated, monkeypatch):
    _flag(monkeypatch, True)
    r = _press(gated, propose_if_gated=True, reasoning="from a cockpit")
    assert r.status_code == 200 and r.json()["status"] == "proposed", r.text
    from aughor.actions.inbox import get_proposal
    staged = get_proposal(r.json()["inbox_id"])
    assert (staged.action_id, staged.status, staged.source) == ("flag_for_review", "pending", "cockpit")
    assert staged.params == {"order": "Order:O000001", "reason": "late"} and staged.reasoning == "from a cockpit"
