"""Schema introspection — builds the context string fed to the LLM."""
from __future__ import annotations

import os
import re

import duckdb

from aughor.semantic.glossary import apply_glossary
from aughor.db.type_overrides import get_table_overrides
from aughor.tools.table_names import bare

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

# Columns whose names indicate they are IDs/keys — skip value sampling for these.
_KEY_COL = re.compile(
    r"(_id|_key|_code|_num|_number|_identifier|_pk|_uuid|_guid)$",
    re.IGNORECASE,
)

# ── Fuzzy join inference ──────────────────────────────────────────────────────
# Strips these suffixes (longest first) to get the semantic "root" of a column.
# customer_id → customer,  order_key → order,  cust_num → cust
_ROOT_SUFFIXES = sorted(
    # _sk = surrogate key (standard star/snowflake warehouse convention, e.g.
    # TPC-DS ss_item_sk ↔ i_item_sk; also _key/_id for natural keys).
    ["_identifier", "_number", "_pseudonym", "_code", "_num", "_key", "_id", "_sk"],
    key=len, reverse=True,
)

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
    for suffix in _ROOT_SUFFIXES:
        if col.endswith(suffix):
            return col[: -len(suffix)]
    return col


# Short table-name alias prefix used by some schemas on every column
# (TPC-H: c_custkey, o_orderkey, l_partkey). 1–3 letters + underscore so it
# strips c_/o_/ps_ but never a word-prefix like ship_/bill_.
_TABLE_PREFIX = re.compile(r"^[a-z]{1,3}_")


def _fk_root(col: str) -> str | None:
    """Normalised foreign-key root for a *key-like* column, else None.

    Handles the convention where every column carries a short table prefix and
    the key suffix is fused: ``c_custkey`` and ``o_custkey`` both → ``cust`` so
    the customer↔orders FK is detected. Standard ``customer_id`` style still
    maps to ``customer`` (prefix regex doesn't fire, ``_id`` suffix strips).
    Returns None for non-key columns so the caller can fall back to legacy
    behaviour — this is purely additive and introduces no new join candidates
    for non-key columns (e.g. c_acctbal / s_acctbal stay un-joined)."""
    c = col.lower()
    stripped = _TABLE_PREFIX.sub("", c, count=1)
    root = None
    for suffix in _ROOT_SUFFIXES:  # _id, _key, _number, _code, _sk, …
        if stripped.endswith(suffix):
            root = stripped[: -len(suffix)]
            break
    if root is None and stripped.endswith("key") and len(stripped) > 3:  # fused: custkey
        root = stripped[:-3]
    if root is None or len(root) < 3:
        return None
    # Skip date/time surrogate keys. In a star schema every fact carries a
    # *_date_sk / *_time_sk pointing at the shared date_dim/time_dim, so plain
    # root-matching would wrongly join the facts to EACH OTHER (ss_sold_date_sk =
    # cs_sold_date_sk). Modelling FK→dimension-PK needs ownership detection we
    # don't have here; staying silent beats emitting false joins. (The model still
    # joins date_dim from column naming; a temporal-grounding lever is future work.)
    if root == "date" or root == "time" or root.endswith("date") or root.endswith("time"):
        return None
    return root


_SECTION_STOP = re.compile(
    r"^(DETECTED JOIN|NO DIRECT JOIN|METRICS CATALOG|Date range|GLOSSARY|JOIN HINTS|RELEVANT|--)"
)

def _parse_schema_tables(schema_str: str) -> dict[str, list[str]]:
    """Parse TABLE: blocks from a schema string → {table: [col_name, ...]}."""
    table_cols: dict[str, list[str]] = {}
    current: str | None = None
    for line in schema_str.splitlines():
        if _SECTION_STOP.match(line):
            current = None
            continue
        m = re.match(r"^TABLE:\s+([\w.]+)", line)
        if m:
            current = m.group(1)
            table_cols[current] = []
        elif current:
            col_m = re.match(r"^\s{2}(.+?)\s{2,}(\S+)", line)
            if col_m and not line.strip().startswith("--"):
                table_cols[current].append(col_m.group(1))
    return table_cols


def parse_schema_tables(schema_str: str) -> dict[str, list[str]]:
    """Public alias for the schema → {table: [columns]} parser (a stable interface
    callers can import without reaching into the module's internals)."""
    return _parse_schema_tables(schema_str)


def compute_join_map(table_cols: dict[str, list[str]]) -> dict:
    """Public alias for the join-map inferrer (companion to parse_schema_tables);
    lets out-of-module callers build a join map without importing internals."""
    return _compute_join_map(table_cols)


def norm_type(t: str) -> str:
    """Public alias for the column-type normaliser (stable cross-module interface)."""
    return _norm_type(t)


def fk_root(col: str) -> str | None:
    """Public alias for the FK-root extractor (stable cross-module interface)."""
    return _fk_root(col)


# Public alias for the schema-block section-stop matcher (stable cross-module interface).
SECTION_STOP = _SECTION_STOP


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
            kroot = _fk_root(col)
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
        jmap = _compute_join_map(_parse_schema_tables(full_schema))
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
        tcols = _parse_schema_tables(full_schema)
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
    table_cols = _parse_schema_tables(schema_str)
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
    table_cols = _parse_schema_tables(schema_str)
    if not table_cols:
        return ""

    # Also capture column types from the raw schema for richer diagram
    table_col_types: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for line in schema_str.splitlines():
        if _SECTION_STOP.match(line):
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
        if _SECTION_STOP.match(line):
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


def validate_join_path(from_table: str, to_table: str, schema_str: str) -> tuple[bool, str]:
    """
    Check whether two tables have a detectable join path in the schema.

    Returns (True, "") when a shared key column was found (exact or fuzzy root match).
    Returns (False, reason) when both tables exist but share no detected key.
    Returns (False, reason) when either table is not in the schema at all.
    """
    table_cols = _parse_schema_tables(schema_str)
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


def inject_value_annotations(schema_str: str, column_profiles: dict) -> str:
    """
    Enrich TABLE: column lines with actual enumerated values from profiler cache.

    For every column that has low-cardinality top_values in its ColumnProfile,
    appends the values inline:
      `  status  VARCHAR` → `  status  VARCHAR  -- [Shipped, Pending, Canceled, Returned]`

    Skips lines that already carry a `-- [` annotation (from build_schema_context's
    first-run sampling) to avoid duplication.  Profile-backed values are richer
    (frequency-ordered, complete) so they overwrite the first-run annotation when present.
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

        if _SECTION_STOP.match(line):
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

    query_log_annotation: pre-rendered block of facts mined from real query history
    (learned join paths / value domains / business formulas). Decoupled like
    profile_annotation; when left empty it is auto-collected from this connection's
    logged queries iff AUGHOR_QUERY_LOG_MINING=1 (opt-in, best-effort).

    schema_name: when set, filters to only tables in that DuckDB schema so that
    multi-schema files don't bleed tables from other schemas into this context.
    """
    if schema_name:
        # For MotherDuck (multi-database DuckDB), restrict to the current database
        # so we don't bleed tables from other attached databases that share the schema.
        current_db = ""
        try:
            current_db = conn.execute("SELECT current_database()").fetchone()[0]
        except Exception:
            pass
        if current_db:
            tables = [
                row[0] for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = ? AND table_type = 'BASE TABLE' "
                    "AND table_catalog = ? ORDER BY table_name",
                    [schema_name, current_db],
                ).fetchall()
            ]
        else:
            tables = [
                row[0] for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = ? AND table_type = 'BASE TABLE' ORDER BY table_name",
                    [schema_name],
                ).fetchall()
            ]
        # Fallback: the user may have set schema_name to a database name
        # (common with MotherDuck) rather than a DuckDB schema. In that case,
        # information_schema.tables returns nothing — fall back to SHOW TABLES.
        if not tables:
            tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    else:
        tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    parts: list[str] = []

    # Use fully-qualified names when schema is known so queries work even if
    # SET search_path silently failed (DuckDB version differences).
    def _fqn(t: str) -> str:
        return f"{schema_name}.{t}" if schema_name else t

    # Load user-authored annotations (table + column descriptions) if available
    from aughor.db.annotations import load_annotations, inject_into_schema_parts
    _annotations = load_annotations(connection_id) if connection_id else None

    for table in sorted(tables):
        fqn = _fqn(table)
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()[0]
        except Exception:
            count = "?"

        parts.append(f"TABLE: {fqn}  ({count:,} rows)")
        if _annotations:
            inject_into_schema_parts(parts, table, None, _annotations)

        cols = conn.execute(f"DESCRIBE {fqn}").fetchall()
        _overrides = get_table_overrides(connection_id or "", table) if connection_id else {}
        for col in cols:
            col_name, col_type = col[0], col[1]
            if col_name in _overrides:
                col_type = _overrides[col_name]
            parts.append(f"  {col_name}  {col_type}")
            if _annotations:
                inject_into_schema_parts(parts, table, col_name, _annotations)

        # Explicitly flag tables with no date/timestamp columns so the LLM never
        # invents a date column name when building time-series queries on this table.
        _date_types = ("DATE", "TIMESTAMP", "TIME", "INTERVAL")
        has_date_col = any(
            any(dt in col[1].upper() for dt in _date_types) for col in cols
        )
        if not has_date_col:
            parts.append(
                f"  -- ⚠ No date/timestamp columns in {table}. "
                "Do NOT fabricate a date column. Join a table that has one if a time range is needed."
            )

        # Enumerate values for ALL low-cardinality categorical columns (frequency-ordered).
        # Using LIMIT 51: if ≤ 50 rows come back we know cardinality is low enough to list.
        for col_name, col_type in [(c[0], c[1]) for c in cols]:
            if not any(t in col_type.upper() for t in ("VARCHAR", "TEXT", "CHAR", "BOOLEAN")):
                continue
            if _KEY_COL.search(col_name.lower()):
                continue
            try:
                rows = conn.execute(
                    f'SELECT "{col_name}", COUNT(*) AS n FROM {fqn} '
                    f'WHERE "{col_name}" IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 51'
                ).fetchall()
                if rows and 1 <= len(rows) <= 50:
                    vals = ", ".join(str(r[0]) for r in rows)
                    parts.append(f"  -- {col_name}  [{vals}]")
            except Exception:
                pass

        parts.append("")

    # Add date range context
    try:
        date_range = conn.execute(
            "SELECT MIN(date)::VARCHAR, MAX(date)::VARCHAR FROM kpi_daily"
        ).fetchone()
        if date_range:
            parts.append(f"Date range in kpi_daily: {date_range[0]} to {date_range[1]}")
    except Exception:
        pass

    raw = "\n".join(parts)
    from aughor.semantic.autoseed import seed_missing_tables
    from aughor.semantic.retriever import build_schema_index
    from aughor.semantic.metrics import build_metrics_block
    seed_missing_tables(raw)
    enriched = apply_glossary(raw)
    build_schema_index()  # best-effort; keeps vector index fresh after glossary changes
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
