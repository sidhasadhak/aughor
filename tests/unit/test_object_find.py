"""Arc FA, FA-1 — an object is found by the name it goes by, across entities (ROADMAP §3.60).

Measured 2026-10-26: an object could be found only from inside its entity (the search box's ``contains`` reads one
entity's title), so ⌘K could not find "Alice Brown" without being told she is a customer. ``POST /objects/find`` looks
across the served entities through the object door's own compiler, on one connection — and says how many it searched,
why it skipped each other one, which have more matches than it shows, and what a row policy or a mask kept from the
reader. Held on the seeded samples warehouse through the real DuckDB connection, the real compiler and the real route.
"""
from __future__ import annotations

import pytest

from aughor.ontology.models import RowPolicy, Sensitivity
from aughor.semantic import object_find as F
from tests.unit.test_object_actions import CONN, db, graph  # noqa: F401 — fixtures by name

PARAMS = {"connection_id": CONN, "schema_name": "ecommerce"}


@pytest.fixture
def served(graph, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: graph)
    return graph


def _find(client, q: str, **body):
    r = client.post("/objects/find", params=PARAMS, json={"q": q, **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_an_object_is_found_by_its_name_and_the_search_says_what_it_read(served, client):
    out = _find(client, "alice smith")
    assert out["path"] == "found" and out["hits"]
    assert {h["type"] for h in out["hits"]} == {"customer"}
    assert all(h["title"] == "Alice Smith" for h in out["hits"])
    hit = out["hits"][0]
    assert hit["key"].startswith("C") and hit["entity_label"] and hit["type_id"] == "Customer"
    assert (out["searched"], out["of"], out["said"]) == (2, 5, "searched 2 of 5 entities")
    skipped = {s["entity"]: s["why"] for s in out["skipped"]}
    assert set(skipped) == {"order", "order_item", "review"}
    assert all(why.startswith("named by its key") for why in skipped.values())


def test_more_matches_than_shown_are_said_and_the_page_is_capped(served, client):
    out = _find(client, "lite", limit_per_entity=3)
    products = [h for h in out["hits"] if h["type"] == "product"]
    assert len(products) == 3 and all("lite" in h["title"].lower() for h in products)
    assert out["more"] == ["product"]


def test_the_entities_past_the_cap_are_listed_with_why(served, client, monkeypatch):
    monkeypatch.setattr(F, "MAX_ENTITIES", 1)
    out = _find(client, "an")
    assert out["searched"] == 1 and out["said"] == "searched 1 of 5 entities"
    assert any(s["why"] == "past the cap — one search reads 1 entity" for s in out["skipped"])


def test_a_search_out_of_time_says_which_it_did_not_reach(graph, db):  # noqa: F811
    found = F.find_objects(graph, lambda sql: db.execute("t", sql), "alice", budget_ms=-1)
    assert found["searched"] == 0 and found["hits"] == []
    assert sum(s["why"].startswith("past the time") for s in found["skipped"]) == 2


def test_too_few_letters_is_refused_with_why(served, client):
    out = _find(client, "a")
    assert out["path"] == "refused" and "at least 2 characters" in out["refused"]


# ── what the reader may see ───────────────────────────────────────────────────────────────────

@pytest.fixture
def policed(served, monkeypatch):
    from aughor.rbac.groups import add_member, upsert_group
    monkeypatch.setenv("AUGHOR_ONTOLOGY_SECURITY", "1")
    for group, members in (("germany", ["user:ana"]), ("finance", ["user:ben"])):
        upsert_group("default", group, group.capitalize())
        for m in members:
            add_member("default", group, m)
    served.entities["Customer"].row_policies = [
        RowPolicy(group="germany", conditions=[{"path": "country", "op": "=", "value": "DE"}]),
        RowPolicy(group="finance", conditions=[])]
    return served


def _customers(out) -> list[str]:
    return [h["key"] for h in out["hits"] if h["type"] == "customer"]


def test_a_row_policy_narrows_what_a_reader_finds_and_says_so(policed, client, monkeypatch, db):  # noqa: F811
    # The seeded shop: every customer in DE is a Young, and every Davis lives elsewhere.
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana")
    young = _find(client, "young")
    keys = ", ".join(f"'{k}'" for k in _customers(young))
    countries = {r[0] for r in db.execute("t", f"SELECT DISTINCT country FROM customers WHERE customer_id IN ({keys})").rows}
    assert _customers(young) and countries == {"DE"}
    davis = _find(client, "davis")
    assert _customers(davis) == [] and davis["searched"] == 2          # searched, and none of hers matched
    assert davis["withheld"] == ["Customer"]
    assert "only the Customer objects user:ana may see" in davis["withheld_said"][0]   # said, never "no such customer"
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ben")
    assert _customers(_find(client, "davis"))


def test_a_masked_name_is_not_searched_and_says_why(policed, client, monkeypatch):
    policed.entities["Customer"].sensitive = {"full_name": Sensitivity(level="confidential", visible_to=["finance"])}
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana")
    out = _find(client, "alice")
    assert not [h for h in out["hits"] if h["type"] == "customer"]
    why = next(s["why"] for s in out["skipped"] if s["entity"] == "customer")
    assert why.startswith("its name is masked for you") and "finance may read it" in why
    assert out["masked"] == ["Customer.full_name"] and out["said"] == "searched 1 of 5 entities"
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ben")
    assert [h for h in _find(client, "alice")["hits"] if h["type"] == "customer"]


def test_with_completeness_on_the_answer_says_withheld_as_the_object_doors_do(policed, client, monkeypatch):
    monkeypatch.setenv("AUGHOR_OBJECTS_COMPLETENESS", "1")
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana")
    said = _find(client, "davis")["completeness"]
    assert said["state"] == "withheld" and said["withheld"] == ["Customer"]
    assert "only the Customer objects user:ana may see" in said["said"]
