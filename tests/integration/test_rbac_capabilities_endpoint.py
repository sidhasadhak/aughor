"""RBAC P2 — GET /capabilities is role-aware (tier ∩ role ceiling).

Localhost is unchanged (full tier set); with identity on + enterprise tier a viewer
sees a reduced set while an owner sees the full set.
"""
from __future__ import annotations

import pytest

from aughor.rbac import store


@pytest.fixture(autouse=True)
def _enterprise(monkeypatch):
    monkeypatch.setenv("AUGHOR_TIER", "enterprise")
    monkeypatch.setenv("AUGHOR_RBAC_AUTO_BOOTSTRAP", "0")
    yield


def _h(org, user="u1"):
    return {"X-Aughor-Org": org, "X-Aughor-User": user}


def test_localhost_capabilities_are_the_full_tier(client, monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    body = client.get("/capabilities").json()
    caps = set(body["capabilities"])
    assert "monitors" in caps and "metrics.define" in caps       # everything on
    assert body["roles"] == ["owner"]


def test_viewer_sees_a_reduced_capability_set(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    store.assign_role("caps-ep-viewer", "vic", "viewer")
    body = client.get("/capabilities", headers=_h("caps-ep-viewer", "vic")).json()
    caps = set(body["capabilities"])
    assert body["roles"] == ["viewer"]
    assert "catalog" in caps                                     # read features present
    assert "intel.hub" in caps
    assert "monitors" not in caps                                # role withholds them
    assert "metrics.define" not in caps
    assert "nl2sql.chat" not in caps


def test_owner_sees_the_full_capability_set(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    store.assign_role("caps-ep-owner", "boss", "owner")
    body = client.get("/capabilities", headers=_h("caps-ep-owner", "boss")).json()
    caps = set(body["capabilities"])
    assert body["roles"] == ["owner"]
    assert "monitors" in caps and "metrics.define" in caps and "security.suite" in caps
