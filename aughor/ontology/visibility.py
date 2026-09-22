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
    return new


def withdraw_exclusion(conn: str, schema: str, table: str) -> bool:
    rows = load_exclusions(conn, schema)
    kept = [e for e in rows if e.table.split(".")[-1].lower() != str(table or "").split(".")[-1].lower()]
    if len(kept) == len(rows):
        return False
    p = _exclusions_path(conn, schema)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump([e.to_dict() for e in kept], sort_keys=False, allow_unicode=True))
    return True


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
    """One sentence a person reads: what is seen, what is measured, what one fix unblocks."""
    parts = []
    if tables.get("basis") == "profiler":
        parts.append(f"sees {tables['mapped']} of {tables['in_scope']} tables ({round(tables['share'] * 100)}%)"
                     + (f", {tables['excluded']} excluded" if tables.get("excluded") else ""))
    else:
        parts.append(f"maps {tables['mapped']} tables; the profiler has not seen this connection, so the denominator is unknown")
    if joins and joins.get("total"):
        parts.append(f"joins measured {joins['measured']} of {joins['total']}")
    if top:
        n = top["holds"]
        parts.append(f"approve `{top['definition']}` and {n} held send{'s' if n != 1 else ''} unblock")
    return " · ".join(parts)
