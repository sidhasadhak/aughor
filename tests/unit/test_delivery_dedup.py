"""One period, one delivery (Layer 4.1a).

A brief and a webhook are OUTWARD sends: a duplicate reaches a real person, and a
suppressed one is worse. Three independent mechanisms could deliver the same effect
twice, and none of them needed anything exotic to fire:

1. **The crash window.** Effects dispatch at step 3, but the only durable write is the
   run row at the end, and due-ness reads that row back. Dying in between means the
   next tick sees no run and fires the same period again.
2. **The in-tick retry, with no crash at all.** A webhook that timed out *after* the
   receiver already had it was reported failed and retried. A timeout is not a known
   failure — it is an unknown outcome, and retrying an unknown send is what duplicates
   it.
3. **The innermost HTTP retry**, whose payload carried a fresh timestamp per attempt,
   so the receiver could not dedup either.

The tests are written so each would have failed before the fix, and so that the
opposite failure — a legitimate new period being swallowed — fails too.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aughor.automations.engine import run_automation
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome


_SEQ = [0]


def _automation(**kw) -> Automation:
    """A fresh automation id per call — the RUN store is session-scoped (unlike the
    per-test claim ledger), so a shared id would let one test's run rows decide
    another's due-ness."""
    _SEQ[0] += 1
    base = dict(
        id=f"auto-dedup-test-{_SEQ[0]}",
        conn_id="c1",
        name="daily brief",
        conditions=[Condition(kind="schedule", config={"cron": "0 8 * * *"})],
        effects=[Effect(kind="notify", config={"trigger_id": "hook-1"})],
    )
    base.update(kw)
    return Automation(**base)


@pytest.fixture(autouse=True)
def _isolated_claims(tmp_path, monkeypatch):
    """The claim store is durable by design; keep the suite off the real ledger."""
    from aughor.kernel.ledger import Ledger
    led = Ledger(str(tmp_path / "claims.db"))
    monkeypatch.setattr(Ledger, "default", staticmethod(lambda: led))
    return led


class _Sends:
    """A dispatcher that counts real deliveries."""

    def __init__(self, status="executed"):
        self.calls: list[str] = []
        self.status = status

    def __call__(self, effect, automation) -> EffectOutcome:
        self.calls.append(effect.kind)
        return EffectOutcome(kind=effect.kind, target=effect.target(), status=self.status)


# ── 1. the crash window ──────────────────────────────────────────────────────

def test_a_crash_after_the_send_does_not_resend_the_same_period():
    """The bug in one test: the run row never got written, so the next tick believed
    the automation had never run."""
    auto = _automation()
    sends = _Sends()
    now = datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)

    def _send_then_die(effect, automation):
        sends(effect, automation)
        # A BaseException models the process dying: it escapes the engine's
        # `except Exception` guards, so `_finish` never runs and no run row lands —
        # which is exactly the window a deploy or an OOM opens.
        raise KeyboardInterrupt("process died mid-delivery")

    with pytest.raises(KeyboardInterrupt):
        run_automation(auto, now=now, dispatch=_send_then_die)
    assert sends.calls == ["notify"]

    # Second tick, same period. Reading only the run row, this looked like "first run".
    run_automation(auto, now=now + timedelta(minutes=5), dispatch=sends)
    assert sends.calls == ["notify"], "the same period must never deliver twice"


def test_a_new_period_still_delivers():
    """The failure that would be worse than the bug: silently swallowing a real send."""
    auto = _automation()
    sends = _Sends()

    run_automation(auto, now=datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc), dispatch=sends)
    run_automation(auto, now=datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc), dispatch=sends)
    assert sends.calls == ["notify", "notify"], "tomorrow's brief must still go out"


# ── 2. the in-tick retry ─────────────────────────────────────────────────────

def test_a_timeout_on_an_outward_send_is_not_retried():
    """A timeout means we do not know whether it arrived. Retrying an unknown send is
    how one alert becomes two."""
    auto = _automation(max_retries=3)
    sends = _Sends(status="uncertain")
    run_automation(auto, now=datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc),
                   dispatch=sends, persist=False)
    assert len(sends.calls) == 1, "an uncertain outward send must not be retried"


def test_a_real_failure_is_still_retried():
    """A refused send never arrived, so trying again is free of duplicate risk — the
    retry ladder must survive this fix."""
    auto = _automation(max_retries=1)
    sends = _Sends(status="failed")
    run_automation(auto, now=datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc),
                   dispatch=sends, persist=False, sleeper=lambda s: None)
    assert len(sends.calls) == 2, "a known failure is still worth one retry"


# ── 3. the receiver's half ───────────────────────────────────────────────────

def _payload(delivery_key: str, triggered_at: str) -> dict:
    from aughor.notifications.models import ActionPayload
    return ActionPayload(
        investigation_id="automation:auto-dedup-test", rec_index=0,
        recommendation="r", metric_name="", headline="h",
        trigger_id="hook-1", triggered_at=triggered_at,
        delivery_key=delivery_key,
    ).to_dict()


def test_the_outbound_payload_carries_a_stable_idempotency_key():
    """The innermost HTTP retry is ours to make harmless: the same delivery must
    present the same key on every attempt, so a receiver can drop the duplicate."""
    key = "auto-dedup-test:2026-08-08T08:00:00Z"
    first = _payload(key, "2026-08-08T09:00:00Z")
    second = _payload(key, "2026-08-08T09:00:31Z")
    assert first["delivery_key"] == second["delivery_key"]
    assert first["delivery_key"], "a receiver cannot dedup without a key"


def test_the_key_is_not_a_fresh_timestamp():
    """`triggered_at` was the only thing distinguishing attempts and it changed on
    every one — which is why the receiver could not tell a retry from a new alert."""
    key = "auto-dedup-test:2026-08-08T08:00:00Z"
    a = _payload(key, "2026-08-08T09:00:00Z")
    b = _payload(key, "2026-08-08T09:00:31Z")
    assert a["triggered_at"] != b["triggered_at"]
    assert a["delivery_key"] == b["delivery_key"]


def test_a_caller_with_no_period_still_builds_a_payload():
    """Every other ActionPayload call site predates this field; none should break."""
    assert _payload("", "2026-08-08T09:00:00Z")["delivery_key"] == ""
