"""DE-4 (ROADMAP §3.51; §6 item 37(f)) — column lineage ON THE RECEIPT.

The receipt already records the tables a statement read as ``("input", "table:t", None)``.
This module adds, beside them, one row per physical column the statement read —

    ("column", "column:<table>.<column>", '{"roles":["output","filter"],"confidence":"certain","as":["n"]}')

— and one row that says whether columns were traced at all —

    ("lineage", "level:column", None)            columns traced
    ("lineage", "level:table", "<why>")           tables only: no schema, a SELECT * over several
                                                  tables, a statement sqlglot could not qualify

so a reader can tell "read no column" from "columns were not traced", and an older receipt
with neither row reads as *not traced*. An output that rests on a table and no column — a
``COUNT(*)`` — is a ``("column", "table:<table>", …)`` row with a note, never dropped.

No store of its own: the Ledger's lineage table holds the edges (one store per concept).
Nothing here raises into an answer path; a producer that cannot trace writes its tables as
before and the level row says so.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

RELATION = "column"
LEVEL_RELATION = "lineage"
_RANK = {"certain": 3, "likely": 2, "possible": 1}


def dialect_for_connection(connection_id: str | None) -> Optional[str]:
    """The connection's declared dialect from its class, no connection opened; None when the
    type is unknown, which parses generically (the door already proved the statement parses)."""
    if not connection_id:
        return None
    try:
        from aughor.db import registry
        from aughor.db.connection import connection_traits
        row = None
        for c in registry.list_connections():
            if str(c.get("id")) == str(connection_id):
                row = c
                break
        if not row:
            return None
        return connection_traits(str(row.get("type") or ""))["dialect"]
    except Exception:
        return None


def column_edges(sqls: Iterable[str], *, dialect: str | None = None, schema_text: str | None = None,
                 schema_map: dict | None = None, limit: int = 6) -> list[tuple[str, str, Optional[str]]]:
    """The Ledger lineage rows for the columns these statements read. Empty for no statements."""
    statements = [s for s in (sqls or []) if s][:limit]
    if not statements:
        return []
    from aughor.sql.lineage import column_lineage

    if schema_map is None and schema_text:
        try:
            from aughor.db.schema_render import sqlglot_schema
            schema_map = sqlglot_schema(schema_text)
        except Exception:
            schema_map = None

    cols: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    level = "column"
    for sql in statements:
        try:
            lin = column_lineage(sql, dialect=dialect, schema=schema_map or None)
        except Exception as exc:  # a tracer that fails must not take the receipt with it
            level = "table"
            notes.append(f"lineage failed ({type(exc).__name__}); tables only")
            continue
        if lin.level == "table":
            level = "table"
            if lin.note:
                notes.append(lin.note)
            continue
        if lin.note:
            notes.append(lin.note)
        for e in lin.edges():
            if not e.get("table"):
                continue
            ref = f"column:{e['table']}.{e['column']}" if e.get("column") else f"table:{e['table']}"
            slot = cols.setdefault(ref, {"roles": set(), "confidence": None, "as": set()})
            slot["roles"].add(e["role"])
            if e.get("as"):
                slot["as"].add(e["as"])
            if e.get("note"):
                slot["note"] = e["note"]
            c = e.get("confidence")
            if c and (slot["confidence"] is None or _RANK[c] > _RANK[slot["confidence"]]):
                slot["confidence"] = c

    rows: list[tuple[str, str, Optional[str]]] = []
    for ref in sorted(cols):
        s = cols[ref]
        detail: dict[str, Any] = {"roles": sorted(s["roles"]), "confidence": s["confidence"]}
        if s["as"]:
            detail["as"] = sorted(s["as"])
        if s.get("note"):
            detail["note"] = s["note"]
        rows.append((RELATION, ref, json.dumps(detail, separators=(",", ":"))))
    note = "; ".join(dict.fromkeys(notes)) or None
    rows.append((LEVEL_RELATION, f"level:{level}", note))
    return rows


def payload_columns(rows: Iterable[tuple[str, str, Optional[str]]]) -> list[str]:
    """``table.column`` for every column row — the compact form the receipt payload and the
    context graph's finding node carry, so `govern/lineage.py` reads it instead of text."""
    return [ref[len("column:"):] for rel, ref, _ in rows if rel == RELATION and ref.startswith("column:")]


def columns_from_lineage(lineage: Iterable[dict]) -> dict[str, Any]:
    """What a receipt's lineage rows say about columns, for a reader.

    ``level`` is ``"column"``, ``"table"`` or ``None`` — None for a receipt written before
    columns were traced, which is not the same as reading none."""
    out: dict[str, Any] = {"level": None, "note": None, "columns": [], "tables_only": []}
    for e in lineage or []:
        rel, ref = e.get("relation"), str(e.get("ref") or "")
        if rel == LEVEL_RELATION and ref.startswith("level:"):
            out["level"] = ref[len("level:"):]
            out["note"] = e.get("detail") or None
            continue
        if rel != RELATION:
            continue
        try:
            detail = json.loads(e.get("detail") or "{}")
        except (TypeError, ValueError):
            detail = {}
        if ref.startswith("column:"):
            table, _, column = ref[len("column:"):].rpartition(".")
            out["columns"].append({"table": table, "column": column, "roles": detail.get("roles") or [],
                                   "confidence": detail.get("confidence"), "as": detail.get("as") or []})
        elif ref.startswith("table:"):
            out["tables_only"].append({"table": ref[len("table:"):], "roles": detail.get("roles") or [],
                                       "as": detail.get("as") or [], "note": detail.get("note")})
    return out


def column_keys(lineage: Iterable[dict]) -> Optional[list[str]]:
    """``table.column`` (bare table, lower-cased) for a receipt whose columns were traced; None
    when they were not, so a caller falls back to the table scope rather than to nothing."""
    info = columns_from_lineage(lineage)
    if info["level"] != "column":
        return None
    return sorted({f"{c['table'].split('.')[-1].lower()}.{c['column'].lower()}" for c in info["columns"]})
