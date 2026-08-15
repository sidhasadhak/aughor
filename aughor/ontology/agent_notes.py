"""Agent-proposed context — the conversation writes back what it learned, governed.

The WrenAI study's `enrich-context` frame (2026-08-14), applied to OUR sinks: an agent
that has just SEEN something in the data (a value domain, a unit, a grain, a definition
the user stated) may write it back so the next session inherits it — but what it may
apply directly and what must wait for a human is decided by the BLAST RADIUS of the
artifact, not by how confident the model feels.

  * A COLUMN NOTE is column-local and additive: it rides one column line into the
    prompt as ``[note: …]``, a human can edit or delete it in place, and it cannot
    change a number. With high confidence AND stated evidence it APPLIES DIRECTLY
    (source="agent" — refresh-safe, provenance visible). The human is the reviewer,
    not the gatekeeper.
  * A TABLE-level claim (grain, description) is a public artifact every future
    session reads before writing SQL — a false grain claim just made every
    returned-orders count wrong (800 vs 296). It is STAGED as an
    ``OntologyRecommendation(kind="table_note")`` and waits for accept().
  * Anything at med/low confidence is staged, never applied.
  * APPEND-ONLY: an existing HUMAN note is never overwritten by the agent — the
    proposal is staged with the conflict named, so the person decides.

Evidence is REQUIRED. A note without the observation that produced it is a guess,
and a guess written into shared context is the failure this whole frame exists to
prevent. Everything the agent writes carries its provenance (evidence, confidence,
session) so a reviewer sees WHY, not just WHAT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

CONFIDENCE = ("high", "med", "low")
TARGETS = ("column", "table")

#: Blast-radius rule, as data: which (target, confidence) pairs may apply directly.
#: Everything else stages. Kept tiny and explicit so a reviewer can read the policy
#: in one line and a test can enumerate it.
DIRECT_APPLY: frozenset[tuple[str, str]] = frozenset({("column", "high")})

MAX_NOTE_CHARS = 280
MAX_EVIDENCE_CHARS = 600


@dataclass
class NoteOutcome:
    ok: bool
    action: str                     # "applied" | "staged" | "rejected"
    reason: str
    target: str = ""
    table: str = ""
    column: str = ""
    recommendation_id: str = ""
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "action": self.action, "reason": self.reason,
                "target": self.target, "table": self.table, "column": self.column,
                "recommendation_id": self.recommendation_id, **self.detail}


def _clean(s: str, cap: int) -> str:
    return " ".join((s or "").split())[:cap]


def propose_note(connection_id: str, schema: str, *, target: str, table: str,
                 column: str = "", note: str, evidence: str, confidence: str,
                 session_id: str = "") -> NoteOutcome:
    """Route one agent proposal: apply, stage, or reject. Never raises."""
    target = (target or "").strip().lower()
    confidence = (confidence or "").strip().lower()
    table = (table or "").strip()
    column = (column or "").strip()
    note = _clean(note, MAX_NOTE_CHARS)
    evidence = _clean(evidence, MAX_EVIDENCE_CHARS)

    if target not in TARGETS:
        return NoteOutcome(False, "rejected", f"target must be one of {TARGETS}")
    if confidence not in CONFIDENCE:
        return NoteOutcome(False, "rejected", f"confidence must be one of {CONFIDENCE}")
    if not table or not note:
        return NoteOutcome(False, "rejected", "table and note are required")
    if target == "column" and not column:
        return NoteOutcome(False, "rejected", "a column note needs the column")
    if not evidence:
        return NoteOutcome(False, "rejected",
                           "evidence is required — say what you observed (a query result, "
                           "the user's own words) that makes this note true; a note without "
                           "evidence is a guess and does not enter shared context")

    try:
        if target == "column":
            return _route_column(connection_id, schema, table, column, note, evidence,
                                 confidence, session_id)
        return _stage(connection_id, schema, "table", table, "", note, evidence,
                      confidence, session_id,
                      why="a table-level claim is read by every future session before it "
                          "writes SQL — it waits for a person to accept it")
    except Exception as exc:  # the answer path must never fail on a note
        from aughor.kernel.errors import tolerate
        tolerate(exc, "agent note routing is best-effort; the proposal is dropped, not the turn",
                 counter="ontology.agent_notes")
        return NoteOutcome(False, "rejected", f"could not record the note: {type(exc).__name__}")


def _route_column(conn: str, schema: str, table: str, column: str, note: str,
                  evidence: str, confidence: str, session_id: str) -> NoteOutcome:
    from aughor.ontology.column_config import load_table_config, set_column_flags
    existing = load_table_config(conn, schema, table).get(column)
    if existing is not None and existing.source == "human" and (existing.note or "").strip():
        # Append-only: a person wrote this. Stage the disagreement, never overwrite it.
        return _stage(conn, schema, "column", table, column, note, evidence, confidence,
                      session_id,
                      why=f"the column already carries a HUMAN note ({existing.note[:80]!r}); "
                          "an agent never overwrites a person — staged for review instead")
    if ("column", confidence) not in DIRECT_APPLY:
        return _stage(conn, schema, "column", table, column, note, evidence, confidence,
                      session_id, why=f"confidence {confidence!r} is not high enough to apply directly")
    stamped = f"{note} (agent-observed: {evidence[:120]})"
    flags = set_column_flags(conn, schema, table, column, note=stamped, source="agent")
    return NoteOutcome(True, "applied",
                       "applied directly: a column note is column-local and additive, and you "
                       "gave high confidence with evidence — a person can edit or remove it",
                       target="column", table=table, column=column,
                       detail={"note": flags.note, "source": flags.source})


def _stage(conn: str, schema: str, target: str, table: str, column: str, note: str,
           evidence: str, confidence: str, session_id: str, *, why: str) -> NoteOutcome:
    from aughor.ontology.recommendations import (
        OntologyRecommendation, get_recommendation, save_recommendation,
    )
    key = f"{table}.{column}" if column else table
    rec_id = f"note_{target}_{_slug(key)}"
    rec = get_recommendation(conn, schema, rec_id)
    now = datetime.now(timezone.utc).isoformat()
    ev = {"note": note, "evidence": evidence, "confidence": confidence,
          "session_id": session_id, "at": now}
    if rec is None:
        rec = OntologyRecommendation(
            id=rec_id, kind=f"{target}_note", target_id=key, entity=table,
            proposed_fields={"note": note, "column": column, "confidence": confidence},
            reason=f"proposed by the conversation with evidence: {evidence[:160]}",
            support=1, evidence=[ev])
    else:
        rec.support += 1
        rec.last_seen = now
        rec.evidence = (rec.evidence + [ev])[-5:]
        rec.proposed_fields = {"note": note, "column": column, "confidence": confidence}
    save_recommendation(conn, schema, rec)
    return NoteOutcome(True, "staged", f"staged for human review: {why}",
                       target=target, table=table, column=column, recommendation_id=rec_id,
                       detail={"support": rec.support})


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)[:80]


def accept_note(conn: str, schema: str, rec_id: str) -> Optional[dict]:
    """A human accepts a staged note: a column note becomes a human-sourced column note;
    a table note becomes the table's glossary grain/description via the glossary's
    own writer. Returns what was written, or None when the id is unknown or not a note."""
    from aughor.ontology.recommendations import get_recommendation, save_recommendation
    rec = get_recommendation(conn, schema, rec_id)
    if rec is None or not rec.kind.endswith("_note"):
        return None
    note = str(rec.proposed_fields.get("note") or "")
    if rec.kind == "column_note":
        from aughor.ontology.column_config import set_column_flags
        flags = set_column_flags(conn, schema, rec.entity, str(rec.proposed_fields.get("column")),
                                 note=note, source="human")
        written = {"column_note": flags.note}
    else:
        from aughor.semantic.glossary import update_table
        update_table(rec.entity, grain=note)
        written = {"table_grain": note}
    rec.status = "accepted"
    save_recommendation(conn, schema, rec)
    return {"accepted": rec_id, **written}
