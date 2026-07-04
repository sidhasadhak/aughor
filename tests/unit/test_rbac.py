"""RBAC P1 — role/permission model, org-scoped assignment store, resolver seam.

Properties:
  * the built-in ladder is a strict superset chain viewer ⊂ analyst ⊂ owner;
  * assignments are tenant-scoped (org A never sees org B's grants — DATA-06);
  * the resolver preserves today's behaviour (no principal → owner → all allowed)
    and defaults an identified-but-unassigned user to least privilege.

No route enforcement is asserted here — P1 wires none (that's P3).
"""
from __future__ import annotations

from aughor.rbac import (
    ALL_PERMISSIONS,
    ANALYST,
    OWNER,
    VIEWER,
    Permission,
    get_role,
    has_permission,
    permissions_for,
    resolve_roles,
    role_permissions,
)
from aughor.rbac import store
from aughor.rbac.resolver import default_role
from aughor.security.authz import Principal


# ── The role model ────────────────────────────────────────────────────────────

def test_ladder_is_a_strict_superset_chain():
    viewer = role_permissions(VIEWER)
    analyst = role_permissions(ANALYST)
    owner = role_permissions(OWNER)
    assert viewer < analyst < owner  # strict subsets
    assert owner == ALL_PERMISSIONS


def test_viewer_is_read_only():
    viewer = get_role(VIEWER)
    assert viewer.permissions == frozenset({Permission.RESOURCE_READ})
    assert viewer.grants(Permission.RESOURCE_READ)
    assert not viewer.grants(Permission.RESOURCE_WRITE)


def test_only_owner_holds_admin_verbs():
    admin_verbs = {
        Permission.ADMIN_MANAGE_ROLES,
        Permission.ADMIN_MANAGE_ORG,
        Permission.ADMIN_MANAGE_BILLING,
    }
    assert admin_verbs <= role_permissions(OWNER)
    assert not (admin_verbs & role_permissions(ANALYST))
    assert not (admin_verbs & role_permissions(VIEWER))


def test_analyst_can_run_and_manage_connections_but_not_govern():
    analyst = role_permissions(ANALYST)
    assert Permission.ANALYSIS_RUN in analyst
    assert Permission.CONNECTION_CREATE in analyst
    assert Permission.RESOURCE_DELETE in analyst
    assert Permission.ADMIN_MANAGE_ROLES not in analyst


def test_unknown_role_is_fail_closed():
    assert get_role("superuser") is None
    assert role_permissions("superuser") == frozenset()


# ── The assignment store ──────────────────────────────────────────────────────

def test_assign_and_read_roles():
    store.assign_role("org-a1", "alice", "analyst")
    assert store.roles_for_user("org-a1", "alice") == [ANALYST]


def test_assign_is_idempotent_no_duplicate_rows():
    store.assign_role("org-a2", "bob", "viewer")
    store.assign_role("org-a2", "bob", "viewer")  # re-grant
    assert store.roles_for_user("org-a2", "bob") == [VIEWER]  # one row, not two


def test_multiple_roles_per_user():
    store.assign_role("org-a3", "carol", "viewer")
    store.assign_role("org-a3", "carol", "analyst")
    assert store.roles_for_user("org-a3", "carol") == [ANALYST, VIEWER]  # sorted


def test_revoke_role():
    store.assign_role("org-a4", "dave", "analyst")
    assert store.revoke_role("org-a4", "dave", "analyst") is True
    assert store.roles_for_user("org-a4", "dave") == []
    assert store.revoke_role("org-a4", "dave", "analyst") is False  # already gone


def test_assignments_are_org_scoped():
    store.assign_role("org-tenant-x", "erin", "owner")
    # A different org with the same user id sees nothing.
    assert store.roles_for_user("org-tenant-y", "erin") == []
    assert store.roles_for_user("org-tenant-x", "erin") == [OWNER]


def test_list_assignments_is_the_org_roster():
    store.assign_role("org-roster", "u1", "viewer")
    store.assign_role("org-roster", "u2", "analyst")
    roster = store.list_assignments("org-roster")
    assert {(a.user_id, a.role) for a in roster} == {("u1", VIEWER), ("u2", ANALYST)}
    assert all(a.org_id == "org-roster" for a in roster)


# ── The resolver ──────────────────────────────────────────────────────────────

def test_no_principal_resolves_to_owner_unchanged_behaviour():
    assert resolve_roles(None) == [OWNER]
    # every permission is granted → byte-identical to pre-RBAC localhost mode
    for perm in Permission:
        assert has_permission(None, perm)


def test_identified_unassigned_user_gets_least_privilege_default():
    p = Principal(user_id="newbie", org_id="org-res1")
    assert resolve_roles(p) == [VIEWER]
    assert has_permission(p, Permission.RESOURCE_READ)
    assert not has_permission(p, Permission.RESOURCE_WRITE)


def test_identified_assigned_user_gets_their_roles():
    store.assign_role("org-res2", "frank", "analyst")
    p = Principal(user_id="frank", org_id="org-res2")
    assert resolve_roles(p) == [ANALYST]
    assert has_permission(p, Permission.ANALYSIS_RUN)
    assert not has_permission(p, Permission.ADMIN_MANAGE_ROLES)


def test_permissions_union_across_multiple_roles():
    store.assign_role("org-res3", "grace", "viewer")
    store.assign_role("org-res3", "grace", "analyst")
    p = Principal(user_id="grace", org_id="org-res3")
    assert permissions_for(p) == role_permissions(ANALYST)  # union == the broader role


def test_default_role_env_override(monkeypatch):
    monkeypatch.setenv("AUGHOR_RBAC_DEFAULT_ROLE", "analyst")
    assert default_role() == ANALYST
    p = Principal(user_id="someone", org_id="org-res4")
    assert resolve_roles(p) == [ANALYST]


def test_default_role_unknown_value_falls_back_to_viewer(monkeypatch):
    monkeypatch.setenv("AUGHOR_RBAC_DEFAULT_ROLE", "godmode")
    assert default_role() == VIEWER  # never silently escalates


def test_resolver_fails_closed_to_default_on_store_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(store, "roles_for_user", _boom)
    p = Principal(user_id="hank", org_id="org-res5")
    # store outage must resolve to the default role (viewer), never to owner
    assert resolve_roles(p) == [VIEWER]
    assert not has_permission(p, Permission.RESOURCE_WRITE)
