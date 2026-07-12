"""aughor.memory — agent procedural memory (learned skills + earned autonomy).

Learned-SKILL crystallization is implemented in `aughor.memory.skills`: a finished
investigation's grounded, read-only SQL is parameterized and saved as a reusable, governed
`OntologyAction` (origin='learned') that re-enters the live ontology via the overlay seam.
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
        KeyedJsonStore(agent_runs_path(), max_entries=2000).put(inv_id, {
            "inv_id": inv_id,
            "connection_id": connection_id,
            "question": question,
            "confidence": st.get("confidence"),
            "grounded": st.get("grounded", st.get("all_grounded")),
            "read_only": st.get("read_only", True),
            "schema": st.get("scope_schema") or st.get("schema"),
            "recorded_at": now_iso(),
        })
    except Exception as exc:
        logger.debug("record_run(%s) best-effort skip: %s", inv_id, exc)
    return None
