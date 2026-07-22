"""
Business Glossary — Milestone 1a.

Loads data/glossary.yaml and enriches any raw schema string produced by
DuckDBConnection.get_schema() or PostgresConnection.get_schema() with:
  - Table descriptions and grain
  - Column business definitions, known values, and caveats
  - Known join hints between tables

The enrichment is pure string transformation — no dependency on the DB
connection type. Both schema paths call apply_glossary() at the end.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from aughor.tools.table_names import qualify, resolve_in, same_table

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "glossary.yaml"


def _default_path() -> Path:
    """The glossary file, honouring the ``AUGHOR_GLOSSARY_PATH`` override. The suite points it at a
    throwaway temp copy (conftest) so the autoseed / knowledge-sync WRITES can never mutate the live
    ``data/glossary.yaml`` — the non-hermeticity that leaked a glossary edit into two commits
    (task_213affac). Resolved per call so it always reflects the current env."""
    from aughor.db.sqlite_util import resolve_db_path
    return resolve_db_path("AUGHOR_GLOSSARY_PATH", _DEFAULT_PATH)


# ── Load / Save ───────────────────────────────────────────────────────────────

def _load_raw(path: Path | None = None) -> dict:
    p = Path(path) if path else _default_path()
    if not p.exists() or yaml is None:
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def load_glossary(path: Path | None = None) -> dict:
    """Return the manual YAML glossary dict (no dbt or auto-seed merging)."""
    return _load_raw(path)


def _deep_merge(base: dict, override: dict) -> dict:
    """
    Deep-merge override into base. override wins at every scalar field.
    For nested dicts (e.g. columns), merge recursively.
    Returns a new dict; neither input is mutated.
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _align_keys(dbt_tables: dict, yaml_keys: set[str]) -> dict:
    """Re-key dbt entries onto the YAML key space so the two layers can actually meet.

    The layering below unions on EXACT keys. dbt keys by what the manifest declares and the
    YAML by what the connector's ``TABLE:`` header carried, and those disagree on both
    qualification and case — so ``orders`` and ``analytics.orders`` were layered as two
    unrelated tables and a dbt description never reached the entry anyone reads.

    Aligns only when the match is UNAMBIGUOUS. With both ``beauty.orders`` and
    ``ecommerce.orders`` in the YAML, a bare dbt ``orders`` could belong to either; picking
    one would attach a description to the wrong table, which is the bug this is fixing. Such
    an entry keeps its own key — visible and separate rather than silently misfiled. A dbt
    node that declares its schema is already qualified and matches exactly, so the ambiguous
    case only arises for manifests that omit it.
    """
    aligned: dict = {}
    for key, entry in dbt_tables.items():
        if key not in yaml_keys:
            matches = [y for y in yaml_keys if same_table(y, key, schema_strict=True)]
            if len(matches) == 1:
                key = matches[0]
        aligned[key] = entry
    return aligned


def load_merged_glossary(path: Path | None = None) -> dict:
    """
    Return the fully merged glossary with three-layer precedence:

        manual YAML  >  dbt manifest  >  auto-seed (auto_generated: true in YAML)

    The dbt layer is skipped if AUGHOR_DBT_MANIFEST is not configured.
    Entries written by autoseed (auto_generated: true) are treated as the
    weakest layer — dbt and manual YAML both override them.
    """
    from aughor.semantic.dbt import load_dbt_glossary

    dbt = load_dbt_glossary()
    yaml_data = _load_raw(path)
    yaml_tables = yaml_data.get("tables", {})

    # Split YAML entries: auto-generated (weak) vs manually provided (strong)
    auto_tables:   dict = {t: e for t, e in yaml_tables.items() if e.get("auto_generated")}
    manual_tables: dict = {t: e for t, e in yaml_tables.items() if not e.get("auto_generated")}
    dbt_tables:    dict = _align_keys(dbt.get("tables", {}) if dbt else {},
                                      set(auto_tables) | set(manual_tables))

    all_names = set(auto_tables) | set(dbt_tables) | set(manual_tables)
    merged_tables: dict = {}

    for table in all_names:
        # Layer 1 (weakest): auto-seed
        entry: dict = dict(auto_tables.get(table, {}))
        # Layer 2: dbt overrides auto-seed
        if table in dbt_tables:
            entry = _deep_merge(entry, dbt_tables[table])
        # Layer 3 (strongest): manual YAML overrides everything
        if table in manual_tables:
            entry = _deep_merge(entry, manual_tables[table])
        merged_tables[table] = entry

    result = dict(yaml_data)
    result["tables"] = merged_tables
    return result


def lookup_table(tables_meta: dict, table: str, schema: str | None = None) -> dict:
    """The glossary entry for a table, tolerant of qualified-vs-bare keys. {} when absent.

    THE SCOPE SEAM. The store is keyed by whatever the ``TABLE:`` header carried when the
    entry was written, and the connectors disagree — DuckDB qualifies, Postgres/SQLite/
    Snowflake/MySQL/BigQuery don't. So the file holds BOTH forms (81 bare and 70 qualified
    keys, 61 colliding leaves: ``orders`` alone has five competing entries). An exact-string
    ``.get()`` therefore never found a qualified entry from a bare header, and vice versa —
    every schema's description silently overwrote the last one's.

    Resolution: qualify the lookup with the caller's schema, then match exact-first,
    schema-tolerant-second via the canonical ``resolve_in`` (``tools/table_names.py``, which
    exists precisely to stop this class of bug recurring). ``schema_strict=True`` means
    ``beauty.orders`` can never answer for ``ecommerce.orders`` — while a BARE key still
    matches any schema, so the pre-existing unqualified entries keep working as fallbacks
    until a scoped write supersedes them."""
    if not tables_meta:
        return {}
    return resolve_in(tables_meta, qualify(table, schema), schema_strict=True) or {}


def canonical_key(table: str, schema: str | None = None) -> str:
    """The key a glossary WRITE should use: schema-qualified whenever the schema is known.

    Canonical on write, tolerant on read. New entries stop colliding across schemas; old
    bare entries are left alone rather than migrated, because there is no way to know which
    schema an unqualified entry was written for — guessing would move one schema's
    description under another's name, which is the bug, not the fix."""
    return qualify(table, schema)


def save_glossary(data: dict, path: Path | None = None) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required: uv add pyyaml")
    p = Path(path) if path else _default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def update_table(table: str, description: str | None = None, grain: str | None = None,
                 joins: list[str] | None = None, path: Path | None = None,
                 schema: str | None = None) -> None:
    """Upsert table-level glossary entry, keyed per schema when one is known."""
    data = _load_raw(path)
    tables = data.setdefault("tables", {})
    entry = tables.setdefault(canonical_key(table, schema), {})
    if description is not None:
        entry["description"] = description
    if grain is not None:
        entry["grain"] = grain
    if joins is not None:
        entry["joins"] = joins
    save_glossary(data, path)


def update_column(table: str, column: str, description: str | None = None,
                  values: str | None = None, caveats: str | None = None,
                  path: Path | None = None, schema: str | None = None) -> None:
    """Upsert column-level glossary entry, keyed per schema when one is known."""
    data = _load_raw(path)
    col_entry = (
        data.setdefault("tables", {})
            .setdefault(canonical_key(table, schema), {})
            .setdefault("columns", {})
            .setdefault(column, {})
    )
    if description is not None:
        col_entry["description"] = description
    if values is not None:
        col_entry["values"] = values
    if caveats is not None:
        col_entry["caveats"] = caveats
    save_glossary(data, path)


# ── Enrichment ────────────────────────────────────────────────────────────────

def apply_glossary(schema_str: str, path: Path | None = None, schema: str | None = None) -> str:
    """
    Enrich a raw schema string with business glossary annotations.

    Operates line-by-line:
    - TABLE: lines get description, grain, and join hints appended
    - Column lines get description, known values, and caveats appended

    Falls back to the unmodified schema_str if the glossary is empty or
    the YAML library is not installed.
    """
    glossary = load_merged_glossary(path)
    tables_meta: dict[str, Any] = glossary.get("tables", {})
    if not tables_meta:
        return schema_str

    lines = schema_str.splitlines()
    out: list[str] = []
    current_table: str | None = None

    for line in lines:
        # Detect TABLE: header
        table_match = re.match(r"^TABLE:\s+([\w.]+)", line)
        if table_match:
            current_table = table_match.group(1)
            out.append(line)
            meta = lookup_table(tables_meta, current_table, schema)
            if meta.get("description"):
                out.append(f"  -- {meta['description']}")
            if meta.get("grain"):
                out.append(f"  -- Grain: {meta['grain']}")
            continue

        # Detect column lines (two leading spaces, then identifier + type)
        col_match = re.match(r"^  (\w+)\s+(\S+)(.*)", line)
        if col_match and current_table:
            col_name = col_match.group(1)
            col_match.group(3)
            meta = lookup_table(tables_meta, current_table, schema)
            col_meta = (meta.get("columns") or {}).get(col_name, {})

            annotation_parts: list[str] = []
            if col_meta.get("description"):
                annotation_parts.append(col_meta["description"])
            if col_meta.get("values"):
                annotation_parts.append(f"Values: {col_meta['values']}")
            if col_meta.get("caveats"):
                annotation_parts.append(f"⚠ {col_meta['caveats']}")

            if annotation_parts:
                # Append annotation inline, preserving existing hints
                annotation = " | ".join(annotation_parts)
                # Strip any existing inline hint so we don't double-up
                base_line = re.sub(r"\s+\[.*\]$", "", line)
                out.append(f"{base_line}  [{annotation}]")
            else:
                out.append(line)
            continue

        # Detect blank line after a table block — emit join hints before it
        if line == "" and current_table:
            meta = lookup_table(tables_meta, current_table, schema)
            joins = meta.get("joins") or []
            if joins:
                out.append(f"  -- Joins: {'; '.join(joins)}")
            current_table = None  # reset after blank line
            out.append(line)
            continue

        out.append(line)

    # Flush join hints if schema ended without a trailing blank line
    if current_table:
        meta = lookup_table(tables_meta, current_table, schema)
        joins = meta.get("joins") or []
        if joins:
            out.append(f"  -- Joins: {'; '.join(joins)}")

    return "\n".join(out)
