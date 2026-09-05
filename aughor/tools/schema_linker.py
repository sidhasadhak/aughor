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
    filtered = link_schema(question, full_schema, connection_id=conn_id)
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

    # 3. Wave O1a — the DECLARED synonym store. Added last so it wins: the two derivations
    #    above are inferences (metric names, KB titles/tags), and a recorded synonym is a
    #    statement. Before O1 there was no store at all and this function WAS the synonym
    #    story, which is why it reads the store rather than the store paralleling it — two
    #    synonym dialects is the Wave V lesson at smaller scale.
    try:
        from aughor.ontology.vocabulary import synonym_expansion
        for term, subjects in synonym_expansion(connection_id).items():
            if term in _STOP_WORDS or len(term) < 2:
                continue
            # A declared synonym also feeds the hint maps, so "takings" reaches the same
            # table `revenue` does — a synonym nothing can match is a synonym that only
            # looks like it works.
            for subject in subjects:
                _add_hint(table_hints, term, subject)
                _add_hint(col_hints, term, subject)
            synonyms.setdefault(term, set()).update(subjects)
    except Exception:
        logger.debug("declared synonyms unavailable for %s", connection_id, exc_info=True)

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
    hint_weight: float = 2.0,
) -> float:
    """Score how relevant a table is to the (morphologically-expanded) question
    tokens. Generic signals (name match, hint match, fuzzy substring) only —
    no schema is privileged. ``hint_weight`` is how much a hint match counts:
    full weight when the hints were DERIVED from this connection's own semantic
    layer, tie-breaker weight (below any real token match) when they are the
    built-in e-commerce fallback — a generic dictionary must never outvote the
    schema's own names on somebody else's domain (A3)."""
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
                score += hint_weight

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
    hint_weight: float = 2.5,
) -> float:
    """Score how relevant a column is to the question. ``hint_weight`` follows the
    same derived-vs-fallback rule as `_score_table`."""
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
                score += hint_weight

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

# Sharded/dated table suffixes that explode wide-warehouse schemas: GA_SESSIONS_20160801,
# events_2021_01, TCGA_HG19_DATA_V0. Stripped to a common stem so a whole family collapses to one
# representative block + a count note — the #1 context-reduction lever for enterprise schemas.
_SHARD_SUFFIX = re.compile(r"_(?:\d{4}_\d{2}_\d{2}|\d{4}_\d{2}|\d{4,8}|v\d+|\d+)$", re.IGNORECASE)


def _shard_stem(table_name: str) -> str:
    bare = table_name.rsplit(".", 1)[-1]
    prev = None
    while prev != bare:               # peel repeated suffixes: events_2021_01 → events
        prev = bare
        bare = _SHARD_SUFFIX.sub("", bare)
    return bare.lower()


def compress_schema(schema_str: str, *, min_group: int = 3) -> str:
    """Collapse families of sharded/dated tables (same stem, e.g. ``events_2021_01 … events_2023_12``)
    to ONE representative block + a count note, leaving every non-sharded table untouched.

    On enterprise warehouses a single logical table is often thousands of dated partitions; including
    them all blows the context window (50MB→<2MB from this alone, arXiv 2502.00675). Recall-safe: a
    table is only collapsed when it is one of ``>= min_group`` siblings sharing a stem — uniquely
    named tables always survive in full — and a no-op on ordinary schemas (returns the input string)."""
    if not schema_str:
        return schema_str
    pre: list[str] = []
    blocks: list[dict] = []
    cur: Optional[dict] = None
    for ln in schema_str.splitlines():
        if ln.startswith("TABLE:"):
            m = re.match(r"TABLE:\s+(\S+)", ln)
            cur = {"name": m.group(1) if m else "", "lines": [ln]}
            blocks.append(cur)
        elif cur is None:
            pre.append(ln)
        else:
            cur["lines"].append(ln)
    if len(blocks) < min_group:
        return schema_str

    groups: dict[str, list[dict]] = {}
    for b in blocks:
        groups.setdefault(_shard_stem(b["name"]), []).append(b)
    if not any(len(g) >= min_group for g in groups.values()):
        return schema_str   # nothing shards ⇒ unchanged

    out = list(pre)
    emitted: set[str] = set()
    for b in blocks:
        stem = _shard_stem(b["name"])
        g = groups[stem]
        if len(g) >= min_group:
            if stem in emitted:
                continue                # sibling already represented
            emitted.add(stem)
            out.extend(g[0]["lines"])   # keep the first sibling in full as the representative
            others = [x["name"] for x in g[1:]]
            sample = ", ".join(others[:3]) + (", …" if len(others) > 3 else "")
            out.append(f"-- + {len(others)} more sharded tables with the same schema "
                       f"(e.g. {sample}) — one logical table; query the family by its shared structure")
        else:
            out.extend(b["lines"])      # non-sharded table — always preserved in full
    return "\n".join(out)


def _linker_budgets() -> tuple[int, int, int]:
    """(top_tables, top_cols, char_budget) from the bound coder's ModelProfile —
    the A3 change: the linker is a RANKER packed to the model's real window, not
    a fixed 4×8 bouncer. Fail-safe to the baseline constants (the old behaviour
    exactly) when the binding cannot be resolved."""
    try:
        from aughor.llm.profile import profile_for
        p = profile_for("coder")
        return p.linker_top_tables, p.linker_top_cols, p.schema_char_limit
    except Exception:
        return 4, 8, 20_000


def _routing_twins(question: str, keep_tables: set[str],
                   connection_id: str | None) -> list[str]:
    """Preferred tables a human routed to, for tables already in the keep-set.

    Never raises: guidance that cannot be loaded must cost the linker nothing. The
    schema name is not threaded here — the linker is called with a connection id
    only, and the override store's default scope is what the ontology writes.
    """
    if not connection_id:
        return []
    try:
        from aughor.ontology.routing import preferred_for
        return preferred_for(question, keep_tables, connection_id)
    except Exception:
        logger.debug("linker: routing guidance unavailable", exc_info=True)
        return []


def link_schema(
    question: str,
    schema_str: str,
    *,
    top_k_tables: int | None = None,
    top_k_cols: int | None = None,
    char_budget: int | None = None,
    always_include: list[str] | None = None,
    connection_id: str | None = None,
) -> str:
    """Return a schema string filtered to the tables/columns most relevant to the
    question, packed to the bound model's budget. Hints are derived from the
    connection's own semantic layer when a connection_id is supplied; the built-in
    e-commerce dictionary is only a tie-breaker fallback.

    A3 (ranks, not drops): tables are ordered by score and included while BOTH the
    rank bound and the char budget hold — on a capable model that is up to 24
    tables into a 60k window; on the baseline it is the old top-4×8 exactly.
    Explicit keyword arguments still win (tests, callers with their own budget).

    Recall safety: if no table shows ANY signal, the full schema is returned
    unchanged — the filter never strips the schema down to nothing.
    """
    if not schema_str or not question:
        return schema_str
    _d_tables, _d_cols, _d_chars = _linker_budgets()
    if top_k_tables is None:
        top_k_tables = _d_tables
    if top_k_cols is None:
        top_k_cols = _d_cols
    if char_budget is None:
        char_budget = _d_chars

    # Collapse sharded/dated table families first (no-op on ordinary schemas), so keyword linking
    # operates on the compact, de-duplicated schema rather than thousands of date partitions.
    schema_str = compress_schema(schema_str)

    # Full-schema-first (grounding.full_schema_first, EXPERIMENT): when the whole
    # compressed schema already fits the budget the packer would have spent anyway,
    # pruning buys no tokens and costs structure — a column dropped by top_k_cols
    # is invisible to the model even though it fits. Off by default until the E4
    # grid settles it; `always_include`/routing twins need no handling here because
    # the full schema contains them by definition.
    from aughor.kernel.flags import flag_enabled
    if flag_enabled("grounding.full_schema_first") and len(schema_str) <= char_budget:
        return schema_str

    question_lower = question.lower()
    raw_tokens = set(_tokenise(question)) - _STOP_WORDS
    tokens = _expand_tokens(raw_tokens) - _STOP_WORDS

    # Per-connection hints (de-hardwired); fall back to defaults when absent —
    # but a DERIVED hint is evidence and keeps full weight, while the generic
    # fallback dictionary only breaks ties (A3: it must never outvote the
    # schema's own names on somebody else's domain).
    conn_table_hints, conn_col_hints, synonyms = build_connection_hints(connection_id)
    table_hints = conn_table_hints or _DEFAULT_TABLE_HINTS
    col_hints = conn_col_hints or _DEFAULT_COL_HINTS
    table_hint_weight = 2.0 if conn_table_hints else 0.25
    col_hint_weight = 2.5 if conn_col_hints else 0.25

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

    scored_tables = [(_score_table(b, tokens, table_hints, table_hint_weight), b)
                     for b in blocks]
    scored_tables.sort(key=lambda x: x[0], reverse=True)

    best_score = scored_tables[0][0] if scored_tables else 0.0

    # ── Recall safety: no signal at all → return the schema untouched. ────────
    # Filtering on noise is how a non-e-commerce schema ends up with an empty
    # context and the model hallucinates table names. Better to send everything.
    if best_score <= 0 and not always:
        return schema_str

    keep_tables = {b["table"].lower() for s, b in scored_tables[:top_k_tables] if s > 0}
    # Routing guidance (Wave 2 / 1.1) — the linker is the SECOND door to the prompt.
    # The retriever adds a preferred twin to its own keep-set; if the packer here then
    # dropped that twin, the guidance would be a feature with both ends built and no
    # middle. Same additive rule: the deprecated table stays. Resolved AFTER scoring
    # so a preferred table that already scored well is not double-counted, and folded
    # into `always` so it rides the same pin the explicit parameter uses.
    always = always | {t.lower() for t in _routing_twins(question, keep_tables, connection_id)}
    for table_name in always:
        keep_tables.add(table_name)
    # Guarantee at least the single best-scoring table survives.
    if not keep_tables and scored_tables:
        keep_tables.add(scored_tables[0][1]["table"].lower())

    out_lines: list[str] = []
    spent = 0
    included = 0
    for score, block in scored_tables:
        if block["table"].lower() not in keep_tables:
            continue
        scored_cols = [(_score_column(c, tokens, question_lower, col_hints, col_hint_weight), c)
                       for c in block["columns"]]
        scored_cols.sort(key=lambda x: x[0], reverse=True)
        keep_cols = scored_cols[:top_k_cols]

        block_lines = [block["header"]] + [col["line"] for _, col in keep_cols] + [""]
        block_chars = sum(len(line) + 1 for line in block_lines)
        # Pack to the char budget: rank order means what falls off the end is the
        # LEAST relevant, never an arbitrary slice. The first table always fits
        # (recall safety over budget purity — an empty schema helps nobody).
        if included and spent + block_chars > char_budget:
            break
        out_lines.extend(block_lines)
        spent += block_chars
        included += 1

    # Append the trailing enrichment sections (join hints, metrics catalog, data
    # profiles, …) VERBATIM. The region starts at the first section header — an
    # unindented, non-blank line after the tables that is neither a TABLE: header
    # nor a `--` note (compress_schema's shard notes are top-level `--` lines
    # between blocks). Structural, not a header name list: a new section kind
    # must not reintroduce this bug by being absent from an enumeration.
    #
    # Selecting section CONTENT by line shape is what this pass must never do
    # again: a join-hint detail or metric formula line is indistinguishable from
    # a column line (`  orders.customer_id → …`), so shape-matching kept bare
    # headers over stripped bodies — a header asserting content that wasn't
    # there — while value enumerations from DROPPED tables leaked in after them.
    lines = schema_str.splitlines()
    past_tables = False
    for i, line in enumerate(lines):
        if line.startswith("TABLE:"):
            past_tables = True
            continue
        if not past_tables or not line.strip():
            continue
        if not line.startswith((" ", "\t", "--")):
            out_lines.extend(lines[i:])
            break

    filtered = "\n".join(out_lines)
    # Final guard: never emit a schema with zero tables.
    if "TABLE:" not in filtered:
        return schema_str
    return filtered


#: The table budget when NOTHING in the question scores. Deliberately the BASELINE tier's
#: `context_table_cap` (llm/profile.py) — "the behaviour everything was measured against" —
#: rather than a new number: a capable model's larger budget is a budget for tables we have
#: reason to send, and with no relevance signal we have none.
_NO_SIGNAL_TABLE_CAP = 10


def _fk_degree(schema_str: str) -> dict[str, int]:
    """Table → number of distinct FK-joinable neighbours, from the same inferred join map
    the catalog and `fk_neighbor_expand` use. Empty on any failure (callers then fall
    back to input order, never to an exception)."""
    try:
        from aughor.tools.schema import compute_join_map, parse_schema_tables
        jmap = compute_join_map(parse_schema_tables(schema_str))
        adj: dict[str, set[str]] = {}
        for j in jmap.get("joins", []):
            adj.setdefault(j["t1"], set()).add(j["t2"])
            adj.setdefault(j["t2"], set()).add(j["t1"])
        return {t: len(nb) for t, nb in adj.items()}
    except Exception:
        logger.debug("FK-degree ranking unavailable", exc_info=True)
        return {}


def rank_tables_for_context(
    question: str,
    schema_str: str,
    tables: list[str],
    *,
    cap: int,
    connection_id: str | None = None,
    pinned: list[str] | None = None,
) -> list[str]:
    """Rank ``tables`` by relevance to ``question`` and keep the top ``cap``.

    The companion to :func:`link_schema`'s recall-safety branch. That branch is right in
    principle — filtering on noise is how a schema ends up empty — but it means the MOST
    open-ended questions get the LEAST filtering: ask "profile the most unusual entities
    in this data" and no table matches a keyword, so all 23 come back byte-identical.
    That was fine when the schema was one domain; on a canvas holding four unrelated
    datasets (airline ops · media reviews · bakery sales · suppliers) "send everything"
    is exactly the wrong answer, and the catalog built from it was 28.5k chars of which
    29% was cookie reviews in an airline-outlier prompt.

    So the recall floor stays where it belongs (the SCHEMA text keeps every table), and
    the bound moves to the expensive artifact: the catalog, which pays 5 sample rows per
    table. Ranking is the linker's own ``_score_table`` — same scores, same hints, same
    connection-derived weights, so a table the linker would have kept ranks first here.
    When NOTHING scores — the case that produced the 2026-08-15 report — keyword order
    would be schema order, i.e. alphabetical luck. The fallback is the schema's own
    structure instead: FK degree, so the connected core of the canvas outranks tables
    that join to nothing. On a canvas of four unrelated datasets that keeps the entity
    tables and drops the free-floating ones, which is what "profile the entities in this
    data" actually means. Order-stable within equal degree, and the log says which basis
    was used, because a silent cap reads as "we covered everything".

    ``pinned`` tables always survive the cut. A date/time dimension is added to the
    context precisely BECAUSE the question never names it, so it scores zero and a
    relevance cut would drop it first — the one table the temporal expansion existed to
    keep.

    🔑 ``cap`` is TIGHTENED to ``_NO_SIGNAL_TABLE_CAP`` when nothing scores. Callers pass
    the profile's ``context_table_cap``, which is 10 on the baseline tier but **24 on a
    capable model** — and a 23-table canvas slips under 24, so on the very model class
    most likely to be pointed at a big canvas this function would have capped nothing.
    The profile number is a budget for RELEVANT tables; with no relevance signal there is
    no evidence any of them belongs, so the conservative baseline applies instead. When
    the ranking IS grounded, the caller's cap is honoured in full."""
    if cap <= 0:
        return tables
    # Under even the tightest bound this could choose — nothing to decide, no scoring.
    if len(tables) <= min(cap, _NO_SIGNAL_TABLE_CAP):
        return tables
    _pin = {t.lower() for t in (pinned or [])}
    try:
        blocks = {b["table"].lower(): b for b in _extract_schema_blocks(schema_str)}
        tokens = _expand_tokens(set(_tokenise(question)) - _STOP_WORDS) - _STOP_WORDS
        conn_table_hints, _cols, synonyms = build_connection_hints(connection_id)
        hints = conn_table_hints or _DEFAULT_TABLE_HINTS
        weight = 2.0 if conn_table_hints else 0.25
        for t in list(tokens):
            tokens |= synonyms.get(t, set())
        scored = [
            (_score_table(blocks[t.lower()], tokens, hints, weight) if t.lower() in blocks else 0.0,
             i, t)
            for i, t in enumerate(tables)
        ]
        ranked = [s for s, _i, t in scored if t.lower() not in _pin]
        basis = "relevance"
        if not ranked or max(ranked) <= 0:
            basis = "FK degree (no keyword matched)"
            degree = _fk_degree(schema_str)
            scored = [(float(degree.get(t, 0)), i, t) for _s, i, t in scored]
            cap = min(cap, _NO_SIGNAL_TABLE_CAP)
            if len(tables) <= cap:
                return tables
        # Pins sort above everything; the ranking below them is unchanged.
        scored.sort(key=lambda x: (0 if x[2].lower() in _pin else 1, -x[0], x[1]))
        kept = [t for _s, _i, t in scored[:cap]]
        dropped = [t for _s, _i, t in scored[cap:]]
        logger.info("[linker] catalog capped to top %d of %d by %s; dropped: %s",
                    cap, len(tables), basis, dropped)
        return kept
    except Exception:
        logger.warning("table ranking failed; capping by input order", exc_info=True)
        return tables[:cap]


def link_schema_for_prompt(
    question: str,
    schema_str: str,
    *,
    top_k_tables: int | None = None,
    top_k_cols: int | None = None,
    connection_id: str | None = None,
) -> str:
    """Wrapper that adds a header note explaining the filter, for LLM prompts.
    Defaults are profile-derived (A3), so the answer path and the grounding
    receipt describe the SAME prompt by construction."""
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
