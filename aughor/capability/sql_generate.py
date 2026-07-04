"""Standalone NL→SQL generation for the Data capability (AL-02).

The answer path's SQL generation (`agent/nodes.py:_gen_sql`) is a closure over ~9 graph-node
locals — not callable standalone. This is the reusable "question + schema → one SELECT" step the
`CapabilityPipeline.generate` phase needs, built on the SAME `WRITE_SQL_PROMPT` + `coder` provider
(a shared prompt, not a fork). Fail-open: returns "" on any error, so the template treats a failed
generate as an empty artifact rather than crashing. Migrating the ADA graph's per-intent generation
onto this shared function is the remaining (larger) AL-02 step.
"""
from __future__ import annotations

from typing import Any, Optional


def generate_sql(question: str, schema_text: str = "", dialect: str = "duckdb", *,
                 intent_description: Optional[str] = None,
                 intent_tables: str = "(any relevant table in the schema)",
                 intent_filters: str = "none",
                 intent_aggregation: str = "none",
                 pitfall_section: str = "",
                 sql_examples_section: str = "",
                 ontology_actions_section: str = "",
                 provider: Optional[Any] = None) -> str:
    """Translate `question` (the hypothesis / NL ask) into one SQL SELECT against `schema_text`.

    The single `WRITE_SQL_PROMPT` call site: the capability's `generate` phase uses the plain
    (question-only) form; the deep answer path (`nodes._gen_sql`) passes its planned intent + the
    pitfall / examples / ontology sections through the keyword params, so both share one prompt.
    `intent_description` defaults to `question`. `provider` is injectable (defaults to the `coder`
    role). Returns "" on any error (the caller treats an empty artifact as a no-op)."""
    q = (question or "").strip()
    if not q:
        return ""
    try:
        from aughor.agent.prompts import WRITE_SQL_PROMPT
        from aughor.agent.state import SQLOutput
        prov = provider
        if prov is None:
            from aughor.llm.provider import get_provider
            prov = get_provider("coder")
        out: SQLOutput = prov.complete(
            system="You are a SQL expert. Translate the query intent into one SQL SELECT statement.",
            user=WRITE_SQL_PROMPT.format(
                dialect=dialect,
                hypothesis_description=q,
                intent_description=(intent_description if intent_description is not None else q),
                intent_tables=intent_tables,
                intent_filters=intent_filters,
                intent_aggregation=intent_aggregation,
                schema=schema_text or "",
                pitfall_section=pitfall_section,
                sql_examples_section=sql_examples_section,
                ontology_actions_section=ontology_actions_section,
            ),
            response_model=SQLOutput,
        )
        return (out.sql or "").strip()
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "capability.sql_generate", counter="capability.generate")
        return ""
