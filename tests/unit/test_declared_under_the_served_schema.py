"""A declaration is written under the schema of the graph the screen shows (2026-10-10).

A connection is browsed under the schema its configuration names and its ontology may be cached under another — the
scratch fixture is configured `main` and was built as `default`; a sheets connection is browsed as `spotify` and
cached as `default`. Every read serves the one built graph and overlays the declarations kept under ITS schema
(`_get_ontology_graph`, `_served_scope`); the declare doors wrote under the name the request carried. A declaration
made from the screen there was kept where nothing reads it, and the door's own read-back failed.
"""
from __future__ import annotations

import json

import pytest

from aughor.ontology import overrides as OV
from aughor.ontology.models import OntologyGraph
from aughor.ontology.overrides import find_override
from tests.unit.test_action_design import ESCALATE
from tests.unit.test_object_bindings import GRAPH

CONN = "served-scope-t"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aughor.api import app
    from aughor.ontology import store as ST
    from aughor.util.json_store import KeyedJsonStore
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    ST.save_ontology(CONN, "ecommerce", "fp", OntologyGraph.model_validate(json.loads(GRAPH.read_text())))
    monkeypatch.setattr("aughor.govern.guard", lambda *a, **k: None)
    return TestClient(app)


def test_an_action_declared_from_the_screen_is_kept_where_the_screen_reads_it(client):
    params = {"connection_id": CONN, "schema_name": "main"}                      # the configured name, never built
    r = client.put("/ontology/kinetic-actions/escalate_to_carrier", params=params, json=ESCALATE)
    assert r.status_code == 200, r.text
    assert find_override(CONN, "ecommerce", "action", "escalate_to_carrier") is not None
    assert find_override(CONN, "main", "action", "escalate_to_carrier") is None
    served = client.get("/ontology", params=params)
    assert served.status_code == 200, served.text
    assert "escalate_to_carrier" in served.json()["kinetic_actions"]
