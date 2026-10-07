"""Who did something is who is signed in — never a name a request body carries.

People sign in, so an approval, a confirmation or a decision is recorded under the person the
request acts for (`authz.caller`), bound on every request by the API's context middleware. Before
this, a dozen doors read the actor from the body: `POST /record/decisions` let a typed
`decided_by` WIN over the sign-in, so anyone could book a decision in the CEO's name, and
`acting_person(None, "user:ceo")` passed `user:ceo` through exactly as written.

These run through the real app, so the middleware that binds the actor is the one under test.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from aughor.api import app
    return TestClient(app)


def test_a_typed_decided_by_is_not_who_decided(client, monkeypatch):
    # nobody signs in: the request acts for the install's own login
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "op-ana")
    r = client.post("/record/decisions", json={"question": f"Extend it? {uuid.uuid4().hex[:6]}", "chosen": "yes",
                                               "decided_by": "ceo"})
    assert r.status_code == 201, r.text
    assert r.json()["decided_by"] == "user:op-ana"


def test_the_signed_in_person_is_who_decided_whatever_the_body_says(client):
    from aughor.security.authz import IDENTITY_ORG_HEADER, IDENTITY_USER_HEADER
    r = client.post("/record/decisions",
                    json={"question": f"Extend it? {uuid.uuid4().hex[:6]}", "chosen": "yes", "decided_by": "user:ceo"},
                    headers={IDENTITY_ORG_HEADER: "default", IDENTITY_USER_HEADER: "dana"})
    assert r.status_code == 201, r.text
    assert r.json()["decided_by"] == "user:dana"


def test_acting_person_never_passes_a_named_person_through(monkeypatch):
    from aughor.org.context import reset_actor, set_actor
    from aughor.security.authz import acting_person
    # with no request bound, the install's own operator — never the name offered
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "the-operator")
    assert acting_person(None, "user:ceo") == "user:the-operator"
    assert acting_person(None, "ceo") == "user:the-operator"
    token = set_actor("op-ana")
    try:
        assert acting_person(None, "user:ceo") == "user:op-ana"
        assert acting_person(SimpleNamespace(user_id="dana"), "user:ceo") == "user:dana"
    finally:
        reset_actor(token)


def test_an_audit_with_no_actor_is_who_the_request_acts_for_and_unattributed_outside_one():
    from aughor.govern import actions as govern
    from aughor.identity import UNATTRIBUTED
    from aughor.org.context import reset_actor, set_actor
    token = set_actor("op-ana")
    try:
        govern.audit("connection.delete", f"conn-{uuid.uuid4().hex[:6]}", "approved")
    finally:
        reset_actor(token)
    assert govern.recent_audit(5)[0]["actor"] == "op-ana"
    # a schedule or an automation run has no request: unchanged, still said as unattributed
    govern.audit("connection.delete", f"conn-{uuid.uuid4().hex[:6]}", "approved")
    assert govern.recent_audit(5)[0]["actor"] == UNATTRIBUTED


def test_an_approval_is_recorded_under_the_caller(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "op-ana")
    r = client.post("/approvals/allow", json={"action": "connection.delete", "scope": f"conn-{uuid.uuid4().hex[:6]}"})
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["by"] == "op-ana"


def test_the_reader_reads_their_own_record_not_the_one_a_query_names(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_LOCAL_USER", f"reader-{uuid.uuid4().hex[:6]}")
    you = client.get("/record/you", params={"by": "ceo"}).json()
    assert you["principal"].startswith("user:reader-")
