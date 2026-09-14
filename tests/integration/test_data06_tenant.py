"""DATA-06 — tenant enforcement on the connections read path.

When AUGHOR_REQUIRE_IDENTITY is on, a caller sees/acts on only their own org's
connections; shared builtins stay visible to everyone; localhost mode (flag off)
is unchanged.
"""
from __future__ import annotations


def test_list_connections_store_filter(monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.org.context import using_org

    with using_org("orgX"):
        cx = registry.add_connection("x-conn", "duckdb", "data/aughor.duckdb")
    with using_org("orgY"):
        cy = registry.add_connection("y-conn", "duckdb", "data/aughor.duckdb")
    try:
        with using_org("orgX"):
            ids = {c["id"] for c in registry.list_connections()}
        assert cx in ids, "org sees its own connection"
        assert cy not in ids, "org must NOT see another org's connection"
        # shared builtins remain visible
        assert "fixture" in ids
    finally:
        registry.delete_connection(cx)
        registry.delete_connection(cy)


def test_list_connections_unfiltered_in_localhost_mode(monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    from aughor.db import registry
    from aughor.org.context import using_org

    with using_org("orgX"):
        cx = registry.add_connection("x-conn2", "duckdb", "data/aughor.duckdb")
    try:
        # identity off → no filtering, every connection visible regardless of org ctx
        with using_org("orgY"):
            ids = {c["id"] for c in registry.list_connections()}
        assert cx in ids
    finally:
        registry.delete_connection(cx)


def test_connections_endpoint_is_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.org.context import using_org

    with using_org("orgA"):
        cid = registry.add_connection("orgA-conn", "duckdb", "data/aughor.duckdb")
    try:
        # orgA sees its connection in the list; orgB does not.
        seen_a = {c["id"] for c in client.get("/connections", headers={"X-Aughor-Org": "orgA"}).json()}
        seen_b = {c["id"] for c in client.get("/connections", headers={"X-Aughor-Org": "orgB"}).json()}
        assert cid in seen_a
        assert cid not in seen_b
        assert "fixture" in seen_b  # shared builtin still visible

        # A by-id route is blocked for the wrong org, allowed for the owner.
        r_forbidden = client.delete(f"/connections/{cid}", headers={"X-Aughor-Org": "orgB"})
        assert r_forbidden.status_code == 403
        r_ok = client.delete(f"/connections/{cid}", headers={"X-Aughor-Org": "orgA"})
        assert r_ok.status_code == 204
    finally:
        registry.delete_connection(cid)  # idempotent cleanup


def test_identity_required_returns_401_without_header(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    r = client.get("/connections")  # no X-Aughor-Org
    assert r.status_code == 401


def test_investigations_carry_org_id_and_version():
    from aughor.db.history import _conn, _ensure_schema

    c = _conn()
    _ensure_schema(c)
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(investigations)").fetchall()}
        assert "org_id" in cols, "investigations table gained the tenant key"
        assert c.execute("PRAGMA user_version").fetchone()[0] >= 2
    finally:
        c.close()


def test_investigation_history_is_org_scoped(monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import history
    from aughor.org.context import using_org

    with using_org("orgA"):
        ia = history.create_investigation("why did orgA revenue drop", "fixture")
    with using_org("orgB"):
        ib = history.create_investigation("why did orgB revenue drop", "fixture")

    with using_org("orgA"):
        ids_a = {r["id"] for r in history.list_investigations(limit=200)}
    assert ia in ids_a, "an org sees its own investigations"
    assert ib not in ids_a, "an org must NOT see another org's investigations"


def test_investigation_history_unfiltered_in_localhost_mode(monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    from aughor.db import history
    from aughor.org.context import using_org

    with using_org("orgA"):
        ia = history.create_investigation("localhost-visible", "fixture")
    with using_org("orgB"):
        ids = {r["id"] for r in history.list_investigations(limit=200)}
    assert ia in ids, "identity off → history is not org-filtered"


# ── DATA-06 on the ontology and object doors (2026-09-14) ─────────────────────────────────────────────────────────
# Both routers took a connection id on every door and never asked whose it was: with identity on, a caller from one
# organisation could read another organisation's ontology overrides by naming its connection, and withdraw them.


def test_the_ontology_and_object_doors_answer_only_the_org_that_owns_the_connection(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.ontology import overrides as OV
    from aughor.org.context import using_org

    with using_org("orgA"):
        mine = registry.add_connection("orgA-onto", "duckdb", "data/aughor.duckdb")
    with using_org("orgB"):
        theirs = registry.add_connection("orgB-onto", "duckdb", "data/aughor.duckdb")
    OV.save_override(mine, "main", OV.OntologyOverride(target_kind="entity", target_id="Order",
                                                       fields={"description": "orgA's words"}))
    a, b = {"X-Aughor-Org": "orgA"}, {"X-Aughor-Org": "orgB"}
    scope = {"connection_id": mine, "schema_name": "main"}
    try:
        own = client.get("/ontology/overrides", params=scope, headers=a)
        assert own.status_code == 200, own.text
        assert [o["target_id"] for o in own.json()["overrides"]] == ["Order"]
        # another organisation is refused on every door that names the connection: read, edit, withdraw, map, query,
        # and a comparison that names it as the reference
        refused = {
            "list": client.get("/ontology/overrides", params=scope, headers=b),
            "edit": client.put("/ontology/entities/Order", params=scope, headers=b, json={"description": "orgB's words"}),
            "withdraw": client.delete("/ontology/overrides/entity/Order", params=scope, headers=b),
            "map": client.get("/object-types", params=scope, headers=b),
            "query": client.post("/objects/query", params=scope, headers=b, json={"object_type": "Order"}),
            "compare": client.get("/ontology/draft", params={"connection_id": theirs, "reference_connection_id": mine},
                                  headers=b),
        }
        assert {what: r.status_code for what, r in refused.items()} == dict.fromkeys(refused, 403), {
            what: (r.status_code, r.text[:120]) for what, r in refused.items()}
        survivor = OV.find_override(mine, "main", "entity", "Order")
        assert survivor is not None and survivor.fields == {"description": "orgA's words"}
        # a shared builtin stays everyone's, and an organisation's own ontology is still reached through ?domain=
        assert client.get("/ontology/overrides", params={"connection_id": "fixture"}, headers=b).status_code == 200
        assert client.get("/object-types", params={"domain": "default", "connection_id": "domain:default"},
                          headers=b).status_code == 200
    finally:
        OV.delete_override(mine, "main", "entity", "Order")
        registry.delete_connection(mine)
        registry.delete_connection(theirs)


def test_the_ontology_doors_are_unchanged_in_localhost_mode(client, monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    from aughor.db import registry
    from aughor.org.context import using_org

    with using_org("orgA"):
        mine = registry.add_connection("orgA-onto-local", "duckdb", "data/aughor.duckdb")
    try:
        assert client.get("/ontology/overrides", params={"connection_id": mine, "schema_name": "main"}).status_code == 200
        assert client.get("/ontology/overrides", params={"connection_id": mine, "schema_name": "main"},
                          headers={"X-Aughor-Org": "orgB"}).status_code == 200
    finally:
        registry.delete_connection(mine)

