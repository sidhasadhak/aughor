"""Arc OC-6 — the edit layer: history, declared moves, a concurrency check, and criteria that see it (D5).

Before: an edit could only add a property; a re-set overwrote the row and a withdrawal deleted it, so nothing said who
set what before; nothing checked that the value a person read was still the one they changed; a criterion read the
object without its edits, so an action could not be gated on state another action set; and nothing declared which
moves a state the edit layer holds may make. Each is held here through the real resolver on the seeded samples.
"""
from __future__ import annotations

from aughor.actions import overlay as OVL
from aughor.actions.executor import default_object_resolver, execute_kinetic_action
from tests.unit.test_object_actions import CONN, ORDER, _action, _declare, db, graph  # noqa: F401 — fixtures by name

FLAG = {"display_name": "Flag", "kind": "annotate", "risk": "low", "object_type": "order",
        "params": [{"name": "order", "kind": "object", "object_type": "order"}],
        "edits": [{"object": "order", "property": "review_status", "value": "flagged", "note": ""}]}
REVIEWED = {**FLAG, "display_name": "Mark reviewed",
            "edits": [{"object": "order", "property": "review_status", "value": "reviewed", "note": ""}]}
CLOSE = {**FLAG, "display_name": "Close the review", "edits": [],
         "submission_criteria": [{"expr": "order.review_status == 'reviewed'",
                                  "message": "Only a reviewed order's review is closed."}],
         "kind": "annotate"}


def _run(graph, action_id: str, *, expected=None):  # noqa: F811
    action = _action(graph, action_id)
    return execute_kinetic_action(action, {"order": f"order:{ORDER}"}, actor="ana", scope=CONN, approved=True,
                                  schema_name="ecommerce", resolver=default_object_resolver(action, CONN, "ecommerce"),
                                  expected_versions=expected)


def _machine(graph) -> None:  # noqa: F811
    from aughor.ontology.models import EditStateMachine
    graph.entities["Order"].edit_states = {"review_status": EditStateMachine(
        states=["flagged", "reviewed"], moves=[["", "flagged"], ["flagged", "reviewed"]], initial="")}


def test_a_state_the_edit_layer_holds_moves_only_as_its_type_declares(graph, db):  # noqa: F811
    _declare(graph, "flag", FLAG)
    _declare(graph, "mark_reviewed", REVIEWED)
    _machine(graph)
    early = _run(graph, "mark_reviewed")
    assert early.status == "criterion_failed" and early.http_status() == 422
    assert early.message == (f"order {ORDER} has review_status unset; this action would set it to reviewed, which is "
                             "not a move review_status allows — from unset it may move to flagged")
    assert _run(graph, "flag").status == "executed"
    assert _run(graph, "mark_reviewed").status == "executed"
    back = _run(graph, "flag")
    assert back.status == "criterion_failed" and "from reviewed it may move to nothing" in back.message


def test_every_change_is_kept_and_a_withdrawal_is_a_version_too(graph, db):  # noqa: F811
    _declare(graph, "flag", FLAG)
    _declare(graph, "mark_reviewed", REVIEWED)
    _run(graph, "flag")
    _run(graph, "mark_reviewed")
    edit_id = OVL.object_edits(CONN)[0].id
    OVL.withdraw_edit(edit_id, CONN, actor="ben")
    rows = OVL.edit_history(CONN, object_type="order", row_key=ORDER, column="review_status")
    assert [(r["event"], r["version"], r["body"], r["previous"], r["actor"]) for r in rows] == [
        ("withdrawn", 3, "", "reviewed", "ben"), ("set", 2, "reviewed", "flagged", "ana"), ("set", 1, "flagged", "", "ana")]
    assert OVL.object_edits(CONN) == []                                        # the current row goes; the record stays
    assert _run(graph, "flag").status == "executed"
    assert OVL.object_edits(CONN)[0].version == 4                              # numbering continues past a withdrawal


def test_a_change_made_against_a_version_no_longer_current_is_refused_and_writes_nothing(graph, db):  # noqa: F811
    _declare(graph, "flag", FLAG)
    _declare(graph, "mark_reviewed", REVIEWED)
    assert _run(graph, "flag", expected={"review_status": 0}).status == "executed"        # read unset: version 0
    stale = _run(graph, "mark_reviewed", expected={"review_status": 0})                   # someone flagged it since
    assert (stale.status, stale.http_status()) == ("edit_conflict", 409)
    assert "read at version 0, it is at version 1 now" in stale.message
    assert len(OVL.edit_history(CONN, row_key=ORDER)) == 1                                 # nothing written
    assert _run(graph, "mark_reviewed", expected={"review_status": 1}).status == "executed"


def test_a_criterion_reads_the_state_another_action_set(graph, db):  # noqa: F811
    _declare(graph, "flag", FLAG)
    _declare(graph, "mark_reviewed", REVIEWED)
    _declare(graph, "close_review", {**CLOSE, "edits": [{"object": "order", "property": "review_closed", "value": "yes",
                                                          "note": ""}]})
    refused = _run(graph, "close_review")
    assert refused.status == "criterion_failed" and refused.message == "Only a reviewed order's review is closed."
    _run(graph, "flag")
    _run(graph, "mark_reviewed")
    assert _run(graph, "close_review").status == "executed"                   # D5: the criterion saw the edit


def test_moves_are_declared_on_an_edit_layer_property_only_and_the_history_reads_over_http(graph, db, client, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.routers.ontology._get_ontology_graph", lambda conn, schema=None: graph)
    params = {"connection_id": CONN, "schema_name": "ecommerce"}
    body = {"states": ["flagged", "reviewed"], "moves": [["", "flagged"], ["flagged", "reviewed"]], "initial": ""}
    source = client.put("/ontology/entities/Order/edit-states/status", params=params, json=body)
    assert source.status_code == 400 and "read from Order's source" in source.json()["detail"]
    bad = client.put("/ontology/entities/Order/edit-states/review_status", params=params,
                     json={**body, "moves": [["flagged", "closed"]]})
    assert bad.status_code == 400 and "between two different states it declares" in bad.json()["detail"]
    kept = client.put("/ontology/entities/Order/edit-states/review_status", params=params, json=body)
    assert kept.status_code == 200, kept.text
    from aughor.ontology.overrides import apply_overrides
    served, _ = apply_overrides(graph, CONN, "ecommerce")
    assert served.entities["Order"].edit_states["review_status"].moves == [["", "flagged"], ["flagged", "reviewed"]]
    _declare(graph, "flag", FLAG)
    _run(graph, "flag")
    history = client.get("/actions/edits/history", params={"connection_id": CONN, "row_key": ORDER}).json()
    assert [(h["event"], h["body"]) for h in history["history"]] == [("set", "flagged")]
    assert client.delete("/ontology/entities/Order/edit-states/review_status", params=params).status_code == 200


def test_the_run_door_carries_the_versions_a_person_read(graph, db, client, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.routers.kinetic._resolve_graph", lambda conn, schema: graph)
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")
    _declare(graph, "flag", FLAG)
    _declare(graph, "mark_reviewed", REVIEWED)
    _run(graph, "flag")
    stale = client.post("/kinetic-actions/mark_reviewed/execute", params={"connection_id": CONN, "schema_name": "ecommerce"},
                        json={"params": {"order": f"order:{ORDER}"}, "expected": {"review_status": 0}})
    assert stale.status_code == 409 and "it is at version 1 now" in stale.json()["detail"]["message"]
