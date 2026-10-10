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
    graph.entities["Case"].edit_states = {"status": EditStateMachine(
        states=["open", "working", "resolved"], moves=[["", "open"], ["open", "working"], ["working", "resolved"]])}
    _declare(graph, "open_case", OPEN)
    _declare(graph, "start_work", _move("working"))
    _declare(graph, "resolve", _move("resolved"))
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
