"""
Explore mode node functions — sequential investigative chunking.

Graph branch (entered when route_question returns mode="explore"):

  decompose_exploration
      ↓
  plan_and_execute_subq  ←──────────────┐
      ↓                                  │
  reason_over_result                     │  (loop)
      ↓                                  │
  route_after_reason ── [more Qs] ───────┘
      ↓ [all done / max iter]
  synthesize_exploration
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)

from aughor.agent.prompts_explore import (
    BUILD_LEDGER_PROMPT,
    DECOMPOSE_EXPLORATION_PROMPT,
    PLAN_SUBQ_PROMPT,
    REASON_OVER_RESULT_PROMPT,
    REFUTE_FINDING_PROMPT,
    SYNTHESIZE_EXPLORATION_PROMPT,
)
from aughor.agent.prompts import format_pitfall_section
from aughor.agent.state import (
    AgentState,
    DataQualityNote,
    ExplorationReport,
    Pitfall,
    QueryPlan,
    QueryResult,
    ReasoningOutput,
    SubQuestion,
    SubQuestionAnswer,
    VerificationCheck,
    VerificationManifest,
)
from aughor.llm.provider import get_provider
from aughor.tools.executor import format_result_for_llm
from aughor.tools.stats import analyze_query_result

from pydantic import BaseModel, Field
from typing import Literal, Optional

MAX_SUBQ = int(__import__("os").getenv("AUGHOR_MAX_SUBQ", "8"))


# ── Pydantic schema for decompose output ─────────────────────────────────────

class _ExplorationPlan(BaseModel):
    question_understanding: str
    constraints: list[str] = Field(default_factory=list)
    sub_questions: list[SubQuestion]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_prior_answers(answers: list[SubQuestionAnswer]) -> str:
    if not answers:
        return "None yet — this is the first sub-question."
    parts = []
    for a in answers:
        lines = [
            f"[{a.subq_id}] {a.question}",
            f"  Answer:  {a.answer}",
            f"  Insight: {a.insight}",
        ]
        if a.refinement:
            lines.append(f"  Refinement for downstream: {a.refinement}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _format_chain_summary(answers: list[SubQuestionAnswer]) -> str:
    parts = []
    for a in answers:
        result_snippet = ""
        if a.columns and a.rows:
            header = " | ".join(a.columns)
            rows = "\n".join("  " + " | ".join(str(v) for v in row) for row in a.rows[:8])
            result_snippet = f"\n  Data:\n  {header}\n{rows}"
            if a.row_count > 8:
                result_snippet += f"\n  … ({a.row_count - 8} more rows)"
        parts.append(
            f"[{a.subq_id}] {a.question} ({a.purpose})\n"
            f"  SQL: {a.sql}\n"
            f"  Answer: {a.answer}\n"
            f"  Insight: {a.insight}"
            + result_snippet
        )
    return "\n\n".join(parts)


def _attach_stats(result: QueryResult) -> QueryResult:
    try:
        # NOTE: analyze_query_result takes (columns, rows, sql) — passing the bare
        # QueryResult silently raised TypeError and the except swallowed it, so the
        # whole stats-injection feature was dead in the explore path until this fix.
        # analyze_query_result returns tools.stats.StatResult (dataclass); QueryResult.stats
        # is the pydantic state.StatResult — bridge via asdict so pydantic validates.
        from dataclasses import asdict
        stats = analyze_query_result(result.columns, result.rows, result.sql)
        return QueryResult(**{**result.model_dump(), "stats": [asdict(s) for s in stats]})
    except Exception:
        return result


# ── Analysis ledger — canonical definitions shared by every stage ─────────────

class _LedgerOut(BaseModel):
    ledger: str = Field(
        description="Short binding list of canonical entity identifiers, metric "
                    "SQL expressions, and segment definitions for this analysis."
    )


def build_analysis_ledger(state: AgentState) -> str:
    """Decide canonical entity/metric definitions ONCE so every downstream step
    uses the same identifiers and expressions (prevents figures drifting between
    stages, e.g. customer_id vs customer_unique_id). Best-effort — never blocks."""
    scan_context = state.get("scan_context") or ""
    scan_section = (
        f"DATA PORTRAIT (actual distributions):\n{scan_context}\n" if scan_context else ""
    )
    try:
        out: _LedgerOut = get_provider("coder").complete(
            system="You define canonical metric/entity definitions for a data analysis.",
            user=BUILD_LEDGER_PROMPT.format(
                question=state["question"],
                schema=state["schema_context"],
                scan_section=scan_section,
            ),
            response_model=_LedgerOut,
        )
        return (out.ledger or "").strip()
    except Exception:
        return ""


# ── Node: decompose_exploration ───────────────────────────────────────────────

def decompose_exploration(state: AgentState) -> dict[str, Any]:
    """Break the question into an ordered chain of sub-questions."""
    scan_context = state.get("scan_context") or ""
    scan_section = (
        f"DATA PORTRAIT (actual distributions — use these ranges in your SQL planning):\n{scan_context}\n"
        if scan_context else ""
    )

    # Specialist-pack steering (Bet 3/Bet 1 intake hook) — flag-gated, off by default so a
    # normal run is byte-identical. If an active pack owns this question AND grounds on the
    # connection, prepend its persona + grounded recipes + diagnostics to the planner context.
    steered_by = None
    try:
        # An explicit pre-rendered block (e.g. from the pack eval harness) forces steering for
        # this run, bypassing the flag/active/select path; otherwise use the live gated path.
        _pre = state.get("_pack_injection_block")
        if _pre:
            scan_section = _pre + scan_section
            steered_by = state.get("_pack_id")
            logger.info("[explore] specialist pack '%s' steering (forced) this run", steered_by)
        else:
            from aughor.packs.intake import injection_for_question, render_injection
            _inj = injection_for_question(state.get("question", ""), state.get("connection_id", ""),
                                          state.get("scope_schema", "") or "")
            if _inj is not None:
                scan_section = render_injection(_inj) + scan_section
                steered_by = _inj.pack_id
                logger.info("[explore] specialist pack '%s' is steering this run", _inj.pack_id)
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "specialist-pack intake best-effort; run proceeds ungrounded",
                 counter="packs.intake")

    # Pin canonical definitions for the whole run before planning any sub-questions.
    analysis_ledger = build_analysis_ledger(state)

    # Extract explicit user constraints from the question (re-use decompose pattern)
    constraint_section = "No explicit constraints detected."

    # Resilience: the planner is the single point where an exploration most often
    # dies (LLM/provider hiccup or an assertion-style prompt that yields no chain).
    # Retry once with a corrective nudge, then fall back to a deterministic floor
    # chain so the investigation ALWAYS proceeds to real queries + synthesis.
    sub_questions = _plan_exploration_chain(state, scan_section, constraint_section)
    if not sub_questions:
        sub_questions = _floor_chain(state)

    # Pre-flight prune: if the data spans a single period, drop seasonality/temporal
    # sub-questions before they cost a planning slot + a query (the Swiss-Air case that
    # "discovered" the data was single-month June only after running the step).
    span = _data_span_months(scan_context)
    sub_questions, dropped = _prune_impossible_subqs(sub_questions, span)
    if dropped:
        logger.info("[explore] pruned %d temporal sub-question(s) — data spans ~%.1f month(s): %s",
                    len(dropped), span or 0.0, "; ".join(s.question[:48] for s in dropped))
    if not sub_questions:
        sub_questions = _floor_chain(state)

    # Reindex to canonical, unique ids BEFORE truncation so the retained chain is a
    # contiguous Q1..Qn with no duplicate keys (planner can emit two 'Q3').
    sub_questions = _canonicalize_subq_ids(sub_questions[:MAX_SUBQ])

    return {
        "sub_questions": sub_questions,
        "current_subq_idx": 0,
        "subq_answers": [],
        "pitfalls": [],
        "iteration": 0,
        "analysis_ledger": analysis_ledger,
        # Liveness: the pre-flight temporal prune ran (record outcome too); plus a marker when
        # a specialist pack steered this run.
        "verification_checks": [f"temporal_prune:{len(dropped)}"]
                               + ([f"specialist:{steered_by}"] if steered_by else []),
    }


def _plan_exploration_chain(state: AgentState, scan_section: str, constraint_section: str) -> list[SubQuestion]:
    """Run the decompose planner with one corrective retry. Never raises —
    returns [] only if the LLM truly can't produce a valid SQL-answerable chain."""
    llm = get_provider("coder")
    base_user = DECOMPOSE_EXPLORATION_PROMPT.format(
        question=state["question"],
        schema=state["schema_context"],
        scan_section=scan_section,
        constraint_section=constraint_section,
    )
    for attempt in range(2):
        user = base_user if attempt == 0 else (
            base_user
            + "\n\nYOUR PREVIOUS ATTEMPT RETURNED NO USABLE SUB-QUESTIONS. You MUST now "
            "return at least 3 concrete, SQL-answerable sub-questions that use ONLY tables "
            "and columns present in the schema above. Begin with a `landscape` question. "
            "If the input is a claim rather than a question, reframe it as a verification "
            "question (e.g. 'Is it true that …?')."
        )
        try:
            plan: _ExplorationPlan = llm.complete(
                system="You are a senior data analyst designing a sequential investigative chain.",
                user=user,
                response_model=_ExplorationPlan,
            )
            sqs = [sq for sq in (plan.sub_questions or []) if (sq.question or "").strip()]
            if sqs:
                return sqs
        except Exception:
            continue  # transient provider/parse error — fall through to retry / floor
    return []


def _floor_chain(state: AgentState) -> list[SubQuestion]:
    """Deterministic safety-net chain (no LLM) so an exploration never starts
    empty even if the planner fails entirely. Anchors on the first schema table
    and the original question, then lets the per-sub-question SQL planner do the
    real work against the live schema."""
    import re as _re
    m = _re.search(r"^(?:TABLE:|##)\s+([^\s\[(]+)", state.get("schema_context", "") or "", _re.MULTILINE)
    table = m.group(1) if m else "the primary table"
    q = (state.get("question") or "the original question").strip()
    return [
        SubQuestion(
            id="Q1", purpose="landscape", depends_on=[],
            question=f"What is the overall volume and the key measurable dimensions in the data most relevant to: {q}?",
            expected_output=f"A small summary of row counts and key aggregates from {table} and directly related tables.",
        ),
        SubQuestion(
            id="Q2", purpose="synthesis", depends_on=["Q1"],
            question=f"Based on the landscape above, what is the most direct, evidence-backed answer to: {q}?",
            expected_output="A focused aggregate (grouped/ranked as needed) that directly addresses the original question.",
        ),
    ]


def _canonicalize_subq_ids(sqs: list[SubQuestion]) -> list[SubQuestion]:
    """Assign canonical, unique, execution-order ids (Q1..Qn) to the planned chain,
    regardless of what the LLM emitted.

    The planner sometimes returns duplicate ids (two 'Q3') or gaps. Downstream state —
    subq_answers, subq_data_portrait, refinement injection, and the frontend stepper key —
    all key off the sub-question id, so a collision silently cross-contaminates two
    distinct questions (answers/portraits overwrite each other) AND crashes the React
    stepper with a duplicate-key error. Reindexing by position guarantees uniqueness.

    depends_on is advisory (execution is sequential by index), so we remap it best-effort
    through the old→new mapping, keeping only backward references that resolve."""
    if not sqs:
        return sqs
    new_ids = [f"Q{i + 1}" for i in range(len(sqs))]
    # An old id may appear more than once; record every replacement so a backward
    # depends_on reference resolves to the most recent earlier occurrence.
    old_to_new: dict[str, list[str]] = {}
    for sq, nid in zip(sqs, new_ids):
        old_to_new.setdefault(sq.id, []).append(nid)

    out: list[SubQuestion] = []
    for i, sq in enumerate(sqs):
        remapped: list[str] = []
        for dep in (sq.depends_on or []):
            earlier = [c for c in old_to_new.get(dep, []) if int(c[1:]) < i + 1]
            if earlier and earlier[-1] not in remapped:
                remapped.append(earlier[-1])
        out.append(SubQuestion(**{**sq.model_dump(), "id": new_ids[i], "depends_on": remapped}))
    return out


# Sub-questions that only make sense with multiple time periods. Pruned pre-flight when
# the data spans a single period — otherwise the planner spends a query to "discover" the
# obvious (the Swiss-Air seasonality step that found the data was single-month June).
_TEMPORAL_KEYWORDS = (
    "season", "seasonal", "quarter", "month-over-month", "monthly trend", "year-over-year",
    "yoy", "over time", "trend over", "by month", "by quarter", "by season", "across month",
    "across quarter", "seasonality", "time series", "per month", "per quarter", "monthly",
    "quarterly", "temporal",
)


def _data_span_months(scan_context: str) -> Optional[float]:
    """Approximate span (in months) of the data's date range, parsed from the DATA
    PORTRAIT text. Returns None when no date range is discoverable (→ don't prune)."""
    try:
        from aughor.agent.investigate import _extract_data_date_range
        lo, hi = _extract_data_date_range(scan_context or "")
        if not lo or not hi:
            return None
        from datetime import date
        span_days = (date.fromisoformat(hi) - date.fromisoformat(lo)).days
        return max(0.0, span_days / 30.44)
    except Exception:
        return None


def _prune_impossible_subqs(
    sub_questions: list[SubQuestion], span_months: Optional[float]
) -> tuple[list[SubQuestion], list[SubQuestion]]:
    """Drop temporal/seasonality sub-questions when the data spans a single period
    (<2 months) — they can only return one group and waste a planning slot + a query.
    landscape/synthesis steps are never pruned. Returns (kept, dropped)."""
    if span_months is None or span_months >= 2.0:
        return sub_questions, []
    kept: list[SubQuestion] = []
    dropped: list[SubQuestion] = []
    for sq in sub_questions:
        text = f"{sq.question} {sq.expected_output}".lower()
        temporal = any(k in text for k in _TEMPORAL_KEYWORDS)
        if temporal and sq.purpose not in ("landscape", "synthesis"):
            dropped.append(sq)
        else:
            kept.append(sq)
    return kept, dropped


def _unique_subq_id(existing: set[str]) -> str:
    """Mint a sub-question id not already in `existing`. Used when a sub-question is
    promoted at runtime (reason_over_result) so an LLM-chosen id can't collide with a
    planned one — a collision would attribute the new step's answer to an existing id."""
    n = len(existing) + 1
    while f"Q{n}" in existing:
        n += 1
    return f"Q{n}"


# ── Node: plan_and_execute_subq ───────────────────────────────────────────────

def _rescope_sql_to_schema(sql: str, allowed: str, conn: "DatabaseConnection") -> str | None:
    """Re-point any table referencing a schema OTHER than `allowed` to `allowed` (same
    table name), so a sub-question planner that copied a sibling-schema table from the
    linked catalog (e.g. netflix.products in a missimi investigation) can't answer from
    the wrong dataset — an explicit qualifier bypasses search_path. Returns rewritten SQL
    only when it actually changed AND still binds (dry_run); else None. Never raises."""
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return None
    dialect = getattr(conn, "dialect", "duckdb")
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if tree is None:
        return None
    allow = (allowed or "").strip().lower()
    if not allow:
        return None
    _SYS = {"information_schema", "pg_catalog", "system", ""}
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    changed = False
    for t in tree.find_all(exp.Table):
        sch = (t.db or "").strip().lower()
        if sch and sch != allow and sch not in _SYS and t.name.lower() not in cte_names:
            t.set("db", exp.to_identifier(allowed))
            changed = True
    if not changed:
        return None
    try:
        out = tree.sql(dialect=dialect)
        ok, _ = conn.dry_run(out)
    except Exception:
        return None
    return out if ok else None


def plan_and_execute_subq(state: AgentState, conn: "DatabaseConnection") -> dict[str, Any]:
    """Plan SQL for the current sub-question, execute it, accumulate results."""
    sub_questions = state.get("sub_questions", [])
    idx = state.get("current_subq_idx", 0)
    prior_answers = state.get("subq_answers", [])

    if idx >= len(sub_questions):
        return {}

    subq = sub_questions[idx]
    known_pitfalls = state.get("pitfalls", [])

    raw_events = state.get("events_context") or ""
    events_section = f"{raw_events}\n" if raw_events else ""

    # Per-sub-question schema context: prefer structured Data Catalog if available,
    # else fall back to linked schema text.
    subq_schema = state.get("data_catalog") or state["schema_context"]
    if not subq_schema:
        subq_schema = state["schema_context"]
    try:
        from aughor.tools.schema_linker import link_schema
        linked = link_schema(
            subq.question, subq_schema, top_k_tables=4, top_k_cols=8,
            connection_id=state.get("connection_id"),
        )
        if linked:
            subq_schema = linked
    except Exception:
        logger.warning("schema-linking failed for sub-question; using unlinked schema", exc_info=True)

    llm = get_provider("coder")
    # Resilience: a single sub-question's planner hiccup (provider timeout, parse
    # error, oversized context) must NOT abort the whole chain. If the LLM raises,
    # fall back to a deterministic landscape query so this step still produces
    # evidence and the chain advances to the next sub-question.
    plan: Optional[QueryPlan] = None
    try:
        plan = llm.complete(
            system="You are a senior data analyst writing SQL for an investigative sub-question.",
            user=PLAN_SUBQ_PROMPT.format(
                question=state["question"],
                subq_id=subq.id,
                purpose=subq.purpose,
                subq_question=subq.question,
                expected_output=subq.expected_output,
                prior_answers=_format_prior_answers(prior_answers),
                analysis_ledger=state.get("analysis_ledger") or "(none)",
                schema=subq_schema,
                pitfall_section=format_pitfall_section(known_pitfalls),
                events_section=events_section,
                data_portrait=state.get("subq_data_portrait", {}).get(subq.id, ""),
            ),
            response_model=QueryPlan,
        )
    except Exception:
        plan = None

    # Guard: ensure at least one query (covers planner failure AND empty plans)
    queries = [q for q in (plan.queries if plan else []) if q and q.strip()]
    if not queries:
        import re as _re
        _tm = _re.search(r"^(?:TABLE:|##)\s+([\w.]+)", state["schema_context"], _re.MULTILINE)
        fallback_table = _tm.group(1) if _tm else "unknown"
        queries = [f'SELECT COUNT(*) AS row_count FROM "{fallback_table}"']

    results: list[QueryResult] = []
    new_pitfalls: list[Pitfall] = []
    ran_checks: list[str] = []          # liveness: guards that actually executed (Bet 0)
    allowed_schema = (state.get("scope_schema") or "").strip()

    for sql in queries[:2]:  # explore mode: cap at 2 queries per sub-question
        # Schema-escape guard: a scoped investigation must never answer from a sibling
        # schema. The deep linker's full-schema FK expansion can surface e.g.
        # netflix.products into a missimi sub-question, and an explicit qualifier bypasses
        # the pinned search_path. Re-point any out-of-scope table to the canvas schema; if
        # that can't bind (the table truly isn't in scope), DROP this query rather than leak.
        if allowed_schema:
            try:
                from aughor.sql.tables import extract_tables
                _allow = allowed_schema.lower()
                _oos = sorted({
                    r.schema.strip().lower()
                    for r in extract_tables(sql, getattr(conn, "dialect", "duckdb"))
                    if r.schema and r.schema.strip().lower()
                    not in (_allow, "information_schema", "pg_catalog", "system")
                })
                if _oos:
                    _fixed = _rescope_sql_to_schema(sql, allowed_schema, conn)
                    if _fixed:
                        logger.info("[explore] rescoped cross-schema refs %s -> %s", _oos, allowed_schema)
                        sql = _fixed
                    else:
                        logger.info("[explore] dropping sub-query %s — escapes schema %s (refs %s)",
                                    subq.id, allowed_schema, _oos)
                        continue
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "explore schema-escape guard best-effort; query proceeds",
                         counter="explore.scope_guard")
        result = conn.execute(subq.id, sql)

        # Attach predictions
        _d = result.model_dump()
        _d["expected_if_true"] = (plan.expected_if_true if plan else None) or None
        _d["expected_if_false"] = (plan.expected_if_false if plan else None) or None
        result = QueryResult(**_d)

        # Value-domain guards: a join on value-disjoint keys OR a WHERE/HAVING literal
        # absent from its column's domain (`status = 'cancelled'` when the data holds
        # 'canceled', or `!= 'cancelled'` which then EXCLUDES nothing) produces an
        # unreliable result without ever erroring. Detect both (fail-open) to drive the
        # regenerate branch below. Filter warnings are folded into domain_warnings so the
        # identical regenerate-and-reverify path handles them too.
        domain_warnings = []
        if "join_value_domain" not in ran_checks:
            ran_checks.append("join_value_domain")   # liveness: the value-domain probe ran
        try:
            from aughor.sql.join_guard import check_join_value_domains
            domain_warnings = check_join_value_domains(conn, sql)
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "explore join-guard probe best-effort; query proceeds",
                     counter="join_guard.explore_probe")
        try:
            from aughor.sql.join_guard import check_filter_value_domains
            domain_warnings = domain_warnings + check_filter_value_domains(conn, sql)
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "explore filter-guard probe best-effort; query proceeds",
                     counter="filter_guard.explore_probe")

        if result.error:
            from aughor.agent.state import SQLFix
            from aughor.agent.prompts import FIX_SQL_PROMPT
            from aughor.semantic.kb_retriever import retrieve_for_fix_sql
            from aughor.tools.error_classifier import classify_sql_error, classify_error_type, error_class_guidance

            original_error = result.error
            kb_fix_patterns = retrieve_for_fix_sql(original_error, sql)
            diagnosis = classify_sql_error(original_error, sql, conn.dialect)
            _g = error_class_guidance(classify_error_type(original_error, sql, conn.dialect))  # R3: route by type
            if _g:
                diagnosis = f"ERROR CLASS — {_g}\n{diagnosis}".strip()
            if domain_warnings:
                _dw = "\n".join(w.to_prompt_text() for w in domain_warnings)
                diagnosis = f"{diagnosis}\n{_dw}".strip()
            error_diagnosis_block = f"DIAGNOSIS:\n{diagnosis}\n" if diagnosis else ""

            fix: SQLFix = get_provider("coder").complete(
                system="You are a SQL expert. Fix the broken query.",
                user=FIX_SQL_PROMPT.format(
                    dialect=conn.dialect,
                    sql=sql,
                    error=original_error,
                    error_diagnosis=error_diagnosis_block,
                    schema=state["schema_context"],
                    kb_patterns_section=kb_fix_patterns,
                    metrics_section="",
                ),
                response_model=SQLFix,
            )
            retry = conn.execute(subq.id, fix.fixed_sql)
            new_pitfalls.append(Pitfall(
                original_sql=sql,
                error=original_error,
                fixed_sql=fix.fixed_sql,
                fix_explanation=fix.fix_explanation,
                data_quality_issue=fix.data_quality_issue,
                retry_error=retry.error or None,
            ))
            results.append(_attach_stats(retry))
        elif domain_warnings:
            # Query executed cleanly but joins on value-disjoint keys → the result
            # is unreliable. Regenerate ONCE with the mismatch as the diagnosis;
            # adopt the rewrite only if it executes AND clears the mismatch (never
            # replace a query with one that still has a disjoint join).
            from aughor.agent.state import SQLFix
            from aughor.agent.prompts import FIX_SQL_PROMPT
            from aughor.sql.join_guard import check_join_value_domains, check_filter_value_domains
            warn_text = "\n".join(w.to_prompt_text() for w in domain_warnings)
            try:
                fix2: SQLFix = get_provider("coder").complete(
                    system="You are a SQL expert. Fix the broken query.",
                    user=FIX_SQL_PROMPT.format(
                        dialect=conn.dialect,
                        sql=sql,
                        error="A predicate references a value not in its column/key domain — the result is unreliable.",
                        error_diagnosis=f"DIAGNOSIS:\n{warn_text}\n",
                        schema=state["schema_context"],
                        kb_patterns_section="",
                        metrics_section="",
                    ),
                    response_model=SQLFix,
                )
                retry = conn.execute(subq.id, fix2.fixed_sql)
                retry_domain = check_join_value_domains(conn, fix2.fixed_sql) or check_filter_value_domains(conn, fix2.fixed_sql)
                if not retry.error and not retry_domain:
                    new_pitfalls.append(Pitfall(
                        original_sql=sql, error=warn_text, fixed_sql=fix2.fixed_sql,
                        fix_explanation=fix2.fix_explanation,
                        data_quality_issue=fix2.data_quality_issue,
                    ))
                    results.append(_attach_stats(retry))
                else:
                    # Couldn't clear it — keep the original but carry the warning
                    # forward so the narrator flags the suspect join.
                    new_pitfalls.append(Pitfall(
                        original_sql=sql, error=warn_text, fixed_sql=sql,
                        fix_explanation=warn_text, data_quality_issue=warn_text,
                    ))
                    results.append(_attach_stats(result))
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "explore join-domain repair best-effort; original kept",
                         counter="join_guard.explore_repair")
                results.append(_attach_stats(result))
        else:
            # Clean execution, no domain warning — still lint for a raw-COUNT rate over a
            # join (#9): COUNT(child)/COUNT(parent) silently overstates the rate if any
            # parent has >1 child. Surface as a data-quality caveat (no auto-rewrite).
            if not result.error:
                if "cardinality_guard" not in ran_checks:
                    ran_checks.append("cardinality_guard")   # liveness: the count-ratio lint ran
                try:
                    from aughor.sql.fanout import count_ratio_distinct_risk
                    _cr = count_ratio_distinct_risk(sql, conn.dialect)
                    if _cr:
                        new_pitfalls.append(Pitfall(
                            original_sql=sql, error=_cr, fixed_sql=sql,
                            fix_explanation=_cr, data_quality_issue=_cr,
                        ))
                        # 0-III triangulation: run the COUNT(DISTINCT) twin and compare the
                        # rate column. Agreement = the number survives an independent path;
                        # divergence = the join fans out and the number is unreliable.
                        try:
                            from aughor.sql.fanout import count_distinct_variant, rate_columns_diverge
                            variant = count_distinct_variant(sql, conn.dialect)
                            if variant and variant != sql:
                                vres = conn.execute(subq.id + "_triangulate", variant)
                                if not vres.error:
                                    diverge = rate_columns_diverge(
                                        result.columns, result.rows, vres.columns, vres.rows)
                                    if diverge is True:
                                        ran_checks.append("triangulation:diverge")
                                        new_pitfalls.append(Pitfall(
                                            original_sql=sql, error="triangulation divergence",
                                            fixed_sql=variant,
                                            fix_explanation="The COUNT(DISTINCT) twin disagrees with the "
                                            "raw-COUNT rate — the join fans out, so the number is distorted.",
                                            data_quality_issue="rate FAILED triangulation: the raw-COUNT and "
                                            "COUNT(DISTINCT) paths disagree — treat the number as unreliable.",
                                        ))
                                    elif diverge is False:
                                        ran_checks.append("triangulation:agree")
                        except Exception as _exc2:
                            from aughor.kernel.errors import tolerate
                            tolerate(_exc2, "explore triangulation best-effort; original kept",
                                     counter="triangulation.explore")
                except Exception as _exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(_exc, "explore count-ratio lint best-effort; query proceeds",
                             counter="count_ratio.explore_lint")
            results.append(_attach_stats(result))

    # Stash results in state temporarily (reason_over_result picks them up)
    return {
        "query_history": results,   # operator.add appends — stays compatible with investigate mode
        "pitfalls": new_pitfalls,
        "verification_checks": ran_checks,   # liveness: guards that fired this sub-question
    }



# ── Node: exploratory_scan_subq ───────────────────────────────────────────────
# MindsDB-style mid-chain discovery: before planning SQL for a sub-question,
# run 1–2 quick probes to discover cardinalities, ranges, and distinct values.
# Results feed into the planner as a "Data Portrait" paragraph.

def exploratory_scan_subq(state: AgentState, conn: "DatabaseConnection") -> dict[str, Any]:
    """Run quick discovery queries for the current sub-question.

    Max 2 queries, max 3 seconds each. Produces a short markdown paragraph
    stored in state["subq_data_portrait"][subq.id].
    """
    import time as _time
    sub_questions = state.get("sub_questions", [])
    idx = state.get("current_subq_idx", 0)
    if idx >= len(sub_questions):
        return {}

    subq = sub_questions[idx]
    purpose = subq.purpose

    # Extract first table from schema context
    import re as _re
    m = _re.search(r'^(?:TABLE:|##)\s+([\w.]+)', state.get("schema_context", ""), _re.MULTILINE)
    table = m.group(1) if m else None
    if not table:
        return {}

    discoveries: list[str] = []
    _MAX_Q = 2
    _TIMEOUT = 3.0

    def _timed(sql: str) -> tuple[list[str], list[list]]:
        t0 = _time.time()
        try:
            result = conn.execute(subq.id + "_scan", sql)
            if _time.time() - t0 > _TIMEOUT:
                return [], []
            return result.columns, result.rows
        except Exception:
            return [], []

    queries_run = 0

    # Landscape / drill_down: cardinality + date range
    if purpose in ("landscape", "drill_down"):
        # Count distinct key column (first non-date column)
        cols, rows = _timed(f"SELECT * FROM {table} LIMIT 1")
        if rows and cols:
            key_col = next((c for c in cols if not _re.search(r'date|time|_at$', c, _re.I)), cols[0])
            c2, r2 = _timed(f'SELECT COUNT(DISTINCT "{key_col}") AS distinct_count FROM {table}')
            if r2 and queries_run < _MAX_Q:
                discoveries.append(f"Distinct {key_col}: {r2[0][0]}")
                queries_run += 1
        # Date range
        date_col = next((c for c in (cols or []) if _re.search(r'date|time|_at$', c, _re.I)), None)
        if date_col and queries_run < _MAX_Q:
            c3, r3 = _timed(f'SELECT MIN("{date_col}") AS min_date, MAX("{date_col}") AS max_date FROM {table}')
            if r3:
                discoveries.append(f"{date_col} range: {r3[0][0]} to {r3[0][1]}")
                queries_run += 1

    # Relationship: distinct categorical values
    elif purpose == "relationship":
        cols, rows = _timed(f"SELECT * FROM {table} LIMIT 1")
        if rows and cols:
            cat_col = next((c for c in cols if _re.search(r'name|type|category|status|region|state$', c, _re.I)), cols[0])
            if queries_run < _MAX_Q:
                c2, r2 = _timed(f'SELECT DISTINCT "{cat_col}" FROM {table} LIMIT 20')
                if r2:
                    vals = [str(r[0]) for r in r2[:20]]
                    discoveries.append(f"Distinct {cat_col} values: {', '.join(vals)}")
                    queries_run += 1

    # Threshold / confounder: numeric summary
    elif purpose in ("threshold", "confounder"):
        cols, rows = _timed(f"SELECT * FROM {table} LIMIT 1")
        if rows and cols:
            num_col = next((c for c in cols if _re.search(r'amount|price|total|revenue|count|score|value$', c, _re.I)), cols[0])
            if queries_run < _MAX_Q:
                c2, r2 = _timed(f'SELECT MIN("{num_col}") AS min_v, MAX("{num_col}") AS max_v, AVG("{num_col}")::FLOAT AS avg_v FROM {table}')
                if r2 and r2[0]:
                    discoveries.append(
                        f"{num_col} summary: min={r2[0][0]}, max={r2[0][1]}, avg={r2[0][2] if len(r2[0]) > 2 else 'N/A'}"
                    )
                    queries_run += 1

    portrait = "\n".join(f"- {d}" for d in discoveries) if discoveries else ""
    current_portraits = state.get("subq_data_portrait", {})
    updated_portraits = {**current_portraits, subq.id: portrait}

    return {"subq_data_portrait": updated_portraits}

# ── Node: reason_over_result ──────────────────────────────────────────────────

def reason_over_result(state: AgentState) -> dict[str, Any]:
    """
    Interpret results for the current sub-question. Marks it done.
    Injects refinements into the next sub-question if needed.
    Advances current_subq_idx.
    """
    sub_questions = state.get("sub_questions", [])
    idx = state.get("current_subq_idx", 0)
    prior_answers = state.get("subq_answers", [])

    if idx >= len(sub_questions):
        return {"current_subq_idx": idx + 1, "iteration": state.get("iteration", 0) + 1}

    subq = sub_questions[idx]

    # Gather the query results produced by plan_and_execute_subq for this sub-question
    all_history = state.get("query_history", [])
    subq_results = [r for r in all_history if r.hypothesis_id == subq.id]

    if not subq_results or all(r.error for r in subq_results):
        # Technical failure — record as inconclusive, don't block chain
        answer_obj = ReasoningOutput(
            answer=f"Could not retrieve data for {subq.id} due to SQL errors.",
            insight="No data available — this sub-question's findings are missing from the final answer.",
            refinement=None,
        )
    else:
        formatted = "\n\n".join(format_result_for_llm(r) for r in subq_results)
        llm = get_provider("coder")
        try:
            answer_obj = llm.complete(
                system="You are a senior data analyst interpreting query results.",
                user=REASON_OVER_RESULT_PROMPT.format(
                    question=state["question"],
                    subq_id=subq.id,
                    purpose=subq.purpose,
                    subq_question=subq.question,
                    expected_output=subq.expected_output,
                    query_results=formatted,
                    analysis_ledger=state.get("analysis_ledger") or "(none)",
                    prior_context=_format_prior_answers(prior_answers),
                ),
                response_model=ReasoningOutput,
            )
        except Exception:
            # Reasoning hiccup must not abort the chain — record the raw result as
            # an inconclusive answer and let downstream steps / synthesis proceed.
            answer_obj = ReasoningOutput(
                answer=f"Query for {subq.id} returned data but automated interpretation failed; see the raw result.",
                insight="Interpretation step errored — figures above are from the query but not narrated.",
                refinement=None,
            )

    # Use the first non-errored result for SQL/columns/rows in the answer record
    best_result = next((r for r in subq_results if not r.error), subq_results[0] if subq_results else None)
    answer = SubQuestionAnswer(
        subq_id=subq.id,
        question=subq.question,
        purpose=subq.purpose,
        sql=best_result.sql if best_result else "",
        columns=best_result.columns if best_result else [],
        rows=best_result.rows if best_result else [],
        row_count=best_result.row_count if best_result else 0,
        error=best_result.error if best_result else "No queries ran",
        answer=answer_obj.answer,
        insight=answer_obj.insight,
        refinement=answer_obj.refinement,
    )

    # Mark sub-question done and inject refinement into the next sub-question
    updated_subqs = list(sub_questions)
    updated_subqs[idx] = SubQuestion(**{**subq.model_dump(), "done": True, "answer": answer_obj.answer, "refinement": answer_obj.refinement})

    # Insert promoted sub-question if data revealed one, guaranteeing its id can't
    # collide with a planned one (a collision would mis-attribute its answer/portrait).
    if answer_obj.new_sub_question:
        nsq = answer_obj.new_sub_question
        existing_ids = {s.id for s in updated_subqs}
        if nsq.id in existing_ids or not (nsq.id or "").strip():
            nsq = SubQuestion(**{**nsq.model_dump(), "id": _unique_subq_id(existing_ids)})
        updated_subqs.insert(idx + 1, nsq)

    # Inject refinement text into the next sub-question's expected_output description
    if answer_obj.refinement and idx + 1 < len(updated_subqs):
        next_subq = updated_subqs[idx + 1]
        updated_subqs[idx + 1] = SubQuestion(**{
            **next_subq.model_dump(),
            "expected_output": f"{next_subq.expected_output}\n[Refinement from {subq.id}: {answer_obj.refinement}]",
        })

    return {
        "sub_questions": updated_subqs,
        "subq_answers": [answer],      # operator.add appends
        "current_subq_idx": idx + 1,
        "iteration": state.get("iteration", 0) + 1,
    }


# ── Routing ───────────────────────────────────────────────────────────────────

# Segment-style drills whose only job is to test the metric on another cut — once the
# metric has proven uniform, more of these re-confirm the baseline rather than add signal.
_DRILL_PURPOSES = {"relationship", "drill_down", "confounder", "threshold"}

# How many uniform dimensions before further drilling is judged redundant.
_UNIFORM_CONVERGENCE = int(__import__("os").getenv("AUGHOR_UNIFORM_CONVERGENCE", "3"))


def _should_early_stop(state: AgentState) -> bool:
    """Has the investigation converged? If the metric read statistically UNIFORM across
    several dimensions already AND the next planned step is just another segment drill,
    stop — it would re-confirm the flat baseline, not reveal a driver (#3 adaptivity,
    #13 redundancy). The synthesis (wrap-up) step is never skipped this way."""
    if len(_uniform_dimensions(state.get("query_history", []))) < _UNIFORM_CONVERGENCE:
        return False
    idx = state.get("current_subq_idx", 0)
    sub_questions = state.get("sub_questions", [])
    if idx >= len(sub_questions):
        return False  # nothing left to skip — normal completion handles it
    return getattr(sub_questions[idx], "purpose", "") in _DRILL_PURPOSES


def route_after_reason(state: AgentState) -> str:
    idx = state.get("current_subq_idx", 0)
    sub_questions = state.get("sub_questions", [])
    iteration = state.get("iteration", 0)

    if iteration >= MAX_SUBQ:
        return "synthesize_exploration"
    if idx >= len(sub_questions):
        return "synthesize_exploration"
    if _should_early_stop(state):
        logger.info("[explore] converged early — metric uniform across ≥%d dimensions; "
                    "skipping remaining segment drills", _UNIFORM_CONVERGENCE)
        return "synthesize_exploration"
    return "plan_and_execute_subq"


# ── Node: synthesize_exploration ──────────────────────────────────────────────

# ── Schema learning models (used by _learn_from_exploration) ─────────────────

class _ColumnCaveat(BaseModel):
    table: str = Field(description="Exact table name as it appears in the schema")
    column: str = Field(description="Exact column name")
    caveat: str = Field(
        description="One-sentence warning an analyst must know to avoid wrong results. "
                    "Must be directly supported by data observed in this investigation. "
                    "Example: 'customer_id is a per-order hash — use customer_unique_id "
                    "to identify unique customers across orders.'"
    )


class _SchemaLearning(BaseModel):
    caveats: list[_ColumnCaveat] = Field(
        default_factory=list,
        description="Schema-level column caveats discovered during this exploration. "
                    "Only include findings directly supported by actual query results above. "
                    "Empty list if no concrete schema issues were found.",
    )


def _learn_from_exploration(
    report: ExplorationReport,
    chain_summary: str,
    conn_id: str,
) -> int:
    """
    Persist schema discoveries from an exploration run back to the glossary.

    Two passes:
      1. Structured  — extract from report.data_quality_notes (no LLM, zero cost)
      2. LLM-based   — lightweight coder pass over the chain summary to catch
                       subtler patterns the structured notes missed

    Returns the number of new caveat entries written. Never raises — best-effort only.
    """
    try:
        from aughor.semantic.glossary import load_glossary, update_column

        written = 0
        glossary = load_glossary()

        def _existing_caveat(table: str, column: str) -> str:
            return (glossary.get("tables", {})
                            .get(table, {})
                            .get("columns", {})
                            .get(column, {})
                            .get("caveats", "") or "")

        def _write_caveat(table: str, column: str, text: str) -> bool:
            """Write caveat only if it adds new information. Returns True if written."""
            nonlocal glossary
            if not table or not column or not text or len(text) < 15:
                return False
            existing = _existing_caveat(table, column)
            if text in existing:
                return False
            combined = f"{existing} | {text}" if existing else text
            update_column(table, column, caveats=combined)
            # Reload so subsequent writes see the updated state
            glossary = load_glossary()
            return True

        # ── Pass 1: data_quality_notes (structured, free) ────────────────────
        for note in (report.data_quality_notes or []):
            table = (note.table or "").strip()
            column = (note.column or "").strip()
            issue = (note.issue or "").strip()
            if not table or not issue or table in ("SQL Execution", ""):
                continue
            if column and _write_caveat(table, column, issue):
                written += 1

        # ── Pass 2: LLM extraction from chain summary ─────────────────────────
        if not chain_summary:
            return written

        try:
            llm = get_provider("coder")
            learning: _SchemaLearning = llm.complete(
                system=(
                    "You are auditing an analytics investigation for schema-level data quality issues. "
                    "Extract ONLY concrete, column-specific caveats that were directly observed in "
                    "the findings below. Do not infer or guess. "
                    "Focus on: wrong identifier columns, per-row hashes mistaken for stable IDs, "
                    "NULL patterns that skew aggregations, type mismatches, and FK mismatches."
                ),
                user=(
                    f"INVESTIGATION FINDINGS:\n{chain_summary[:4000]}\n\n"
                    f"CONCLUSION: {report.conclusion}\n\n"
                    "List any schema caveats (column-level gotchas) that an analyst must know "
                    "to avoid getting wrong answers on this dataset. "
                    "Only include findings directly evidenced by the data above. "
                    "Return an empty list if no clear schema issues were found."
                ),
                response_model=_SchemaLearning,
            )

            for caveat in (learning.caveats or []):
                table = (caveat.table or "").strip()
                column = (caveat.column or "").strip()
                text = (caveat.caveat or "").strip()
                if _write_caveat(table, column, text):
                    written += 1

        except Exception:
            pass  # LLM pass failing is fine — pass 1 already wrote what it could

        return written

    except Exception:
        return 0  # Never crash the pipeline


def _uniform_dimensions(query_history: list) -> list[str]:
    """Interpretations of every sub-question result whose rate was UNIFORM across its
    segments (a uniformity StatResult with is_significant=False). Two or more such
    dimensions ⇒ the metric is statistically flat and the report must not claim drivers."""
    return [
        s.interpretation
        for r in (query_history or [])
        for s in (getattr(r, "stats", None) or [])
        if getattr(s, "type", "") == "uniformity" and not getattr(s, "is_significant", True)
    ]


class _RefutationVerdict(BaseModel):
    refuted: bool = Field(description="True if the headline finding does NOT hold up to scrutiny.")
    reason: str = Field(default="", description="One-sentence strongest objection.")
    alternative: Optional[str] = Field(default=None, description="Plausible alternative explanation, or null.")


def _run_refutation(question: str, conclusion: str, chain_summary: str) -> Optional[_RefutationVerdict]:
    """Adversarial self-verification (Bet 0, 0-IV): an independent skeptic pass that TRIES to
    refute the headline. Best-effort — returns None on any provider/parse failure so synthesis
    is never blocked. Gated by the caller to load-bearing (non-no-signal) conclusions only."""
    try:
        return get_provider("coder").complete(
            system="You are a skeptical analyst whose only job is to refute a finding.",
            user=REFUTE_FINDING_PROMPT.format(
                question=question, conclusion=conclusion, chain_summary=chain_summary[:6000]),
            response_model=_RefutationVerdict,
        )
    except Exception:
        return None


def _build_verification_manifest(state: AgentState, extra_checks: Optional[list[str]] = None) -> VerificationManifest:
    """Prove which guards actually ran on this investigation (Bet 0, increments 0-I…0-IV).

    Combines the liveness recorder (`verification_checks`, appended by each guard when it
    fires) + `extra_checks` (synthesis-time outcomes like adversarial refutation) with derived
    evidence. The key payoff is the `stats_attached` canary: if no statistical signals attached
    to numeric results, a guard silently failed (the exact `_attach_stats` class-E bug) —
    surfaced as not_run, never assumed passed."""
    recorded: set[str] = set()
    temporal_detail = None
    triangulation_outcome = None   # "agree" | "diverge" | None
    refute_outcome = None          # "survived" | "refuted" | None
    steered_by = None
    for c in (list(state.get("verification_checks", []) or []) + list(extra_checks or [])):
        head, _, tail = c.partition(":")
        recorded.add(head)
        if head == "specialist" and tail:
            steered_by = tail
        if head == "temporal_prune" and tail:
            temporal_detail = (f"pruned {tail} temporal sub-question(s)"
                               if tail != "0" else "ran — nothing to prune")
        if head == "triangulation" and tail:
            # diverge anywhere in the run is the signal that matters; it sticks.
            if tail == "diverge" or triangulation_outcome != "diverge":
                triangulation_outcome = tail
        if head == "adversarial_refute" and tail:
            refute_outcome = tail

    history = state.get("query_history", []) or []
    had_numeric = any((not r.error) and r.rows for r in history)
    stats_attached = any(getattr(r, "stats", None) for r in history)
    significance_ran = any(
        getattr(s, "type", "") == "uniformity"
        for r in history for s in (getattr(r, "stats", None) or [])
    )

    checks: list[VerificationCheck] = []
    if steered_by:
        checks.append(VerificationCheck(name="specialist", label="Steered by specialist",
                                        status="ran", detail=f"the '{steered_by}' expert shaped this run"))
    checks += [
        VerificationCheck(name="temporal_prune", label="Pre-flight temporal prune",
                          status="ran" if "temporal_prune" in recorded else "not_run",
                          detail=temporal_detail),
        VerificationCheck(name="join_value_domain", label="Join / filter value-domain guard",
                          status="ran" if "join_value_domain" in recorded else "not_run"),
        VerificationCheck(name="cardinality_guard", label="Raw-COUNT rate cardinality guard",
                          status="ran" if "cardinality_guard" in recorded else "not_run"),
    ]
    if not had_numeric:
        checks.append(VerificationCheck(name="stats_attached", label="Statistical signals attached",
                                        status="n/a", detail="no numeric results to analyse"))
    else:
        checks.append(VerificationCheck(
            name="stats_attached", label="Statistical signals attached",
            status="ran" if stats_attached else "not_run",
            detail=None if stats_attached
            else "NO stats attached to numeric results — a guard may have silently failed"))
    checks.append(VerificationCheck(
        name="segment_significance", label="Segment-uniformity significance test",
        status="ran" if significance_ran else "n/a",
        detail=None if significance_ran else "no rate-by-segment result to test"))
    if triangulation_outcome == "agree":
        checks.append(VerificationCheck(name="triangulation", label="Independent-path triangulation",
                                        status="ran", detail="COUNT(DISTINCT) twin agrees with the raw-COUNT rate"))
    elif triangulation_outcome == "diverge":
        checks.append(VerificationCheck(name="triangulation", label="Independent-path triangulation",
                                        status="ran", detail="paths DISAGREE — the rate is unreliable"))
    else:
        checks.append(VerificationCheck(name="triangulation", label="Independent-path triangulation",
                                        status="n/a", detail="no raw-COUNT rate over a join to triangulate"))
    if refute_outcome == "survived":
        checks.append(VerificationCheck(name="adversarial_refute", label="Adversarial refutation pass",
                                        status="ran", detail="headline survived an independent skeptic"))
    elif refute_outcome == "refuted":
        checks.append(VerificationCheck(name="adversarial_refute", label="Adversarial refutation pass",
                                        status="ran", detail="a skeptic REFUTED the headline — confidence demoted"))
    else:
        checks.append(VerificationCheck(name="adversarial_refute", label="Adversarial refutation pass",
                                        status="n/a", detail="not run for this conclusion"))

    # coverage is a pure GUARD metric — exclude the informational "specialist" marker.
    applicable = [c for c in checks if c.status != "n/a" and c.name != "specialist"]
    ran = sum(1 for c in applicable if c.status == "ran")
    coverage = round(ran / len(applicable), 3) if applicable else 1.0

    # ── Earned confidence (computed, not asserted) = coverage × completeness × data_trust ──
    answers = state.get("subq_answers", []) or []
    planned = state.get("sub_questions", []) or []
    pitfalls = state.get("pitfalls", []) or []
    uniform_dims = _uniform_dimensions(history)
    signals: list[str] = []

    # data_trust — does the underlying data look like it can support a conclusion?
    data_trust = 1.0
    nud = len(uniform_dims)
    if nud >= 3:
        data_trust -= 0.4
        signals.append(f"metric uniform across {nud} dimensions — suspiciously flat (possibly "
                       f"synthetic or exogenous); data-trust reduced")
    elif nud >= 2:
        data_trust -= 0.2
        signals.append(f"metric uniform across {nud} dimensions — limited signal; data-trust reduced")
    if "temporal_prune" in recorded and temporal_detail and "pruned" in temporal_detail \
            and "nothing to prune" not in temporal_detail:
        data_trust -= 0.2
        signals.append("data spans a single period — no temporal variance; data-trust reduced")
    if triangulation_outcome == "diverge":
        data_trust -= 0.4
        signals.append("a rate FAILED triangulation — its raw-COUNT and COUNT(DISTINCT) paths "
                       "disagree, so the number is unreliable")
    elif any("raw COUNT" in (getattr(p, "data_quality_issue", "") or "") for p in pitfalls):
        data_trust -= 0.2
        signals.append("a key rate divides raw COUNTs over a join — denominator may be distorted")
    data_trust = max(0.0, round(data_trust, 3))

    # completeness — a deliberate convergence stop (≥ _UNIFORM_CONVERGENCE uniform dims) is
    # NOT incomplete; only a genuine partial run is penalised.
    answered = len({a.subq_id for a in answers})
    total = len(planned) or answered or 1
    if nud >= _UNIFORM_CONVERGENCE:
        completeness = 1.0
    else:
        completeness = min(1.0, answered / total)
        if completeness < 1.0:
            signals.append(f"chain ran {answered}/{total} planned sub-questions")

    if coverage < 1.0:
        signals.append("not every guard ran — see the verification checks")
    earned = coverage * completeness * data_trust
    if refute_outcome == "refuted":
        earned *= 0.5
        signals.append("an independent skeptic refuted the headline — confidence halved")
    earned = round(earned, 3)
    band = "high" if earned >= 0.7 else "medium" if earned >= 0.4 else "low"
    if not signals:
        signals.append("all guards fired, chain complete, data looks trustworthy")

    return VerificationManifest(
        checks=checks, coverage=coverage,
        earned_confidence=earned, confidence_band=band,
        data_trust=data_trust, signals=signals,
    )


def _honesty_preamble(answers: list, planned: list, uniform_dims: list[str]) -> str:
    """Build the directive prefix prepended to the synthesis evidence so the report stays
    honest about (a) completeness and (b) signal. Pure/testable — no LLM, no state.

    Two independent guards, in order:
      • Completeness — if planned steps did NOT run, say so. Distinguish a DELIBERATE
        convergence stop (#3/#13: metric uniform ⇒ remaining drills skipped as redundant)
        from a genuine partial/salvaged run, since the right framing differs.
      • No-signal (#1) — if ≥2 dimensions read uniform, forbid segment-rate driver claims
        and flag a likely data-generation artifact / exogenous process; keep confidence low.
    """
    parts: list[str] = []
    answered_ids = {a.subq_id for a in answers}
    unanswered = [sq for sq in planned if sq.id not in answered_ids and not getattr(sq, "done", False)]
    converged_early = bool(unanswered) and len(uniform_dims) >= _UNIFORM_CONVERGENCE

    if converged_early:
        gap = "; ".join(f"{sq.id}: {sq.question}" for sq in unanswered[:6]) or "further segment drills"
        parts.append(
            f"✅ CONVERGED EARLY — the metric proved statistically uniform across "
            f"{len(uniform_dims)} dimensions, so the remaining planned drills were "
            f"intentionally skipped as redundant (they would re-confirm the flat baseline, "
            f"not reveal a new driver): {gap}. This is a deliberate, evidence-based stop, "
            f"NOT a failure or a data gap. Conclude that the metric is flat across the "
            f"tested dimensions and that further segment-level drilling is unwarranted; "
            f"pivot recommendations to baseline / policy-level levers. Do NOT imply the "
            f"skipped cuts were each individually tested.\n\n"
        )
    elif planned and (len(answers) < len(planned) or unanswered):
        gap = "; ".join(f"{sq.id}: {sq.question}" for sq in unanswered[:6]) or "later planned steps"
        parts.append(
            f"⚠️ INCOMPLETE CHAIN — only {len(answers)} of {len(planned)} planned sub-questions "
            f"actually ran. The following were NOT investigated and have NO data: {gap}. "
            f"Do NOT claim a comprehensive analysis or use phrases like 'given all of the above'. "
            f"Answer only from the completed steps below and explicitly note what remains unknown.\n\n"
        )

    if len(uniform_dims) >= 2:
        parts.append(
            f"⚠️ NO CAUSAL SIGNAL — {len(uniform_dims)} separate dimensions tested showed the "
            f"metric statistically UNIFORM across all their segments (every segment within "
            f"sampling noise of the pooled baseline; significance tests are in the evidence "
            f"below). Apparent segment differences are noise, not drivers. You MUST: "
            f"(1) state plainly that the metric is statistically flat across the tested "
            f"dimensions; (2) NOT recommend any segment-specific intervention justified by a "
            f"rate difference (cost concentration by volume/value is fine, a rate-driver claim "
            f"is not); (3) explicitly flag that a metric this uniform is typically a "
            f"data-generation artifact or an exogenous/discretionary process — recommend "
            f"validating the data-generating process before acting, and keep the headline "
            f"confidence LOW.\n\n"
        )
    return "".join(parts)


def synthesize_exploration(state: AgentState) -> dict[str, Any]:
    """Produce the final ExplorationReport from the completed Q→A chain."""
    answers = state.get("subq_answers", [])
    pitfalls = state.get("pitfalls", [])

    if not answers:
        return {
            "explore_report": ExplorationReport(
                headline="No data could be retrieved for this investigation.",
                conclusion="All sub-questions failed technically. Check the schema and query logs.",
                narrative="The investigative chain could not be completed due to SQL execution failures.",
                recommended_actions=["Check the connection and retry."],
            )
        }

    planned = state.get("sub_questions", []) or []
    uniform_dims = _uniform_dimensions(state.get("query_history", []))
    chain_summary = _honesty_preamble(answers, planned, uniform_dims) + _format_chain_summary(answers)

    # Collect data quality notes from pitfalls
    dq_notes: list[DataQualityNote] = []
    for p in pitfalls:
        if p.data_quality_issue:
            dq_notes.append(DataQualityNote(
                table="SQL Execution",
                column=None,
                issue=p.data_quality_issue,
                impact="May have affected data quality in the investigative chain.",
                recommended_fix=p.fix_explanation,
            ))

    raw_events = state.get("events_context") or ""
    events_section = f"BUSINESS CALENDAR CONTEXT (use to attribute findings to known events):\n{raw_events}\n" if raw_events else ""

    llm = get_provider("narrator")
    report: ExplorationReport = llm.complete(
        system="You are a senior data analyst writing an executive investigation report.",
        user=SYNTHESIZE_EXPLORATION_PROMPT.format(
            question=state["question"],
            analysis_ledger=state.get("analysis_ledger") or "(none)",
            chain_summary=chain_summary,
            events_section=events_section,
        ),
        response_model=ExplorationReport,
    )

    # Bet 0 (0-IV): adversarial self-verification. Gate to load-bearing conclusions — when
    # the run already converged to "no signal", refuting "it's flat" adds little. One skeptic
    # pass tries to refute the headline; a refutation halves earned confidence and is surfaced.
    extra_checks: list[str] = []
    if len(uniform_dims) < 2 and (report.conclusion or "").strip():
        verdict = _run_refutation(state["question"], report.conclusion, chain_summary)
        if verdict is not None:
            extra_checks.append(f"adversarial_refute:{'refuted' if verdict.refuted else 'survived'}")
            if verdict.refuted and verdict.reason:
                dq_notes.append(DataQualityNote(
                    table="Adversarial check", column=None,
                    issue=f"An independent skeptic refuted the headline: {verdict.reason}",
                    impact="Headline confidence was reduced accordingly.",
                    recommended_fix=verdict.alternative or "Re-examine the claim against this objection.",
                ))

    # Merge any dq_notes found during execution (after refutation so its note is included)
    if dq_notes:
        existing = list(report.data_quality_notes or [])
        report = ExplorationReport(**{**report.model_dump(), "data_quality_notes": existing + dq_notes})

    # Bet 0: attach the verification manifest (which guards actually ran). The LLM never
    # fills this — it's stamped from the run's liveness record so the user sees what was
    # (and wasn't) checked, defeating silent guard failures.
    manifest = _build_verification_manifest(state, extra_checks=extra_checks)
    report = ExplorationReport(**{**report.model_dump(), "verification": manifest})

    # Bet 1 flywheel (safe writeback): if a specialist steered this run AND it's verified, distil
    # learnings and PROPOSE them to the delta store (a human accepts/dismisses — never auto-mutate
    # the pack). Gated by is_compoundable, so an unverified run compounds nothing.
    try:
        _steered = [c.split(":", 1)[1] for c in (state.get("verification_checks", []) or [])
                    if isinstance(c, str) and c.startswith("specialist:")]
        if _steered:
            from aughor.packs.flywheel import distill_deltas, llm_distill_deltas
            from aughor.packs.deltastore import record_deltas
            _inv = state.get("investigation_id", "") or ""
            _res = distill_deltas(_steered[0], manifest,
                                  data_quality_notes=report.data_quality_notes, source_run=_inv)
            _deltas = list(_res.deltas)
            if _res.compounded:   # only LLM-distil a verified run (gate already passed)
                _deltas += llm_distill_deltas(_steered[0], manifest, chain_summary, source_run=_inv)
            if _deltas:
                n = record_deltas(_steered[0], state.get("connection_id", ""), _deltas, source_run=_inv)
                logger.info("[explore] flywheel proposed %d delta(s) for pack '%s'", n, _steered[0])
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "flywheel distil best-effort; run unaffected", counter="packs.flywheel")

    # ── Learning loop: persist schema discoveries back to the glossary ────────
    conn_id = state.get("connection_id", "")
    _learn_from_exploration(report, chain_summary, conn_id)

    return {"explore_report": report}
