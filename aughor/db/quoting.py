"""Dialect-aware identifier quoting for hand-built SQL.

Routers that assemble SQL by hand (table sample, column probes, filter
pickers, freshness) historically double-quoted identifiers. BigQuery and
MySQL read a double-quoted name as a STRING LITERAL, so every such query
was a syntax error there — `SELECT * FROM "thelook"."orders"` — while the
same statement was fine on DuckDB/Postgres. Quote from the connector's
declared dialect instead.

LLM-written SQL does not come through here: it is transpiled/qualified via
sqlglot with the connector's dialect (see aughor.sql.identifiers).
"""

from __future__ import annotations

#: Engines whose identifier quote is the backtick. Everything else here takes
#: standard double quotes.
_BACKTICK_DIALECTS = {"bigquery", "mysql"}


def ident_quote(db) -> str:
    """The identifier quote character for an open connector."""
    return "`" if getattr(db, "dialect", "") in _BACKTICK_DIALECTS else '"'


def quote_ident(db, name: str) -> str:
    """Quote one identifier, each dotted segment separately — never the whole
    dotted string as one identifier (the beautycommerce bug)."""
    q = ident_quote(db)
    return ".".join(f"{q}{part}{q}" for part in name.split("."))


def qualified_table(db, table: str, schema: str | None = None) -> str:
    """`schema.table` (or bare `table`) quoted for the connector's dialect."""
    if schema:
        return f"{quote_ident(db, schema)}.{quote_ident(db, table)}"
    return quote_ident(db, table)
