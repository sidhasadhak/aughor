"""VA-9a — every call that leaves the platform is seen and budgeted.

Measured before building (2026-08-29): `slackbots/post.py`, `slackbots/verify.py` and
`notifications/executor.py` emitted no span and consulted no cap. Outbound calls were
invisible in the waterfall and unbudgeted, which is why this slice precedes the MCP
consumer — adding third-party servers to a plane that cannot see or budget what leaves
scales the blindness, not the capability.

The properties locked here:

* **The call is recorded on EVERY path** — success, failure and refusal alike. A record
  written only on success gives a usage picture that flatters itself and hides exactly
  the failing counterparty worth noticing.
* **`observed_usage` can actually COUNT it.** A span alone leaves the cap plane blind:
  it reads session events, not spans. That gap is what made deliverable 5 read as
  "instrumented" while nothing could be metered.
* **Counted toward `calls` and nothing else.** An external call has no tokens and no
  model cost; folding it into those would invent spend.
* **Its own event kind, never TOOL_CALL.** Every `mlflow_tool_span` emits TOOL_CALL —
  2554 live events against llm_call's 3109 — so reusing it would nearly double `calls`
  for reasons unrelated to anything leaving the platform.
* **The cap is checked BEFORE the work**, and a blocked call reports "nothing was sent"
  rather than "uncertain", so the send can legitimately be retried later.
* **Telemetry failure never fails a send.**
"""
from __future__ import annotations

import pytest

from aughor.govern.outbound import OutboundBlocked, external_call


class _Decision:
    """Stands in for CapDecision — matching its REAL interface (`allowed`, `reason`),
    which is `allowed: bool` and a `reason` property, not a `blocked` flag. A fake that
    invents a field the real class lacks produces a guard that never fires."""

    def __init__(self, allowed: bool, reason: str = ""):
        self.allowed = allowed
        self.reason = reason


@pytest.fixture
def emitted(monkeypatch):
    """Capture the EXTERNAL_CALL events reaching the session log.

    Filtered on purpose: the enclosing span emits its own `tool_call` /
    `tool_call_result` pair, so an unfiltered capture sees three events per call. That
    overlap is also why `observed_usage` must not count TOOL_CALL toward `calls` — it
    would count every external call twice, once as its span and once as itself.
    """
    seen: list[dict] = []
    import aughor.obs.session_log as slog
    real_emit = slog.emit

    def _capture(kind, **kw):
        if kind == slog.EXTERNAL_CALL:
            seen.append({"kind": kind, **kw})
        return real_emit(kind, **kw)

    monkeypatch.setattr(slog, "emit", _capture)
    return seen


def _allow(monkeypatch, allowed=True, reason=""):
    monkeypatch.setattr("aughor.govern.usage_caps.check",
                        lambda **kw: _Decision(allowed, reason))


# ── recorded on every path ───────────────────────────────────────────────────────

def test_a_successful_call_is_recorded(monkeypatch, emitted):
    _allow(monkeypatch)
    with external_call("slack", "chat.postMessage") as extra:
        extra["channel"] = "C1"
    assert len(emitted) == 1
    ev = emitted[0]
    assert ev["kind"] == "external_call"
    assert ev["name"] == "slack.chat.postMessage"
    assert ev["ok"] is True
    assert ev["provider"] == "slack"
    assert ev["payload"]["channel"] == "C1", "the body's annotations ride out on the event"


def test_a_FAILING_call_is_still_recorded(monkeypatch, emitted):
    """The one a naive implementation misses. A counterparty that always fails would
    otherwise be invisible in exactly the usage picture meant to surface it."""
    _allow(monkeypatch)
    with pytest.raises(ValueError):
        with external_call("slack", "chat.postMessage"):
            raise ValueError("slack said no")
    assert len(emitted) == 1
    assert emitted[0]["ok"] is False
    assert emitted[0]["error_class"] == "ValueError"


# ── the cap, checked before the work ─────────────────────────────────────────────

def test_a_blocking_cap_refuses_before_the_call_is_made(monkeypatch, emitted):
    _allow(monkeypatch, allowed=False, reason="Usage cap reached: 100 calls / 24h")
    ran = []
    with pytest.raises(OutboundBlocked) as exc:
        with external_call("slack", "chat.postMessage"):
            ran.append(1)
    assert ran == [], "the body must NOT run once a cap blocks"
    assert "100 calls" in exc.value.reason


def test_an_alerting_cap_proceeds(monkeypatch, emitted):
    """`alert` records and proceeds — what alert means everywhere else in the plane."""
    _allow(monkeypatch, allowed=True)
    ran = []
    with external_call("slack", "chat.postMessage"):
        ran.append(1)
    assert ran == [1]


def test_an_unreadable_cap_store_fails_OPEN(monkeypatch, emitted):
    """A cap is a budget. Losing sight of a budget is not a reason to refuse work a human
    asked for — the opposite posture to the approval gate, which governs permission and
    fails closed."""
    monkeypatch.setattr("aughor.govern.usage_caps.check",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("no store")))
    ran = []
    with external_call("slack", "auth.test"):
        ran.append(1)
    assert ran == [1]


def test_a_broken_session_log_never_fails_the_send(monkeypatch):
    import aughor.obs.session_log as slog
    _allow(monkeypatch)
    real_emit = slog.emit

    def _boom(kind, **kw):
        if kind == slog.EXTERNAL_CALL:
            raise RuntimeError("log down")
        return real_emit(kind, **kw)

    monkeypatch.setattr(slog, "emit", _boom)
    with external_call("slack", "chat.postMessage"):
        pass    # must not raise


# ── the count: a span alone would leave the cap plane blind ──────────────────────

def test_external_calls_count_toward_calls_and_nothing_else(monkeypatch):
    from datetime import datetime, timezone

    from aughor.govern import usage_caps as UC

    now = datetime.now(timezone.utc).isoformat()

    class _FakeLedger:
        def session_events(self, **kw):
            rows = [
                {"at": now, "kind": "llm_call", "provider": "openrouter", "model": "m",
                 "ok": True, "prompt_tokens": 10, "completion_tokens": 5,
                 "total_tokens": 15, "org_id": "default", "user_id": "",
                 "duration_ms": 1.0, "payload": {}},
                {"at": now, "kind": "external_call", "provider": "slack", "ok": True,
                 "org_id": "default", "user_id": "", "duration_ms": 5.0, "payload": {}},
                {"at": now, "kind": "external_call", "provider": "webhook", "ok": False,
                 "org_id": "default", "user_id": "", "duration_ms": 5.0, "payload": {}},
            ]
            kind = kw.get("kind")
            return [r for r in rows if not kind or r["kind"] == kind]

    import aughor.kernel.ledger as ledger_mod
    monkeypatch.setattr(ledger_mod.Ledger, "default", classmethod(lambda cls: _FakeLedger()))

    totals = UC.observed_usage(window_hours=24)
    assert totals["calls"] == 3.0, "1 llm call + 2 external calls"
    assert totals["total_tokens"] == 15.0, "an external call has no tokens"
    assert totals["cost_usd"] == 0.0, "and no model cost — counting it would invent spend"


def test_an_external_call_outside_the_window_is_not_counted(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from aughor.govern import usage_caps as UC

    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()

    class _FakeLedger:
        def session_events(self, **kw):
            rows = [{"at": old, "kind": "external_call", "provider": "slack", "ok": True,
                     "org_id": "default", "user_id": "", "duration_ms": 1.0, "payload": {}}]
            kind = kw.get("kind")
            return [r for r in rows if not kind or r["kind"] == kind]

    import aughor.kernel.ledger as ledger_mod
    monkeypatch.setattr(ledger_mod.Ledger, "default", classmethod(lambda cls: _FakeLedger()))
    assert UC.observed_usage(window_hours=24)["calls"] == 0.0


# ── the call sites keep their never-raise contracts ──────────────────────────────

def test_a_blocked_slack_post_reports_nothing_was_sent(monkeypatch):
    """Not 'uncertain': nothing left the machine, so a retry once the window rolls over
    is legitimate. Marking it uncertain would suppress a send that never happened."""
    from aughor.slackbots.post import post_as_bot
    _allow(monkeypatch, allowed=False, reason="Usage cap reached: 10 calls / 24h")
    ok, info = post_as_bot("xoxb-t", "C1", "hello")
    assert ok is False
    assert info.get("blocked") is True
    assert info.get("uncertain") is not True


def test_a_blocked_auth_test_reports_NOT_VERIFIED_not_a_bad_token(monkeypatch):
    """Telling a user their token is wrong when it was never checked sends them to
    rotate a credential that was fine."""
    from aughor.slackbots.verify import auth_test
    _allow(monkeypatch, allowed=False, reason="Usage cap reached")
    ok, info = auth_test("xoxb-t")
    assert ok is False and "not verified" in info["error"]
