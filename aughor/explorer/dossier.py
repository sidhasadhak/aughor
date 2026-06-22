"""The Finding Dossier — the explorer's own derivation, captured at emit time.

The explorer already does deep analysis to produce a single finding: it asks a
business question, runs SQL, reads the actual result cells, grounds every
magnitude-bearing number against those cells, and sits on top of the structural
facts it mapped earlier (verified joins, NULL meanings, lifecycle states, value
distributions). Historically *all* of that derivation was discarded the instant
the finding prose was written — so when a CEO later asked "how was this derived?"
the system ran a second, redundant deep analysis (a full ADA investigation) to
reconstruct what it already knew.

A :class:`dossier` captures that derivation ONCE, at the one instant in
``SchemaExplorer._phase8`` where every input is simultaneously in hand, and rides
into the finding's K3 ledger artifact (``_emit_insight``). The already-wired,
read-only Evidence drawer then renders the full trace from the Trust Receipt at
*zero* recompute — no new SQL, no new LLM call.

Nothing here executes SQL or calls an LLM: ``build_dossier`` is pure assembly +
dict-filtering over data the caller already holds. It must stay cheap and
fail-soft — a dossier is provenance, never on the critical path of emitting a
finding.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

# Bump when the on-disk dossier shape changes so the renderer can branch / a
# re-explore can supersede stale-shaped dossiers (artifact version+1).
DOSSIER_VERSION = 1


def _bare(table: str) -> str:
    """Bare table name, schema-qualifier stripped, lowercased. ``scope.tables_in_sql``
    yields schema-qualified names (``ecommerce.orders``) while the structural facts
    are keyed bare (``orders``); normalising both sides is what makes the slice match
    (an exact compare silently dropped every fact — caught in live verification)."""
    return str(table).rsplit(".", 1)[-1].strip().strip('"').lower()


def _structural_ctx(state: dict, tables: Iterable[str]) -> dict:
    """Slice the explorer's Phase 3-7 structural facts down to just the tables
    this finding touches. Keyed off the tables in the finding's SQL (the honest
    signal), not entity ids. Pure dict-filtering — no probing, no SQL."""
    tset = {_bare(t) for t in (tables or [])}
    out: dict[str, Any] = {"null_meanings": {}, "joins": [], "lifecycles": {}, "distributions": {}}
    if not tset:
        return out

    for key, val in (state.get("null_meanings") or {}).items():
        # keys are "{table}:{column}"
        if _bare(str(key).split(":", 1)[0]) in tset:
            out["null_meanings"][key] = val

    for jv in (state.get("join_verifications") or []):
        if (_bare(jv.get("from_table", "")) in tset
                or _bare(jv.get("to_table", "")) in tset):
            out["joins"].append(jv)

    for tbl, lm in (state.get("lifecycle_maps") or {}).items():
        if _bare(tbl) in tset:
            out["lifecycles"][tbl] = lm

    for key, dist in (state.get("distributions") or {}).items():
        if _bare(str(key).split(":", 1)[0]) in tset:
            out["distributions"][key] = dist

    return out


def update_dossier(connection_id: str, insight_id: str, *, merge: dict,
                   lineage_edge: Optional[tuple] = None) -> Optional[int]:
    """Write a new version of a finding's artifact with ``merge`` folded into its
    dossier — the supersede-not-delete primitive behind a living dossier (freshness
    re-stamps, per-finding narrative). Returns the new version, or None if the
    finding has no dossier yet. Best-effort: callers tolerate None/exceptions."""
    from aughor.kernel.ledger import Ledger
    led = Ledger.default()
    nk = f"insight:{connection_id}:{insight_id}"
    art = led.artifact_latest(nk)
    if not art:
        return None
    payload = dict(art.get("payload") or {})
    dossier = dict(payload.get("dossier") or {})
    if not dossier:
        return None
    dossier.update(merge)
    payload["dossier"] = dossier
    led.artifact_write("finding", nk, payload, conn_id=connection_id,
                       lineage=[lineage_edge] if lineage_edge else None)
    return int(art.get("version", 0)) + 1


def build_dossier(
    *,
    question: str,
    sql: str,
    finding: str,
    rationale: str,
    rows: Any,
    grounding: Any,
    tables: Iterable[str],
    state: dict,
    generated_at: str,
    data_fingerprint: Optional[str] = None,
) -> dict:
    """Assemble the dossier for one finding from inputs already in hand at emit.

    ``grounding`` is the explorer's :class:`GroundingResult` (the proof that every
    magnitude in ``finding`` matched a real result cell). ``rows`` are the final
    result rows (post de-fan); we keep only the bounded, de-duplicated numeric
    cells block — never the raw, potentially unbounded result set. ``state`` is
    ``self._state``; only the slice relevant to this finding's tables is kept.
    """
    from aughor.explorer.grounding import numeric_cells_block

    g_grounded = bool(getattr(grounding, "grounded", True))
    g_checked = int(getattr(grounding, "checked", 0) or 0)
    g_ungrounded = list(getattr(grounding, "ungrounded", []) or [])

    return {
        "dossier_version": DOSSIER_VERSION,
        "question": question or "",
        "sql": sql or "",
        "finding": finding or "",
        "rationale": rationale or "",
        # The actual numeric evidence behind the claim (bounded top-N, de-duped).
        "result_cells": numeric_cells_block(rows or []),
        "grounding": {
            "grounded": g_grounded,
            "checked": g_checked,
            "ungrounded": g_ungrounded,
        },
        # Phase 3-7 facts scoped to this finding's tables — the structural ground
        # the claim stands on (joins verified, NULL semantics, lifecycle, shape).
        "structural_ctx": _structural_ctx(state or {}, tables),
        # Freshness anchors — Phase 4 (re-validate) compares live data against these.
        "generated_at": generated_at,
        "data_fingerprint": data_fingerprint,
    }
