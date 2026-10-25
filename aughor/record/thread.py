"""The thread — one decision point read from where it arose to its last consequence, forwards and backwards (the
decision-framework study §3.1 and §3.3, `docs/DECISION_FRAMEWORK_STUDY_2026-10-26.md`).

The user asked for *"an advanced decision flow — forwards & backwards with loops where every decision and their 'why'
is readable if the user wishes to"*. The thread is that reader. It is a VIEW over what the Record already holds — the
inquiry a decision came out of, the claims it relied on as they stood, its options and dissent, who decided and who
approved, what ran under it, its outcome against what would have happened anyway, what was learned, and the loops —
never a new store, as Belief and Memory are views in the model.

Seven stages, in the study's words: ARISING · GATHERING · OPTIONS · DECIDED · ACTING · REVIEWED · LEARNED; and the
loops: a relied-on claim restated reopens the decision; an outcome becomes a past case for the next decision of its
kind; a decision that revises another is read backwards to the reasoning it changed, and the older one forwards to
what changed it.

**The why, in three layers, composed by code from fields** — never from a model's narrative: ``line`` (the verdict or
the state, a few words), ``why`` (one sentence), and ``receipt`` (the ids, the numbers, the versions). A reader opens
each layer by choice. A stage with nothing in it says so; nothing is implied by absence.
"""
from __future__ import annotations

from typing import Any, Optional

from aughor.record import claims as _claims
from aughor.record import decisions as _dec

STAGES: tuple[str, ...] = ("arising", "gathering", "options", "decided", "acting", "reviewed", "learned")
STAGE_WORDS: dict[str, str] = {
    "arising": "Where it arose", "gathering": "What it stood on", "options": "The options", "decided": "Decided",
    "acting": "What ran under it", "reviewed": "Reviewed", "learned": "What was learned",
}
_SOURCE_WORDS = {"declared": "declared in a sentence", "recommendation": "by accepting a recommendation",
                 "approval": "by approving an action", "reply": "by a reply"}


def _step(kind: str, line: str, why: str = "", receipt: Optional[dict] = None, *, at: str = "", ref: str = "") -> dict:
    return {"kind": kind, "line": line, "why": why, "receipt": {k: v for k, v in (receipt or {}).items() if v not in (None, "", [], {})},
            "at": (at or "")[:10], "ref": ref}


def _claim_step(c: _claims.Claim, *, kind: str = "claim") -> dict:
    now = _claims.latest(c.key) if c.key else None
    since = ""
    if now is not None and now.id != c.id and (now.statement.text, now.statement.value) != (c.statement.text, c.statement.value):
        since = f"; since restated as “{now.statement.text[:200]}”"
    warrants = [f"{w.kind} {w.ref}" for w in c.warrants]
    return _step(kind, f"{c.kind} · {c.tier}", f"“{c.statement.text[:300]}” as of {c.as_of or 'an unstated day'}{since}",
                 {"claim": c.id, "warrants": warrants, "value": c.statement.value, "metric": c.statement.metric,
                  "restated_as": now.id if since and now is not None else ""},
                 at=c.recorded_at, ref=c.id)


def resolve(ref: str) -> Optional[_dec.Decision]:
    """The decision a reference reads as: a decision's id (any version — read as it stands now), a claim it relied on
    (the latest decision citing it), or an inquiry (the latest decision it led to)."""
    ref = (ref or "").strip()
    if not ref:
        return None
    d = _dec.get_decision(ref)
    if d is not None:
        return _dec.latest_decision(d.source) or d
    c = _claims.get(ref)
    if c is not None:
        citing = [x for x in _dec.list_decisions(limit=2000) if ref in x.relied_on]
        return citing[0] if citing else None
    from aughor.record.inquiry import get_inquiry
    q = get_inquiry(ref)
    if q is not None and q.decisions:
        d = _dec.get_decision(q.decisions[-1])
        return (_dec.latest_decision(d.source) or d) if d is not None else None
    return None


def _inquiry_of(d: _dec.Decision) -> Any:
    """The inquiry the decision came out of: one that lists it, ran the answer it was taken on, or established a
    claim it relied on."""
    from aughor.record.inquiry import for_run, list_inquiries
    run = str(d.extra.get("run_id") or d.extra.get("investigation_id") or "")
    if run:
        q = for_run(run, conn_id=d.connection_id or None)
        if q is not None:
            return q
    ids = set(_dec.version_ids(d.id) or [d.id])
    for q in list_inquiries(conn_id=d.connection_id or None, limit=500):
        if ids & set(q.decisions) or set(d.relied_on) & set(q.claims):
            return q
    return None


def thread_of(ref: str) -> Optional[dict]:
    """The thread of the decision ``ref`` reads as, stage by stage, with its loops and the decisions read backwards
    and forwards from it. None when ``ref`` reads as no decision."""
    d = resolve(ref)
    if d is None:
        return None
    stages: dict[str, list[dict]] = {s: [] for s in STAGES}
    # ARISING — where it came from
    q = _inquiry_of(d)
    if q is not None:
        stages["arising"].append(_step("inquiry", f"an inquiry · {q.state}",
                                       f"“{q.question[:240]}”, opened by {q.opened_by or 'someone unrecorded'}",
                                       {"inquiry": q.id, "runs": [r.run for r in q.runs]}, at=q.opened_at, ref=q.id))
    origin = [("finding_id", "a finding on Home"), ("run_id", "an answer"), ("figure", "a Briefing figure")]
    for key, words in origin:
        if d.extra.get(key):
            stages["arising"].append(_step("door", f"decided on {words}", str(d.extra.get("note") or ""),
                                           {key: d.extra.get(key)}))
    for e in d.extra.get("evidence") or []:
        where = {"conversation": "said in a conversation", "meeting": "taken in a meeting"}.get(str(e.get("kind")), "evidence")
        stages["arising"].append(_step(str(e.get("kind") or "evidence"), where,
                                       str(e.get("detail") or e.get("ref") or ""),
                                       {"ref": e.get("ref"), "content_hash": e.get("content_hash"), "excerpt": e.get("excerpt")}))
    if d.objective:
        from aughor.record import mission as M
        m = M.get_mission(d.objective) or (M.latest(d.objective) if d.objective.startswith("mission:") else None)
        stages["arising"].append(_step("mission", "under a mission",
                                       f"toward “{m.name}”" if m is not None else f"toward {d.objective}",
                                       {"mission": m.id if m is not None else d.objective}, ref=m.id if m is not None else ""))
    if d.extra.get("revises"):
        stages["arising"].append(_step("revises", "revises an earlier decision",
                                       "a modifying decision: read backwards for the reasoning it changes",
                                       {"decision": d.extra.get("revises")}, ref=str(d.extra.get("revises"))))
    if not stages["arising"]:
        stages["arising"].append(_step("door", _SOURCE_WORDS.get(d.source.kind, d.source.kind),
                                       str(d.source.detail or d.extra.get("note") or "nothing recorded about where it arose")))
    # GATHERING — the claims it relied on, as they stood
    for cid in d.relied_on:
        c = _claims.get(cid)
        stages["gathering"].append(_claim_step(c) if c is not None else
                                   _step("claim", "a claim that cannot be read", f"{cid} is not in the Record", ref=cid))
    if not d.relied_on:
        stages["gathering"].append(_step("none", "it cites nothing",
                                         str(d.extra.get("relied_on_note") or "no claim was cited when it was booked")))
    # OPTIONS — what was on the table, what was added later, who disagreed
    added = {(a.get("kind"), a.get("what")) for a in (d.extra.get("amendments") or [])}
    for o in d.options:
        later = ("option", o.id[:200]) in added
        stages["options"].append(_step("option", ("chosen" if o.id == d.chosen else "not chosen")
                                       + (" · added later" if later else ""), o.description, ref=o.id))
    for x in d.dissent:
        stages["options"].append(_step("dissent", f"dissent · {x.who}", x.why))
    if d.kind:
        stages["options"].append(_step("kind", f"a declared kind · {d.kind.split(':', 1)[-1].replace('_', ' ')}",
                                       "its rules held at the door; past decisions of this kind are its base rate",
                                       {"kind": d.kind}))
    # DECIDED — who, when, approved by whom, what was expected
    versions = _dec.version_ids(d.id) or [d.id]
    stages["decided"].append(_step("decision", f"decided by {d.decided_by or 'nobody identified'}",
                                   f"chose “{d.chosen}” on {d.decided_at[:10] or 'an unrecorded day'}"
                                   + (f"; approvers named: {', '.join(d.approvers)}" if d.approvers else ""),
                                   {"decision": d.id, "versions": len(versions)}, at=d.decided_at, ref=d.id))
    for a in d.extra.get("approvals") or []:
        stages["decided"].append(_step("approval", f"approved by {a.get('by')}",
                                       f"in {a.get('where') or 'an unrecorded place'}"
                                       + ("" if a.get("named") or not d.approvers else " — not one of the named approvers"),
                                       {"ref": a.get("ref")}, at=str(a.get("at") or "")))
    pred = _claims.get(d.expectation_claim) if d.expectation_claim else None
    if pred is not None:
        stages["decided"].append(_step("expectation", "expected",
                                       pred.statement.text, {"claim": pred.id, "direction": pred.extra.get("direction"),
                                                             "low": pred.extra.get("low"), "high": pred.extra.get("high")},
                                       ref=pred.id))
    else:
        stages["decided"].append(_step("expectation", "nothing expected",
                                       str(d.extra.get("expectation_note") or "nothing was expected, so it cannot be scored")))
    # ACTING — what ran under it
    for a in d.actions:
        stages["acting"].append(_step("action", "an action ran under it", a, {"action": a}, ref=a))
    try:
        from aughor.record.scenario import scenarios_for
        for s in [s for vid in versions for s in scenarios_for(vid)]:
            stages["acting"].append(_step("scenario", "a scenario projected for it",
                                          s.question or "its assumptions and predictions, by method",
                                          {"scenario": s.id, "methods": list(s.methods), "predictions": list(s.predictions)},
                                          ref=s.id))
    except Exception as exc:  # noqa: BLE001 — a thread reads what it can; an unreadable scenario store is said below
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the thread could not read the decision's scenarios", counter="record.thread")
    if not stages["acting"]:
        stages["acting"].append(_step("none", "nothing recorded as run under it",
                                      "no declared action or scenario names this decision"))
    # REVIEWED — the outcome against what would have happened anyway
    o = _dec.outcome_by_id(d.outcome) if d.outcome else None
    if o is not None:
        stages["reviewed"].append(_step("outcome", o.verdict.replace("_", " "), o.why,
                                        {"outcome": o.id, "actual": o.actual, "baseline": o.baseline,
                                         "effect": o.effect.value, "effect_low": o.effect.low,
                                         "effect_high": o.effect.high, "method": o.effect.method,
                                         "against_expectation": o.against_expectation,
                                         "window": o.extra.get("review_window"), "measured_by": o.measured_by},
                                        at=o.measured_on, ref=o.id))
    else:
        why = str(d.extra.get("review_on_why") or "")
        stages["reviewed"].append(_step("due", f"review on {d.review_on or 'no date set'}",
                                        why or "not reviewed yet"))
    # LEARNED — what the outcome taught, and the loops
    loops: list[dict] = []
    if pred is not None:
        scored = _claims.latest(pred.key)
        if scored is not None and scored.state == "scored":
            stages["learned"].append(_step("scored", f"the expectation scored {scored.extra.get('scored_against')}",
                                           f"its author, {scored.author}, is counted in the Record's calibration",
                                           {"claim": scored.id}, ref=scored.id))
    if d.kind and o is not None:
        stages["learned"].append(_step("base_rate", "a past case for its kind",
                                       "the next decision of this kind reads this outcome as one of its cases (method 4)",
                                       {"kind": d.kind}))
    if q is not None:
        for lesson in q.lessons:
            stages["learned"].append(_step("lesson", "a lesson", f"believed “{lesson.believed}”; it turned out "
                                                                 f"“{lesson.turned_out}”", {"inquiry": q.id}))
    for r in d.extra.get("reopened") or []:
        loops.append(_step("reopened", "reopened: a claim it stood on moved",
                           str(r.get("why") or "a relied-on claim was restated")
                           + (f"; settled by {r.get('settled_by')}: {r.get('settled_why')}" if r.get("settled_at") else
                              "; waiting for a person's answer"),
                           {"restated_as": r.get("restated_as") or r.get("claim")}, at=str(r.get("at") or "")))
    if not stages["learned"]:
        stages["learned"].append(_step("none", "nothing learned yet",
                                       "a reviewed outcome, a scored expectation or an inquiry's lesson is learned here"))
    # BACKWARDS and FORWARDS — the decisions it revises, and those that revised it
    backwards = []
    if d.extra.get("revises"):
        older = _dec.get_decision(str(d.extra["revises"]))
        if older is not None:
            backwards.append({"decision": older.id, "question": older.question[:200], "chosen": older.chosen,
                              "decided_at": older.decided_at[:10], "why": "this decision revises it"})
    ids = set(versions)
    forwards = [{"decision": x.id, "question": x.question[:200], "chosen": x.chosen, "decided_at": x.decided_at[:10],
                 "why": "revises this decision"}
                for x in _dec.list_decisions(conn_id=d.connection_id or None, limit=2000)
                if str(x.extra.get("revises") or "") in ids]
    return {
        "decision": d.id, "question": d.question, "connection_id": d.connection_id,
        "stages": [{"stage": s, "words": STAGE_WORDS[s], "steps": stages[s]} for s in STAGES],
        "loops": loops, "backwards": backwards, "forwards": forwards,
        "composed_by": "code, from the Record's own fields — no model",
    }
