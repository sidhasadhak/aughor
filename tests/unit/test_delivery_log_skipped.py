"""A disabled trigger is a SKIP, not a failed delivery (2026-09-22).

The live install's outbound delivery log held 336 rows, all `status: failed`, and the
roadmap read that as every send having failed. Read, the reasons were 332 × "Trigger is
disabled" for one switched-off trigger and 4 sends to a deliberate blackhole test target.
No real send had ever failed — the executor recorded a row it never attempted as a
failure. This pins the corrected record: nothing is sent, the row says `skipped`, the
reason stays on it, and the two real outcomes are untouched.
"""
from __future__ import annotations

import pytest

from aughor.notifications import executor
from aughor.notifications.models import ActionLog, ActionPayload, ActionTrigger


def _trigger(enabled: bool) -> ActionTrigger:
    return ActionTrigger(id="t1", name="slack-ops", type="webhook",
                         url="https://hooks.example.test/x", enabled=enabled)


def _payload() -> ActionPayload:
    return ActionPayload(investigation_id="inv-1", rec_index=0, recommendation="hi",
                         metric_name="m", headline=None, trigger_id="t1",
                         triggered_at="2026-09-22T00:00:00+00:00")


@pytest.fixture
def recorded(monkeypatch):
    rows: list[ActionLog] = []
    monkeypatch.setattr(executor, "log_action", rows.append)

    def _no_send(*a, **k):
        raise AssertionError("a disabled trigger must never reach the network")
    monkeypatch.setattr(executor, "_post", _no_send)
    monkeypatch.setattr(executor, "_post_attempts", _no_send)
    return rows


def test_a_disabled_trigger_logs_skipped_with_its_reason_and_sends_nothing(recorded):
    log = executor.fire_action(_trigger(enabled=False), _payload())
    assert log.status == "skipped"
    assert log.error == "Trigger is disabled" and log.http_status is None
    assert recorded == [log]                       # one row, the returned one


def test_skipped_is_a_declared_status():
    """The wire vocabulary names it — the hub panel and any reader switch on this literal."""
    from typing import get_args
    assert "skipped" in get_args(ActionLog.__dataclass_fields__["status"].type) or \
        "skipped" in str(ActionLog.__dataclass_fields__["status"].type)


def test_mutation_check_an_enabled_trigger_still_reaches_the_sender(monkeypatch):
    """Same call, enabled trigger → the executor DOES try to send. Proves the skip branch
    is what produced `skipped`, not a stubbed-out send."""
    monkeypatch.setattr(executor, "log_action", lambda log: None)
    # The SSRF guard resolves the host; a test hostname has no address, so it is
    # answered here rather than by DNS — the sender is what this test is about.
    monkeypatch.setattr("aughor.util.url_guard.is_safe_webhook_url", lambda url: True)
    reached: list = []

    def _fake_send(url, headers, payload, *a, **k):
        reached.append(url)
        return 200, None, False, {}
    monkeypatch.setattr(executor, "_post", _fake_send)
    log = executor.fire_action(_trigger(enabled=True), _payload())
    assert reached == ["https://hooks.example.test/x"]
    assert log.status == "ok" and log.http_status == 200
