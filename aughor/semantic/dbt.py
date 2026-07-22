"""
dbt Integration — Milestone 1b.

Parses dbt's manifest.json (and optionally catalog.json) to extract
model/source descriptions and column annotations, returning them in the
same shape as data/glossary.yaml so they flow through apply_glossary()
transparently.

Configuration (optional — dbt layer is skipped if unset):
    AUGHOR_DBT_MANIFEST=/path/to/dbt/project/target/manifest.json
    AUGHOR_DBT_CATALOG=/path/to/dbt/project/target/catalog.json   # optional

Precedence (enforced in load_merged_glossary, not here):
    manual YAML  >  dbt manifest  >  auto-seed  >  raw DDL
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from aughor.tools.table_names import qualify


def _manifest_path() -> Path | None:
    v = os.getenv("AUGHOR_DBT_MANIFEST")
    if not v:
        return None
    p = Path(v)
    return p if p.exists() else None


def _catalog_path() -> Path | None:
    v = os.getenv("AUGHOR_DBT_CATALOG")
    if not v:
        return None
    p = Path(v)
    return p if p.exists() else None


def is_configured() -> bool:
    """Return True if a dbt manifest is configured and exists on disk."""
    return _manifest_path() is not None


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_columns(raw_cols: dict) -> dict[str, dict]:
    """Convert dbt column dict → glossary column dict (description only; skip empties)."""
    out: dict[str, dict] = {}
    for col_name, col_meta in (raw_cols or {}).items():
        desc = (col_meta.get("description") or "").strip()
        if desc:
            out[col_name.lower()] = {"description": desc}
    return out


def _table_key(node: dict) -> str:
    """The glossary key for a dbt node — schema-qualified whenever dbt declares a schema.

    Every manifest node carries the schema it materialises into, and the glossary is keyed
    by schema-qualified table name. Keying dbt entries bare meant a dbt annotation could
    never meet a qualified YAML entry for the same physical table: the merge unions on exact
    keys, so ``orders`` and ``analytics.orders`` were layered as two unrelated tables and
    the dbt description silently never applied.

    ``alias`` wins over ``name`` when set — that is the identifier the warehouse actually
    holds, and therefore the one the schema reader will present. Lowercased leaf, matching
    the column keys and the comparison convention in ``tools.table_names.bare``.
    """
    leaf = (node.get("alias") or node.get("name") or "").strip().lower()
    if not leaf:
        return ""
    return qualify(leaf, (node.get("schema") or "").strip().lower() or None)


def _parse_node(node: dict) -> dict[str, Any] | None:
    """
    Convert a dbt node (model or source) to a glossary table entry.
    Returns None if the node has no useful annotations.
    """
    desc = (node.get("description") or "").strip()
    cols = _parse_columns(node.get("columns") or {})

    if not desc and not cols:
        return None

    entry: dict[str, Any] = {"dbt_source": node.get("unique_id", "")}
    if desc:
        entry["description"] = desc
    if cols:
        entry["columns"] = cols
    return entry


def load_dbt_glossary() -> dict:
    """
    Parse the configured dbt manifest (and optional catalog) and return
    a glossary-shaped dict:

        {"tables": {"orders": {"description": "...", "columns": {...}}}}

    Returns {} if not configured or manifest cannot be parsed.
    """
    mp = _manifest_path()
    if not mp:
        return {}

    try:
        manifest = json.loads(mp.read_text())
    except Exception:
        return {}

    tables: dict[str, Any] = {}

    # ── Models ────────────────────────────────────────────────────────────────
    for uid, node in (manifest.get("nodes") or {}).items():
        if not uid.startswith("model."):
            continue
        if node.get("config", {}).get("materialized") == "ephemeral":
            continue
        table_name = _table_key(node)
        if not table_name:
            continue
        entry = _parse_node(node)
        if entry:
            tables[table_name] = entry

    # ── Sources ───────────────────────────────────────────────────────────────
    for uid, node in (manifest.get("sources") or {}).items():
        table_name = _table_key(node)
        if not table_name:
            continue
        entry = _parse_node(node)
        if entry:
            # Sources don't override models if both exist
            tables.setdefault(table_name, entry)

    if not tables:
        return {}

    # ── Catalog enrichment (optional) ─────────────────────────────────────────
    cp = _catalog_path()
    if cp:
        try:
            _enrich_from_catalog(tables, json.loads(cp.read_text()))
        except Exception:
            pass

    return {"tables": tables}


def _enrich_from_catalog(tables: dict, catalog: dict) -> None:
    """
    Pull additional column metadata from catalog.json.
    catalog provides physical column types and comments not always in manifest.
    """
    for uid, node in (catalog.get("nodes") or {}).items():
        # uid: "model.project.table_name" or "source.project.src.table"
        parts = uid.split(".")
        table_name = parts[-1].lower()
        if table_name not in tables:
            continue
        cat_cols = node.get("columns") or {}
        existing_cols = tables[table_name].setdefault("columns", {})
        for col_name, col_meta in cat_cols.items():
            comment = (col_meta.get("comment") or "").strip()
            col_lower = col_name.lower()
            if comment and col_lower not in existing_cols:
                existing_cols[col_lower] = {"description": comment}
