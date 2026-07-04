"""RBAC P3 — enforcement dependency, admin roster, first-user-owner bootstrap.

The ``gate_permission`` dependency is a NO-OP unless BOTH conditions hold:
  * ``AUGHOR_REQUIRE_IDENTITY`` is on (a principal is bound), AND
  * the org's tier grants ``Capability.RBAC_SSO`` (default enterprise → on).
When enforced, a caller whose roles don't grant the permission gets 403, and the
org's first identified caller is bootstrapped as owner.

Every org id here is globally unique so the session-shared RBAC store and the
per-process bootstrap cache never leak across tests.
"""
from __future__ import annotations

import pytest

from aughor.rbac import OWNER
from aughor.rbac import store


@pytest.fixture(autouse=True)
def _identity_on(monkeypatch):
    """Default every test to identity-on, enterprise tier, auto-bootstrap on."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    monkeypatch.setenv("AUGHOR_TIER", "enterprise")
    monkeypatch.setenv("AUGHOR_RBAC_AUTO_BOOTSTRAP", "1")
    yield


def _h(org: str, user: str = "u1") -> dict:
    return {"X-Aughor-Org": org, "X-Aughor-User": user}


# ── The role catalogue + self-introspection ──────────────────────────────────

def test_role_catalogue(client):
    roles = {x["name"]: x for x in client.get("/rbac/roles", headers=_h("rbacp3-cat")).json()}
    assert set(roles) == {"owner", "analyst", "viewer"}
    assert roles["viewer"]["permissions"] == ["resource.read"]
    assert "admin.manage_roles" in roles["owner"]["permissions"]
    assert "admin.manage_roles" not in roles["analyst"]["permissions"]


def test_me_reflects_assigned_role(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_RBAC_AUTO_BOOTSTRAP", "0")
    org = "rbacp3-me"
    store.assign_role(org, "ana", "analyst")
    me = client.get("/rbac/me", headers=_h(org, "ana")).json()
    assert me["user_id"] == "ana"
    assert me["org_id"] == org
    assert me["roles"] == ["analyst"]
    assert "analysis.run" in me["permissions"]
    assert "admin.manage_roles" not in me["permissions"]


# ── Enforcement: no-op cases ─────────────────────────────────────────────────

def test_localhost_is_unenforced(client, monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    # No identity → no principal → the gate no-ops; the admin roster answers with
    # no role at all, and /rbac/me resolves the caller to owner (unchanged behaviour).
    assert client.get("/rbac/assignments").status_code == 200
    assert client.get("/rbac/me").json()["roles"] == [OWNER]


def test_not_enforced_without_rbac_sso_capability(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_TIER", "free")            # free tier lacks RBAC_SSO
    monkeypatch.setenv("AUGHOR_RBAC_AUTO_BOOTSTRAP", "0")
    # 'vic' would be a viewer under enterprise, but without the capability the gate
    # is inert — RBAC is an enterprise feature.
    assert client.get("/rbac/assignments", headers=_h("rbacp3-free", "vic")).status_code == 200


# ── Enforcement: 403 for an insufficient role ────────────────────────────────

def test_viewer_forbidden_on_admin_endpoints(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_RBAC_AUTO_BOOTSTRAP", "0")  # 'vic' stays a default viewer
    org = "rbacp3-viewer"
    assert client.get("/rbac/assignments", headers=_h(org, "vic")).status_code == 403
    r = client.post("/rbac/assignments", headers=_h(org, "vic"),
                    json={"user_id": "x", "role": "viewer"})
    assert r.status_code == 403


def test_viewer_forbidden_on_resource_and_connection_gates(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_RBAC_AUTO_BOOTSTRAP", "0")
    org = "rbacp3-res"
    h = _h(org, "vic")
    # viewer lacks resource.delete / resource.export / connection.delete — the gate
    # blocks BEFORE the handler, so the target id needn't exist.
    assert client.delete("/investigations/nope", headers=h).status_code == 403
    assert client.get("/investigations/nope/export", headers=h).status_code == 403
    assert client.delete("/connections/nope", headers=h).status_code == 403


# ── Enforcement: allowed for a sufficient role ───────────────────────────────

def test_owner_passes_resource_and_connection_gates(client):
    # first caller in a fresh org → bootstrapped owner → the gate lets the request
    # through (the handler may then 204/404 on the bogus id; the point is NOT 403).
    h = _h("rbacp3-owner-pass", "boss")
    assert client.delete("/connections/nope", headers=h).status_code != 403
    assert client.delete("/investigations/nope", headers=h).status_code != 403


# ── First-user-is-owner bootstrap ────────────────────────────────────────────

def test_first_identified_user_becomes_owner(client):
    org = "rbacp3-boot"
    # A gated endpoint triggers the bootstrap; the first caller becomes owner and is
    # allowed. A later, different user finds the org non-empty → default viewer → 403.
    assert client.get("/rbac/assignments", headers=_h(org, "founder")).status_code == 200
    assert store.roles_for_user(org, "founder") == [OWNER]
    assert client.get("/rbac/assignments", headers=_h(org, "latecomer")).status_code == 403


def test_bootstrap_disabled_locks_out_first_user(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_RBAC_AUTO_BOOTSTRAP", "0")
    # With auto-bootstrap off (pre-seeded-IdP deployments), the first user is a plain
    # viewer and cannot self-administer.
    assert client.get("/rbac/assignments", headers=_h("rbacp3-noboot", "someone")).status_code == 403


# ── The admin roster round-trip (as the bootstrapped owner) ───────────────────

def test_owner_roster_crud(client):
    org = "rbacp3-crud"
    h = _h(org, "boss")  # first caller → owner
    # assign
    r = client.post("/rbac/assignments", headers=h, json={"user_id": "alice", "role": "analyst"})
    assert r.status_code == 201 and r.json()["role"] == "analyst"
    # list roster (owner + alice)
    roster = client.get("/rbac/assignments", headers=h).json()
    assert {(a["user_id"], a["role"]) for a in roster} == {("boss", OWNER), ("alice", "analyst")}
    # an unknown role is rejected
    assert client.post("/rbac/assignments", headers=h,
                       json={"user_id": "z", "role": "superuser"}).status_code == 400
    # revoke
    d = client.delete("/rbac/assignments", headers=h, params={"user_id": "alice", "role": "analyst"})
    assert d.status_code == 200 and d.json()["removed"] is True
    assert store.roles_for_user(org, "alice") == []


def test_roster_is_org_scoped(client):
    # An owner in one org never sees or manages another org's roster.
    a = _h("rbacp3-tenant-a", "boss-a")
    b = _h("rbacp3-tenant-b", "boss-b")
    client.post("/rbac/assignments", headers=a, json={"user_id": "alice", "role": "viewer"})
    client.post("/rbac/assignments", headers=b, json={"user_id": "bob", "role": "viewer"})
    users_a = {x["user_id"] for x in client.get("/rbac/assignments", headers=a).json()}
    assert "bob" not in users_a and "alice" in users_a
