"""Schema-linking pre-filter for Aughor.

Given a natural-language question and a full schema context string, returns a
filtered schema containing only the tables and columns most likely to be relevant.

This is a deterministic, zero-LLM filter — it uses keyword matching, name
normalisation (singular/plural + snake_case), and per-connection hints derived
from the connection's own semantic layer (metrics catalog + knowledge base).
It runs in ~1 ms and cuts schema size for typical questions, which directly
reduces SQL hallucination rates.

Plug-and-play contract:
  * Hints are DERIVED from the connected database's metrics/KB — not hardwired to
    any one schema. The built-in e-commerce dictionary is only a last-resort
    fallback used when a connection has no semantic layer yet.
  * The filter never returns an EMPTY schema. If no table shows any signal for
    the question, the full schema is returned unchanged (recall safety).

Usage:
    from aughor.tools.schema_linker import link_schema
    filtered = link_schema(question, full_schema, top_k_tables=4, top_k_cols=8,
                           connection_id=conn_id)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
_DATA_DIR = Path(__file__).parent.parent.parent / "data"

# ── Stop words ────────────────────────────────────────────────────────────────
_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "need", "dare", "ought", "used",
    "to", "of", "in", "on", "at", "by", "for", "with", "about", "against",
    "between", "into", "through", "during", "before", "after", "above",
    "below", "from", "up", "down", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "show", "me", "give", "tell", "what", "which",
    "who", "whom", "whose", "this", "that", "these", "those", "am", "get",
    "did", "does", "done", "each", "every", "find", "list", "and", "or",
})

# ── Default (fallback) hints ──────────────────────────────────────────────────
# These map common business terms to likely table / column name fragments for a
# generic e-commerce schema. They are ONLY consulted when the connection has no
# metrics/KB to derive hints from — they are NOT the primary signal and must
# never be relied on for non-e-commerce schemas. See build_connection_hints().
_DEFAULT_TABLE_HINTS: dict[str, list[str]] = {
    "order": ["orders", "order_items"],
    "purchase": ["orders", "order_items"],
    "sale": ["orders", "order_items"],
    "transaction": ["orders"],
    "customer": ["customers"],
    "user": ["customers"],
    "buyer": ["customers"],
    "product": ["products", "order_items"],
    "item": ["order_items", "products"],
    "review": ["reviews"],
    "rating": ["reviews"],
    "feedback": ["reviews"],
    "revenue": ["orders", "order_items"],
    "amount": ["orders", "order_items"],
    "price": ["products", "order_items"],
    "category": ["products"],
    "stock": ["products"],
    "inventory": ["products"],
    "delivery": ["orders"],
    "shipment": ["orders"],
    "shipping": ["orders"],
    "payment": ["orders"],
    "refund": ["orders"],
    "cancel": ["orders"],
    "return": ["orders"],
    "country": ["customers"],
    "city": ["customers"],
    "signup": ["customers"],
    "register": ["customers"],
    "cohort": ["customers"],
    "lifetime": ["customers"],
}

_DEFAULT_COL_HINTS: dict[str, list[str]] = {
    "revenue": ["total_amount", "line_total", "price"],
    "aov": ["total_amount"],
    "order value": ["total_amount"],
    "average order": ["total_amount"],
    "sales": ["total_amount", "line_total"],
    "quantity": ["quantity", "item_count"],
    "count": ["order_id", "customer_id", "product_id"],
    "status": ["status"],
    "date": ["order_date", "signup_date", "review_date", "shipped_at", "delivered_at"],
    "month": ["order_date", "signup_date", "review_date"],
    "year": ["order_date", "signup_date", "review_date"],
    "delivery time": ["shipped_at", "delivered_at"],
    "shipping time": ["shipped_at", "delivered_at"],
    "rating": ["rating"],
    "review": ["rating", "review_text"],
    "category": ["category"],
    "product name": ["product_name"],
    "payment": ["payment_method"],
    "method": ["payment_method"],
    "country": ["country"],
    "city": ["city"],
    "customer name": ["full_name"],
    "name": ["full_name", "product_name"],
    "email": ["email"],
    "out of stock": ["is_out_of_stock", "stock_quantity"],
    "stock": ["stock_quantity", "is_out_of_stock"],
    "price": ["price", "unit_price"],
    "unit price": ["unit_price"],
    "lifetime": ["lifetime_spend", "lifetime_orders"],
    "spend": ["lifetime_spend", "total_amount"],
}

# SQL keywords to ignore when pulling column identifiers out of a metric formula.
_SQL_KEYWORDS: frozenset[str] = frozenset({
    "select", "from", "where", "group", "by", "order", "having", "as", "and",
    "or", "not", "null", "is", "in", "on", "join", "left", "right", "inner",
    "outer", "full", "case", "when", "then", "else", "end", "sum", "count",
    "avg", "min", "max", "distinct", "cast", "coalesce", "over", "partition",
    "asc", "desc", "limit", "offset", "between", "like", "exists", "union",
    "all", "with", "date", "interval", "extract", "float", "double", "int",
    "integer", "varchar", "numeric", "decimal", "true", "false",
})


# ── Morphology (singular/plural/snake) ────────────────────────────────────────

def _singular(token: str) -> str:
    """Cheap, dependency-free singulariser. 'orders'→'order', 'categories'→'category'."""
    t = token
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith("ses"):
        return t[:-2]            # 'addresses'→'address', 'statuses'→'status'
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _morph(token: str) -> set[str]:
    """All useful surface forms of a token: itself, singular, snake_case parts."""
    out = {token}
    out.add(_singular(token))
    for part in token.split("_"):
        if part and part not in _STOP_WORDS:
            out.add(part)
            out.add(_singular(part))
    return {t for t in out if t}


def _expand_tokens(tokens: set[str]) -> set[str]:
    """Expand a token set with morphological variants."""
    expanded: set[str] = set()
    for t in tokens:
        expanded |= _morph(t)
    return expanded


def _tokenise(text: str) -> list[str]:
    """Lower-case, alphanumeric/underscore tokens."""
    return [t.lower() for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)]


def _columns_from_sql(sql: str) -> set[str]:
    """Pull candidate column identifiers from a metric formula (best-effort)."""
    if not sql:
        return set()
    toks = {t.lower() for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", sql)}
    return {t for t in toks if t not in _SQL_KEYWORDS and len(t) > 1}


# ── Per-connection hint derivation (the de-hardwiring) ────────────────────────
# Cache keyed by connection_id → (table_hints, col_hints, synonym_expansion).
_hint_cache: dict[str, tuple[dict[str, list[str]], dict[str, list[str]], dict[str, set[str]]]] = {}


def _add_hint(d: dict[str, list[str]], term: str, target: str) -> None:
    term = (term or "").lower().strip()
    target = (target or "").lower().strip()
    if not term or not target or term in _STOP_WORDS or len(term) < 2:
        return
    bucket = d.setdefault(term, [])
    if target not in bucket:
        bucket.append(target)


def build_connection_hints(
    connection_id: str | None,
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, set[str]]]:
    """Derive (table_hints, col_hints, synonym_expansion) from a connection's
    own semantic layer — its metrics catalog and knowledge base — so the linker
    works on ANY schema without hardwired table names.

    Returns empty dicts when the connection has no semantic layer (the caller
    then falls back to the built-in default hints). Fully fail-safe + cached.
    """
    if not connection_id:
        return {}, {}, {}
    if connection_id in _hint_cache:
        return _hint_cache[connection_id]

    table_hints: dict[str, list[str]] = {}
    col_hints: dict[str, list[str]] = {}
    synonyms: dict[str, set[str]] = {}

    # 1. Metrics catalog — metric name/label → its tables; metric sql → columns.
    #    This is the strongest, fully schema-specific signal (data-derived).
    try:
        import json
        mpath = _DATA_DIR / "metrics.json"
        metrics = json.loads(mpath.read_text()) if mpath.exists() else []
        for m in metrics if isinstance(metrics, list) else []:
            name_tokens = set(_tokenise(f"{m.get('name','')} {m.get('label','')}"))
            name_tokens = _expand_tokens(name_tokens) - _STOP_WORDS
            tables = [str(t) for t in (m.get("tables") or [])]
            cols = {c.lower() for c in (m.get("dimensions") or [])}
            cols |= _columns_from_sql(str(m.get("sql") or ""))
            for tok in name_tokens:
                for t in tables:
                    _add_hint(table_hints, tok, t.rsplit(".", 1)[-1])
                for c in cols:
                    _add_hint(col_hints, tok, c)
    except Exception:
        logger.debug("metrics-derived hints unavailable", exc_info=True)

    # 2. Connection KB — synonym/join entries expand question vocabulary.
    #    title + tags become mutually-synonymous terms, so a query using one
    #    surfaces the others (which then match metric/table hints or names).
    try:
        from aughor.semantic.connection_kb import load_entries
        for e in load_entries(connection_id):
            terms = set(_tokenise(getattr(e, "title", "")))
            terms |= {str(t).lower() for t in (getattr(e, "tags", None) or [])}
            terms = {t for t in _expand_tokens(terms) if t not in _STOP_WORDS and len(t) > 1}
            for t in terms:
                synonyms.setdefault(t, set()).update(terms - {t})
    except Exception:
        logger.debug("connection-KB hints unavailable for %s", connection_id, exc_info=True)

    result = (table_hints, col_hints, synonyms)
    _hint_cache[connection_id] = result
    return result


def invalidate_hints(connection_id: str | None = None) -> None:
    """Drop cached hints (call after metrics/KB edits)."""
    if connection_id is None:
        _hint_cache.clear()
    else:
        _hint_cache.pop(connection_id, None)


# ── Schema parsing ────────────────────────────────────────────────────────────

def _extract_schema_blocks(schema_str: str) -> list[dict]:
    """Parse a schema context string into table blocks."""
    blocks: list[dict] = []
    current: Optional[dict] = None
    for line in schema_str.splitlines():
        if line.startswith("TABLE:"):
            m = re.match(r"TABLE:\s+(\S+)", line)
            if m:
                current = {"table": m.group(1), "header": line, "columns": []}
                blocks.append(current)
        elif current is not None:
            cm = re.match(r"^\s{2}(\w+)\s+(\S+)", line)
            if cm:
                current["columns"].append({"name": cm.group(1), "type": cm.group(2), "line": line})
    return blocks


def _bare_table(name: str) -> str:
    """Extract the bare table name from a possibly schema-qualified name."""
    return name.lower().rsplit(".", 1)[-1]


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_table(
    block: dict,
    tokens: set[str],
    table_hints: dict[str, list[str]],
) -> float:
    """Score how relevant a table is to the (morphologically-expanded) question
    tokens. Generic signals (name match, hint match, fuzzy substring) only —
    no schema is privileged."""
    table_name = block["table"].lower()
    bare_name = _bare_table(table_name)
    name_forms = _morph(bare_name) | {table_name, bare_name}
    score = 0.0

    # Exact / morphological table-name match (e.g. "orders"~"order").
    if name_forms & tokens:
        score += 3.0

    # Hint match — term → table fragment.
    for token in tokens:
        for hint in table_hints.get(token, []):
            if hint in (table_name, bare_name) or hint in name_forms:
                score += 2.0

    # Fuzzy substring (e.g. "order" inside "order_items").
    for token in tokens:
        if len(token) > 3 and (token in table_name or _singular(token) in bare_name):
            score += 0.5

    # Column-aware: a table whose COLUMNS match the question is relevant even when
    # its name doesn't (e.g. "amount billed" → claims.amount_billed). This is the
    # main recall lever on arbitrary schemas where measures live in oddly-named
    # tables. Capped so a name match still dominates.
    col_hit = 0.0
    for col in block.get("columns", []):
        if _morph(col["name"].lower()) & tokens:
            col_hit += 0.75
    score += min(col_hit, 2.25)

    return score


def _score_column(
    col: dict,
    tokens: set[str],
    question_lower: str,
    col_hints: dict[str, list[str]],
) -> float:
    """Score how relevant a column is to the question."""
    col_name = col["name"].lower()
    col_type = col["type"].upper()
    col_forms = _morph(col_name)
    score = 0.0

    # Exact / morphological column-name match.
    if col_forms & tokens:
        score += 2.0

    # Hint match — multi-word phrases checked against the raw question.
    for phrase, hints in col_hints.items():
        if phrase in question_lower or phrase in tokens:
            if col_name in {h.lower() for h in hints}:
                score += 2.5

    # Date-shaped questions → boost date/time columns.
    if any(w in question_lower for w in ("month", "year", "quarter", "day", "week", "trend", "over time")):
        if any(dt in col_type for dt in ("DATE", "TIMESTAMP", "TIME")):
            score += 1.5

    # Aggregation questions → boost numeric columns.
    if any(w in question_lower for w in ("average", "avg", "sum", "total", "count", "max", "min")):
        if any(nt in col_type for nt in ("INT", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL")):
            score += 0.5

    return score


# ── Public API ────────────────────────────────────────────────────────────────

def link_schema(
    question: str,
    schema_str: str,
    *,
    top_k_tables: int = 4,
    top_k_cols: int = 8,
    always_include: list[str] | None = None,
    connection_id: str | None = None,
) -> str:
    """Return a schema string filtered to the tables/columns most relevant to the
    question. Hints are derived from the connection's own semantic layer when a
    connection_id is supplied; otherwise the built-in defaults are used.

    Recall safety: if no table shows ANY signal, the full schema is returned
    unchanged — the filter never strips the schema down to nothing.
    """
    if not schema_str or not question:
        return schema_str

    question_lower = question.lower()
    raw_tokens = set(_tokenise(question)) - _STOP_WORDS
    tokens = _expand_tokens(raw_tokens) - _STOP_WORDS

    # Per-connection hints (de-hardwired); fall back to defaults when absent.
    conn_table_hints, conn_col_hints, synonyms = build_connection_hints(connection_id)
    table_hints = conn_table_hints or _DEFAULT_TABLE_HINTS
    col_hints = conn_col_hints or _DEFAULT_COL_HINTS

    # Expand tokens through user-authored synonyms (KB-derived).
    if synonyms:
        extra: set[str] = set()
        for t in list(tokens):
            extra |= synonyms.get(t, set())
        tokens |= extra

    always = {t.lower() for t in (always_include or [])}

    blocks = _extract_schema_blocks(schema_str)
    if not blocks:
        return schema_str

    scored_tables = [(_score_table(b, tokens, table_hints), b) for b in blocks]
    scored_tables.sort(key=lambda x: x[0], reverse=True)

    best_score = scored_tables[0][0] if scored_tables else 0.0

    # ── Recall safety: no signal at all → return the schema untouched. ────────
    # Filtering on noise is how a non-e-commerce schema ends up with an empty
    # context and the model hallucinates table names. Better to send everything.
    if best_score <= 0 and not always:
        return schema_str

    keep_tables = {b["table"].lower() for s, b in scored_tables[:top_k_tables] if s > 0}
    for table_name in always:
        keep_tables.add(table_name)
    # Guarantee at least the single best-scoring table survives.
    if not keep_tables and scored_tables:
        keep_tables.add(scored_tables[0][1]["table"].lower())

    out_lines: list[str] = []
    for score, block in scored_tables:
        if block["table"].lower() not in keep_tables:
            continue
        scored_cols = [(_score_column(c, tokens, question_lower, col_hints), c) for c in block["columns"]]
        scored_cols.sort(key=lambda x: x[0], reverse=True)
        keep_cols = scored_cols[:top_k_cols]

        out_lines.append(block["header"])
        for _, col in keep_cols:
            out_lines.append(col["line"])
        out_lines.append("")

    # Append non-table trailing content (join hints, metrics, etc.) verbatim.
    past_tables = False
    for line in schema_str.splitlines():
        if line.startswith("TABLE:"):
            past_tables = True
        if not past_tables:
            continue
        if not line.startswith("TABLE:") and not re.match(r"^\s{2}\w+", line):
            out_lines.append(line)

    filtered = "\n".join(out_lines)
    # Final guard: never emit a schema with zero tables.
    if "TABLE:" not in filtered:
        return schema_str
    return filtered


def link_schema_for_prompt(
    question: str,
    schema_str: str,
    *,
    top_k_tables: int = 4,
    top_k_cols: int = 8,
    connection_id: str | None = None,
) -> str:
    """Wrapper that adds a header note explaining the filter, for LLM prompts."""
    filtered = link_schema(
        question, schema_str,
        top_k_tables=top_k_tables, top_k_cols=top_k_cols, connection_id=connection_id,
    )
    if filtered == schema_str:
        return schema_str
    return (
        "-- Schema filtered to tables/columns most relevant to the question.\n"
        "-- Full schema is available if needed.\n\n"
        + filtered
    )
