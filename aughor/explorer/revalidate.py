"""Re-validate STORED explorer findings against the current guards.

Generation-time guards (agent.has_fabricated_dimension, clamp_novelty,
_is_degenerate_result) only protect NEW findings. Anything written before a guard
existed sits in the store untouched. This pass re-checks stored findings and either:

  - QUARANTINES it (sets ``invalid=True`` + ``invalid_reason``) for fabricated-
    dimension / no-data findings. The finding is HIDDEN from intel surfaces (the
    store read path filters ``invalid``) but KEPT in the store for inspection —
    never deleted. Reversible: clearing ``invalid`` un-quarantines it.
  - REPAIRS it in place (clamps a runaway novelty + recomputes confidence) when the
    finding itself is real and only its score is wrong — so a good insight is fixed,
    not hidden.

Apply is opt-in: callers dry-run first (``apply=False``) so stored repros are never
silently mutated. See scripts/revalidate_findings.py and store.get_insights'
``include_invalid`` escape hatch.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from aughor.explorer.verify import has_fabricated_dimension, clamp_novelty, _NO_DATA_RE


def validate_insight(ins: dict) -> Optional[tuple[str, str]]:
    """Return (action, reason) for a problem finding, where action is 'quarantine'
    or 'repair'; None when the finding is fine (or already quarantined)."""
    if ins.get("invalid"):
        return None
    sql = ins.get("sql") or ""
    if has_fabricated_dimension(sql):
        return ("quarantine", "fabricated dimension (constant grouping key)")
    finding = ins.get("finding") or ""
    if finding and _NO_DATA_RE.search(finding):
        return ("quarantine", "no-data interpretation")
    nv = ins.get("novelty")
    if isinstance(nv, (int, float)) and not isinstance(nv, bool) and not (1 <= nv <= 5):
        return ("repair", f"novelty {nv} out of range")
    return None


def revalidate_finding(dossier: dict, conn) -> dict:
    """Re-run a finding's stored SQL against LIVE data (ONE query, no LLM) and check
    whether its claim still holds. The finding's magnitudes are re-grounded against
    the fresh result cells:

      - ``confirmed``  — every magnitude in the finding text still appears in the data;
      - ``drifted``    — at least one no longer does (the number moved);
      - ``error``      — the query no longer runs (schema/data changed underneath it).

    A dossier snapshots cells at emit time; this is how a *living* dossier knows the
    snapshot is still true rather than silently serving a stale number. Cheap enough
    to run on a drawer click; no synthesis, no agent."""
    from aughor.explorer.grounding import verify_finding, numeric_cells_block
    sql = (dossier.get("sql") or "").strip()
    finding = dossier.get("finding") or ""
    stored_cells = dossier.get("result_cells") or ""
    if not sql:
        return {"status": "error", "error": "no SQL recorded for this finding"}
    res = conn.execute("__revalidate__", sql)
    if res.error:
        return {"status": "error", "error": res.error}
    rows = res.rows or []
    fresh_cells = numeric_cells_block(rows)
    g = verify_finding(finding, rows)
    status = "confirmed" if g.grounded else "drifted"
    cells_changed = fresh_cells != stored_cells

    # Snapshot-pinned attribution: compare the data version this finding ran against (pinned
    # in the dossier) with the data version NOW. This is what tells a moved dataset apart from
    # a mis-derived finding — the ambiguity a bare cells_changed flag can't resolve.
    pinned_version = dossier.get("data_version")
    current_version = None
    data_moved = None
    reproduced = None   # True/False when we could re-run AT the pinned snapshot (DuckLake); else None
    if pinned_version:
        try:
            from aughor.db.snapshot import (
                data_version, as_of_supported, execute_as_of, native_version_id,
            )
            from aughor.explorer.scope import tables_in_sql
            current_version = data_version(conn, tables_in_sql(sql))
            if current_version is not None:
                data_moved = (current_version != pinned_version)
            # EXACT proof when the storage is version-aware: re-run the finding's SQL AT its
            # pinned snapshot. If the stored number reproduces there, the finding was correctly
            # computed and any live drift is genuinely new data; if it doesn't, it was mis-derived.
            vid = native_version_id(pinned_version)
            if vid is not None and as_of_supported(conn):
                repro = execute_as_of(conn, sql, vid)
                if repro is not None and not getattr(repro, "error", None):
                    reproduced = (numeric_cells_block(repro.rows or []) == stored_cells)
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "snapshot data-version comparison is best-effort", counter="snapshot.revalidate")

    if not cells_changed:
        interpretation = "stable — the finding's numbers are unchanged"
    elif reproduced is True:
        interpretation = (
            "CONFIRMED correct as computed — it reproduces exactly at its pinned snapshot; the "
            "data has since moved, so the live number is new data, not a mis-derivation"
        )
    elif reproduced is False:
        interpretation = (
            "the finding does NOT reproduce even at its own pinned snapshot — it was mis-derived "
            "or non-deterministic (a trust issue, not a data update)"
        )
    elif data_moved is True:
        interpretation = (
            "the underlying data has moved since this finding was computed (as of "
            f"{dossier.get('generated_at') or 'emit'}); the change likely reflects new data, not a mis-derivation"
        )
    elif data_moved is False:
        interpretation = (
            "the result changed with NO change to the underlying data — the finding's SQL is "
            "non-deterministic or was mis-derived (a trust issue, not a data update)"
        )
    else:
        interpretation = "the numbers changed; no data-version pin was available to attribute the cause"

    return {
        "status": status,
        "grounded": g.grounded,
        "checked": g.checked,
        "ungrounded": g.ungrounded,
        "stored_cells": stored_cells,
        "fresh_cells": fresh_cells,
        "cells_changed": cells_changed,
        "row_count": res.row_count,
        # snapshot-pinned attribution (None when the finding predates pinning / was off)
        "pinned_version": pinned_version,
        "current_version": current_version,
        "data_moved": data_moved,
        "reproduced": reproduced,
        "interpretation": interpretation,
    }


def revalidate_state(state: dict, *, apply: bool = False) -> dict:
    """Scan a store state's insights. Returns a report. Mutates state only if apply."""
    quarantined: list[dict] = []
    repaired: list[dict] = []
    for ins in state.get("insights", []):
        verdict = validate_insight(ins)
        if not verdict:
            continue
        action, reason = verdict
        rec = {"id": ins.get("id"), "reason": reason, "finding": (ins.get("finding") or "")[:120]}
        if action == "quarantine":
            quarantined.append(rec)
            if apply:
                ins["invalid"] = True
                ins["invalid_reason"] = reason
        else:
            nv = ins.get("novelty")
            new = clamp_novelty(nv)
            conf = min(0.95, 0.4 + new * 0.1)
            rec["fix"] = f"novelty {nv}→{new}, confidence→{conf}"
            repaired.append(rec)
            if apply:
                ins["novelty"] = new
                ins["confidence"] = conf
    return {"quarantined": quarantined, "repaired": repaired}


def revalidate_file(path, *, apply: bool = False) -> dict:
    """Load an exploration store JSON, revalidate, optionally write back. Works for
    both connection and canvas stores (identical on-disk shape)."""
    p = Path(path)
    state = json.loads(p.read_text())
    report = revalidate_state(state, apply=apply)
    if apply and (report["quarantined"] or report["repaired"]):
        p.write_text(json.dumps(state, indent=2, default=str))
    report["file"] = str(p)
    return report
