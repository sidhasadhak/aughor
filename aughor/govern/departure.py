"""HB-2 — the departure gate: nothing leaves the screen that the screen would not show,
and less (§3.18).

`govern.outbound` is transport customs — caps, spans, EXTERNAL_CALL — and knows nothing
about the message. This module is CONTENT customs for the unattended paths: the engine's
`slack_post` and `notify` dispatchers ask it before sending, and every decision (departed
or held) lands in the departures ledger with its reasons, so "with the reason recorded"
is structural, not a log line.

First slice, three checks — each deterministic, each named in the record:

- **trust** — a brief whose headline figure a computation-error trust check flagged
  carries the reframe banner in its text (`aughor/agent/investigate.py` composes it from
  ``TRUST_BANNER`` below, one source of truth). On the screen that banner is honesty; in
  a channel it is a wrong number with a disclaimer, so the departure HOLDS. Live receipt:
  2026-09-16, theLook's brief departed to #aughor_canvas flagged "NOT reliable" — the
  incident this gate exists to make impossible.
- **tie-out** — a departing text that asserts a governed metric runs that metric's
  `quality_tests` AT THE GATE (`validate_metric` had exactly one on-demand caller — a
  click; §3.18 measured "a failing tie-out never holds a number out of the Briefing").
  A tie-out that RUNS and FAILS holds the departure; one that cannot run is recorded
  ("unavailable") and does not hold — an infrastructure hiccup is not a failing number.
- **probation** — a NEW automation's departures go only to the person who declared it
  until its measured precision graduates it. A probation departure is not sent to the
  channel at all: it lands in the ledger addressed to the declarer, who marks it
  accept / correct / reject through the feedback plane. With identity off there is no
  declarer to address, so probation is inert exactly as HB-1's enforcement is — built,
  tested, waiting on OIDC.

An accuracy hold outranks probation: a wrong number is held from EVERYONE, declarer
included; probation only decides who a *clean* departure reaches. The gate never raises
into the dispatcher — a gate defect must not take the transport down with it — and the
ledger write is tolerated for the same reason, but a failure to RECORD a hold does not
un-hold it.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

from aughor.kernel.errors import tolerate

logger = logging.getLogger(__name__)

#: The reframe banner's stable prefix — load-bearing text, not a label. The deep run's
#: `_reframe_on_trust_caveat` composes its banner from THIS constant, and the gate
#: detects it in departing text; a reword in either place breaks the pair, which is why
#: `tests/unit/test_departure_gate.py` locks the round trip.
TRUST_BANNER = "A trust check flagged the evidence"

#: Tie-out bounds: at most this many asserted metrics are validated per departure — the
#: gate runs live SQL, and one message must not fan out into a scan.
TIEOUT_MAX_METRICS = 3

#: Graduation: an automation leaves probation when at least MIN_MARKED of its departures
#: are marked and the precision (accept + correct, over all marked) reaches THRESHOLD.
#: `correct` counts toward precision deliberately: a finding worth correcting reached a
#: person worth reaching — the reject is the wasted push.
GRADUATION_MIN_MARKED = 5
GRADUATION_PRECISION = 0.8

#: HB-3's falsifier, structural: a probation push its declarer never acted on within
#: this window counts AGAINST precision (an "unlanded" push in the denominator) — so an
#: automation whose queue nobody reads cannot graduate by silence. A push that earns no
#: landing is not value.
PROBATION_WINDOW_DAYS = 7


@dataclass
class DepartureVerdict:
    """The gate's decision about one outbound message."""
    state: str                      # "departed" | "held" | "held_probation"
    reasons: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)   # check name -> what it found (the receipt)
    record_id: str = ""             # the ledger row, "" when the ledger write failed

    @property
    def held(self) -> bool:
        return self.state != "departed"

    def reason_sentence(self) -> str:
        return " · ".join(self.reasons) if self.reasons else ""


def gate_departure(*, kind: str, org_id: str, conn_id: str, text: str,
                   automation_id: str = "", automation_name: str = "",
                   probation: bool = False, declared_by: str = "",
                   actor: str = "", target: str = "",
                   investigation_id: str = "") -> DepartureVerdict:
    """Judge one outbound message. Returns the verdict; the caller decides how a hold
    reads in its own vocabulary (the engine maps it to a step outcome).

    Deliberately takes plain data, not an Automation — the automations package imports
    this module, never the reverse.
    """
    reasons: list[str] = []
    checks: dict = {}
    state = "departed"

    # trust — the banner travels in the text because confidence does not (measured:
    # the chain binds step1.summary; nothing else of the synthesis crosses).
    if TRUST_BANNER in (text or ""):
        caveat = _banner_caveat(text)
        checks["trust"] = caveat
        reasons.append(
            "a computation-error trust check flagged a headlined figure — "
            "the screen shows the flagged report; a channel gets nothing until it is recomputed"
            + (f" ({caveat})" if caveat else ""))
        state = "held"
    else:
        checks["trust"] = "clean"

    # tie-out — validate_metric at the gate, for governed metrics the text asserts.
    tie = _tie_out(text, conn_id)
    checks["tie_out"] = tie["summary"]
    if tie["failed"]:
        reasons.append("a failing tie-out holds the number at departure: " + tie["summary"])
        state = "held"

    # probation — decides addressing, never accuracy; an accuracy hold above outranks it.
    if state == "departed" and probation and declared_by:
        checks["probation"] = f"on probation — addressed to {declared_by}"
        reasons.append(
            f"on probation: this departure goes to {declared_by}'s review queue, not the "
            f"channel — it graduates at measured precision "
            f"(≥{GRADUATION_PRECISION:.0%} over ≥{GRADUATION_MIN_MARKED} marked)")
        state = "held_probation"
    elif probation and declared_by:
        checks["probation"] = f"on probation (accuracy hold already applies) — {declared_by}"
    else:
        checks["probation"] = "not on probation" if not probation else "no declarer — inert"

    record_id = _record(kind=kind, org_id=org_id, conn_id=conn_id, state=state,
                        automation_id=automation_id, automation_name=automation_name,
                        actor=actor, target=target, addressed_to=declared_by if state == "held_probation" else "",
                        reasons=reasons, checks=checks, text=text,
                        investigation_id=investigation_id)
    return DepartureVerdict(state=state, reasons=reasons, checks=checks, record_id=record_id)


def _banner_caveat(text: str) -> str:
    """The caveat sentence the banner carries, for the record — the text between the
    banner's colon and the reframe's own 'Do not read' sentence."""
    try:
        after = text.split(TRUST_BANNER, 1)[1]
        caveat = after.split(":", 1)[1] if ":" in after[:80] else after
        caveat = caveat.split("Do not read", 1)[0]
        return caveat.strip().rstrip(".")[:300]
    except Exception:
        return ""


def _tie_out(text: str, conn_id: str) -> dict:
    """Run the quality_tests of governed metrics the text asserts. Returns
    {"failed": bool, "summary": str}. Never raises; a tie-out that cannot run is
    recorded and does not hold (an infrastructure error is not a failing number)."""
    if not text or not conn_id:
        return {"failed": False, "summary": "no text or connection — not applicable"}
    try:
        from aughor.explorer.metric_coherence import asserted_governed_metrics
        asserted = [m for m in asserted_governed_metrics(text, conn_id)
                    if getattr(m, "quality_tests", None)]
    except Exception as exc:
        tolerate(exc, "departure gate: metric assertion scan failed",
                 counter="departures.tieout_scan_failed")
        return {"failed": False, "summary": "assertion scan unavailable"}
    if not asserted:
        return {"failed": False, "summary": "no governed metric with quality tests asserted"}

    parts: list[str] = []
    failed = False
    db = None
    try:
        from aughor.db.connection import open_connection_for
        db = open_connection_for(conn_id)
    except Exception as exc:
        tolerate(exc, "departure gate: tie-out connection unavailable",
                 counter="departures.tieout_conn_failed")
        return {"failed": False,
                "summary": "tie-out unavailable (connection could not be opened) for " +
                           ", ".join(getattr(m, "name", "?") for m in asserted[:TIEOUT_MAX_METRICS])}
    try:
        from aughor.semantic.metrics import validate_metric
        for m in asserted[:TIEOUT_MAX_METRICS]:
            try:
                v = validate_metric(m, db)
                if v.passed:
                    parts.append(f"{m.name}: passed")
                else:
                    failed = True
                    parts.append(f"{m.name}: FAILED — {v.message}")
            except Exception as exc:
                tolerate(exc, "departure gate: tie-out errored",
                         counter="departures.tieout_errored")
                parts.append(f"{m.name}: unavailable ({type(exc).__name__})")
    finally:
        try:
            db.close()
        except Exception as exc:
            tolerate(exc, "departure gate: tie-out connection close failed",
                     counter="departures.tieout_close_failed")
    return {"failed": failed, "summary": "; ".join(parts)}


def _record(**kw) -> str:
    """One ledger row per gate decision. Tolerated — the ledger must not block a send —
    but a failure to record a hold never un-holds it (the verdict is already made)."""
    try:
        from aughor.govern.departure_store import record_departure
        return record_departure(
            id=uuid.uuid4().hex[:12], kind=kw["kind"], org_id=kw["org_id"],
            conn_id=kw["conn_id"], state=kw["state"], automation_id=kw["automation_id"],
            automation_name=kw["automation_name"], actor=kw["actor"], target=kw["target"],
            addressed_to=kw["addressed_to"], reasons=json.dumps(kw["reasons"]),
            checks=json.dumps(kw["checks"]), text_preview=(kw["text"] or "")[:500],
            investigation_id=kw["investigation_id"])
    except Exception as exc:
        tolerate(exc, "departure gate: ledger write failed — the verdict stands unrecorded",
                 counter="departures.record_failed")
        return ""
