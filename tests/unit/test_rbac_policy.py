"""RBAC P4 — the declarative endpoint→permission policy table.

Reads are open; every other verb falls to the resource.write floor unless the table
names a more specific permission (and a GET override can raise a read above open).
"""
from __future__ import annotations

from aughor.rbac import Permission
from aughor.rbac.policy import required_permission


def test_reads_are_open_by_default():
    assert required_permission("GET", "/anything/{id}") is None
    assert required_permission("HEAD", "/x") is None
    assert required_permission("OPTIONS", "/x") is None  # CORS preflight never gated


def test_unlisted_mutations_hit_the_write_floor():
    assert required_permission("POST", "/canvases") == Permission.RESOURCE_WRITE
    assert required_permission("PUT", "/metrics/{name}") == Permission.RESOURCE_WRITE
    assert required_permission("DELETE", "/connections/{conn_id}/files/{filename}") == Permission.RESOURCE_WRITE


def test_specific_overrides_raise_the_bar():
    assert required_permission("POST", "/connections") == Permission.CONNECTION_CREATE
    assert required_permission("DELETE", "/connections/{conn_id}") == Permission.CONNECTION_DELETE
    assert required_permission("DELETE", "/investigations/{inv_id}") == Permission.RESOURCE_DELETE
    assert required_permission("POST", "/chat") == Permission.ANALYSIS_RUN
    assert required_permission("POST", "/investigate") == Permission.ANALYSIS_RUN
    assert required_permission("POST", "/rbac/assignments") == Permission.ADMIN_MANAGE_ROLES
    assert required_permission("PUT", "/org-settings") == Permission.ADMIN_MANAGE_ORG
    assert required_permission("PATCH", "/agents/{agent_id}") == Permission.ADMIN_MANAGE_ORG
    assert required_permission("POST", "/llm/config") == Permission.ADMIN_MANAGE_BILLING


def test_a_get_override_wins_over_the_open_default():
    # export is a GET but must require resource.export, not be open.
    assert required_permission("GET", "/investigations/{inv_id}/export") == Permission.RESOURCE_EXPORT
    # a plain read on the same collection stays open.
    assert required_permission("GET", "/investigations") is None


def test_method_is_case_insensitive():
    assert required_permission("post", "/connections") == Permission.CONNECTION_CREATE
    assert required_permission("delete", "/investigations/{inv_id}") == Permission.RESOURCE_DELETE


def test_allowlisting_and_authority_changes_need_an_admin_and_each_key_names_a_real_route():
    """Arc OC-6, D7 (the user's call, 2026-10-10): these fell to the write floor, so once RBAC was enforced any Editor
    could allowlist a high-risk action for a connection. A key that names no route gates nothing — so each is checked
    against the app's own routes."""
    from aughor.api import app
    from aughor.rbac.permissions import Permission as P
    from aughor.rbac.policy import POLICY, required_permission
    real = {(m, r.path) for r in app.routes for m in getattr(r, "methods", None) or ()}
    governed = [k for k in POLICY if k[0] == "POST" and k[1].split("/")[1] in ("approvals", "authority")]
    assert len(governed) == 7 and all(POLICY[k] == P.ADMIN_MANAGE_ORG for k in governed)
    assert set(governed) <= real, set(governed) - real
    assert required_permission("POST", "/kinetic-actions/{action_id}/execute") == P.RESOURCE_WRITE   # running stays
    assert required_permission("POST", "/authority/{action_id}/executions/{entry_id}/undo") == P.RESOURCE_WRITE
