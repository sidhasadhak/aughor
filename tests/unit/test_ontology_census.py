"""Arc OC-0 — the ontology census (ROADMAP §3.56): what every built scope declares, what the data verified of it,
and what leans on it, counted the same way every time and journaled once a day behind `ontology.census`.

The live receipt is in the arc's status: on the study's six scopes the census reproduced the hand count of
`docs/ONTOLOGY_FIRST_STUDY_2026-10-09.md` §5 exactly, and found four built scopes the hand count had missed.
Hermetic here: the stores are faked or isolated, the journal is a fresh ledger per test.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aughor.ontology import census as CEN
from aughor.ontology.models import (
    Backing, Binding, DisplayProperty, EntityProperty, OntologyEntity, OntologyGraph, OntologyRelationship, Process,
    ProcessStage, Promise, Rollup, Segment,
)


def _entity(eid: str, **kw) -> OntologyEntity:
    base = dict(id=eid, display_name=eid, source_tables=[eid.lower()], identity_key="id", grain_verified=True)
    base.update(kw)
    return OntologyEntity(**base)


def _link(rid: str, **kw) -> OntologyRelationship:
    base = dict(id=rid, from_entity="Line", to_entity="Order", cardinality="N:1", join_sql="l.order_id = o.id",
                from_table="line", from_col="order_id", to_table="orders", to_col="id")
    base.update(kw)
    return OntologyRelationship(**base)


def _graph() -> OntologyGraph:
    order = _entity(
        "Order",
        backing=Backing(kind="table", table="orders", primary_key="id", verified=True),
        display_property=DisplayProperty(name="id", verified=True),
        bindings=[Binding(name="lines", kind="detail", table="line", key="order_id", verified=True,
                          rollups={"n": Rollup(column="id", agg="count")})],
        segments={"open": Segment(id="open", display_name="Open", verified=True),
                  "late": Segment(id="late", display_name="Late", verified=False)},
        properties={"id": EntityProperty(name="id", description="the order's key"),
                    "status": EntityProperty(name="status")})
    line = _entity("Line", absorbed_into="Order", backing=Backing(kind="table", table="line", verified=False))
    review = _entity("Review", origin="human", backing=Backing(kind="query", sql="SELECT 1 AS id", verified=True))
    process = Process(id="fulfilment", entity="Order", stages=[
        ProcessStage(name="placed", timestamp="created_at"),
        ProcessStage(name="shipped", timestamp="shipped_at", promise=Promise(within_days=2))])
    return OntologyGraph(
        connection_id="c", schema_name="s", schema_fingerprint="x",
        entities={"Order": order, "Line": line, "Review": review},
        relationships={"a": _link("a", name="belongs_to", name_origin="human", measured_cardinality="N:1"),
                       "b": _link("b", name="of_order", name_origin="model"),
                       "c": _link("c", verb="relates to")},
        processes={"fulfilment": process})


# ── what a scope declares and what the data verified ─────────────────────────────────────

def test_a_scope_counts_what_it_declares():
    declared = CEN.scope_census(_graph())["declared"]
    assert declared["entities"] == 3
    assert declared["one_table_each"] == 2               # Review is a person's, backed by a query
    assert declared["query_backed"] == 1
    assert declared["parts"] == 1 and declared["with_detail_binding"] == 1
    assert declared["promises"] == 1 and declared["processes"] == 1
    assert declared["segments"] == 2


def test_a_link_is_named_by_its_name_not_by_the_enrichers_verb():
    # theLook's twelve links all carry a verb; eight carry a name — the study's §5 counted eight.
    declared = CEN.scope_census(_graph())["declared"]
    assert declared["links"] == 3
    assert declared["links_named"] == 2
    assert declared["links_named_by_a_person"] == 1


def test_a_scope_counts_what_the_data_verified():
    measured = CEN.scope_census(_graph())["measured"]
    assert measured["backing_verified"] == {"of": 3, "n": 2}
    assert measured["display_property_verified"] == {"of": 3, "n": 1}
    assert measured["links_counted"] == {"of": 3, "n": 1}
    assert measured["bindings_verified"] == {"of": 1, "n": 1}
    assert measured["segments_verified"] == {"of": 2, "n": 1}
    assert measured["properties_described"] == {"of": 2, "n": 1}


# ── the whole install: built scopes only, never built here ────────────────────────────────

def test_the_reading_adds_scopes_and_lists_a_connection_with_nothing_built(monkeypatch):
    graph = _graph()
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda *a, **k: [{"id": "c", "name": "Shop"}, {"id": "empty", "name": "New"}])
    monkeypatch.setattr("aughor.ontology.store.list_schemas", lambda cid: ["s", "t"] if cid == "c" else [])
    built: list[tuple] = []

    def load(cid, schema=None):
        built.append((cid, schema))
        return graph
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", load)
    monkeypatch.setattr(CEN, "consumption", lambda: {})
    reading = CEN.take_census()
    assert [s["schema"] for s in reading["scopes"]] == ["s", "t"]
    assert reading["totals"]["declared"]["entities"] == 6
    assert reading["totals"]["measured"]["backing_verified"] == {"of": 6, "n": 4}
    assert reading["not_built"] == ["empty"]
    assert ("empty", None) not in built                  # a connection with no cached ontology is not read


# ── what leans on it ───────────────────────────────────────────────────────────────────────

def test_what_leans_on_the_ontology_is_counted_and_an_unreadable_store_is_said(monkeypatch):
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.record.claims import About, Claim, Statement

    autos = [
        Automation(name="watch", conn_id="c", conditions=[Condition(kind="promise_breached", config={"process": "f"})],
                   effects=[Effect(kind="investigate", config={"question": "why"})]),
        Automation(name="flag", conn_id="c", conditions=[Condition(kind="schedule", config={"cron": "0 7 * * *"})],
                   effects=[Effect(kind="kinetic_action", config={"action_id": "flag_order"})]),
        Automation(name="daily", conn_id="c", conditions=[Condition(kind="schedule", config={"cron": "0 7 * * *"})],
                   effects=[Effect(kind="investigate", config={"question": "what"})]),
    ]
    claims = [
        Claim(kind="observation", tier="measured", statement=Statement(text="a", metric="revenue")),
        Claim(kind="observation", tier="measured", about=About(kind="type", key="Order"),
              statement=Statement(text="b", object_set="late_dispatch"), definition_version="r3"),
    ]
    monkeypatch.setattr("aughor.automations.store.list_automations", lambda *a, **k: autos)
    monkeypatch.setattr("aughor.record.claims.list_claims", lambda **k: claims)

    def unreadable(**k):
        raise RuntimeError("decisions store is locked")
    monkeypatch.setattr("aughor.record.decisions.list_decisions", unreadable)
    monkeypatch.setattr("aughor.record.mission.list_missions", lambda **k: [])

    out = CEN.consumption()
    assert out["automations"] == {"total": 3, "read_the_ontology": 2, "on_a_promise": 1, "run_a_declared_action": 1}
    assert out["record"]["claims"] == 2
    assert out["record"]["about_the_ontology"] == 1
    assert out["record"]["citing_a_metric"] == 1
    assert out["record"]["citing_a_segment"] == 1
    assert out["record"]["citing_a_definition_version"] == 1
    assert out["missions"] == 0
    assert out["decisions"] is None and "locked" in out["unread"]["decisions"]   # said, never a zero


# ── once a day, behind the flag ─────────────────────────────────────────────────────────────

@pytest.fixture
def journal(tmp_path, monkeypatch):
    from aughor.kernel.ledger import Ledger
    ledger = Ledger(str(tmp_path / "system.db"))
    monkeypatch.setattr(Ledger, "default", classmethod(lambda cls: ledger))
    monkeypatch.setattr(CEN, "take_census",
                        lambda: {"totals": {"declared": {"entities": 52}}, "scopes": [], "not_built": [],
                                 "leaned_on": {"record": {"claims": 192}}})
    return ledger


def _flag(monkeypatch, on: bool):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: on and name == "ontology.census")


def test_off_nothing_is_read_or_written(journal, monkeypatch):
    _flag(monkeypatch, False)
    monkeypatch.setattr(CEN, "take_census", lambda: pytest.fail("the census was read with the flag off"))
    assert CEN.record_if_due() is None
    assert journal.events(kind=CEN.EVENT_KIND) == []


def test_on_one_reading_a_day(journal, monkeypatch):
    _flag(monkeypatch, True)
    now = datetime.now(timezone.utc)
    assert CEN.record_if_due(now) is not None
    assert CEN.record_if_due(now + timedelta(hours=2)) is None          # not due again the same day
    assert len(journal.events(kind=CEN.EVENT_KIND)) == 1
    assert CEN.record_if_due(now + timedelta(hours=25)) is not None     # due the next day
    readings = CEN.history()
    assert len(readings) == 2
    assert readings[0]["totals"] == {"declared": {"entities": 52}}
    assert readings[0]["leaned_on"] == {"record": {"claims": 192}}


def test_the_kind_is_catalogued_and_off_the_governance_feed():
    from aughor.govern.audit_categories import NON_GOVERNANCE_KINDS
    from aughor.kernel.events import CATALOGUE
    assert CEN.EVENT_KIND in CATALOGUE and CEN.EVENT_KIND in NON_GOVERNANCE_KINDS


def test_the_door_serves_the_reading_and_the_kept_readings(journal, monkeypatch):
    from fastapi.testclient import TestClient

    from aughor.api import app
    _flag(monkeypatch, True)
    CEN.record_if_due()
    body = TestClient(app).get("/ontology/census").json()
    assert body["reading"]["totals"] == {"declared": {"entities": 52}}
    assert len(body["history"]) == 1
