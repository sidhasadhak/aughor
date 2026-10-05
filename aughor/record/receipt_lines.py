"""The two lines the Trust Receipt gains from the Record (the 2027 study §F "line two"; phase 1,
P1-5): how often answers of this kind have held, counted, and who else was told.

Read live from the Record and the departures ledger when the receipt is served, so the receipt
of an answer given in March shows the count as it stands today — a receipt is rebuilt and
re-signed on every read by design (`trust/receipt.py`). Pure projection over two stores; never
raises into the receipt (the receipt stands without these lines, and says so).
"""
from __future__ import annotations

from typing import Any, Optional

from aughor.record import claims as _claims
from aughor.record.writers import observation_key


def _told(investigation_id: str) -> list[dict]:
    from aughor.govern.departure_store import decode_row, departures_for
    out = []
    for row in departures_for(investigation_id=investigation_id, limit=50):
        r = decode_row(row)
        out.append({"at": r.get("ts", ""), "state": r.get("state", ""), "kind": r.get("kind", ""),
                    "target": r.get("target", ""), "addressed_to": r.get("addressed_to", ""),
                    "by": r.get("automation_name") or r.get("actor") or "",
                    "verdict": r.get("verdict", ""), "departure_id": r.get("id", "")})
    return out


def told_about(claim: _claims.Claim) -> tuple[list[dict], str]:
    """``(told, note)`` for a claim's own page (the study §V, screen 9): every gate decision on a
    message that cited the answer this claim came from. The departures ledger is keyed by the
    answer a message cites, so a claim with no answer behind it — a declared term, a pack's
    prior — has nothing to read, and the note says that rather than "nobody"."""
    # an answer's observation and a deep run's findings carry `investigation_id`; a hypothesis, `run`
    answers: list[str] = []
    for field in ("investigation_id", "run"):
        v = str(claim.extra.get(field) or "")
        if v and v not in answers:
            answers.append(v)
    if not answers:
        return [], "this claim did not come from an answer, and the gate records a message by the answer it cites — nothing can be read for it"
    told: list[dict] = []
    for inv_id in answers:
        told += _told(inv_id)
    told.sort(key=lambda t: str(t.get("at") or ""), reverse=True)
    return told, ("" if told else "no message citing the answer behind this claim has passed the departure gate")


def record_lines(raw: dict) -> Optional[dict]:
    """``{"answer", "claim", "confidence", "confidence_note", "told", "told_note"}`` for a raw ledger receipt
    (`{artifact, lineage, …}`), or None when the artifact is not an answer's receipt."""
    art = (raw or {}).get("artifact") or {}
    if not art:
        return None
    conn_id = str(art.get("conn_id") or "")
    natural_key = str(art.get("natural_key") or "")
    payload = art.get("payload") if isinstance(art.get("payload"), dict) else {}
    inv_id = str(payload.get("investigation_id") or (natural_key.rsplit(":", 1)[-1] if natural_key else ""))
    # `answer` is the run this receipt is for — what "Re-perform" re-runs (screen 10 of the study).
    out: dict[str, Any] = {"answer": inv_id, "claim": None, "confidence": None, "confidence_note": "",
                           "told": [], "told_note": ""}
    try:
        claim = _claims.latest(observation_key(conn_id, inv_id)) if (conn_id and inv_id) else None
        if claim is None:
            out["confidence_note"] = ("this answer booked no claim in the Record (it concluded nothing with a "
                                      "query behind it, or predates the Record), so nothing is counted for it")
        else:
            from aughor.record.confidence import counted, why_uncounted
            conf = counted(claim)
            out["claim"] = {"id": claim.id, "key": claim.key, "version": claim.version, "tier": claim.tier,
                            "kind": claim.kind, "as_of": claim.as_of, "recorded_at": claim.recorded_at,
                            "restated": claim.version > 1,
                            "warrants_this_receipt": any(w.kind == "run" and w.ref == art.get("id")
                                                         for w in claim.warrants)}
            out["confidence"] = conf.model_dump() if conf is not None else None
            out["confidence_note"] = why_uncounted(claim) if conf is None else ""
    except Exception as exc:  # noqa: BLE001 — the receipt stands without the count
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the receipt's counted confidence could not be read", counter="receipt.record_confidence")
        out["confidence_note"] = "the count could not be read just now"
    try:
        out["told"] = _told(inv_id) if inv_id else []
        if not out["told"]:
            out["told_note"] = "no message citing this answer has passed the departure gate"
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the receipt's departures could not be read", counter="receipt.record_told")
        out["told_note"] = "the departures ledger could not be read just now"
    return out
