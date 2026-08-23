"""Outbound Slack, by failure cause.

The retry policy this pins replaced one that was inverted in both directions at once: it
retried on exception — mostly a READ timeout, the one case where Slack may already have
posted — and it returned any HTTP status immediately, so a **429 or a 502 was dropped on
the floor**. Rate limiting is the normal way a webhook says "slow down", and a burst of
alerts quietly lost the tail of itself.

The other half is that a Slack incoming-webhook URL **is** the credential. `to_safe_dict`
already masked it for the API; the logger did not, and wrote `trigger.url[:60]` — workspace
id, channel id, and the first characters of the secret — on every fire, success or failure.
"""
from __future__ import annotations

import logging

import pytest
import requests

from aughor.notifications import executor as ex
from aughor.notifications.models import ActionPayload, ActionTrigger

HOOK = "https://hooks.slack.com/services/T-PLACEHOLDER/B-PLACEHOLDER/not-a-real-webhook-secret"


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(ex.time, "sleep", lambda s: slept.append(s))
    return slept


@pytest.fixture(autouse=True)
def _quiet_log_store(monkeypatch):
    """The ActionLog is asserted on directly; the store is not what these tests are about."""
    written: list = []
    monkeypatch.setattr(ex, "log_action", lambda log: written.append(log))
    return written


class _Resp:
    def __init__(self, status: int, text: str = "", headers: dict | None = None):
        self.status_code, self.text, self.headers = status, text, headers or {}

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


def _trigger(**kw) -> ActionTrigger:
    base = dict(id="t1", name="Ops Slack", type="slack", url=HOOK, channel="#ops")
    base.update(kw)
    return ActionTrigger(**base)


def _payload(**kw) -> ActionPayload:
    base = dict(investigation_id="inv-123", rec_index=0, recommendation="Check refunds",
                metric_name="gmv", headline="GMV down", trigger_id="t1",
                triggered_at="2026-08-24T00:00:00Z")
    base.update(kw)
    return ActionPayload(**base)


def _posts(monkeypatch, *responses):
    """Queue responses (or exceptions); record every attempt."""
    calls: list = []

    def _post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json})
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(requests, "post", _post)
    return calls


# ── the policy, by cause ──────────────────────────────────────────────────────────

def test_a_read_timeout_is_never_retried(monkeypatch):
    """It reached Slack and we did not hear back. Retrying is how one alert becomes two."""
    calls = _posts(monkeypatch, requests.exceptions.ReadTimeout("too slow"))

    log = ex.fire_action(_trigger(), _payload())

    assert len(calls) == 1, "a read timeout must be sent exactly once"
    assert log.status == "timeout", "and reported as uncertain, not as a failure to retry"


def test_a_connect_timeout_is_retried(monkeypatch):
    """Nothing left the machine, so a retry cannot duplicate — this one is safe."""
    calls = _posts(monkeypatch, requests.exceptions.ConnectTimeout("no route"))

    log = ex.fire_action(_trigger(), _payload())

    assert len(calls) == ex._MAX_ATTEMPTS
    assert log.status == "failed"


def test_a_rate_limit_is_retried_on_the_providers_own_header(_no_sleeping, monkeypatch):
    """Backing off on our schedule instead of Slack's is how a burst of alerts becomes a
    burst of rejected alerts."""
    calls = _posts(monkeypatch,
                   _Resp(429, "rate_limited", {"Retry-After": "7"}),
                   _Resp(200))

    log = ex.fire_action(_trigger(), _payload())

    assert len(calls) == 2 and log.status == "ok"
    assert _no_sleeping == [7.0], "the wait must come from Retry-After, not from our backoff"


def test_an_absurd_retry_after_is_capped(_no_sleeping, monkeypatch):
    """A ten-minute Retry-After is a signal to give up, not to hold a worker."""
    _posts(monkeypatch, _Resp(429, "rate_limited", {"Retry-After": "600"}))

    ex.fire_action(_trigger(), _payload())

    assert max(_no_sleeping) <= ex._MAX_RETRY_AFTER_S


def test_a_server_error_is_retried(monkeypatch):
    calls = _posts(monkeypatch, _Resp(502, "bad gateway"), _Resp(502), _Resp(200))

    log = ex.fire_action(_trigger(), _payload())

    assert len(calls) == 3 and log.status == "ok"


def test_a_client_error_is_not_retried(monkeypatch):
    """`invalid_payload` fails identically next time; retrying only spends the rate limit."""
    calls = _posts(monkeypatch, _Resp(400, "invalid_payload"))

    log = ex.fire_action(_trigger(), _payload())

    assert len(calls) == 1
    assert log.status == "failed" and log.http_status == 400


def test_success_sends_once(monkeypatch):
    calls = _posts(monkeypatch, _Resp(200))

    assert ex.fire_action(_trigger(), _payload()).status == "ok"
    assert len(calls) == 1


# ── the credential ────────────────────────────────────────────────────────────────

def test_redact_url_keeps_the_host_and_drops_the_path():
    assert ex.redact_url(HOOK) == "https://hooks.slack.com/…"
    assert "not-a-real-webhook-secret" not in ex.redact_url(HOOK)
    assert ex.redact_url("") == ""
    assert ex.redact_url("not a url") == "(unparseable url)"


def test_the_webhook_secret_never_reaches_the_log_output(monkeypatch, caplog):
    _posts(monkeypatch, _Resp(200))

    with caplog.at_level(logging.INFO, logger=ex.logger.name):
        ex.fire_action(_trigger(), _payload())

    assert caplog.text, "the fire is logged at all"
    assert "not-a-real-webhook-secret" not in caplog.text
    assert "B-PLACEHOLDER" not in caplog.text, "the channel id is in the first 60 chars too"


def test_an_error_body_that_echoes_the_url_is_redacted_before_it_is_stored(monkeypatch):
    """A provider can hand our own URL back to us, and the stored ActionLog outlives the
    request."""
    _posts(monkeypatch, _Resp(404, f"no_service for {HOOK}"))

    log = ex.fire_action(_trigger(), _payload())

    assert "not-a-real-webhook-secret" not in (log.error or "")
    assert "hooks.slack.com" in (log.error or ""), "redacted, not blanked"


def test_a_blocked_url_is_not_logged_raw(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger=ex.logger.name):
        log = ex.fire_action(_trigger(url="http://169.254.169.254/latest/meta-data"),
                             _payload())

    assert log.status == "failed" and "SSRF" in (log.error or "")
    assert "meta-data" not in caplog.text


# ── the payload ───────────────────────────────────────────────────────────────────

def test_a_long_field_is_trimmed_with_the_cut_made_visible(monkeypatch):
    """Slack refuses a payload over 40 KB outright, so unbounded text does not arrive
    long — it does not arrive."""
    calls = _posts(monkeypatch, _Resp(200))

    ex.fire_action(_trigger(), _payload(recommendation="x" * 50_000))

    text = calls[0]["json"]["text"]
    assert len(text) <= ex._MAX_FIELD_CHARS
    assert text.endswith(ex._TRUNCATED)


def test_a_monitor_alert_still_leads_with_severity_and_monitor(monkeypatch):
    calls = _posts(monkeypatch, _Resp(200))

    ex.fire_action(_trigger(), _payload(context={
        "kind": "monitor_alert", "severity": "critical", "monitor_name": "Revenue",
        "metric_name": "gmv", "message": "y" * 50_000}))

    body = calls[0]["json"]
    assert "Revenue" in body["text"]
    assert body["attachments"][0]["color"] == ex._SEVERITY_COLOR["critical"]
    what_fired = [f for f in body["attachments"][0]["fields"] if f["title"] == "What fired"]
    assert len(what_fired[0]["value"]) <= ex._MAX_FIELD_CHARS
