"""aughor.memory — agent procedural memory (learned skills + earned autonomy).

Learned-SKILL crystallization is implemented in `aughor.memory.skills`: a finished
investigation's grounded, read-only SQL is parameterized and saved as a reusable, governed
`QueryTemplate` (origin='learned') that re-enters the live ontology via the overlay seam.
The earned L0–L3 autonomy ladder is NOT built yet — autonomy is manual (L0), so
`auto_crystallize` is a deliberate no-op (a strong run stays a UI-confirmed candidate, never
silently persisted). `record_run` below persists the per-run signals that ladder will read.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def record_run(inv_id: str, connection_id: str, question: str, state: dict[str, Any]) -> None:
    """Persist a finished run's reflection signals (confidence / grounded / read-only / schema)
    into agent procedural memory — the substrate the autonomy ladder will read to earn trust, and
    a light audit trail today. Best-effort: never breaks the investigation stream."""
    if not inv_id:
        return None
    try:
        from aughor.memory.paths import agent_runs_path
        from aughor.util.json_store import KeyedJsonStore
        from aughor.util.time import now_iso
        st = state or {}
        grounded, confidence, basis = _derive_evidence(st)
        KeyedJsonStore(agent_runs_path(), max_entries=2000).put(inv_id, {
            "inv_id": inv_id,
            "connection_id": connection_id,
            "question": question,
            "confidence": confidence,
            "grounded": grounded,
            "evidence_basis": basis,
            "read_only": st.get("read_only", True),
            "schema": st.get("scope_schema") or st.get("schema"),
            "recorded_at": now_iso(),
        })
    except Exception as exc:
        logger.debug("record_run(%s) best-effort skip: %s", inv_id, exc)
    return None


def _derive_evidence(st: dict[str, Any]) -> tuple[Any, Any, str]:
    """``(grounded, confidence, basis)`` from what a run actually carries (AO-7e).

    Measured 2026-10-03: `AgentState` has no top-level `confidence`/`grounded`, so every run
    was recorded as unknown, no run was ever "clean", and the autonomy ladder never moved.
    An explore run carries a VERIFICATION MANIFEST (earned confidence, a band); a deep run's
    trajectory carries a REWARD LABEL (`learning/reward.run_label`). Neither is a model's
    claim about itself — the manifest counts checks that ran, the label counts executions,
    guard fires and human verdicts. The legacy keys are read last, so a caller that set
    them keeps its meaning."""
    report = st.get("exploration_report")
    manifest = None
    if isinstance(report, dict):
        manifest = report.get("verification")
    elif report is not None:
        manifest = getattr(report, "verification", None)
    if manifest is not None:
        get = (manifest.get if isinstance(manifest, dict)
               else lambda k, d=None: getattr(manifest, k, d))
        conf = get("earned_confidence")
        band = str(get("confidence_band") or "").lower()
        checks = get("checks") or []
        grounded = bool(checks) and band not in ("", "low", "none")
        return grounded, (float(conf) if conf is not None else None), "verification_manifest"
    trace_id = st.get("trace_id") or ""
    if trace_id:
        try:
            from aughor.obs.trajectory import trajectory_of
            from aughor.learning.reward import run_label
            label = run_label(trajectory_of(trace_id)) or {}
            if label.get("label") in ("positive", "negative"):
                return label["label"] == "positive", None, "reward_label"
        except Exception as exc:                        # noqa: BLE001 — fall through
            logger.debug("reward label unavailable for %s: %s", trace_id, exc)
    return (st.get("grounded", st.get("all_grounded")), st.get("confidence"),
            "state_keys" if ("grounded" in st or "confidence" in st) else "unknown")
