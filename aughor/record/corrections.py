"""Corrections — what the platform was wrong about, as a first-class view (the 2027 study §N;
phase 5, P5-3).

The system must remember what it was wrong about, and show it under one heading rather than
bury it in history. Five records, each already in the ledger, read here through one door:

1. **Restatements** — a number it gave that later changed: a claim with a newer version under its
   key (`record/claims.restate`, written by the daily re-check and the review), shown with what was
   first said and what replaced it.
2. **Refuted hypotheses** — what it thought the cause was and tested false: a hypothesis claim in
   state ``refuted``, with the evidence the run recorded. Memory the next inquiry reads.
3. **Missed moves** — something a person found by asking that nothing had flagged: the review of a
   missed move (`monitors/missed.py`, idea 8) books a ``missed_move`` entry when its verdict is that
   a watch should have caught it and none did.
4. **Predictions outside their interval** — a scored prediction whose actual fell above or below its
   band (`record/scenario.score_prediction`).
5. **Decisions that went worse than expected** — an Outcome whose verdict is ``worse``, with the
   decision's question and what was expected.

Nothing here is a second store: every entry is a kernel artifact read back by kind and state, and
each row says what was believed and what replaced it. An empty kind is a count of zero, said.
"""
from __future__ import annotations

from typing import Any, Optional

from aughor.record import claims as _claims
from aughor.record import decisions as _dec

MISSED_MOVE_KIND = "missed_move"
KINDS: tuple[str, ...] = ("restatement", "refuted_hypothesis", "missed_move", "prediction_outside_interval",
                          "decision_worse_than_expected")
LABELS: dict[str, str] = {
    "restatement": "a number we gave later changed",
    "refuted_hypothesis": "a cause we thought likely tested false",
    "missed_move": "a move a person found that nothing flagged",
    "prediction_outside_interval": "a prediction whose actual fell outside its band",
    "decision_worse_than_expected": "a decision that went worse than expected",
}


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _conn_of(c: _claims.Claim) -> str:
    return c.about.key if c.about.kind == "connection" else ""


def restatements(*, conn_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    out = []
    for c in _claims.list_claims(conn_id=conn_id, limit=max(limit * 4, 400)):
        if not c.supersedes:
            continue
        prior = _claims.get(c.supersedes)
        out.append({"kind": "restatement", "at": c.recorded_at, "connection_id": _conn_of(c), "ref": c.id,
                    "claim_kind": c.kind, "believed": prior.statement.text if prior else "(the earlier version could not be read)",
                    "replaced_by": c.statement.text, "believed_as_of": prior.as_of if prior else "",
                    "replaced_as_of": c.as_of, "why": str(c.extra.get("cause") or c.extra.get("restated_by") or "restated"),
                    "superseded": c.supersedes})
        if len(out) >= limit:
            break
    return out


def refuted_hypotheses(*, conn_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    out = []
    for c in _claims.list_claims(kind="hypothesis", state="refuted", conn_id=conn_id, limit=limit):
        out.append({"kind": "refuted_hypothesis", "at": c.recorded_at, "connection_id": _conn_of(c), "ref": c.id,
                    "believed": c.statement.text, "replaced_by": str(c.extra.get("evidence") or "refuted by the run; no evidence text recorded"),
                    "run": str(c.extra.get("run") or ""), "inquiry": str(c.extra.get("inquiry") or ""),
                    "why": "tested false by the run that refuted it"})
    return out


def missed_moves(*, conn_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    out = []
    for art in _ledger().artifacts_of_kind(MISSED_MOVE_KIND, conn_id=conn_id, limit=limit):
        p = dict(art.get("payload") or {})
        out.append({"kind": "missed_move", "at": str(art.get("created_at") or ""), "connection_id": str(p.get("connection_id") or ""),
                    "ref": str(art.get("id") or ""), "believed": f"nothing on {p.get('metric')} needed flagging on {p.get('day')}",
                    "replaced_by": str(p.get("verdict") or ""), "metric": p.get("metric"), "day": p.get("day"),
                    "z": p.get("z"), "watches": len(p.get("watches") or []), "proposal": p.get("proposal") or {},
                    "why": "a person found the move by asking"})
    return out


def predictions_outside_interval(*, conn_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    out = []
    for c in _claims.list_claims(kind="prediction", state="scored", conn_id=conn_id, limit=max(limit * 4, 400)):
        against = str(c.extra.get("scored_against") or "")
        if against not in ("above", "below"):
            continue
        out.append({"kind": "prediction_outside_interval", "at": c.recorded_at, "connection_id": _conn_of(c), "ref": c.id,
                    "believed": c.statement.text, "replaced_by": f"the actual was {c.extra.get('actual')}: {against} the band",
                    "metric": c.statement.metric, "method": str(c.extra.get("method") or ""), "author": c.author,
                    "against": against, "low": c.extra.get("low"), "high": c.extra.get("high"), "actual": c.extra.get("actual"),
                    "why": "scored by code when its range was Final"})
        if len(out) >= limit:
            break
    return out


def decisions_worse_than_expected(*, conn_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    out = []
    for art in _ledger().artifacts_of_kind(_dec.OUTCOME_KIND, conn_id=conn_id, limit=max(limit * 4, 400)):
        p = dict(art.get("payload") or {})
        if p.get("verdict") != "worse":
            continue
        d = _dec.get_decision(str(p.get("of") or ""))
        expected = ""
        if d is not None and d.expectation_claim:
            pred = _claims.get(d.expectation_claim)
            expected = pred.statement.text if pred else ""
        out.append({"kind": "decision_worse_than_expected", "at": str(art.get("created_at") or ""),
                    "connection_id": d.connection_id if d else "", "ref": str(art.get("id") or ""),
                    "decision": d.id if d else str(p.get("of") or ""),
                    "believed": (f"{d.question} → {d.chosen}" if d else "(the decision could not be read)") + (f"; {expected}" if expected else ""),
                    "replaced_by": str(p.get("why") or "worse than expected"), "actual": p.get("actual"), "baseline": p.get("baseline"),
                    "against_expectation": str(p.get("against_expectation") or ""), "measured_on": str(p.get("measured_on") or ""),
                    "why": "measured on the review date against the expectation and the metric's own history"})
        if len(out) >= limit:
            break
    return out


_READERS = {"restatement": restatements, "refuted_hypothesis": refuted_hypotheses, "missed_move": missed_moves,
            "prediction_outside_interval": predictions_outside_interval,
            "decision_worse_than_expected": decisions_worse_than_expected}


def corrections(*, conn_id: Optional[str] = None, kind: Optional[str] = None, limit: int = 100) -> dict[str, Any]:
    """The view: counts by kind and the entries, newest first, each with what was believed and what
    replaced it. ``kind`` narrows to one of :data:`KINDS`; an unknown kind is refused by name."""
    if kind and kind not in KINDS:
        raise ValueError(f"no correction kind named {kind!r}; the kinds are {', '.join(KINDS)}")
    counts: dict[str, int] = {}
    entries: list[dict] = []
    for k in KINDS:
        rows = _READERS[k](conn_id=conn_id, limit=limit)
        counts[k] = len(rows)
        if not kind or kind == k:
            entries.extend(rows)
    entries.sort(key=lambda e: str(e.get("at") or ""), reverse=True)
    return {"counts": counts, "labels": dict(LABELS), "entries": entries[:limit],
            "note": "every entry is a ledger record read back by kind; a kind with 0 has none recorded, not none that happened"}
