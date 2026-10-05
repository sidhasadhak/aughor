"""Decisions and outcomes — the missing half of the books (the 2027 study §K; phase 1).

A ledger of money records the budget and then the spend. A ledger of judgment records what was
expected and decided, and then what happened. Both kinds are kernel artifacts (``decision`` ·
``outcome``), supersede-not-delete, with the claims a decision relied on recorded AS THEY STOOD at
the moment of deciding (their artifact ids, which are immutable versions).

Capture costs nearly nothing or the ledger stays empty — the outcome loop proved that by running
end to end with no outcome ever recorded. So a decision is booked as a BY-PRODUCT of the doors
that already exist (accepting a recommendation, approving an action, a sentence declaring a
decision taken elsewhere), and the expectation is booked with it as a prediction claim: one line,
"expected: conversion +2% to +4% by 14 November". Without it there is nothing to score.

The review date is proposed, never guessed from nothing: the default 30 days, pushed out by the
connection's learned settling lag so the review reads settled days (:func:`propose_review_on`).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from aughor.record import claims as _claims

DECISION_KIND = "decision"
OUTCOME_KIND = "outcome"
DEFAULT_REVIEW_DAYS = 30

SourceKind = Literal["recommendation", "approval", "declared", "autonomy"]
Verdict = Literal["as_expected", "better", "worse", "cannot_tell"]


class Option(BaseModel):
    id: str
    description: str
    predictions: list[str] = Field(default_factory=list)   # prediction claim ids
    cost: str = ""
    reversibility: str = ""        # undoable until … | compensable | irreversible
    actor: str = ""                # who would act


class Dissent(BaseModel):
    who: str
    why: str


class Expectation(BaseModel):
    """What the decision expects, as a prediction claim's statement: a metric, a direction, an
    interval at a stated coverage, and the date it settles on."""
    metric: str
    direction: str = ""            # up | down | hold
    low: Optional[float] = None
    mid: Optional[float] = None
    high: Optional[float] = None
    unit: str = ""                 # "%" for a relative change, else the metric's own
    coverage: float = 0.8          # the interval's stated coverage
    settles_on: str = ""           # ISO date
    text: str = ""                 # the one line, as said


class Source(BaseModel):
    kind: SourceKind
    ref: str                       # the recommendation's outcome id · the proposal id · the note id
    detail: str = ""


class Decision(BaseModel):
    question: str
    owner: str = ""                # the principal answerable; "" is said, not hidden
    approvers: list[str] = Field(default_factory=list)
    options: list[Option] = Field(default_factory=list)
    chosen: str = ""               # option id
    dissent: list[Dissent] = Field(default_factory=list)
    relied_on: list[str] = Field(default_factory=list)   # claim artifact ids, as recorded then
    objective: str = ""            # a mission id or a metric
    decided_at: str = ""
    decided_by: str = ""
    review_on: str = ""
    expectation_claim: str = ""    # the prediction claim's artifact id
    actions: list[str] = Field(default_factory=list)
    outcome: str = ""              # the outcome artifact id, once measured
    reopened_by: str = ""          # a relied-on claim that was restated or refuted
    source: Source
    connection_id: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    # read-only, filled by the ledger
    id: str = ""
    key: str = ""
    version: int = 0
    recorded_at: str = ""
    superseded_by: str = ""


class Effect(BaseModel):
    value: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None
    method: str = ""               # the scenario ladder's method (identity · declared · history · …)


class Outcome(BaseModel):
    of: str                        # the decision artifact id
    measured_on: str               # ISO date; settled days only
    actual: Optional[float] = None
    baseline: Optional[float] = None   # what the metric's own history predicted without the change
    effect: Effect = Field(default_factory=Effect)
    verdict: Verdict = "cannot_tell"
    why: str = ""
    against_expectation: str = ""  # inside | above | below | no expectation
    writes_back: list[str] = Field(default_factory=list)   # what was updated: a claim class, a playbook entry, …
    measured_by: str = "system"
    extra: dict[str, Any] = Field(default_factory=dict)
    id: str = ""
    key: str = ""
    recorded_at: str = ""


def decision_key(source: Source) -> str:
    return f"decision:{source.kind}:{source.ref}"


def outcome_key(decision_id: str) -> str:
    return f"outcome:{decision_id}"


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def propose_review_on(connection_id: str, decided_at: Optional[_dt.datetime] = None, *,
                      default_days: int = DEFAULT_REVIEW_DAYS) -> tuple[str, str]:
    """``(review_on, why)``: the default days out, pushed by the connection's learned settling
    lag so the review is measured on settled days. Says which it did."""
    decided_at = decided_at or _dt.datetime.now(_dt.timezone.utc)
    lag: Optional[int] = None
    try:
        from aughor.settling.store import learned_lag_days
        lag = learned_lag_days(connection_id) if connection_id else None
    except Exception as exc:  # noqa: BLE001 — an unreadable lag is a note, never a failed booking
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the settling lag could not be read; the review date uses the default",
                 counter="record.review_lag", conn_id=connection_id or None)
    days = int(default_days)
    if lag:
        days += int(lag)
        why = f"{default_days} days plus the connection's learned settling lag of {lag} days"
    else:
        why = f"{default_days} days; no learned settling lag for this connection"
    return (decided_at + _dt.timedelta(days=days)).date().isoformat(), why


def _expectation_claim(decision: Decision, exp: Expectation, *, author: str) -> str:
    text = exp.text or _expectation_text(exp)
    claim = _claims.Claim(
        kind="prediction", tier="declared",
        about=_claims.About(kind="connection", key=decision.connection_id) if decision.connection_id
        else _claims.About(kind="organisation", key=""),
        statement=_claims.Statement(text=text, metric=exp.metric, value=exp.mid, unit=exp.unit,
                                    range_end=exp.settles_on),
        status="To date", as_of=decision.decided_at[:10], author=author or decision.decided_by,
        author_kind="person", owner=decision.owner, state="open",
        extra={"direction": exp.direction, "low": exp.low, "mid": exp.mid, "high": exp.high,
               "coverage": exp.coverage, "settles_on": exp.settles_on, "method": "declared"},
    )
    return _claims.book(claim, key=_claims.claim_key("prediction", decision_key(decision.source)),
                        conn_id=decision.connection_id or None)


def _expectation_text(exp: Expectation) -> str:
    unit = exp.unit or ""
    if exp.low is not None and exp.high is not None:
        band = f"{exp.low:+g}{unit} to {exp.high:+g}{unit}" if unit == "%" else f"{exp.low:g} to {exp.high:g} {unit}".strip()
    elif exp.mid is not None:
        band = f"{exp.mid:+g}{unit}" if unit == "%" else f"{exp.mid:g} {unit}".strip()
    else:
        band = exp.direction or "to move"
    by = f" by {exp.settles_on}" if exp.settles_on else ""
    return f"expected: {exp.metric} {band}{by}"


def book_decision(decision: Decision, *, expectation: Optional[Expectation] = None,
                  author: str = "") -> str:
    """Book a decision, and its expectation as a prediction claim at the same moment. A decision
    already booked under the same source is restated (a new version; the old kept). Returns the
    decision's artifact id."""
    if not (decision.question or "").strip():
        raise ValueError("a decision states what was being decided")
    decision.decided_at = decision.decided_at or _now()
    if not decision.review_on:
        decision.review_on, why = propose_review_on(
            decision.connection_id, _claims._as_dt(decision.decided_at))
        decision.extra.setdefault("review_on_why", why)
    if expectation is not None and expectation.metric:
        if not expectation.settles_on:
            expectation.settles_on = decision.review_on
        decision.expectation_claim = _expectation_claim(decision, expectation, author=author)
    data = decision.model_dump()
    for read_only in ("id", "key", "version", "recorded_at", "superseded_by"):
        data.pop(read_only, None)
    edges = [("relied_on", cid, "as recorded at the moment of deciding") for cid in decision.relied_on]
    if decision.expectation_claim:
        edges.append(("expects", decision.expectation_claim, "the prediction booked with the decision"))
    return _ledger().artifact_write(DECISION_KIND, decision_key(decision.source), data,
                                    conn_id=decision.connection_id or None, lineage=edges)


def _decision_from(art: dict) -> Decision:
    d = Decision.model_validate(dict(art.get("payload") or {}))
    d.id = str(art.get("id") or "")
    d.key = str(art.get("natural_key") or "")
    d.version = int(art.get("version") or 0)
    d.recorded_at = str(art.get("created_at") or "")
    d.superseded_by = str(art.get("superseded_by") or "")
    return d


def get_decision(decision_id: str) -> Optional[Decision]:
    art = _ledger().artifact_by_id(decision_id)
    return _decision_from(art) if art and art.get("kind") == DECISION_KIND else None


def latest_decision(source: Source) -> Optional[Decision]:
    art = _ledger().artifact_latest(decision_key(source))
    return _decision_from(art) if art and art.get("kind") == DECISION_KIND else None


def list_decisions(*, conn_id: Optional[str] = None, limit: int = 200) -> list[Decision]:
    return [_decision_from(a) for a in _ledger().artifacts_of_kind(DECISION_KIND, conn_id=conn_id, limit=limit)]


def version_ids(decision_id: str) -> list[str]:
    """The id of every version of the decision this id belongs to, newest first. What was booked
    FOR an earlier version — a scenario, a prediction — is still the decision's after an outcome,
    an amendment or a reopening has restated it."""
    d = get_decision(decision_id)
    if d is None:
        return []
    return [str(a.get("id") or "") for a in _ledger().artifact_versions(d.key, limit=500)
            if a.get("kind") == DECISION_KIND]


def decisions_relying_on(claim_id: str) -> list[Decision]:
    return [d for d in list_decisions(limit=2000) if claim_id in d.relied_on]


def due_for_review(now: Optional[_dt.datetime] = None) -> list[Decision]:
    """Decisions whose review date has come and that carry no outcome yet."""
    today = (now or _dt.datetime.now(_dt.timezone.utc)).date().isoformat()
    return [d for d in list_decisions(limit=2000) if d.review_on and d.review_on <= today and not d.outcome]


def book_outcome(outcome: Outcome) -> str:
    """Book the outcome of a decision and stamp the decision with it (a restatement of the
    decision, its earlier version kept). Returns the outcome's artifact id."""
    decision = get_decision(outcome.of)
    if decision is None:
        raise ValueError(f"no decision {outcome.of!r} to book an outcome of")
    data = outcome.model_dump()
    for read_only in ("id", "key", "recorded_at"):
        data.pop(read_only, None)
    oid = _ledger().artifact_write(OUTCOME_KIND, outcome_key(outcome.of), data,
                                   conn_id=decision.connection_id or None,
                                   lineage=[("outcome_of", outcome.of, outcome.verdict)])
    decision.outcome = oid
    book_decision(decision)      # a new version carrying the outcome; the expectation stays as booked
    if decision.expectation_claim:
        pred = _claims.get(decision.expectation_claim)
        if pred is not None and pred.state != "scored":
            pred.state = "scored"
            pred.extra["scored_against"] = outcome.against_expectation
            pred.extra["outcome"] = oid
            _claims.restate(pred.key, pred, conn_id=decision.connection_id or None)
    # Phase 7 — an outcome is an event out: journaled and delivered to the subscriptions that asked.
    try:
        payload = {"outcome_id": oid, "decision": outcome.of, "verdict": outcome.verdict, "against_expectation": outcome.against_expectation,
                   "actual": outcome.actual, "baseline": outcome.baseline, "text": decision.question[:300]}
        _ledger().emit("outcome.booked", payload, conn_id=decision.connection_id or None)
        from aughor.record.subscriptions import notify
        notify("outcome.booked", payload, conn_id=decision.connection_id or "")
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the outcome.booked event could not go out; the outcome stands", counter="decisions.events_out")
    return oid


def _outcome_from(art: Optional[dict]) -> Optional[Outcome]:
    if not art or art.get("kind") != OUTCOME_KIND:
        return None
    o = Outcome.model_validate(dict(art.get("payload") or {}))
    o.id = str(art.get("id") or "")
    o.key = str(art.get("natural_key") or "")
    o.recorded_at = str(art.get("created_at") or "")
    return o


def get_outcome(decision_id: str) -> Optional[Outcome]:
    """The outcome booked against this decision id — the version that was current when the
    outcome was measured. A later version carries the outcome's id in ``outcome``; read that
    with :func:`outcome_by_id`."""
    return _outcome_from(_ledger().artifact_latest(outcome_key(decision_id)))


def outcome_by_id(outcome_id: str) -> Optional[Outcome]:
    return _outcome_from(_ledger().artifact_by_id(outcome_id)) if outcome_id else None


def restate_outcome(outcome_id: str, *, extra: dict, verdict: Optional[str] = None, why: str = "") -> str:
    """A new version of an outcome under its key — a person's answer laid beside the measured
    verdict, never over it. Returns the new version's id and leaves the decision pointing at it."""
    prior = outcome_by_id(outcome_id)
    if prior is None:
        raise ValueError(f"no outcome {outcome_id!r} to restate")
    data = prior.model_dump()
    for read_only in ("id", "key", "recorded_at"):
        data.pop(read_only, None)
    data["extra"] = {**(data.get("extra") or {}), **(extra or {})}
    if verdict:
        data["verdict"] = verdict
    if why:
        data["why"] = why
    new_id = _ledger().artifact_write(OUTCOME_KIND, prior.key, data, lineage=[("supersedes", outcome_id, "restated")])
    decision = get_decision(prior.of)
    if decision is not None:
        latest = latest_decision(decision.source) or decision
        if latest.outcome == outcome_id:
            latest.outcome = new_id
            book_decision(latest)
    return new_id


# ── what a person adds after a decision is booked (the study §V, screen 5) ─────────────────

def _current(decision: Decision) -> Decision:
    return latest_decision(decision.source) or decision


def amend_decision(decision_id: str, *, by: str = "", option: str = "", dissent_who: str = "",
                   dissent_why: str = "") -> Decision:
    """Add an option that was on the table, or a dissent, to a decision already booked — a new
    version, the earlier one kept, the addition dated and named so it never reads as having been
    there at the moment of deciding. What was chosen does not change here: choosing again is a
    new decision."""
    asked = get_decision(decision_id)
    if asked is None:
        raise ValueError(f"no decision {decision_id!r}")
    option, dissent_who, dissent_why = (option or "").strip(), (dissent_who or "").strip(), (dissent_why or "").strip()
    if not option and not (dissent_who or dissent_why):
        raise ValueError("an amendment adds an option or a dissent")
    if (dissent_who or dissent_why) and not (dissent_who and dissent_why):
        raise ValueError("a dissent names who disagreed and why")
    d = _current(asked)
    added: list[dict] = []
    if option:
        if option.lower() in {o.description.strip().lower() for o in d.options} | {o.id.strip().lower() for o in d.options}:
            raise ValueError("that option is already on the decision")
        d.options = list(d.options) + [Option(id=option[:200], description=option[:500])]
        added.append({"kind": "option", "what": option[:200]})
    if dissent_who:
        d.dissent = list(d.dissent) + [Dissent(who=dissent_who[:200], why=dissent_why[:1000])]
        added.append({"kind": "dissent", "what": dissent_who[:200]})
    now = _now()
    d.extra["amendments"] = list(d.extra.get("amendments") or []) + [
        {**a, "at": now, "by": by or "unidentified"} for a in added]
    new_id = book_decision(d)
    return get_decision(new_id) or d


def reopen_for_claim(claim_id: str, *, restated_as: str = "", why: str = "") -> list[Decision]:
    """A claim was restated or marked wrong: every decision that relied on it — as recorded at the
    moment of deciding — is reopened, naming the version that replaced what it stood on. A
    reopened decision is not undone; it says its ground moved, and a person answers."""
    if not claim_id:
        return []
    out: list[Decision] = []
    for d in list_decisions(limit=2000):
        # what it stands on: the claims it cited, and whatever replaced one of them since
        stood_on = set(d.relied_on) | {str(r.get("restated_as") or "") for r in (d.extra.get("reopened") or [])}
        if claim_id not in stood_on or d.reopened_by == (restated_as or claim_id):
            continue
        d.reopened_by = restated_as or claim_id
        d.extra["reopened"] = list(d.extra.get("reopened") or []) + [
            {"at": _now(), "claim": claim_id, "restated_as": restated_as, "why": (why or "")[:400]}]
        new_id = book_decision(d)
        out.append(get_decision(new_id) or d)
    return out


def settle_reopening(decision_id: str, *, by: str = "", why: str = "") -> Decision:
    """A person answers a reopened decision: it stands on the restated ground, and why. The
    reopening stays in the decision's history; only the open flag is cleared."""
    asked = get_decision(decision_id)
    if asked is None:
        raise ValueError(f"no decision {decision_id!r}")
    d = _current(asked)
    if not d.reopened_by:
        raise ValueError("this decision is not reopened")
    if not (why or "").strip():
        raise ValueError("say why the decision still stands on what replaced the claim")
    history = list(d.extra.get("reopened") or [])
    if history:
        history[-1] = {**history[-1], "settled_at": _now(), "settled_by": by or "unidentified", "settled_why": why.strip()[:1000]}
    d.extra["reopened"] = history
    d.reopened_by = ""
    new_id = book_decision(d)
    return get_decision(new_id) or d
