"""HB-5 — arrivals from people: a sentence in Slack becomes a NOTE on the object it is
about, with provenance, through customs (§3.18).

The thread→object link HB-3 filed is what makes this deterministic: a reply lands in a
thread whose root the platform posted and FILED on a securable, so the reply is about
that securable — no model decides. Customs, in order: the text is capped and
control-stripped (`prompt_safety`), PII is redacted (`security/pii`), and the result is
STAGED as an object note under `agent_notes`' blast-radius law — an arrival never
applies, never executes, never stages an act. The falsifier is a red-team corpus:
injected instructions land as data, never as acts (`test_hb5_arrival_redteam.py`).

The email direction stays closed (§6 item 24 f — keyed on the Google OAuth client only
the user can create); Jira/Confluence state arrives through the allowlisted MCP
consumer, no connector code here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from aughor.security.authz import connection_owner_guard

#: DATA-06 — every connection a door of this router names belongs to the caller's org.
router = APIRouter(tags=["arrivals"], dependencies=[Depends(connection_owner_guard)])

#: An arrival sentence is a note, not a document: capped hard, like a note is.
MAX_ARRIVAL_CHARS = 500


class SlackArrival(BaseModel):
    channel: str            # Slack channel id the reply was seen in
    thread_ts: str          # the THREAD ROOT's ts — what HB-3 filed as the link ref
    text: str
    author: str = ""        # display name, best-effort ("Ana")
    author_ref: str = ""    # principal-ish ref when known ("slack:U123")
    reply_ts: str = ""      # the REPLY's own ts when the bot sends it — one claim per reply in the Record


@router.post("/arrivals/slack")
def slack_arrival(body: SlackArrival):
    """One inbound thread reply → a staged note on the filed object, with provenance.

    404 when the thread is not filed on anything — an unfiled thread is ordinary
    conversation, and inventing an object for it would be a model's guess."""
    channel = body.channel.strip()
    thread_ts = body.thread_ts.strip()
    if not channel or not thread_ts:
        raise HTTPException(status_code=422, detail="channel and thread_ts are required")

    from aughor.hub.links import list_links
    ref = f"{channel}:{thread_ts}"
    filed = [ln for ln in list_links(kind="thread", limit=500) if ln.get("ref") == ref]
    if not filed:
        raise HTTPException(
            status_code=404,
            detail=f"thread {ref} is not filed on any object — nothing to note")
    link = filed[0]

    # Customs: cap + strip control characters, then redact PII. The text that survives
    # is DATA — it is stored as a note's words, never interpreted.
    from aughor.security.pii import redact_text
    from aughor.util.prompt_safety import sanitize_db_text
    text = sanitize_db_text(body.text or "")[:MAX_ARRIVAL_CHARS].strip()
    if not text:
        raise HTTPException(status_code=422, detail="the reply carried no usable text")
    text = redact_text(text)

    from aughor.util.time import now_iso_z
    provenance = {
        "source_kind": "conversation",
        "authority": "said",
        "author": sanitize_db_text(body.author or "")[:80] or (body.author_ref or "someone"),
        "author_kind": "person",
        "where": f"#{channel}" if not channel.startswith("#") else channel,
        "observed_at": now_iso_z(),
        "verification": "unverified",
        "thread": ref,
    }

    from aughor.ontology.agent_notes import propose_note
    conn_id = str((link.get("metrics_at_filing") or {}).get("connection_id") or "")
    outcome = propose_note(
        conn_id or "unknown", "arrivals",
        target="object", table=str(link["object_ref"]),
        note=text,
        evidence=f"said in Slack thread {ref}"
                 + (f" by {provenance['author']}" if body.author else ""),
        confidence="low",
        provenance=provenance)
    if not outcome.ok:
        raise HTTPException(status_code=422, detail=outcome.reason)
    # CB-8 — said versus measured: the numbers this reply states, checked against the measures the
    # thread was filed with. Agreement raises the note to `measured`; disagreement writes the owner's
    # question; no number or nothing measured stays `unchecked`. Recorded on the staged note.
    check = None
    try:
        from aughor.hub.claims import check_claim
        check = check_claim(text, str(link["object_ref"]), conn_id, measures=link.get("metrics_at_filing") or None)
        provenance["verification"] = check.verification
        if check.verification == "measured":
            provenance["authority"] = "measured"
        from aughor.ontology.recommendations import get_recommendation, save_recommendation
        rec = get_recommendation(conn_id or "unknown", "arrivals", outcome.recommendation_id) if outcome.recommendation_id else None
        if rec is not None:
            fields = dict(rec.proposed_fields or {})
            fields["check"] = check.to_dict()
            fields["provenance"] = dict(provenance)
            rec.proposed_fields = fields
            save_recommendation(conn_id or "unknown", "arrivals", rec)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the claim check is best-effort; the note is staged unchecked", counter="claims.check")
    # The hub writer (the 2027 study §E, the last of the five shapes): what was said is a SAID claim
    # in the Record, one per reply — a second reply on the same object is counted beside the first,
    # never over it (the staged note above still shows the latest check). Best-effort.
    claim_id = None
    try:
        from aughor.record.writers import book_said_claim, reply_id_for
        claim_id = book_said_claim(
            text=text, object_ref=str(link["object_ref"]), connection_id=conn_id,
            reply_id=reply_id_for(reply_ts=body.reply_ts.strip(), author_ref=body.author_ref, author=body.author, text=text),
            check=check.to_dict() if check is not None else {"verification": "unchecked", "note": "the check did not run"},
            author=provenance["author"], author_ref=body.author_ref, thread_ref=ref, observed_at=provenance["observed_at"])
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the said claim could not be booked into the Record; the staged note stands", counter="record.said_claim")
    return {"action": outcome.action, "object_ref": link["object_ref"],
            "recommendation_id": outcome.recommendation_id,
            "note": text, "provenance": provenance,
            "check": check.to_dict() if check is not None else None,
            "claim": claim_id,
            "why": outcome.reason}


#: What was decided, as said: a sentence, capped like a decision's question is.
MAX_DECISION_CHARS = 500


class SlackDecision(BaseModel):
    channel: str
    thread_ts: str
    text: str                   # what was decided, as written after `decide:`
    question: str = ""          # what was being decided: the question the thread's answer was to
    investigation_id: str = ""  # the answer's run — its claims are what the decision cites
    connection_id: str = ""
    author: str = ""
    author_ref: str = ""        # "slack:U123"
    approver_refs: list[str] = Field(default_factory=list)


class SlackApproval(BaseModel):
    verdict: str = "approve"    # approve | dissent
    author: str = ""
    author_ref: str = ""


def _said(text: str, cap: int) -> str:
    from aughor.security.pii import redact_text
    from aughor.util.prompt_safety import sanitize_db_text
    return redact_text(sanitize_db_text(text or "")[:cap].strip())


@router.post("/arrivals/slack/decision")
def slack_decision(body: SlackDecision):
    """The decide verb (the decision-framework study §3.2): a decision said in a Slack thread is booked in the Record —
    decided by the person who said it, citing the answer the bot gave in that thread (its run's claims), the people
    named after the verb as its approvers, the thread as where it was taken. Through the same customs as a note: capped,
    control-stripped, PII redacted; what was said is the decision's words, never an instruction."""
    channel, thread_ts = body.channel.strip(), body.thread_ts.strip()
    if not channel or not thread_ts:
        raise HTTPException(status_code=422, detail="channel and thread_ts are required")
    text = _said(body.text, MAX_DECISION_CHARS)
    if not text:
        raise HTTPException(status_code=422, detail="the message said nothing after decide:")
    question = _said(body.question, MAX_DECISION_CHARS)
    run = body.investigation_id.strip()
    conn = body.connection_id.strip()
    if not conn and run:
        try:
            from aughor.db.history import get_investigation
            conn = str((get_investigation(run) or {}).get("connection_id") or "")
        except Exception:  # noqa: BLE001 — an unreadable run names no connection, and the refusal below says so
            conn = ""
    if not conn:
        raise HTTPException(status_code=422, detail="the decision names no connection, and no answer in the thread does")
    ref = f"{channel}:{thread_ts}"
    who = _said(body.author, 80) or body.author_ref.strip() or "someone in Slack"
    approvers = [r.strip() for r in body.approver_refs if r.strip().startswith("slack:")][:10]
    from aughor.record import decisions as D
    from aughor.record.byproducts import NOT_ACT, declare_decision
    try:
        did = declare_decision(
            question=question or f"Decided in Slack: {text}", chosen=text, options=[text, NOT_ACT],
            approvers=approvers, connection_id=conn, decided_by=f"person:{who}",
            note=f"decided in Slack thread {ref} by {who}" + (f" ({body.author_ref.strip()})" if body.author_ref.strip() else ""),
            run_id=run)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    d = D.get_decision(did)
    return {"decision_id": did, "review_on": d.review_on if d else "", "cited": len(d.relied_on) if d else 0,
            "why": str((d.extra.get("relied_on_note") if d else "") or ""), "thread": ref}


@router.post("/arrivals/slack/decision/{decision_id}/approval")
def slack_decision_approval(decision_id: str, body: SlackApproval):
    """A ✅ on a decision card is the reacting person's approval; a ❌ is their dissent, kept on the decision with the
    rest — never a verdict on an answer (TJ-4 reads the answer's ✅). 404 for a decision the Record does not hold."""
    from aughor.record import decisions as D
    if D.get_decision(decision_id) is None:
        raise HTTPException(status_code=404, detail=f"no decision {decision_id}")
    who = _said(body.author, 80) or body.author_ref.strip() or "someone in Slack"
    if body.verdict == "dissent":
        D.amend_decision(decision_id, by=f"person:{who}", dissent_who=f"person:{who}",
                         dissent_why="a ❌ on the decision card in Slack")
        return {"booked": True, "why": f"{who}'s dissent is kept on the decision"}
    if body.verdict != "approve":
        raise HTTPException(status_code=422, detail="verdict is approve or dissent")
    d, added = D.approve_decision(decision_id, by=f"person:{who}", ref=body.author_ref.strip(), where="Slack")
    return {"booked": added, "decision_id": d.id,
            "why": (f"approved by {who}" if added else f"{who} had already approved it")}


@router.get("/arrivals/claims")
def arrival_claims(connection_id: str = Query(default="")):
    """CB-8 — what people said, by what the data made of it: counts per verification and every
    contradiction with the question it raised and who it went to. The map's 'claims checked' count."""
    from aughor.hub.claims import claims_summary
    return claims_summary(connection_id)


@router.get("/arrivals/notes")
def arrival_notes(object_ref: str = Query(...),
                  connection_id: str = Query(default="")):
    """Stored and shown — the conversation notes filed on one securable, each with its
    provenance stamp. This is the surface the injection gate points at while it holds:
    a reader SEES what people said; a prompt gets it only after measured lift."""
    from aughor.hub.provenance import Provenance
    from aughor.ontology.agent_notes import object_notes_for
    conns = [connection_id] if connection_id else _known_note_connections()
    rows = []
    for conn in conns:
        for row in object_notes_for(conn, object_ref):
            prov = row.get("provenance") or {}
            stamp = Provenance(
                source_kind=str(prov.get("source_kind") or "conversation"),
                authority=str(prov.get("authority") or "said"),
                author=str(prov.get("author") or ""),
                where=str(prov.get("where") or ""),
                observed_at=str(prov.get("observed_at") or row.get("last_seen") or ""),
                verification=str(prov.get("verification") or "unverified")).stamp()
            rows.append({**row, "connection_id": conn, "stamp": stamp})
    return {"object_ref": object_ref, "notes": rows}


def _known_note_connections() -> list[str]:
    from aughor.hub.claims import known_note_connections
    return known_note_connections()
