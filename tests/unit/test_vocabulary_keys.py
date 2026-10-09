"""Arc OC-3 — words people use, keyed to the entity and property they name (2026-10-09).

A vocabulary entry named a table, `table.column`, a metric or a term; the ontology's entities and properties it could
not name, so the item stood deferred: "the schema linker and the SQL synonym block expect tables and columns". An entry
may now name an entity (`Order`) or a property (`Order.status`), and each reader that works in tables and columns reads
it as the table and column it comes from, at the moment it reads it. Table and column entries are proposed a key, as a
metric is; a person confirms it through `PUT /ontology/vocabulary/key`.
"""
from __future__ import annotations

import json

import pytest

from aughor.ontology import vocabulary as V
from aughor.ontology.framing import frame_question
from aughor.ontology.keys import keyed_counts, propose_synonym_key, subject_columns, vocabulary_keys
from aughor.ontology.models import OntologyGraph
from tests.unit.test_object_bindings import GRAPH

CONN = "vocab-keys"


@pytest.fixture
def graph(monkeypatch, tmp_path):
    g = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    monkeypatch.setenv("AUGHOR_VOCABULARY_ROOT", str(tmp_path / "vocabulary"))
    monkeypatch.setattr(V, "_served_graph", lambda conn: g)
    return g


def test_an_entity_or_a_property_is_read_as_the_table_and_column_it_comes_from(graph):
    assert subject_columns(graph, "entity", "Order") == ("orders", "")
    assert subject_columns(graph, "property", "Order.status") == ("orders", "status")
    assert subject_columns(graph, "property", "order.STATUS") == ("orders", "status")          # by api name, any case
    for kind, subject in (("entity", "Warehouse"), ("property", "Order.no_such"), ("table", "orders")):
        assert subject_columns(graph, kind, subject) is None


def test_a_table_or_column_entry_is_proposed_the_entity_or_property_it_names(graph):
    assert propose_synonym_key("table", "orders", graph)["subject"] == "Order"
    assert propose_synonym_key("column", "ecommerce.orders.status", graph) == {
        "kind": "property", "subject": "Order.status", "why": "Order reads status as status"}
    assert propose_synonym_key("column", "orders.no_such", graph)["kind"] == ""
    assert propose_synonym_key("metric", "revenue", graph)["why"] == "a metric is not a table or a column — nothing to key it to"
    assert propose_synonym_key("table", "orders", None)["why"] == "no ontology is built for this scope"


def test_the_sql_writer_reads_a_keyed_entry_with_the_column_it_comes_from(graph):
    V.add_synonym(CONN, "property", "Order.status", "order state")
    V.add_synonym(CONN, "entity", "Order", "purchases")
    V.add_synonym(CONN, "column", "orders.total_amount", "sales value")
    block = V.build_synonyms_block(CONN)
    assert '- "order state" means property Order.status (column orders.status)' in block
    assert '- "purchases" means entity Order (table orders)' in block
    assert '- "sales value" means column orders.total_amount' in block                        # unchanged


def test_the_linker_is_handed_the_table_and_column_and_never_a_name_nothing_matches(graph):
    V.add_synonym(CONN, "property", "Order.status", "order state")
    V.add_synonym(CONN, "property", "Order.gone", "lost words")
    expansion = V.synonym_expansion(CONN)
    assert expansion["order state"] == {"orders", "status"}
    assert "lost words" not in expansion


def test_a_question_frames_a_keyed_word_onto_its_property(graph):
    words = [V.Synonym(CONN, "property", "Order.status", "order state")]
    frame = frame_question("how many orders by order state", graph, synonyms=words)
    assert any(t.kind == "property" and t.target == "Order.status" and t.text == "order state" for t in frame.terms), frame.terms


def test_the_keys_read_and_the_census_say_how_far_the_vocabulary_is_keyed(graph):
    V.add_synonym(CONN, "column", "orders.status", "order state")
    V.add_synonym(CONN, "entity", "Order", "purchases")
    V.add_synonym(CONN, "term", "gmv", "gross merchandise value")
    rows = {r["synonym"]: r for r in vocabulary_keys(CONN, graph)}
    assert set(rows) == {"order state", "purchases"}                                           # a term is not keyable
    assert rows["order state"]["keyed"] is False and rows["order state"]["proposal"]["subject"] == "Order.status"
    assert rows["purchases"]["keyed"] is True and rows["purchases"]["reads"] == {"table": "orders", "column": ""}
    assert keyed_counts()["vocabulary"] == {"of": 2, "n": 1}


# ── the door ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def served(graph, monkeypatch):
    from aughor.routers import ontology as ONT
    monkeypatch.setattr(ONT, "_get_ontology_graph", lambda conn, schema=None: graph)
    monkeypatch.setattr("aughor.govern.guard", lambda *a, **k: None)
    from fastapi.testclient import TestClient

    from aughor.api import app
    return TestClient(app)


def test_a_person_keys_an_entry_and_the_table_column_entry_it_replaces_goes(served):
    V.add_synonym(CONN, "column", "orders.status", "order state", source="mined")
    body = {"subject_kind": "column", "subject_id": "orders.status", "synonym": "order state",
            "kind": "property", "subject": "Order.status"}
    r = served.put("/ontology/vocabulary/key", params={"connection_id": CONN}, json=body)
    assert r.status_code == 200, r.text
    assert [(s.subject_kind, s.subject_id, s.source, s.note) for s in V.synonyms_for(CONN)] == [
        ("property", "Order.status", "human", "keyed from column orders.status")]
    keys = served.get("/ontology/keys", params={"connection_id": CONN}).json()["vocabulary"]
    assert keys[0]["keyed"] and keys[0]["reads"] == {"table": "orders", "column": "status"}


def test_the_door_refuses_a_key_nothing_reads_and_an_entry_that_is_not_there(served):
    V.add_synonym(CONN, "column", "orders.status", "order state")
    wrong = {"subject_kind": "column", "subject_id": "orders.status", "synonym": "order state",
             "kind": "property", "subject": "Order.no_such"}
    assert served.put("/ontology/vocabulary/key", params={"connection_id": CONN}, json=wrong).status_code == 400
    missing = {**wrong, "synonym": "never said", "subject": "Order.status"}
    assert served.put("/ontology/vocabulary/key", params={"connection_id": CONN}, json=missing).status_code == 404
    assert [s.subject_kind for s in V.synonyms_for(CONN)] == ["column"]                         # nothing changed
