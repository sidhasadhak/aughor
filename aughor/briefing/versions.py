"""Every Briefing kept as of the day it was built (Arc BR-6, ROADMAP §3.48).

**The premise, re-measured 2026-09-27 before this was written.** §3.48 describes "the period
cache … overwrites it when the window moves", which reads as though a Briefing were stored and
replaced. It is not stored at all: `build_period_briefing` returns its result to the caller —
`routers/exploration.py` hands it to the page, `briefing/delivery.py` sends it — and nothing
keeps it. What the caches hold is one layer down: `db/matcache` keeps the QUERIES' rows, and
`knowledge/briefing.briefing_cache` keeps the standing narrative for two hours. So the platform
could not say what it had told someone, because it never wrote it down.

**No new store.** The invariant is one store per concept, and the ledger already keeps versioned
artifacts: `artifact_write` finds the current un-superseded row for a natural key, writes the
next version, and stamps `superseded_by` on the one before — supersede-not-delete, with lineage
and a tenant. A Briefing is exactly that shape, so it becomes an artifact of kind ``briefing``
rather than a fifth thing that keeps history its own way.

**A version is a CHANGE of figures, not a page load.** Opening the Briefing re-runs its queries,
and opening it twice in a minute must not leave two versions — the standing view is re-POSTed on
every mount. So a reading whose figures have not moved writes NOTHING and the as-of stays the
day the figures are actually from; a reading that moves one figure by `NOISE_REL` or more (the
platform's own 5% bar, imported, not re-declared) writes the next version and names what moved.

**Figures, never prose.** The digest reads `measured[].current` only. The narrative is
model-written and varies between runs over identical rows; digesting it would make every visit a
revision and the history meaningless.
"""
from __future__ import annotations

from typing import Any, Optional

#: The artifact kind. A Briefing's history is `artifact_versions(natural_key)`.
KIND = "briefing"


def natural_key(conn_id: str, *, scope_key: str, range_key: str, recipe: str = "") -> str:
    """One Briefing's identity: its scope, its range and the recipe that wrote it.

    The recipe is part of the key because BR-4 gives each horizon a different one — the Day and
    the Week over the same days are two Briefings, not two versions of one.
    """
    parts = [str(conn_id or ""), str(scope_key or ""), str(range_key or ""), str(recipe or "")]
    return "briefing:" + "|".join(p.replace("|", "/") for p in parts)


def figures(briefing: dict) -> dict[str, float]:
    """The comparable numbers in a built Briefing: each measured metric's current value.

    A built Briefing carries them at ``brief["period"]["measured"]`` — `build_period_briefing`
    hands its `measure()` output to `get_briefing` as `period_measure`, and `sheet_lines`, the
    reader that turns a brief into the lines a send departs with, reads exactly that path. The
    top level is accepted too, because that is the shape `measure()` itself returns and a caller
    may hold either. Reading only the top level was this module's first bug: `figures` returned
    `{}` for every real Briefing, so nothing ever differed, and the store would have kept
    version 1 forever while looking like it worked.

    Non-numeric and missing values are skipped rather than coerced — a metric the run could not
    measure is absent, which is a change when it was present before, and `revisions` says so.
    """
    brief = briefing or {}
    rows = ((brief.get("period") or {}).get("measured")
            if isinstance(brief.get("period"), dict) else None)
    if not rows:
        rows = brief.get("measured")
    out: dict[str, float] = {}
    for m in rows or []:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "").strip()
        value = m.get("current")
        if name and isinstance(value, (int, float)) and not isinstance(value, bool):
            out[name] = float(value)
    return out


def revisions(before: dict[str, float], after: dict[str, float]) -> list[dict]:
    """Which figures moved enough to be news, by the platform's own noise band.

    Relative to the LARGER magnitude, the same way the departure gate compares two readings of
    one number — so a move from 0 is a revision and a move to 0 is too, and neither divides by
    zero. A figure that appeared or disappeared is named as such rather than compared.
    """
    from aughor.govern.departure import NOISE_REL

    out: list[dict] = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        if old is None:
            out.append({"name": name, "from": None, "to": new, "what": "first measured"})
        elif new is None:
            out.append({"name": name, "from": old, "to": None, "what": "no longer measured"})
        else:
            scale = max(abs(old), abs(new))
            moved = abs(new - old) / scale if scale else 0.0
            if moved >= NOISE_REL:
                out.append({"name": name, "from": old, "to": new, "what": "moved",
                            "relative": round(moved, 4)})
    return out


def record(conn_id: str, briefing: dict, *, scope_key: str, range_key: str,
           recipe: str = "", as_of: Optional[str] = None) -> dict:
    """Keep this reading of a Briefing. Idempotent while its figures have not moved.

    Returns what happened, never raising: ``kept`` is False when nothing was written, and the
    caller still gets the version the reader should be shown. Observability must not break the
    Briefing it observes, so every failure returns an empty verdict instead of propagating.
    """
    key = natural_key(conn_id, scope_key=scope_key, range_key=range_key, recipe=recipe)
    now = as_of or _now()
    try:
        from aughor.kernel.ledger import Ledger
        ledger = Ledger.default()
        latest = ledger.artifact_latest(key)
        current = figures(briefing)
        if latest is not None:
            prior = figures((latest.get("payload") or {}).get("briefing") or {})
            moved = revisions(prior, current)
            if not moved:
                # The same figures. The as-of belongs to the day they are FROM, not to this
                # visit, so nothing is written and the reader keeps the original stamp.
                return {"kept": False, "version": latest.get("version"),
                        "artifact_id": latest.get("id"), "as_of": _as_of_of(latest),
                        "revisions": [], "first_as_of": _first_as_of(ledger, key)}
        else:
            moved = revisions({}, current)
        art_id = ledger.artifact_write(
            KIND, key, {"briefing": briefing, "as_of": now, "revisions": moved,
                        "scope_key": scope_key, "range_key": range_key, "recipe": recipe},
            conn_id=conn_id,
            lineage=[("supersedes", latest["id"], "figures moved")] if latest else None)
        return {"kept": True, "version": (latest.get("version", 0) if latest else 0) + 1,
                "artifact_id": art_id, "as_of": now, "revisions": moved,
                "first_as_of": _first_as_of(ledger, key) or now}
    except Exception as exc:  # noqa: BLE001 — a Briefing must render even if its history cannot
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the Briefing is served whether or not its version could be kept",
                 counter="briefing.version.write")
        return {"kept": False, "version": None, "artifact_id": "", "as_of": now,
                "revisions": [], "first_as_of": ""}


def history(conn_id: str, *, scope_key: str, range_key: str, recipe: str = "",
            limit: int = 50) -> list[dict]:
    """Every version of one Briefing, newest first. Empty on any trouble."""
    key = natural_key(conn_id, scope_key=scope_key, range_key=range_key, recipe=recipe)
    try:
        from aughor.kernel.ledger import Ledger
        return Ledger.default().artifact_versions(key, limit=limit)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a Briefing's history is additive; the page stands without it",
                 counter="briefing.version.read")
        return []


def as_of_line(verdict: dict) -> str:
    """What the page says above a Briefing — "as of 15 September · revised 12 October".

    The revision half appears only when there IS one: a first version says only its as-of, which
    is the honest reading of a Briefing nobody has had to correct.
    """
    first = _day(verdict.get("first_as_of") or verdict.get("as_of") or "")
    latest = _day(verdict.get("as_of") or "")
    if not first:
        return ""
    if latest and latest != first:
        return f"as of {first} · revised {latest}"
    return f"as of {first}"


def _first_as_of(ledger: Any, key: str) -> str:
    versions = ledger.artifact_versions(key, limit=100)
    if not versions:
        return ""
    oldest = min(versions, key=lambda v: int(v.get("version") or 0))
    return _as_of_of(oldest)


def _as_of_of(row: dict) -> str:
    return str((row.get("payload") or {}).get("as_of") or row.get("created_at") or "")


def _day(stamp: str) -> str:
    return str(stamp or "")[:10]


def _now() -> str:
    from aughor.util.time import now_iso_z
    return now_iso_z()
