"""Measured agents — evaluate a user-agent against ITS OWN golden questions.

The differentiator over Gem/custom-GPT builders (study Part B Phase 3): an
agent's quality is measured, not vibes. Each golden = {question, reference_sql}
(ground truth authored by the agent's creator). An evaluation:

1. activates the agent (brief + document scope + connection binding — the same
   contextvar the live answer path uses),
2. generates SQL for each golden question with the CURRENT coder model through
   the product chat prompt,
3. executes both the generated and the reference SQL on the agent's connection,
4. compares result sets DETERMINISTICALLY (no LLM judges), and
5. stamps {passed, total, at, per_question} onto the agent (the pass chip) —
   and logs a span per evaluation when `obs.mlflow` tracing is active.

Failure posture: a generation/execution error fails THAT golden, never the run.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from aughor.user_agents.context import activate_agent, release_agent
from aughor.user_agents.models import UserAgent
from aughor.user_agents.store import list_goldens, record_eval

logger = logging.getLogger(__name__)

MAX_GOLDENS_PER_EVAL = 20  # sync endpoint budget: one LLM call per golden
_COMPARE_ROWS = 50         # compare at most the first N rows (stable sort applied)


# ── Deterministic result comparison ───────────────────────────────────────────

def _normalize(rows: list, limit: int = _COMPARE_ROWS) -> list[tuple]:
    """Order-insensitive, type-tolerant view of a result set: every cell to a
    canonical string (floats rounded to 6 places), rows sorted."""
    def cell(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return str(v)
        if isinstance(v, (int, float)):
            return f"{float(v):.6f}".rstrip("0").rstrip(".")
        return str(v).strip()

    normed = sorted(tuple(cell(c) for c in row) for row in rows)
    return normed[:limit]


def results_match(ref_rows: list, gen_rows: list) -> bool:
    """The golden passes when the generated result carries the reference result:
    identical normalized sets, or (single-column references) the reference's
    values all present per-row in the generated rows (extra columns are fine —
    a richer correct answer must not fail the suite)."""
    ref_n, gen_n = _normalize(ref_rows), _normalize(gen_rows)
    if ref_n == gen_n:
        return True
    if not ref_rows or not gen_rows or len(ref_rows) != len(gen_rows):
        return False
    # Column-superset tolerance: each reference row's cells ⊆ some generated row.
    gen_sets = [set(r) for r in gen_n]
    used: set[int] = set()
    for ref_row in ref_n:
        hit = next((i for i, g in enumerate(gen_sets)
                    if i not in used and set(ref_row) <= g), None)
        if hit is None:
            return False
        used.add(hit)
    return True


# ── Generation (the product chat prompt, minimal sections) ───────────────────

def _generate_sql(question: str, schema: str) -> str:
    """SQL for a golden question with the CURRENT coder model. The active agent's
    brief leads the prompt exactly like the live quick path."""
    from pydantic import BaseModel, Field

    from aughor.agent.prompts import CHAT_PROMPT, CHAT_SQL_SYSTEM
    from aughor.llm.provider import get_provider
    from aughor.user_agents.context import agent_brief_block

    class _Answer(BaseModel):
        sql: str = ""
        headline: str = ""
        chart_type: str = "auto"
        intent: str = ""
        approach: list[str] = Field(default_factory=list)

    prompt = CHAT_PROMPT.format(
        schema=schema, history_section="", question=question, schema_qualifier="",
        kb_patterns_section="", conn_kb_section="", sql_examples_section="",
        metrics_section="", exploration_section="", causal_section="",
        document_section="",
    )
    brief = agent_brief_block()
    if brief:
        prompt = brief + prompt
    answer: _Answer = get_provider("coder").complete(
        system=CHAT_SQL_SYSTEM, user=prompt, response_model=_Answer, temperature=0.0)
    return (answer.sql or "").strip()


# ── The evaluation ────────────────────────────────────────────────────────────

def evaluate_agent(agent: UserAgent, db=None,
                   generate: Optional[Callable[[str, str], str]] = None) -> dict:
    """Run the agent's golden suite; stamp + return the result.

    ``db``/``generate`` are injectable for tests; by default the agent's bound
    connection (or the builtin) is opened and the coder model generates."""
    goldens = list_goldens(agent.id)[:MAX_GOLDENS_PER_EVAL]
    started = time.monotonic()
    result: dict = {"passed": 0, "total": len(goldens), "per_question": [],
                    "at": datetime.now(timezone.utc).isoformat()}
    if not goldens:
        record_eval(agent.id, result)
        return result

    if db is None:
        from aughor.db.connection import open_connection_for
        from aughor.db.registry import BUILTIN_ID
        db = open_connection_for(agent.connection_id or BUILTIN_ID)
    gen = generate or _generate_sql
    schema = ""
    try:
        schema = db.get_schema()
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "schema introspection for agent eval is best-effort",
                 counter="agents.eval_schema")

    token = activate_agent(agent)
    try:
        for g in goldens:
            entry = {"golden_id": g["id"], "question": g["question"], "passed": False,
                     "error": ""}
            try:
                ref = db.execute("__agent_eval_ref__", g["reference_sql"])
                if ref.error:
                    entry["error"] = f"reference failed: {ref.error}"
                    result["per_question"].append(entry)
                    continue
                sql = gen(g["question"], schema)
                if not sql:
                    entry["error"] = "no SQL generated"
                    result["per_question"].append(entry)
                    continue
                got = db.execute("__agent_eval_gen__", sql)
                if got.error:
                    entry["error"] = f"generated SQL failed: {got.error}"
                else:
                    entry["passed"] = results_match(ref.rows, got.rows)
                    if not entry["passed"]:
                        entry["error"] = "result mismatch vs reference"
            except Exception as exc:  # one golden's failure never aborts the suite
                entry["error"] = f"{type(exc).__name__}: {exc}"
            result["per_question"].append(entry)
            if entry["passed"]:
                result["passed"] += 1
    finally:
        release_agent(token)

    result["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
    record_eval(agent.id, result)
    # obs.mlflow — the evaluation as a TOOL span when a trace is active (advisory).
    try:
        from aughor.telemetry import mlflow_tool_span
        with mlflow_tool_span("agent.evaluate",
                              {"agent_id": agent.id, "passed": result["passed"],
                               "total": result["total"]}):
            pass
    except Exception as exc:
        logger.debug("agent-eval telemetry best-effort: %s", exc)
    return result
