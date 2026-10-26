"""ROADMAP §6 item 53 (2026-10-25, the look study) — what an entity is used by, as one read.

Three things already know it, each in its own place: the dependents index (Arc OC-1,
`ontology.dependents`) names the automations, processes, rules, actions, links, parts and metrics that
depend on a declaration; the release strip's door (`dashboards.pieces.dashboards_reading`) names every
dashboard whose pieces read it, whoever keeps it; and the SQL audit holds every statement the platform ran.
This module composes them for the entity's own page and stores nothing. What cannot be read is said:
no bound table means nothing is counted, and an unreadable log says so instead of counting zero.

Arc FA, FA-3 (ROADMAP §3.60) folds *usage* in here — one concept, one flag: the reads of the last thirty days, the
day an entity was last read and how many people read it, and every entity of a scope ranked by those reads, the least
read first, for the person cleaning up. Who read is the person the session log names for the run that issued the
statement; a read whose run it does not name is counted and said, never given a reader. A statement naming a table
two entities are read from counts for both, and that is said beside each.
"""
from __future__ import annotations

from typing import Any, Optional

FLAG = "ontology.entity_usage"
#: Calendar months of reads shown, the current one included.
MONTHS = 12
#: Days the recent window covers, today included.
WINDOW_DAYS = 30


def enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def bound_tables(body: dict) -> list[str]:
    """The bare names of the tables an entity is read from, as its detail lists them — a schema prefix dropped,
    so a statement naming ``shop.orders`` and one naming ``orders`` both count."""
    names = {str(b.get("table") or "").rsplit(".", 1)[-1].strip() for b in body.get("bindings") or []}
    return sorted(n for n in names if n)


def entity_tables(entity: Any) -> list[str]:
    """`bound_tables` read off the entity itself, without describing it: its backing's table (none for a keyed
    SELECT) and each further binding's that reads a table."""
    b = entity.backing
    tables = [] if b is not None and b.kind == "query" else \
        [(b.table if b is not None else None) or (entity.source_tables[0] if entity.source_tables else "")]
    tables += [binding.table or "" for binding in entity.bindings or [] if binding.reads != "query"]
    return sorted({str(t).rsplit(".", 1)[-1].strip() for t in tables if t} - {""})


def _owners(graph: Any) -> dict[str, list[str]]:
    """Each bare table name, lower-cased, and the entities read from it."""
    out: dict[str, list[str]] = {}
    for eid, entity in (graph.entities or {}).items():
        for table in entity_tables(entity):
            out.setdefault(table.lower(), []).append(eid)
    return out


def shared(graph: Any, entity_id: str, tables: list[str], owners: Optional[dict] = None) -> list[dict]:
    """The tables of ``entity_id`` that another entity is read from too, each with those entities' names — a statement
    naming one counts for each of them."""
    owners = owners if owners is not None else _owners(graph)
    out = []
    for table in tables:
        others = [o for o in owners.get(table.lower(), []) if o != entity_id]
        if others:
            names = [(graph.entities[o].display_name or o) for o in others if o in graph.entities]
            out.append({"table": table, "with": names})
    return out


def shared_said(rows: list[dict]) -> str:
    if not rows:
        return ""
    return "; ".join(f"a statement naming {r['table']} counts for {', '.join(r['with'])} too" for r in rows) + "."


def window_reads(connection_id: str, tables_by_entity: dict[str, list[str]], *, days: int = WINDOW_DAYS,
                 now: Optional[float] = None) -> dict[str, dict]:
    """For each entity, the audited statements of the last ``days`` days naming its tables: how many, the newest one's
    moment, how many distinct people the session log names for the runs that issued them, and how many of the reads
    name no one (``unattributed``). Raises when the statement log cannot be read; a session log that cannot be read
    leaves ``readers`` None, with why."""
    from aughor.org.context import current_org_id
    from aughor.security.audit import AuditLogger
    org = current_org_id() or None
    raw = AuditLogger.reads_within(connection_id, tables_by_entity, days=days, org_id=org, now=now)
    people: Optional[dict[str, str]] = None
    why = ""
    traced = sorted({run for row in raw.values() for run in row["runs"] if run})
    try:
        from aughor.kernel.ledger import Ledger
        people = Ledger.default().session_people(traced, org_id=org) if traced else {}
    except Exception as exc:  # noqa: BLE001 — the reads still stand; who made them is said as not read
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the session log could not be read for who read an entity", counter="objects.uses.readers")
        why = "Who read them could not be read from the session log."
    out: dict[str, dict] = {}
    for key, row in raw.items():
        entry: dict[str, Any] = {"days": days, "reads": row["reads"], "last_read": row["last_read"]}
        if people is None:
            entry.update({"readers": None, "unattributed": None, "readers_said": why})
        else:
            named = {people[run] for run in row["runs"] if run in people}
            unattributed = sum(n for run, n in row["runs"].items() if run not in people)
            entry.update({"readers": len(named), "unattributed": unattributed})
            if unattributed:
                entry["readers_said"] = (f"Who ran {unattributed:,} of {row['reads']:,} is not recorded — the session "
                                         "log names a person only for the runs it kept.")
        out[key] = entry
    return out


def uses_of(graph: Any, connection_id: str, body: dict, *, days: int = WINDOW_DAYS) -> dict:
    """What the entity ``body`` describes is used by, on ``connection_id``: its dependents, each with how it
    depends; the dashboards reading it; how many audited statements named its tables in each of the last twelve
    months; and the last ``days`` days' reads, last read and readers, with the tables it shares with another entity.
    Every part that could not be read says so beside what was."""
    from aughor.dashboards.pieces import dashboards_reading
    from aughor.kernel.errors import tolerate
    from aughor.ontology.dependents import dependents_of
    from aughor.org.context import current_org_id
    from aughor.security.audit import AuditLogger

    entity_id = str(body.get("id") or "")
    names = {entity_id} if entity_id else set()
    out: dict[str, Any] = {"dependents": dependents_of(graph, connection_id, "entity", entity_id), "dashboards": []}
    try:
        out["dashboards"] = [{"id": row.get("id") or "", "title": row.get("title") or "", "pieces": row.get("pieces") or []}
                             for row in dashboards_reading(connection_id, names, graph=graph)]
    except Exception as exc:  # noqa: BLE001 — the page still lists the rest; the gap is said
        tolerate(exc, "dashboards reading an entity could not be listed; the page says so", counter="objects.uses.dashboards")
        out["dashboards_said"] = "The dashboards could not be listed."
    tables = bound_tables(body)
    reads: dict[str, Any] = {"tables": tables, "months": [], "source": "the platform's log of statements run"}
    if not tables:
        reads["said"] = "No table is bound to it, so nothing is counted."
    else:
        try:
            reads["months"] = AuditLogger.reads_by_month(connection_id, tables, months=MONTHS,
                                                         org_id=current_org_id() or None)
            reads["window"] = window_reads(connection_id, {entity_id: tables}, days=days)[entity_id]
        except Exception as exc:  # noqa: BLE001
            tolerate(exc, "the statement log could not be read for an entity's reads; the page says so",
                     counter="objects.uses.reads")
            reads["said"] = "The log of statements could not be read."
        reads["shared"] = shared(graph, entity_id, tables) if graph is not None else []
        if reads["shared"]:
            reads["shared_said"] = shared_said(reads["shared"])
    out["reads"] = reads
    return out


def ranked_by_reads(graph: Any, connection_id: str, *, days: int = WINDOW_DAYS, now: Optional[float] = None) -> dict:
    """Every entity of ``graph`` with its reads of the last ``days`` days, the least read first — then the longest
    unread, then by name; an entity with no table bound is not counted and comes last, saying so. One scan of the
    statement log for all of them."""
    owners = _owners(graph)
    tables = {eid: entity_tables(e) for eid, e in (graph.entities or {}).items()}
    out: dict[str, Any] = {"days": days, "source": "the platform's log of statements run", "entities": []}
    try:
        window = window_reads(connection_id, {k: v for k, v in tables.items() if v}, days=days, now=now)
    except Exception as exc:  # noqa: BLE001 — the list says the log is unread, never that nothing was read
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the statement log could not be read for the entities' reads", counter="objects.uses.reads")
        out["said"] = "The log of statements could not be read, so no entity's reads are counted."
        window = {}
    rows = []
    for eid, entity in (graph.entities or {}).items():
        row: dict[str, Any] = {"entity": eid, "object_type": entity.api_name, "display_name": entity.display_name or eid,
                               "tables": tables[eid], "part_of": entity.absorbed_into or ""}
        if not tables[eid]:
            row.update({"reads": None, "said": "No table is bound to it, so nothing is counted."})
        elif eid not in window:
            row.update({"reads": None, "said": "Not counted: the log of statements could not be read."})
        else:
            row.update(window[eid])
            row["shared"] = shared(graph, eid, tables[eid], owners)
            if row["shared"]:
                row["shared_said"] = shared_said(row["shared"])
        rows.append(row)
    counted = sorted((r for r in rows if r["reads"] is not None),
                     key=lambda r: (r["reads"], r["last_read"] or "", r["display_name"].lower()))
    out["entities"] = counted + sorted((r for r in rows if r["reads"] is None), key=lambda r: r["display_name"].lower())
    return out
