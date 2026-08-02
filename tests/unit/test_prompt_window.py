"""Prompt capture as a bounded act (flag endgame, 2026-08-01).

The standing `obs.prompt_capture` switch was replaced because a privacy control that
depends on somebody remembering to close it is not a control. So the properties worth
testing are the ones a flag could not offer: it closes itself on EITHER bound, a spent
window is indistinguishable from one never opened, and a request bigger than the
ceiling is clamped rather than quietly honoured.
"""
from __future__ import annotations

import time

import pytest

from aughor.obs import prompt_window as PW


@pytest.fixture(autouse=True)
def _closed_window():
    PW.close_window()
    yield
    PW.close_window()


def test_nothing_is_captured_until_a_window_is_opened():
    assert PW.active() is False
    assert PW.consume() is False
    assert PW.status()["active"] is False


def test_an_open_window_permits_capture_and_reports_itself():
    PW.open_window(calls=3, minutes=10, opened_by="alice", reason="repro #412")
    st = PW.status()
    assert st["active"] is True and st["remaining"] == 3 and st["granted"] == 3
    assert st["opened_by"] == "alice" and st["reason"] == "repro #412"
    assert 0 < st["expires_in_seconds"] <= 600


def test_the_budget_is_spent_by_capture_and_closes_the_window():
    """The bound that a flag never had: capture stops on its own."""
    PW.open_window(calls=2, minutes=10)
    assert PW.consume() is True and PW.status()["remaining"] == 1
    assert PW.consume() is True
    assert PW.active() is False                  # spent
    assert PW.consume() is False                 # …and stays spent


def test_a_spent_window_is_indistinguishable_from_never_opened():
    """A zero-remaining row left lying around would read as 'capture configured'."""
    PW.open_window(calls=1, minutes=10)
    PW.consume()
    assert PW.status() == {"active": False, "remaining": 0, "granted": 0,
                           "expires_in_seconds": 0, "opened_by": "", "reason": ""}


def test_an_expired_window_captures_nothing_even_with_budget_left(monkeypatch):
    """The clock closes it too — an operator who opened a window and walked away is
    the case the standing flag handled worst."""
    PW.open_window(calls=50, minutes=1)
    assert PW.active() is True
    later = time.time() + 3600                       # captured BEFORE patching the clock
    monkeypatch.setattr(PW.time, "time", lambda: later)
    assert PW.active() is False
    assert PW.consume() is False


def test_an_oversized_request_is_clamped_not_honoured():
    """A window for 10,000 calls over a week IS a standing switch — the thing this
    replaces. The clamp is reported, so the operator sees what they actually got."""
    st = PW.open_window(calls=10_000, minutes=10_080)
    assert st["granted"] == PW.MAX_CALLS
    assert st["expires_in_seconds"] <= PW.MAX_MINUTES * 60


def test_closing_is_idempotent():
    PW.open_window(calls=5, minutes=5)
    assert PW.close_window()["active"] is False
    assert PW.close_window()["active"] is False


def test_a_store_failure_means_no_capture(monkeypatch):
    """Fail-safe direction: observability must never WIDEN what it observes."""
    PW.open_window(calls=5, minutes=5)
    monkeypatch.setattr(PW, "_ledger", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert PW.active() is False
    assert PW.consume() is False


def test_capture_prompt_stores_content_only_inside_a_window():
    """The consumer contract, end to end — session_log defers to the window."""
    from aughor.obs.session_log import capture_prompt

    assert capture_prompt(system="SYS", user="USER") == {}
    PW.open_window(calls=1, minutes=5)
    assert capture_prompt(system="SYS", user="USER")["system_prompt"] == "SYS"
    assert capture_prompt(system="SYS", user="USER") == {}      # budget spent


def test_an_empty_capture_call_does_not_spend_budget():
    """A call with nothing to store must not shorten the operator's window."""
    PW.open_window(calls=1, minutes=5)
    from aughor.obs.session_log import capture_prompt

    assert capture_prompt() == {}
    assert PW.status()["remaining"] == 1


def test_budget_is_not_spent_while_recording_is_off(monkeypatch):
    """`capture_prompt` is evaluated as an ARGUMENT to `emit`, which writes nothing
    when the log is off — so consuming there would silently drain an operator's
    window on calls that stored no content at all. Recording is hardwired on today,
    so the guard is pinned by patching the one function that decides."""
    from aughor.obs import session_log
    monkeypatch.setattr(session_log, "enabled", lambda: False)
    PW.open_window(calls=3, minutes=5)
    from aughor.obs.session_log import capture_prompt

    assert capture_prompt(system="SYS", user="USER") == {}
    assert PW.status()["remaining"] == 3          # untouched
