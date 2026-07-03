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
