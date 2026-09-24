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
from pydantic import BaseModel

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
    return {"action": outcome.action, "object_ref": link["object_ref"],
            "recommendation_id": outcome.recommendation_id,
            "note": text, "provenance": provenance,
            "check": check.to_dict() if check is not None else None,
            "why": outcome.reason}


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
