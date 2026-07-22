"""Schema vector index — build from glossary, retrieve relevant tables per hypothesis.

Only activates when the schema has more than TABLE_THRESHOLD tables. Below that the
full schema is always returned so there's no latency cost on small databases.

Graceful degradation: any Qdrant or embedding failure falls back to the full schema
string silently, so the agent always gets a usable context.
"""
from __future__ import annotations

import re

from aughor.tools.table_names import same_table

SCHEMA_COLLECTION = "aughor_schema"
TABLE_THRESHOLD = 12  # below this, skip retrieval and pass the full schema


def scope_key(connection_id: str | None = "", schema_name: str | None = "") -> str:
    """Which connection+schema a point belongs to. ``""`` when neither is known.

    One collection holds every scope's points, and until this existed they carried no
    owner at all: point ids were ``{table}.{column}``, so two connections that both have
    ``analytics.orders`` wrote the SAME point and the later index silently replaced the
    earlier one's embedding — retrieval for one connection then ranked by the other's
    descriptions. Searches were unfiltered too, so foreign tables consumed top-k slots and
    were dropped later by the schema filter, quietly returning fewer tables than asked for.
    """
    conn = (connection_id or "").strip()
    sch = (schema_name or "").strip()
    return f"{conn}|{sch}" if (conn or sch) else ""


def _scope_filter(scope: str):
    """Qdrant filter restricting a search to one scope, or None when unscoped.

    Points indexed before scoping existed carry no ``scope`` payload, so this matches none
    of them: an upgraded install retrieves nothing once, falls back to the full schema (the
    documented degradation), and self-heals on the next schema load — ``build_schema_index``
    runs on every one. Preferred over matching legacy points, which would reintroduce
    exactly the cross-connection bleed this closes.
    """
    if not scope:
        return None
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        return Filter(must=[FieldCondition(key="scope", match=MatchValue(value=scope))])
    except Exception:
        return None


# ── Index building ────────────────────────────────────────────────────────────

def build_schema_index(path=None, connection_id: str = "", schema_name: str = "") -> int:
    """
    Embed all table/column entries from the merged glossary and upsert to Qdrant.
    Called after every schema load so the index stays fresh.
    Returns the number of points indexed, 0 on failure.

    ``connection_id`` / ``schema_name`` stamp each point with its owner so one
    connection's index can neither overwrite nor answer for another's.
    """
    try:
        return _build(path, scope_key(connection_id, schema_name))
    except Exception:
        return 0


def _build(path=None, scope: str = "") -> int:
    from aughor.semantic.glossary import load_merged_glossary
    from aughor.semantic.embedder import embed
    from aughor.semantic.vector_store import ensure_collection, upsert

    tables = load_merged_glossary(path).get("tables", {})
    if not tables:
        return 0

    texts: list[str] = []
    metas: list[dict] = []

    for table_name, meta in tables.items():
        # Table-level point: description + grain
        t_text = f"{table_name}: {meta.get('description', table_name)}"
        if meta.get("grain"):
            t_text += f". Grain: {meta['grain']}"
        texts.append(t_text)
        metas.append({"type": "table", "table": table_name, "scope": scope})

        # Column-level points
        for col_name, col_meta in (meta.get("columns") or {}).items():
            c_text = f"{table_name}.{col_name}: {col_meta.get('description', col_name)}"
            if col_meta.get("values"):
                c_text += f". Values: {col_meta['values']}"
            texts.append(c_text)
            metas.append({"type": "column", "table": table_name,
                          "column": col_name, "scope": scope})

    if not texts:
        return 0

    ensure_collection(SCHEMA_COLLECTION)
    vectors = embed(texts)
    points = [
        {
            # Scope leads the id: without it two connections holding the same qualified
            # table name resolved to one point, so indexing either overwrote the other.
            "id": f"{scope}|{m['table']}.{m.get('column', '__table__')}",
            "vector": v,
            "payload": m,
        }
        for m, v in zip(metas, vectors)
    ]
    upsert(SCHEMA_COLLECTION, points)
    return len(points)


# ── Retrieval ─────────────────────────────────────────────────────────────────

def retrieve_relevant_schema(
    hypothesis: str,
    full_schema_str: str,
    top_k_tables: int = 5,
    connection_id: str = "",
    schema_name: str = "",
) -> str:
    """
    Return a schema string containing only the top-k most relevant tables for
    the given hypothesis. Falls back to the full schema when:
    - The schema has ≤ TABLE_THRESHOLD tables (no retrieval needed)
    - Qdrant is unavailable
    - The collection is empty (not yet indexed)
    - Nothing is indexed for this scope yet

    ``connection_id`` / ``schema_name`` restrict the search to this scope's own points.
    Named ``schema_name``, not ``schema``: the second positional is the schema TEXT, and a
    bare ``schema=`` reads like that rather than the schema this run is scoped to.
    """
    table_count = len(re.findall(r"^TABLE:", full_schema_str, re.MULTILINE))
    if table_count <= TABLE_THRESHOLD:
        return full_schema_str

    try:
        return _retrieve(hypothesis, full_schema_str, top_k_tables,
                         scope_key(connection_id, schema_name))
    except Exception:
        return full_schema_str


def _retrieve(hypothesis: str, full_schema_str: str, top_k_tables: int,
              scope: str = "") -> str:
    from aughor.semantic.embedder import embed_one
    from aughor.semantic.vector_store import search, collection_count

    # Auto-build index on first use if collection is empty
    if collection_count(SCHEMA_COLLECTION) == 0:
        build_schema_index()

    vector = embed_one(hypothesis)
    # Over-fetch so we can collect enough unique tables after dedup
    hits = search(SCHEMA_COLLECTION, vector, top_k=top_k_tables * 5,
                  query_filter=_scope_filter(scope))

    if not hits:
        return full_schema_str

    seen: set[str] = set()
    relevant_tables: list[str] = []
    for hit in hits:
        t = hit["payload"].get("table")
        if t and t not in seen:
            seen.add(t)
            relevant_tables.append(t)
        if len(relevant_tables) >= top_k_tables:
            break

    if not relevant_tables:
        return full_schema_str

    return _filter_schema(full_schema_str, set(relevant_tables))


def _keep(table: str | None, keep_tables: set[str]) -> bool:
    """Is this ``TABLE:`` header one of the retrieved tables?

    Tolerant of qualified-vs-bare, because the two sides come from different producers:
    ``keep_tables`` holds GLOSSARY keys (now schema-qualified whenever the schema was known),
    while the header is whatever the connector emitted — and DuckDB qualifies while Postgres /
    SQLite / Snowflake / MySQL / BigQuery do not. An exact-string check silently dropped a
    retrieved table's block from the prompt whenever the two forms disagreed, which is a far
    worse failure than over-inclusion: the model is told the table does not exist.
    ``schema_strict`` still prevents a different schema's same-named table from matching."""
    if not table:
        return False
    return any(same_table(k, table, schema_strict=True) for k in keep_tables)


def _filter_schema(schema_str: str, keep_tables: set[str]) -> str:
    """Return only the TABLE: blocks for the specified tables, with a header note."""
    blocks: list[str] = []
    current_table: str | None = None
    current_lines: list[str] = []

    for line in schema_str.splitlines():
        m = re.match(r"^TABLE:\s+([\w.]+)", line)
        if m:
            if _keep(current_table, keep_tables):
                blocks.append("\n".join(current_lines))
            current_table = m.group(1)
            current_lines = [line]
        elif current_table:
            current_lines.append(line)

    # Flush last block
    if _keep(current_table, keep_tables):
        blocks.append("\n".join(current_lines))

    if not blocks:
        return schema_str  # nothing matched — return full schema as safety net

    note = (
        f"[Schema filtered to {len(keep_tables)} relevant tables "
        f"via semantic search: {', '.join(sorted(keep_tables))}]"
    )
    return note + "\n\n" + "\n\n".join(blocks)
