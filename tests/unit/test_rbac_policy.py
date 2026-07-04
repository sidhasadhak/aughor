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
