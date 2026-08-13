"""The BYOK panel's gate — per-org controls need distinguishable orgs to mean anything.

Settings ▸ Organization gained a "Models & keys (BYOK)" section in CI-5b. On a
single-tenant deployment that section can only ever restate Settings ▸ Models: there is
one org, so an "org override" of the deployment config is the same three fields in a
second place. `/capabilities` now says whether tenants are distinguishable at all, and
the frontend hides the section when they are not.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from aughor.api import app


def test_single_tenant_by_default(monkeypatch):
    """Localhost / identity-off is the common case and must report False, or the UI
    would offer a per-org override that cannot differ from the deployment's."""
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    body = TestClient(app).get("/capabilities").json()
    assert body["multi_tenant"] is False


def test_multi_tenant_when_identity_is_enforced(monkeypatch):
    """With identity on, orgs are real and a per-org key is a genuine choice.

    The request carries `X-Aughor-Org` because identity mode rejects an
    unauthenticated caller outright — which is itself the point: the endpoint's answer
    is about the CALLER's world, not a global fact.
    """
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    res = TestClient(app).get("/capabilities", headers={"X-Aughor-Org": "acme"})
    assert res.status_code == 200
    assert res.json()["multi_tenant"] is True


def test_the_signal_is_read_per_request_not_at_import(monkeypatch):
    """Flipping it in a running process must take effect. A module-level read would
    make the switch unflippable and turn `monkeypatch.setenv` into a silent no-op —
    the trap this repo has paid for before with flag reads."""
    client = TestClient(app)

    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    on = client.get("/capabilities", headers={"X-Aughor-Org": "acme"})
    assert on.json()["multi_tenant"] is True

    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY")
    assert client.get("/capabilities").json()["multi_tenant"] is False
