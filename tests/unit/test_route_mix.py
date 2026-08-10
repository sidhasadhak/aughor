"""The route receipt — `ask.converse`'s graduation input (Wave 6).

The flag's stated exit is the headline receipt, the parity invariant, AND data on the
converse/fast-path ratio: whether conversation should become the default door is a
measurement, not a taste.

The emission side already existed — the converse body logs itself, and every `/ask` turn
logs a final response. What did not exist was anything that READ them together, so there
was a numerator with nothing to divide it by. These tests pin the fold, and specifically
the three ways it could quietly lie: an undefined share reported as zero, unfinished turns
inflating the numerator, and counting markers instead of turns.
"""
from __future__ import annotations

import pytest

from aughor.obs import session_log


class _FakeLedger:
    """Stands in for the ledger so these tests read a known corpus, not whatever this
    machine happens to have run today."""

    def __init__(self, finals, tool_calls):
        self._finals, self._tools = finals, tool_calls

    def session_events(self, *, kind, org_id=None, limit=5000):
        if kind == session_log.FINAL_RESPONSE:
            return self._finals
        if kind == session_log.TOOL_CALL:
            return self._tools
        return []


def _install(monkeypatch, finals, tools):
    import aughor.kernel.ledger as led
    monkeypatch.setattr(led.Ledger, "default", staticmethod(lambda: _FakeLedger(finals, tools)))


def _final(trace, name="ask"):
    return {"trace_id": trace, "name": name}


def _mark(trace, *, steps=2, stop="answered", tools=("run_sql",), injected=1000):
    return {"trace_id": trace, "name": "ask.converse", "row_count": steps,
            "payload": {"stop_reason": stop, "tools": list(tools),
                        "injected_chars": injected}}


def test_the_ratio_is_computed_from_both_halves(monkeypatch):
    """The headline: three /ask turns, one of them a conversation."""
    _install(monkeypatch, [_final("t1"), _final("t2"), _final("t3")], [_mark("t2")])

    mix = session_log.route_mix()

    assert mix["ask_turns"] == 3
    assert mix["converse_turns"] == 1
    assert mix["fast_path_turns"] == 2
    assert mix["converse_share"] == round(1 / 3, 3)


def test_no_turns_yields_an_undefined_share_not_zero(monkeypatch):
    """A share of zero turns is undefined. Reporting 0.0 would read as 'converse is never
    chosen' — a claim about behaviour made from an absence of data."""
    _install(monkeypatch, [], [])

    assert session_log.route_mix()["converse_share"] is None


def test_an_unfinished_converse_turn_does_not_inflate_the_share(monkeypatch):
    """A marker whose turn never completed — crash, disconnect — is not in the
    denominator, so it must not be counted in the numerator either. It is reported
    separately instead of dropped, because a rising count means turns are dying."""
    _install(monkeypatch, [_final("t1")], [_mark("t1"), _mark("ghost")])

    mix = session_log.route_mix()

    assert mix["converse_turns"] == 1, "an unfinished turn was counted as served"
    assert mix["converse_share"] == 1.0
    assert mix["converse_unfinished"] == 1


def test_turns_are_counted_not_markers(monkeypatch):
    """One turn emitting two markers must count once. It emits one today; counting rows
    would become a lie the moment that changes, and nothing would say so."""
    _install(monkeypatch, [_final("t1"), _final("t2")], [_mark("t1"), _mark("t1")])

    assert session_log.route_mix()["converse_turns"] == 1


def test_other_doors_are_not_in_the_denominator(monkeypatch):
    """`/chat` is a different door with its own body. Counting it would answer a question
    nobody asked and dilute the one that was."""
    _install(monkeypatch, [_final("t1"), _final("c1", name="chat")], [_mark("t1")])

    mix = session_log.route_mix()

    assert mix["ask_turns"] == 1 and mix["converse_share"] == 1.0


def test_the_cost_detail_rides_along(monkeypatch):
    """'converse is chosen more' and 'converse costs more' are answerable from one read —
    otherwise widening the routing is a decision made on frequency alone."""
    _install(monkeypatch, [_final("t1"), _final("t2")],
             [_mark("t1", steps=2, tools=("list_tables", "run_sql"), injected=1000),
              _mark("t2", steps=4, stop="budget", tools=("run_sql",), injected=3000)])

    mix = session_log.route_mix()

    assert mix["converse_mean_steps"] == 3.0
    assert mix["converse_mean_injected_chars"] == 2000.0
    assert mix["converse_stop_reasons"] == {"answered": 1, "budget": 1}
    assert mix["converse_tools"]["run_sql"] == 2


@pytest.mark.parametrize("bad", [None, 0, ""])
def test_a_missing_trace_id_never_becomes_a_turn(monkeypatch, bad):
    """Rows without a trace id cannot be correlated to a turn. Letting one through would
    make an unattributable marker look like a served conversation."""
    _install(monkeypatch, [_final("t1")], [{"trace_id": bad, "name": "ask.converse",
                                            "row_count": 1, "payload": {}}])

    assert session_log.route_mix()["converse_turns"] == 0


# ── the write path, which the fold's own tests never crossed ──────────────────

def test_tool_names_survive_the_round_trip_through_the_store():
    """Every test above hands `route_mix` a payload it built by hand. That is the right
    shape for pinning the fold, and it is also how a real defect stayed invisible while
    the fold was fully covered: no test ever put a payload THROUGH `emit` and read it
    back, so nothing exercised the one step that could change it.

    It did. `_clip` stringified anything that was not a scalar, so
    `{"tools": ["list_tables", "run_sql"]}` was stored as the repr
    `"['list_tables', 'run_sql']"`. `converse_tools` then iterated a string and tallied
    CHARACTERS — the live receipt reported `{"'": 4, "l": 3, "s": 3, ...}` as the tools a
    conversation had used. Only reading the endpoint against real data showed it, which
    is the argument for the endpoint as much as for the fix.
    """
    from aughor.kernel.ledger import Ledger

    ledger = Ledger.default()
    ledger.session_events_clear()
    try:
        session_log.emit(session_log.FINAL_RESPONSE, name="ask",
                         trace_id="rt1", payload={"answered": True})
        session_log.emit(session_log.TOOL_CALL, name="ask.converse", trace_id="rt1",
                         row_count=2,
                         payload={"body": "converse", "stop_reason": "answered",
                                  "tools": ["list_tables", "run_sql"],
                                  "injected_chars": 1000})

        mix = session_log.route_mix()

        assert mix["converse_turns"] == 1
        assert mix["converse_tools"] == {"list_tables": 1, "run_sql": 1}, (
            "tool names must survive emit->store->read; a character histogram here means "
            "a payload value was stringified on the way in"
        )
    finally:
        ledger.session_events_clear()
