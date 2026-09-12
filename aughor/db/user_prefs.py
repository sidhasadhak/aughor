"""SP-3 (§3.11) — the per-user preferences store: Arc SP's ONE new store.

The platform has org-level settings, per-connection settings, and — until this file —
no per-USER anything: theme lived in one browser's localStorage and followed nobody.
This store is deliberately tiny: a keyed (org, user, key) → JSON value table with a
CLOSED key registry, because "preferences" is where schemaless key/value stores go to
rot. An unknown key is a 422 naming the known ones, never a silent write.

The custody line (§3.11): a preference is a COSMETIC, self-scoped write — it changes
how the platform looks to YOU and nothing about what runs or what others see — so it
applies instantly, with no proposal. Anything that outgrows that sentence does not
belong in this store.

Resolution is PER CALL, never at import: three import-time env freezes have now been
paid for in this repo (`resolve_db_path` at module level, `vocabulary._ROOT`), and a
store born after those lessons does not get to re-learn them.

The user key: ``current_user_id()`` when the identity middleware pinned one, else
``"local"`` — a single-seat deployment has one person, and "" as a key would make
every anonymous caller share a row invisibly. When VA-10 lands a real auth model,
identified users simply shard out of "local" with no migration.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from aughor.db.sqlite_util import resolve_db_path
from aughor.util.time import now_iso as _now

_LOCK = threading.Lock()

#: The closed registry: key → (validator, human description). A validator returns the
#: normalized value or raises ValueError with a sentence the 422 can carry verbatim.
def _one_of(*allowed: str):
    def check(v: Any) -> str:
        s = str(v or "").strip().lower()
        if s not in allowed:
            raise ValueError(f"must be one of {', '.join(allowed)}")
        return s
    return check


def _connection_id(v: Any) -> str:
    s = str(v or "").strip()
    if not s:
        raise ValueError("must be a connection id")
    from aughor.db.registry import list_connections
    known = {c.get("id") for c in list_connections()}
    if s not in known:
        raise ValueError(f"unknown connection '{s}'")
    return s


#: How many ontology maps one person's arrangement is kept for, and how many cards on one map. Caps, because
#: this value is the one key here that a UI writes on every drag rather than a person choosing from a list.
MAX_MAPS = 24
MAX_CARDS = 300


def _map_layout(v: Any) -> dict:
    """ON-3b — where a person dragged the cards on the ontology map, per connection and schema:
    ``{"<connection>:<schema>": {"<object type>": {"x": <number>, "y": <number>}}}``. Cosmetic and self-scoped,
    which is this store's whole custody line: it changes where YOU see a card and nothing about what runs."""
    import math
    if not isinstance(v, dict):
        raise ValueError("must be an object of maps, keyed by '<connection>:<schema>'")
    if len(v) > MAX_MAPS:
        raise ValueError(f"keeps at most {MAX_MAPS} maps; this one carries {len(v)}")
    out: dict[str, dict] = {}
    for scope, cards in v.items():
        key = str(scope or "").strip()
        if not key or len(key) > 200:
            raise ValueError("each map is keyed by '<connection>:<schema>'")
        if not isinstance(cards, dict):
            raise ValueError(f"'{key}' must map an object type to its position")
        if len(cards) > MAX_CARDS:
            raise ValueError(f"'{key}' places {len(cards)} cards; at most {MAX_CARDS} are kept")
        placed: dict[str, dict] = {}
        for name, at in cards.items():
            try:
                x, y = float(at["x"]), float(at["y"])          # type: ignore[index]
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                raise ValueError(f"'{name}' needs a numeric x and y") from exc
            if not (math.isfinite(x) and math.isfinite(y)):
                raise ValueError(f"'{name}' needs a finite x and y")
            placed[str(name)[:200]] = {"x": x, "y": y}
        out[key] = placed
    return out


ALLOWED_KEYS: dict[str, tuple] = {
    "theme": (_one_of("dark", "light", "system"), "UI theme"),
    "density": (_one_of("comfortable", "compact"), "layout density"),
    "default_connection": (_connection_id, "connection new conversations open on"),
    "ontology_map_layout": (_map_layout, "where you dragged the cards on the ontology map"),
}


def _db_path() -> str:
    # Per call, on purpose — see the module docstring's paid-for lessons.
    return str(resolve_db_path("AUGHOR_USER_PREFS_DB",
                               Path(__file__).parent.parent.parent / "data" / "user_prefs.db"))


def _conn() -> sqlite3.Connection:
    from aughor.db.backend import connect_store
    c = connect_store(_db_path())
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_prefs (
            org_id     TEXT NOT NULL,
            user_id    TEXT NOT NULL,
            key        TEXT NOT NULL,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (org_id, user_id, key)
        )
    """)
    return c


def _scope() -> tuple[str, str]:
    from aughor.org.context import current_org_id, current_user_id
    return current_org_id() or "default", current_user_id() or "local"


def get_preferences() -> dict:
    """The caller's stored preferences, keys absent when never set — an absent key means
    "the client's default applies", and only an explicit value means a choice was made."""
    org, user = _scope()
    with _LOCK:
        c = _conn()
        try:
            rows = c.execute(
                "SELECT key, value FROM user_prefs WHERE org_id=? AND user_id=?",
                (org, user)).fetchall()
        finally:
            c.close()
    out: dict[str, Any] = {}
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except (TypeError, ValueError) as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"unreadable preference row '{r['key']}' skipped on read",
                     counter="user_prefs.unreadable")
    return {"user": user, "org": org, "preferences": out,
            "known_keys": {k: desc for k, (_v, desc) in ALLOWED_KEYS.items()}}


def set_preference(key: str, value: Any) -> dict:
    """Set one preference for the caller. Raises ValueError on an unknown key or a value
    the key's validator refuses — the caller turns that into a 422 or a tool refusal."""
    k = str(key or "").strip()
    if k not in ALLOWED_KEYS:
        raise ValueError(
            f"unknown preference '{k}' — known keys: {', '.join(sorted(ALLOWED_KEYS))}")
    validator, _desc = ALLOWED_KEYS[k]
    normalized = validator(value)
    org, user = _scope()
    with _LOCK:
        c = _conn()
        try:
            c.execute(
                "INSERT INTO user_prefs (org_id, user_id, key, value, updated_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(org_id, user_id, key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (org, user, k, json.dumps(normalized), _now()))
            c.commit()
        finally:
            c.close()
    return get_preferences()
