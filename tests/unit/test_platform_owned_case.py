"""Arc OC-6 — the first entity the platform owns: a Case (decision (b); the user chose Case, 2026-10-10).

No warehouse holds a case. It is declared with `backing: {kind: platform}`; a declared action on an order MAKES one
(`creates`), and declared actions move it — open → working → resolved, the moves its type declares and no other — every
change kept as a version. It reads back on its own page and in its listing, names the order it is about, and the order's
page lists its cases. The object door refuses it in a warehouse query and says why. Held through the real resolver on
the seeded samples.
"""
from __future__ import annotations

from aughor.actions import overlay as OVL
from aughor.actions.executor import default_object_resolver, execute_kinetic_action
from aughor.ontology import overrides as OV
from aughor.ontology.declared import entity_fields, entity_spec_problem
from aughor.ontology.models import EditStateMachine
from aughor.ontology.platform_objects import listing, referring
from aughor.semantic.object_context import object_context
from aughor.semantic.object_instances import get_object
from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query
from tests.unit.test_object_actions import CONN, ORDER, _action, _declare, db, graph  # noqa: F401 — fixtures by name

import pytest

CASE = {"id": "Case", "display_name": "Case", "description": "a late order someone is working",
        "backing": {"kind": "platform", "properties": [{"name": "about"}, {"name": "status"}, {"name": "assignee"}]}}
OPEN = {"display_name": "Open a case", "kind": "annotate", "risk": "low", "object_type": "order", "creates": "Case",
        "params": [{"name": "order", "kind": "object", "object_type": "order"}, {"name": "assignee", "data_type": "VARCHAR"}],
        # an object parameter fills a template as its reference, `order:<key>` — what links the case to its order
        "edits": [{"object": "created", "property": "about", "value": "{order}", "note": ""},
                  {"object": "created", "property": "status", "value": "open", "note": ""},
                  {"object": "created", "property": "assignee", "value": "{assignee}", "note": ""}]}


def _move(to: str) -> dict:
    return {"display_name": f"Case to {to}", "kind": "annotate", "risk": "low", "object_type": "case",
            "params": [{"name": "case", "kind": "object", "object_type": "case"}],
            "edits": [{"object": "case", "property": "status", "value": to, "note": ""}]}


@pytest.fixture
def cases(graph):  # noqa: F811
    assert entity_spec_problem(CASE) == ""
    fields = entity_fields(CASE)
    OV.save_override(CONN, "ecommerce", OV.OntologyOverride(target_kind="entity", target_id="Case", fields=fields,
                                                            binding={"backing": {"bound": True, "primary_key": "id"}}))
    OV.apply_overrides(graph, CONN, "ecommerce")
    # Every declaration goes through the doors' own checks — the body each door reads and the problem it refuses with.
    # A first draft set these on the graph directly, and the doors refused all four live on theLook (2026-10-10).
    from aughor.routers.ontology import _checked_action, _DeclaredActionBody, _edit_states_problem, _EditStates
    moves = _EditStates(states=["open", "working", "resolved"],
                        moves=[["", "open"], ["open", "working"], ["working", "resolved"]])
    assert _edit_states_problem(graph.entities["Case"], "status", moves) == ""
    graph.entities["Case"].edit_states = {"status": EditStateMachine(states=moves.states, moves=moves.moves)}
    for action_id, spec in (("open_case", OPEN), ("start_work", _move("working")), ("resolve", _move("resolved"))):
        fields = {k: v for k, v in _DeclaredActionBody(**spec).model_dump().items() if v is not None}
        _checked_action(action_id, fields, graph)
        _declare(graph, action_id, fields)
    return graph


def _run(graph, action_id: str, params: dict):  # noqa: F811
    action = _action(graph, action_id)
    return execute_kinetic_action(action, params, actor="ana", scope=CONN, approved=True, schema_name="ecommerce",
                                  resolver=default_object_resolver(action, CONN, "ecommerce"))


def test_a_case_is_opened_on_an_order_and_moves_only_as_its_type_declares(cases, db):  # noqa: F811
    opened = _run(cases, "open_case", {"order": f"order:{ORDER}", "assignee": "ben"})
    assert opened.status == "executed", opened.message
    case_id = opened.outcome["edits"][0]["object"].split(":", 1)[1]
    assert case_id.startswith("case-")
    page = get_object(cases, None, "case", case_id, overlay=OVL.accepted_object_edits(CONN))
    said = {p["name"]: p["value"] for p in page.properties}
    assert said == {"id": case_id, "about": f"order:{ORDER}", "status": "open", "assignee": "ben"}
    assert [(link["name"], link["to"], link["pk"]) for link in page.links] == [("about", "order", ORDER)]
    assert page.to_dict()["platform"] is True                     # the page says it is held, never "read live"
    assert "platform" not in get_object(cases, db, "order", ORDER).to_dict()
    early = _run(cases, "resolve", {"case": f"case:{case_id}"})
    assert early.status == "criterion_failed" and "from open it may move to working" in early.message
    assert _run(cases, "start_work", {"case": f"case:{case_id}"}).status == "executed"
    assert _run(cases, "resolve", {"case": f"case:{case_id}"}).status == "executed"
    history = OVL.edit_history(CONN, object_type="case", row_key=case_id, column="status")
    assert [(h["body"], h["previous"]) for h in history] == [("resolved", "working"), ("working", "open"), ("open", "")]


def test_cases_are_listed_from_the_edit_layer_and_an_order_lists_its_own(cases, db):  # noqa: F811
    first = _run(cases, "open_case", {"order": f"order:{ORDER}", "assignee": "ben"})
    _run(cases, "open_case", {"order": "order:O000124", "assignee": "cy"})
    edits = OVL.accepted_object_edits(CONN)
    page = listing(cases.entities["Case"], edits, columns=["status", "assignee"],
                   filters=[{"path": "assignee", "op": "=", "value": "ben"}])
    case_id = first.outcome["edits"][0]["object"].split(":", 1)[1]
    assert page["path"] == "listed" and page["total"] == 1 and page["rows"] == [[case_id, "open", "ben"]]
    order = get_object(cases, db, "order", ORDER, overlay=edits)
    related = object_context(cases, db, CONN, "ecommerce", order)["platform"]
    assert [(r["type_id"], r["pk"], r["summary"]["status"]) for r in related] == [("Case", case_id, "open")]
    assert referring(cases, edits, cases.entities["Order"], "O999999") == []


def test_the_object_door_refuses_a_platform_owned_type_in_a_warehouse_query_and_says_why(cases):
    with pytest.raises(ObjectQueryRefused, match="held by the platform"):
        compile_object_query({"object_type": "case", "measures": [{"agg": "count"}]}, cases)


def test_a_platform_owned_type_declares_its_properties_and_reads_no_source():
    assert "reads no table" in entity_spec_problem({**CASE, "backing": {**CASE["backing"], "table": "cases"}})
    assert "`id` is the key" in entity_spec_problem({**CASE, "backing": {"kind": "platform", "properties": [{"name": "id"}]}})
    assert entity_fields(CASE)["backing"] == {"kind": "platform", "primary_key": "id", "properties": [
        {"name": "about", "data_type": "VARCHAR"}, {"name": "status", "data_type": "VARCHAR"},
        {"name": "assignee", "data_type": "VARCHAR"}]}


def test_the_moves_door_takes_a_platform_owned_property_and_refuses_its_key(cases):
    """Found live on theLook (2026-10-10): the door refused moves on the Case's `status` as "read from Case's source" —
    every property a platform-owned type declares is held by the edit layer; only its key, and a name it does not
    declare, are refused."""
    from aughor.routers.ontology import _edit_states_problem, _EditStates
    spec = _EditStates(states=["open", "working", "resolved"], moves=[["", "open"], ["open", "working"]])
    case = cases.entities["Case"]
    assert _edit_states_problem(case, "status", spec) == ""
    assert "no property 'id'" in _edit_states_problem(case, "id", spec)
    assert "no property 'priority'" in _edit_states_problem(case, "priority", spec)
    assert "read from Order's source" in _edit_states_problem(cases.entities["Order"], "status", spec)


def test_a_platform_owned_key_is_unique_by_construction_and_its_type_says_where_it_lives(cases):
    """Found live (2026-10-10): the Case's key read "not yet measured" with a Measure button beside its title — there is
    no warehouse to count either over; the platform mints every key."""
    from aughor.semantic.object_types import describe_object_type
    assert cases.entities["Case"].backing.verified is True
    detail = describe_object_type(cases, "Case")
    assert detail["platform"] is True and detail["key"]["verified"] is True
    assert describe_object_type(cases, "Order")["platform"] is False
