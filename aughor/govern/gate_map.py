"""The gate map as something a person can read (the 2027 study §V, screen 12) — both halves of it.

IN: every place a statement reaches a warehouse, and how its dialect is handled. That is GM-2's
census, `docs/SQL_DOORS.json`, held to the code by `tests/unit/test_sql_door_census.py` (the walk
finds every door call; the file may not drift from it). This module reads the same file and owns
the one definition of each class — the test imports ``DIALECTS`` from here.

OUT: every law of the departure gate, with what it held and when it last did, counted from the
departure ledger's own rows.

A read. Nothing is decided here, and what cannot be read is said: the census ships with the
source tree, so an install without it says so instead of showing an empty map.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: How a site's statement meets the engine's dialect. The first two are read from the call itself.
DIALECTS: dict[str, str] = {
    "declared": "the call declares sql_dialect='duckdb'; the door translates for an engine that runs SQL as written",
    "forwards": "the call passes on a declaration its caller made",
    "door": "the door's own delegation; the statement was rendered for the engine before it",
    "native": "written for the engine that runs it — a person, the model under the writer rules or a fix prompt that "
              "names the dialect, SQL stored from a run on that engine, a platform branch dispatched on the dialect",
    "generated": "rendered in the engine's dialect, by sqlglot or the dialect-aware quoting helpers",
    "portable": "platform-built with no engine-specific spelling, possibly around a model's or a person's fragment",
    "unstated": "written by a model that was not told the dialect",
    "none": "DuckDB's spelling, or a statement only DuckDB has, sent undeclared: the bug class",
    "not-sql": "a method that shares a door's name and runs no SQL",
}

#: The classes a reader should look at first: a statement nothing declared or told the engine of.
UNGUARDED: tuple[str, ...] = ("none", "unstated")

CENSUS_PATH = Path(__file__).resolve().parents[2] / "docs" / "SQL_DOORS.json"


def _site(key: str, row: dict) -> dict[str, str]:
    path, function, door, label = (key.split("::") + ["", "", "", ""])[:4]
    return {"key": key, "path": path, "function": function, "door": door, "label": label,
            "dialect": str(row.get("dialect") or ""), "author": str(row.get("author") or ""),
            "note": str(row.get("note") or "")}


def door_uses() -> dict[str, Any]:
    """How often each door method was the way a caller came in, and when it last was — for this organisation, from
    the audit store's own count. Counting began the day the count shipped; a door with no row was not used since."""
    try:
        from aughor.org.context import current_org_id
        from aughor.security.audit import DoorCounter
        seen = DoorCounter.totals(org_id=current_org_id() or "default")
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the door-use count could not be read; the map says so", counter="gate_map.door_uses")
        return {"since": None, "doors": {}, "note": "The count of door uses could not be read"}
    since = seen.get("since")
    return {"since": since, "doors": seen.get("doors") or {},
            "note": (f"Uses are counted from {since}; nothing earlier was recorded" if since
                     else "No use has been counted yet; counting began when this map gained the column")}

def statement_doors(path: Path | None = None) -> dict[str, Any]:
    """The census, grouped the two ways a reader asks: by how the dialect is handled, and by which
    door method the call goes through — with the unguarded sites listed by name and reason."""
    path = path or CENSUS_PATH
    try:
        census = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"present": False, "sites": 0, "by_dialect": [], "by_door": [], "unguarded": [],
                "note": "the census of statement doors ships with the source tree and is not on this install"}
    sites = [_site(k, v) for k, v in sorted((census.get("sites") or {}).items())]
    by_dialect: dict[str, int] = {}
    by_door: dict[str, int] = {}
    for s in sites:
        by_dialect[s["dialect"]] = by_dialect.get(s["dialect"], 0) + 1
        by_door[s["door"]] = by_door.get(s["door"], 0) + 1
    used = door_uses()
    return {
        "present": True, "sites": len(sites),
        "by_dialect": [{"dialect": d, "sites": n, "means": DIALECTS.get(d, "")}
                       for d, n in sorted(by_dialect.items(), key=lambda kv: -kv[1])],
        "by_door": [{"door": d, "sites": n, "uses": int((used["doors"].get(d) or {}).get("uses") or 0),
                     "last_used": str((used["doors"].get(d) or {}).get("last_used") or "")}
                    for d, n in sorted(by_door.items(), key=lambda kv: -kv[1])],
        "counted_since": used["since"], "uses_note": used["note"],
        "unguarded": [s for s in sites if s["dialect"] in UNGUARDED],
        "note": ("every place a statement reaches a warehouse, from the code itself; a call the census does not "
                 "list fails the build"),
    }


def departure_laws(*, limit: int = 500) -> dict[str, Any]:
    """Each guard of the departure gate: its law, what a hold by it means, and — over the newest
    ``limit`` departures — how often it passed, held or asked, and when it last held."""
    from aughor.govern import departure_store
    from aughor.govern.departure import ASKED, GUARD_LABELS, GUARDS, HOLDS, PASSED
    from aughor.govern.departure_remedies import REMEDIES, laws

    rows = [departure_store.decode_row(r) for r in departure_store.list_departures(limit=limit)]
    told = laws()
    out = []
    for guard in GUARDS:
        passed = held = asked = 0
        last_held = ""
        for r in rows:
            outcome = str((r.get("guards") or {}).get(guard) or "")
            if outcome == PASSED:
                passed += 1
            elif outcome == HOLDS:
                held += 1
                last_held = max(last_held, str(r.get("ts") or ""))
            elif outcome == ASKED:
                asked += 1
                last_held = max(last_held, str(r.get("ts") or ""))
        law = told.get(guard) or {"law": "", "sentence": ""}
        out.append({"guard": guard, "label": GUARD_LABELS.get(guard, guard), "law": law["law"],
                    "sentence": law["sentence"], "meaning": (REMEDIES.get(guard) or {}).get("meaning", ""),
                    "passed": passed, "held": held, "asked": asked, "last_held": last_held})
    return {"laws": out, "over": len(rows),
            "note": f"counted over the newest {len(rows)} departures; a law with 0 held none of them"}


def gate_map() -> dict[str, Any]:
    return {"statements": statement_doors(), "departures": departure_laws()}
