"""CB-5 (2026-09-23) — show how much of the business the platform can see.

Codos puts one number in front of the executive: the share of the company's working context that
AI can see, and the single gap holding up the most work. Aughor computed pieces of this and showed
none of them: `declarations.Coverage` (the share of tables mapped to business objects, declared
exclusions out of the denominator, banded) was imported only by its own test, and the departure
gate held sends for a missing approved definition without anyone counting which definition held the
most. On 2026-09-18, on theLook, one missing approved `revenue` definition held the Slack send,
floored confidence and warned on every revenue answer — and nothing on screen said that this one
definition was the most valuable thing to fix.

Two numbers, both deterministic, no model:
- **tables**: the profiler's table universe (`profile_cache.latest_profiled_tables`) against the
  ontology's mapped tables, with the people-declared exclusions removed from the denominator. A
  connection never profiled has no honest denominator, and the answer says so instead of 100%.
- **definitions**: the held departures grouped by the definition that would clear them
  (`checks.definition_missing`, recorded structurally since CB-5; older rows parsed from the
  guard's own sentence), so "approve `revenue` and N sends unblock" is a count, not a guess.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import yaml

from aughor.ontology.declarations import EXCLUSION_REASONS, Coverage, Exclusion, coverage, exclusion_from

EXCLUSIONS_FILE = "table_exclusions.yaml"
#: An exclusion of this "table" turns off the WHOLE schema (exploration principles §6, 2026-10-08).
SCHEMA_WIDE = "*"
HELD_STATES = ("held", "held_probation", "held_owner")
_UNAPPROVED_RE = re.compile(r"(?:^|; )(.+?) is stated with a number and its definition is [\w ]+, not approved")
_UNDEFINED_RE = re.compile(r"'(.+?)' is stated with a number and no approved metric defines it")


# ── exclusions: a person says "this table is not required" ─────────────────────

def _exclusions_path(conn: str, schema: str) -> Path:
    from aughor.ontology.recommendations import recommendations_root, safe_name
    return recommendations_root() / safe_name(conn) / safe_name(schema or "default") / EXCLUSIONS_FILE


def load_exclusions(conn: str, schema: str) -> list[Exclusion]:
    p = _exclusions_path(conn, schema)
    if not p.exists():
        return []
    try:
        raw = yaml.safe_load(p.read_text()) or []
    except Exception as exc:  # noqa: BLE001 — an unreadable file excludes nothing, with a trace
        from aughor.kernel.errors import tolerate
        tolerate(exc, "table exclusions could not be read; none applied", counter="visibility.exclusions")
        return []
    out = []
    for d in raw if isinstance(raw, list) else []:
        e = exclusion_from(d) if isinstance(d, dict) else None
        if e is not None:
            out.append(e)
    return out


def declare_exclusion(conn: str, schema: str, table: str, reason: str, *, note: str = "", declared_by: str = "") -> Exclusion:
    """Declare a table out of scope with one of the honest reasons. Replaces an earlier declaration
    for the same table. Raises ``ValueError`` for an empty table or an unknown reason."""
    t = str(table or "").strip()
    if not t:
        raise ValueError("a table is required")
    if reason not in EXCLUSION_REASONS:
        raise ValueError(f"the reason must be one of {', '.join(EXCLUSION_REASONS)}")
    rows = [e for e in load_exclusions(conn, schema) if e.table.split(".")[-1].lower() != t.split(".")[-1].lower()]
    new = Exclusion(table=t, reason=reason, note=" ".join((note or "").split()), declared_by=declared_by or "")
    rows.append(new)
    p = _exclusions_path(conn, schema)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump([e.to_dict() for e in rows], sort_keys=False, allow_unicode=True))
    _changed(conn)
    return new


def withdraw_exclusion(conn: str, schema: str, table: str) -> bool:
    rows = load_exclusions(conn, schema)
    kept = [e for e in rows if e.table.split(".")[-1].lower() != str(table or "").split(".")[-1].lower()]
    if len(kept) == len(rows):
        return False
    p = _exclusions_path(conn, schema)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump([e.to_dict() for e in kept], sort_keys=False, allow_unicode=True))
    _changed(conn)
    return True


# ── excluded means excluded (exploration principles §6, 2026-10-08) ───────────
#
# A table or schema a person turned off is never read on the platform's own initiative or in an
# answer: the Explorer does not explore it, and neither Investigation nor Quick analysis queries
# it. Enforced at the door every statement passes (`db.connection._security_pre`), at the schema
# text every mode reads (`open_connection` / `render_raw_schema`), and at the explorer's own table
# lists. A person may still read it themselves: the SQL editor and the Catalog's own reads (the labels
# `kernel/registries/exclusions.PERSON_LABELS` names). The platform reads these through that seam; the
# agent registers them there at bootstrap (`agent/bootstrap._register_exclusions`).

_CACHE_SECONDS = 5.0
_cache: dict[str, tuple[float, dict[str, dict[str, Exclusion]]]] = {}


def _changed(conn: str) -> None:
    """A declaration changed: drop the lookup and the cached schema text that still lists the table."""
    _cache.pop(conn, None)
    try:
        from aughor.routers._shared import invalidate_schema_cache
        invalidate_schema_cache(conn)
    except Exception as exc:  # noqa: BLE001 — the text expires on its own within minutes
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the schema cache could not be dropped after an exclusion changed",
                 counter="visibility.exclusion_cache")


def connection_exclusions(conn: str) -> dict[str, dict[str, Exclusion]]:
    """Every exclusion of a connection: ``{schema dir: {bare table or "*": Exclusion}}``. Read on
    every statement, so held for a few seconds; a write in this process drops it at once."""
    import time
    now = time.monotonic()
    hit = _cache.get(conn)
    if hit and hit[0] > now:
        return hit[1]
    out: dict[str, dict[str, Exclusion]] = {}
    try:
        from aughor.ontology.recommendations import recommendations_root, safe_name
        root = recommendations_root() / safe_name(conn)
        if root.is_dir():
            for f in root.glob(f"*/{EXCLUSIONS_FILE}"):
                rows = load_exclusions(conn, f.parent.name)
                if rows:
                    out[f.parent.name] = {e.table.split(".")[-1].lower(): e for e in rows}
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "exclusions could not be listed; none applied", counter="visibility.exclusions_list")
    _cache[conn] = (now + _CACHE_SECONDS, out)
    return out


def excluded(conn: str, schema: Optional[str], table: str = "") -> Optional[Exclusion]:
    """The exclusion that turns this table (or, with no table, this schema) off, or None.
    ``schema`` None means the statement did not say and the door did not know: any schema of the
    connection that turned a table of that name off answers — a refusal the reader can see beats a
    read they were promised would not happen — but a schema turned off wholesale cannot claim a
    table it may not hold. ``default`` is where a single-schema connection's declarations were
    filed before schemas were named, so it is read beside the schema's own."""
    every = connection_exclusions(conn)
    if not every:
        return None
    from aughor.ontology.recommendations import safe_name
    bare = str(table or "").split(".")[-1].lower()
    if not schema:
        for rows in every.values():
            if bare and bare in rows:
                return rows[bare]
        return None
    for d in dict.fromkeys([safe_name(schema), "default"]):
        rows = every.get(d) or {}
        hit = rows.get(SCHEMA_WIDE) or (rows.get(bare) if bare else None)
        if hit is not None:
            return hit
    return None


def without_excluded(conn: str, schema_text: str, *, default_schema: Optional[str] = None) -> str:
    """The schema text with every table a person turned off taken out; unchanged, byte for byte,
    when the connection turned nothing off."""
    if not schema_text or not connection_exclusions(conn):
        return schema_text
    from aughor.db.schema_render import without_tables

    def _off(name: str) -> bool:
        parts = str(name).split(".")
        schema = parts[-2] if len(parts) >= 2 else default_schema
        return excluded(conn, schema, parts[-1]) is not None

    return without_tables(schema_text, _off)


def is_table_off(conn: str, schema: Optional[str], table: str) -> bool:
    """Whether a person turned this table — or its schema — off."""
    return excluded(conn, schema, table) is not None


def refusal_for(conn: str, sql: str, dialect: Optional[str], *, default_schema: Optional[str] = None) -> str:
    """The sentence a statement naming an excluded table is refused with, or "" when it names none."""
    if not connection_exclusions(conn):
        return ""
    from aughor.sql.tables import extract_tables
    for ref in sorted(extract_tables(sql, dialect), key=lambda r: r.qualified()):
        schema = ref.schema or default_schema
        hit = excluded(conn, schema, ref.table)
        if hit is not None:
            name = ref.qualified() if ref.schema else (f"{schema}.{ref.table}" if schema else ref.table)
            what = "its schema is" if hit.table == SCHEMA_WIDE else "it is"
            return (f"[EXCLUDED] {name} is turned off for analysis — {what} excluded "
                    f"({hit.reason.replace('_', ' ')}{', by ' + hit.declared_by if hit.declared_by else ''}). "
                    "Turn it back on in the Catalog to use it.")
    return ""


# ── tables: the share the ontology maps ────────────────────────────────────────

def mapped_tables(graph) -> list[str]:
    out: set[str] = set()
    for ent in (getattr(graph, "entities", {}) or {}).values():
        for t in (getattr(ent, "source_tables", None) or []):
            if str(t).strip():
                out.add(str(t))
    return sorted(out)


def table_coverage(conn: str, schema: str, graph, *, universe: Optional[list[str]] = None) -> dict:
    """``Coverage.to_dict()`` plus ``basis``, the unmapped tables and the exclusions. ``universe`` is
    the profiler's table list (injectable); when it is empty the denominator is unknown and the
    dict says so rather than reporting a mapped share of nothing."""
    if universe is None:
        from aughor.tools.profile_cache import latest_profiled_tables
        universe = latest_profiled_tables(conn)
    mapped = mapped_tables(graph) if graph is not None else []
    exclusions = load_exclusions(conn, schema)
    if any(e.table == SCHEMA_WIDE for e in exclusions):
        # the whole schema is turned off: every table of it is out of the denominator
        whole = next(e for e in exclusions if e.table == SCHEMA_WIDE)
        exclusions = [Exclusion(table=str(t), reason=whole.reason, note=whole.note, declared_by=whole.declared_by)
                      for t in (universe or [])] + [e for e in exclusions if e.table != SCHEMA_WIDE]
    if not universe:
        cov = Coverage(total=len(mapped), mapped=len(mapped), excluded=0)
        return {**cov.to_dict(), "basis": "unknown", "share": None, "band": "unknown",
                "unmapped": [], "exclusions": [e.to_dict() for e in exclusions],
                "note": "this connection has not been profiled; the platform cannot say how many tables it does not see"}
    cov = coverage(universe, mapped, exclusions)
    bare = lambda t: str(t).split(".")[-1].lower()  # noqa: E731
    mapped_set = {bare(t) for t in mapped}
    excluded_set = {bare(e.table) for e in exclusions}
    unmapped = sorted(t for t in universe if bare(t) not in mapped_set and bare(t) not in excluded_set)
    return {**cov.to_dict(), "basis": "profiler", "unmapped": unmapped,
            "exclusions": [e.to_dict() for e in exclusions], "note": ""}


# ── definitions: the one missing definition holding the most back ──────────────

def missing_definitions_of(row: dict) -> list[str]:
    """The definitions that would clear a held departure: the structural record when the row has
    one (CB-5 onward), else the guard's own sentence read back."""
    try:
        checks = json.loads(row.get("checks") or "{}") or {}
    except ValueError:
        checks = {}
    structural = str(checks.get("definition_missing") or "")
    if structural:
        return [x.strip() for x in structural.split(" · ") if x.strip()]
    summary = str(checks.get("definition") or "")
    found = [m.strip().lower() for m in _UNAPPROVED_RE.findall(summary)]
    found += [m.strip() for m in _UNDEFINED_RE.findall(summary)]
    out: list[str] = []
    for f in found:
        if f and f not in out:
            out.append(f)
    return out


def definition_holds(conn_id: str, *, rows: Optional[list[dict]] = None, limit: int = 500) -> list[dict]:
    """Held departures on this connection grouped by the definition that would clear them, most
    first: ``[{definition, holds, automations, latest}]``. ``rows`` is injectable for tests."""
    if rows is None:
        from aughor.govern.departure_store import list_departures
        rows = list_departures(states=list(HELD_STATES), limit=limit)
    groups: dict[str, dict] = {}
    for r in rows:
        if conn_id and str(r.get("conn_id") or "") != conn_id:
            continue
        if str(r.get("verdict") or ""):
            continue          # a marked departure has had its say
        for name in missing_definitions_of(r):
            g = groups.setdefault(name, {"definition": name, "holds": 0, "automations": set(), "latest": ""})
            g["holds"] += 1
            if r.get("automation_id"):
                g["automations"].add(str(r["automation_id"]))
            g["latest"] = max(g["latest"], str(r.get("ts") or ""))
    out = [{**g, "automations": sorted(g["automations"])} for g in groups.values()]
    out.sort(key=lambda g: (-g["holds"], g["definition"]))
    return out


def visibility(conn: str, schema: str, graph, *, context_graph=None, universe: Optional[list[str]] = None,
               held_rows: Optional[list[dict]] = None) -> dict:
    """The number and the gap, together: how much the platform sees and what one fix would unblock."""
    tables = table_coverage(conn, schema, graph, universe=universe)
    joins = None
    if context_graph is not None:
        try:
            from aughor.ontology.graph_warrant import audit
            a = audit(context_graph)
            joins = {"total": a["totals"]["joins"], "measured": (a.get("edges_by_kind", {}).get("joins_on", {}) or {}).get("measured", 0),
                     "share": a.get("joins_measured_share", 0.0)}
        except Exception as exc:  # noqa: BLE001 — the joins line is additive
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the joins warrant audit is best-effort for the visibility line", counter="visibility.joins")
    definitions = definition_holds(conn, rows=held_rows)
    top = definitions[0] if definitions else None
    return {"tables": tables, "joins": joins, "definitions": definitions, "top_blocker": top,
            "line": visibility_line(tables, joins, top)}


def visibility_line(tables: dict, joins: Optional[dict], top: Optional[dict]) -> str:
    """One sentence a person reads: what is seen, what is checked, what one approval lets through. In a business
    reader's words (the usability walk-through, 2026-10-09, read "joins measured 9 of 9" and "approve `revenue` and 4
    held sends unblock" as the builder's language); the precise terms stay in the line's hover detail."""
    parts = []
    if tables.get("basis") == "profiler":
        parts.append(f"Reads {tables['mapped']} of your {tables['in_scope']} tables"
                     + (f" ({tables['excluded']} set aside)" if tables.get("excluded") else ""))
    else:
        parts.append(f"Reads {tables['mapped']} tables — how many this connection holds is not known yet")
    if joins and joins.get("total"):
        measured, total = joins["measured"], joins["total"]
        parts.append(f"all {total} links checked" if measured == total else f"{measured} of {total} links checked")
    if top:
        n = top["holds"]
        parts.append(f"{n} message{'s wait' if n != 1 else ' waits'} for you to approve '{top['definition']}'")
    return " · ".join(parts)
