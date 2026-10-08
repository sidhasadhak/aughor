"""What a person turned off for analysis — the platform's seam (exploration principles §6, 2026-10-08).

A schema or table a person turned off is never read on the platform's own initiative or in an answer: the
connection layer refuses a statement that names one (`db.connection._security_pre`) and leaves it out of the
schema text every mode reads (`db.connection.open_connection`, `db.schema_render.render_raw_schema`). WHICH tables
are off is the people's declarations store (`ontology/visibility.py`), on the agent side of the boundary — so the
agent registers its reader here at bootstrap and the platform reads through the seam, never importing it.

With no reader registered (a bare platform, a harness outside the app) nothing is turned off. The labels a
person's OWN reads carry are the platform's to name: the SQL editor, the query builder and the Catalog browsing a
table pass, because off is the platform's restraint, not a lock on the person.
"""
from __future__ import annotations

from typing import Callable, Optional

#: The statement labels a PERSON's own reads carry: the SQL editor, the query builder, the Catalog's sample,
#: column, freshness and distinct-value reads.
PERSON_LABELS = frozenset({"query_workbench", "query_builder", "sample", "columns", "freshness",
                           "__catalog__", "__distinct__"})

# fn(connection_id, sql, dialect, default_schema) -> the refusal sentence, or "" when it names nothing turned off
Refusal = Callable[[str, str, Optional[str], Optional[str]], str]
# fn(connection_id, schema_text, default_schema) -> the schema text without the tables turned off
SchemaText = Callable[[str, str, Optional[str]], str]
# fn(connection_id, schema, table) -> whether the table (or its schema) is turned off
TableOff = Callable[[str, Optional[str], str], bool]

_refusal: Optional[Refusal] = None
_schema_text: Optional[SchemaText] = None
_table_off: Optional[TableOff] = None


def register_exclusions(*, refusal: Refusal, schema_text: SchemaText, table_off: TableOff) -> None:
    """Install (or replace) the reader. The agent registers the real one at bootstrap; tests may register fakes."""
    global _refusal, _schema_text, _table_off
    _refusal, _schema_text, _table_off = refusal, schema_text, table_off


def clear() -> None:
    """Drop the reader (test isolation)."""
    global _refusal, _schema_text, _table_off
    _refusal = _schema_text = _table_off = None


def _tolerated(exc: BaseException, what: str, conn_id: str) -> None:
    from aughor.kernel.errors import tolerate
    tolerate(exc, f"the exclusion reader failed ({what}); nothing is refused or hidden for it",
             counter=f"exclusions.{what}", conn_id=conn_id or None)


def refusal_for(connection_id: str, label: str, sql: str, dialect: Optional[str],
                default_schema: Optional[str] = None) -> str:
    """Why this statement is refused — it names a table or schema a person turned off — or ""."""
    if _refusal is None or not connection_id or label in PERSON_LABELS:
        return ""
    try:
        return _refusal(connection_id, sql, dialect, default_schema) or ""
    except Exception as exc:  # noqa: BLE001
        _tolerated(exc, "refusal", connection_id)
        return ""


def without_excluded(connection_id: str, schema_text: str, default_schema: Optional[str] = None) -> str:
    """The schema text with the tables a person turned off taken out; unchanged when none is or no reader is."""
    if _schema_text is None or not connection_id or not schema_text:
        return schema_text
    try:
        return _schema_text(connection_id, schema_text, default_schema)
    except Exception as exc:  # noqa: BLE001
        _tolerated(exc, "schema_text", connection_id)
        return schema_text


def is_table_off(connection_id: str, schema: Optional[str], table: str) -> bool:
    if _table_off is None or not connection_id:
        return False
    try:
        return bool(_table_off(connection_id, schema, table))
    except Exception as exc:  # noqa: BLE001
        _tolerated(exc, "table_off", connection_id)
        return False
