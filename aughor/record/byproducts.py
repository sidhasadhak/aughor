"""Decisions booked as a BY-PRODUCT of the doors that already exist (the 2027 study §K; phase 1,
P1-3).

Capture costs nearly nothing or the ledger stays empty: `data/recommendation_outcomes.json` had
never been written on the live deployment before CB-2, and the inbox resolved proposals for a
year without a decision record. So no door here asks for a form. Three doors book a Decision in
passing, each with what it already knows:

- **accepting a recommendation** (`routers/investigations.py::log_recommendation_outcome`,
  status ``accepted``): the recommendation's own text as the question, accept/decline as the
  options, the claims the deep analysis booked as what was relied on, the review date CB-2
  already decides (now pushed by the connection's settling lag), and the expectation when the
  request carries one — a metric, a direction, a band. Declining before ever accepting books the
  same decision with ``decline`` chosen. Answering the review (``verified`` · ``rejected`` ·
  ``implemented``) books the Outcome against the expectation; against the metric's own history is
  phase 3's, and the outcome says so.
- **approving or rejecting a staged proposal** (`actions/inbox.py`): approve/decline, the action
  it arms, the proposer, the trace; a proposal raised from an investigation relies on that
  investigation's claims. A proposal carries no expectation line, and the decision says so.
- **declaring a decision taken elsewhere** (`routers/record.py`, ``POST /record/decisions``): the
  one door that takes the decision's own words, for the choices made in a meeting or a thread.

Every booking is best-effort by contract: the acceptance, the approval and the review stand when
the booking fails, and ``tolerate`` says so.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from aughor.record import claims as _claims
from aughor.record import decisions as _dec
from aughor.record.writers import observation_key

_ACCEPT_OPTIONS = [_dec.Option(id="accept", description="accept the recommendation and review it on its date"),
                   _dec.Option(id="decline", description="decline the recommendation")]
_APPROVE_OPTIONS = [_dec.Option(id="approve", description="approve the proposal and arm the action"),
                    _dec.Option(id="decline", description="reject the proposal; nothing runs")]


def relied_on_claims(connection_id: str, investigation_id: str) -> list[str]:
    """The claims an investigation booked — its observation and its findings — as they stand now
    (their ids are immutable versions, so what was relied on is what was current at deciding)."""
    if not (connection_id and investigation_id):
        return []
    out: list[str] = []
    obs = _claims.latest(observation_key(connection_id, investigation_id))
    if obs is not None:
        out.append(obs.id)
    for c in _claims.list_claims(conn_id=connection_id, limit=500):
        if c.extra.get("investigation_id") == investigation_id and c.id not in out and c.kind != "observation":
            out.append(c.id)
    return out


def expectation_from(fields: Optional[dict], *, default_metric: str = "") -> Optional[_dec.Expectation]:
    """An Expectation from a request's fields, or None when no metric is named — nothing is
    guessed from a recommendation's wording."""
    f = dict(fields or {})
    metric = str(f.get("metric") or default_metric or "").strip()
    if not metric:
        return None
    return _dec.Expectation(metric=metric, direction=str(f.get("direction") or ""),
                            low=f.get("low"), mid=f.get("mid"), high=f.get("high"),
                            unit=str(f.get("unit") or ""), coverage=float(f.get("coverage") or 0.8),
                            settles_on=str(f.get("settles_on") or ""), text=str(f.get("text") or ""),
                            segment_dimension=str(f.get("segment_dimension") or "").strip(),
                            segment_value=str(f.get("segment_value") or "").strip())


def _person(uid: str, fallback: str) -> str:
    return f"user:{uid}" if uid and not uid.startswith("user:") else (uid or fallback or "")


def _mission_for(connection_id: str, metric: str) -> str:
    """The active mission the decision's metric bears on, or "" (phase 5) — best-effort."""
    if not metric:
        return ""
    from aughor.record.inquiry import mission_for
    return mission_for(connection_id, metric)


# ── the acceptance door ────────────────────────────────────────────────────────────────────

def decision_from_recommendation(outcome, *, chosen: str, decided_by: str, connection_id: str,
                                 expectation: Optional[_dec.Expectation] = None,
                                 review_on: str = "", review_on_why: str = "") -> str:
    """Book (or restate) the decision a recommendation's acceptance or decline is. ``outcome`` is
    the playbook's RecOutcome; its id (``{inv_id}_rec_{index}``) is the decision's source ref."""
    src = _dec.Source(kind="recommendation", ref=outcome.id,
                      detail=f"recommendation {outcome.rec_index} of investigation {outcome.inv_id}")
    prior = _dec.latest_decision(src)
    extra: dict[str, Any] = {"investigation_id": outcome.inv_id, "rec_index": outcome.rec_index,
                             "outcome_record": outcome.id}
    if review_on_why:
        extra["review_on_why"] = review_on_why
    if getattr(outcome, "baseline_value", None) is not None:
        extra["baseline_value"] = outcome.baseline_value
        extra["baseline_window"] = outcome.baseline_window
    if getattr(outcome, "review_note", ""):
        extra["review_note"] = outcome.review_note
    if expectation is None:
        extra["expectation_note"] = "none given with the acceptance — nothing to score on the review date"
    # Phase 5: the decision carries the mission its metric bears on, so the mission's report can count it.
    metric = (expectation.metric if expectation is not None else "") or (getattr(outcome, "spec", None) or {}).get("metric_label") \
        or getattr(outcome, "metric_name", "") or ""
    objective = prior.objective if prior is not None and prior.objective else _mission_for(connection_id, metric)
    # PENDING 57, D-1: the same report's other recommended actions were on the table too — kept as the
    # alternatives weighed; and the platform recommended accepting, so a decline is an override, counted.
    options = list(_ACCEPT_OPTIONS) + _alternatives(outcome)
    extra["recommended"] = "accept"
    decision = _dec.Decision(
        question=(outcome.rec_text or "").strip()[:500] or f"recommendation {outcome.rec_index}",
        owner=decided_by, options=options, chosen=chosen,
        relied_on=prior.relied_on if prior is not None else relied_on_claims(connection_id, outcome.inv_id),
        objective=objective,
        decided_by=decided_by, review_on=review_on or (outcome.review_at or "")[:10],
        expectation_claim=prior.expectation_claim if prior is not None else "",
        source=src, connection_id=connection_id or "", extra={**(prior.extra if prior else {}), **extra},
    )
    return _dec.book_decision(decision, expectation=expectation if prior is None else None,
                              author=decided_by)


def _alternatives(outcome) -> list[_dec.Option]:
    """The other actions the same deep analysis recommended, as options — ``alt_<index>``. Best-effort: a report
    that cannot be read leaves the accept/decline pair as it was."""
    try:
        from aughor.db.history import get_investigation
        inv = get_investigation(str(getattr(outcome, "inv_id", "") or "")) or {}
        report = inv.get("report") if isinstance(inv.get("report"), dict) else {}
        actions = [str(a).strip() for a in (report.get("recommended_actions") or []) if str(a).strip()]
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the decision stands; its report's other recommendations could not be read", counter="record.alternatives")
        return []
    own = int(getattr(outcome, "rec_index", -1))
    return [_dec.Option(id=f"alt_{i}", description=text[:300], actor="")
            for i, text in enumerate(actions) if i != own]


def overridden(decision: _dec.Decision) -> Optional[bool]:
    """Whether the chosen option was not the one recommended — None when nothing was recommended."""
    rec = str(decision.extra.get("recommended") or "")
    return None if not rec else decision.chosen != rec


_ANSWER_VERDICT = {"verified": "as_expected", "rejected": "worse", "implemented": "cannot_tell"}


def band_of(pred) -> Optional[tuple]:
    """An expectation claim's own band, ``(low, high, unit)``; None without one."""
    if pred is None:
        return None
    return (pred.extra.get("low"), pred.extra.get("high"), pred.statement.unit or "")


def against_expectation(decision, actual: Optional[float], before: Optional[float]) -> tuple[str, Optional[_claims.Claim]]:
    """Where the actual fell against the decision's expectation: inside · above · below · cannot
    tell (a relative band with no before value) · no expectation."""
    if not decision.expectation_claim:
        return "no expectation", None
    pred = _claims.get(decision.expectation_claim)
    if pred is None:
        return "no expectation", None
    from aughor.record.scenario import against_band
    return against_band(actual, low=pred.extra.get("low"), high=pred.extra.get("high"),
                        unit=pred.statement.unit, before=before), pred


def verdict_against_baseline(*, actual: Optional[float], baseline: Optional[float], low: Optional[float],
                             high: Optional[float], direction: str, against: str, history_note: str,
                             drift: str = "", method: str = "history",
                             band: Optional[tuple] = None) -> tuple[str, str, _dec.Effect]:
    """``drift`` (PENDING 57, D-3): why this baseline cannot be trusted to stand for "what would have happened
    anyway" — the metric's own history band has missed one way; the effect is still measured and said, the verdict
    is cannot tell. ``method`` names the baseline the effect was measured against. ``band`` is the expectation's own
    ``(low, high, unit)`` — what a *hold* allowed; ``low``/``high`` are the baseline's band."""
    verdict, why, e = _verdict_core(actual=actual, baseline=baseline, low=low, high=high, direction=direction,
                                    against=against, history_note=history_note, band=band)
    if method != "history":
        e.method = method
        why = why.replace("against its own history", f"against its {_BASELINE_WORDS.get(method, method)}") \
                 .replace("history predicted", f"its {_BASELINE_WORDS.get(method, method)} predicted") \
                 .replace("no history baseline could be measured", "no comparison could be drawn")
    if drift and verdict != "cannot_tell":
        return "cannot_tell", f"{drift}; measured against it anyway, {why[0].lower() + why[1:]}", e
    return verdict, why, e


#: The words for a baseline an effect was measured against.
_BASELINE_WORDS = {"comparison": "comparison group (the rest of its group, at its usual share)"}


def _verdict_core(*, actual: Optional[float], baseline: Optional[float], low: Optional[float],
                  high: Optional[float], direction: str, against: str, history_note: str,
                  band: Optional[tuple] = None) -> tuple[str, str, _dec.Effect]:
    """Both verdicts' meeting point (the study §K rule 2; `IDEAS.md` 13 and 22): the effect is the
    actual against what the metric's own history predicted, with history's band; the verdict is
    code over that effect and the expected direction, and ``cannot tell`` says why. A *hold* is
    judged by :func:`_hold_verdict` (the decision-framework run, defect 5)."""
    if actual is None:
        return "cannot_tell", "the review could not measure the metric", _dec.Effect(method="history")
    if baseline is None:
        return "cannot_tell", f"no history baseline could be measured: {history_note or 'unknown'}", _dec.Effect(method="history")
    effect = actual - baseline
    eff_low = (actual - high) if high is not None else None
    eff_high = (actual - low) if low is not None else None
    e = _dec.Effect(value=round(effect, 6), low=round(eff_low, 6) if eff_low is not None else None,
                    high=round(eff_high, 6) if eff_high is not None else None, method="history")
    if direction == "hold":
        return _hold_verdict(actual=actual, baseline=baseline, effect=effect, eff_low=eff_low, eff_high=eff_high,
                             band=band, e=e)
    if eff_low is not None and eff_high is not None and eff_low <= 0 <= eff_high:
        return ("cannot_tell", f"inside the baseline's own noise: history predicted {low:,.4g} to {high:,.4g} and the "
                               f"metric read {actual:,.4g}", e)
    if direction not in ("up", "down"):
        return ("cannot_tell", f"the metric moved {effect:+,.4g} against its own history, but no expectation named the "
                               "wanted direction", e)
    wanted = effect > 0 if direction == "up" else effect < 0
    if not wanted:
        return "worse", f"the metric moved {effect:+,.4g} against its own history, the wrong way for '{direction}'", e
    if against == "above" and direction == "up" or against == "below" and direction == "down":
        return "better", f"the metric moved {effect:+,.4g} against its own history, beyond the expected band", e
    if against in ("inside", "no expectation", "cannot_tell"):
        return "as_expected", f"the metric moved {effect:+,.4g} against its own history, the wanted way", e
    return "worse", f"the metric moved {effect:+,.4g} the wanted way but short of the expected band", e


def allowed_effect(band: Optional[tuple], baseline: float) -> Optional[tuple[Optional[float], Optional[float]]]:
    """The effect an expectation's band allows, against the baseline: a relative band (unit %) is a share of the
    baseline, a band in the metric's own unit is where the level may land. None when the expectation named no band."""
    if not band:
        return None
    lo, hi, unit = (list(band) + [None, None, ""])[:3]
    if lo is None and hi is None:
        return None
    if unit == "%":
        return (baseline * lo / 100.0 if lo is not None else None, baseline * hi / 100.0 if hi is not None else None)
    return (lo - baseline if lo is not None else None, hi - baseline if hi is not None else None)


def _band_words(band: tuple) -> str:
    lo, hi, unit = (list(band) + [None, None, ""])[:3]
    if unit == "%":
        if lo is not None and hi is not None and abs(lo + hi) < 1e-9:
            return f"the ±{abs(hi):g}% its hold allowed"
        return f"the {lo if lo is not None else '…'}% to {hi if hi is not None else '…'}% its hold allowed"
    return f"the {lo if lo is not None else '…'} to {hi if hi is not None else '…'} its hold allowed"


def _hold_verdict(*, actual: float, baseline: float, effect: float, eff_low: Optional[float],
                  eff_high: Optional[float], band: Optional[tuple], e) -> tuple[str, str, _dec.Effect]:
    """A *hold* expects no move beyond its band; it names no wanted side, so a move outside the band is ``missed``
    — never better or worse, which would need a side the metric does not declare (the Lux run, scenario 3: Mytheresa
    moved +10% against the other shops under a "hold within 3%" and the review said cannot tell). Inside the
    baseline's noise, the hold is read as held only when the whole of that noise fits inside what the hold allowed —
    a noise wider than the band cannot tell a hold from a move."""
    rel = f" ({effect / abs(baseline) * 100:+.1f}%)" if baseline else ""
    allowed = allowed_effect(band, baseline)
    if allowed is None:
        return ("cannot_tell", f"the metric moved {effect:+,.4g}{rel} against its own history, but the hold named no "
                               "band to read it against", e)
    a_lo, a_hi = allowed
    words = _band_words(band)
    noisy = eff_low is not None and eff_high is not None and eff_low <= 0 <= eff_high
    if not noisy:
        if a_hi is not None and effect > a_hi or a_lo is not None and effect < a_lo:
            side = "above" if a_hi is not None and effect > a_hi else "below"
            return ("missed", f"the metric moved {effect:+,.4g}{rel} against its own history, {side} {words} — a hold "
                              "names no wanted side, so the move is neither better nor worse", e)
        return "as_expected", f"the metric moved {effect:+,.4g}{rel} against its own history, inside {words}", e
    fits = (eff_low is not None and eff_high is not None and (a_lo is None or a_lo <= eff_low)
            and (a_hi is None or eff_high <= a_hi))
    if fits:
        return ("as_expected", f"held: the metric read {actual:,.4g}, inside the baseline's noise, and the whole of "
                               f"that noise lies inside {words}", e)
    return ("cannot_tell", f"inside the baseline's own noise (an effect of {eff_low:+,.4g} to {eff_high:+,.4g}), which "
                           f"is wider than {words} — whether it held cannot be told", e)


def outcome_from_review(outcome) -> Optional[str]:
    """The REVIEW books the Outcome (phase 3): the actual measured on the review date against the
    expectation and against the metric's own history (method 3, measured by the review), the
    verdict by code, and the prediction scored. None when no decision was booked for this
    recommendation; the outcome already booked when the review ran before."""
    src = _dec.Source(kind="recommendation", ref=outcome.id)
    decision = _dec.latest_decision(src)
    if decision is None:
        return None
    if decision.outcome:
        return decision.outcome
    actual = outcome.review_value
    before = outcome.baseline_value if outcome.baseline_value is not None else outcome.metric_before
    # a relative band is read against the baseline the verdict is read against, never the window before (defect 8)
    against, pred = against_expectation(decision, actual, outcome.history_value if outcome.history_value is not None
                                        else before)
    direction = str(pred.extra.get("direction") or "") if pred is not None else ""
    from aughor.record.scenario import drift_words
    drift = drift_words(decision.connection_id, (pred.statement.metric if pred is not None else "")
                        or str(getattr(outcome, "metric_name", "") or ""))
    verdict, why, effect = verdict_against_baseline(
        actual=actual, baseline=outcome.history_value, low=outcome.history_low, high=outcome.history_high,
        direction=direction, against=against, history_note=outcome.history_note, drift=drift,
        band=band_of(pred))
    # The one outcome version the review books says what it wrote back. (The confirmed-cause graph it once wrote back
    # to is retired: what one promise does to another is a declared impact — Arc ED, ED-5.)
    writes_back = ["prediction scored"] if pred is not None else []
    result = _dec.Outcome(of=decision.id, measured_on=(outcome.reviewed_at or _dt.datetime.now(_dt.timezone.utc).isoformat())[:10],
                          actual=actual, baseline=outcome.history_value, effect=effect, verdict=verdict, why=why,
                          against_expectation=against, measured_by="system:review", writes_back=writes_back,
                          extra={"before": before, "after": actual, "review_window": outcome.review_window,
                                 "history_n": outcome.history_n, "history_note": outcome.history_note,
                                 "history_band": [outcome.history_low, outcome.history_high]})
    oid = _dec.book_outcome(result)
    if pred is not None:
        latest = _claims.latest(pred.key)
        if latest is not None and latest.state == "scored":
            latest.extra["actual"] = actual
            latest.confidence = None
            _claims.restate(latest.key, latest, conn_id=decision.connection_id or None)
    _relearn_playbook()
    return oid


def _relearn_playbook() -> int:
    """Phase 5: a play's success rate is learned from outcomes, not from use — re-counted after an
    outcome is booked (`playbook/outcomes.update_playbook_success_rates`). The playbook entry carries
    the record of it (its count and source); the outcome is not restated for bookkeeping."""
    try:
        from aughor.playbook.outcomes import update_playbook_success_rates
        return update_playbook_success_rates()
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the outcome stands; the playbook's success rates could not be re-learned", counter="record.playbook_writeback")
        return 0


def outcome_from_review_answer(outcome, *, status: str, answered_by: str) -> Optional[str]:
    """A person's answer at review (verified · rejected · implemented): when the review already
    booked the Outcome, the answer is RESTATED onto it — both verdicts kept, the measured one and
    the person's, never one overwriting the other (a good decision with a bad outcome is both). When
    no review ran yet (the answer came first), the answer books the Outcome against the expectation
    alone and says the history comparison is still owed. None when no decision was booked."""
    verdict = _ANSWER_VERDICT.get(status)
    if verdict is None:
        return None
    src = _dec.Source(kind="recommendation", ref=outcome.id)
    decision = _dec.latest_decision(src)
    if decision is None:
        return None
    if decision.outcome:
        return _dec.restate_outcome(decision.outcome, extra={"answer": status, "answered_by": answered_by or "unidentified",
                                                            "answer_verdict": verdict,
                                                            "answered_at": _dt.datetime.now(_dt.timezone.utc).isoformat()})
    actual = outcome.metric_after if outcome.metric_after is not None else outcome.review_value
    before = outcome.metric_before if outcome.metric_before is not None else outcome.baseline_value
    against, _pred = against_expectation(decision, actual, before)
    why = (f"the person's answer at review was '{status}'; measured against what was expected"
           f"{'' if against != 'no expectation' else ' (none was given)'}, not yet against the metric's "
           "own history — the review that measures it has not run")
    result = _dec.Outcome(of=decision.id, measured_on=(outcome.reviewed_at or _dt.datetime.now(_dt.timezone.utc).isoformat())[:10],
                          actual=actual, baseline=None,
                          effect=_dec.Effect(value=(actual - before) if (actual is not None and before is not None) else None,
                                             method="before_after"),
                          verdict=verdict, why=why, against_expectation=against,
                          measured_by=answered_by or "unidentified",
                          extra={"before": before, "after": actual, "review_window": outcome.review_window,
                                 "answer": status, "answered_by": answered_by or "unidentified"})
    return _dec.book_outcome(result)


# ── the approval door ──────────────────────────────────────────────────────────────────────

def decision_from_proposal(p, *, chosen: str, actor: str) -> str:
    """Book the decision an inbox resolution is: ``approve`` (accepted) or ``decline`` (rejected)."""
    from aughor.org.context import current_user_id
    decided_by = _person(current_user_id(), actor)
    src = _dec.Source(kind="approval", ref=p.id, detail=f"{p.kind} proposal for {p.action_id}")
    relied: list[str] = []
    source = str(p.source or "")
    if source.startswith("investigation:"):
        relied = relied_on_claims(p.connection_id, source.split(":", 1)[1])
    question = (f"{p.action_id}: {p.reasoning.strip()}" if (p.reasoning or "").strip()
                else f"arm {p.action_id} as proposed").strip()[:500]
    decision = _dec.Decision(
        question=question, owner=decided_by, options=list(_APPROVE_OPTIONS), chosen=chosen,
        relied_on=relied, decided_by=decided_by, actions=[p.action_id] if chosen == "approve" else [],
        source=src, connection_id=p.connection_id or "",
        extra={"proposal_kind": p.kind, "proposer": p.proposer, "proposal_source": source,
               **({"trace_id": p.trace_id} if p.trace_id else {}),
               "expectation_note": "none: a staged proposal carries no expectation line",
               # PENDING 57, D-1: the proposer recommended approving; a rejection is an override, counted
               "recommended": "approve"},
    )
    return _dec.book_decision(decision, author=decided_by)


# ── the declare door ───────────────────────────────────────────────────────────────────────

def declare_decision(*, question: str, chosen: str, options: Optional[list[str]] = None,
                     owner: str = "", approvers: Optional[list[str]] = None,
                     dissent: Optional[list[dict]] = None, relied_on: Optional[list[str]] = None,
                     objective: str = "", connection_id: str = "", decided_at: str = "",
                     decided_by: str = "", review_on: str = "", expectation: Optional[dict] = None,
                     note: str = "", finding_id: str = "", schema_name: str = "", run_id: str = "",
                     figure: Optional[dict] = None, kind: str = "", revises: str = "",
                     evidence: Optional[list[dict]] = None) -> str:
    """A decision taken elsewhere, declared in its own words. Refuses a relied-on id that is not a
    claim (a decision cites what the Record holds, never a loose string). The server cites what the decision was taken
    on: an Explorer finding's claim (``finding_id``), the claims a run's receipt booked
    (``run_id`` — a dashboard Question's answer, a chat answer), or a Briefing figure measured for its days and booked
    as a reading (``figure``: metric, start, end) — the decision-framework study §3.2 and §8 step 3."""
    if not (question or "").strip():
        raise ValueError("a decision states what was being decided")
    if not (chosen or "").strip():
        raise ValueError("a decision names what was chosen")
    revised = None
    if (revises or "").strip():
        # a modifying decision names the decision it changes; its inquiry reads backwards to it (study §3.1)
        revised = _dec.get_decision(revises.strip())
        if revised is None:
            raise ValueError(f"{revises!r} is not a decision in the Record; a decision revises one it can name")
    declared_kind = None
    if (kind or "").strip():
        # a decision of a declared kind keeps its kind's rules at the door (the decision-framework study §3.1)
        from aughor.record.kinds import rules_for
        declared_kind, approvers = rules_for(kind, expectation=expectation, approvers=approvers)
        if not review_on:
            when = _claims._as_dt(decided_at) if decided_at else None
            review_on, _why = _dec.propose_review_on(connection_id, when, default_days=declared_kind.review_days)
    cited: list[str] = []
    for cid in relied_on or []:
        if _claims.get(cid) is None:
            raise ValueError(f"{cid!r} is not a claim in the Record; a decision relies on claims it can cite")
        cited.append(cid)
    finding_note = ""
    if finding_id:
        # PENDING 57, D-1: a decision taken on a finding cites the finding's claim as it stands now; one the Record
        # does not hold is said on the decision, never guessed at.
        from aughor.record.writers import explorer_finding_claim
        claim, finding_note = explorer_finding_claim(connection_id, finding_id, schema_name)
        if claim is not None and claim.id not in cited:
            cited.append(claim.id)
    notes = [finding_note] if finding_note else []
    if run_id:
        ids = relied_on_claims(connection_id, run_id)
        cited += [c for c in ids if c not in cited]
        if not ids:
            notes.append(f"run {run_id} booked no claim — what it answered is not in the Record to cite")
    if figure:
        cid, why = reading_claim(connection_id, str(figure.get("metric") or ""), str(figure.get("start") or ""),
                                 str(figure.get("end") or ""))
        if cid and cid not in cited:
            cited.append(cid)
        if why:
            notes.append(why)
    finding_note = "; ".join(notes)
    opts = [_dec.Option(id=o, description=o) for o in (options or [])]
    if chosen not in {o.id for o in opts}:
        opts.append(_dec.Option(id=chosen, description=chosen))
    import uuid
    decision = _dec.Decision(
        question=question.strip()[:500], owner=owner or decided_by, approvers=list(approvers or []),
        options=opts, chosen=chosen, dissent=[_dec.Dissent(**d) for d in (dissent or [])],
        relied_on=cited, objective=objective or "", decided_at=decided_at or "",
        decided_by=decided_by or "unidentified", review_on=review_on or "",
        source=_dec.Source(kind="declared", ref=uuid.uuid4().hex[:12], detail=(note or "")[:400]),
        connection_id=connection_id or "", kind=declared_kind.key if declared_kind is not None else "",
        extra={**({"note": note} if note else {}),
               **({} if expectation else {"expectation_note": "none declared — nothing to score"}),
               **({"finding_id": finding_id} if finding_id else {}),
               **({"run_id": run_id} if run_id else {}),
               **({"figure": dict(figure)} if figure else {}),
               **({"revises": revised.id} if revised is not None else {}),
               # where it was taken — a conversation or a meeting, as a reference and a hash (study §3.2)
               **({"evidence": list(evidence)} if evidence else {}),
               **({"relied_on_note": finding_note} if finding_note else {})},
    )
    return _dec.book_decision(decision, expectation=expectation_from(expectation), author=decided_by)


def reading_claim(connection_id: str, metric: str, start: str, end: str, *, runner=None,
                  today: Optional[_dt.date] = None) -> tuple[Optional[str], str]:
    """A figure a person decided on, measured for its days by the metric's own compiler and booked as a *reading*
    with its own receipt — ``(claim id, "")``, or ``(None, why not)``. The page's number is never taken on trust: the
    decision relies on what the warehouse held for those days when it was decided (the decision-framework run: a
    query's figure could not be cited, so a decision taken on a Briefing figure cited nothing). ``end`` is exclusive."""
    from aughor.semantic import metric_time as mt
    from aughor.semantic.metrics import get_metric
    name = (metric or "").strip()
    if not (connection_id and name):
        return None, "no figure was named, so none was booked"
    m = get_metric(name, connection_id=connection_id)
    if m is None:
        return None, f"{name} is not a metric on this connection, so the figure was not booked"
    label = getattr(m, "label", None) or m.name
    ok, why = mt.measurable(m)
    if not ok:
        return None, f"{label} cannot be measured for a period ({why}), so the figure was not booked"
    try:
        s, e = _dt.date.fromisoformat(start[:10]), _dt.date.fromisoformat(end[:10])
    except ValueError:
        return None, f"the figure's days ({start} to {end}) are not dates, so it was not booked"
    if e <= s:
        return None, f"the figure's days end ({end}) before they start ({start}), so it was not booked"
    window = mt.Window("current", s, e)
    if runner is None:
        from aughor.knowledge.period_brief import connection_runner as runner
    with runner(connection_id) as (run_sql, dialect):
        sql, why = mt.measure_sql(m, [window], dialect=dialect)
        rows, why = mt.run_measure(m, [window], run_sql, dialect=dialect) if sql else ([], why)
    span = f"{s.isoformat()} to {window.last_day.isoformat()}"
    if why:
        return None, f"{label} could not be measured for {span}: {why}"
    got = rows[0] if rows else None
    if got is None or not got["n"] or got["value"] is None:
        return None, f"{span} holds no rows of {label}, so there was no figure to book"
    value = float(got["value"])
    from aughor.routers.investigations import write_answer_receipt
    written = write_answer_receipt(
        kind="chat_answer", natural_key=f"chat:{connection_id}:reading:{m.name}:{s.isoformat()}:{e.isoformat()}",
        question=f"{label}, {span}", sqls=[sql or ""], headline="", schema="", connection_id=connection_id,
        payload_extra={"reading": {"metric": m.name, "start": s.isoformat(), "end": e.isoformat(), "value": value},
                       "body": "decide.figure"})
    receipt = (written or {}).get("receipt_id")
    if not receipt:
        return None, f"{label} read {value:,.6g} for {span}, but its receipt could not be written, so it was not booked"
    lag = 0
    try:
        from aughor.settling.store import learned_lag_days
        lag = int(learned_lag_days(connection_id) or 0)
    except Exception:  # noqa: BLE001 — an unknown lag reads as provisional below, never as final
        lag = 0
    status = mt.figure_status(m, window, as_of=today or _dt.datetime.now(_dt.timezone.utc).date(), lag_days=lag)
    unit = getattr(m, "unit", None) or ""
    claim = _claims.Claim(
        kind="reading", tier="measured", about=_claims.About(kind="connection", key=connection_id),
        statement=_claims.Statement(text=f"{label} read {value:,.6g}{unit if unit == '%' else ''} for {span}",
                                    metric=m.name, value=value, unit=unit, range_start=s.isoformat(),
                                    range_end=e.isoformat()),
        status={"final": "Final", "to_date": "To date"}.get(status, "Provisional"), as_of=window.last_day.isoformat(),
        warrants=[_claims.Warrant(kind="run", ref=receipt, detail=(sql or "")[:400])],
        author="system", author_kind="system",
        extra={"rows": int(got["n"]), "booked_for": "a decision taken on this figure"})
    key = _claims.claim_key("reading", connection_id, m.name, s.isoformat(), e.isoformat())
    return _claims.book(claim, key=key, conn_id=connection_id), ""


# ── the decision not to act (PENDING 57, D-1) ───────────────────────────────────────────────

#: The two options a finding put on the table, as Home offers them.
ACT, NOT_ACT = "act on it", "not act"


def decision_not_to_act(*, connection_id: str, finding_id: str, finding_text: str, reason: str,
                        decided_by: str, schema_name: str = "") -> str:
    """Setting a finding aside as not worth acting on IS a decision — booked citing the finding, with the reason
    as said. Before, "Not worth it" flagged the finding and the choice was lost."""
    return declare_decision(
        question=(finding_text or f"finding {finding_id}").strip()[:500], chosen=NOT_ACT, options=[ACT, NOT_ACT],
        connection_id=connection_id, decided_by=decided_by,
        note=(reason or "").strip()[:400] or "set aside as not worth acting on",
        finding_id=finding_id, schema_name=schema_name)

