"""HB-4 — envelope adapters: the pieces context could be made of, each wrapped in its
provenance where it already lives. No ninth store — an adapter READS an existing store
and returns ``ContextPiece``s; the ranker and the receipts consume them.

First adapter: conversation-derived object notes (HB-5's arrivals), the source kind
whose injection the gate holds until measured. More adapters join as their kinds earn
harness arms (definitions and measurements already reach prompts through their own
established blocks — the metrics catalog, the stamped ontology — and are not
re-plumbed here).
"""
from __future__ import annotations

from aughor.hub.provenance import ContextPiece, Provenance
from aughor.kernel.errors import tolerate


def conversation_note_pieces(connection_id: str) -> list[ContextPiece]:
    """Every conversation-derived object note on this connection, enveloped. Pending
    notes rank as unverified 'said'; accepted ones keep 'said' authority (a person
    accepted that it was SAID — acceptance is not verification against the data) with
    the verification tier showing the difference."""
    try:
        from aughor.ontology.agent_notes import object_notes_for
    except Exception:
        return []

    out: list[ContextPiece] = []
    try:
        refs = _noted_object_refs(connection_id)
        for ref in refs:
            for row in object_notes_for(connection_id, ref):
                prov_d = row.get("provenance") or {}
                prov = Provenance(
                    source_kind="conversation",
                    authority="said",
                    author=str(prov_d.get("author") or ""),
                    author_kind=str(prov_d.get("author_kind") or "person"),
                    scope_kind="object",
                    scope_key=ref,
                    observed_at=str(prov_d.get("observed_at") or row.get("last_seen") or ""),
                    verification=("accepted" if row.get("status") == "accepted"
                                  else "unverified"),
                    where=str(prov_d.get("where") or ""),
                )
                out.append(ContextPiece(text=row.get("note", ""), provenance=prov,
                                        subject=ref, piece_id=str(row.get("id") or "")))
    except Exception as exc:
        tolerate(exc, "conversation-note adapter is best-effort; context goes on without it",
                 counter="hub.adapters.conversation_notes")
    return out


def _noted_object_refs(connection_id: str) -> list[str]:
    """Every securable that carries at least one object note — a scan of the
    recommendations tree only."""
    from aughor.ontology.recommendations import load_recommendations, recommendation_schemas
    refs: list[str] = []
    for schema in recommendation_schemas(connection_id):
        for rec in load_recommendations(connection_id, schema):
            if rec.kind == "object_note" and rec.status != "dismissed" \
                    and rec.target_id not in refs:
                refs.append(rec.target_id)
    return refs
