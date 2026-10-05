"""Links into other connections, cited on a claim's page (the 2027 study §V, screen 9; decided
read-only on 2026-10-05, ROADMAP §6 item 42e).

A claim is about one connection. The organisation's ontology — a person's declarations — may say
that a type read from that connection is linked to a type read from another one. This names those
links for a claim, and the claims on the far side that are about the far type. It reads the
declarations and the Record only: no statement runs on either connection.

The organisation's ontology is opened by the door that serves this (`GET /ontology/claim-links/
{claim_id}`, one of the doors that take `?domain=`) and handed in; this module never opens it.

How a claim is tied to a type: by the entities its writer recorded (`extra.entities`), and failing
that by the tables its run warrants read. A claim tied to no type cites no link — the page then
shows no section, rather than an empty one.

A far connection the reader may not see is said, never listed: the link is named with the type on
this side, and the far side reads as withheld.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

#: The most claims on the far side a link cites. The count of all of them is said beside these.
FAR_CLAIMS = 5
#: How many of a far connection's newest claims are read to find the ones about the far type.
FAR_READ = 200


def connection_of(claim: Any) -> str:
    """The connection a claim is about, or "" when it is about something else."""
    about = getattr(claim, "about", None)
    return str(about.key) if about is not None and about.kind == "connection" else ""


def _segments(table: str) -> list[str]:
    return [s.strip().strip('"`').lower() for s in str(table or "").split(".") if s.strip()]


def same_table(a: str, b: str) -> bool:
    """Whether two table names can be the same table: every segment both spell agrees, read from the
    right. `east.sales` is `sales`; `east.sales` is not `west.sales`."""
    x, y = _segments(a), _segments(b)
    n = min(len(x), len(y))
    return n > 0 and x[-n:] == y[-n:]


def _tables_read(claim: Any) -> set[str]:
    from aughor.explorer.scope import tables_in_sql
    found: set[str] = set()
    for w in getattr(claim, "warrants", None) or []:
        if w.kind == "run" and w.detail:
            try:
                found |= {str(t) for t in tables_in_sql(w.detail)}
            except Exception as exc:  # noqa: BLE001 — a statement that cannot be parsed ties the claim to no table
                from aughor.kernel.errors import tolerate
                tolerate(exc, "a run warrant's tables could not be read; the claim is tied by its entities alone",
                         counter="record.cross_links.tables")
    return found


def types_of(claim: Any, graph: Any) -> set[str]:
    """The ids of the ontology's types this claim is about: those read from the claim's own connection
    whose name the claim's writer recorded, or whose table one of its runs read."""
    from aughor.ontology.sources import entity_source

    conn = connection_of(claim)
    if not conn:
        return set()
    named = {str(e).strip().lower() for e in ((getattr(claim, "extra", None) or {}).get("entities") or []) if str(e).strip()}
    tables = _tables_read(claim)
    found = set()
    for e in graph.entities.values():
        if entity_source(graph, e) != conn:
            continue
        backing = (e.backing.table if e.backing is not None else None) or ""
        if e.id.lower() in named or (e.display_name or "").strip().lower() in named \
                or (backing and any(same_table(backing, t) for t in tables)):
            found.add(e.id)
    return found


def _claims_on(conn_id: str) -> list:
    from aughor.record import claims as C
    return C.list_claims(conn_id=conn_id, limit=FAR_READ)


def cross_links(claim: Any, graphs: Iterable[tuple[str, Any]], *, visible: Optional[Callable[[str], bool]] = None,
                claims_on: Optional[Callable[[str], list]] = None) -> list[dict]:
    """Every declared link from a type this claim is about into a type read from another connection.
    One row per link: the two types, the far connection, how many current claims there are about the
    far type and the newest few. ``graphs`` is each domain's name with its ontology, opened by the
    door. ``visible`` says whether the reader may see a connection; a far side they may not is
    ``withheld`` and carries no claim. ``claims_on`` reads a connection's claims from the Record."""
    from aughor.ontology.sources import entity_source

    conn = connection_of(claim)
    if not conn:
        return []
    visible = visible or (lambda _conn: True)
    claims_on = claims_on or _claims_on
    far_cache: dict[str, list] = {}
    out: list[dict] = []
    for domain, graph in graphs:
        mine = types_of(claim, graph)
        if not mine:
            continue
        for rel in graph.relationships.values():
            if rel.traversal != "cross-source":
                continue
            if rel.from_entity in mine:
                near_id, far_id = rel.from_entity, rel.to_entity
            elif rel.to_entity in mine:
                near_id, far_id = rel.to_entity, rel.from_entity
            else:
                continue
            near, far = graph.entities.get(near_id), graph.entities.get(far_id)
            if near is None or far is None:
                continue
            far_conn = entity_source(graph, far)
            row = {"domain": domain, "relationship": rel.id, "name": _link_name(rel),
                   "near_type": near.display_name or near.id, "cardinality": rel.cardinality}
            if not visible(far_conn):
                out.append({**row, "withheld": True, "far_type": "", "far_connection": "", "far_claims": [],
                            "far_claims_total": 0})
                continue
            if far_conn not in far_cache:
                far_cache[far_conn] = [c for c in claims_on(far_conn) if getattr(c, "state", "") != "withdrawn"]
            about_far = [c for c in far_cache[far_conn] if far.id in types_of(c, graph)]
            out.append({**row, "withheld": False, "far_type": far.display_name or far.id,
                        "far_connection": far_conn, "far_claims_total": len(about_far),
                        "far_claims": [{"id": c.id, "text": c.statement.text, "kind": c.kind, "tier": c.tier,
                                        "status": c.status, "as_of": c.as_of} for c in about_far[:FAR_CLAIMS]]})
    return out


def _link_name(rel: Any) -> str:
    try:
        name = rel.business_name()
    except Exception:  # noqa: BLE001 — a link with no readable name is called by its verb
        name = ""
    return str(name or rel.verb or "").replace("_", " ").strip().lower()
