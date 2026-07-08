"""End-to-end RBAC row-policy (Rec 7) through the DuckDB connection chokepoint (`_run`).

A real two-org DuckDB table; the policy, identity gate, and role are controlled per test. Asserts a viewer is
scoped to its org, an owner is unrestricted, un-policied tables are untouched, the feature is byte-identical
off, it fails CLOSED on an injection error, and internal (no-user-context) queries are never filtered.
"""
from __future__ import annotations

import duckdb

import aughor.licensing as _lic
import aughor.rbac.resolver as _resolver
import aughor.rbac.row_policy as rp
import aughor.security.authz as _authz
from aughor.db import registry
from aughor.db.connection import open_connection_for
from aughor.org.context import reset_org_id, reset_user_id, set_org_id, set_user_id


def _orders(tmp_path, name):
    p = tmp_path / f"{name}.duckdb"
    con = duckdb.connect(str(p))
    con.execute("CREATE TABLE orders (id INT, org_id VARCHAR, amount INT)")
    con.execute("INSERT INTO orders VALUES (1,'o1',100),(2,'o2',50),(3,'o1',30)")
    con.execute("CREATE TABLE ref (k VARCHAR, v VARCHAR)")     # a table with NO policy
    con.execute("INSERT INTO ref VALUES ('a','x'),('b','y')")
    con.close()
    return registry.add_connection(name, "duckdb", str(p))


def _enable(monkeypatch, *, roles, policies=None):
    """Turn the feature on and pin the caller's roles/identity for the test."""
    monkeypatch.setenv("AUGHOR_RBAC_ROW_POLICY", "1")
    monkeypatch.setattr(_authz, "require_identity_enabled", lambda: True)
    monkeypatch.setattr(_lic, "has_capability", lambda *a, **k: True)
    monkeypatch.setattr(_resolver, "resolve_roles", lambda principal: list(roles))
    monkeypatch.setattr(rp, "ROW_POLICIES",
                        policies if policies is not None else {"viewer": {"orders": "org_id = '{org_id}'"}})


def _ids(res):
    return [r[0] for r in res.rows]


def test_viewer_scoped_to_its_org(monkeypatch, tmp_path):
    _enable(monkeypatch, roles=["viewer"])
    cid = _orders(tmp_path, "rp1")
    ot, ut = set_org_id("o1"), set_user_id("u1")
    try:
        res = open_connection_for(cid).execute("q", "SELECT id, amount FROM orders ORDER BY id")
        assert res.error is None
        assert _ids(res) == ["1", "3"]                 # only org o1's rows
    finally:
        reset_user_id(ut); reset_org_id(ot)


def test_owner_is_unrestricted(monkeypatch, tmp_path):
    _enable(monkeypatch, roles=["owner"])
    cid = _orders(tmp_path, "rp2")
    ot, ut = set_org_id("o1"), set_user_id("u1")
    try:
        res = open_connection_for(cid).execute("q", "SELECT id FROM orders ORDER BY id")
        assert _ids(res) == ["1", "2", "3"]            # owner sees every org's rows
    finally:
        reset_user_id(ut); reset_org_id(ot)


def test_unpolicied_table_untouched(monkeypatch, tmp_path):
    _enable(monkeypatch, roles=["viewer"])             # policy only covers `orders`, not `ref`
    cid = _orders(tmp_path, "rp3")
    ot, ut = set_org_id("o1"), set_user_id("u1")
    try:
        res = open_connection_for(cid).execute("q", "SELECT k FROM ref ORDER BY k")
        assert _ids(res) == ["a", "b"]
    finally:
        reset_user_id(ut); reset_org_id(ot)


def test_off_by_default_byte_identical(monkeypatch, tmp_path):
    monkeypatch.delenv("AUGHOR_RBAC_ROW_POLICY", raising=False)   # flag off
    monkeypatch.setattr(_authz, "require_identity_enabled", lambda: True)
    monkeypatch.setattr(_lic, "has_capability", lambda *a, **k: True)
    monkeypatch.setattr(_resolver, "resolve_roles", lambda p: ["viewer"])
    monkeypatch.setattr(rp, "ROW_POLICIES", {"viewer": {"orders": "org_id = '{org_id}'"}})
    cid = _orders(tmp_path, "rp4")
    ot, ut = set_org_id("o1"), set_user_id("u1")
    try:
        res = open_connection_for(cid).execute("q", "SELECT id FROM orders ORDER BY id")
        assert _ids(res) == ["1", "2", "3"]            # flag off → no filtering
    finally:
        reset_user_id(ut); reset_org_id(ot)


def test_internal_query_no_user_context_not_filtered(monkeypatch, tmp_path):
    _enable(monkeypatch, roles=["viewer"])
    cid = _orders(tmp_path, "rp5")
    ot = set_org_id("o1")                               # org set, but NO user id → internal/background query
    try:
        res = open_connection_for(cid).execute("q", "SELECT id FROM orders ORDER BY id")
        assert _ids(res) == ["1", "2", "3"]            # unfiltered — row-policy only scopes identified requests
    finally:
        reset_org_id(ot)


def test_fails_closed_on_injection_error(monkeypatch, tmp_path):
    # A CTE that collides with a policied table name → the injector refuses → the query is BLOCKED.
    _enable(monkeypatch, roles=["viewer"])
    cid = _orders(tmp_path, "rp6")
    ot, ut = set_org_id("o1"), set_user_id("u1")
    try:
        res = open_connection_for(cid).execute(
            "q", "WITH orders AS (SELECT 1 AS id) SELECT * FROM orders")
        assert res.error is not None and "ROW POLICY" in res.error
        assert res.rows == []                          # fail-closed: blocked, never run unfiltered
    finally:
        reset_user_id(ut); reset_org_id(ot)
