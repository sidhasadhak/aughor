"""Track A5 (docs/TENX_PROGRAM_2026-11-05.md): an organisation's first owner is a named, verified person.

Measured before: the header seam with an org and no user resolved to ``anonymous``, and the first
such request made "anonymous" the owner — so every later user-less request owned the org. And a
service principal, an outside vendor's agent, could be an organisation's first caller and be made
its administrator. Neither is a person; neither bootstraps. The organisation stays claimable by
its first named person, because a refused bootstrap is not cached as "checked".
"""
from __future__ import annotations

from aughor.rbac import resolver
from aughor.rbac.roles import OWNER
from aughor.rbac.store import roles_for_user
from aughor.security.authz import Principal
from aughor.security.service_principals import PREFIX


def test_anonymous_and_service_principals_never_bootstrap(monkeypatch):
    monkeypatch.setenv("AUGHOR_RBAC_AUTO_BOOTSTRAP", "1")
    resolver._reset_bootstrap_cache()
    org = "a5-org"
    assert resolver.maybe_bootstrap_owner(Principal(user_id="anonymous", org_id=org)) is False
    assert resolver.maybe_bootstrap_owner(Principal(user_id="", org_id=org)) is False
    assert resolver.maybe_bootstrap_owner(Principal(user_id=f"{PREFIX}vendor-bot", org_id=org)) is False
    assert roles_for_user(org, "anonymous") == [] and roles_for_user(org, f"{PREFIX}vendor-bot") == []
    # The org was not marked checked: its first named person still claims it.
    assert resolver.maybe_bootstrap_owner(Principal(user_id="amit", org_id=org)) is True
    assert roles_for_user(org, "amit") == [OWNER]
    # And only once.
    assert resolver.maybe_bootstrap_owner(Principal(user_id="mallory", org_id=org)) is False
    assert roles_for_user(org, "mallory") == []


def test_over_http_an_anonymous_first_caller_is_a_viewer(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    monkeypatch.setenv("AUGHOR_RBAC_AUTO_BOOTSTRAP", "1")
    resolver._reset_bootstrap_cache()
    nobody = {"X-Aughor-Org": "a5-http-org"}                 # no X-Aughor-User → "anonymous"
    assert client.get("/rbac/me", headers=nobody).json()["roles"] == ["viewer"]
    assert client.get("/rbac/assignments", headers=nobody).status_code == 403
    someone = {"X-Aughor-Org": "a5-http-org", "X-Aughor-User": "amit"}
    assert client.get("/rbac/me", headers=someone).json()["roles"] == [OWNER]
