"""Arc OC-3 — an automation's `source_change` / `entity_appears` trigger may name the entity it watches
(ROADMAP §3.56).

Before: a trigger named a table, so what it was about was a table name the ontology had to translate, and a release
could only guess which automations a change to an entity touched. Now the door reads the entity's table from its
backing on the automation's connection and keeps both; the probe reads it again on every tick, so the trigger follows
the entity; the run history names the entity; and the dependents index and the census read it. An unknown entity, or
one backed by a query (a SELECT has no table version to watch), is refused with why.
"""
from __future__ import annotations

import pytest

from aughor.ontology.models import Backing, OntologyEntity, OntologyGraph

CONN = "triggers-t"


def _graph() -> OntologyGraph:
    order = OntologyEntity(id="Order", display_name="Order", source_tables=["orders"], identity_key="order_id",
                           grain_verified=True, backing=Backing(kind="table", table="orders", verified=True))
    review = OntologyEntity(id="Review", display_name="Review", source_tables=[], identity_key="id",
                            grain_verified=True, backing=Backing(kind="query", sql="SELECT 1 AS id", verified=True))
    return OntologyGraph(connection_id=CONN, schema_name="shop", schema_fingerprint="x",
                         entities={"Order": order, "Review": review}, table_to_entity={"orders": "Order"})


@pytest.fixture
def client(monkeypatch):
    graph = _graph()
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: graph)
    from fastapi.testclient import TestClient

    from aughor.api import app
    return TestClient(app)


def _body(**config) -> dict:
    return {"name": "New orders", "conn_id": CONN, "enabled": False,
            "conditions": [{"kind": "entity_appears", "config": config}],
            "effects": [{"kind": "investigate", "config": {"question": "what arrived?"}}]}


def test_a_trigger_names_its_entity_and_keeps_the_table_it_reads(client):
    r = client.post("/automations", json=_body(entity="Order"))
    assert r.status_code == 200, r.text
    (cond,) = r.json()["conditions"]
    assert cond["config"] == {"entity": "Order", "table": "orders"}
    from aughor.automations.models import Condition
    assert Condition(kind="entity_appears", config=cond["config"]).describe() == "entity_appears(Order)"


@pytest.mark.parametrize("entity, says", [("Refund", "no entity 'Refund'"), ("Review", "backed by a query")])
def test_an_entity_with_no_table_to_watch_is_refused(client, entity, says):
    r = client.post("/automations", json=_body(entity=entity))
    assert r.status_code == 422 and says in r.json()["detail"]


def test_the_probe_reads_the_entitys_table_again_on_every_tick(monkeypatch):
    from aughor.automations import probes
    from aughor.automations.models import Automation, Condition, Effect
    auto = Automation(name="x", conn_id=CONN, conditions=[Condition(kind="entity_appears",
                                                                    config={"entity": "Order", "table": "orders"})],
                      effects=[Effect(kind="investigate", config={"question": "q"})])
    monkeypatch.setattr("aughor.ontology.keys.entity_table", lambda conn, entity: "orders_v2")   # its backing moved
    assert probes._watched_table(auto.conditions[0], auto) == "orders_v2"
    plain = Condition(kind="source_change", config={"table": "events"})
    assert probes._watched_table(plain, auto) == "events"


def test_a_trigger_keyed_to_an_entity_relies_on_it_and_is_counted(client):
    from aughor.automations.store import list_automations
    from aughor.ontology.dependents import dependents_of
    from aughor.ontology.keys import keyed_counts
    assert client.post("/automations", json=_body(entity="Order")).status_code == 200
    autos = [a for a in list_automations(conn_id=CONN)]
    rows = dependents_of(_graph(), CONN, "entity", "Order", automations=autos)
    assert any(r["consumer"] == "automation" and "watches Order objects" in r["how"] for r in rows)
    triggers = keyed_counts()["triggers"]
    assert triggers["n"] >= 1 and triggers["of"] >= triggers["n"]
