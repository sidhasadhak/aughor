"""
Outcome Tracking — Sprint 16.

Records the result of each recommendation from an investigation.
Drives historical_success_rate on PlaybookEntry objects.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "recommendation_outcomes.json"

RecStatus = Literal["accepted", "rejected", "implemented", "verified", "dismissed"]


class RecOutcome(BaseModel):
    id: str                              # "{inv_id}_rec_{index}"
    inv_id: str
    rec_index: int                       # position in report.recommended_actions
    rec_text: str
    status: RecStatus = "accepted"
    metric_name: Optional[str] = None
    metric_before: Optional[float] = None
    metric_after: Optional[float] = None
    created_at: str = Field(default_factory=lambda: _now())
    updated_at: str = Field(default_factory=lambda: _now())


def _now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


# ── Persistence ───────────────────────────────────────────────────────────────

def _load_raw(path: Path | None = None) -> list[dict]:
    p = path or _DEFAULT_PATH
    if not p.exists():
        return []
    with open(p) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _save_raw(outcomes: list[dict], path: Path | None = None) -> None:
    p = path or _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(outcomes, f, indent=2)


# ── Public API ────────────────────────────────────────────────────────────────

def log_outcome(
    inv_id: str,
    rec_index: int,
    rec_text: str,
    status: RecStatus,
    metric_name: Optional[str] = None,
    metric_before: Optional[float] = None,
    metric_after: Optional[float] = None,
    path: Path | None = None,
) -> RecOutcome:
    outcome_id = f"{inv_id}_rec_{rec_index}"
    raw = _load_raw(path)
    outcome = RecOutcome(
        id=outcome_id,
        inv_id=inv_id,
        rec_index=rec_index,
        rec_text=rec_text,
        status=status,
        metric_name=metric_name,
        metric_before=metric_before,
        metric_after=metric_after,
        updated_at=_now(),
    )
    for i, o in enumerate(raw):
        if o.get("id") == outcome_id:
            # Preserve original created_at on update
            outcome = RecOutcome(**{**outcome.model_dump(), "created_at": o.get("created_at", _now())})
            raw[i] = outcome.model_dump()
            _save_raw(raw, path)
            return outcome
    raw.append(outcome.model_dump())
    _save_raw(raw, path)

    # Promote (or weaken) causal proposals for this investigation
    if status in ("verified", "implemented", "rejected"):
        try:
            from aughor.process.causal import promote_on_outcome
            promote_on_outcome(inv_id, contradicted=(status == "rejected"))
        except Exception:
            pass

    return outcome


def load_outcomes_for_inv(inv_id: str, path: Path | None = None) -> list[RecOutcome]:
    return [RecOutcome(**o) for o in _load_raw(path) if o.get("inv_id") == inv_id]


def load_all_outcomes(path: Path | None = None) -> list[RecOutcome]:
    return [RecOutcome(**o) for o in _load_raw(path)]


def update_playbook_success_rates(path: Path | None = None) -> int:
    """
    Recompute historical_success_rate for all playbook entries that have outcomes.
    Returns the number of entries updated.
    """
    from aughor.playbook.retriever import retrieve_for_metric_and_phases
    from aughor.playbook.store import get_entry, save_entry

    outcomes = load_all_outcomes(path)
    terminal = [o for o in outcomes if o.status in ("verified", "rejected")]
    if not terminal:
        return 0

    # Group outcomes by matched playbook entry
    entry_stats: dict[str, dict] = {}  # entry_id -> {wins, total}
    for outcome in terminal:
        # Match the recommendation text to playbook entries
        matches = retrieve_for_metric_and_phases([outcome.rec_text], limit=1)
        if not matches:
            continue
        entry = matches[0]
        if entry.id not in entry_stats:
            entry_stats[entry.id] = {"wins": 0, "total": 0, "sources": []}
        entry_stats[entry.id]["total"] += 1
        if outcome.status == "verified":
            entry_stats[entry.id]["wins"] += 1
        if outcome.inv_id not in entry_stats[entry.id]["sources"]:
            entry_stats[entry.id]["sources"].append(outcome.inv_id)

    updated = 0
    for entry_id, stats in entry_stats.items():
        entry = get_entry(entry_id)
        if not entry:
            continue
        entry.historical_success_rate = stats["wins"] / stats["total"] if stats["total"] else 0.0
        entry.evidence_sources = stats["sources"]
        # Auto-promote to active if success rate >= 50% with at least 2 outcomes
        if entry.status == "draft" and stats["total"] >= 2 and entry.historical_success_rate >= 0.5:
            entry.status = "active"
        save_entry(entry)
        updated += 1

    return updated
