"""Arc NV-7 — the platform signs every statement it sends to a warehouse, so a warehouse's own history can tell it apart.

The warehouse's query history (`aughor.db.query_history`) is read for how OTHER people query it: the joins the map
lacks, the formulas analysts actually use. Measured on LuxExperience (2026-11-05) the history was almost entirely the
platform's own statements — metric runs, Briefing checks, probes — and the candidate door proposed the platform's own
approved metrics back to a person, sixteen times. Nothing on the statements said who had sent them.

Now every statement the platform hands to a driver carries :data:`SIGNATURE`, a leading comment the engines keep in
their history views (`pg_stat_statements.query`, BigQuery's `INFORMATION_SCHEMA.JOBS.query`, Snowflake's `QUERY_TEXT`,
ClickHouse's `system.query_log.query`), and the history reader leaves signed statements out, counting them. The
statement a result carries (`QueryResult.sql`, the receipts, the ledger) stays as written: the signature travels to the
engine alone, at the driver call, which is why it is applied there and nowhere earlier. A comment is the one marker
every engine accepts without a setting; an engine's own tag (a Snowflake query tag, a BigQuery label) would be a
second, engine-specific channel for the same fact and is deliberately not added.
"""
from __future__ import annotations

SIGNATURE = "/* aughor */"


def sign(sql: str) -> str:
    """``sql`` with the platform's signature in front, once."""
    text = sql if isinstance(sql, str) else str(sql or "")
    if is_signed(text):
        return text
    return f"{SIGNATURE} {text.lstrip()}" if text.strip() else text


def is_signed(sql: str) -> bool:
    """Whether a statement — as the platform sent it, or as a history view kept it — opens with the signature."""
    return (sql or "").lstrip().startswith(SIGNATURE)
