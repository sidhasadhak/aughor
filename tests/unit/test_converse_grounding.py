"""The closing prose is held to the rows the turn executed.

Found live. Asked "give me route wise number of flights", the quick path answered with
a tidy markdown table — ZRH-LHR 108, GVA-LHR 96, ZRH-CDG 84, ZRH-AMS 72 — while the
chart beside it, drawn from the same 84 rows of `main.flights`, showed nothing of the
sort. The real counts were 28, 42, 35, 21. Every other number the user saw that turn
came from a result set; the sentence above them did not, and nothing compared the two.

Deep analysis, asked the same question, computed the right totals. So this is not a SQL
problem — it is the loop's final text being whatever the model typed.
"""
from __future__ import annotations

import pytest

from aughor.agent.converse_tools import ground_answer_numbers

# The rows the query really returned (route, flights) — the shape of the live case.
_ROWS = [["ZRH-LHR", 28], ["GVA-LHR", 42], ["ZRH-LCY", 21], ["GVA-LCY", 28],
         ["ZRH-CDG", 35], ["GVA-CDG", 21], ["ZRH-FRA", 21], ["GVA-FRA", 42]]

_FABRICATED = ("The number of flights per route is as follows: ZRH-LHR 108, "
               "GVA-LHR 96, ZRH-CDG 84, ZRH-AMS 72.")
_FAITHFUL = ("The busiest routes are GVA-LHR and GVA-FRA at 42 flights each, "
             "followed by ZRH-CDG at 35.")


class _Provider:
    """Stands in for the coder binding. `reply` is what the re-ask returns."""
    def __init__(self, reply=None, raises=False):
        self.reply, self.raises, self.calls = reply, raises, []

    def complete(self, *, system, user, response_model, temperature=0.1):
        self.calls.append(user)
        if self.raises:
            raise RuntimeError("provider down")
        return response_model(answer=self.reply)


def test_a_faithful_answer_is_left_exactly_alone():
    """The guard may only ever remove a false claim — never touch a true one."""
    out, receipt = ground_answer_numbers(_FAITHFUL, _ROWS, question="q")
    assert out == _FAITHFUL
    assert receipt is None


def test_the_live_failure_does_not_reach_the_user():
    """The headline case: numbers no cell contains must not ship as fact."""
    p = _Provider(reply=_FAITHFUL)
    out, receipt = ground_answer_numbers(_FABRICATED, _ROWS, question="q", provider=p)

    assert "108" not in out and "96" not in out
    assert out == _FAITHFUL                      # the grounded rewrite served instead
    assert receipt["action"] == "rewrote the answer"
    assert "108" in receipt["detail"]
    # it was told which values it may cite
    assert "28" in p.calls[0] and "42" in p.calls[0]


def test_a_rewrite_that_is_still_wrong_is_withheld_not_shipped():
    """One chance, like the explorer's phase 8. A second fabrication is not a third."""
    p = _Provider(reply="Actually it was 500 flights on ZRH-LHR.")
    out, receipt = ground_answer_numbers(_FABRICATED, _ROWS, question="q", provider=p)

    assert "500" not in out and "108" not in out
    assert "could not ground" in out
    assert receipt["action"] == "withheld the answer"


def test_a_dead_provider_still_withholds_the_claim():
    """Fail-open on the REWRITE, never on the verdict: if we cannot fix the sentence we
    still do not publish it."""
    p = _Provider(raises=True)
    out, receipt = ground_answer_numbers(_FABRICATED, _ROWS, question="q", provider=p)

    assert "108" not in out
    assert receipt["action"] == "withheld the answer"


@pytest.mark.parametrize("rows, why", [
    ([], "no rows to check against"),
    (None, "the turn ran no query at all"),
])
def test_without_evidence_the_guard_stands_down(rows, why):
    """A turn with nothing to ground against must answer exactly as it always did —
    the guard removes false claims, it does not invent failures."""
    out, receipt = ground_answer_numbers(_FABRICATED, rows, question="q")
    assert (out, receipt) == (_FABRICATED, None), why


def test_prose_carrying_no_numbers_is_untouched():
    """Nothing enforced ⇒ nothing to verify; no provider call is made."""
    p = _Provider(reply="should not be called")
    out, receipt = ground_answer_numbers(
        "The routes are concentrated on the two Swiss hubs.", _ROWS, provider=p)
    assert receipt is None and p.calls == []
