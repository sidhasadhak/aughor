"""Every object read says how complete it is (Arc ED, ED-6; ROADMAP §3.58).

Measured 2026-10-25: every connection hands back at most ``db.connection.MAX_ROWS`` (500) rows, and the object query
door said ``truncated`` only past 1,000 — so a cut read reached its reader as complete. And the linked-objects page
read ``SELECT *`` with no mask: a sensitive property emptied on an object's own page was shown in full on the page of
the objects linked to it (OC-7's law, closed here at that door).

With ``objects.completeness`` on, every object door says one typed thing — complete · truncated · withheld · refused —
with what it showed, what it withheld and how long it took, and the contract describes it. Held on the seeded samples
warehouse through the real DuckDB connection, the real compiler and the real routes. The falsifier: an object read cut
at the cap that says complete.
"""
from __future__ import annotations

import pytest

from aughor.semantic import completeness as C
from tests.unit.test_object_actions import CONN, ORDER, db, graph  # noqa: F401 — fixtures by name
from tests.unit.test_ontology_security import SHIPPED, secured  # noqa: F401 — fixtures by name

ON = {"AUGHOR_OBJECTS_COMPLETENESS": "1"}
PARAMS = {"connection_id": CONN, "schema_name": "ecommerce"}
BY_STATUS = {"object_type": "order", "measures": [{"name": "n", "agg": "count"}], "by": ["status"]}


@pytest.fixture
def served(graph, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: graph)
    return graph


@pytest.fixture
def on(monkeypatch):
    for k, v in ON.items():
        monkeypatch.setenv(k, v)


def _as(monkeypatch, who: str) -> None:
    monkeypatch.setenv("AUGHOR_LOCAL_USER", who)


def _shipping_customer(db) -> str:  # noqa: F811
    """A customer with an order Ana may see — read unfiltered: no request acts for anyone here."""
    result = db.execute("t", "SELECT customer_id FROM orders WHERE status IN ('shipped', 'delivered') "
                             "ORDER BY customer_id LIMIT 1")
    assert not result.error and result.rows, result.error
    return str(result.rows[0][0])


def _ok(r):
    assert r.status_code == 200, r.text
    return r.json()


# ── the falsifier ───────────────────────────────────────────────────────────────────────────────────────────────

def test_a_query_cut_at_the_connections_cap_says_truncated(served, client, on, monkeypatch):
    every = _ok(client.post("/objects/query", params=PARAMS, json=BY_STATUS))
    assert every["completeness"]["state"] == "complete" and len(every["rows"]) > 3
    monkeypatch.setattr("aughor.db.connection.MAX_ROWS", 3)                    # the connection's own cap, lowered
    cut = _ok(client.post("/objects/query", params=PARAMS, json=BY_STATUS))
    said = cut["completeness"]
    assert len(cut["rows"]) == 3 and said["state"] == "truncated" and said["shown"] == 3
    assert said["said"].startswith("the first 3 rows") and cut["truncated"] is True   # the old boolean, made true
    assert isinstance(said["took_ms"], int) and said["took_ms"] >= 0


def test_off_a_cut_read_answers_as_it_did_and_carries_no_completeness(served, client, monkeypatch):
    monkeypatch.setattr("aughor.db.connection.MAX_ROWS", 3)
    out = _ok(client.post("/objects/query", params=PARAMS, json=BY_STATUS))
    assert "completeness" not in out and out["truncated"] is False and len(out["rows"]) == 3   # the defect, as it was


# ── withheld, said ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_row_policy_reads_withheld_at_the_query_and_listing_doors_with_its_words(secured, client, on, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: secured)
    _as(monkeypatch, "ana")
    count = _ok(client.post("/objects/query", params=PARAMS,
                            json={"object_type": "order", "measures": [{"name": "n", "agg": "count"}]}))["completeness"]
    assert count["state"] == "withheld" and count["withheld"] == ["Order"]
    assert "only the Order objects user:ana may see are shown" in count["said"]
    listed = _ok(client.post("/objects/list", params=PARAMS, json={"entity": "Order", "columns": ["status"], "limit": 2}))
    said = listed["completeness"]
    assert said["state"] == "withheld" and said["shown"] == 2 and said["of"] == listed["total"] > 2


def test_the_object_page_says_the_property_it_emptied(secured, client, on, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: secured)
    _as(monkeypatch, "ana")
    said = _ok(client.get(f"/objects/order/{ORDER}", params=PARAMS))["completeness"]
    assert said["state"] == "withheld" and said["masked"] == ["total_amount"] and said["shown"] == 1
    assert "masked for user:ana" in said["said"]


def test_the_linked_page_masks_what_an_objects_own_page_masks(secured, db, client, monkeypatch):  # noqa: F811
    """OC-7 at the linked page — with object security on and completeness OFF: the mask is the security law's."""
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: secured)
    customer = _shipping_customer(db)
    _as(monkeypatch, "ana")
    page = _ok(client.get(f"/objects/Customer/{customer}/links/customer_to_order", params={**PARAMS, "limit": 50}))
    at = page["columns"].index("total_amount")
    assert page["rows"] and all(row[at] is None for row in page["rows"])
    assert {row[page["columns"].index("status")] for row in page["rows"]} <= SHIPPED
    assert "masked for user:ana" in page["masked"]["total_amount"]
    assert any("only the Order objects user:ana may see are shown" in c for c in page["caveats"])
    assert "completeness" not in page
    _as(monkeypatch, "ben")                                                   # finance reads the amount
    assert "masked" not in _ok(client.get(f"/objects/Customer/{customer}/links/customer_to_order", params=PARAMS))


def test_the_linked_page_says_withheld_when_completeness_is_on(secured, client, on, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: secured)
    _as(monkeypatch, "ana")
    said = _ok(client.get("/objects/Customer/C00001/links/customer_to_order", params=PARAMS))["completeness"]
    assert said["state"] == "withheld" and said["withheld"] == ["Order"] and said["masked"] == ["total_amount"]


def test_titles_say_the_first_of_more(served, client, on, monkeypatch):
    monkeypatch.setattr("aughor.semantic.object_instances.MAX_TITLES", 1)
    said = _ok(client.post("/objects/titles", params=PARAMS,
                           json={"object_type": "customer", "keys": ["C00001", "C00002"]}))["completeness"]
    assert said["state"] == "truncated" and said["of"] == 2 and said["shown"] <= 1


# ── refused, and off ────────────────────────────────────────────────────────────────────────────────────────────

def test_a_refusal_says_refused_with_its_reason(served, client, on):
    out = _ok(client.post("/objects/query", params=PARAMS,
                          json={"object_type": "no_such_thing", "measures": [{"name": "n", "agg": "count"}]}))
    assert out["path"] == "refused" and out["completeness"]["state"] == "refused"
    assert out["completeness"]["said"] == out["refused"] and out["completeness"]["shown"] == 0


def test_off_no_object_door_carries_it(served, client):
    answers = [client.post("/objects/query", params=PARAMS, json=BY_STATUS),
               client.post("/objects/list", params=PARAMS, json={"entity": "Order", "columns": ["status"], "limit": 2}),
               client.get(f"/objects/order/{ORDER}", params=PARAMS),
               client.get("/objects/Customer/C00001/links/customer_to_order", params=PARAMS),
               client.post("/objects/titles", params=PARAMS, json={"object_type": "customer", "keys": ["C00001"]})]
    assert all("completeness" not in _ok(r) for r in answers)


# ── the contract, and the one definition ────────────────────────────────────────────────────────────────────────

def test_the_contract_describes_it_for_a_program(graph, on):  # noqa: F811
    from aughor.ontology.builder_doors import ontology_contract, typescript
    contract = ontology_contract(graph, "r@1")
    assert contract["completeness"]["properties"]["state"]["enum"] == list(C.STATES)
    ts = typescript(contract)
    assert "export interface Completeness {" in ts
    assert "  state: 'complete' | 'truncated' | 'withheld' | 'refused';" in ts and "  withheld: string[];" in ts


def test_off_the_contract_is_as_before(graph):  # noqa: F811
    from aughor.ontology.builder_doors import ontology_contract, typescript
    contract = ontology_contract(graph, "r@1")
    assert "completeness" not in contract and "Completeness" not in typescript(contract)


def test_one_state_by_precedence_and_every_list_said():
    assert C.of_read(shown=0, took_ms=1, refused="no", truncated=True, withheld=["A"])["state"] == "refused"
    both = C.of_read(shown=3, took_ms=1, truncated=True, withheld=["A"], said=["only some A"])
    assert both["state"] == "truncated" and both["withheld"] == ["A"] and "only some A" in both["said"]
    assert C.of_read(shown=1, took_ms=1, masked=["amount"])["said"] == "amount is withheld from you"
    assert C.of_read(shown=1, took_ms=1) == {"state": "complete", "shown": 1, "of": None, "withheld": [], "masked": [],
                                             "said": "", "took_ms": 1}


def test_a_read_is_cut_when_the_connection_counted_more_than_it_returned():
    class R:
        def __init__(self, rows, n):
            self.rows, self.row_count = rows, n
    assert C.cut(R([[1]] * 3, 4)) and not C.cut(R([[1]] * 3, 3)) and not C.cut(R([], 0))
