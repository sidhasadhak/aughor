"""The action designer's reading of a draft action (`ontology.action_design`, `POST /ontology/declared-actions/preview`).

The usability walk-through of 2026-10-09 (job 2) found the declare form a developer's, pre-filled with someone else's
refund rule, and unable to say before declaring which objects a person could press an action on or what a press would
change. Every count here is held to a query written by hand over the seeded samples warehouse; a press is dry-run by
the executor's own rules on an object read from it; and neither door writes anything.
"""
from __future__ import annotations

import json

import pytest

from aughor.ontology import overrides as OV
from aughor.ontology.action_design import criteria_filters, preview
from aughor.ontology.models import KineticAction, OntologyGraph
from aughor.ontology.overrides import find_override
from tests.unit.test_object_bindings import GRAPH
from tests.unit.test_process_design import CONN, SCHEMA, _Kept, db, one  # noqa: F401 — the warehouse, by name

ESCALATE = {
    "display_name": "Escalate to carrier", "kind": "annotate", "risk": "low", "object_type": "Order",
    "params": [{"name": "order", "kind": "object", "object_type": "Order", "display_name": "Order"},
               {"name": "reason", "display_name": "Reason", "required": True}],
    "submission_criteria": [{"expr": "order.status in ['shipped']",
                             "message": "Escalate to carrier is only for an order whose status is shipped."}],
    "edits": [{"object": "order", "property": "escalated_to_carrier", "value": "yes", "note": "{reason}"}],
}


def action(**change) -> KineticAction:
    return KineticAction.model_validate({**ESCALATE, "id": "escalate_to_carrier", **change})


@pytest.fixture
def graph():
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


@pytest.fixture(autouse=True)
def _isolated_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")


@pytest.fixture
def live(db, monkeypatch):  # noqa: F811
    """The executor's object read, answered from the seeded warehouse — as `object_resolver` answers from a connection."""
    def read(object_type, key):
        found = db.execute("__t__", f"SELECT * FROM {SCHEMA}.orders WHERE CAST(order_id AS VARCHAR) = '{key}'",
                           internal=True)
        if not found.rows:
            raise LookupError(f"no {object_type} {key}")
        return {"object_type": object_type, "key": key, "properties": dict(zip(found.columns, found.rows[0]))}
    monkeypatch.setattr("aughor.semantic.object_instances.object_resolver", lambda scope, schema="": read)
    return read


# ── who may be pressed on, counted ──────────────────────────────────────────────────────────────────────────────────

def test_criteria_of_the_designers_shape_are_read_as_the_object_doors_filters():
    both = action(submission_criteria=[
        {"expr": "order.status not in ['cancelled', 'refunded'] and object.item_count != 0", "message": "m"},
        {"expr": "order.payment_method == 'card'", "message": "m"}])
    assert criteria_filters(both) == ([
        {"path": "status", "op": "not_in", "values": ["cancelled", "refunded"]},
        {"path": "item_count", "op": "!=", "value": 0},
        {"path": "payment_method", "op": "=", "value": "card"}], "")
    for expr in ("order.total_amount > reason", "order.status in reason", "len(order.status) > 2", "order.status or 1"):
        filters, why = criteria_filters(action(submission_criteria=[{"expr": expr, "message": "m"}]))
        assert filters is None and "is not counted" in why, expr


def test_how_many_allow_a_press_is_counted_over_all_and_over_a_segment(db, graph, live):  # noqa: F811
    read = preview(db, graph, action(), scope=CONN, schema_name=SCHEMA, segments=["active_orders", "cancelled_orders"])
    assert read["objects"] == one(db, f"SELECT COUNT(*) FROM {SCHEMA}.orders")
    assert read["allowed"] == one(db, f"SELECT COUNT(*) FROM {SCHEMA}.orders WHERE status = 'shipped'") > 0
    active, cancelled = read["segments"]
    active_sql = f"FROM {SCHEMA}.orders WHERE status NOT IN ('delivered', 'cancelled')"
    assert active == {"segment": "active_orders", "objects": one(db, f"SELECT COUNT(*) {active_sql}"),
                      "allowed": one(db, f"SELECT COUNT(*) {active_sql} AND status = 'shipped'")}
    # A segment none of whose objects allow it says 0 — not the count over every object.
    assert cancelled == {"segment": "cancelled_orders", "allowed": 0,
                         "objects": one(db, f"SELECT COUNT(*) FROM {SCHEMA}.orders WHERE status = 'cancelled'")}
    assert read["uncounted"] == "" and read["unread"] == []


def test_a_press_is_dry_run_on_a_real_object_by_the_executors_own_rules(db, graph, live):  # noqa: F811
    read = preview(db, graph, action(), scope=CONN, schema_name=SCHEMA, said={"reason": "Missed pickup"})
    press = read["sample"]
    assert press["status"] == "allowed" and press["properties"]["status"] == "shipped"
    assert list(press["properties"])[0] == "status"                      # what the conditions read comes first
    assert press["edits"] == [{"property": "escalated_to_carrier", "value": "yes", "note": "Missed pickup"}]
    assert live("Order", press["key"])["properties"]["status"] == "shipped"


def test_when_no_object_allows_it_the_press_shows_the_refusal_in_the_authors_words(db, graph, live):  # noqa: F811
    nobody = action(submission_criteria=[{"expr": "order.status in ['lost at sea']", "message": "Only lost orders."}])
    read = preview(db, graph, nobody, scope=CONN, schema_name=SCHEMA)
    assert read["allowed"] == 0
    assert (read["sample"]["status"], read["sample"]["message"]) == ("criterion_failed", "Only lost orders.")


def test_a_call_is_shown_filled_and_never_made(db, graph, live):  # noqa: F811
    call = action(kind="side_effect", edits=[], reversibility="irreversible",
                  verification={"sql": "SELECT 1"},
                  side_effects=[{"kind": "http", "config": {"method": "post", "url": "https://carrier.example/o/{reason}",
                                                            "body": {"note": "{reason}"}}}])
    press = preview(db, graph, call, scope=CONN, schema_name=SCHEMA, said={"reason": "a b/c"})["sample"]
    assert press["call"] == {"method": "POST", "url": "https://carrier.example/o/a%20b%2Fc", "body": {"note": "a b/c"}}


# ── the door ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def served(db, graph, live, monkeypatch):  # noqa: F811
    from aughor.routers import ontology as ONT
    monkeypatch.setattr(ONT, "_get_ontology_graph", lambda conn, schema=None: graph)
    monkeypatch.setattr(ONT, "_resolve_schema", lambda conn, schema=None: SCHEMA)
    monkeypatch.setattr("aughor.db.connection.open_connection_for_with_schema", lambda conn, schema=None: _Kept(db))
    from fastapi.testclient import TestClient

    from aughor.api import app
    return TestClient(app)


def _preview(served, **change):
    body = {"id": "escalate_to_carrier", "action": {**ESCALATE, **change}, "segments": ["active_orders"],
            "said": {"reason": "Missed pickup"}}
    return served.post("/ontology/declared-actions/preview", params={"connection_id": CONN}, json=body)


def test_the_preview_door_reads_a_draft_and_writes_nothing(served, db, graph):  # noqa: F811
    r = _preview(served)
    assert r.status_code == 200, r.text
    assert r.json()["allowed"] == one(db, f"SELECT COUNT(*) FROM {SCHEMA}.orders WHERE status = 'shipped'")
    assert r.json()["sample"]["edits"][0]["note"] == "Missed pickup"
    assert find_override(CONN, SCHEMA, "action", "escalate_to_carrier") is None            # nothing written
    assert "escalate_to_carrier" not in graph.kinetic_actions


@pytest.mark.parametrize("change, status, says", [
    ({"kind": None}, 400, "requires a 'kind'"),
    ({"edits": [{"object": "order", "property": "status", "value": "x"}]}, 422, "reads from its source"),
    ({"submission_criteria": [{"expr": "order.status in [", "message": "m"}]}, 422, "is not an expression"),
    ({"kind": "side_effect", "edits": []}, 422, "incomplete declaration"),
])
def test_the_preview_door_refuses_what_declaring_would_refuse(served, change, status, says):
    r = _preview(served, **change)
    assert r.status_code == status and says in r.json()["detail"], r.text


def test_the_preview_door_never_reads_an_id_already_taken_as_new(served, graph):
    graph.kinetic_actions["escalate_to_carrier"] = action()
    assert _preview(served).status_code == 409


def test_the_declare_door_refuses_a_condition_that_is_not_an_expression(served, monkeypatch):
    monkeypatch.setattr("aughor.govern.guard", lambda *a, **k: None)
    r = served.put("/ontology/kinetic-actions/escalate_to_carrier", params={"connection_id": CONN},
                   json={**ESCALATE, "submission_criteria": [{"expr": "order.status in [", "message": "m"}]})
    assert r.status_code == 422 and "is not an expression" in r.json()["detail"]
    assert find_override(CONN, SCHEMA, "action", "escalate_to_carrier") is None
