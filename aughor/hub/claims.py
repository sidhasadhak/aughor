"""CB-8 (2026-09-23) — said versus measured.

A person's claim arrives at the hub's ``said`` tier (HB-5: a reply in a filed Slack thread becomes
a staged note). Codos keeps such claims as they are; Aughor can CHECK one, because the thread was
filed on an object the platform measures. This module is that check: the numbers the note states
against the measures the thread was filed with (``links.metrics_at_filing`` — the promise's breach
rate and counts at filing). Agreement raises the note to ``measured``; disagreement makes it
``contradicted`` and writes the question for the object's owner (CB-3 says who can be reached);
a note with no number, or an object with nothing measured, stays ``unchecked`` — visibly unknown,
never guessed. Deterministic, no model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

MEASURED, CONTRADICTED, UNCHECKED = "measured", "contradicted", "unchecked"


@dataclass
class ClaimCheck:
    verification: str                      # measured | contradicted | unchecked
    said: list[dict] = field(default_factory=list)      # [{text, value}] the numbers stated
    against: dict = field(default_factory=dict)         # label → value the note was checked against
    matched: Optional[dict] = None                      # {said, label, value} when measured
    question: str = ""                                  # the owner's question when contradicted
    question_to: str = ""                               # principal it goes to ("" = unresolved)
    note: str = ""                                      # why unchecked / who the owner is

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt(v: float) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) >= 1000 else f"{v:.4g}"


def owner_of(object_ref: str, connection_id: str) -> tuple[str, str]:
    """``(principal, owner_text)`` for the object a thread was filed on — a metric's catalog owner, a
    process's or rule's declared owner, a promise's process owner — resolved the CB-3 way. ``("", text)``
    when the owner is unresolved; ``("", "")`` when nothing names one."""
    kind, _, ident = str(object_ref or "").partition(":")
    text = ""
    try:
        if kind == "metric":
            from aughor.semantic.metrics import get_metric
            m = get_metric(ident, connection_id=connection_id or None) or get_metric(ident)
            text = str(getattr(m, "owner", "") or "") if m is not None else ""
        elif kind in ("process", "rule", "promise") and connection_id:
            from aughor.agent.framing import served_graph
            g = served_graph(connection_id, None)
            pid = ident.split(".", 1)[0] if kind == "promise" else ident
            thing = ((getattr(g, "processes", None) or {}).get(pid) if kind in ("process", "promise")
                     else (getattr(g, "rules", None) or {}).get(pid)) if g is not None else None
            text = str(getattr(thing, "owner", "") or "") if thing is not None else ""
    except Exception as exc:  # noqa: BLE001 — an owner that cannot be read is an unresolved owner
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the object's owner could not be read for a claim question", counter="claims.owner")
    if not text:
        return "", ""
    try:
        from aughor.rbac.routing import owner_principal
        return owner_principal(text) or "", text
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "owner routing failed for a claim question", counter="claims.owner")
        return "", text


def check_claim(text: str, object_ref: str, connection_id: str, *, measures: Optional[dict] = None) -> ClaimCheck:
    """Check the numbers ``text`` states against ``measures`` (default: what the thread was filed
    with). See the module docstring for the three outcomes."""
    from aughor.explorer.grounding import extract_numerals, numeral_matches_measure
    numerals = [n for n in extract_numerals(text or "") if n.value is not None]
    said = [{"text": n.text, "value": n.value} for n in numerals]
    if not numerals:
        return ClaimCheck(UNCHECKED, said=said, note="no number is stated")
    if measures is None:
        try:
            from aughor.hub.links import stamped_measures
            measures = stamped_measures(object_ref)
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the object's measures could not be read for a claim check", counter="claims.measures")
            measures = {}
    numeric = {str(k): float(v) for k, v in (measures or {}).items()
               if isinstance(v, (int, float)) and not isinstance(v, bool) and k not in ("connection_id",)}
    if not numeric:
        return ClaimCheck(UNCHECKED, said=said, note="nothing is measured on this object to check against")
    for n in numerals:
        for label, val in numeric.items():
            candidates = [val]
            if n.suffix == "%" or label.endswith("_rate") or label.endswith("rate"):
                candidates.append(val * 100.0)      # a rate stored as a fraction, said as a percentage
            if any(numeral_matches_measure(n, c) for c in candidates):
                return ClaimCheck(MEASURED, said=said, against=numeric, matched={"said": n.text, "label": label, "value": val})
    principal, owner_text = owner_of(object_ref, connection_id)
    closest_label, closest = min(numeric.items(), key=lambda kv: abs(kv[1] - numerals[0].value))
    shown = _fmt(closest * 100.0) + "%" if (numerals[0].suffix == "%" and closest <= 1.0) else _fmt(closest)
    question = (f'You said "{numerals[0].text}" about {object_ref}; the platform measured {shown} ({closest_label}) '
                f"when the thread was filed. Which is right?")
    note = ("" if principal else (f"owner '{owner_text}' is not linked to a person; the question has nowhere to go"
                                  if owner_text else "no owner is declared on this object; the question has nowhere to go"))
    return ClaimCheck(CONTRADICTED, said=said, against=numeric, question=question, question_to=principal, note=note)



def claims_summary(connection_id: str = "") -> dict:
    """CB-8 — what people said, by what the data made of it: counts per verification and every
    contradiction with the question it raised and who it went to. One fold, read by the
    arrivals door and by the company-brain map (its 'claims checked' box)."""
    from aughor.ontology.recommendations import load_recommendations, recommendation_schemas
    conns = [connection_id] if connection_id else known_note_connections()
    counts = {"measured": 0, "contradicted": 0, "unchecked": 0}
    contradictions = []
    for conn in conns:
        for schema in recommendation_schemas(conn):
            for rec in load_recommendations(conn, schema):
                if rec.kind != "object_note" or rec.status == "dismissed":
                    continue
                check = (rec.proposed_fields or {}).get("check") or {}
                v = str(check.get("verification") or "unchecked")
                counts[v if v in counts else "unchecked"] += 1
                if v == "contradicted":
                    contradictions.append({"connection_id": conn, "object_ref": rec.target_id,
                                           "note": (rec.proposed_fields or {}).get("note", ""),
                                           "question": check.get("question", ""),
                                           "question_to": check.get("question_to", ""),
                                           "why_unreached": check.get("note", "")})
    return {"counts": counts, "contradictions": contradictions}


def known_note_connections() -> list[str]:
    """Every connection that has filed notes (the recommendations tree's connection folders)."""
    from pathlib import Path

    from aughor.db.sqlite_util import resolve_db_path
    root = resolve_db_path("AUGHOR_ONTOLOGY_RECOMMENDATIONS_DIR",
                           Path(__file__).parent.parent.parent / "data" / "ontology_recommendations")
    try:
        return sorted(p.name for p in Path(root).iterdir() if p.is_dir())
    except FileNotFoundError:
        return []
