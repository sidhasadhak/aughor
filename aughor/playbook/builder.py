"""
Convert KB Tier-2 causal entries into draft PlaybookEntry objects.
Run seed_from_kb() once on startup when data/playbook.json is empty.

IP-1 — the entries come from the knowledge packages (`aughor/packs/knowledge.py`), the one
reader that replaced this module's own recursive walk of `data/kb`.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

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


def _cause_fix(cause) -> str:
    """The KB's fix for a cause, verbatim, or "" (27 of the 486 causes carry none, and a bare string
    carries nothing but its cause)."""
    if isinstance(cause, dict):
        return str(cause.get("fix") or "").strip()
    return ""


def stable_key(entry_id: str) -> str:
    """A seeded play's id without its random six-hex suffix: the same KB cause gives the same key on
    every build, so an existing playbook can be matched against a fresh one. Unique across the 878
    plays the shipped packages build."""
    return entry_id.rsplit("_", 1)[0]


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
            cause=cause_text,
            fix=_cause_fix(cause),
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
            cause=cause_text,
            fix=_cause_fix(cause),
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


def top_up_data_quality(path: Path | None = None) -> dict:
    """IP-1 — give an EXISTING playbook the data-quality plays it never received (§6 item 21, answer 7).

    `seed_from_kb` writes only into an empty playbook, so every playbook seeded before IP-0 fixed the
    cause parser holds the 392 diagnostic plays and none of the 486 inflation and deflation checks.
    Now that those checks reach the Verifier (deep-analysis rule-outs), they arrive — on these terms:

    - a play is **added** only when no play with its stable key is in the playbook and none ever was:
      a key in the version log whose play is gone was deleted by a person, and is never resurrected;
    - a play already there keeps everything a person may have changed — status, wording, tags — and
      only an EMPTY ``cause`` or ``fix`` is filled from the KB (a playbook seeded between IP-0 and
      IP-1 holds the checks without them);
    - an empty playbook is left to `seed_from_kb`, and diagnostic plays are never touched.

    Idempotent by construction: after one pass every key is in the playbook or in the log. One read
    and one write. Returns the counts ``{"added", "filled", "kept_deleted"}``."""
    from aughor.playbook.retriever import is_data_quality
    from aughor.playbook.store import ever_saved_ids, list_entries

    counts = {"added": 0, "filled": 0, "kept_deleted": 0}
    if count_entries(path) == 0:
        return counts
    built = [p for e in _load_all_kb() if _has_causal_data(e)
             for p in _build_entries_for_kb(e) if is_data_quality(p)]
    present = {stable_key(e.id): e for e in list_entries(path)}
    ever = {stable_key(entry_id) for entry_id in ever_saved_ids(path)}

    to_save: list[PlaybookEntry] = []
    for play in built:
        key = stable_key(play.id)
        held = present.get(key)
        if held is not None:
            fill = {f: getattr(play, f) for f in ("cause", "fix") if getattr(play, f) and not getattr(held, f)}
            if fill:
                to_save.append(held.model_copy(update=fill))
                counts["filled"] += 1
        elif key in ever:
            counts["kept_deleted"] += 1
        else:
            to_save.append(play)
            counts["added"] += 1
    save_entries(to_save, path)
    return counts
