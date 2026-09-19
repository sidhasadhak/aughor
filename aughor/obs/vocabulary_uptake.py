"""AV-M (§3.11, the third movement) — is the answer vocabulary actually used?

AV-0…AV-3 gave a converse turn a way to answer in PARTS — fact rows, a status badge, a
progress bar with a real denominator, a folded section, door-bound actions, a live
proposal card — instead of a paragraph. The wave that shipped them specified this
measurement in the same breath, and for a reason this repository has paid for repeatedly:

* the chart vocabulary was named **zero times in 1,477 findings** after it shipped;
* the declared-actions plane was complete, tested, and **inert**;
* §7's standing lesson is that features stall at TESTED, not at LEVERAGED.

A vocabulary nobody uses looks exactly like a vocabulary that works, from the inside. The
only difference is a number, and until this module there was none — answering "is it being
used" meant opening sqlite by hand.

**The population is the turns where the tool was OFFERED**, not every turn the product
served. `present` is offered only on a streaming converse turn (a sync caller has nowhere
to render parts), so a deep investigation or an automation run could never have used it and
must not be counted against it. `ask.converse` marks such a turn — **and so does a `present`
call itself**, because a turn that used the vocabulary self-evidently had it.

That second clause is not belt-and-braces either. Measured 2026-09-19: of the 16 traces
using a Spotlight `platform_*` tool, 15 carry the `ask.converse` marker and one does not —
and that one called `present` TWICE before ending in an `execution_error`. Keyed on the
marker alone it fell out of the numerator AND the denominator, so a turn that used the
vocabulary and then crashed was invisible to a meter whose whole job is to notice use.
🔑 **A turn that failed still happened.** Dropping it silently biases in exactly the
direction that flatters a quiet feature.

**An unreadable log reports `None`, never zero.** A failed probe is not an absence — SP-7's
law, and the reason `score_proposal` returns `None` rather than a grade it cannot justify.
Reporting 0% uptake when the session log is missing would manufacture the exact conclusion
this module exists to test.
"""
from __future__ import annotations

from typing import Optional

#: The tool call that marks a turn as a streaming converse turn — the only shape where
#: `present` is offered, and therefore the only fair denominator.
CONVERSE_TOOL = "ask.converse"

#: The tool a turn calls to answer in parts.
PRESENT_TOOL = "present"


def vocabulary_uptake(*, org_id: Optional[str] = None, scan: int = 20000) -> dict:
    """How many converse turns answered in parts rather than prose.

    Returns ``{turns, in_parts, rate, by_day, measured}``. ``measured`` is False and
    ``rate`` is None when the session log could not be read or holds no such turn at
    all — the two cases where a percentage would be an invention rather than a reading.

    ``by_day`` is the same pair per ISO date, newest first, because uptake is a question
    about a TREND: "3 of 41, all on the day it shipped" and "3 of 41, spread over a month"
    are the same ratio and opposite findings.
    """
    from aughor.kernel.ledger import Ledger

    # BOTH kinds, and this is not belt-and-braces — it is the defect this meter shipped
    # with for ten minutes. `emit` writes `tool_call` on ENTRY and `tool_call_result` on
    # exit, but the two tools here do not both do both: measured 2026-09-19 on the live
    # log, `ask.converse` appears 41 times as `tool_call` and NEVER as a result, while
    # `present` appears 4 times as `tool_call_result` and NEVER as a call. A meter that
    # picked one kind read **zero uptake on a feature that had been used**, which is
    # precisely the false verdict it exists to prevent.
    # 🔑 A tool's evidence may live under either kind. Never assume one.
    try:
        ledger = Ledger.default()
        rows = list(ledger.session_events(kind="tool_call", org_id=org_id, limit=scan))
        rows += list(ledger.session_events(kind="tool_call_result", org_id=org_id,
                                           limit=scan))
    except Exception as exc:  # noqa: BLE001 — an unreadable log is unknown, not zero
        from aughor.kernel.errors import tolerate
        tolerate(exc, "vocabulary uptake: the session log could not be read",
                 counter="vocabulary_uptake.unreadable")
        return {"turns": 0, "in_parts": 0, "rate": None, "by_day": [], "measured": False}

    # One row per TURN, keyed by trace: a turn that called `present` twice is one turn that
    # answered in parts, not two. Counting calls would flatter a chatty turn into a trend.
    converse: dict[str, str] = {}
    in_parts: set[str] = set()
    day_of: dict[str, str] = {}
    for e in rows:
        trace = str(e.get("trace_id") or "")
        if not trace:
            continue
        name = e.get("name") or ""
        day = str(e.get("at") or "")[:10]
        if name in (CONVERSE_TOOL, PRESENT_TOOL) and day:
            if trace not in day_of or day < day_of[trace]:
                day_of[trace] = day
        if name == CONVERSE_TOOL:
            # The EARLIEST event dates the turn; a long turn must not drift into the next
            # day and read as uptake on a day nobody asked anything.
            if trace not in converse or (day and day < converse[trace]):
                converse[trace] = day
        elif name == PRESENT_TOOL:
            in_parts.add(trace)

    if not converse:
        return {"turns": 0, "in_parts": 0, "rate": None, "by_day": [], "measured": False}

    # A `present` on a trace with no converse marker JOINS the population rather than being
    # discarded: it is proof the tool was offered there. Added to BOTH sides, so the rate
    # stays a rate — the first version added it to neither and lost the turn outright.
    for trace in in_parts - set(converse):
        converse[trace] = day_of.get(trace, "")
    counted = in_parts & set(converse)

    per_day: dict[str, dict] = {}
    for trace, day in converse.items():
        d = per_day.setdefault(day or "(undated)", {"day": day or "(undated)",
                                                    "turns": 0, "in_parts": 0})
        d["turns"] += 1
        if trace in counted:
            d["in_parts"] += 1

    turns = len(converse)
    return {
        "turns": turns,
        "in_parts": len(counted),
        "rate": round(len(counted) / turns, 3),
        "by_day": sorted(per_day.values(), key=lambda d: d["day"], reverse=True),
        "measured": True,
    }
