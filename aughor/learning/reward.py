"""TJ-3 — a run label that takes both values, from what the run already recorded (2026-09-26).

§3.47's premise: nothing attached a number to a live run — `earned_confidence` on 5 of 1,113
runs measured coverage, the decision corpus's outcome was `ok` on every row because it recorded
only that the tool did not raise, and no person labels a step. §3.9's law: reward integrity
precedes optimisation, and the verifier is hand-audited on real outputs first.

ONE function, deterministic, read by every tier the exporters name and by the trajectory's
`reward` block, so the training corpus and the few-shot memory cannot disagree about what
clean means:

* **positive** — every statement ran without error and returned rows, no guard fired except
  lint, the re-check (when one ran) found the number unchanged, and no person rejected it.
* **negative** — a statement failed, a fan-out or grain guard fired, the re-check found the
  number changed, or a person rejected it.
* **unlabeled** — everything else, and the default: a store that could not be read, a guard
  that only caveated, a statement that returned no rows, a run that ran nothing. Never `ok`.

The headline-against-rows contradiction §3.47 names is not recorded on a chat answer today;
the label says so in its evidence (`contradiction: None`) rather than guessing. What comes
back is the label AND its reasons — the audit sheet reads both.
"""
from __future__ import annotations

import re
from typing import Any, Optional

POSITIVE, NEGATIVE, UNLABELED = "positive", "negative", "unlabeled"
LABELS = (POSITIVE, NEGATIVE, UNLABELED)

#: A guard whose fire makes the run negative, by the name the guard registered under.
_BLOCKING = re.compile(r"fan.?out|grain", re.I)
#: The one guard whose fire does not disqualify a positive run.
_LINT = re.compile(r"^lint", re.I)
_REJECT = {"reject", "rejected", "wrong", "incorrect"}


def _fires(guards: list) -> tuple[list[dict], list[dict]]:
    """``(fired, unknown)``: the guard rows that WARNED — the same actions the envelope calls a
    warning — lint aside, and the rows whose action was never recorded (a verdict row from
    before audit migration 4, or a phase that carries none): not a fire, not clean either."""
    from aughor.answer.envelope import WARNING_ACTIONS
    fired, unknown = [], []
    for g in guards:
        if not isinstance(g, dict):
            continue
        pattern = str(g.get("pattern") or "")
        action = str(g.get("action") or "")
        if _LINT.search(pattern):
            continue
        if not action:
            unknown.append(g)
        elif action in WARNING_ACTIONS:
            fired.append(g)
    return fired, unknown


def run_label(trajectory: dict) -> dict:
    """``{"label", "reasons", "evidence"}`` for one run's trajectory (`obs.trajectory.trajectory_of`
    or any dict carrying ``executions``, ``guards`` and ``answers``)."""
    t = trajectory or {}
    executions, guards, answers = t.get("executions"), t.get("guards"), t.get("answers")
    reasons: list[str] = []
    negative: list[str] = []
    evidence: dict[str, Any] = {"execution": None, "rows": None, "guard_fires": [], "recheck": None,
                                "human_verdict": None, "contradiction": None}

    if not isinstance(executions, list):
        reasons.append("the execution store could not be read")
    elif not executions:
        evidence["execution"] = "none"
        reasons.append("no statement ran")
    else:
        failed = [x for x in executions if x.get("error")]
        evidence["execution"] = "error" if failed else "ok"
        counts = [x.get("row_count") for x in executions]
        evidence["rows"] = sum(int(c or 0) for c in counts if isinstance(c, (int, float)))
        if failed:
            negative.append(f"a statement failed: {str(failed[0].get('error'))[:120]}")
        elif any((c is None) or int(c or 0) <= 0 for c in counts):
            reasons.append("a statement returned no rows")

    if not isinstance(guards, list):
        reasons.append("the guard store could not be read")
    else:
        fires, unknown = _fires(guards)
        evidence["guard_fires"] = [f"{g.get('pattern')}:{g.get('action')}" for g in fires]
        blocking = [g for g in fires if _BLOCKING.search(str(g.get("pattern") or ""))]
        if blocking:
            negative.append(f"a {blocking[0].get('pattern')} guard fired")
        elif fires:
            reasons.append(f"a guard fired: {fires[0].get('pattern')}")
        if unknown:
            reasons.append(f"a guard's action was not recorded: {unknown[0].get('pattern')}")

    human: Optional[str] = None
    recheck: Optional[str] = None
    if isinstance(answers, list):
        for a in answers:
            v = a.get("verdict") if isinstance(a, dict) else None
            if isinstance(v, dict) and v.get("verdict"):
                human = str(v["verdict"])
            rechecks = a.get("rechecks") if isinstance(a, dict) else None
            if isinstance(rechecks, list) and rechecks:
                last = rechecks[-1]
                recheck = str(last.get("status")) if isinstance(last, dict) else None
    evidence["human_verdict"], evidence["recheck"] = human, recheck
    if human and human.lower() in _REJECT:
        negative.append("a person rejected it")
    if recheck == "changed":
        negative.append("the re-check found the number changed")

    if negative:
        return {"label": NEGATIVE, "reasons": negative, "evidence": evidence}
    if reasons:
        return {"label": UNLABELED, "reasons": reasons, "evidence": evidence}
    return {"label": POSITIVE, "reasons": ["ran without error, returned rows, no guard but lint fired, "
                                           "the re-check found it unchanged or did not run, nobody rejected it"],
            "evidence": evidence}


def label_of_trace(trace_id: str) -> dict:
    """The label for a recorded run, by its trace; unlabeled with the reason when the run has
    no readable trajectory."""
    from aughor.obs.trajectory import trajectory_of
    t = trajectory_of(str(trace_id or "")) if trace_id else None
    if t is None:
        return {"label": UNLABELED, "reasons": ["no trajectory was recorded for this run"], "evidence": {}}
    return run_label(t)


def distribution(labels: list[dict]) -> dict:
    """Counts per label, and whether the label discriminates on this traffic (§3.47's falsifier:
    a constant label is a finding, not a dataset)."""
    counts = {k: 0 for k in LABELS}
    reasons: dict[str, int] = {}
    for r in labels:
        counts[r.get("label", UNLABELED)] = counts.get(r.get("label", UNLABELED), 0) + 1
        for why in r.get("reasons") or []:
            key = why.split(":")[0][:80]
            reasons[key] = reasons.get(key, 0) + 1
    n = sum(counts.values())
    taken = [k for k, v in counts.items() if v]
    return {"n": n, "counts": counts, "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
            "discriminating": len(taken) >= 2}
