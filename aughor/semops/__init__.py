"""Semantic operators over SQL — LLM filter / extract / top-k / aggregate over the *text* columns
of a SQL result set, after the warehouse has done the structured push-down. See ``operators.py``."""
from __future__ import annotations

from aughor.semops.ai_sql import (
    AIColumnReceipt,
    ai_embed,
    ai_prompt,
    emit_ai_receipt,
    register_embedding_udf,
    register_prompt_udf,
)
from aughor.semops.operators import (
    SemanticOpResult,
    apply_step,
    detect_text_columns,
    semantic_aggregate,
    semantic_extract,
    semantic_filter,
    semantic_top_k,
)

__all__ = [
    "SemanticOpResult",
    "apply_step",
    "detect_text_columns",
    "semantic_aggregate",
    "semantic_extract",
    "semantic_filter",
    "semantic_top_k",
    # R8 — AI as a governed SQL operator
    "AIColumnReceipt",
    "ai_embed",
    "ai_prompt",
    "emit_ai_receipt",
    "register_embedding_udf",
    "register_prompt_udf",
]
