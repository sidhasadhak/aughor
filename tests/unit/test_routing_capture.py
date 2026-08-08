"""Capturing a routing correction as a proposal (Wave 2 / Layer 1.1, capture half).

The store, the existence bind, both enforcement doors and the schema annotation all
shipped; what was missing was any way for a person to CREATE a rule short of a direct
API call. This is that path, and its one non-negotiable property: **a proposal changes
nothing until a human clicks accept** (C4 — never auto-apply).

That property is structural rather than a status check. A proposal lives in its own
field, and enforcement reads only `use_instead`, so "pending guidance is inert" is true
by construction — there is no flag to forget and no status column to mis-read.
"""
from __future__ import annotations

import pytest

from aughor.ontology.overrides import (
    PROPOSED_FIELD,
    ROUTING_FIELD,
    OntologyOverride,
    find_override,
    save_override,
)
from aughor.ontology.routing import routing_rules

CONN = "capture-test"
SCHEMA = "main"


@pytest.fixture
def store(tmp_path, monkeypatch):
    from aughor.ontology import overrides as O
    monkeypatch.setattr(O, "_ROOT", tmp_path / "ontology_overrides")
    return tmp_path


def _proposal(table="v_fact_sales", scope="sales", bound=True):
    ov = OntologyOverride(
        target_kind="entity", target_id="orders",
        fields={PROPOSED_FIELD: {"table": table, "scope": scope,
                                 "reason": "net of returns", "evidence": "run-123"}},
    )
    from aughor.ontology.overrides import bind_overrides
    return bind_overrides(ov, None, (lambda sql: None) if bound else (lambda sql: "no such table"))


# ── the load-bearing property ────────────────────────────────────────────────

def test_a_proposal_is_never_enforced(store):
    """Pending guidance must not reach a prompt. Enforcement reads `use_instead`;
    a proposal is in a different field, so this holds by construction."""
    save_override(CONN, SCHEMA, _proposal())
    assert routing_rules(CONN, SCHEMA) == []


def test_a_proposal_binds_at_capture_time(store):
    """Bound while the person who volunteered it is still here, so a typo is reported
    now rather than at accept time."""
    ov = _proposal(table="v_typo", bound=False)
    assert ov.binding[PROPOSED_FIELD]["bound"] is False


def test_accepting_moves_it_across_and_it_becomes_live(store):
    """The one path from proposed to enforced."""
    save_override(CONN, SCHEMA, _proposal(scope=""))
    ov = find_override(CONN, SCHEMA, "entity", "orders")
    fields = dict(ov.fields)
    fields[ROUTING_FIELD] = {k: v for k, v in fields[PROPOSED_FIELD].items() if k != "evidence"}
    fields.pop(PROPOSED_FIELD)
    from aughor.ontology.overrides import bind_overrides
    accepted = bind_overrides(
        OntologyOverride(target_kind="entity", target_id="orders", fields=fields),
        None, lambda sql: None)
    save_override(CONN, SCHEMA, accepted)

    rules = routing_rules(CONN, SCHEMA)
    assert len(rules) == 1 and rules[0].preferred == "v_fact_sales"
    assert find_override(CONN, SCHEMA, "entity", "orders").fields.get(PROPOSED_FIELD) is None


# ── the endpoints ────────────────────────────────────────────────────────────

def _post(client, path, **kw):
    return client.post(path, **kw)


def test_propose_endpoint_stores_pending_and_reports_the_bind(client, store):
    r = _post(client, "/ontology/entities/orders/routing-proposal",
              params={"connection_id": CONN, "schema_name": SCHEMA},
              json={"table": "no_such_table_here", "scope": "sales",
                    "reason": "net of returns", "evidence": "run-123"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_id"] == "orders"
    assert body["proposed"]["table"] == "no_such_table_here"
    assert body["bound"] is False, "a table that cannot be read must not report bound"
    assert body["bind_note"]
    # and it did NOT become live
    assert routing_rules(CONN, SCHEMA) == []


def test_listing_shows_pending_proposals_with_their_verdict(client, store):
    _post(client, "/ontology/entities/orders/routing-proposal",
          params={"connection_id": CONN, "schema_name": SCHEMA},
          json={"table": "nope", "scope": "sales"})
    r = client.get("/ontology/routing-proposals",
                   params={"connection_id": CONN, "schema_name": SCHEMA})
    assert r.status_code == 200, r.text
    props = r.json()["proposals"]
    assert len(props) == 1
    assert props[0]["entity_id"] == "orders"
    assert "bound" in props[0] and "bind_note" in props[0]


def test_accepting_an_unbound_proposal_is_refused(client, store):
    """Accepting a rule that names an unreadable table would put a dead pointer into
    every prompt for this connection."""
    _post(client, "/ontology/entities/orders/routing-proposal",
          params={"connection_id": CONN, "schema_name": SCHEMA},
          json={"table": "definitely_not_a_table", "scope": "sales"})
    r = _post(client, "/ontology/entities/orders/routing-proposal/accept",
              params={"connection_id": CONN, "schema_name": SCHEMA})
    assert r.status_code == 409, r.text
    assert "never bound" in r.json()["detail"]
    assert routing_rules(CONN, SCHEMA) == []


def test_accepting_without_a_proposal_is_a_404(client, store):
    r = _post(client, "/ontology/entities/nothing_here/routing-proposal/accept",
              params={"connection_id": CONN, "schema_name": SCHEMA})
    assert r.status_code == 404, r.text


def test_proposing_does_not_wipe_an_existing_override(client, store):
    """`save_override` replaces the whole file, so capture must MERGE — otherwise
    volunteering a routing correction silently deletes the entity's description."""
    save_override(CONN, SCHEMA, OntologyOverride(
        target_kind="entity", target_id="orders",
        fields={"description": "the order line grain"}))
    _post(client, "/ontology/entities/orders/routing-proposal",
          params={"connection_id": CONN, "schema_name": SCHEMA},
          json={"table": "v_fact_sales"})
    ov = find_override(CONN, SCHEMA, "entity", "orders")
    assert ov.fields["description"] == "the order line grain"
    assert ov.fields[PROPOSED_FIELD]["table"] == "v_fact_sales"
