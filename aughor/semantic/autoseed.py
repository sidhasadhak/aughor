"""
Auto-Seed Glossary — Milestone 1a+.

When get_schema() encounters tables with no glossary entry, this module
calls the LLM once per missing table to infer business descriptions from
column names and sample values, then writes the results back to
data/glossary.yaml marked auto_generated: true.

User-provided entries always take precedence — autoseed never overwrites
an existing entry. The operation is idempotent: once a table is seeded
(even auto-generated), it is never re-seeded unless manually deleted.

Disable via env var: AUGHOR_AUTOSEED=false
"""
from __future__ import annotations

import os
import re
from typing import Optional

from pydantic import BaseModel, Field

from aughor.semantic.glossary import _DEFAULT_PATH, load_glossary, save_glossary

_ENABLED = os.getenv("AUGHOR_AUTOSEED", "true").lower() != "false"


# ── LLM output schema ─────────────────────────────────────────────────────────

class ColumnAnnotation(BaseModel):
    name: str = Field(description="Exact column name as it appears in the schema")
    description: str = Field(description="Plain-English business meaning of this column")
    values: Optional[str] = Field(
        default=None,
        description="Known distinct values or range (e.g. 'delivered, shipped, canceled'). Only for categoricals or enums."
    )
    caveats: Optional[str] = Field(
        default=None,
        description="Data quality issues, business rules, or gotchas analysts must know (e.g. 'NULLs represent legacy rows'). Null if none."
    )


class TableAnnotation(BaseModel):
    description: str = Field(
        description="One or two sentence plain-English description of what this table contains and its purpose"
    )
    grain: str = Field(
        description="What one row in this table represents (e.g. 'one row per order_id')"
    )
    columns: list[ColumnAnnotation] = Field(
        description="Annotations for each column. Include every column from the schema."
    )


_SEED_SYSTEM = """\
You are a senior data analyst annotating a database schema for a business intelligence tool.
Given a table schema (column names, types, and sample values), infer the business meaning of
the table and each column.

Rules:
- Be concise — one sentence per description
- grain must precisely describe what one row represents
- values: only populate for categorical/enum columns where you can see the distinct values
- caveats: only if there is a real gotcha (e.g. NULLs, type issues, known data quality problems)
- Infer from column names and sample values — do not hallucinate
"""


# ── Schema string parser ──────────────────────────────────────────────────────

def _parse_table_blocks(schema_str: str) -> dict[str, str]:
    """
    Extract per-table schema blocks from a raw schema string.
    Returns {table_name: schema_block_text}.
    """
    blocks: dict[str, str] = {}
    current_table: str | None = None
    current_lines: list[str] = []

    for line in schema_str.splitlines():
        m = re.match(r"^TABLE:\s+([\w.]+)", line)
        if m:
            if current_table and current_lines:
                blocks[current_table] = "\n".join(current_lines)
            current_table = m.group(1)
            current_lines = [line]
        elif current_table:
            # Stop accumulating at SQL HINTS block
            if line.startswith("SQL HINTS"):
                blocks[current_table] = "\n".join(current_lines)
                current_table = None
                current_lines = []
            elif line.strip() == "" and current_lines:
                blocks[current_table] = "\n".join(current_lines)
                current_table = None
                current_lines = []
            else:
                current_lines.append(line)

    if current_table and current_lines:
        blocks[current_table] = "\n".join(current_lines)

    return blocks


def _block_columns(block: str) -> set[str]:
    """Column names declared in a schema block — the `  <col>  <type>` detail lines
    (skip the TABLE: header, `--` comments, and hint lines)."""
    cols: set[str] = set()
    for line in block.splitlines():
        if line.startswith("TABLE:") or line.lstrip().startswith("--"):
            continue
        m = re.match(r"^  (\w+)\s+\S", line)
        if m:
            cols.add(m.group(1).lower())
    return cols


def _columns_drifted(stored: set[str], live: set[str]) -> bool:
    """True when an auto-generated glossary entry's columns no longer match the live
    table — the cross-warehouse contamination signature (a new connection's analytics.orders
    inheriting a DELETED warehouse's columns). Jaccard overlap < 0.6 ⇒ stale ⇒ re-seed."""
    if not stored or not live:
        return False
    overlap = len(stored & live) / len(stored | live)
    return overlap < 0.6


# ── Main entry point ──────────────────────────────────────────────────────────

def seed_missing_tables(raw_schema: str) -> bool:
    """
    Seed glossary entries for tables not yet in glossary.yaml.
    Called by get_schema() before apply_glossary().
    Returns True if any new entries were written.
    Never raises — failures are silent so schema load is never blocked.
    """
    if not _ENABLED:
        return False

    try:
        return _seed(raw_schema)
    except Exception:
        return False


def _seed(raw_schema: str) -> bool:
    from aughor.llm.provider import get_provider
    from aughor.semantic.glossary import load_merged_glossary
    from aughor.db.schema_cache import compute_fingerprint, is_complete, mark_complete

    # Check the fully merged glossary (manual + dbt) so we never re-seed
    # tables that dbt already covers.
    existing = set((load_merged_glossary().get("tables") or {}).keys())

    # But write new entries only to the YAML file (not dbt manifest)
    glossary = load_glossary()
    yaml_tables = glossary.get("tables") or {}
    table_blocks = _parse_table_blocks(raw_schema)
    missing = {t: b for t, b in table_blocks.items() if t not in existing}

    # Schema-drift invalidation (F6): glossary is keyed by bare schema.table, so a new
    # connection's `analytics.orders` used to inherit a DELETED warehouse's annotations
    # (phantom columns + hallucinated enum values). Re-seed any AUTO-generated entry whose
    # stored columns no longer match the live table. User-curated entries are never touched.
    for t, block in table_blocks.items():
        if t in missing:
            continue
        ent = yaml_tables.get(t)
        if not isinstance(ent, dict) or not ent.get("auto_generated"):
            continue
        if _columns_drifted(set((ent.get("columns") or {}).keys()), _block_columns(block)):
            logger.info("autoseed: re-seeding %r — stored glossary columns drifted from live schema", t)
            missing[t] = block

    # Fast-path: schema fingerprint matches a previously fully-seeded schema
    fp = compute_fingerprint(table_blocks)
    if not missing and is_complete(fp):
        return False  # identical schema, all tables already covered — skip LLM calls

    if not missing:
        mark_complete(fp)  # all tables covered by glossary — record and return
        return False

    provider = get_provider()
    tables_meta: dict = glossary.setdefault("tables", {})
    wrote_any = False

    for table_name, schema_block in missing.items():
        try:
            annotation: TableAnnotation = provider.complete(
                system=_SEED_SYSTEM,
                user=f"Annotate this table:\n\n{schema_block}",
                response_model=TableAnnotation,
                temperature=0.1,
            )

            col_dict: dict = {}
            for col in annotation.columns:
                entry: dict = {"description": col.description}
                if col.values:
                    entry["values"] = col.values
                if col.caveats:
                    entry["caveats"] = col.caveats
                col_dict[col.name] = entry

            tables_meta[table_name] = {
                "description": annotation.description,
                "grain": annotation.grain,
                "auto_generated": True,
                "columns": col_dict,
            }
            wrote_any = True

        except Exception as exc:
            # Best-effort — a failed seed for one table never blocks the rest
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a failed LLM seed for one table never blocks the rest", counter="autoseed.seed_table")
            continue

    if wrote_any:
        save_glossary(glossary)
        # If all tables are now covered, record the fingerprint so the next
        # call with the same schema skips LLM calls entirely.
        remaining = {
            t for t in table_blocks
            if t not in (load_merged_glossary().get("tables") or {})
        }
        if not remaining:
            mark_complete(fp)

    return wrote_any
