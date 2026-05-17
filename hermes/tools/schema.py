"""Schema introspection — builds the context string fed to the LLM."""
from __future__ import annotations

import re

import duckdb

from hermes.semantic.glossary import apply_glossary

# ── Fuzzy join inference ──────────────────────────────────────────────────────
# Strips these suffixes (longest first) to get the semantic "root" of a column.
# customer_id → customer,  order_key → order,  cust_num → cust
_ROOT_SUFFIXES = sorted(
    ["_identifier", "_number", "_pseudonym", "_code", "_num", "_key", "_id"],
    key=len, reverse=True,
)


def _col_root(col: str) -> str:
    col = col.lower()
    for suffix in _ROOT_SUFFIXES:
        if col.endswith(suffix):
            return col[: -len(suffix)]
    return col


def _parse_schema_tables(schema_str: str) -> dict[str, list[str]]:
    """Parse TABLE: blocks from a schema string → {table: [col_name, ...]}."""
    table_cols: dict[str, list[str]] = {}
    current: str | None = None
    for line in schema_str.splitlines():
        m = re.match(r"^TABLE:\s+(\w+)", line)
        if m:
            current = m.group(1)
            table_cols[current] = []
        elif current:
            col_m = re.match(r"^\s{2}(.+?)\s{2,}(\S+)", line)
            if col_m and not line.strip().startswith("--"):
                table_cols[current].append(col_m.group(1))
    return table_cols


def _compute_join_map(table_cols: dict[str, list[str]]) -> dict:
    """
    Compute join candidates across tables using root-normalised column names.
    Returns {"joins": [...], "no_join": [...]} — same shape as talonsight's get_join_map.
    """
    root_map: dict[str, list[tuple[str, str]]] = {}
    for table, cols in table_cols.items():
        for col in cols:
            root = _col_root(col)
            if len(root) < 3:
                continue
            root_map.setdefault(root, []).append((table, col))

    joined_pairs: set[frozenset[str]] = set()
    joins: list[dict] = []

    for root, entries in root_map.items():
        if len(entries) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                t1, c1 = entries[i]
                t2, c2 = entries[j]
                if t1 == t2:
                    continue
                pair = frozenset([t1, t2])
                if pair in joined_pairs:
                    continue
                match = "exact" if (c1 == c2 or c1.endswith("_id") or c2.endswith("_id")) else "inferred"
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
        parts.append("NO DIRECT JOIN DETECTED — do not hallucinate a JOIN path between:")
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
        m = re.match(r"^TABLE:\s+(\w+)", line)
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
    table_col_types: dict[str, list[tuple[str, str]]] = {}
    table_row_counts: dict[str, str] = {}
    current: str | None = None

    _SECTION_STOP = re.compile(r"^(DETECTED JOIN|NO DIRECT JOIN|METRICS CATALOG|Date range|GLOSSARY|JOIN HINTS)")

    for line in schema_str.splitlines():
        if _SECTION_STOP.match(line):
            current = None
            continue
        m = re.match(r"^TABLE:\s+(\w+)\s*\(?([\d,?]+)?\s*rows?\)?", line)
        if m:
            current = m.group(1)
            if current not in table_col_types:
                table_col_types[current] = []
                if m.group(2):
                    table_row_counts[current] = m.group(2).replace(",", "")
        elif current:
            col_m = re.match(r"^\s{2}(.+?)\s{2,}(\S+)", line)
            if col_m and not line.strip().startswith("--"):
                table_col_types[current].append((col_m.group(1), col_m.group(2)))

    table_cols = {t: [c for c, _ in cols] for t, cols in table_col_types.items()}
    jmap = _compute_join_map(table_cols)

    fk_hints: dict[str, set[str]] = {t: set() for t in table_cols}
    for j in jmap["joins"]:
        fk_hints[j["t1"]].add(j["c1"])
        fk_hints[j["t2"]].add(j["c2"])

    tables = []
    for table, col_type_pairs in table_col_types.items():
        tables.append({
            "name": table,
            "row_count": table_row_counts.get(table),
            "columns": [
                {"name": col, "type": typ, "is_fk": col in fk_hints.get(table, set())}
                for col, typ in col_type_pairs
            ],
        })

    warnings = []

    # Type mismatch on join columns
    type_index: dict[str, dict[str, str]] = {
        t: dict(pairs) for t, pairs in table_col_types.items()
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


def build_schema_context(conn: duckdb.DuckDBPyConnection) -> str:
    """Return a rich schema description for the LLM, including row counts and glossary annotations."""
    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    parts: list[str] = []

    for table in sorted(tables):
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            count = "?"

        parts.append(f"TABLE: {table}  ({count:,} rows)")

        cols = conn.execute(f"DESCRIBE {table}").fetchall()
        for col in cols:
            col_name, col_type = col[0], col[1]
            parts.append(f"  {col_name}  {col_type}")

        # Sample distinct values for categorical columns (quick orientation for the LLM)
        categorical = [c[0] for c in cols if "VARCHAR" in c[1] or "TEXT" in c[1]]
        for col_name in categorical[:3]:
            try:
                vals = conn.execute(
                    f"SELECT DISTINCT {col_name} FROM {table} LIMIT 8"
                ).fetchall()
                sample = ", ".join(str(v[0]) for v in vals if v[0] is not None)
                if sample:
                    parts.append(f"  -- {col_name} sample values: {sample}")
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
    from hermes.semantic.autoseed import seed_missing_tables
    from hermes.semantic.retriever import build_schema_index
    from hermes.semantic.metrics import build_metrics_block
    seed_missing_tables(raw)
    enriched = apply_glossary(raw)
    build_schema_index()  # best-effort; keeps vector index fresh after glossary changes
    join_hints = infer_joins(enriched)
    if join_hints:
        enriched += "\n\n" + join_hints
    metrics_block = build_metrics_block()
    if metrics_block:
        enriched += "\n\n" + metrics_block
    return enriched
