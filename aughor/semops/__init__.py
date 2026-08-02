"""Semantic operators over SQL — LLM filter / extract / top-k / aggregate over the *text* columns
of a SQL result set, after the warehouse has done the structured push-down. See ``operators.py``."""
from __future__ import annotations

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
]
