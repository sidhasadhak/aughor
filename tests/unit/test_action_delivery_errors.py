"""A declared action's call that got no answer is a recorded dispatch error, said as what is known.

Before: a transport error, or a usage cap refusing the call, escaped the executor — a 500, no
`dispatch_error` audit, no outcome recorded, and an accepted proposal left `accepted`, which a resumed
automation reads as executed. Now the dispatchers raise the executor's own dispatch error, and its message
says whether the call may have landed: refused before it left (a cap, a connection never opened) it was
not delivered; once the request went out with no answer it may have been, and a retry could do the thing
twice. Hermetic: the network and the SSRF guard are faked; the approval gate is off.
"""
from __future__ import annotations

import contextlib

import httpx
import pytest

from aughor.actions.executor import execute_kinetic_action
from aughor.govern import outbound
from aughor.ontology.models import ActionParameter, KineticAction, SideEffect


@pytest.fixture(autouse=True)
def _gate_off_and_guard_open(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")   # the gate is on by default since 2026-10-04
    monkeypatch.setattr("aughor.util.url_guard.is_safe_webhook_url", lambda u: True)


def _action(side_effect: SideEffect) -> KineticAction:
    return KineticAction(id="notify_carrier", kind="side_effect", risk="low", side_effects=[side_effect],
                         params=[ActionParameter(name="amount", data_type="NUMERIC", required=True)])


_WEBHOOK = SideEffect(kind="webhook", config={"url": "https://hooks.example.com/x"})


def _post_raising(monkeypatch, exc):
    def post(url, **k):
        raise exc
    monkeypatch.setattr(httpx, "post", post)


def test_a_webhook_that_cannot_connect_says_it_was_not_delivered(monkeypatch):
    _post_raising(monkeypatch, httpx.ConnectError("connection refused"))
    r = execute_kinetic_action(_action(_WEBHOOK), {"amount": 500})
    assert r.status == "dispatch_error" and not r.ok
    assert "was not delivered" in r.message


def test_a_webhook_with_no_answer_says_it_may_have_landed(monkeypatch):
    _post_raising(monkeypatch, httpx.ReadTimeout("no answer"))
    r = execute_kinetic_action(_action(_WEBHOOK), {"amount": 500})
    assert r.status == "dispatch_error"
    assert "may have been delivered" in r.message


def test_a_call_a_usage_cap_refuses_is_a_dispatch_error(monkeypatch):
    @contextlib.contextmanager
    def blocked(service, operation, **kwargs):
        raise outbound.OutboundBlocked(service, "the webhook budget for today is spent")
        yield {}
    monkeypatch.setattr(outbound, "external_call", blocked)
    r = execute_kinetic_action(_action(_WEBHOOK), {"amount": 500})
    assert r.status == "dispatch_error" and "budget for today is spent" in r.message


def test_a_described_http_call_that_cannot_connect_is_a_dispatch_error(monkeypatch):
    def request(method, url, **k):
        raise httpx.ConnectError("connection refused")
    monkeypatch.setattr(httpx, "request", request)
    http = SideEffect(kind="http", config={"url": "https://api.vendor.example/v1/refunds"})
    r = execute_kinetic_action(_action(http), {"amount": 500})
    assert r.status == "dispatch_error" and "was not delivered" in r.message
