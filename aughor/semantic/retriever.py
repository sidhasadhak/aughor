"""Schema vector index — build from glossary, retrieve relevant tables per hypothesis.

Only activates when the schema has more than TABLE_THRESHOLD tables. Below that the
full schema is always returned so there's no latency cost on small databases.

Graceful degradation: any Qdrant or embedding failure falls back to the full schema
string silently, so the agent always gets a usable context.
"""
from __future__ import annotations

import re

SCHEMA_COLLECTION = "hermes_schema"
TABLE_THRESHOLD = 12  # below this, skip retrieval and pass the full schema


# ── Index building ────────────────────────────────────────────────────────────

def build_schema_index(path=None) -> int:
    """
    Embed all table/column entries from the merged glossary and upsert to Qdrant.
    Called after every schema load so the index stays fresh.
    Returns the number of points indexed, 0 on failure.
    """
    try:
        return _build(path)
    except Exception:
        return 0


def _build(path=None) -> int:
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
        metas.append({"type": "table", "table": table_name})

        # Column-level points
        for col_name, col_meta in (meta.get("columns") or {}).items():
            c_text = f"{table_name}.{col_name}: {col_meta.get('description', col_name)}"
            if col_meta.get("values"):
                c_text += f". Values: {col_meta['values']}"
            texts.append(c_text)
            metas.append({"type": "column", "table": table_name, "column": col_name})

    if not texts:
        return 0

    ensure_collection(SCHEMA_COLLECTION)
    vectors = embed(texts)
    points = [
        {
            "id": f"{m['table']}.{m.get('column', '__table__')}",
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
) -> str:
    """
    Return a schema string containing only the top-k most relevant tables for
    the given hypothesis. Falls back to the full schema when:
    - The schema has ≤ TABLE_THRESHOLD tables (no retrieval needed)
    - Qdrant is unavailable
    - The collection is empty (not yet indexed)
    """
    table_count = len(re.findall(r"^TABLE:", full_schema_str, re.MULTILINE))
    if table_count <= TABLE_THRESHOLD:
        return full_schema_str

    try:
        return _retrieve(hypothesis, full_schema_str, top_k_tables)
    except Exception:
        return full_schema_str


def _retrieve(hypothesis: str, full_schema_str: str, top_k_tables: int) -> str:
    from aughor.semantic.embedder import embed_one
    from aughor.semantic.vector_store import search, collection_count

    # Auto-build index on first use if collection is empty
    if collection_count(SCHEMA_COLLECTION) == 0:
        build_schema_index()

    vector = embed_one(hypothesis)
    # Over-fetch so we can collect enough unique tables after dedup
    hits = search(SCHEMA_COLLECTION, vector, top_k=top_k_tables * 5)

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


def _filter_schema(schema_str: str, keep_tables: set[str]) -> str:
    """Return only the TABLE: blocks for the specified tables, with a header note."""
    blocks: list[str] = []
    current_table: str | None = None
    current_lines: list[str] = []

    for line in schema_str.splitlines():
        m = re.match(r"^TABLE:\s+(\w+)", line)
        if m:
            if current_table and current_table in keep_tables:
                blocks.append("\n".join(current_lines))
            current_table = m.group(1)
            current_lines = [line]
        elif current_table:
            current_lines.append(line)

    # Flush last block
    if current_table and current_table in keep_tables:
        blocks.append("\n".join(current_lines))

    if not blocks:
        return schema_str  # nothing matched — return full schema as safety net

    note = (
        f"[Schema filtered to {len(keep_tables)} relevant tables "
        f"via semantic search: {', '.join(sorted(keep_tables))}]"
    )
    return note + "\n\n" + "\n\n".join(blocks)
