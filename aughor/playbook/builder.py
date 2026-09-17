"""
Convert KB Tier-2 causal entries into draft PlaybookEntry objects.
Run seed_from_kb() once on startup when data/playbook.json is empty.

IP-1 — the entries come from the knowledge packages (`aughor/packs/knowledge.py`), the one
reader that replaced this module's own recursive walk of `data/kb`.
"""
from __future__ import annotations

import re
import uuid

from aughor.playbook.models import DATA_QUALITY_TAG, PlaybookEntry
from aughor.playbook.store import count_entries, save_entries


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:80]


def _load_all_kb() -> list[dict]:
    """Every KB entry the knowledge packages carry, in file-name order."""
    from aughor.packs.knowledge import iter_kb_payloads

    entries: list[dict] = []
    for _file, data in iter_kb_payloads():
        if isinstance(data, list):
            entries.extend(e for e in data if isinstance(e, dict))
        elif isinstance(data, dict):
            entries.append(data)
    return entries


def _has_causal_data(e: dict) -> bool:
    return bool(
        e.get("causal_relationships")
        or e.get("inflation_causes")
        or e.get("deflation_causes")
    )


def _tags(e: dict) -> list[str]:
    raw = e.get("intent_tags") or e.get("tags") or []
    if isinstance(raw, list):
        return [t for t in raw if isinstance(t, str)][:10]
    return []


def _cause_text(cause) -> str:
    """The cause an inflation or deflation entry names: a dict's ``cause``, or a bare string.

    This was ``cause.get("cause") or cause if isinstance(cause, str) else ""``, which Python reads as
    ``(cause.get("cause") or cause) if isinstance(cause, str) else ""``. Every cause in the KB is a dict, so
    each became "" and was skipped — 486 causes, each with detection SQL and a fix, never became plays — and a
    string cause raised AttributeError."""
    if isinstance(cause, dict):
        return str(cause.get("cause") or "").strip()
    if isinstance(cause, str):
        return cause.strip()
    return ""


def _build_entries_for_kb(e: dict) -> list[PlaybookEntry]:
    results: list[PlaybookEntry] = []
    kb_id = e.get("id", "unknown")
    title = e.get("title", kb_id)
    trigger_metric = _slug(kb_id)
    tags = _tags(e)

    # 1. causal_relationships → each symptom + first check step
    for rel in (e.get("causal_relationships") or []):
        symptom = rel.get("symptom") or rel.get("if") or ""
        checks = rel.get("check_in_order") or []
        if isinstance(rel.get("then"), str):
            checks = [rel["then"]]
        if not symptom and not checks:
            continue
        check_str = ", ".join(checks[:3]) if checks else "root cause"
        rec = (
            f"When {symptom}: investigate {check_str} in that order to identify the root cause."
            if checks
            else f"Investigate {symptom} as a potential driver of {title}."
        )
        results.append(PlaybookEntry(
            id=f"kb_{trigger_metric}_{_slug(symptom)}_{uuid.uuid4().hex[:6]}",
            source_kb_id=kb_id,
            trigger_metric=trigger_metric,
            trigger_condition=symptom or f"{title} anomaly detected",
            recommendation=rec,
            expected_impact="Identify and isolate the root cause",
            typical_timeline="1–3 days investigation",
            owner_role="Data Analyst",
            tags=tags,
            status="draft",
        ))

    # 2. inflation_causes → one entry per cause
    for cause in (e.get("inflation_causes") or []):
        cause_text = _cause_text(cause)
        if not cause_text:
            continue
        results.append(PlaybookEntry(
            id=f"kb_{trigger_metric}_inflation_{_slug(cause_text)[:40]}_{uuid.uuid4().hex[:6]}",
            source_kb_id=kb_id,
            trigger_metric=trigger_metric,
            trigger_condition=f"{title} appears inflated",
            recommendation=f"Check if {cause_text} is artificially inflating {title}.",
            expected_impact="Correct metric definition or exclude contaminating data",
            typical_timeline="Same day",
            owner_role="Data Analyst",
            tags=tags + [DATA_QUALITY_TAG, "inflation"],
            status="draft",
        ))

    # 3. deflation_causes → one entry per cause
    for cause in (e.get("deflation_causes") or []):
        cause_text = _cause_text(cause)
        if not cause_text:
            continue
        results.append(PlaybookEntry(
            id=f"kb_{trigger_metric}_deflation_{_slug(cause_text)[:40]}_{uuid.uuid4().hex[:6]}",
            source_kb_id=kb_id,
            trigger_metric=trigger_metric,
            trigger_condition=f"{title} appears suppressed",
            recommendation=f"Check if {cause_text} is suppressing {title}.",
            expected_impact="Uncover hidden volume or revenue",
            typical_timeline="Same day",
            owner_role="Data Analyst",
            tags=tags + [DATA_QUALITY_TAG, "deflation"],
            status="draft",
        ))

    return results


def activate_seeded() -> int:
    """Promote KB-seeded 'draft' entries to 'active' so they're live by default.
    Leaves user-deprecated and user-authored entries untouched. Idempotent —
    returns the number of entries newly promoted."""
    from aughor.playbook.store import list_entries, _save_raw
    raw = [e.model_dump() for e in list_entries()]
    promoted = 0
    for e in raw:
        is_seed = bool(e.get("source_kb_id")) or str(e.get("id", "")).startswith("kb_")
        if is_seed and e.get("status") == "draft":
            e["status"] = "active"
            promoted += 1
    if promoted:
        _save_raw(raw)
    return promoted


def seed_from_kb(force: bool = False) -> int:
    """
    Convert KB causal entries into draft PlaybookEntry objects.
    Skipped when data/playbook.json is already populated unless force=True.
    When force=True, only KB-sourced entries are replaced (user-created entries preserved).
    Returns the number of entries written.
    """
    if not force and count_entries() > 0:
        return 0

    kb_entries = [e for e in _load_all_kb() if _has_causal_data(e)]
    playbook: list[PlaybookEntry] = []
    for kb in kb_entries:
        playbook.extend(_build_entries_for_kb(kb))

    if force:
        # Remove existing KB-seeded entries before re-seeding so we don't duplicate
        from aughor.playbook.store import list_entries, _save_raw
        existing = list_entries()
        user_entries = [e for e in existing if not (e.source_kb_id or e.id.startswith("kb_"))]
        _save_raw([e.model_dump() for e in user_entries])

    # One read and one write for the whole seed: a save per play rewrote the playbook and its version log
    # each time, which is quadratic — and startup awaits this.
    save_entries(playbook)

    return len(playbook)
