"""Temporal Tier 3 — incremental re-exploration watermark.

The real "without breaking sweat" lever for *recurring* intelligence: after the first
build, a re-run should scan only the partitions that arrived since last time, not the whole
warehouse. A Monday brief on a 10-year warehouse should scan last week, not 10 years.

We persist, per (connection, table), the max activity timestamp seen on the last run. On
the next run the explorer ANDs ``delta_clause(ts_col, watermark)`` into its scans so only
new rows are read. Best-effort + JSON-backed; a missing/older watermark just means a fuller
scan (never wrong, only less incremental). See docs/ADAPTIVE_TEMPORAL_SCOPE.md §6.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from aughor.db.paths import state_dir

logger = logging.getLogger(__name__)

_PATH = state_dir() / "explore_watermark.json"


def _load() -> dict:
    try:
        if _PATH.exists():
            return json.loads(_PATH.read_text())
    except Exception:
        pass
    return {}


def _save(data: dict) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(data, indent=2, default=str))
    except Exception as exc:
        logger.debug("watermark: save failed: %s", exc)


def get_watermark(connection_id: str, table: str) -> Optional[str]:
    """Return the last-seen max timestamp for (connection, table), or None."""
    return (_load().get(connection_id) or {}).get(table)


def set_watermark(connection_id: str, table: str, ts) -> None:
    """Record the max activity timestamp scanned for (connection, table)."""
    if not ts:
        return
    data = _load()
    data.setdefault(connection_id, {})[table] = str(ts)[:26]
    _save(data)


def clear_watermark(connection_id: str, table: Optional[str] = None) -> None:
    """Forget the watermark for a connection (a table, or all of it) — forces a full scan."""
    data = _load()
    if connection_id not in data:
        return
    if table is None:
        data.pop(connection_id, None)
    else:
        data[connection_id].pop(table, None)
    _save(data)


def clear_schema(connection_id: str, schema: str) -> int:
    """Forget watermarks for every table of a schema (keys are ``schema.table``) —
    used when a schema is removed. Returns the number of table entries dropped."""
    data = _load()
    tables = data.get(connection_id)
    if not tables:
        return 0
    prefix = f"{schema}."
    drop = [t for t in tables if t == schema or t.startswith(prefix)]
    for t in drop:
        tables.pop(t, None)
    if drop:
        _save(data)
    return len(drop)


def delta_clause(ts_col: str, watermark: Optional[str]) -> str:
    """A SQL AND-fragment selecting only rows newer than the watermark, or '' when there's
    no watermark / no timestamp column (→ a full scan)."""
    if not ts_col or not watermark:
        return ""
    safe = str(watermark).replace("'", "")
    return f"{ts_col} > '{safe}'"
