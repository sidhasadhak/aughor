"""SP-15 (§3.11) — what a held departure MEANS and what to do about it, beside the laws.

The gate (`departure.py`, laws 1–8) says why a message did not leave, in the guard's own
words. A reader who meets that sentence alone hits a wall (the user, 2026-09-25: *"user
needs to know where to troubleshoot such issues.. otherwise its a wall that it hits"*).
This module adds, per guard, what the hold means in the reader's words, what to change,
and which screens hold the fix — and it reads each law's sentence from the gate module's
OWN docstring, so the platform never keeps a second telling of a law.

ONE place for the words. The departures screen renders them (`GET /departures` serves a
`remedy` on every held row), `platform_help` answers "what is re-measure" with them, and
Spotlight's `explain` tool cites them for THIS hold. Until this wave the table lived in
`web/lib/departureRemedies.ts` and nothing server-side could reach it — which is how a
question about a hold ran Spotlight out of steps twice (§3.11 SP-15's baseline).

Nothing here sends: a hold is a verdict, and the next run departs fresh.
"""
from __future__ import annotations

import re

from aughor.govern import departure as _gate
from aughor.govern.departure import ASKED, GUARD_LABELS, GUARDS, HOLDS

#: The sentence every held row leads with — the wall, named.
HOLD_LEAD = ("Nothing on this row sends the message: a hold is a verdict. Fix the cause "
             "below and run the automation again — the next run departs fresh.")

#: The screens a remedy can open, in the order to try them.
DOOR_AUTOMATION = "automation"
DOOR_ANALYSIS = "analysis"
DOOR_SEMANTIC = "semantic"
DOOR_ASK = "ask"

#: Per guard: what the hold MEANS in the reader's words, what to change (and that the next
#: run is the send), and the screens that hold the fix.
REMEDIES: dict[str, dict] = {
    "remeasure": {
        "meaning": ("The message states numbers the analysis never measured. Only measured "
                    "numbers leave the platform, and a figure the writer computed from "
                    "measured ones is not one of them."),
        "action": ("Have the analysis measure what the message should cite — ask for it in "
                   "the automation's question — or have the writer quote only figures from "
                   "the results. Then run the automation again."),
        "doors": [DOOR_AUTOMATION, DOOR_ANALYSIS, DOOR_ASK],
    },
    "definition": {
        "meaning": "A number is stated with no approved metric behind it on this connection.",
        "action": "Approve a metric that defines it in the Semantic Layer; the next run cites it.",
        "doors": [DOOR_SEMANTIC, DOOR_ASK],
    },
    "trust": {
        "meaning": ("The analysis flagged its own headline figure as a computation error. On "
                    "screen that flag is honesty; in a channel it would be a wrong number "
                    "with a disclaimer."),
        "action": ("Open the analysis and read what the check caught; fix the question or the "
                   "data it read, then run again."),
        "doors": [DOOR_ANALYSIS, DOOR_ASK],
    },
    "caveat": {
        "meaning": "The measurement carries a caveat that refutes its own number.",
        "action": ("Read the caveat on the analysis; the figure cannot leave until the "
                   "population behind it is right."),
        "doors": [DOOR_ANALYSIS, DOOR_ASK],
    },
    "tie_out": {
        "meaning": "A governed metric the message asserts failed its own quality tests at the gate.",
        "action": "Open the metric in the Semantic Layer and read which test failed.",
        "doors": [DOOR_SEMANTIC, DOOR_ASK],
    },
    "freshness": {
        "meaning": "The data behind a governed metric is older than the freshness its owner declared.",
        "action": "Refresh the source, or revisit the metric's freshness SLA in the Semantic Layer.",
        "doors": [DOOR_SEMANTIC, DOOR_ASK],
    },
    "claims": {
        "meaning": ("A sentence makes a causal, associational or forecast claim the analysis "
                    "did not license."),
        "action": ("Reword the automation's question or instruction to state the fact; the "
                   "reader draws the conclusion."),
        "doors": [DOOR_AUTOMATION, DOOR_ASK],
    },
    "disagreement": {
        "meaning": "Two readings of a metric disagree, and nobody at departure could choose.",
        "action": "Choose a reading on the departure. The choice is remembered, and the next run binds it.",
        "doors": [DOOR_ASK],
    },
    "repeat": {
        "meaning": ("The same message went to the same place within the last seven days, and "
                    "its numbers barely moved."),
        "action": "Nothing to fix. It sends again when the numbers move or the window passes.",
        "doors": [],
    },
    "probation": {
        "meaning": ("A new automation reaches only the person who declared it until its "
                    "measured precision graduates it."),
        "action": "Mark its departures on the departures screen; it graduates at the measured precision.",
        "doors": [],
    },
}

#: The gate docstring names two guards by a spelling that is not their key.
_DOC_NAMES: dict[str, str] = {"tie-out": "tie_out", "re-measure": "remeasure"}

#: One law bullet in the gate's docstring: ``- **name** (law N) — sentence…`` up to the
#: next bullet or a blank line. The law number is optional (four guards carry none).
_LAW_BULLET = re.compile(
    r"^- \*\*(?P<name>[a-z-]+)\*\*(?: \(law (?P<law>\d+)\))? — (?P<text>.*?)(?=^- \*\*|^\s*$)",
    re.MULTILINE | re.DOTALL)


def laws() -> dict[str, dict]:
    """Every guard's law, read from the gate module's own docstring: ``{guard: {"law":
    "law 1" | "", "sentence": …}}``. Parsed, not copied, so the words the reader gets are
    the words the module keeps; a bullet the parser cannot find is a failing test, not a
    silent gap (`tests/unit/test_departure_remedies.py`)."""
    out: dict[str, dict] = {}
    for m in _LAW_BULLET.finditer(_gate.__doc__ or ""):
        guard = _DOC_NAMES.get(m.group("name"), m.group("name"))
        if guard not in GUARDS:
            continue
        sentence = " ".join(line.strip() for line in m.group("text").splitlines()).strip()
        out[guard] = {"law": f"law {m.group('law')}" if m.group("law") else "",
                      "sentence": sentence}
    return out


def explain_guard(guard: str, *, outcome: str = "", reason: str = "") -> dict | None:
    """One guard, fully told: its label, its law's sentence, what a hold by it means, what
    to change and where. ``None`` for a guard this module does not know — the reader is
    told the gate recorded something, never handed an invented remedy."""
    remedy = REMEDIES.get(guard)
    if remedy is None:
        return None
    law = laws().get(guard) or {"law": "", "sentence": ""}
    return {"guard": guard, "label": GUARD_LABELS.get(guard, guard),
            "outcome": outcome, "reason": reason,
            "law": law["law"], "law_sentence": law["sentence"],
            "meaning": remedy["meaning"], "action": remedy["action"],
            "doors": list(remedy["doors"])}


def remedy_for_row(row: dict) -> dict | None:
    """The remedy a served ledger row carries: the lead sentence and one entry per guard
    that held or asked, in the gate's order. ``None`` when nothing held — a departed row
    has nothing to fix, and an absent key says so rather than an empty list that reads
    as "held by nothing". ``guards`` and ``checks`` may arrive decoded or as JSON text."""
    guards = _decoded(row.get("guards"), dict)
    checks = _decoded(row.get("checks"), dict)
    entries = []
    for guard in GUARDS:
        outcome = str(guards.get(guard) or "")
        if outcome not in (HOLDS, ASKED):
            continue
        told = explain_guard(guard, outcome=outcome, reason=str(checks.get(guard) or ""))
        if told is not None:
            entries.append(told)
    if not entries:
        return None
    return {"lead": HOLD_LEAD, "guards": entries}


def _decoded(raw, empty):
    if isinstance(raw, empty):
        return raw
    if isinstance(raw, str) and raw:
        import json
        try:
            value = json.loads(raw)
        except ValueError:
            return empty()
        return value if isinstance(value, empty) else empty()
    return empty()
