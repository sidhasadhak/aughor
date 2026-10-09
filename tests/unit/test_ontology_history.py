"""Arc OC-1 — every declaration keeps its history, and a withdrawal something depends on is refused (ROADMAP §3.56).

Before: a save replaced the declaration's YAML file and a withdrawal deleted it, so what a promise said last week
had no answer, and `DELETE /ontology/entities/{id}` removed a type an automation watched. Behind `ontology.history`
each save and withdrawal is a version on the lifecycle substrate under the element's stable id, a measurement written
back is not a version, a declaration older than its history starts from its last edit — never "not declared" — and
the withdrawal doors answer 409 naming what depends. Off, the store reads and writes exactly as before.

Hermetic: the overrides tree and the ledger are per test; the dependents run on the samples graph the process
suite measures (`evals/ablation_samples_ecommerce_ontology_measured.json`).
"""
from __future__ import annotations

import itertools

import pytest

from aughor.kernel import lifecycle
from aughor.ontology import dependents as DEP
from aughor.ontology import history as H
from aughor.ontology import overrides as OV
from aughor.ontology.models import KineticAction, Undo
from aughor.ontology.overrides import OntologyOverride, delete_override, find_override, save_override
from aughor.ontology.processes import process_fields, process_from_fields
from tests.unit.test_object_processes import FULFILMENT, fresh_graph

CONN, SCHEMA = "history-t", "ecommerce"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from aughor.kernel.ledger import Ledger
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(OV, "_SEED_ROOT", tmp_path / "seed")
    ledger = Ledger(str(tmp_path / "system.db"))
    monkeypatch.setattr(Ledger, "default", classmethod(lambda cls: ledger))
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")     # the gate is on by default since 2026-10-04


def _flag(monkeypatch, on: bool) -> None:
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: on and name == "ontology.history")


@pytest.fixture
def clock(monkeypatch):
    """Each lifecycle write at the next of these moments."""
    moments = iter(["2026-09-20T10:00:00+00:00", "2026-10-05T10:00:00+00:00", "2026-10-12T10:00:00+00:00",
                    "2026-10-20T10:00:00+00:00", "2026-10-21T10:00:00+00:00"])
    monkeypatch.setattr(lifecycle, "_now", lambda: next(moments))


def _dispatch(days: int, **kw) -> OntologyOverride:
    return OntologyOverride(target_kind="process", target_id="dispatch", edited_by="ana", fields={
        "declared": True, "entity": "Order", "stages": [
            {"name": "placed", "timestamp": "order_date"},
            {"name": "shipped", "timestamp": "shipped_at", "promise": {"name": "dispatch", "within_days": days}}]},
        **kw)


def _days(fields: dict) -> int:
    return fields["stages"][1]["promise"]["within_days"]


def _key() -> str:
    return H.element_key(CONN, SCHEMA, "process", "dispatch")


# ── off: byte-identical ───────────────────────────────────────────────────────────────────────

def test_off_the_store_reads_and_keeps_nothing(monkeypatch):
    _flag(monkeypatch, False)
    monkeypatch.setattr(OV, "find_override", lambda *a, **k: pytest.fail("the store read a prior with the flag off"))
    save_override(CONN, SCHEMA, _dispatch(2))
    save_override(CONN, SCHEMA, _dispatch(3))
    assert delete_override(CONN, SCHEMA, "process", "dispatch")
    assert lifecycle.history(H.KIND, _key()) == []


# ── on: every save and withdrawal kept ────────────────────────────────────────────────────────

def test_a_promise_declared_changed_twice_and_withdrawn_reads_back_four_versions(monkeypatch, clock):
    from aughor.org.context import reset_actor, set_actor
    _flag(monkeypatch, True)
    token = set_actor("person:ana")
    try:
        for days in (2, 3, 4):
            save_override(CONN, SCHEMA, _dispatch(days))
        assert delete_override(CONN, SCHEMA, "process", "dispatch")
    finally:
        reset_actor(token)
    rows = H.versions(CONN, SCHEMA, "process", "dispatch")
    assert [(r["version"], r["state"]) for r in rows] == [(4, "withdrawn"), (3, "declared"), (2, "declared"),
                                                          (1, "declared")]
    assert [_days(r["fields"]) for r in rows] == [4, 4, 3, 2]       # a withdrawal keeps what it said when it went
    assert all(r["by"] == "person:ana" for r in rows)
    assert rows[2]["changes"] == ["changed stages[1].promise.within_days"]
    assert find_override(CONN, SCHEMA, "process", "dispatch") is None   # the tree serves the withdrawal


def test_a_verdict_written_back_is_not_a_version(monkeypatch):
    _flag(monkeypatch, True)
    save_override(CONN, SCHEMA, _dispatch(2))
    measured = find_override(CONN, SCHEMA, "process", "dispatch")
    measured.binding = {"process": {"bound": True, "objects": 124_987}}
    save_override(CONN, SCHEMA, measured)
    assert [r["version"] for r in H.versions(CONN, SCHEMA, "process", "dispatch")] == [1]


def test_as_of_answers_what_late_meant_on_a_past_day(monkeypatch, clock):
    _flag(monkeypatch, True)
    save_override(CONN, SCHEMA, _dispatch(2))                       # 20 Sep
    save_override(CONN, SCHEMA, _dispatch(3))                       # 5 Oct
    delete_override(CONN, SCHEMA, "process", "dispatch")            # 12 Oct
    on_1_october = H.as_of(CONN, SCHEMA, "process", "dispatch", "2026-10-01")
    assert on_1_october["known"] and on_1_october["state"] == "declared" and _days(on_1_october["fields"]) == 2
    assert _days(H.as_of(CONN, SCHEMA, "process", "dispatch", "2026-10-05")["fields"]) == 3   # the day it changed
    gone = H.as_of(CONN, SCHEMA, "process", "dispatch", "2026-10-15")
    assert gone["state"] == "withdrawn" and gone["fields"] == {} and _days(gone["withdrawn_fields"]) == 3
    before = H.as_of(CONN, SCHEMA, "process", "dispatch", "2026-09-01")
    assert before["known"] and before["state"] == "not declared"
    with pytest.raises(ValueError):
        H.as_of(CONN, SCHEMA, "process", "dispatch", "last Tuesday")


def test_a_declaration_older_than_its_history_starts_from_its_last_edit(monkeypatch, clock):
    _flag(monkeypatch, False)
    save_override(CONN, SCHEMA, _dispatch(2, edited_at="2026-09-01T08:00:00+00:00"))
    _flag(monkeypatch, True)
    (only,) = H.versions(CONN, SCHEMA, "process", "dispatch")        # unchanged since: one unrecorded version
    assert only["version"] is None and only["note"] == H.BASELINE_NOTE
    assert _days(H.as_of(CONN, SCHEMA, "process", "dispatch", "2026-09-15")["fields"]) == 2
    save_override(CONN, SCHEMA, _dispatch(3))
    rows = H.versions(CONN, SCHEMA, "process", "dispatch")
    assert [(r["version"], r["note"]) for r in rows] == [(2, ""), (1, H.BASELINE_NOTE)]
    assert rows[1]["in_force_from"] == "2026-09-01T08:00:00+00:00"
    unknown = H.as_of(CONN, SCHEMA, "process", "dispatch", "2026-08-01")
    assert unknown["known"] is False and "not known" in unknown["why"]     # said, never "not declared"


def test_a_history_that_cannot_be_kept_never_undoes_the_declaration(monkeypatch):
    _flag(monkeypatch, True)
    said = []

    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(lifecycle, "record", broken)
    monkeypatch.setattr("aughor.kernel.errors.tolerate", lambda exc, reason, **k: said.append(reason))
    save_override(CONN, SCHEMA, _dispatch(2))
    assert find_override(CONN, SCHEMA, "process", "dispatch") is not None
    assert said and "could not be kept" in said[0]


def test_the_generic_lifecycle_doors_read_a_declaration_and_refuse_to_write_one(monkeypatch):
    from fastapi.testclient import TestClient

    from aughor.api import app
    _flag(monkeypatch, True)
    save_override(CONN, SCHEMA, _dispatch(2))
    client = TestClient(app)
    assert client.get("/lifecycle/ontology_declaration/history", params={"natural_key": _key()}).status_code == 200
    for door in ("publish", "revert"):
        r = client.post(f"/lifecycle/ontology_declaration/{door}", params={"natural_key": _key(), "to_version": 1})
        assert r.status_code == 409 and "own doors" in r.json()["detail"]
    assert len(lifecycle.history(H.KIND, _key())) == 1


# ── what depends on a declaration ─────────────────────────────────────────────────────────────

def _automation(name: str, **kw):
    from aughor.automations.models import Automation, Condition, Effect
    conditions = kw.get("conditions") or [Condition(kind="schedule", config={"cron": "0 7 * * *"})]
    effects = kw.get("effects") or [Effect(kind="investigate", config={"question": "why"})]
    return Automation(name=name, conn_id=CONN, conditions=conditions, effects=effects)


def _watch():
    from aughor.automations.models import Condition
    return _automation("Dispatch promise watch",
                       conditions=[Condition(kind="promise_breached", config={"process": "order_fulfilment"})])


@pytest.fixture
def graph():
    g = fresh_graph()
    g.processes["order_fulfilment"] = process_from_fields("order_fulfilment", process_fields(FULFILMENT))
    return g


def test_a_process_reads_the_link_its_promise_walks(graph):
    # The shipping promise is kept per order line and reaches the order through the only to-one link between them —
    # the same walk its measurement takes, so withdrawing that link would leave the promise unmeasurable.
    entities, links = DEP.process_reach(graph, graph.processes["order_fulfilment"])
    assert {"Order", "OrderItem"} <= entities
    assert "OrderItem_RELATES_TO_Order" in links


def test_an_entity_an_automation_relies_on_names_the_automation(graph):
    rows = DEP.dependents_of(graph, CONN, "entity", "OrderItem", automations=[_watch(), _automation("Daily")])
    assert ("process", "order_fulfilment") in {(r["consumer"], r["id"]) for r in rows}
    (auto,) = [r for r in rows if r["consumer"] == "automation"]
    assert auto["name"] == "Dispatch promise watch"
    assert auto["how"] == "its trigger watches the process 'order_fulfilment', which reads OrderItem"
    assert "Dispatch promise watch" in DEP.refusal("entity", "OrderItem", rows)


def test_a_link_a_promise_walks_is_depended_on(graph):
    rows = DEP.dependents_of(graph, CONN, "link", "OrderItem_RELATES_TO_Order", automations=[_watch()])
    assert {r["consumer"] for r in rows} == {"process", "automation"}
    assert DEP.dependents_of(graph, CONN, "link", "Customer_RELATES_TO_Review", automations=[_watch()]) == []


def test_an_action_a_step_runs_or_another_undoes_with_is_depended_on(graph):
    from aughor.automations.models import Effect
    graph.kinetic_actions = {
        "flag_order": KineticAction(id="flag_order", kind="annotate", object_type="Order"),
        "notify": KineticAction(id="notify", kind="side_effect", undo=Undo(action_id="flag_order", window_hours=24)),
    }
    runs = _automation("Flag late orders", effects=[Effect(kind="kinetic_action", config={"action_id": "flag_order"})])
    rows = DEP.dependents_of(graph, CONN, "action", "flag_order", automations=[runs])
    assert {(r["consumer"], r["id"]) for r in rows} == {("automation", runs.id), ("action", "notify")}
    on_order = DEP.dependents_of(graph, CONN, "entity", "Order", automations=[runs])
    assert ("action", "flag_order") in {(r["consumer"], r["id"]) for r in on_order}
    assert any(r["consumer"] == "automation" and "flag_order" in r["how"] for r in on_order)


def test_a_process_nothing_watches_has_no_dependents(graph):
    assert DEP.dependents_of(graph, CONN, "process", "order_fulfilment", automations=[_automation("Daily")]) == []


# ── the doors ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def served(graph, monkeypatch):
    from aughor.routers import ontology as ONT
    monkeypatch.setattr(ONT, "_get_ontology_graph", lambda conn, schema=None: graph)
    monkeypatch.setattr(ONT, "_resolve_schema", lambda conn, schema=None: SCHEMA)
    monkeypatch.setattr(DEP, "_automations", lambda conn: [_watch()])
    save_override(CONN, SCHEMA, OntologyOverride(target_kind="process", target_id="order_fulfilment",
                                                 fields={"declared": True, **process_fields(FULFILMENT)}))
    from fastapi.testclient import TestClient

    from aughor.api import app
    return TestClient(app)


def test_on_withdrawing_a_process_an_automation_watches_is_refused_naming_it(served, monkeypatch):
    _flag(monkeypatch, True)
    r = served.delete("/ontology/processes/order_fulfilment", params={"connection_id": CONN})
    assert r.status_code == 409 and "Dispatch promise watch" in r.json()["detail"]
    assert find_override(CONN, SCHEMA, "process", "order_fulfilment") is not None
    deps = served.get("/ontology/dependents", params={"connection_id": CONN, "kind": "process",
                                                       "target_id": "order_fulfilment"}).json()
    assert [d["name"] for d in deps["dependents"]] == ["Dispatch promise watch"]


def test_off_the_same_withdrawal_goes_ahead_as_before(served, monkeypatch):
    _flag(monkeypatch, False)
    r = served.delete("/ontology/processes/order_fulfilment", params={"connection_id": CONN})
    assert r.status_code == 200 and r.json()["removed"] is True


def test_the_history_door_reads_versions_and_a_past_day(served, monkeypatch):
    _flag(monkeypatch, True)
    moments = itertools.chain(["2026-10-02T09:00:00+00:00"], itertools.repeat("2026-10-09T09:00:00+00:00"))
    monkeypatch.setattr(lifecycle, "_now", lambda: next(moments))
    save_override(CONN, SCHEMA, _dispatch(2))
    body = served.get("/ontology/history", params={"connection_id": CONN, "kind": "process", "target_id": "dispatch",
                                                   "as_of": "2026-10-03"}).json()
    assert body["kept"] is True and body["element"] == _key()
    assert body["as_of"]["state"] == "declared" and _days(body["as_of"]["fields"]) == 2
    bad = served.get("/ontology/history", params={"connection_id": CONN, "kind": "process", "target_id": "dispatch",
                                                  "as_of": "soon"})
    assert bad.status_code == 400
