"""
Convert KB Tier-2 causal entries into draft PlaybookEntry objects.
Run seed_from_kb() once on startup when data/playbook.json is empty.

IP-1 — the entries come from the knowledge packages (`aughor/packs/knowledge.py`), the one
reader that replaced this module's own recursive walk of `data/kb`.
"""
from __future__ import annotations

import hashlib
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


#: The trigger operators `PlaybookEntry` accepts. A pack may leave `trigger_operator` empty, and
#: gate 3 does not constrain its spelling, so anything else becomes "any" rather than raising at
#: seed time — a malformed play must not stop the other plays reaching the store.
_TRIGGER_OPERATORS = ("gt", "lt", "eq", "any")


def _load_all_pack_plays() -> list[tuple[str, object]]:
    """Every play an ACTIVE knowledge package declares in `playbooks/*.yaml` — IP-3's anatomy —
    paired with its package id.

    Until this function existed the anatomy reached no prompt at all. `playbooks/*.yaml` had five
    readers (`gate3`, `gate4`, `validate`, the packs API and the `list_packs` tool) and every one
    of them was a gate or a surface; the steering path could not see them, because
    `PackManifest.steers` is False for every knowledge layer, so `intake.active_packs` — the pool
    `inject.render_injection` draws from — excludes an industry package by construction.

    Two properties come from sourcing the packages through `knowledge_index()` rather than by
    walking the roots: gate 6 is honoured (the index holds only `status: active` packages, so a
    draft's plays are never seeded), and every package here has a resolved industry, which is what
    lets `entry_industry` attribute the row instead of defaulting it to "every industry".
    """
    from aughor.packs.knowledge import knowledge_index
    from aughor.packs.loader import load_pack

    out: list[tuple[str, object]] = []
    for package in knowledge_index().packages:
        try:
            pack = load_pack(package.directory)
        except Exception as e:  # a malformed pack must not cost the others their plays
            from aughor.kernel.errors import tolerate
            tolerate(e, f"skip pack {package.pack_id} while seeding anatomy plays",
                     counter="playbook.pack_play_scan")
            continue
        for play in pack.playbooks:
            out.append((package.pack_id, play))
    return out


def _pack_play_entry(pack_id: str, play) -> PlaybookEntry | None:
    """One `playbooks/*.yaml` play as a `PlaybookEntry`, or None when it carries nothing to act on.

    The id ends in a short DETERMINISTIC digest because `stable_key` strips the last `_`-separated
    segment: the part before it has to be the identity, and re-seeding must not mint a new row for
    a play that has not changed (`_build_entries_for_kb` uses `uuid4` and can only ever run into an
    empty playbook for that reason).
    """
    play_id = (getattr(play, "id", "") or "").strip()
    recommendation = (getattr(play, "recommendation", "") or "").strip()
    if not play_id or not recommendation:
        return None
    from aughor.packs.knowledge import pack_play_source

    operator = (getattr(play, "trigger_operator", "") or "").strip().lower()
    tags = [t for t in (getattr(play, "tags", None) or []) if isinstance(t, str)]
    # A data-quality play is a rule-out the Verifier runs inside a deep report, never a move a
    # person takes — `retriever.is_data_quality` keys on this tag beside a source id, and the
    # default retrieval drops it. Carrying the pack's own `kind` across is what keeps the 486
    # KB rule-outs and a pack's rule-outs the same kind of thing.
    if getattr(play, "kind", "") == "data_quality" and DATA_QUALITY_TAG not in tags:
        tags = [*tags, DATA_QUALITY_TAG]
    digest = hashlib.sha256(f"{pack_id}/{play_id}".encode()).hexdigest()[:6]
    return PlaybookEntry(
        id=f"pack_{_slug(pack_id)}_{_slug(play_id)}_{digest}",
        source_kb_id=pack_play_source(pack_id, play_id),
        trigger_metric=_slug(getattr(play, "trigger_metric", "") or play_id),
        trigger_condition=(getattr(play, "trigger_condition", "") or "").strip(),
        trigger_operator=operator if operator in _TRIGGER_OPERATORS else "any",
        recommendation=recommendation,
        expected_impact=(getattr(play, "expected_impact", "") or "").strip(),
        # The pack names a real owner ("Operations Control", "Credit Risk"); the KB seeder hardcodes
        # "Data Analyst" on every row it writes, which is the column that reads as information and
        # carries none. Do not default this one.
        owner_role=(getattr(play, "owner_role", "") or "").strip(),
        tags=tags,
        status="draft",
    )


def seed_from_packs(path: Path | None = None) -> dict:
    """Seed the playbook with the plays the active knowledge packages declare.

    Idempotent, and shaped like `top_up_data_quality` rather than `seed_from_kb`: it adds into a
    populated playbook, it never rewrites a row a person has edited, and a play somebody DELETED
    stays deleted (`ever_saved_ids`). Returns ``{"added", "kept_deleted", "skipped"}``.
    """
    from aughor.playbook.store import ever_saved_ids, list_entries

    counts = {"added": 0, "kept_deleted": 0, "skipped": 0}
    built: list[PlaybookEntry] = []
    for pack_id, play in _load_all_pack_plays():
        entry = _pack_play_entry(pack_id, play)
        if entry is None:
            counts["skipped"] += 1
            continue
        built.append(entry)

    present = {stable_key(e.id) for e in list_entries(path)}
    ever = {stable_key(entry_id) for entry_id in ever_saved_ids(path)}
    to_save: list[PlaybookEntry] = []
    for entry in built:
        key = stable_key(entry.id)
        if key in present:
            continue
        if key in ever:
            counts["kept_deleted"] += 1
            continue
        to_save.append(entry)
        counts["added"] += 1
    if to_save:
        save_entries(to_save, path)
    return counts


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
