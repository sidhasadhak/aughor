"""Self-distilling experts (Bet 1) — a pack learns from its own VERIFIED runs.

The moat: every investigation a specialist runs can refine the pack (schema caveats, binding
corrections, new diagnostics), so day-90 >> day-1. The safety rail is the trust gate — the
distiller consumes ONLY manifest-verified runs (is_compoundable), so it compounds learning,
not drift. This module is the deterministic distiller + the gate; an LLM distiller for subtler
patterns can layer on later behind the same gate. Pure; never raises.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


from aughor.agent.state import VerificationManifest
from aughor.verify.gate import is_compoundable


@dataclass
class PackDelta:
    kind: str                 # "caveat" | "diagnostic" | "binding_fix"
    target: str               # e.g. "table.column" for a caveat, "" for a diagnostic
    content: str
    source_run: str = ""
    confidence: float = 0.5


@dataclass
class DistillResult:
    compounded: bool = False          # did the run pass the trust gate?
    deltas: list[PackDelta] = field(default_factory=list)
    skipped_reason: str = ""          # why nothing compounded (gate blockers)


def distill_deltas(
    pack_id: str,
    manifest: Optional[VerificationManifest],
    data_quality_notes: Optional[list] = None,
    human_verdict: Optional[str] = None,
    verdict_note: str = "",
    source_run: str = "",
) -> DistillResult:
    """Propose versioned pack deltas from one run. GATE FIRST: an unverified run compounds
    nothing (quarantined). From a verified run, turn column-specific data-quality notes into
    caveats, and a human 'correct'/'reject' verdict into a diagnostic the expert should ask."""
    ok, reasons = is_compoundable(manifest)
    if not ok:
        return DistillResult(compounded=False, skipped_reason="; ".join(reasons) or "unverified run")

    deltas: list[PackDelta] = []
    for n in (data_quality_notes or []):
        table = getattr(n, "table", "") or ""
        column = getattr(n, "column", "") or ""
        issue = getattr(n, "issue", "") or ""
        if column and issue and table not in ("", "SQL Execution", "Adversarial check"):
            deltas.append(PackDelta(
                kind="caveat", target=f"{table}.{column}", content=issue,
                source_run=source_run, confidence=0.6))

    if human_verdict in ("correct", "reject") and verdict_note.strip():
        deltas.append(PackDelta(
            kind="diagnostic", target="",
            content=f"A reviewer flagged ({human_verdict}): {verdict_note.strip()} — add a check for this.",
            source_run=source_run, confidence=0.7 if human_verdict == "reject" else 0.5))

    return DistillResult(compounded=True, deltas=deltas)


def llm_distill_deltas(
    pack_id: str,
    manifest: Optional[VerificationManifest],
    chain_summary: str,
    source_run: str = "",
    provider=None,
) -> list[PackDelta]:
    """LLM pass that distils subtler pack learnings (caveats/diagnostics) from a VERIFIED run's
    chain summary — the patterns the deterministic distiller misses. Same trust gate
    (is_compoundable) so it never learns from an unverified run. Best-effort: returns [] on the
    gate, an empty summary, or any provider/parse error. `provider` is injectable for tests."""
    ok, _ = is_compoundable(manifest)
    if not ok or not (chain_summary or "").strip():
        return []
    try:
        from pydantic import BaseModel, Field
        from aughor.agent.prompts_explore import DISTILL_PACK_DELTAS_PROMPT

        class _D(BaseModel):
            kind: str = "diagnostic"
            target: str = ""
            content: str = ""

        class _Out(BaseModel):
            deltas: list[_D] = Field(default_factory=list)

        prov = provider
        if prov is None:
            from aughor.llm.provider import get_provider
            prov = get_provider("coder")
        out = prov.complete(
            system="You distil durable improvements to a domain-expert pack. Be conservative.",
            user=DISTILL_PACK_DELTAS_PROMPT.format(pack_id=pack_id, chain_summary=chain_summary[:6000]),
            response_model=_Out,
        )
        return [
            PackDelta(kind=d.kind, target=d.target or "", content=d.content.strip(),
                      source_run=source_run, confidence=0.55)
            for d in (out.deltas or [])
            if (d.content or "").strip() and d.kind in ("caveat", "diagnostic")
        ]
    except Exception:
        return []
