"""HB-2 — the departure gate: nothing leaves the screen that the screen would not show,
and less (§3.18).

`govern.outbound` is transport customs — caps, spans, EXTERNAL_CALL — and knows nothing
about the message. This module is CONTENT customs: every path that sends information out
of the platform asks it first, and every decision (departed or held) lands in the
departures ledger with its reasons, so "with the reason recorded" is structural, not a log
line. "Every path" is held literally by `tests/unit/test_departure_every_exit_gated.py`: a
call to a transport that neither asks this gate in the same function nor is listed in
``UNGATED_BY_DESIGN`` with its reason fails the suite.

The laws, in the order they run — each deterministic, each named in the record and on the
receipt the message carries:

- **trust** — a brief whose headline figure a computation-error trust check flagged carries
  the reframe banner (`aughor/agent/investigate.py` composes it from ``TRUST_BANNER``, one
  source of truth). On the screen that banner is honesty; in a channel it is a wrong number
  with a disclaimer, so the departure HOLDS. Live receipt: 2026-09-16, theLook's brief
  departed to #aughor_canvas flagged "NOT reliable" — the incident this gate exists to make
  impossible.
- **caveat** — a measurement that REFUTES its own number does not leave. A promise's flags
  mostly qualify a figure and ride the receipt, but one class says the figure is
  arithmetically wrong: objects whose lag is impossible, counted as kept, so the rate is
  lower than the truth. Live anchor: 2026-09-20, LuxExperience's refund promise measured
  23.27% breached over a population including 4,199 Returns refunded BEFORE they arrived —
  25.41% without them. Which caveats block is `departure_basis._blocking`'s call, not this
  module's.
- **tie-out** — a governed metric the text asserts runs its `quality_tests` AT THE GATE. A
  tie-out that runs and fails holds; one that cannot run is recorded and does not hold — an
  infrastructure hiccup is not a failing number.
- **definition** (law 2) — a number leaves only citing an approved governed metric, a
  declared promise or rule that has been measured, or the declaration that measured it (a
  monitor, an alert rule) — never an inferred definition. A well-known KPI stated beside a
  number with no approved metric behind it holds; so does an asserted metric whose
  definition is still a draft.
- **re-measure** (law 1) — every magnitude the text states must be in the measurement it
  departs on, and that measurement must be one taken AT departure: older than
  ``REMEASURE_WITHIN_SECONDS`` it is re-executed first. A magnitude with no measurement
  behind it holds — what leaves is information the platform measured. Live anchor:
  2026-09-16, the dispatch-promise watch departed "10,423 of 99,441 order lines"; the
  promise it was about counted 111,456 lines — 99,441 is the ORDER count, and no
  measurement of that promise ever said it.
- **freshness** (law 4) — a governed metric whose data breaches its declared SLA holds, and
  every departure states the data's as-of wherever one is known.
- **claims** (law 5) — a descriptive fact departs; an associational or causal sentence only
  on the licence its analysis recorded (`agent/claim_type.py`: causal needs an intervention
  in the data or a human-owned assumption, and a recorded refutation withdraws it); a
  forecast never — the platform has no forecaster.
- **disagreement** (law 6) — divergent readings the source analysis paused on have no asker
  at departure, so the OWNER is asked (``held_owner``) and nothing is sent until answered.
  The answer lands in the ambiguity ledger, so the next run binds it: asked once.
- **repeat** (law 7) — an unattended automation never sends the same message to the same
  place twice within ``REPEAT_WINDOW_HOURS``, and a repeat whose every number moved less
  than ``NOISE_REL`` is noise, not news. Alerts keep their own anti-flap policy (a grace
  window, a debounce); a scheduled briefing speaks by its schedule; a person chose.
- **probation** — a NEW automation's departures go only to the person who declared it until
  its measured precision graduates it. With identity off there is no declarer to address,
  so probation is inert exactly as HB-1's enforcement is.

**The receipt travels** (law 8): every verdict carries ``receipt`` — the source, the
definition, the as-of, each guard's outcome and the ledger row — and each transport attaches
``receipt_line()`` to the message itself.

An accuracy hold outranks everything after it: a wrong number is held from EVERYONE,
declarer and owner included; the owner question and probation only decide who a *clean*
departure reaches. The gate never raises into a transport — a gate defect must not take the
transport down with it — and the ledger write is tolerated for the same reason, but a
failure to RECORD a hold never un-holds it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from aughor.kernel.errors import tolerate

logger = logging.getLogger(__name__)

#: The reframe banner's stable prefix — load-bearing text, not a label. The deep run's
#: `_reframe_on_trust_caveat` composes its banner from THIS constant, and the gate
#: detects it in departing text; a reword in either place breaks the pair, which is why
#: `tests/unit/test_departure_gate.py` locks the round trip.
TRUST_BANNER = "A trust check flagged the evidence"

#: Tie-out and freshness bounds: at most this many asserted metrics are checked per
#: departure — the gate runs live SQL, and one message must not fan out into a scan.
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

#: Law 1 — how old a measurement may be and still count as taken AT departure. A chain's
#: analysis finishes seconds before its send and a monitor alert is dispatched in the tick
#: that measured it; anything older is re-executed before its numbers may leave.
REMEASURE_WITHIN_SECONDS = 1800

#: Law 7 — how far back "never the same message twice" looks, and the noise band: a repeat
#: whose every number moved less than this — relative, the triage's change term
#: |a − b| / max(|a|, |b|) — is noise. 5% is the platform's own bar for two readings of one
#: number disagreeing materially (`agent/investigate.py`'s `_METRIC_DIVERGENCE_REL`).
REPEAT_WINDOW_HOURS = 168
NOISE_REL = 0.05

#: Verdict states.
DEPARTED = "departed"
HELD = "held"
HELD_PROBATION = "held_probation"
HELD_OWNER = "held_owner"

#: Who started the send. A person pressing Share chose the moment and the words, so
#: probation and the repeat law do not apply to them; the accuracy laws do, because a
#: person cannot see a failing tie-out or a stale number from the screen.
UNATTENDED = "unattended"
PERSON = "person"

#: Every guard, in the order it runs; a receipt lists outcomes in this order.
GUARDS: tuple[str, ...] = ("trust", "caveat", "tie_out", "definition", "remeasure", "freshness",
                           "claims", "disagreement", "repeat", "probation")

#: What a guard concluded.
PASSED = "passed"
HOLDS = "held"
ASKED = "asked"
NOT_APPLICABLE = "not_applicable"
UNAVAILABLE = "unavailable"
EXEMPT = "exempt"

GUARD_LABELS: dict[str, str] = {
    "trust": "trust", "caveat": "caveat", "tie_out": "tie-out", "definition": "definition",
    "remeasure": "re-measure", "freshness": "freshness", "claims": "claim type",
    "disagreement": "disagreement", "repeat": "repeat", "probation": "probation",
}

#: Departure kinds that carry their own re-notification policy. Law 7 records the
#: exemption with this reason instead of second-guessing a debounce a person configured —
#: a sustained breach re-alerting once per grace window is the design, not noise.
REPEAT_POLICY: dict[str, str] = {
    "monitor_alert": "re-notification is the monitor's own anti-flap policy (its grace window)",
    "agent_alert": "re-notification is the alert rule's own policy (its debounce)",
    "briefing": "a scheduled briefing speaks by its schedule",
}

#: Transport call sites that deliberately do NOT ask this gate, each with its reason. The
#: exit ratchet reads this map both ways: every call site listed must still exist, and a
#: call site not listed must ask the gate in the same function.
UNGATED_BY_DESIGN: dict[str, str] = {
    "aughor/actions/inbox.py::_accept_outbound_send":
        "a person reviewed this exact post in the inbox and pressed send — the person is the gate",
    "aughor/actions/inbox.py::_accept_notify_send":
        "a person reviewed this exact send in the inbox and pressed accept — the person is the gate",
    "aughor/routers/actions.py::test_action_trigger":
        "a fixed '[TEST]' payload that carries no measured information",
}


@dataclass
class Measurement:
    """What a departure's numbers were measured from — the basis law 1 grounds them in.

    ``values`` are measured magnitudes (result cells, stamped counts); ``rates`` are measured
    fractions a message may state as percentages (a promise's breach rate). A percentage is
    checked only against a measurement that HAS rates: every other percentage is a derived
    quantity, which the finding guard never enforced either. ``remeasure`` re-executes the
    measurement for the claims about to leave and returns fresh ``(values, rates)``, or None
    when it cannot run. ``stale_note`` says why a stale measurement cannot be re-executed at
    a send (a promise is re-measured by the ontology's measure pass). ``rendered`` marks a
    message whose numbers code printed from exactly these values in the same tick (an alert's
    template) — grounded by construction, and matching its tokens would only misread a
    "1440m" window as 1.44 billion."""
    source: str
    values: list = field(default_factory=list)
    rates: list = field(default_factory=list)
    measured_at: str = ""
    as_of: str = ""
    definition: str = ""
    remeasure: Optional[Callable[[list], Optional[tuple]]] = None
    stale_note: str = ""
    rendered: bool = False
    #: What the measurement itself found worth a reader's eye — a promise's `flags`. These do
    #: NOT hold a departure: they qualify a number rather than refute it, and a gate that
    #: blocked on every caveat would teach senders to stop writing them. They ride the receipt
    #: instead, because the alternative is what shipped on LuxExperience: a refund promise
    #: departing as "23.27% breached" when 4,199 of the 50,048 objects were refunded BEFORE
    #: they arrived and were counted as kept — 25.41% without them, with nothing on the
    #: message to say so.
    caveats: list = field(default_factory=list)
    #: The subset of ``caveats`` that REFUTE the number rather than qualify it — classified by
    #: the builder that knows the vocabulary (`departure_basis._blocking`), never by the gate.
    #: These HOLD. Today it is one case: a promise whose population contains objects with an
    #: impossible lag, counted as kept, so the departing rate is arithmetically lower than the
    #: truth. Keeping the two lists apart is what stops "a caveat holds" from becoming "every
    #: caveat holds", which would teach senders to stop writing them.
    blocking_caveats: list = field(default_factory=list)


@dataclass
class _Check:
    outcome: str                    # PASSED | HOLDS | ASKED | NOT_APPLICABLE | UNAVAILABLE | EXEMPT
    summary: str                    # what the guard found — recorded verbatim
    reason: str = ""                # the sentence a hold or a question carries
    detail: dict = field(default_factory=dict)


@dataclass
class DepartureVerdict:
    """The gate's decision about one outbound message."""
    state: str                      # departed | held | held_probation | held_owner
    reasons: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)   # guard -> what it found (verbatim)
    record_id: str = ""             # the ledger row, "" when the ledger write failed
    guards: dict = field(default_factory=dict)   # guard -> outcome word
    receipt: dict = field(default_factory=dict)  # law 8 — what travels with the message
    addressed_to: str = ""          # the declarer (probation) or the owner (a question)

    @property
    def held(self) -> bool:
        return self.state != DEPARTED

    def reason_sentence(self) -> str:
        return " · ".join(self.reasons) if self.reasons else ""

    def receipt_line(self) -> str:
        return receipt_line(self.receipt)


def gate_departure(*, kind: str, org_id: str, conn_id: str, text: str,
                   automation_id: str = "", automation_name: str = "",
                   probation: bool = False, declared_by: str = "",
                   actor: str = "", target: str = "",
                   investigation_id: str = "",
                   origin: str = UNATTENDED, source_kind: str = "", source_id: str = "",
                   source_name: str = "", about: str = "",
                   measurement: Optional[Measurement] = None,
                   declared_definition: str = "",
                   disagreement: Optional[dict] = None,
                   dated_records: bool = False,
                   held_lines: Optional[list[str]] = None) -> DepartureVerdict:
    """Judge one outbound message. Returns the verdict; the caller decides how a hold reads
    in its own vocabulary (the engine maps it to a step outcome, a door to a response).

    Deliberately takes plain data, not an Automation or a Monitor — the packages that send
    import this module, never the reverse. Everything after ``investigation_id`` is context
    a caller supplies when it has it; a guard with nothing to judge records
    ``not_applicable``, never a silent pass. ``dated_records`` marks a message whose numbers
    are records each stated with the moment it happened (a briefing's alert list) — there is
    nothing to re-measure in "fired at 08:00 with 12.4". ``held_lines`` are the reasons lines
    of an assembled message (a briefing) were held by `line_holds` before this call — the
    message departs without them, and its record says what was cut and why."""
    text = text or ""
    found: dict[str, _Check] = {}
    conn = _LazyConnection(conn_id)
    try:
        found["trust"] = _guarded("trust", lambda: _trust(text))
        found["caveat"] = _guarded("caveat", lambda: _caveat(measurement))
        found["tie_out"] = _guarded("tie_out", lambda: _tie_out(text, conn_id, conn))
        found["definition"] = _guarded(
            "definition", lambda: _definition(text, conn_id, about, declared_definition))
        found["remeasure"] = _guarded(
            "remeasure", lambda: _remeasure(text, measurement, dated_records))
        found["freshness"] = _guarded(
            "freshness", lambda: _freshness(text, conn_id, conn, measurement))
        found["claims"] = _guarded("claims", lambda: _claims(text, investigation_id))
    finally:
        conn.close()

    state = HELD if any(c.outcome == HOLDS for c in found.values()) else DEPARTED
    addressed_to = ""

    found["disagreement"] = _guarded(
        "disagreement", lambda: _disagreement(disagreement, conn_id, declared_by))
    if found["disagreement"].outcome == ASKED:
        addressed_to = str(found["disagreement"].detail.get("owner") or "")
        if state == DEPARTED:
            state = HELD_OWNER

    if state == DEPARTED:
        found["repeat"] = _guarded(
            "repeat", lambda: _repeat(kind, origin, text, target, automation_id or source_id))
        if found["repeat"].outcome == HOLDS:
            state = HELD
    else:
        found["repeat"] = _Check(NOT_APPLICABLE, "not judged — the departure is already held")

    found["probation"] = _probation(state, probation, declared_by)
    if found["probation"].outcome == HOLDS:
        state = HELD_PROBATION
        addressed_to = declared_by

    reasons = [found[g].reason for g in GUARDS
               if g in found and found[g].outcome in (HOLDS, ASKED) and found[g].reason]
    checks = {g: found[g].summary for g in GUARDS}
    if held_lines:
        checks["held_lines"] = " · ".join(held_lines)
    missing = list(found["definition"].detail.get("missing") or [])
    if missing:
        checks["definition_missing"] = " · ".join(missing)     # CB-5: what would clear the hold
    guards = {g: found[g].outcome for g in GUARDS}
    as_of = str(found["freshness"].detail.get("as_of") or "")
    cited = list(found["definition"].detail.get("cited") or [])

    record_id = uuid.uuid4().hex[:12]
    receipt = {
        "departure_id": record_id,
        "source": ((measurement.source if measurement else "") or source_name
                   or automation_name or kind),
        "definition": ", ".join(cited),
        "as_of": as_of,
        "guards": guards,
        "held_lines": len(held_lines or []),
        "caveats": list(measurement.caveats) if measurement else [],
        "link": departure_link(record_id),
    }
    # The exact sentence that travels, stored with the row — readable where it was recorded.
    receipt["line"] = receipt_line(receipt)
    written = _record(
        id=record_id, kind=kind, org_id=org_id, conn_id=conn_id, state=state,
        automation_id=automation_id, automation_name=automation_name or source_name,
        actor=actor, target=target, addressed_to=addressed_to,
        reasons=json.dumps(reasons), checks=json.dumps(checks),
        text_preview=text[:500], investigation_id=investigation_id,
        source_kind=source_kind, source_id=source_id, origin=origin, about=about,
        guards=json.dumps(guards), receipt=json.dumps(receipt),
        fingerprint=message_shape_key(text), numerals=json.dumps(significant_values(text)),
        as_of=as_of, question=json.dumps(_question_record(disagreement)))
    if not written:
        receipt = {**receipt, "departure_id": "", "link": ""}
        receipt["line"] = receipt_line(receipt)
    return DepartureVerdict(state=state, reasons=reasons, checks=checks, record_id=written,
                            guards=guards, receipt=receipt, addressed_to=addressed_to)


# ── law 8 — the receipt that travels ──────────────────────────────────────────────

def receipt_line(receipt: dict) -> str:
    """The sentence a transport attaches to the message: what measured it, what defines it,
    as of when, which guards ran, and where the full record lives."""
    if not receipt:
        return ""
    guards = receipt.get("guards") or {}
    ran = [GUARD_LABELS[g] for g in GUARDS if guards.get(g) == PASSED]
    could_not = [GUARD_LABELS[g] for g in GUARDS if guards.get(g) == UNAVAILABLE]
    parts = [f"Receipt: {receipt.get('source') or 'unnamed source'}",
             f"defined by {receipt['definition']}" if receipt.get("definition")
             else "definition: none named",
             f"as of {str(receipt['as_of'])[:10]}" if receipt.get("as_of")
             else "as of: not stated by the source"]
    # Before the guard list, not after: a caveat qualifies the number a reader just read, and
    # a sentence that ends in a list of green ticks reads as reassurance whatever follows it.
    for caveat in (receipt.get("caveats") or []):
        parts.append(f"caveat: {caveat}")
    if ran:
        parts.append("checked: " + ", ".join(ran))
    if could_not:
        parts.append("could not check: " + ", ".join(could_not))
    if receipt.get("held_lines"):
        n = int(receipt["held_lines"])
        parts.append(f"{n} line{'s' if n != 1 else ''} held at departure")
    ref = receipt.get("link") or (f"departure {receipt['departure_id']}"
                                  if receipt.get("departure_id") else "")
    if ref:
        parts.append(ref)
    return " · ".join(parts)


def departure_link(departure_id: str) -> str:
    """A link to the departure's row on the departures screen, or "" when the API does
    not know its public web origin. Opt-in via ``AUGHOR_WEB_URL``, the monitors' rule:
    empty beats guessed — a message linking to ``localhost`` is worse than no link."""
    base = os.environ.get("AUGHOR_WEB_URL", "").strip().rstrip("/")
    if not (base and departure_id):
        return ""
    from urllib.parse import urlencode
    return f"{base}/?{urlencode({'tab': 'agentic-ops', 'layer': 'departures', 'departure': departure_id})}"


def line_holds(text: str, *, conn_id: str, declared: bool = False,
               measurement: Optional[Measurement] = None) -> list[str]:
    """The laws that judge ONE line of an assembled message on its own — trust, definition,
    claim type — so a briefing sends its sound lines instead of holding everything for one
    bad one. No ledger row per line: the message's own departure records what was cut
    (``held_lines``). ``declared`` marks a line whose numbers a person's declaration defines
    (a monitor alert), which law 2 then reads as cited. ``measurement`` adds law 1 for the
    line: every magnitude it states must be in that measurement (a period briefing's headline
    metrics, re-run at the send) — omitted, the line is judged exactly as before."""
    checks = (
        ("trust", lambda: _trust(text)),
        ("definition", lambda: _definition(text, conn_id, "",
                                           "a declared monitor" if declared else "")),
        ("claims", lambda: _claims(text, "")),
    )
    if measurement is not None:
        checks += (("remeasure", lambda: _remeasure(text, measurement, False)),)
    return [c.reason for c in (_guarded(name, run) for name, run in checks)
            if c.outcome == HOLDS and c.reason]


# ── law 6's answer ─────────────────────────────────────────────────────────────────

def answer_owner_question(departure_id: str, reading: str, *, answered_by: str = "") -> dict:
    """The owner picks one of the readings a held departure asked about. The choice is
    crystallized in the ambiguity ledger at USER authority, so the next analysis of that
    metric binds it and never pauses on it again — asked once, remembered. The held message
    itself is not re-sent: a hold is a verdict, and the next run departs on the answer.

    Returns ``{"departure": row, "resolution_id": str}``. Raises ``LookupError`` for an
    unknown departure and ``ValueError`` when there is no question or the reading is not
    one of its options."""
    from aughor.govern.departure_store import get_departure, record_answer
    row = get_departure(departure_id)
    if row is None:
        raise LookupError("departure not found")
    try:
        question = json.loads(row.get("question") or "{}") or {}
    except ValueError:
        question = {}
    readings = [r for r in (question.get("readings") or []) if isinstance(r, dict)]
    if not readings:
        raise ValueError("this departure asked no question")
    chosen = next((r for r in readings if r.get("label") == reading), None)
    if chosen is None:
        labels = ", ".join(repr(r.get("label", "")) for r in readings)
        raise ValueError(f"{reading!r} is not one of the readings: {labels}")
    from aughor.semantic.ambiguity_ledger import Reading, crystallize_user_choice
    res = crystallize_user_choice(
        row.get("conn_id") or "", question.get("subject") or "", chosen.get("label") or "",
        org_id=row.get("org_id") or "", resolved_sql=chosen.get("sql") or "",
        readings=[Reading(label=r.get("label", ""), sql_evidence=r.get("sql", ""))
                  for r in readings])
    updated = record_answer(departure_id, reading, answered_by)
    return {"departure": updated, "resolution_id": str(getattr(res, "id", "") or "")}


# ── the guards ────────────────────────────────────────────────────────────────────

def _guarded(name: str, run: Callable[[], _Check]) -> _Check:
    """One guard's defect is that guard's outcome, never the transport's failure."""
    try:
        return run()
    except Exception as exc:
        tolerate(exc, f"departure gate: the {name} guard failed and is recorded unavailable",
                 counter="departures.guard_failed")
        return _Check(UNAVAILABLE, f"{GUARD_LABELS.get(name, name)} unavailable "
                                   f"({type(exc).__name__})")


def _trust(text: str) -> _Check:
    # The banner travels in the text because confidence does not (measured: the chain
    # bound step1.summary and nothing else of the synthesis crossed).
    if TRUST_BANNER not in text:
        return _Check(PASSED, "clean")
    caveat = _banner_caveat(text)
    return _Check(HOLDS, caveat,
                  "a computation-error trust check flagged a headlined figure — the screen "
                  "shows the flagged report; a channel gets nothing until it is recomputed"
                  + (f" ({caveat})" if caveat else ""))


def _caveat(measurement: Optional[Measurement]) -> _Check:
    """A measurement that refutes its own number does not leave.

    The flags a measurement carries mostly QUALIFY it — "never broken" is a surprising shape,
    not a wrong figure — and those ride the receipt. A blocking caveat is different in kind:
    the number is arithmetically wrong, and the measurement itself says so. Live anchor,
    2026-09-20: LuxExperience's refund promise measured 23.27% breached over a population
    that included 4,199 Returns refunded BEFORE they were received, every one counted as
    kept; the true rate is 25.41%. On the screen the flag is shown beside the number, which
    is honesty. In a channel it would be a wrong number with a footnote, so it holds — the
    same reasoning as the trust banner above, reached from the measurement instead of the
    text. Which caveats block is decided by `departure_basis._blocking`, not here.
    """
    if measurement is None:
        return _Check(NOT_APPLICABLE, "no measurement to judge")
    blocking = [str(c) for c in (measurement.blocking_caveats or [])]
    if not blocking:
        return _Check(PASSED, "clean")
    return _Check(HOLDS, " · ".join(blocking),
                  "the measurement refutes its own number: " + " · ".join(blocking))


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


def _tie_out(text: str, conn_id: str, conn: "_LazyConnection") -> _Check:
    """Run the quality_tests of governed metrics the text asserts. A tie-out that cannot
    run is recorded and does not hold (an infrastructure error is not a failing number)."""
    if not text or not conn_id:
        return _Check(NOT_APPLICABLE, "no text or no connection to check")
    try:
        from aughor.explorer.metric_coherence import asserted_governed_metrics
        asserted = _unique_by_name(m for m in asserted_governed_metrics(text, conn_id)
                                   if getattr(m, "quality_tests", None))
    except Exception as exc:
        tolerate(exc, "departure gate: metric assertion scan failed",
                 counter="departures.tieout_scan_failed")
        return _Check(UNAVAILABLE, "assertion scan unavailable")
    if not asserted:
        return _Check(NOT_APPLICABLE, "no governed metric with quality tests asserted")
    checked = asserted[:TIEOUT_MAX_METRICS]
    try:
        db = conn.get()
    except Exception as exc:
        tolerate(exc, "departure gate: tie-out connection unavailable",
                 counter="departures.tieout_conn_failed")
        return _Check(UNAVAILABLE, "tie-out unavailable (connection could not be opened) for "
                                   + ", ".join(getattr(m, "name", "?") for m in checked))
    from aughor.semantic.metrics import validate_metric
    parts: list[str] = []
    failed = False
    ran = 0
    for m in checked:
        try:
            v = validate_metric(m, db)
            ran += 1
            if v.passed:
                parts.append(f"{m.name}: passed")
            else:
                failed = True
                parts.append(f"{m.name}: FAILED — {v.message}")
        except Exception as exc:
            tolerate(exc, "departure gate: tie-out errored", counter="departures.tieout_errored")
            parts.append(f"{m.name}: unavailable ({type(exc).__name__})")
    summary = "; ".join(parts)
    if failed:
        return _Check(HOLDS, summary, "a failing tie-out holds the number at departure: " + summary)
    return _Check(PASSED if ran else UNAVAILABLE, summary)


def metric_is_approved(metric) -> bool:
    """The catalog's lifecycle, read the way `MetricDefinition` writes it: `status`, or —
    for a record that predates the lifecycle — an `approved_by`."""
    status = str(getattr(metric, "status", "") or "")
    if status:
        return status == "approved"
    return bool(getattr(metric, "approved_by", None))


def _definition(text: str, conn_id: str, about: str, declared: str) -> _Check:
    """Law 2. Holds a number that cites a draft metric, a well-known KPI with no approved
    metric behind it, or an object that is not declared and measured on this connection."""
    cited: list[str] = [declared] if declared else []
    clauses = numeric_clauses(text)
    if not clauses:
        return _Check(NOT_APPLICABLE, "no number is stated", detail={"cited": cited})
    problems: list[str] = []
    if about.startswith(("promise:", "process:", "rule:")):
        from aughor.govern.departure_basis import declared_thing
        thing = declared_thing(about, conn_id)
        if thing is None:
            problems.append(f"it is about {about}, which is not declared on this connection")
        elif not thing.get("measured"):
            problems.append(f"it is about {thing['label']}, which is declared but has never "
                            f"been measured")
        else:
            cited.append(f"{thing['label']} (declared, measured)")
    unapproved: set[str] = set()
    inferred: list[str] = []
    if conn_id:
        from aughor.explorer.metric_coherence import asserted_governed_metrics
        from aughor.semantic.enforcement import propose_undefined_metrics
        from aughor.semantic.metrics import list_metrics
        catalog = list_metrics(connection_id=conn_id)
        approved = [m for m in catalog if metric_is_approved(m)]
        named = []
        if about.startswith("metric:"):
            # The metric the sender DECLARES it measured (a monitor's metric), judged from
            # the catalog directly — its name need not appear beside a number in the text.
            name = about.split(":", 1)[1]
            scoped = sorted((m for m in catalog if str(getattr(m, "name", "")) == name),
                            key=lambda m: getattr(m, "connection", "") != conn_id)
            named = scoped[:1]
        for m in _unique_by_name([*named, *asserted_governed_metrics(text, conn_id)]):
            name = str(getattr(m, "name", "") or "")
            if metric_is_approved(m):
                cited.append(f"metric {name} v{int(getattr(m, 'version', 0) or 1)}")
            else:
                unapproved.add(name.lower())
                status = str(getattr(m, "status", "") or "") or "unapproved"
                problems.append(f"{name} is stated with a number and its definition is "
                                f"{status}, not approved")
        for clause in clauses:
            for undefined in propose_undefined_metrics(clause, approved):
                phrase, slug = undefined["phrase"], undefined["slug"]
                if phrase in inferred or slug in unapproved or phrase in unapproved:
                    continue
                inferred.append(phrase)
        if inferred and not declared:
            problems.extend(f"'{p}' is stated with a number and no approved metric defines it "
                            f"on this connection" for p in inferred)
    if problems:
        # CB-5: the definitions that would clear this hold, structurally — so "approve `revenue` and
        # N sends unblock" is counted from the record, never parsed out of the sentence.
        missing = sorted(unapproved) + [p for p in inferred if p not in unapproved]
        return _Check(HOLDS, "; ".join(problems),
                      "a number leaves only citing an approved definition, never an inferred "
                      "one: " + "; ".join(problems), detail={"cited": cited, "missing": missing})
    if cited:
        return _Check(PASSED, "cites " + ", ".join(cited), detail={"cited": cited})
    return _Check(NOT_APPLICABLE, "no defined measure is named beside a number",
                  detail={"cited": cited})


def _remeasure(text: str, measurement: Optional[Measurement], dated_records: bool) -> _Check:
    """Law 1. Every stated magnitude must be in the measurement the message departs on,
    taken at departure — re-executed first when it is older than the window."""
    if dated_records:
        return _Check(NOT_APPLICABLE, "dated records — each number is stated with the moment "
                                      "it was recorded")
    from aughor.explorer.grounding import extract_numerals, numeral_matches_measure
    numerals = extract_numerals(_strip_dates(text))
    magnitudes = [n for n in numerals if n.enforce]
    percents = [n for n in numerals if n.suffix == "%"]
    if measurement is None:
        if not magnitudes:
            return _Check(NOT_APPLICABLE, "no magnitude is stated")
        toks = _tokens(magnitudes)
        return _Check(HOLDS, f"no measurement behind {toks}",
                      f"{toks} {_is_are(magnitudes)} stated with no measurement behind "
                      f"{'it' if len(magnitudes) == 1 else 'them'} — what leaves is information "
                      f"the platform measured")
    if measurement.rendered:
        return _Check(PASSED, f"rendered by code from {measurement.source}'s own reading, "
                              f"{describe_age(age_seconds(measurement.measured_at))} — grounded "
                              f"by construction")
    checked = magnitudes + (percents if measurement.rates else [])
    if not checked:
        return _Check(NOT_APPLICABLE, f"no magnitude is stated (measured by {measurement.source})")

    values, rates = list(measurement.values), list(measurement.rates)
    age = age_seconds(measurement.measured_at)
    stale = age is None or age > REMEASURE_WITHIN_SECONDS
    note, unavailable, remeasured = "", False, False
    if (stale or not (values or rates)) and measurement.remeasure is not None:
        fresh = None
        try:
            fresh = measurement.remeasure(checked)
        except Exception as exc:
            tolerate(exc, "departure gate: re-execution failed",
                     counter="departures.remeasure_failed")
        if fresh is None:
            unavailable = True
            note = "re-execution at departure could not run"
        else:
            values, rates = list(fresh[0] or []), list(fresh[1] or [])
            remeasured = True
    elif stale:
        unavailable = True
        note = measurement.stale_note or "it cannot be re-executed at departure"

    percent_cells = values + [r * 100.0 for r in rates]
    ungrounded = [n for n in magnitudes if not any(numeral_matches_measure(n, c) for c in values)]
    if rates:
        ungrounded += [n for n in percents if not any(numeral_matches_measure(n, c) for c in percent_cells)]
    when = ("re-executed at departure" if remeasured
            else f"measured {describe_age(age)}" if age is not None
            else "measured at an unrecorded time")
    if ungrounded:
        toks = _tokens(ungrounded)
        measured = _measured_phrase(values, rates)
        return _Check(HOLDS, f"{toks} not in {measurement.source} ({when})",
                      f"re-measured at departure: {toks} {_is_are(ungrounded)} not in "
                      f"{measurement.source}" + (f" ({measured})" if measured else ""))
    summary = (f"{len(checked)} number{'s' if len(checked) != 1 else ''} grounded in "
               f"{measurement.source}, {when}" + (f" — {note}" if note else ""))
    return _Check(UNAVAILABLE if unavailable else PASSED, summary)


def _freshness(text: str, conn_id: str, conn: "_LazyConnection",
               measurement: Optional[Measurement]) -> _Check:
    """Law 4. The as-of every departure states, and a hold where a governed metric's data
    breaches the SLA its owner declared. No SLA declared means nothing to judge — the
    platform does not invent a staleness bar for data nobody gave one."""
    as_ofs: list[str] = [measurement.as_of] if measurement and measurement.as_of else []
    metrics = []
    if conn_id and text:
        from aughor.explorer.metric_coherence import asserted_governed_metrics
        metrics = [m for m in _unique_by_name(asserted_governed_metrics(text, conn_id))
                   if metric_is_approved(m) and getattr(m, "freshness_check_sql", None)]
    breaches: list[str] = []
    notes: list[str] = []
    unavailable = False
    now = datetime.now(timezone.utc)
    for m in metrics[:TIEOUT_MAX_METRICS]:
        try:
            from aughor.semantic.metrics import check_freshness
            result = check_freshness(m, conn.get())
        except Exception as exc:
            tolerate(exc, "departure gate: freshness check unavailable",
                     counter="departures.freshness_unavailable")
            unavailable = True
            notes.append(f"{m.name}: freshness unavailable")
            continue
        latest = parse_moment(getattr(result, "latest_data_at", None))
        if latest is None:
            unavailable = True
            notes.append(f"{m.name}: latest data time unknown")
            continue
        as_ofs.append(latest.strftime("%Y-%m-%d %H:%M"))
        sla = sla_hours(getattr(m, "freshness_sla", "") or "")
        if sla is None:
            notes.append(f"{m.name}: its SLA is not a duration — not judged")
            continue
        age_h = (now - latest).total_seconds() / 3600.0
        if age_h > sla:
            breaches.append(f"{m.name}'s data is {_hours(age_h)} old against its declared "
                            f"{_hours(sla)} freshness SLA")
        else:
            notes.append(f"{m.name}: within its {_hours(sla)} SLA")
    stated = earliest(as_ofs)
    detail = {"as_of": stated}
    if breaches:
        return _Check(HOLDS, "; ".join(breaches), "freshness: " + "; ".join(breaches), detail)
    if not metrics and not stated:
        return _Check(NOT_APPLICABLE, "no as-of is known for these numbers", detail=detail)
    summary = (f"as of {stated[:10]}" if stated else "as of: not known") + (
        " — " + "; ".join(notes) if notes else "")
    return _Check(UNAVAILABLE if unavailable and not stated else PASSED, summary, detail=detail)


def _claims(text: str, investigation_id: str) -> _Check:
    """Law 5 — descriptive departs; associational and causal on the analysis's recorded
    licence; a forecast never."""
    from aughor.agent.claim_type import is_at_least, sentence_claims
    found = sentence_claims(text)
    if not found:
        return _Check(PASSED, "descriptive — no associational, causal or forecast claim")
    licence, refuted = "", False
    if investigation_id and any(t in ("causal", "associational") for _s, t, _v in found):
        from aughor.govern.departure_basis import analysis_claim_facts
        licence, refuted = analysis_claim_facts(investigation_id)
    why = (" — no analysis is linked" if not investigation_id
           else " — its analysis recorded no licence" if not licence
           else f" — its analysis is licensed {licence}")
    problems: list[str] = []
    for sentence, claim, verb in found:
        quoted = _clip(sentence, 120)
        if claim == "predictive":
            problems.append(f"a forecast never departs — the platform has no forecaster "
                            f"(\"{verb}\" in: {quoted})")
        elif claim == "causal" and not is_at_least(licence, "causal"):
            problems.append(f"a causal claim departs only on its analysis's causal licence"
                            f"{why} (\"{verb}\" in: {quoted})")
        elif claim == "causal" and refuted:
            problems.append(f"a causal claim whose analysis recorded a refutation does not "
                            f"depart (\"{verb}\" in: {quoted})")
        elif claim == "associational" and not is_at_least(licence, "associational"):
            problems.append(f"an associational claim departs only on its analysis's licence"
                            f"{why} (\"{verb}\" in: {quoted})")
    if problems:
        return _Check(HOLDS, "; ".join(problems), "claim type: " + "; ".join(problems))
    return _Check(PASSED, f"claims within the analysis's {licence} licence")


def _disagreement(disagreement: Optional[dict], conn_id: str, declared_by: str) -> _Check:
    """Law 6 — divergent readings have no asker at departure, so the owner is asked."""
    if not disagreement:
        return _Check(NOT_APPLICABLE, "no divergent readings")
    from aughor.govern.departure_basis import owner_for_disagreement
    owner = owner_for_disagreement(disagreement, conn_id) or declared_by or ""
    label = disagreement.get("metric_label") or disagreement.get("subject") or "a metric"
    # A preview is written for a chip ("= 2.10%"); in a sentence it reads "2.10% vs 7.80%".
    previews = " vs ".join(str(p).lstrip("= ").strip() for p in (disagreement.get("previews") or []) if p)
    what = f"the readings of {label} disagree" + (f" ({previews})" if previews else "")
    asked = (f"{owner} is asked" if owner
             else "the owner is asked on the departures screen (no owner is routable)")
    return _Check(ASKED, f"{what} — asking {owner or 'on the departures screen'}",
                  f"{what}, and a departure has no asker — {asked}; nothing is sent until "
                  f"answered", detail={"owner": owner})


def _repeat(kind: str, origin: str, text: str, target: str, source: str) -> _Check:
    """Law 7 — never the same message twice to the same place; a repeat inside the noise
    band is noise."""
    if origin == PERSON:
        return _Check(EXEMPT, "a person chose to send it")
    if kind in REPEAT_POLICY:
        return _Check(EXEMPT, REPEAT_POLICY[kind])
    if not source:
        return _Check(NOT_APPLICABLE, "no source to compare against")
    from aughor.govern.departure_store import last_departed
    since = (datetime.now(timezone.utc) - timedelta(hours=REPEAT_WINDOW_HOURS)
             ).strftime("%Y-%m-%dT%H:%M:%SZ")
    prior = last_departed(source=source, target=target, fingerprint=message_shape_key(text),
                          since=since)
    if prior is None:
        return _Check(PASSED, f"not sent to this place in the last {REPEAT_WINDOW_HOURS // 24} days")
    try:
        before = [float(x) for x in json.loads(prior.get("numerals") or "[]")]
    except (TypeError, ValueError):
        before = []
    now_values = significant_values(text)
    when = str(prior.get("ts") or "")[:16].replace("T", " ")
    place = target or "the same place"
    if now_values and len(before) == len(now_values):
        largest = max(_rel(a, b) for a, b in zip(before, now_values))
        if largest >= NOISE_REL:
            return _Check(PASSED, f"the same message moved {largest:.0%} since {when}")
        if largest > 0:
            return _Check(HOLDS, f"within the noise band of the departure at {when} "
                                 f"(largest move {largest:.1%})",
                          f"every number moved less than {NOISE_REL:.0%} since this message "
                          f"departed to {place} at {when} (largest {largest:.1%}) — within "
                          f"the noise band, not news")
    elif now_values or before:
        return _Check(PASSED, f"the numbers changed shape since {when}")
    return _Check(HOLDS, f"already departed at {when}",
                  f"the same message already departed to {place} at {when} — never the "
                  f"same finding twice")


def _probation(state: str, probation: bool, declared_by: str) -> _Check:
    """Probation decides addressing, never accuracy; any hold above outranks it."""
    if not probation:
        return _Check(NOT_APPLICABLE, "not on probation")
    if not declared_by:
        return _Check(NOT_APPLICABLE, "no declarer — inert")
    if state != DEPARTED:
        return _Check(NOT_APPLICABLE,
                      f"on probation (already {state.replace('_', ' ')}) — {declared_by}")
    return _Check(HOLDS, f"on probation — addressed to {declared_by}",
                  f"on probation: this departure goes to {declared_by}'s review queue, not the "
                  f"channel — it graduates at measured precision "
                  f"(≥{GRADUATION_PRECISION:.0%} over ≥{GRADUATION_MIN_MARKED} marked)")


# ── text helpers (pure) ───────────────────────────────────────────────────────────

_DATE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\b")
_CLAUSE_RE = re.compile(r"(?<=[.!?])\s+|[;\n]+")
_NUMBER_TOKEN_RE = re.compile(r"[$€£]?\d[\d,]*(?:\.\d+)?%?")


def _strip_dates(text: str) -> str:
    """Dates and clock times are moments, not measured magnitudes."""
    return _DATE_RE.sub(" ", text or "")


def _assertive(numeral) -> bool:
    return bool(numeral.enforce or numeral.suffix == "%" or numeral.decimals > 0
                or numeral.text[:1] in "$€£")


def numeric_clauses(text: str) -> list[str]:
    """Clauses that state a number — any numeral once dates, clock times and calendar years
    are taken out. Law 2 judges only what these clauses NAME beside the number (a KPI, a
    governed metric), so "3 regions" costs nothing and "AOV held at 96" is judged."""
    from aughor.explorer.grounding import extract_numerals
    out: list[str] = []
    for clause in _CLAUSE_RE.split(text or ""):
        if clause.strip() and any(not _is_year(n) for n in extract_numerals(_strip_dates(clause))):
            out.append(clause.strip())
    return out


def _is_year(numeral) -> bool:
    return (not numeral.suffix and numeral.decimals == 0
            and 1900.0 <= float(numeral.value) <= 2100.0)


def significant_values(text: str) -> list[float]:
    """The numbers law 7 compares between two sends of one message, in order."""
    from aughor.explorer.grounding import extract_numerals
    return [float(n.value) for n in extract_numerals(_strip_dates(text)) if _assertive(n)]


def message_shape_key(text: str) -> str:
    """The message with its numbers and moments taken out — two sends share it when they
    say the same thing about possibly different numbers."""
    skeleton = _NUMBER_TOKEN_RE.sub("#", _strip_dates(text).lower())
    skeleton = re.sub(r"\s+", " ", skeleton).strip()
    return hashlib.sha256(skeleton.encode("utf-8")).hexdigest()[:24]


def _rel(a: float, b: float) -> float:
    top = max(abs(a), abs(b))
    return abs(a - b) / top if top else 0.0


_SLA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)\b", re.I)
_SLA_WORDS = {"hourly": 1.0, "daily": 24.0, "nightly": 24.0, "weekly": 168.0}


def sla_hours(text: str) -> Optional[float]:
    """A free-text freshness SLA as hours — "24h", "within 2 days", "daily by 6am UTC" — or
    None when it names no duration."""
    t = (text or "").lower()
    m = _SLA_RE.search(t)
    if m:
        n, unit = float(m.group(1)), m.group(2)[0]
        return {"m": n / 60.0, "h": n, "d": n * 24.0, "w": n * 168.0}[unit]
    for word, hours in _SLA_WORDS.items():
        if word in t:
            return hours
    return None


def parse_moment(value) -> Optional[datetime]:
    """A timestamp or a date as an aware UTC datetime. A bare date means the END of that
    day — data "as of 2026-09-16" was complete through the 16th, not stale at 00:01."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.strptime(s, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def earliest(moments: list[str]) -> str:
    """The earliest of several as-of strings (the most conservative one to state), as
    written; "" when none parses."""
    parsed = [(parse_moment(m), m) for m in moments if m]
    parsed = [(dt, m) for dt, m in parsed if dt is not None]
    return min(parsed)[1] if parsed else ""


def age_seconds(moment: str) -> Optional[float]:
    dt = parse_moment(moment)
    if dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())


def describe_age(seconds: Optional[float]) -> str:
    if seconds is None:
        return "at an unrecorded time"
    if seconds < 60:
        return "moments ago"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 172800:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} days ago"


def _hours(h: float) -> str:
    return f"{h:.0f}h" if h < 72 else f"{h / 24:.0f} days"


def _tokens(numerals) -> str:
    return ", ".join(n.text for n in numerals)


def _is_are(items) -> str:
    return "is" if len(items) == 1 else "are"


def _measured_phrase(values: list, rates: list) -> str:
    if len(values) + len(rates) > 8:
        return f"{len(values) + len(rates)} measured values"
    shown = [f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}" for v in values]
    shown += [f"{r * 100:.2f}%" for r in rates]
    return " · ".join(shown)


def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _unique_by_name(metrics) -> list:
    seen: set[str] = set()
    out = []
    for m in metrics:
        name = str(getattr(m, "name", "") or "")
        if name in seen:
            continue
        seen.add(name)
        out.append(m)
    return out


def _question_record(disagreement: Optional[dict]) -> dict:
    """What the owner is asked, stored on the row so the answer door can remember it
    without resuming anything."""
    if not disagreement:
        return {}
    keep = ("subject", "metric_label", "metric_name", "question", "options", "previews",
            "readings", "investigation_id")
    return {k: disagreement[k] for k in keep if k in disagreement}


class _LazyConnection:
    """The warehouse connection the tie-out and freshness guards share — opened only when a
    guard needs SQL, once per departure, closed when the accuracy guards are done."""

    def __init__(self, conn_id: str):
        self.conn_id = conn_id
        self._db = None
        self._error: Optional[Exception] = None

    def get(self):
        if self._db is None and self._error is None:
            try:
                from aughor.db.connection import open_connection_for
                self._db = open_connection_for(self.conn_id)
            except Exception as exc:
                self._error = exc
        if self._error is not None:
            raise self._error
        return self._db

    def close(self) -> None:
        if self._db is None:
            return
        try:
            self._db.close()
        except Exception as exc:
            tolerate(exc, "departure gate: connection close failed",
                     counter="departures.tieout_close_failed")
        self._db = None


def _record(**fields) -> str:
    """One ledger row per gate decision. Tolerated — the ledger must not block a send —
    but a failure to record a hold never un-holds it (the verdict is already made).
    Returns the row id, "" when the write failed."""
    try:
        from aughor.govern.departure_store import record_departure
        return record_departure(**fields)
    except Exception as exc:
        tolerate(exc, "departure gate: ledger write failed — the verdict stands unrecorded",
                 counter="departures.record_failed")
        return ""
