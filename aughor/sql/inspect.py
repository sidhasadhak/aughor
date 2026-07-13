"""Semantic SQL inspector — the "Inspect" step (Databricks Genie equivalent).

After SQL executes successfully, this module runs a lightweight second LLM call
that checks whether the SQL *logically* answers the question.  Syntactic lint
(`lint.py`) catches anti-patterns before execution; Inspect catches semantic
mismatches that only make sense once you see the question + query together.

Examples of what it catches:
  • "Top 10 customers" → query returns products (wrong table)
  • "For a single month" → query still groups by month (temporal filter missing)
  • "Freight-to-price ratio" → denominator is freight not price (columns swapped)
  • "Active customers" → no status filter on the customers table

Design
------
• Uses the "narrator" provider (fast/cheap model) — NOT the coder.
• Non-blocking: failures here never prevent the user from seeing results.
• Returns InspectResult with valid=True when everything looks fine.
• When valid=False, the caller streams an `inspect_warning` SSE event to the
  frontend so the user knows the result may be questionable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from aughor.llm.provider import get_provider


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class InspectResult:
    valid: bool
    issues: list[str] = field(default_factory=list)
    suggested_fix: str = ""     # plain-English hint for the rewrite step


# ── Pydantic model for structured LLM output ─────────────────────────────────

class _InspectAnswer(BaseModel):
    valid: bool = True
    issues: list[str] = []
    suggested_fix: str = ""


_INSPECT_SYSTEM = (
    "You are a senior data analyst reviewing whether a SQL query correctly answers a business question. "
    "Be precise and concise. Only flag genuine logical problems — do NOT nitpick style or formatting. "
    "If the SQL is correct, say so by returning valid=true with an empty issues list."
)

_INSPECT_PROMPT = """\
QUESTION:
{question}

SQL WRITTEN TO ANSWER IT:
{sql}
{schema_block}
FIRST FEW RESULT COLUMNS AND ROWS (sample):
{result_sample}

Review whether the SQL actually answers the question. Check:
1. Are the right tables used (e.g. did "customers" question end up querying products)?
2. Are all stated filters applied (e.g. "for a single month" → is there a WHERE date filter)?
3. Is the aggregation correct (e.g. "ratio" → SUM/SUM not AVG)?
4. Are column semantics correct (numerator / denominator not swapped)?
5. Does the result shape match the question (e.g. "by state" → state column present)?
{grain_rule}
CRITICAL: when the schema is given above, any column you name in suggested_fix MUST appear
in it verbatim — never invent a plausible-sounding column (e.g. do not say "use fiscal_month"
unless a fiscal_month column is actually listed). If the needed column is absent, say so.

Return:
- valid: true if no significant issues
- issues: list of specific problems found (empty if valid)
- suggested_fix: one sentence describing what to change (empty if valid)
"""

_GRAIN_RULE = ("6. Do NOT flag time-GRAIN mismatches (monthly vs yearly etc.) — a separate "
               "deterministic gate owns that; focus on the checks above.\n")


# ── Inspector ─────────────────────────────────────────────────────────────────

def inspect(
    question: str,
    sql: str,
    columns: list[str],
    rows: list[list],
    max_rows: int = 5,
    schema: str = "",
    skip_grain: bool = False,
) -> InspectResult:
    """Run semantic inspection.  Never raises — returns valid=True on any error.

    ``schema`` (the rendered schema slice) grounds the inspector so it stops
    inventing columns in ``suggested_fix``. ``skip_grain`` tells it to leave
    time-grain mismatches to the deterministic grain-feasibility gate (which owns
    that verdict), so the two don't emit contradictory advice."""
    try:
        sample_rows = rows[:max_rows]
        if columns and sample_rows:
            header = " | ".join(columns[:8])
            lines  = [header, "-" * len(header)]
            for row in sample_rows:
                lines.append(" | ".join(str(v)[:30] for v in row[:8]))
            result_sample = "\n".join(lines)
        else:
            result_sample = "(no rows)"

        schema_block = f"\nSCHEMA (the only columns that exist):\n{schema}\n" if schema else ""
        prompt = _INSPECT_PROMPT.format(
            question=question,
            sql=sql,
            schema_block=schema_block,
            grain_rule=_GRAIN_RULE if skip_grain else "",
            result_sample=result_sample,
        )

        answer: _InspectAnswer = get_provider("narrator").complete(
            system=_INSPECT_SYSTEM,
            user=prompt,
            response_model=_InspectAnswer,
        )

        return InspectResult(
            valid=answer.valid,
            issues=answer.issues or [],
            suggested_fix=answer.suggested_fix or "",
        )
    except Exception:
        return InspectResult(valid=True)   # non-blocking — assume OK on failure
