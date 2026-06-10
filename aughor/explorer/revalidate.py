"""Re-validate STORED explorer findings against the current guards.

Generation-time guards (agent._has_fabricated_dimension, _clamp_novelty,
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

from aughor.explorer.agent import _has_fabricated_dimension, _clamp_novelty, _NO_DATA_RE


def validate_insight(ins: dict) -> Optional[tuple[str, str]]:
    """Return (action, reason) for a problem finding, where action is 'quarantine'
    or 'repair'; None when the finding is fine (or already quarantined)."""
    if ins.get("invalid"):
        return None
    sql = ins.get("sql") or ""
    if _has_fabricated_dimension(sql):
        return ("quarantine", "fabricated dimension (constant grouping key)")
    finding = ins.get("finding") or ""
    if finding and _NO_DATA_RE.search(finding):
        return ("quarantine", "no-data interpretation")
    nv = ins.get("novelty")
    if isinstance(nv, (int, float)) and not isinstance(nv, bool) and not (1 <= nv <= 5):
        return ("repair", f"novelty {nv} out of range")
    return None


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
            new = _clamp_novelty(nv)
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
