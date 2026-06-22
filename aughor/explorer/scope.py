"""Dataset-isolation scope guard — keep unrelated uploaded datasets from joining.

Extracted from the explorer/agent.py god-file (K4 code-health split). A single
connection can hold several UNRELATED uploaded datasets, each in its own schema
(a bakehouse CRM in ``bakehouse.*`` beside an ecommerce store in ``ecommerce.*``).
They share no real key, so any join across them is a hallucination — the
``bakehouse.sales_customers join ecommerce.orders`` garbage that produced a broken
finding. "Dataset" = the schema path; the schema is the reliable boundary (the
inferred join map had a false-positive cross-schema edge, so it can't be trusted
to separate them). Public so the explorer + investigations router share one guard.
"""
from __future__ import annotations


def dataset_of(tbl: str) -> str:
    """Schema path of a (possibly qualified) table name; '' when unqualified."""
    parts = str(tbl).split(".")
    return ".".join(parts[:-1]) if len(parts) > 1 else ""


def tables_in_sql(sql: str) -> set:
    """Real (non-CTE) qualified table names referenced by a SQL string. Best-effort.

    Delegates to the shared, CTE-safe extractor (aughor/sql/tables.py) so the
    explorer's dataset-isolation guard, the chat scope guard, and the read-only
    gate all share one tested table-extraction primitive (scope traversal +
    flat fallback) instead of three ad-hoc walks."""
    from aughor.sql.tables import extract_tables
    return {r.qualified() for r in extract_tables(sql)}


def crosses_datasets(sql: str) -> bool:
    """True when the SQL references real tables from ≥2 distinct schemas (datasets) — a
    join across unrelated uploaded datasets. Operates on the generated SQL's *qualified*
    table refs, so it works regardless of how the ontology stored source tables. Tables
    with no schema qualifier are ignored (they can't be cross-dataset)."""
    datasets = {dataset_of(t) for t in tables_in_sql(sql)}
    datasets.discard("")
    return len(datasets) > 1
