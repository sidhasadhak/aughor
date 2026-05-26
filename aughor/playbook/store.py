from __future__ import annotations

import json
from pathlib import Path

from aughor.playbook.models import PlaybookEntry

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "playbook.json"


def _load_raw(path: Path | None = None) -> list[dict]:
    p = path or _DEFAULT_PATH
    if not p.exists():
        return []
    with open(p) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _save_raw(entries: list[dict], path: Path | None = None) -> None:
    p = path or _DEFAULT_PATH
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


def save_entry(entry: PlaybookEntry, path: Path | None = None) -> None:
    raw = _load_raw(path)
    for i, e in enumerate(raw):
        if e.get("id") == entry.id:
            raw[i] = entry.model_dump()
            _save_raw(raw, path)
            return
    raw.append(entry.model_dump())
    _save_raw(raw, path)


def delete_entry(entry_id: str, path: Path | None = None) -> bool:
    raw = _load_raw(path)
    new = [e for e in raw if e.get("id") != entry_id]
    if len(new) == len(raw):
        return False
    _save_raw(new, path)
    return True


def count_entries(path: Path | None = None) -> int:
    return len(_load_raw(path))
