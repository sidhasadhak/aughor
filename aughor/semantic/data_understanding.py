"""Shared data-understanding context — the per-question grounding every answer mode should build ONCE.

Insight and Deep each assembled a DIFFERENT subset of the same understanding (metric grounding, measure
grain, trusted-query patterns, date coverage), which is precisely how Insight ended up blind to a date
column Deep understood. ``build_data_understanding`` bundles those pieces behind one builder and one
``grounding_block()`` renderer, so a mode can never silently miss a piece — and so the assembly logic
lives in one place instead of drifting across three call sites.

Every piece is no-op safe: a missing helper, an empty trusted library, or an unclassifiable schema each
yield "" for that section, never an exception. See docs/MODE_ARCHITECTURE_AND_CROSS_POLLINATION.md (R4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DataUnderstanding:
    """The per-question understanding, each section independently optional."""
    grain_block: str = ""        # measure grains (per-unit/per-line/per-order) — prevent SUM-at-wrong-grain
    trusted_block: str = ""      # verified KNOWN-CORRECT query patterns for this connection
    metric_block: str = ""       # canonical metric formulas resolved for the question

    def grounding_block(self) -> str:
        """The combined grounding text to append to a generator's system prompt (sections that are
        present, joined by blank lines). Empty string when nothing was classified."""
        return "\n\n".join(b for b in (self.metric_block, self.grain_block, self.trusted_block) if b)

    def __bool__(self) -> bool:
        return bool(self.metric_block or self.grain_block or self.trusted_block)


def build_data_understanding(
    conn,
    *,
    connection_id: str = "",
    schema: Optional[str] = None,
    question: str = "",
    include_metric: bool = False,
) -> DataUnderstanding:
    """Assemble the shared per-question understanding from a connection + schema (+ question for the
    trusted-query match). ``include_metric`` resolves the canonical metric block too (off by default —
    the ADA phase planner already carries metric_sql from intake; Insight wants it on).

    Resolves the connection id from the explicit arg or the connection object. No-op safe throughout."""
    du = DataUnderstanding()
    cid = connection_id or getattr(conn, "connection_id", "") or getattr(conn, "_connection_id", "") or ""

    if schema:
        try:
            from aughor.semantic.measure_grain import measure_grains_block
            du.grain_block = measure_grains_block(cid, conn, schema_text=schema) or ""
        except Exception:
            pass

    if question and cid:
        try:
            from aughor.semantic.trusted_queries import retrieve_trusted, build_trusted_block
            du.trusted_block = build_trusted_block(retrieve_trusted(question, cid)) or ""
        except Exception:
            pass

    if include_metric and cid:
        try:
            from aughor.semantic.canonical import unified_metric_grounding
            du.metric_block = unified_metric_grounding(cid, None, schema_text=schema) or ""
        except Exception:
            pass

    return du
