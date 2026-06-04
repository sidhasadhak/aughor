"""
Semantic SQL validator — catches cases where the SQL uses the wrong identifier
column for the entity asked about in the question/hypothesis.

Examples of what this catches:
  • Question says "seller-wise profitability" but SQL groups on product_id
  • Question says "customer analysis" but SQL groups on order_id
  • Question says "product revenue" but SQL groups on customer_id

The check is deterministic (no LLM) and runs *after* SQL generation but
*before* execution so the fix can be injected into the FIX_SQL prompt as
diagnosis context if the SQL later fails, or raised as a warning in the trace
even if the query succeeds (letting the semantic inspector flag it).

Usage:
    warnings = check_entity_column_alignment(question, sql, schema_context)
    for w in warnings:
        print(w.message)
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# ── Entity → expected column-name tokens ─────────────────────────────────────
# Each entry: (question_keywords, must_contain_any_col_tokens)
# If the question contains a keyword but the SQL GROUP BY / SELECT uses none of
# the expected tokens, we emit a warning.

_ENTITY_MAP: list[tuple[list[str], list[str]]] = [
    (
        ["seller", "sellers", "seller-wise", "by seller", "per seller",
         "seller level", "seller performance"],
        ["seller_id", "seller"],
    ),
    (
        ["customer", "customers", "customer-wise", "by customer", "per customer",
         "customer level", "customer segment"],
        ["customer_unique_id", "customer_id", "customer"],
    ),
    (
        ["product", "products", "product-wise", "by product", "per product",
         "sku", "item"],
        ["product_id", "sku_id", "sku", "product"],
    ),
    (
        ["order", "orders", "order-level", "by order", "per order"],
        ["order_id", "order"],
    ),
    (
        ["category", "categories", "by category", "per category",
         "product category", "product_category"],
        ["category", "product_category", "category_name"],
    ),
    (
        ["channel", "channels", "by channel", "per channel", "acquisition channel"],
        ["channel", "source", "medium", "utm_source"],
    ),
    (
        ["region", "regions", "by region", "geography", "country",
         "by country", "per country"],
        ["region", "country", "geography", "state", "city"],
    ),
]

# Regex to extract GROUP BY token list (handles multi-column group bys)
_GROUP_BY_RE = re.compile(
    r'\bGROUP\s+BY\b(.*?)(?=\bHAVING\b|\bORDER\b|\bLIMIT\b|\bUNION\b|$)',
    re.IGNORECASE | re.DOTALL,
)
_PARTITION_BY_RE = re.compile(
    r'\bPARTITION\s+BY\b(.*?)(?=\bORDER\b|\bROWS\b|\bRANGE\b|\))',
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class SemanticColumnWarning:
    entity: str          # e.g. "seller"
    expected: list[str]  # e.g. ["seller_id", "seller"]
    found_in_sql: list[str]  # columns actually found in GROUP BY / PARTITION BY
    message: str

    def to_prompt_text(self) -> str:
        return self.message


def _extract_groupby_tokens(sql: str) -> list[str]:
    """Return all identifier tokens from GROUP BY and PARTITION BY clauses."""
    tokens: list[str] = []
    for pattern in (_GROUP_BY_RE, _PARTITION_BY_RE):
        for m in pattern.finditer(sql):
            clause = m.group(1)
            for tok in re.finditer(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', clause):
                tokens.append(tok.group(1).lower())
    return tokens


def _extract_select_aliases(sql: str) -> list[str]:
    """Return identifiers used with AS aliases in SELECT (catches col AS seller_id patterns)."""
    aliases: list[str] = []
    for m in re.finditer(r'\bAS\s+([a-zA-Z_][a-zA-Z0-9_]*)\b', sql, re.IGNORECASE):
        aliases.append(m.group(1).lower())
    return aliases


def check_entity_column_alignment(
    question: str,
    sql: str,
    schema_context: str = "",
) -> list[SemanticColumnWarning]:
    """
    Check that SQL GROUP BY columns semantically match the entity noun in the question.

    Returns a (possibly empty) list of SemanticColumnWarning objects.
    Never raises — best-effort, designed to run on every generated SQL.
    """
    try:
        question_lower = question.lower()
        sql_lower = sql.lower()

        groupby_tokens = _extract_groupby_tokens(sql)
        select_aliases = _extract_select_aliases(sql)
        all_sql_tokens = set(groupby_tokens + select_aliases)

        # Also extract what columns appear directly referenced in FROM/JOIN scope
        # (catch cases like oi.product_id AS seller_id)
        raw_col_refs: list[str] = []
        for m in re.finditer(r'(?:\w+\.)?([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s+\w+', sql, re.IGNORECASE):
            raw_col_refs.append(m.group(1).lower())
        for m in re.finditer(r'\.([a-zA-Z_][a-zA-Z0-9_]*)', sql):
            raw_col_refs.append(m.group(1).lower())

        warnings: list[SemanticColumnWarning] = []

        for question_kws, expected_cols in _ENTITY_MAP:
            # Does the question mention this entity?
            if not any(kw in question_lower for kw in question_kws):
                continue

            entity_name = question_kws[0]

            # ── Step 1: check for alias-from-wrong-source (highest priority)
            # e.g. oi.product_id AS seller_id — alias looks right but source is wrong.
            wrong_source_pairs: list[str] = []
            for m in re.finditer(
                r'([a-zA-Z_][a-zA-Z0-9_.]*)\s+AS\s+([a-zA-Z_][a-zA-Z0-9_]*)',
                sql, re.IGNORECASE
            ):
                source = m.group(1).lower()
                alias = m.group(2).lower()
                alias_matches_entity = any(exp in alias for exp in expected_cols)
                # Source column (after the last dot, e.g. "product_id" from "oi.product_id")
                source_col = source.split(".")[-1]
                source_wrong = not any(exp in source_col for exp in expected_cols)
                if alias_matches_entity and source_wrong:
                    wrong_source_pairs.append(
                        f"'{source}' aliased as '{alias}' — the alias looks correct but "
                        f"the source column '{source_col}' is not a {entity_name} identifier"
                    )

            if wrong_source_pairs:
                msg = (
                    f"SEMANTIC MISMATCH: the question asks for {entity_name}-level analysis "
                    f"but the SQL uses the wrong source column. "
                    + "; ".join(wrong_source_pairs)
                    + f". Expected columns: {', '.join(expected_cols)}."
                )
                warnings.append(SemanticColumnWarning(
                    entity=entity_name,
                    expected=expected_cols,
                    found_in_sql=list(all_sql_tokens),
                    message=msg,
                ))
                continue

            # ── Step 2: check GROUP BY tokens only (not aliases, which may look right
            # but could mask the wrong source — handled above)
            groupby_matched = [
                col for col in groupby_tokens
                if any(exp in col or col in exp for exp in expected_cols)
            ]
            if groupby_matched:
                continue  # correct entity columns in GROUP BY — clean

            # ── Step 3: no entity columns in GROUP BY at all → warn
            msg = (
                f"SEMANTIC MISMATCH: the question asks for {entity_name}-level analysis "
                f"but none of the expected {entity_name} identifier columns "
                f"({', '.join(expected_cols)}) appear in GROUP BY or PARTITION BY. "
                f"GROUP BY tokens found: {', '.join(groupby_tokens[:8]) or 'none detected'}. "
                f"Verify the correct {entity_name} identifier column from the schema."
            )
            warnings.append(SemanticColumnWarning(
                entity=entity_name,
                expected=expected_cols,
                found_in_sql=list(all_sql_tokens),
                message=msg,
            ))

        return warnings

    except Exception:
        return []  # validator must never block the pipeline
