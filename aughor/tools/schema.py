"""Schema introspection — builds the context string fed to the LLM."""
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:  # forward ref only — avoids importing the canvas layer at runtime
    from aughor.canvas.models import Canvas

from aughor.semantic.glossary import apply_glossary
from aughor.tools.table_names import bare

# Raw schema rendering + the pure parsing / FK-root helpers now live on the PLATFORM
# side (aughor.db.schema_render) so the platform can render/parse schemas without
# importing the agent. Re-exported here so the agent's many `tools.schema` imports
# stay stable, and so the helpers below (compute_join_map, infer_joins, _col_root, …)
# keep resolving them.
from aughor.db.schema_render import (  # noqa: F401
    ROOT_SUFFIXES,
    SECTION_STOP,
    fk_root,
    parse_schema_tables,
    render_raw_schema,
)

# Normalise verbose type names (PostgreSQL information_schema, DuckDB DESCRIBE).
_TYPE_MAP: dict[str, str] = {
    "character varying": "VARCHAR",
    "character":         "CHAR",
    "double precision":  "DOUBLE",
    "numeric":           "NUMERIC",
    "integer":           "INTEGER",
    "bigint":            "BIGINT",
    "smallint":          "SMALLINT",
    "real":              "FLOAT",
    "boolean":           "BOOLEAN",
    "timestamp without time zone": "TIMESTAMP",
    "timestamp with time zone":    "TIMESTAMPTZ",
}


def _norm_type(t: str) -> str:
    t_clean = t.strip().lower()
    return _TYPE_MAP.get(t_clean, t.strip())

# ── Fuzzy join inference ──────────────────────────────────────────────────────
# (_KEY_COL and ROOT_SUFFIXES are imported from aughor.db.schema_render above.)

# Roots that are generic attribute names, NOT foreign-key roots.
# Columns whose root matches one of these will be skipped during join inference
# to avoid false positives like currency↔currency or status↔status across tables.
_NON_KEY_ROOTS = frozenset({
    "currency", "status", "type", "name", "date", "year", "month", "day",
    "time", "timestamp", "created", "updated", "deleted", "modified",
    "code", "description", "category", "country", "region", "city", "state",
    "amount", "price", "cost", "total", "count", "rate", "ratio", "percent",
    "flag", "label", "title", "note", "comment", "address", "phone",
    "email", "url", "path", "size", "weight", "color", "colour",
    "gender", "age", "score", "rank", "level", "priority", "sequence",
    "value", "text", "number", "active", "enabled", "visible", "public",
    "source", "target", "action", "event", "message", "error", "result",
})


def _col_root(col: str) -> str:
    col = col.lower()
    for suffix in ROOT_SUFFIXES:
        if col.endswith(suffix):
            return col[: -len(suffix)]
    return col


def compute_join_map(table_cols: dict[str, list[str]]) -> dict:
    """Public alias for the join-map inferrer (companion to parse_schema_tables);
    lets out-of-module callers build a join map without importing internals."""
    return _compute_join_map(table_cols)


def norm_type(t: str) -> str:
    """Public alias for the column-type normaliser (stable cross-module interface)."""
    return _norm_type(t)


def _table_base(t: str) -> str:
    """Bare table name for owner matching: last path segment, lowercased, with
    dim_/fact_/_dim wrappers and a trailing plural 's' removed."""
    base = bare(t)
    base = re.sub(r"^(dim|fact|tbl|stg)_", "", base)
    base = re.sub(r"_(dim|fact|tbl)$", "", base)
    return base.rstrip("s")


def _find_dim_owner(root: str, entries: list[tuple[str, str]]) -> int | None:
    """Index of the table that OWNS this key (the dimension), or None. The owner
    is the table whose bare name matches the key root (item→item, customer→
    customers, date→date_dim, cust→customer)."""
    rk = root.rstrip("s")
    for idx, (t, _c) in enumerate(entries):
        tb = _table_base(t)
        if tb == rk or (len(rk) >= 4 and (tb.startswith(rk) or rk.startswith(tb))):
            return idx
    return None


def _entity_roots(table_cols: dict[str, list[str]]) -> set[str]:
    """Root tokens that NAME an entity (a table in the schema) — its head noun and the
    full base, in singular and plural.

    A non-suffixed join key references an entity: a bare ``customer`` column means "the
    customer this row belongs to" → the customers table. A shared *dimension* attribute
    (``continent``, ``quantity``, ``district``) names no table — two tables having a
    ``continent`` column is a coincidence, not a foreign key. Requiring a non-key join
    root to name an entity is the data-free signal that separates the two, so the verifier
    never wastes an orphan-check (or pollutes neighbour-grounding) on ``quantity↔quantity``."""
    roots: set[str] = set()
    for t in table_cols:
        base = _table_base(t)                       # sales_customers → sales_customer
        head = base.split("_")[-1]                  # head noun → customer
        for r in (base, head):
            if len(r) >= 3:
                roots.add(r)
                roots.add(r + "s")                  # plural, so a bare `customer` col matches `customers`
    return roots


def _compute_join_map(table_cols: dict[str, list[str]]) -> dict:
    """
    Compute join candidates across tables using root-normalised column names.
    Returns {"joins": [...], "no_join": [...]} — same shape as talonsight's get_join_map.
    """
    entity_roots = _entity_roots(table_cols)
    # Two rooting passes, merged. A column is treated as a join key if EITHER:
    #   • key-aware: it ends in a key/id suffix (incl. fused/prefixed forms like
    #     c_custkey) → high-confidence FK, never blocklisted; or
    #   • legacy: its plain root (suffix-stripped, no prefix strip) is shared and
    #     not a generic attribute (preserves prior behaviour for non-key columns).
    root_map: dict[str, list[tuple[str, str]]] = {}
    key_roots: set[str] = set()
    for table, cols in table_cols.items():
        for col in cols:
            kroot = fk_root(col)
            if kroot and len(kroot) >= 3:
                root_map.setdefault(kroot, []).append((table, col))
                key_roots.add(kroot)
                continue
            oroot = _col_root(col)
            # Legacy non-key path: a shared root joins only when it NAMES AN ENTITY (a
            # table). This is what stops a coincidental dimension/measure match — two tables
            # both having `continent` or `quantity` — from being proposed as a foreign key.
            if len(oroot) >= 3 and oroot not in _NON_KEY_ROOTS and oroot in entity_roots:
                root_map.setdefault(oroot, []).append((table, col))

    joined_pairs: set[frozenset[str]] = set()
    joins: list[dict] = []

    for root, entries in root_map.items():
        if len(entries) < 2:
            continue
        is_key = root in key_roots
        # Star-schema routing: when ≥3 tables share a key, they are facts pointing
        # at a DIMENSION (the eponymous table, e.g. root 'item' → table `item`).
        # Join each fact to the dimension (FK→PK), NOT fact-to-fact — otherwise
        # store_sales and catalog_sales get falsely joined just for both having
        # an item key. With no eponymous owner, fall back to all-pairs.
        owner = _find_dim_owner(root, entries) if len(entries) >= 3 else None
        if owner is not None:
            pairs = [(owner, j) for j in range(len(entries)) if j != owner]
        else:
            pairs = [(i, j) for i in range(len(entries)) for j in range(i + 1, len(entries))]
        for a, b in pairs:
            t1, c1 = entries[a]
            t2, c2 = entries[b]
            if t1 == t2:
                continue
            pair = frozenset([t1, t2])
            if pair in joined_pairs:
                continue
            match = "exact" if (is_key or c1 == c2 or c1.endswith("_id") or c2.endswith("_id")) else "inferred"
            joins.append({"t1": t1, "c1": c1, "t2": t2, "c2": c2, "match": match})
            joined_pairs.add(pair)

    all_tables = list(table_cols.keys())
    no_join = [
        (all_tables[i], all_tables[j])
        for i in range(len(all_tables))
        for j in range(i + 1, len(all_tables))
        if frozenset([all_tables[i], all_tables[j]]) not in joined_pairs
    ]
    return {"joins": joins, "no_join": no_join}


def fk_neighbor_expand(full_schema: str, tables: list[str], cap: int = 10) -> list[str]:
    """Expand a set of schema-linked tables with their direct FK neighbours.

    The schema-linker picks tables by keyword relevance, so it misses BRIDGE and
    OUTPUT tables that a multi-table question needs only via a join (e.g. TPC-H Q5
    needs `lineitem` for revenue, Q10 needs `nation` for the nation name — neither
    is named in the question). Adding 1-hop FK neighbours (bounded by ``cap``)
    completes the join paths without dumping the whole schema. Order-preserving:
    the originally linked tables stay first."""
    try:
        jmap = _compute_join_map(parse_schema_tables(full_schema))
    except Exception:
        return tables
    adj: dict[str, set[str]] = {}
    for j in jmap.get("joins", []):
        adj.setdefault(j["t1"], set()).add(j["t2"])
        adj.setdefault(j["t2"], set()).add(j["t1"])
    out = list(tables)
    seen = set(tables)
    for t in tables:
        for nb in sorted(adj.get(t, ())):
            if len(out) >= cap:
                break
            if nb not in seen:
                out.append(nb)
                seen.add(nb)
    return out


_TEMPORAL_HINT = re.compile(
    r"\b(year|month|quarter|week|day|daily|monthly|quarterly|weekly|annual|annually|"
    r"ytd|mtd|qtd|hour|minute|date|jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|"
    r"jul(y)?|aug(ust)?|sep(tember)?|oct(ober)?|nov(ember)?|dec(ember)?|\b\d{4}\b)\b",
    re.IGNORECASE,
)
_DT_SURROGATE = re.compile(r"_(date|time)_(sk|key|id)$", re.IGNORECASE)
_DT_DIM_NAME = re.compile(r"(date|time|calendar|day)", re.IGNORECASE)


def temporal_dimension_tables(full_schema: str, linked_tables: list[str], question: str) -> list[str]:
    """Date/time DIMENSION tables to add to context for a temporal question.

    A star schema filters time through a date_dim/time_dim joined on a surrogate
    key (fact._date_sk = date_dim.d_date_sk); the schema-linker misses it because
    "November 2000" names no table. Returns the dimension table(s) when the
    question is temporal AND a linked fact carries a *_date_sk / *_time_sk key.
    Empty otherwise (e.g. schemas with plain DATE columns need nothing)."""
    if not question or not _TEMPORAL_HINT.search(question):
        return []
    try:
        tcols = parse_schema_tables(full_schema)
    except Exception:
        return []
    linked = set(linked_tables)
    if not any(any(_DT_SURROGATE.search(c) for c in tcols.get(t, [])) for t in linked):
        return []
    dims: list[str] = []
    for t, cols in tcols.items():
        if t in linked:
            continue
        base = bare(t)
        if _DT_DIM_NAME.search(base) and any(_DT_SURROGATE.search(c) for c in cols):
            dims.append(t)
    return dims


def infer_joins(schema_str: str) -> str:
    """
    Return a JOIN HINTS text block to append to the schema context, or "".

    Two-phase approach:
      Phase 1 (exact): same normalised root + both share an _id suffix → high confidence
      Phase 2 (fuzzy): same root, one side lacks _id → marked [inferred — verify]
    """
    table_cols = parse_schema_tables(schema_str)
    if len(table_cols) < 2:
        return ""

    jmap = _compute_join_map(table_cols)

    join_lines = [
        f"  {j['t1']}.{j['c1']} → {j['t2']}.{j['c2']}  [{j['match']}]"
        for j in jmap["joins"]
    ]
    no_join_lines = [
        f"  {t1} ↔ {t2}: no shared key detected"
        for t1, t2 in jmap["no_join"]
    ][:5]

    if not join_lines and not no_join_lines:
        return ""

    parts: list[str] = []
    if join_lines:
        parts.append("DETECTED JOIN PATHS (use these to write correct JOINs):")
        parts.extend(join_lines)
    if no_join_lines:
        parts.append(
            "NO DIRECT FOREIGN KEY between these table pairs — join them through an "
            "intermediate table if the question needs both; do not invent a shared key:"
        )
        parts.extend(no_join_lines)
    return "\n".join(parts)


def build_mermaid_er(schema_str: str) -> str:
    """
    Generate a Mermaid erDiagram source from a schema context string.

    Solid lines (||--|{) = exact column-name match or shared _id suffix.
    Dashed lines (||..|{) = similar name (fuzzy root match).
    Tables with no detected join remain as isolated entities.
    """
    table_cols = parse_schema_tables(schema_str)
    if not table_cols:
        return ""

    # Also capture column types from the raw schema for richer diagram
    table_col_types: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for line in schema_str.splitlines():
        if SECTION_STOP.match(line):
            current = None
            continue
        m = re.match(r"^TABLE:\s+([\w.]+)", line)
        if m:
            current = m.group(1)
            table_col_types[current] = []
        elif current:
            col_m = re.match(r"^\s{2}(.+?)\s{2,}(\S+)", line)
            if col_m and not line.strip().startswith("--"):
                table_col_types[current].append((col_m.group(1), col_m.group(2)))

    def _safe(s: str) -> str:
        """Mermaid-safe identifier — must start with a letter."""
        name = re.sub(r"[^a-zA-Z0-9_]", "_", s).strip("_") or "col"
        return ("n" + name) if name[0].isdigit() else name

    def _base_type(t: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_]", "", re.split(r"[\s(]", t.strip())[0]) or "VARCHAR"

    jmap = _compute_join_map(table_cols)

    # Track which columns are FKs (appear as join keys on one side)
    fk_hints: dict[str, set[str]] = {t: set() for t in table_cols}
    for j in jmap["joins"]:
        fk_hints[j["t1"]].add(j["c1"])
        fk_hints[j["t2"]].add(j["c2"])

    lines = ["erDiagram"]

    for table, col_type_pairs in table_col_types.items():
        ename = _safe(table)
        lines.append(f"    {ename} {{")
        for col, col_type in col_type_pairs[:30]:
            atype = _base_type(col_type)
            aname = _safe(col)
            marker = " FK" if col in fk_hints.get(table, set()) else ""
            lines.append(f"        {aname} {atype}{marker}")
        if len(col_type_pairs) > 30:
            lines.append(f"        varchar more{len(col_type_pairs) - 30}cols")
        lines.append("    }")

    for j in jmap["joins"]:
        t1 = _safe(j["t1"])
        t2 = _safe(j["t2"])
        c1s = _safe(j["c1"])
        c2s = _safe(j["c2"])
        lbl = c1s if c1s == c2s else f"{c1s}_{c2s}"
        rel = "||--|{" if j["match"] == "exact" else "||..|{"
        lines.append(f'    {t1} {rel} {t2} : "{lbl}"')

    return "\n".join(lines)


def build_rich_schema(schema_str: str) -> dict:
    """Return structured schema data for the rich UI card view."""
    table_col_types: dict[str, list[tuple[str, str, str]]] = {}
    table_row_counts: dict[str, str] = {}
    current: str | None = None

    for line in schema_str.splitlines():
        if SECTION_STOP.match(line):
            current = None
            continue
        m = re.match(r"^TABLE:\s+([\w.]+)\s*\(([\d,?]+|\?)?\s*rows?\)?", line)
        if m:
            current = m.group(1)
            if current not in table_col_types:
                table_col_types[current] = []
                if m.group(2):
                    table_row_counts[current] = m.group(2).replace(",", "")
        elif current:
            col_m = re.match(r"^\s{2}(.+?)\s{2,}(\S+)", line)
            if col_m and not line.strip().startswith("--"):
                desc = ""
                desc_m = re.search(r"\[(.+?)\]", line)
                if desc_m:
                    desc = desc_m.group(1)
                table_col_types[current].append((col_m.group(1), col_m.group(2), desc))

    table_cols = {t: [c for c, _, _ in cols] for t, cols in table_col_types.items()}
    jmap = _compute_join_map(table_cols)

    # Only the FK side (t1.c1) gets is_fk=True.
    # The PK target side (t2.c2) is a primary/unique key — marking it as FK would be wrong.
    fk_hints: dict[str, set[str]] = {t: set() for t in table_cols}
    for j in jmap["joins"]:
        fk_hints[j["t1"]].add(j["c1"])

    tables = []
    for table, col_type_pairs in table_col_types.items():
        tables.append({
            "name": table,
            "row_count": table_row_counts.get(table),
            "columns": [
                {"name": col, "type": typ, "is_fk": col in fk_hints.get(table, set()),
                 **({"description": desc} if desc else {})}
                for col, typ, desc in col_type_pairs
            ],
        })

    warnings = []

    # Type mismatch on join columns
    type_index: dict[str, dict[str, str]] = {
        t: {col: typ for col, typ, _ in pairs} for t, pairs in table_col_types.items()
    }
    for j in jmap["joins"]:
        t1_type = type_index.get(j["t1"], {}).get(j["c1"], "")
        t2_type = type_index.get(j["t2"], {}).get(j["c2"], "")
        if t1_type and t2_type:
            base1 = re.split(r"[\s(]", t1_type.upper())[0]
            base2 = re.split(r"[\s(]", t2_type.upper())[0]
            if base1 != base2:
                warnings.append({
                    "level": "warn",
                    "message": (
                        f"Type mismatch on join: {j['t1']}.{j['c1']} ({t1_type}) ↔ "
                        f"{j['t2']}.{j['c2']} ({t2_type}) — may cause implicit cast"
                    ),
                })

    # Isolated tables (no detected joins)
    joined_tables: set[str] = set()
    for j in jmap["joins"]:
        joined_tables.add(j["t1"])
        joined_tables.add(j["t2"])
    isolated = [t for t in table_cols if t not in joined_tables]
    if len(table_cols) > 1:
        for t in isolated:
            warnings.append({
                "level": "info",
                "message": f"{t} has no detected join path to other tables",
            })

    # Wide tables
    for table, col_type_pairs in table_col_types.items():
        if len(col_type_pairs) > 25:
            warnings.append({
                "level": "info",
                "message": f"{table} is wide ({len(col_type_pairs)} columns) — select only needed columns",
            })

    return {
        "tables": tables,
        "joins": jmap["joins"],
        "isolated": isolated,
        "warnings": warnings,
    }


def col_types_from_schema(schema_str: str) -> dict[str, str]:
    """Map bare + qualified column name → declared dtype, parsed from a rich-schema string.

    The single source of truth for the aggregate↔type guard (``knowledge.triage``: a SUM/AVG
    over a VARCHAR column is a coercion artifact, not a measure). Used at BOTH the insight
    cards / brief (``routers.exploration._connection_col_types``) and the explorer's
    pre-emission gate (``explorer.verify``) so every consumer stamps by the same authority.
    Bare name maps to the first real type seen; the qualified ``table.col`` key disambiguates
    a name that appears on multiple tables. Fail-open ({}) — a schema hiccup must never blank
    the guard (which would silently re-admit the coercion artifacts it exists to catch)."""
    out: dict[str, str] = {}
    try:
        for t in build_rich_schema(schema_str).get("tables", []):
            tname = (t.get("name") or "").split(".")[-1].lower()   # bare table
            for c in t.get("columns", []):
                cname = (c.get("name") or "").lower()
                ctype = (c.get("type") or "").strip()
                if not cname or not ctype:
                    continue
                out.setdefault(cname, ctype)          # bare col (first real type wins)
                if tname:
                    out[f"{tname}.{cname}"] = ctype    # qualified — cross-table disambiguation
    except Exception:
        return out
    return out


def validate_join_path(from_table: str, to_table: str, schema_str: str) -> tuple[bool, str]:
    """
    Check whether two tables have a detectable join path in the schema.

    Returns (True, "") when a shared key column was found (exact or fuzzy root match).
    Returns (False, reason) when both tables exist but share no detected key.
    Returns (False, reason) when either table is not in the schema at all.
    """
    table_cols = parse_schema_tables(schema_str)
    known = {t.lower(): t for t in table_cols}

    ft, tt = from_table.lower(), to_table.lower()

    if ft not in known:
        return False, f"Table '{from_table}' is not in the schema"
    if tt not in known:
        return False, f"Table '{to_table}' is not in the schema"

    jmap = _compute_join_map(table_cols)
    for j in jmap["joins"]:
        if {j["t1"].lower(), j["t2"].lower()} == {ft, tt}:
            confidence = "verified" if j["match"] == "exact" else "inferred"
            return True, confidence

    return (
        False,
        f"No shared key detected between '{known[ft]}' and '{known[tt]}' — "
        "they may not be directly joinable. Use only join paths listed in the schema.",
    )


def inject_value_annotations(
    schema_str: str, column_profiles: dict, sample_disabled: set[str] | None = None
) -> str:
    """
    Enrich TABLE: column lines with actual enumerated values from profiler cache.

    For every column that has low-cardinality top_values in its ColumnProfile,
    appends the values inline:
      `  status  VARCHAR` → `  status  VARCHAR  -- [Shipped, Pending, Canceled, Returned]`

    Skips lines that already carry a `-- [` annotation (from build_schema_context's
    first-run sampling) to avoid duplication.  Profile-backed values are richer
    (frequency-ordered, complete) so they overwrite the first-run annotation when present.

    ``sample_disabled`` (R11 per-column config): "table.column" keys (bare table
    name) whose values must NOT be enumerated — those lines pass through untouched.
    """
    if not column_profiles:
        return schema_str

    lines = schema_str.splitlines()
    result: list[str] = []
    current_table: str | None = None

    for line in lines:
        tm = re.match(r'^TABLE:\s+([\w.]+)', line)
        if tm:
            current_table = tm.group(1)
            result.append(line)
            continue

        if SECTION_STOP.match(line):
            current_table = None
            result.append(line)
            continue

        if (
            current_table
            and re.match(r'^\s{2}\S', line)
            and not line.strip().startswith('--')
            and 'Values:' not in line   # glossary already annotated this column
        ):
            col_m = re.match(r'^\s{2}(\w+)\s+', line)
            if col_m:
                col_name = col_m.group(1)
                if sample_disabled and f"{current_table.split('.')[-1]}.{col_name}" in sample_disabled:
                    result.append(line)
                    continue
                cp = column_profiles.get(f"{current_table}.{col_name}")
                if cp is not None:
                    top_values = getattr(cp, 'top_values', None)
                    is_low_card = getattr(cp, 'is_low_cardinality', False)
                    is_fk = getattr(cp, 'is_fk', False)
                    sem_type = getattr(cp, 'semantic_type', '')
                    # Only annotate true categorical dimensions; skip free-text and keys.
                    # Also skip if any value is long (> 60 chars) — these are description fields.
                    if (
                        top_values and is_low_card and not is_fk
                        and sem_type in ('dimension', 'flag', 'ordinal')
                        and all(len(str(v)) <= 60 for v in top_values)
                    ):
                        vals = ", ".join(str(v) for v in top_values[:15])
                        # Replace any first-run sampling annotation with richer profile data
                        base_line = re.sub(r'\s+--\s+\[.*\]$', '', line)
                        line = f"{base_line}  -- [{vals}]"

        result.append(line)

    return "\n".join(result)


def apply_schema_enrichment(
    raw: str,
    *,
    connection_id: str | None = None,
    profile_annotation: str = "",
    query_log_annotation: str = "",
    schema_name: str | None = None,
) -> str:
    """The AGENT enrichment tail of :func:`build_schema_context`, applied on top of a
    raw schema (``aughor.db.schema_render.render_raw_schema``): seed missing tables,
    apply the glossary, refresh the vector index, append inferred join hints + the
    schema-scoped metrics catalog (+ an optional pre-rendered profile block).

    Extracted so the platform's ``get_schema`` can reproduce build_schema_context's
    output **byte-for-byte** via the schema-annotator registry, without the platform
    importing the agent. ``query_log_annotation`` (facts mined from real query history —
    learned joins / value domains / formulas) is appended last; when empty it is
    auto-collected iff AUGHOR_QUERY_LOG_MINING=1 (opt-in, best-effort)."""
    from aughor.semantic.autoseed import seed_missing_tables
    from aughor.semantic.metrics import build_metrics_block
    from aughor.semantic.retriever import build_schema_index
    # R11 — prune per-column-config-hidden columns (and sample-disabled value
    # enumerations) from the schema text FIRST, so every downstream reader — join
    # hints, metrics filtering, schema linking, the coder prompt — sees the pruned
    # schema. Flag-gated; the store is empty until the intelligence phase persists
    # defaults, and an empty config is a byte-identical no-op.
    from aughor.kernel.flags import flag_enabled
    if connection_id and flag_enabled("ontology.column_config"):
        try:
            from aughor.ontology.column_config import (
                apply_column_config_to_schema,
                load_column_configs,
            )
            _col_cfg = load_column_configs(connection_id, schema_name or "default")
            if _col_cfg:
                raw = apply_column_config_to_schema(raw, _col_cfg)
        except Exception as _cc_exc:
            from aughor.kernel.errors import tolerate
            tolerate(_cc_exc, "column-config schema pruning is best-effort",
                     counter="ontology.column_config", conn_id=connection_id)
    # Both are schema-scoped now: the glossary is keyed per schema when one is known, so a
    # write from THIS schema can no longer overwrite a same-named table in another (the
    # `orders` collision — five competing entries in one store). `schema_name` was already
    # in scope here and simply wasn't passed.
    seed_missing_tables(raw, schema=schema_name, connection_id=connection_id)
    enriched = apply_glossary(raw, schema=schema_name)
    # best-effort; keeps vector index fresh after glossary changes. Scoped, so this
    # connection's points can neither overwrite nor answer for another's.
    build_schema_index(connection_id=connection_id or "", schema_name=schema_name or "")
    join_hints = infer_joins(enriched)
    if join_hints:
        enriched += "\n\n" + join_hints
    # Filter metrics against THIS schema so a globally-stored metric that
    # references columns absent here (another connection's metric) doesn't leak
    # a wrong formula into the prompt.
    metrics_block = build_metrics_block(schema_text=enriched, connection_id=connection_id or "")
    if metrics_block:
        enriched += "\n\n" + metrics_block
    if profile_annotation:
        enriched += "\n\n" + profile_annotation
    # Query-log facts: learned join paths / value domains / formulas from real query history.
    # Injected pre-rendered (decoupled, like profile_annotation); opt-in auto-collect when enabled
    # so the schema hot-path never depends on the vector store unless explicitly turned on.
    if not query_log_annotation and connection_id and os.environ.get("AUGHOR_QUERY_LOG_MINING") == "1":
        try:
            from aughor.sql.query_log_miner import build_query_log_annotation
            query_log_annotation = build_query_log_annotation(connection_id)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "query-log mining is best-effort schema enrichment",
                     counter="query_log.annotate", conn_id=connection_id)
    if query_log_annotation:
        enriched += "\n\n" + query_log_annotation
    return enriched


def build_schema_context(
    conn: duckdb.DuckDBPyConnection,
    profile_annotation: str = "",
    schema_name: str | None = None,
    connection_id: str | None = None,
    query_log_annotation: str = "",
) -> str:
    """Return a rich schema description for the LLM, including row counts and glossary annotations.

    profile_annotation: pre-rendered DATA PROFILES block from the profiler.
    When supplied (non-empty), it is appended after join hints so every prompt
    receives grain, null-rate, and value-interpretation information.

    schema_name: when set, filters to only tables in that DuckDB schema so that
    multi-schema files don't bleed tables from other schemas into this context.

    The raw rendering is the platform's ``render_raw_schema``; the glossary / join /
    metrics enrichment is :func:`apply_schema_enrichment`.
    """
    raw = render_raw_schema(conn, schema_name, connection_id)
    return apply_schema_enrichment(
        raw, connection_id=connection_id, profile_annotation=profile_annotation,
        query_log_annotation=query_log_annotation, schema_name=schema_name)


# ── Canvas-scoped schema helpers ──────────────────────────────────────────────

def get_schema_for_tables(full_schema: str, tables: list[str]) -> str:
    """Filter a full schema context string down to only the requested tables.

    Parses TABLE: blocks from the schema string and returns only those whose
    table name (case-insensitive) appears in `tables`. Preserves the join-hints
    and metrics blocks that follow the TABLE: sections (everything after the
    last table block is kept verbatim).

    Matches both bare table names ("orders") and qualified names ("ecommerce.orders")
    so Canvas table filters work regardless of how the schema context formats
    table headers.

    If `tables` is empty, returns the full schema unchanged.
    """
    if not tables:
        return full_schema

    include = {t.lower() for t in tables}
    # Also build a set of bare-only names for cross-matching qualified <-> bare
    include_bare = {bare(t) for t in tables}
    lines = full_schema.splitlines(keepends=True)
    out: list[str] = []
    in_table_block = False
    keep_block = False
    past_tables = False   # True once we've seen at least one TABLE: line

    for line in lines:
        if line.startswith("TABLE:"):
            past_tables = True
            in_table_block = True
            # Extract table name from "TABLE: orders  (99,441 rows)" or "TABLE: ecommerce.orders"
            raw_name = line.split()[1].lower() if len(line.split()) > 1 else ""
            bare_name = bare(raw_name)
            keep_block = raw_name in include or bare_name in include or raw_name in include_bare or bare_name in include_bare
            if keep_block:
                out.append(line)
        elif in_table_block:
            if line.strip() == "":
                # Blank line ends the current block
                if keep_block:
                    out.append(line)
                in_table_block = False
                keep_block = False
            else:
                if keep_block:
                    out.append(line)
        else:
            # Non-table content (join hints, metrics, profile annotations)
            # Emit only if we're past the table blocks section
            if past_tables:
                out.append(line)

    return "".join(out)


def build_canvas_schema_context(canvas: "Canvas") -> str:  # type: ignore[name-defined]
    """Build a schema context string scoped to a Canvas.

    Opens the Canvas's primary connection, builds the full schema context,
    then filters it down to the Canvas's selected tables (if any).
    The connection's get_schema() handles profiling and glossary enrichment.

    Falls back to the full schema if the Canvas has no table filter or if
    anything goes wrong — never raises.
    """
    from aughor.db.connection import open_connection_for_with_schema

    if not canvas.scopes:
        return ""

    scope = canvas.scopes[0]
    try:
        db = open_connection_for_with_schema(scope.connection_id, schema_name=scope.schema_name)
        full_schema = db.get_schema()
    except Exception:
        return ""

    if scope.is_full_schema:
        return full_schema

    return get_schema_for_tables(full_schema, scope.tables)
