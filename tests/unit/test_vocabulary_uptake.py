"""AV-M (§3.11) — the meter that says whether the answer vocabulary is used.

Every case here is a way the meter could report a confident wrong number, because that is
the only failure that matters: a meter built to detect an inert feature, reading zero for
its own reasons, would confirm the thing it was meant to test.
"""
from __future__ import annotations

import pytest

from aughor.obs.vocabulary_uptake import vocabulary_uptake


class _Ledger:
    """A session log holding exactly the rows given, served by kind like the real one."""

    def __init__(self, rows):
        self.rows = rows
        self.kinds_asked: list[str] = []

    def session_events(self, *, kind=None, org_id=None, limit=None, **kw):
        self.kinds_asked.append(kind)
        return [r for r in self.rows if r.get("kind") == kind]


@pytest.fixture
def ledger(monkeypatch):
    def _install(rows):
        led = _Ledger(rows)
        monkeypatch.setattr("aughor.kernel.ledger.Ledger.default",
                            classmethod(lambda cls: led))
        return led
    return _install


def call(trace, at="2026-09-15T10:00:00Z"):
    return {"kind": "tool_call", "name": "ask.converse", "trace_id": trace, "at": at}


def present(trace, at="2026-09-15T10:00:05Z"):
    # As the LIVE log records it — a result, never a call. See the next test.
    return {"kind": "tool_call_result", "name": "present", "trace_id": trace, "at": at}


# ── the defect this meter shipped with ───────────────────────────────────────────

def test_present_is_counted_even_though_it_only_emits_a_RESULT(ledger):
    """🔴 The first cut read `kind="tool_call"` only and reported 0 uptake on a feature
    that had been used four times. Measured on the live log: `ask.converse` appears as a
    `tool_call` and never as a result; `present` appears as a `tool_call_result` and never
    as a call. A tool's evidence may live under either kind."""
    led = ledger([call("t1"), present("t1"), call("t2")])
    out = vocabulary_uptake()

    assert out["turns"] == 2
    assert out["in_parts"] == 1
    assert out["rate"] == 0.5
    # And the reason it works: both kinds are asked for.
    assert set(led.kinds_asked) == {"tool_call", "tool_call_result"}


# ── an unreadable log is UNKNOWN, never zero ─────────────────────────────────────

def test_an_unreadable_log_reports_measured_false_and_no_rate(monkeypatch):
    class _Boom:
        def session_events(self, **kw):
            raise RuntimeError("no such table: session_events")

    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default",
                        classmethod(lambda cls: _Boom()))
    out = vocabulary_uptake()
    # 0% would be a claim about the product; this is a claim about the log.
    assert out["measured"] is False and out["rate"] is None


def test_no_converse_turn_at_all_is_also_unmeasured(ledger):
    """A deployment that has never had a converse turn has not declined the vocabulary —
    it has never been offered it. A 0% there would indict a feature nobody could reach."""
    ledger([{"kind": "tool_call", "name": "sql.execute", "trace_id": "t9",
             "at": "2026-09-18T09:00:00Z"}])
    out = vocabulary_uptake()
    assert out["measured"] is False and out["rate"] is None and out["turns"] == 0


# ── the denominator means one thing ──────────────────────────────────────────────

def test_a_turn_is_counted_once_however_many_parts_it_emitted(ledger):
    """Counting CALLS would let one chatty turn read as a trend."""
    ledger([call("t1"), present("t1"), present("t1"), present("t1")])
    out = vocabulary_uptake()
    assert out["turns"] == 1 and out["in_parts"] == 1 and out["rate"] == 1.0


def test_a_present_outside_the_population_is_not_counted(ledger):
    """`present` on a trace with no converse call would mean the tool was offered by a
    path this module does not know about. Counting it would widen the denominator's
    meaning silently — and inflate uptake while doing it."""
    ledger([call("t1"), present("t2")])
    out = vocabulary_uptake()
    assert out["turns"] == 1 and out["in_parts"] == 0


def test_deep_runs_and_automations_are_not_in_the_denominator(ledger):
    """`present` is offered only on a streaming converse turn, so a deep investigation
    could never have used it and must not be counted against it. Including them would
    drive the rate toward zero by construction."""
    ledger([
        call("t1"), present("t1"),
        {"kind": "tool_call", "name": "sql.execute", "trace_id": "deep1",
         "at": "2026-09-18T09:00:00Z"},
        {"kind": "tool_call", "name": "automation.synthesize", "trace_id": "auto1",
         "at": "2026-09-18T09:00:00Z"},
    ])
    out = vocabulary_uptake()
    assert out["turns"] == 1 and out["rate"] == 1.0


# ── the trend, because the ratio alone hides the finding ─────────────────────────

def test_by_day_separates_shipped_then_never_used_from_steady_use(ledger):
    """3 of 41 all on one day and 3 of 41 spread over a month are the same ratio and
    opposite findings. The live log is the first shape: every use on the day it shipped."""
    ledger([
        call("a", "2026-09-15T10:00:00Z"), present("a", "2026-09-15T10:00:01Z"),
        call("b", "2026-09-15T11:00:00Z"),
        call("c", "2026-09-18T09:00:00Z"),
        call("d", "2026-09-18T09:30:00Z"),
    ])
    out = vocabulary_uptake()
    assert out["by_day"][0] == {"day": "2026-09-18", "turns": 2, "in_parts": 0}
    assert out["by_day"][1] == {"day": "2026-09-15", "turns": 2, "in_parts": 1}


def test_a_turn_is_dated_by_its_EARLIEST_event(ledger):
    """A turn spanning midnight must not land on the later day and read as activity on a
    day nobody asked anything."""
    ledger([call("t1", "2026-09-18T23:59:00Z"), call("t1", "2026-09-19T00:01:00Z")])
    out = vocabulary_uptake()
    assert [d["day"] for d in out["by_day"]] == ["2026-09-18"]
