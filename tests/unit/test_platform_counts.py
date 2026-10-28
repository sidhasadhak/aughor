"""Arc AP-4 — a case queue: a platform-owned type counted, and kept in a dashboard like any other (ROADMAP §3.57).

A case lives in the edit layer, not a warehouse (Arc OC-6), so the object door's compiler refuses it. A dashboard's figure
and its filter column ask how many: here they are counted where the cases live — how many, or how many different
values of a property, in all or by one property, kept to the conditions given, a reader's search words among them —
and the keep door checks a case queue's pieces the same way, with no case read. Anything the edit layer cannot answer
— a segment, days, a sum, a second grouping, a condition it does not read — is refused and says so. Held through the
real resolver on the seeded samples.
"""
from __future__ import annotations

from aughor.actions import overlay as OVL
from aughor.dashboards import pieces
from aughor.ontology.platform_objects import listing, query
from aughor.semantic.object_query import ObjectQuery
from tests.unit.test_object_actions import CONN, ORDER, db, graph  # noqa: F401 — fixtures by name
from tests.unit.test_platform_owned_case import _run, cases  # noqa: F401 — the fixture, by name

import pytest


@pytest.fixture
def queue(cases, db):  # noqa: F811
    """Three cases: two for ben, one for ana; one of ben's being worked."""
    made = [_run(cases, "open_case", {"order": f"order:{o}", "assignee": who})
            for o, who in ((ORDER, "ben"), ("O000124", "ben"), ("O000125", "ana"))]
    assert all(m.status == "executed" for m in made), [m.message for m in made]
    first = made[0].outcome["edits"][0]["object"].split(":", 1)[1]
    assert _run(cases, "start_work", {"case": f"case:{first}"}).status == "executed"
    return cases


def _count(graph, **ask):  # noqa: F811
    return query(graph.entities["Case"], OVL.accepted_object_edits(CONN), **{"measures": [{"name": "n", "agg": "count"}], **ask})


def test_cases_are_counted_where_they_live_in_all_by_one_property_and_kept_to_conditions(queue):
    assert _count(queue)["rows"] == [[3]]
    assert _count(queue, by=["status"])["rows"] == [["open", 2], ["working", 1]]           # the most first
    assert _count(queue, by=["assignee"], filters=[{"path": "status", "op": "=", "value": "open"}])["rows"] == [
        ["ana", 1], ["ben", 1]]
    assert _count(queue, filters=[{"path": "assignee", "op": "contains", "value": "BE"}])["rows"] == [[2]]
    distinct = query(queue.entities["Case"], OVL.accepted_object_edits(CONN),
                     measures=[{"name": "who", "agg": "count_distinct", "path": "assignee"}])
    assert distinct["path"] == "compiled" and distinct["columns"] == ["who"] and distinct["rows"] == [[2]]
    assert "from the edit layer" in distinct["plan"][0]


@pytest.mark.parametrize("ask, says", [
    ({"segment": "late"}, "a segment is read on a warehouse type"),
    ({"time": "about", "grain": "day"}, "counted, never drawn over days"),
    ({"by": ["status", "assignee"]}, "counted by one property at most"),
    ({"measures": [{"agg": "sum", "path": "status"}]}, "a sum is not read on a platform-owned type"),
    ({"measures": [{"agg": "count_distinct"}]}, "how many different names the property it counts"),
    ({"by": ["priority"]}, "Case has no property 'priority'"),
    ({"filters": [{"path": "status", "op": "in_last", "value": 7}]}, "a 'in_last' condition is not read"),
])
def test_what_the_edit_layer_cannot_count_is_refused_and_said(queue, ask, says):
    out = _count(queue, **ask)
    assert out["path"] == "refused" and says in out["refused"], out


def test_a_listing_reads_search_words_and_refuses_a_sort_it_does_not_list_or_a_condition_it_does_not_read(queue):
    edits = OVL.accepted_object_edits(CONN)
    case = queue.entities["Case"]
    found = listing(case, edits, columns=["assignee"], filters=[{"path": "assignee", "op": "contains", "value": "an"}])
    assert [r[1] for r in found["rows"]] == ["ana"]
    assert listing(case, edits, columns=["assignee"], filters=[], order_by="status")["refused"] == "order_by 'status' is not a listed column"
    # refused before any case is read: a check with none held says the same
    dry = listing(case, [], columns=["status"], filters=[{"path": "status", "op": "in_last", "value": 3}])
    assert dry["path"] == "refused" and "a 'in_last' condition is not read" in dry["refused"], dry
    counted = query(case, [], measures=[{"agg": "count"}], filters=[{"path": "status", "op": "in_last", "value": 3}])
    assert counted["path"] == "refused" and "a 'in_last' condition is not read" in counted["refused"], counted


def test_the_query_door_counts_a_case_queue_from_the_edit_layer(queue, monkeypatch):
    from aughor.routers import objects as R
    monkeypatch.setattr(R, "_served_graph", lambda conn, schema: queue)
    monkeypatch.setattr(R, "_accepted_edits", lambda conn: OVL.accepted_object_edits(CONN))
    out = R.post_object_query(ObjectQuery(object_type="case", measures=[{"name": "n", "agg": "count"}], by=["status"]),
                              connection_id=CONN, schema_name="ecommerce", execute=True, domain=None)
    assert out["path"] == "compiled" and out["rows"] == [["open", 2], ["working", 1]], out
    refused = R.post_object_query(ObjectQuery(object_type="case", measures=[{"agg": "avg", "path": "status"}]),
                                  connection_id=CONN, schema_name="ecommerce", execute=True, domain=None)
    assert refused["path"] == "refused" and "a avg is not read" in refused["refused"]


def _case_desk(**list_props) -> dict:
    return {"root": "cockpit", "elements": {
        "cockpit": {"type": "Cockpit", "props": {"title": "Cases"}, "children": ["filters", "desk"]},
        "filters": {"type": "ObjectFilters", "props": {"entity": "case", "properties": [{"path": "status", "label": "Status"}]},
                    "children": []},
        "desk": {"type": "Section", "props": {"title": "Cases"}, "children": ["open", "queue"]},
        "open": {"type": "ObjectFigure", "props": {"entity": "case", "label": "Cases", "agg": "count"}, "children": []},
        "queue": {"type": "ObjectList", "props": {"entity": "case", "title": "about", "mark": "status", "sort": "assignee",
                                                  **list_props}, "children": []}}}


def test_a_case_queue_is_checked_where_its_cases_live_and_kept_like_any_cockpit(queue, monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: False)
    monkeypatch.setattr(pieces, "accepted_edits", lambda conn: [])
    assert pieces.not_resolved(CONN, _case_desk(), graph=queue) == []
    said = pieces.not_resolved(CONN, _case_desk(title="priority"), graph=queue)
    assert said == ["The object list \"queue\" cannot be read: Case has no property 'priority'."], said
    segmented = pieces.not_resolved(CONN, _case_desk(segment="late"), graph=queue)
    assert len(segmented) == 1 and "a segment is read on a warehouse type" in segmented[0], segmented
