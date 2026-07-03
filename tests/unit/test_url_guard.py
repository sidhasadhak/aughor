"""REC-06 / SEC-04 — SSRF guard on outbound webhook URLs.

The guard must fail CLOSED and block private/loopback/link-local/reserved
targets (incl. the cloud metadata endpoint) while allowing genuine public
http(s) webhooks.
"""
from __future__ import annotations

import socket

import pytest

from aughor.util import url_guard
from aughor.util.url_guard import is_safe_webhook_url


@pytest.fixture
def _resolves(monkeypatch):
    """Force DNS resolution to a controlled IP so the test is offline + deterministic."""
    def _make(ip: str):
        def _fake_getaddrinfo(host, *a, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]
        monkeypatch.setattr(url_guard.socket, "getaddrinfo", _fake_getaddrinfo)
    return _make


def test_blocks_cloud_metadata(_resolves):
    _resolves("169.254.169.254")
    assert is_safe_webhook_url("http://169.254.169.254/latest/meta-data/") is False


def test_blocks_loopback(_resolves):
    _resolves("127.0.0.1")
    assert is_safe_webhook_url("http://localhost/hook") is False


def test_blocks_private_ranges(_resolves):
    for ip in ("10.0.0.1", "192.168.1.5", "172.16.0.9"):
        _resolves(ip)
        assert is_safe_webhook_url(f"http://{ip}/x") is False


def test_blocks_non_http_schemes():
    # scheme check happens before resolution, so no monkeypatch needed
    assert is_safe_webhook_url("file:///etc/passwd") is False
    assert is_safe_webhook_url("gopher://evil/x") is False
    assert is_safe_webhook_url("ftp://host/x") is False
    assert is_safe_webhook_url("not a url") is False
    assert is_safe_webhook_url("") is False


def test_allows_public_https(_resolves):
    _resolves("13.107.42.14")  # a public IP
    assert is_safe_webhook_url("https://hooks.slack.com/services/T/B/xxxx") is True


def test_fails_closed_on_resolution_error(monkeypatch):
    def _boom(host, *a, **k):
        raise socket.gaierror("no such host")
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", _boom)
    assert is_safe_webhook_url("https://nonexistent.invalid/x") is False


def test_on_prem_override_allows_private(monkeypatch):
    monkeypatch.setenv("AUGHOR_ALLOW_PRIVATE_WEBHOOKS", "1")
    # No resolution needed under the override, but scheme + host are still required.
    assert is_safe_webhook_url("http://10.0.0.1/internal-hook") is True
    assert is_safe_webhook_url("file:///etc/passwd") is False


def test_executor_blocks_unsafe_url_at_send_time(monkeypatch):
    """fire_action must NOT POST to an unsafe URL — it records a failed log instead."""
    from aughor.actions import executor
    from aughor.actions.models import ActionTrigger, ActionPayload

    posted = {}
    monkeypatch.setattr(executor, "_post",
                        lambda *a, **k: posted.setdefault("called", True) or (200, ""))
    monkeypatch.setattr(executor, "log_action", lambda log: None)
    monkeypatch.setattr(url_guard.socket, "getaddrinfo",
                        lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))])

    trigger = ActionTrigger(id="t1", name="evil", type="webhook",
                            url="http://localhost/hook", headers={}, enabled=True)
    payload = ActionPayload(investigation_id="i", rec_index=0, recommendation="x",
                            metric_name="m", headline="h", trigger_id="t1", triggered_at="now")

    log = executor.fire_action(trigger, payload)
    assert "called" not in posted, "executor must NOT POST to a blocked URL"
    assert log.status == "failed" and "SSRF" in (log.error or "")
