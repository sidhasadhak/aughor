"""Persistent column type overrides — survives DuckDB ALTER COLUMN limitations."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_OVERRIDES_FILE = Path(__file__).parent.parent.parent / "data" / "type_overrides.json"


def _load() -> dict:
    if _OVERRIDES_FILE.exists():
        return json.loads(_OVERRIDES_FILE.read_text())
    return {}


def _save(data: dict) -> None:
    _OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _OVERRIDES_FILE.write_text(json.dumps(data, indent=2))


def get_override(conn_id: str, table: str, column: str) -> Optional[str]:
    """Return the user-specified type for a column, or None if not overridden."""
    data = _load()
    return data.get(conn_id, {}).get(table, {}).get(column)


def set_override(conn_id: str, table: str, column: str, new_type: str) -> None:
    """Store a user-specified type override."""
    data = _load()
    data.setdefault(conn_id, {}).setdefault(table, {})[column] = new_type
    _save(data)


def get_table_overrides(conn_id: str, table: str) -> dict[str, str]:
    """Return all type overrides for a given table."""
    data = _load()
    return data.get(conn_id, {}).get(table, {})


def apply_overrides(conn_id: str, table: str, columns: list[dict]) -> list[dict]:
    """Apply stored type overrides to a column list (mutates in-place)."""
    overrides = get_table_overrides(conn_id, table)
    if not overrides:
        return columns
    for c in columns:
        if c["name"] in overrides:
            c["type"] = overrides[c["name"]]
    return columns
