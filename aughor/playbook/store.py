from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from aughor.playbook.models import PlaybookEntry


def _default_path() -> Path:
    """Where the playbook lives — ``AUGHOR_PLAYBOOK_PATH`` overrides.

    Resolved at CALL time, not import, so a deployment can point it somewhere
    writable. Alone among the platform's stores this had no override, and on a
    read-only serverless filesystem every seed and every version append failed
    against the bundle's `data/` — 43 times in one 30-minute window.
    """
    env = os.environ.get("AUGHOR_PLAYBOOK_PATH", "").strip()
    return Path(env) if env else _BUNDLED_PATH


_BUNDLED_PATH = Path(__file__).parent.parent.parent / "data" / "playbook.json"

# A play's CONTENT — what a consumer actually relied on. The receipt fingerprints THESE
# fields only, so a meta-only update (outcomes refreshing the success rate, or a draft→active
# promotion) leaves the receipt — and the version — untouched. Versions move only when the
# advice itself moves.
_CONTENT_FIELDS = (
    "trigger_metric", "trigger_condition", "trigger_operator", "trigger_value",
    "recommendation", "expected_impact", "typical_timeline", "owner_role", "tags",
)
#: Content a play carries only when it has it (IP-1: a data-quality play's cause and fix). Each is
#: fingerprinted when non-empty and left out when empty, so every play that has none keeps the
#: receipt — and the version — it had before these fields existed.
_OPTIONAL_CONTENT_FIELDS = ("cause", "fix")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compute_receipt(entry: PlaybookEntry) -> str:
    """Deterministic content fingerprint pinning WHAT the play recommends, independent of its
    volatile meta (success rate, status, evidence, version). A finding that cites this receipt
    can prove it relied on exactly this content — even after the play is later revised."""
    payload = {k: getattr(entry, k) for k in _CONTENT_FIELDS}
    payload.update({k: v for k in _OPTIONAL_CONTENT_FIELDS if (v := getattr(entry, k))})
    blob = json.dumps(payload, sort_keys=True, default=str)
    return "pbk_" + hashlib.sha256(blob.encode()).hexdigest()[:16]


def _load_raw(path: Path | None = None) -> list[dict]:
    p = path or _default_path()
    if not p.exists():
        return []
    with open(p) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _save_raw(entries: list[dict], path: Path | None = None) -> None:
    p = path or _default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(entries, f, indent=2)


def list_entries(path: Path | None = None) -> list[PlaybookEntry]:
    return [PlaybookEntry(**e) for e in _load_raw(path)]


def list_active_entries(path: Path | None = None) -> list[PlaybookEntry]:
    return [e for e in list_entries(path) if e.status != "deprecated"]


def get_entry(entry_id: str, path: Path | None = None) -> PlaybookEntry | None:
    for e in _load_raw(path):
        if e.get("id") == entry_id:
            return PlaybookEntry(**e)
    return None


# ── Immutable version log (Governed Dives) ────────────────────────────────────
# An append-only sibling file. Every content change appends a frozen snapshot, so a
# finding that cited version N always resolves to exactly what version N said — the
# play's edit history is auditable and its past advice is never silently rewritten.

def _versions_path(path: Path | None = None) -> Path:
    return (path or _default_path()).parent / "playbook_versions.json"


def _append_version(snapshot: dict, path: Path | None = None) -> None:
    _append_versions([snapshot], path)


def _append_versions(snapshots: list[dict], path: Path | None = None) -> None:
    vp = _versions_path(path)
    vp.parent.mkdir(parents=True, exist_ok=True)
    log = json.load(open(vp)) if vp.exists() else []
    if not isinstance(log, list):
        log = []
    log.extend(snapshots)
    with open(vp, "w") as f:
        json.dump(log, f, indent=2)


def list_versions(entry_id: str, path: Path | None = None) -> list[dict]:
    """Every frozen snapshot of a play, oldest → newest (the Governed-Dive history)."""
    vp = _versions_path(path)
    if not vp.exists():
        return []
    log = json.load(open(vp))
    return [s for s in (log if isinstance(log, list) else []) if s.get("entry_id") == entry_id]


def ever_saved_ids(path: Path | None = None) -> set[str]:
    """Every play id the version log holds a snapshot of, including plays since deleted. An id here and
    not in the playbook is a play a person removed (IP-1's top-up never brings one back)."""
    vp = _versions_path(path)
    if not vp.exists():
        return set()
    log = json.load(open(vp))
    return {str(s["entry_id"]) for s in (log if isinstance(log, list) else []) if s.get("entry_id")}


def get_version(entry_id: str, version: int, path: Path | None = None) -> dict | None:
    """The frozen content of one past version — what a finding citing it actually relied on."""
    for s in list_versions(entry_id, path):
        if s.get("version") == version:
            return s
    return None


def save_entry(entry: PlaybookEntry, path: Path | None = None) -> None:
    """Upsert a play, version-aware. A CONTENT change (new receipt) bumps the version and
    appends an immutable snapshot; a meta-only save (success-rate refresh, status promotion)
    carries the version + receipt forward untouched, so versions track advice, not bookkeeping."""
    save_entries([entry], path)


def save_entries(entries: list[PlaybookEntry], path: Path | None = None) -> None:
    """:func:`save_entry` for many plays, reading and writing the playbook and its version log once.

    Seeding saved one play at a time, and every save rewrote both files: 392 plays took 3.8 s of
    startup, and the time grows with the square of the count."""
    if not entries:
        return
    raw = _load_raw(path)
    index: dict = {}
    for i, e in enumerate(raw):
        index.setdefault(e.get("id"), i)
    snapshots: list[dict] = []
    for entry in entries:
        at = index.get(entry.id)
        prior = raw[at] if at is not None else None
        receipt = compute_receipt(entry)

        if prior is None or prior.get("receipt") != receipt:
            entry.version = (prior.get("version", 0) + 1) if prior else 1
            entry.receipt = receipt
            entry.updated_at = _now_iso()
            snapshots.append({
                "entry_id": entry.id, "version": entry.version, "receipt": receipt,
                "saved_at": entry.updated_at, "content": entry.model_dump(),
            })
        else:
            # content unchanged — preserve the pin from the stored record
            entry.version = prior.get("version", 1)
            entry.receipt = prior.get("receipt") or receipt
            entry.updated_at = prior.get("updated_at", "")

        if at is not None:
            raw[at] = entry.model_dump()
        else:
            index[entry.id] = len(raw)
            raw.append(entry.model_dump())
    if snapshots:
        _append_versions(snapshots, path)
    _save_raw(raw, path)


def emit_playbook_use(entry: PlaybookEntry, *, conn_id: str | None = None,
                      used_in: str | None = None) -> None:
    """Journal that an analysis relied on a play, pinned to its version + receipt — the
    Governed-Dive binding, so a finding's reliance on org knowledge is auditable. Fail-open."""
    try:
        from aughor.kernel.ledger import Ledger
        from aughor.kernel.jobs import current_job_id
        Ledger.default().emit("playbook.use", {
            "entry_id": entry.id, "version": entry.version, "receipt": entry.receipt,
            "trigger_metric": entry.trigger_metric, "used_in": used_in,
        }, conn_id=conn_id, job_id=current_job_id())
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "playbook-use receipt", counter="playbook.use")


def delete_entry(entry_id: str, path: Path | None = None) -> bool:
    raw = _load_raw(path)
    new = [e for e in raw if e.get("id") != entry_id]
    if len(new) == len(raw):
        return False
    _save_raw(new, path)
    return True


def count_entries(path: Path | None = None) -> int:
    return len(_load_raw(path))
