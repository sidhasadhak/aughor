"""SE-0 — DATA-06 for the query surface: every route that resolves a ``conn_id``
(body or path) is reachable only by the org that owns the connection.

Before this wave, the query router's owner guard saw only ``query_id`` path
params: org A could run SQL against org B's connection via /query/run (and its
siblings) in multi-tenant mode. Same conventions as test_data06_depth.py:
cross-org requests assert ONLY on the 403 (never which layer produced it);
owner requests assert "not 403" (the route may still 4xx/5xx for its own
reasons — a missing table is not an authz result); unique org ids per test
avoid shared RBAC bootstrap state; localhost mode (identity off) stays
byte-identical, pinned by the whole rest of the suite running identity-off.
"""
from __future__ import annotations


def _mk_conn(org: str, name: str) -> str:
    from aughor.db import registry
    from aughor.org.context import using_org
    with using_org(org):
        return registry.add_connection(name, "duckdb", "data/aughor.duckdb")


def test_query_run_body_conn_is_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    cid = _mk_conn("se0run_a", "se0-run-conn")
    try:
        payload = {"conn_id": cid, "sql": "SELECT 1"}
        assert client.post("/query/run", json=payload,
                           headers={"X-Aughor-Org": "se0run_b"}).status_code == 403
        assert client.post("/query/run", json=payload,
                           headers={"X-Aughor-Org": "se0run_a"}).status_code != 403
    finally:
        registry.delete_connection(cid)


def test_query_validate_and_semantic_context_are_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    cid = _mk_conn("se0val_a", "se0-val-conn")
    try:
        assert client.post("/query/validate", json={"conn_id": cid, "sql": "SELECT 1"},
                           headers={"X-Aughor-Org": "se0val_b"}).status_code == 403
        assert client.post("/query/semantic-context", json={"conn_id": cid, "question": "q"},
                           headers={"X-Aughor-Org": "se0val_b"}).status_code == 403
        assert client.post("/query/validate", json={"conn_id": cid, "sql": "SELECT 1"},
                           headers={"X-Aughor-Org": "se0val_a"}).status_code != 403
    finally:
        registry.delete_connection(cid)


def test_cross_source_join_checks_both_sides(client, monkeypatch):
    """The sneaky shape: drive from your OWN connection but point the right side at
    another org's — both ids must pass the owner check."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    mine = _mk_conn("se0xj_a", "se0-xj-mine")
    theirs = _mk_conn("se0xj_b", "se0-xj-theirs")
    try:
        assert client.post("/query/cross-source-join", json={
            "left_conn_id": mine, "left_sql": "SELECT 1 AS k", "left_key": "k",
            "right_conn_id": theirs, "right_table": "t", "right_key": "k",
        }, headers={"X-Aughor-Org": "se0xj_a"}).status_code == 403
    finally:
        registry.delete_connection(mine)
        registry.delete_connection(theirs)


def test_chat_feedback_is_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    cid = _mk_conn("se0fb_a", "se0-fb-conn")
    try:
        payload = {"conn_id": cid, "turn_id": "t1", "verdict": "helpful"}
        assert client.post("/chat/feedback", json=payload,
                           headers={"X-Aughor-Org": "se0fb_b"}).status_code == 403
        assert client.post("/chat/feedback", json=payload,
                           headers={"X-Aughor-Org": "se0fb_a"}).status_code != 403
    finally:
        registry.delete_connection(cid)


def test_conn_id_path_params_on_query_router_are_org_scoped(client, monkeypatch):
    """measure-grains / distinct / cache-invalidate live on the QUERY router, so the
    connections router's path guard never saw them."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    cid = _mk_conn("se0path_a", "se0-path-conn")
    try:
        wrong = {"X-Aughor-Org": "se0path_b"}
        mine = {"X-Aughor-Org": "se0path_a"}
        assert client.get(f"/connections/{cid}/measure-grains", headers=wrong).status_code == 403
        assert client.get(f"/connections/{cid}/distinct",
                          params={"table": "t", "column": "c"}, headers=wrong).status_code == 403
        assert client.delete(f"/query/cache/{cid}", headers=wrong).status_code == 403
        assert client.get(f"/connections/{cid}/measure-grains", headers=mine).status_code != 403
        assert client.delete(f"/query/cache/{cid}", headers=mine).status_code != 403
    finally:
        registry.delete_connection(cid)
