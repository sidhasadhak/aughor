"""ROADMAP §6 item 53 (2026-10-25, the look study) — what an entity is used by, as one read.

Three things already know it, each in its own place: the dependents index (Arc OC-1,
`ontology.dependents`) names the automations, processes, rules, actions, links, parts and metrics that
depend on a declaration; the release strip's door (`dashboards.pieces.dashboards_reading`) names every
dashboard whose pieces read it, whoever keeps it; and the SQL audit holds every statement the platform ran.
This module composes them for the entity's own page and stores nothing. What cannot be read is said:
no bound table means nothing is counted, and an unreadable log says so instead of counting zero.
"""
from __future__ import annotations

from typing import Any

FLAG = "ontology.entity_usage"
#: Calendar months of reads shown, the current one included.
MONTHS = 12


def enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def bound_tables(body: dict) -> list[str]:
    """The bare names of the tables an entity is read from, as its detail lists them — a schema prefix dropped,
    so a statement naming ``shop.orders`` and one naming ``orders`` both count."""
    names = {str(b.get("table") or "").rsplit(".", 1)[-1].strip() for b in body.get("bindings") or []}
    return sorted(n for n in names if n)


def uses_of(graph: Any, connection_id: str, body: dict) -> dict:
    """What the entity ``body`` describes is used by, on ``connection_id``: its dependents, each with how it
    depends; the dashboards reading it; and how many audited statements named its tables in each of the
    last twelve months. Every part that could not be read says so beside what was."""
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
        except Exception as exc:  # noqa: BLE001
            tolerate(exc, "the statement log could not be read for an entity's reads; the page says so",
                     counter="objects.uses.reads")
            reads["said"] = "The log of statements could not be read."
    out["reads"] = reads
    return out
