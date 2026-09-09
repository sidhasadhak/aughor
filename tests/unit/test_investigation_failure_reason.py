"""A failed investigation has to say why.

`fail_investigation` took a status and nothing else, so the cause was discarded at the one
moment anything knew it — every failed run on this platform was unexplainable by
construction. Measured 2026-09-06: run a0c735ef sat at status=failed with headline=None,
hypotheses=0, queries=0, report={} and 878 seconds of silence. Why it died is not
recoverable, because nothing ever wrote it down.

No fixture here on purpose: `AUGHOR_HISTORY_DB` is in the conftest allowlist, so the store
is already isolated. Reloading the module to point it elsewhere is the trap that leaves two
live modules and passes alone while failing in the suite.
"""
from __future__ import annotations

from aughor.db import history


def test_a_failure_records_its_reason():
    inv = history.create_investigation("why did refunds spike?", "conn-fr1")
    history.fail_investigation(inv, status="failed", reason="provider timed out after 180s")
    row = history.get_investigation(inv)
    assert row["status"] == "failed"
    assert row["error"] == "provider timed out after 180s"


def test_a_caller_that_does_not_know_writes_an_honest_empty():
    """'' means nobody knew, which is the truth. A fabricated cause would be worse than
    the silence this migration exists to end."""
    inv = history.create_investigation("q", "conn-fr2")
    history.fail_investigation(inv, status="timed_out")
    row = history.get_investigation(inv)
    assert row["status"] == "timed_out" and row["error"] == ""


def test_the_reason_is_capped_so_a_traceback_cannot_bloat_the_row():
    inv = history.create_investigation("q", "conn-fr3")
    history.fail_investigation(inv, status="failed", reason="x" * 9000)
    assert len(history.get_investigation(inv)["error"]) == 2000


def test_a_running_row_carries_no_reason_yet():
    """Additive and defaulted — a row that has not failed must not look explained."""
    inv = history.create_investigation("q", "conn-fr4")
    assert history.get_investigation(inv)["error"] == ""


# ── the runner surfaces it ───────────────────────────────────────────────────────────

def test_the_runner_reports_the_recorded_reason_not_just_the_status(monkeypatch):
    """The Sep 6 chain end to end: nothing on the stream, a row that says why, and a
    caller that now hears the CAUSE instead of `executed`."""
    from aughor.runners import investigation as runner
    from tests.unit.test_runners_investigation import _fake_ask, _no_loop, _req

    _no_loop(monkeypatch)
    _fake_ask(monkeypatch, {"type": "start", "investigation_id": "inv-900"})
    monkeypatch.setattr("aughor.db.history.get_investigation",
                        lambda i: {"status": "failed", "query_count": 0,
                                   "error": "the run ended without a terminal status "
                                            "— cancelled (deadline or budget)"})

    run = runner.run_investigation(_req(), idempotency_key="k")
    assert run.status == "failed" and not run.ok
    assert "cancelled (deadline or budget)" in run.message


def test_a_failure_with_no_recorded_reason_still_reports_the_status(monkeypatch):
    """The reason is an ADDITION, never a precondition: a row from before this migration
    must still be reported as a failure rather than slipping back to `executed`."""
    from aughor.runners import investigation as runner
    from tests.unit.test_runners_investigation import _fake_ask, _no_loop, _req

    _no_loop(monkeypatch)
    _fake_ask(monkeypatch, {"type": "start", "investigation_id": "inv-old"})
    monkeypatch.setattr("aughor.db.history.get_investigation",
                        lambda i: {"status": "failed", "query_count": 0, "error": ""})

    run = runner.run_investigation(_req(), idempotency_key="k")
    assert run.status == "failed" and "ended failed" in run.message
