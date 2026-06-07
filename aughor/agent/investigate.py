"""
ADA (Autonomous Intelligence Platform) — structured investigation engine.

Replaces the hypothesis-scoring pipeline for investigate-mode questions with
an 8-phase analytical lifecycle that produces a progressive, number-backed
narrative instead of confidence-scored hypothesis cards.

Each phase is a separate LangGraph node so api.py can stream phase results
progressively as they complete.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from aughor.agent.state import (
    AgentState,
    ADAReport,
    ADARecommendation,
    InvestigationFinding,
    InvestigationPhaseResult,
    PhaseKeyNumber,
    WaterfallEntry,
)
from aughor.tools.executor import format_result_for_llm
from aughor.tools.stats import analyze_query_result
from aughor.tools.table_names import bare as _bare  # aliased — local vars named `bare` shadow it
from aughor import telemetry as _telemetry

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection


# ── Dimension priority ordering (Spec §2, Tier 2V) ───────────────────────────
# Run customer-type first (new vs returning splits the cause tree), then
# channel, category, geography, everything else last.

_DIMENSION_PRIORITY_KEYWORDS: list[list[str]] = [
    ["customer_type", "customer_segment", "is_new", "new_customer", "returning", "customer_class"],
    ["channel", "source", "medium", "acquisition", "referrer", "utm"],
    ["category", "product_category", "product_type", "business_line", "vertical", "department"],
    ["region", "country", "geography", "geo", "city", "state", "market"],
    ["device", "platform", "browser", "os"],
    ["payment", "payment_method", "payment_type"],
]


def _prioritize_dimensions(dimensions: list[str]) -> list[str]:
    """Sort dimensions by spec-mandated priority: customer → channel → category → geo → other."""
    def _rank(dim: str) -> int:
        dl = dim.lower()
        for i, keywords in enumerate(_DIMENSION_PRIORITY_KEYWORDS):
            if any(kw in dl for kw in keywords):
                return i
        return len(_DIMENSION_PRIORITY_KEYWORDS)

    return sorted(dimensions, key=_rank)


# ── Router functions (read by graph.py conditional edges) ────────────────────

_DIMENSION_QUESTION_RE = re.compile(
    r'\b(which|what|top|breakdown|by|per|across|segment|split|attribution|influence|'
    r'channel|source|medium|region|country|geo|product|category|device|platform|'
    r'customer|segment|cohort|campaign|referrer|utm)\b',
    re.IGNORECASE,
)


def _question_asks_for_dimension(question: str) -> bool:
    """
    Return True when the user explicitly asked about a specific dimension
    (e.g. "which channel", "by region", "top product category").
    When True, Tier 0 termination is suppressed — we must run dimensional analysis
    even if the overall metric change is within normal variance.
    """
    q = question.lower()
    # "which X" or "what X" followed by a dimension keyword
    if re.search(r'\b(which|what)\b.{0,40}\b(channel|source|region|product|category|device|segment|campaign)\b', q):
        return True
    # Explicit attribution phrasing
    if re.search(r'\b(influence|attribution|drove|driving|caused|responsible|contributed|contribution)\b', q):
        return True
    # "breakdown by" / "split by" / "per channel" patterns
    if re.search(r'\b(breakdown|split|breakdown|segment)\s+(by|across|per)\b', q):
        return True
    return False


def route_after_baseline(state: AgentState) -> str:
    """
    Tier 0 gate: if the decline is within normal variance, skip straight to
    synthesis so we don't run 4 more expensive phases on non-anomalies.

    EXCEPTION: when the user explicitly asked about a specific dimension
    (e.g. "which channel had most influence"), always proceed to dimensional
    analysis — the user wants the breakdown regardless of anomaly status.

    Decision hierarchy:
      1. User asked about a dimension → always proceed to ada_decompose
      2. stats.py code-level sigma (authoritative, deterministic)
      3. LLM interpretation's is_significant flags (fallback)
      4. Unknown → proceed (don't block on uncertainty)
    """
    question = state.get("question", "")
    if _question_asks_for_dimension(question):
        return "ada_decompose"  # never skip when user wants dimensional breakdown

    sigma = state.get("_baseline_sigma")
    code_sig = state.get("_baseline_significant")

    # Code-level signal: stats.py ran and says "not significant"
    if code_sig is False and (sigma is None or sigma < 1.5):
        from aughor.stats import stats as _s; _s.inc("tier0_skips")
        return "ada_synthesize"  # early stop → "within normal variance" report

    # LLM interpretation signal
    phases = state.get("investigation_phases") or []
    for phase in phases:
        if phase.get("phase_id") == "baseline":
            for f in phase.get("findings", []):
                if f.get("is_significant"):
                    return "ada_decompose"
            # Baseline phase found, but no finding flagged significant
            if code_sig is False:
                return "ada_synthesize"

    # No definitive signal → proceed (conservative: don't block)
    return "ada_decompose"


def route_after_decompose(state: AgentState) -> str:
    """
    Tier 1 gate: if the question does NOT ask about a specific dimension AND
    the decomposition already gave a clear, complete answer, skip straight to
    synthesis — no need for dimensional drill-down.

    We proceed to dimensional when ANY of these are true:
      - User explicitly asked about a dimension (channel, region, product, segment…)
      - Baseline anomaly is very large (sigma >= 3.0 — something concentrated is likely)
      - No definitive decomposition summary exists (play it safe)
    """
    question = state.get("question", "")
    if _question_asks_for_dimension(question):
        return "ada_dimensional"

    sigma = state.get("_baseline_sigma")
    # Very large anomaly (3σ+) — still worth dimensional drill-down to find where it concentrated
    if sigma is not None and sigma >= 3.0:
        return "ada_dimensional"

    decomp_summary = state.get("_decomp_summary", "")
    if not decomp_summary or decomp_summary == "Metric decomposition complete.":
        return "ada_dimensional"  # no useful decomp output → still run dimensional

    # Decompose gave a clear answer and question is simple → go straight to synthesis
    from aughor.stats import stats as _s; _s.inc("tier1_skips")
    return "ada_synthesize"


def _question_needs_behavioral(question: str) -> bool:
    """
    Return True only when behavioral/operational diagnostics are likely to add value.
    Behavioral phase is expensive and often adds noise for simple trend questions.
    Only run it when the user is explicitly asking about behavioral patterns.
    """
    q = question.lower()
    behavioral_keywords = [
        "refund", "return rate", "churn", "retain", "retention", "cancel",
        "discount", "coupon", "promotion", "promo", "stockout", "inventory",
        "stop buying", "stopped buying", "not coming back", "not returning",
        "customer behav", "why did customer", "why are customer",
        "repeat purchase", "repeat buy", "loyalty",
    ]
    return any(kw in q for kw in behavioral_keywords)


def route_after_dimensional(state: AgentState) -> str:
    """
    Tier 2 gate: skip behavioral unless the question explicitly asks about
    behavioral/operational patterns (refunds, churn, discounts, retention, etc.).

    Behavioral phase runs many extra queries that rarely add signal for simple
    trend questions ("why did revenue increase?") and often generate errors
    when behavioral tables (sessions, refunds) don't exist in the schema.
    """
    question = state.get("question", "")
    if _question_needs_behavioral(question):
        return "ada_behavioral"
    from aughor.stats import stats as _s; _s.inc("tier2_skips")
    return "ada_synthesize"


# ── Helpers ───────────────────────────────────────────────────────────────────

# Groq free tier hard cap is ~12k tokens per request.
# Rough char-to-token ratio for mixed SQL/prose is ~3.5 chars/token.
# Budget: 8000 tokens for schema+scan combined → ~28000 chars total.
_SCHEMA_CHAR_LIMIT = 20_000
_SCAN_CHAR_LIMIT = 6_000


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated {len(text) - limit} chars]"


def _with_ledger(state: "AgentState", schema: str) -> str:
    """Prepend the run's canonical definitions to the schema block a phase planner
    sees, so every phase uses the same identifiers/metric expressions and reuses
    figures already computed earlier. No-op when no ledger was built."""
    led = (state.get("analysis_ledger") or "").strip()
    if not led:
        return schema
    return (
        "CANONICAL DEFINITIONS (binding for THIS analysis — use these exact "
        "identifiers and metric expressions in EVERY query so figures stay "
        "consistent across phases; if a figure was already computed in an earlier "
        "phase, reuse it verbatim rather than recomputing it):\n"
        f"{led}\n\n"
        f"{schema}"
    )


def _filter_schema(schema: str, table_names: list[str]) -> str:
    """
    Keep only the schema blocks for tables mentioned in table_names.
    Works with both TABLE: headers (traditional schema) and ## headers (data catalog).
    Uses word-boundary matching to avoid 'orders' matching 'order_items'.
    Falls back to full schema if nothing matches.
    """
    if not table_names or not schema:
        return schema

    # Normalise: extract bare table names (strip schema prefix like analytics.)
    bare = {_bare(t) for t in table_names if t}

    # Build a single regex that matches any bare name at a word boundary
    pattern = re.compile(
        r'\b(' + '|'.join(re.escape(n) for n in bare) + r')\b',
        re.IGNORECASE,
    )

    blocks: list[str] = []
    current: list[str] = []

    def _flush():
        if current:
            block_text = "\n".join(current)
            if pattern.search(current[0]):
                blocks.append(block_text)
            current.clear()

    for line in schema.splitlines():
        if line.strip() == "":
            _flush()
        else:
            current.append(line)
    _flush()

    filtered = "\n\n".join(blocks)
    return filtered if filtered.strip() else schema


def _provider(role="coder"):
    from aughor.llm.provider import get_provider
    return get_provider(role)


_ID_COLUMN_SUFFIXES = ("_id", "_key", "_code", "_num", "_no", "_ref", "_sk", "_nk", "_pk")


def _validate_intake_date_column(date_column: str) -> str | None:
    """
    Return an error message if date_column looks like an identifier column, not a date.
    Returns None if date_column looks valid.
    """
    if not date_column or date_column.upper() == "NONE":
        return None  # explicitly set to NONE is valid (no date column found)
    col_part = _bare(date_column)
    if any(col_part.endswith(s) for s in _ID_COLUMN_SUFFIXES):
        return (
            f"date_column '{date_column}' ends with an identifier suffix ({col_part}) — "
            "this is not a date column. You MUST use a column whose schema type contains "
            "DATE, TIMESTAMP, or TIME. Check the schema for the correct date column and update date_column."
        )
    return None




def _extract_qualified_tables(schema: str) -> dict[str, str]:
    """Map bare table names → fully-qualified names from schema context.

    Handles both TABLE: ecommerce.orders (schema context) and ## ecommerce.orders (data catalog).
    Returns a dict like {'orders': 'ecommerce.orders', 'customers': 'ecommerce.customers'}.
    If the schema has no qualified names, the mapping is identity (bare → bare).
    """
    # TABLE: header format (traditional schema context)
    table_pattern = re.compile(r'^TABLE:\s+([\w.]+)', re.MULTILINE)
    # ## header format (data catalog markdown)
    catalog_pattern = re.compile(r'^##\s+([\w.]+)', re.MULTILINE)
    mapping: dict[str, str] = {}
    for m in table_pattern.finditer(schema):
        qualified = m.group(1)
        bare = _bare(qualified)
        if bare not in mapping or len(qualified) < len(mapping[bare]):
            mapping[bare] = qualified
    for m in catalog_pattern.finditer(schema):
        qualified = m.group(1)
        bare = _bare(qualified)
        if bare not in mapping or len(qualified) < len(mapping[bare]):
            mapping[bare] = qualified
    return mapping


def _qualify_intake_table_names(intake, schema: str) -> None:
    """In-place fix bare table/column references in an IntakeOutput using the schema context."""
    mapping = _extract_qualified_tables(schema)
    if not mapping:
        return

    # metric_table
    if intake.metric_table:
        bare = _bare(intake.metric_table)
        if bare in mapping and intake.metric_table != mapping[bare]:
            intake.metric_table = mapping[bare]

    # date_column  (table.column)
    if intake.date_column and intake.date_column.upper() != "NONE":
        parts = intake.date_column.split(".")
        if len(parts) == 2:
            bare_table = parts[0].lower()
            if bare_table in mapping and parts[0] != mapping[bare_table]:
                intake.date_column = f"{mapping[bare_table]}.{parts[1]}"

    # dimensions  (list of table.column)
    qualified_dims: list[str] = []
    for dim in intake.dimensions:
        parts = dim.split(".")
        if len(parts) == 2:
            bare_table = parts[0].lower()
            if bare_table in mapping and parts[0] != mapping[bare_table]:
                qualified_dims.append(f"{mapping[bare_table]}.{parts[1]}")
            else:
                qualified_dims.append(dim)
        else:
            qualified_dims.append(dim)
    intake.dimensions = qualified_dims
def _validate_intake_metric_table(metric_table: str, schema: str) -> str | None:
    """Return an error if metric_table does not exist in the schema."""
    if not metric_table or not schema:
        return None
    import re
    # Match both TABLE: and ## header formats
    table_pattern = re.compile(r'^TABLE:\s+([\w.]+)', re.MULTILINE)
    catalog_pattern = re.compile(r'^##\s+([\w.]+)', re.MULTILINE)
    found_qualified = [m.group(1) for m in table_pattern.finditer(schema)] + [m.group(1) for m in catalog_pattern.finditer(schema)]
    found_bare = [_bare(t) for t in found_qualified]
    bare = _bare(metric_table)

    if bare not in found_bare:
        return (
            f"metric_table '{metric_table}' does not exist in the schema. "
            f"Available tables: {', '.join(found_bare[:12])}. "
            "You MUST choose one of the tables listed above."
        )

    # If schema uses qualified names, require the intake to also use them
    has_qualified = any('.' in t for t in found_qualified)
    if has_qualified and '.' not in metric_table:
        qualified_match = next((t for t in found_qualified if _bare(t) == bare), None)
        if qualified_match:
            return (
                f"metric_table '{metric_table}' is missing the schema prefix. "
                f"The schema uses qualified names. Use '{qualified_match}' instead."
            )
    return None


def _zero_row_suspicious(sql: str) -> str | None:
    """Return a diagnosis string if a zero-row result is likely a bad query, else None."""
    s = sql.lower()
    # Casting an identifier column as a date is the #1 cause of silent zero-row failures
    if "cast(" in s and ("as date" in s or "as timestamp" in s):
        return (
            "Query returned 0 rows. LIKELY CAUSE: CAST(... AS DATE/TIMESTAMP) is being used on "
            "an identifier column (e.g. order_id, invoice_id) which is NOT a date. "
            "Find the real DATE/TIMESTAMP column in the schema (or a joinable table) and use that instead."
        )
    # Filtering on a column that sounds like an ID but treating it as a date range
    import re as _re
    if _re.search(r"where\s+\w*(?:_id|_key|_num|_code)\b.*>=\s*'[0-9]{4}", s):
        return (
            "Query returned 0 rows. LIKELY CAUSE: a WHERE clause is comparing an _id/_key column "
            "to a date string — identifiers are not dates. "
            "Use a proper DATE/TIMESTAMP column for date range filtering."
        )
    return None


def _execute_safe(conn: "DatabaseConnection", phase_id: str, sql: str):
    """Execute SQL with one self-correction retry. Returns QueryResult.

    Retries on:
    - Hard SQL errors (syntax, missing column/table)
    - Suspicious zero-row results (e.g. CAST of identifier column as DATE)
    """
    from aughor.agent.prompts import FIX_SQL_PROMPT
    from aughor.agent.prompts_investigate import PhasePlan
    from pydantic import BaseModel

    result = conn.execute(phase_id, sql)

    # Determine whether to retry: hard error OR suspicious zero-row result
    _zero_diag = None
    if not result.error and result.row_count == 0:
        _zero_diag = _zero_row_suspicious(sql)

    if result.error or _zero_diag:
        class _Fix(BaseModel):
            fixed_sql: str
            explanation: str

        try:
            _err = result.error or ""
            # Build targeted diagnosis for the fix LLM
            if _zero_diag:
                _diag = f"DIAGNOSIS: {_zero_diag}\n"
            elif "does not have a column named" in _err or ("column" in _err.lower() and "not" in _err.lower()):
                _diag = (
                    "DIAGNOSIS: A column name in the query does not exist. "
                    "Use ONLY the exact column names listed in the SCHEMA. "
                    "Do NOT invent or rename columns — find the correct column or join to a table that has it.\n"
                )
            elif "does not exist" in _err and "table" in _err.lower():
                _diag = (
                    "DIAGNOSIS: A table name in the query does not exist. "
                    "Use ONLY the table names listed in the SCHEMA above.\n"
                )
            else:
                _diag = ""

            # For zero-row retries, synthesise a fake "error" message so FIX_SQL_PROMPT
            # has something useful in the ERROR MESSAGE field
            fix_error = _err if _err else "Query returned 0 rows — the SQL logic is likely wrong (see DIAGNOSIS)."

            fix_prompt = FIX_SQL_PROMPT.format(
                dialect=conn.dialect,
                sql=sql,
                error=fix_error,
                schema=conn.get_schema(),
                kb_patterns_section="",
                error_diagnosis=_diag,
            )
            fix = _provider("coder").complete(
                system="Fix this SQL query. Return fixed_sql and a one-line explanation.",
                user=fix_prompt,
                response_model=_Fix,
            )
            retry = conn.execute(phase_id, fix.fixed_sql)
            # Accept the fix if: hard error resolved, OR zero-row and fix got rows
            if not retry.error and (retry.row_count > 0 or not _zero_diag):
                retry.sql = fix.fixed_sql
                result = retry
        except Exception:
            pass
    return result


def _parallel_execute_safe(
    conn: "DatabaseConnection",
    phase_id: str,
    plan_queries: list,
    cap: int = 4,
) -> list[tuple]:
    """Run up to `cap` PhasePlan queries in parallel using per-thread reader connections.

    Each worker calls _execute_safe() on its own make_reader() clone so shared
    connection state is never touched concurrently. Falls back to serial if
    ThreadPoolExecutor fails or there is only one query.

    Returns a list of (PlanQuery, QueryResult) tuples in the same order as
    plan_queries[:cap].
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    valid = [(q, q.sql.strip()) for q in plan_queries[:cap] if q.sql and q.sql.strip()]
    if not valid:
        return []
    if len(valid) == 1:
        q, sql = valid[0]
        r = _execute_safe(conn, phase_id, sql)
        r.hypothesis_id = phase_id
        return [(q, r)]

    def _run(item: tuple) -> tuple:
        q, sql = item
        reader = conn.make_reader()
        r = _execute_safe(reader, phase_id, sql)
        r.hypothesis_id = phase_id
        return (q, r)

    try:
        with ThreadPoolExecutor(max_workers=len(valid)) as pool:
            futures = {pool.submit(_run, item): i for i, item in enumerate(valid)}
            ordered: list[tuple | None] = [None] * len(valid)
            for fut in as_completed(futures):
                ordered[futures[fut]] = fut.result()
            return [r for r in ordered if r is not None]
    except Exception:
        # Serial fallback — never let parallelization break the investigation
        results = []
        for q, sql in valid:
            r = _execute_safe(conn, phase_id, sql)
            r.hypothesis_id = phase_id
            results.append((q, r))
        return results


def _results_to_text(results) -> str:
    """Render a list of QueryResults as compact text for LLM interpretation."""
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(f"--- Query {i} ---")
        parts.append(format_result_for_llm(r, max_rows=12))
    return "\n\n".join(parts)


def _phase_result(
    phase_id: str,
    phase_name: str,
    phase_icon: str,
    status: str,
    summary: str,
    findings: list[InvestigationFinding],
    skipped_reason: Optional[str] = None,
) -> InvestigationPhaseResult:
    return InvestigationPhaseResult(
        phase_id=phase_id,
        phase_name=phase_name,
        phase_icon=phase_icon,
        status=status,
        summary=summary,
        findings=findings,
        skipped_reason=skipped_reason,
    )


def _finding_from_result_and_model(
    finding_id: str,
    result,
    model,
    plan_chart_type: str = "auto",
) -> InvestigationFinding:
    chart = model.chart_type if model.chart_type != "auto" else plan_chart_type
    return InvestigationFinding(
        finding_id=finding_id,
        title=model.title,
        sql=result.sql,
        columns=result.columns,
        rows=result.rows[:50],
        row_count=result.row_count,
        error=result.error,
        interpretation=model.interpretation,
        key_numbers=[
            PhaseKeyNumber(
                label=kn.label,
                value=kn.value,
                delta=kn.delta,
                context=kn.context,
            )
            for kn in model.key_numbers
        ],
        chart_type=chart,
        stat_note=model.stat_note,
        is_significant=model.is_significant,
    )


def _skipped_finding(phase_id: str, reason: str) -> InvestigationFinding:
    return InvestigationFinding(
        finding_id=f"{phase_id}_skip",
        title="Skipped",
        sql="",
        columns=[],
        rows=[],
        row_count=0,
        error=None,
        interpretation=reason,
        key_numbers=[],
        chart_type="none",
        stat_note=None,
        is_significant=False,
    )


def _detect_phase_contradictions(phases: list[InvestigationPhaseResult]) -> str:
    """
    Deterministically scan phase summaries for direct factual contradictions.

    Detects these contradiction classes:
      A. Significance flip — one phase says the change is "significant" / "anomalous"
         while another says "within normal variance" / "not significant" / "no anomaly".
      B. Direction flip — one phase says metric is "up" / "increased" and another
         says "down" / "decreased" for the same metric mention.
      C. Causal attribution flip — one phase names a cause X, another says X is "not
         the cause" or that the relationship is "not significant".

    Returns a prompt section string to inject before synthesis, or "" if clean.
    Never raises.
    """
    try:
        if not phases or len(phases) < 2:
            return ""

        summaries: list[tuple[str, str]] = [
            (p.get("phase_name", ""), (p.get("summary") or "").lower())
            for p in phases
        ]

        contradictions: list[str] = []

        # ── Class A: significance flip ────────────────────────────────────────
        sig_positive = re.compile(
            r'\b(significant|anomal|unusual|notable|material|above.normal|outside.normal)\b'
        )
        sig_negative = re.compile(
            r'\b(within.normal|no.anomal|not.significant|insignificant|expected.variance|'
            r'consistent.with.historical|normal.variance|no.significant)\b'
        )
        phases_with_sig = [(name, s) for name, s in summaries if sig_positive.search(s)]
        phases_with_neg = [(name, s) for name, s in summaries if sig_negative.search(s)]
        if phases_with_sig and phases_with_neg:
            contradictions.append(
                f"Significance contradiction: phase(s) {', '.join(n for n, _ in phases_with_sig)} "
                f"describe the change as significant/anomalous, but phase(s) "
                f"{', '.join(n for n, _ in phases_with_neg)} describe it as within normal variance. "
                f"You MUST resolve this tension explicitly in your report — do NOT paper over it."
            )

        # ── Class B: direction flip on same metric keyword ─────────────────────
        # Find metric-like tokens (revenue, orders, conversion, churn, etc.)
        metric_re = re.compile(
            r'\b(revenue|orders|conversion|churn|retention|aov|gmv|mrr|sessions|'
            r'traffic|cac|ltv|profit|margin|spend|cost)\b'
        )
        direction_up = re.compile(r'\b(increas|grew|up|higher|gain|improv|recover|surged)\b')
        direction_down = re.compile(r'\b(declin|decreas|fell|drop|down|lower|reduc|shrunk|worsened)\b')

        metric_directions: dict[str, dict[str, list[str]]] = {}
        for name, s in summaries:
            for m in metric_re.finditer(s):
                metric = m.group(1)
                # Check surrounding context (±80 chars)
                start = max(0, m.start() - 80)
                end = min(len(s), m.end() + 80)
                ctx = s[start:end]
                if direction_up.search(ctx):
                    metric_directions.setdefault(metric, {}).setdefault("up", []).append(name)
                elif direction_down.search(ctx):
                    metric_directions.setdefault(metric, {}).setdefault("down", []).append(name)

        for metric, dirs in metric_directions.items():
            if "up" in dirs and "down" in dirs:
                contradictions.append(
                    f"Direction contradiction on '{metric}': "
                    f"phase(s) {', '.join(dirs['up'])} describe it as increasing, "
                    f"phase(s) {', '.join(dirs['down'])} describe it as decreasing. "
                    f"Clarify which direction is correct and over what time period."
                )

        if not contradictions:
            return ""

        lines = [
            "\n⚠ CROSS-PHASE CONTRADICTIONS DETECTED — address each explicitly in your report "
            "(surface them in the risks or data quality notes; do NOT silently average them out):"
        ]
        for i, c in enumerate(contradictions, 1):
            lines.append(f"  {i}. {c}")
        lines.append("")
        return "\n".join(lines)

    except Exception:
        return ""


def _phases_summary(phases: list[InvestigationPhaseResult]) -> str:
    lines = []
    for p in phases:
        lines.append(f"[{p['phase_name']}] {p['summary']}")
        for f in p["findings"]:
            if not f["error"] and f["interpretation"]:
                lines.append(f"  • {f['title']}: {f['interpretation'][:200]}")
    return "\n".join(lines)


def _phases_evidence(phases: list[InvestigationPhaseResult]) -> str:
    lines = []
    for p in phases:
        lines.append(f"\n=== {p['phase_name']} ===")
        for f in p["findings"]:
            if f["sql"]:
                lines.append(f"SQL: {f['sql']}")
            if f["error"]:
                lines.append(f"ERROR: {f['error']}")
            elif f["columns"] and f["rows"]:
                col_str = " | ".join(f["columns"])
                lines.append(col_str)
                lines.append("-" * len(col_str))
                for row in f["rows"][:20]:
                    lines.append(" | ".join(str(v) for v in row))
                if f["row_count"] > 20:
                    lines.append(f"... ({f['row_count'] - 20} more rows)")
    return "\n".join(lines)


# ── Phase nodes ───────────────────────────────────────────────────────────────

def _extract_data_date_range(scan_context: str) -> tuple:
    """Pull the overall (min, max) date the data actually covers from the DATA
    PORTRAIT text — the [PROFILE] lines carry 'YYYY-MM-DD → YYYY-MM-DD'."""
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", scan_context or "")
    if not dates:
        return None, None
    return min(dates), max(dates)


def _validate_intake_windows(intake, dmin, dmax):
    """Reject a comparison window that falls entirely OUTSIDE the data's real date
    range — the #1 cause of 'compared against an empty period' (e.g. 'May vs April'
    when only May exists). Returns a correction string, or None if the window is OK."""
    if not dmin or not dmax:
        return None
    cs = (getattr(intake, "comparison_start", "") or "")[:10]
    ce = (getattr(intake, "comparison_end", "") or "")[:10]
    if cs and ce and (ce < dmin or cs > dmax):
        return (
            f"The comparison period {intake.comparison_label} ({cs} → {ce}) falls OUTSIDE the "
            f"data range [{dmin} → {dmax}] — there is no data there, so the baseline would be empty. "
            f"Pick the most recent prior period that lies within [{dmin} → {dmax}]; if no prior "
            f"period exists, set comparison_start/comparison_end equal to observation_start/"
            f"observation_end and explain in intake_notes that there is no prior period to compare against."
        )
    return None


@_telemetry.node_span("ada_intake")
def ada_intake(state: AgentState) -> dict:
    """
    Phase 1 — Question Intake.
    Parses the question into: metric SQL, observation period, comparison period,
    date column, metric table, available dimensions.
    Returns updated state with ada_intake stored in investigation_phases[0].
    """
    from aughor.agent.prompts_investigate import INTAKE_PROMPT, IntakeOutput

    question = state["question"]
    schema = _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT)
    scan = _trim(state.get("scan_context") or "", _SCAN_CHAR_LIMIT)
    events = state.get("events_context") or ""
    events_section = f"BUSINESS CALENDAR:\n{events}\n" if events else ""

    prompt = INTAKE_PROMPT.format(
        question=question,
        schema=schema,
        scan_context=scan,
        events_section=events_section,
    )

    try:
        intake: IntakeOutput = _provider("coder").complete(
            system="You are a precise data analyst parsing a business question. Return a structured investigation specification.",
            user=prompt,
            response_model=IntakeOutput,
        )
    except Exception as e:
        intake = None
        intake_error = str(e)

    # Code-level validation: reject and retry if date_column is obviously an ID column
    if intake is not None:
        dc_error = _validate_intake_date_column(intake.date_column)
        if dc_error:
            retry_prompt = (
                prompt
                + f"\n\nCORRECTION REQUIRED: {dc_error}\n"
                "Re-examine the schema, find the correct DATE/TIMESTAMP column, and return the fixed spec."
            )
            try:
                intake = _provider("coder").complete(
                    system="You are a precise data analyst parsing a business question. Return a structured investigation specification.",
                    user=retry_prompt,
                    response_model=IntakeOutput,
                )
            except Exception as e2:
                # Keep the original (even if bad) rather than crashing
                pass

    # Code-level validation: reject and retry if metric_table does not exist in schema
    if intake is not None:
        mt_error = _validate_intake_metric_table(intake.metric_table, schema)
        if mt_error:
            retry_prompt = (
                prompt
                + f"\n\nCORRECTION REQUIRED: {mt_error}\n"
                "Re-examine the schema, pick a table that actually exists, and return the fixed spec."
            )
            try:
                intake = _provider("coder").complete(
                    system="You are a precise data analyst parsing a business question. Return a structured investigation specification.",
                    user=retry_prompt,
                    response_model=IntakeOutput,
                )
            except Exception:
                pass

    # Code-level validation: reject and retry if the comparison window is outside the data range
    if intake is not None:
        _dmin, _dmax = _extract_data_date_range(scan)
        win_error = _validate_intake_windows(intake, _dmin, _dmax)
        if win_error:
            retry_prompt = (
                prompt
                + f"\n\nCORRECTION REQUIRED: {win_error}\n"
                "Return the fixed spec with a comparison window that actually contains data."
            )
            try:
                intake = _provider("coder").complete(
                    system="You are a precise data analyst parsing a business question. Return a structured investigation specification.",
                    user=retry_prompt,
                    response_model=IntakeOutput,
                )
            except Exception:
                pass

    # Post-process: ensure all table references are fully-qualified when the schema uses them
    if intake is not None:
        _qualify_intake_table_names(intake, schema)

    if intake is None:
        phase = _phase_result(
            "intake", "Question Intake", "🔍", "error",
            "Could not parse investigation specification.",
            [_skipped_finding("intake", intake_error)],
        )
        return {
            "investigation_phases": [phase],
            "ada_report": None,
        }

    # Store the intake spec in state via a synthetic phase (no SQL, just metadata)
    finding = InvestigationFinding(
        finding_id="intake_spec",
        title="Investigation Specification",
        sql="",
        columns=["field", "value"],
        rows=[
            ["Metric", f"{intake.metric_label} ({intake.metric_sql})"],
            ["Observation", f"{intake.observation_label} ({intake.observation_start} → {intake.observation_end})"],
            ["Comparison", f"{intake.comparison_label} ({intake.comparison_start} → {intake.comparison_end})"],
            ["Date column", intake.date_column],
            ["Primary table", intake.metric_table],
            ["Dimensions", ", ".join(intake.dimensions[:8])],
        ],
        row_count=6,
        error=None,
        interpretation=intake.intake_notes or f"Investigating {intake.metric_label} in {intake.observation_label}.",
        key_numbers=[],
        chart_type="none",
        stat_note=None,
        is_significant=False,
    )
    phase = _phase_result(
        "intake", "Question Intake", "🔍", "complete",
        f"Measuring {intake.metric_label} in {intake.observation_label} vs {intake.comparison_label}.",
        [finding],
    )
    # Build a filtered schema containing only the tables intake identified
    relevant_tables = [intake.metric_table] + [
        d.split(".")[0] for d in intake.dimensions if "." in d
    ]
    filtered_schema = _filter_schema(state["schema_context"], relevant_tables)

    intake_dict = intake.model_dump()
    intake_dict["filtered_schema"] = filtered_schema

    # Enrich with ontology entity context (best-effort — never crash ada_intake)
    try:
        from aughor.ontology.store import load_latest_ontology
        onto = load_latest_ontology(state.get("connection_id", ""))
        if onto:
            mt = intake.metric_table
            entity = next(
                (e for e in onto.entities.values()
                 if mt in (e.source_tables or [])),
                None,
            )
            if entity:
                intake_dict["ontology_entity_id"] = entity.id
                intake_dict["active_filter"]      = entity.active_filter
                intake_dict["lifecycle_column"]   = entity.lifecycle_column
                intake_dict["terminal_states"]    = entity.terminal_states
                intake_dict["lifecycle_states"]   = entity.lifecycle_states
    except Exception:
        pass

    # Pin canonical entity/metric definitions once so every phase uses the same
    # identifiers/expressions (prevents figures drifting between phases).
    try:
        from aughor.agent.explore import build_analysis_ledger
        analysis_ledger = build_analysis_ledger(state)
    except Exception:
        analysis_ledger = ""

    return {
        "investigation_phases": [phase],
        "_ada_intake": intake_dict,
        "analysis_ledger": analysis_ledger,
    }


# ── Premise direction helpers ─────────────────────────────────────────────────

_QUESTION_DOWN_RE = re.compile(
    r'\b(drop|dropped|decline|declined|fell|fall|falls|decrease|decreased|down|lower|'
    r'loss|lost|shrink|shrank|worse|worsening|underperform|underperforming|slow|slowed|slowing)\b',
    re.IGNORECASE,
)
_QUESTION_UP_RE = re.compile(
    r'\b(rise|rose|risen|increase|increased|grew|grow|growth|jump|jumped|surge|surged|'
    r'up|higher|improve|improved|gain|gained|spike|spiked|accelerat)\b',
    re.IGNORECASE,
)


def _detect_question_direction(question: str) -> Optional[str]:
    """Return 'down' if question implies a drop, 'up' if it implies a rise, else None."""
    if _QUESTION_DOWN_RE.search(question):
        return "down"
    if _QUESTION_UP_RE.search(question):
        return "up"
    return None


@_telemetry.node_span("ada_baseline")
def ada_baseline(state: AgentState, conn: "DatabaseConnection") -> dict:
    """
    Phase 2 — Baseline & Anomaly Assessment.
    Confirms the anomaly is real and statistically significant.
    """
    from aughor.agent.prompts_investigate import (
        BASELINE_PLAN_PROMPT,
        BASELINE_INTERPRET_PROMPT,
        PhasePlan,
        PhaseInterpretation,
    )

    question = state["question"]
    intake_data = state.get("_ada_intake") or {}
    schema = _with_ledger(state, intake_data.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT))
    events = state.get("events_context") or ""
    events_section = f"BUSINESS CALENDAR:\n{events}\n" if events else ""
    phases = state.get("investigation_phases", [])
    metric_label = intake_data.get("metric_label", "the core metric")
    metric_sql = intake_data.get("metric_sql", "SUM(revenue)")
    obs_start = intake_data.get("observation_start", "")
    obs_end = intake_data.get("observation_end", "")
    obs_label = intake_data.get("observation_label", "the observation period")
    comp_start = intake_data.get("comparison_start", "")
    comp_end = intake_data.get("comparison_end", "")
    comp_label = intake_data.get("comparison_label", "the comparison period")
    date_col = intake_data.get("date_column", "")
    metric_table = intake_data.get("metric_table", "")

    # Step 1: Plan SQL
    plan_prompt = BASELINE_PLAN_PROMPT.format(
        question=question,
        metric_label=metric_label,
        metric_sql=metric_sql,
        observation_period=f"{obs_label} ({obs_start} to {obs_end})",
        comparison_basis=f"{comp_label} ({comp_start} to {comp_end})",
        date_column=date_col,
        metric_table=metric_table,
        schema=schema,
        events_section=events_section,
    )
    # Append ontology entity context if available
    active_filter   = intake_data.get("active_filter")
    lifecycle_col   = intake_data.get("lifecycle_column")
    terminal_states = intake_data.get("terminal_states") or []
    if active_filter or lifecycle_col:
        lines = ["\nONTOLOGY ENTITY CONTEXT (auto-derived — treat as authoritative):"]
        if active_filter:
            lines.append(
                f"  active_filter: {active_filter}\n"
                "  ↳ ALWAYS apply this filter to every query on the metric table "
                "unless you are explicitly counting terminal/inactive rows."
            )
        if lifecycle_col and terminal_states:
            lines.append(
                f"  lifecycle_column: {lifecycle_col}"
                f"  terminal_states: {terminal_states}\n"
                "  ↳ When computing active counts, exclude rows whose "
                f"{lifecycle_col} is in {terminal_states}."
            )
        plan_prompt += "\n".join(lines)
    try:
        plan: PhasePlan = _provider("coder").complete(
            system="Write SQL queries for baseline anomaly detection. Return a JSON object with a 'queries' list.",
            user=plan_prompt,
            response_model=PhasePlan,
        )
    except Exception as e:
        phase = _phase_result(
            "baseline", "Baseline & Anomaly Assessment", "📊", "error",
            "Could not plan baseline queries.",
            [_skipped_finding("baseline", str(e))],
        )
        return {"investigation_phases": phases + [phase]}

    # Step 2: Execute (parallel — each query gets its own reader connection)
    results = _parallel_execute_safe(conn, "baseline", plan.queries, cap=4)

    if not results:
        phase = _phase_result(
            "baseline", "Baseline & Anomaly Assessment", "📊", "error",
            "All baseline queries failed to execute.",
            [_skipped_finding("baseline", "No queries produced results.")],
        )
        return {"investigation_phases": phases + [phase]}

    # Step 3: Interpret
    results_text = _results_to_text([r for _, r in results])
    interpret_prompt = BASELINE_INTERPRET_PROMPT.format(
        question=question,
        results_text=results_text,
        events_section=events_section,
        z_threshold=2.0,
        pct_threshold=10,
    )
    try:
        interpretation: PhaseInterpretation = _provider("narrator").complete(
            system="You are a senior data analyst interpreting query results. Be precise. Cite real numbers.",
            user=interpret_prompt,
            response_model=PhaseInterpretation,
        )
    except Exception as e:
        interpretation = None

    # ── Stats.py: code-level significance check (runs before LLM interpretation) ──
    # Compute z-score on the baseline time series. The LLM is asked to compute
    # the same thing in SQL, but this gives us a deterministic Python-level gate
    # that the router can trust unconditionally.
    code_sigma: Optional[float] = None
    code_significant: Optional[bool] = None
    for _, r in results:
        if r.error or not r.rows or not r.columns:
            continue
        stat_results = analyze_query_result(r.columns, r.rows)
        for sr in stat_results:
            if sr.sigma is not None:
                if code_sigma is None or sr.sigma > code_sigma:
                    code_sigma = sr.sigma
        if code_sigma is not None:
            code_significant = code_sigma >= 2.0
            break  # first successful result is enough

    if interpretation and interpretation.findings:
        findings = [
            _finding_from_result_and_model(
                f"baseline_{i}", r, interpretation.findings[min(i, len(interpretation.findings) - 1)],
                q.chart_type,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = interpretation.phase_summary
        passes_to_next = interpretation.passes_to_next
        # If stats.py couldn't compute sigma, fall back to LLM's is_significant flags
        if code_significant is None:
            code_significant = any(f["is_significant"] for f in findings)
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"baseline_{i}",
                title=q.title,
                sql=r.sql,
                columns=r.columns,
                rows=r.rows[:50],
                row_count=r.row_count,
                error=r.error,
                interpretation=f"Query executed: {r.row_count} rows returned." if not r.error else r.error,
                key_numbers=[],
                chart_type=q.chart_type,
                stat_note=None,
                is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = f"Baseline computed for {obs_label}."
        passes_to_next = summary
        if code_significant is None:
            code_significant = True  # unknown → assume significant, don't block

    # Append sigma note to summary if available
    if code_sigma is not None:
        sig_label = "significant anomaly" if code_significant else "within normal variance"
        summary = f"{summary} [stats.py: σ={code_sigma:.2f} — {sig_label}]"

    # ── Premise validation: detect when observation period contradicts the question's intent ──
    # e.g. question asks "why did revenue DROP?" but obs period actually showed a rise.
    # Strategy: fire ONE three-way SQL (obs vs comp vs prior) to determine actual directions.
    # If obs vs comp contradicts question intent but comp vs prior confirms it → redirect.
    updated_intake = None
    try:
        expected_dir = _detect_question_direction(question)
        if expected_dir is not None and obs_start and obs_end and comp_start and comp_end:
            from datetime import date, timedelta
            cs_dt = date.fromisoformat(comp_start[:10])
            ce_dt = date.fromisoformat(comp_end[:10])
            # Prior period = same span as comp period, immediately before it
            period_days = (ce_dt - cs_dt).days  # e.g. Feb: 27 days (Feb1→Feb28 span-1)
            prior_end_dt = cs_dt - timedelta(days=1)
            prior_start_dt = prior_end_dt - timedelta(days=period_days)
            prior_start = prior_start_dt.isoformat()
            prior_end = prior_end_dt.isoformat()

            # Single query: returns obs_value, comp_value, prior_value
            three_way_sql = (
                f"SELECT "
                f"  SUM(CASE WHEN CAST({date_col} AS DATE) >= DATE '{obs_start}' "
                f"           AND CAST({date_col} AS DATE) <= DATE '{obs_end}' "
                f"      THEN {metric_sql} ELSE 0 END) AS obs_value, "
                f"  SUM(CASE WHEN CAST({date_col} AS DATE) >= DATE '{comp_start}' "
                f"           AND CAST({date_col} AS DATE) <= DATE '{comp_end}' "
                f"      THEN {metric_sql} ELSE 0 END) AS comp_value, "
                f"  SUM(CASE WHEN CAST({date_col} AS DATE) >= DATE '{prior_start}' "
                f"           AND CAST({date_col} AS DATE) <= DATE '{prior_end}' "
                f"      THEN {metric_sql} ELSE 0 END) AS prior_value "
                f"FROM {metric_table}"
            )
            # Apply ontology active filter if available (same as baseline queries)
            active_filter = intake_data.get("active_filter")
            if active_filter:
                three_way_sql += f" WHERE {active_filter}"

            val_result = _execute_safe(conn, "premise_check", three_way_sql)
            if (not val_result.error and val_result.rows
                    and len(val_result.rows[0]) >= 3):
                row = val_result.rows[0]
                try:
                    obs_v = float(row[0] or 0)
                    comp_v = float(row[1] or 0)
                    prior_v = float(row[2] or 0)

                    if comp_v == 0 or obs_v == comp_v:
                        raise ValueError("degenerate values — skip")

                    # Direction obs period actually moved vs comparison
                    obs_dir = "up" if obs_v > comp_v else "down"

                    if obs_dir != expected_dir and prior_v != 0:
                        # Mismatch: obs period moved opposite to question intent.
                        # Check if comp period shows the expected direction vs prior.
                        comp_dir = "down" if comp_v < prior_v else "up"
                        if comp_dir == expected_dir:
                            actual_obs_pct = (obs_v - comp_v) / abs(comp_v) * 100
                            redirect_pct = (comp_v - prior_v) / abs(prior_v) * 100
                            direction_word = "drop" if expected_dir == "down" else "rise"
                            correction_note = (
                                f"Your question asked about a {direction_word} in {obs_label}, "
                                f"but that period actually showed a "
                                f"{'rise' if expected_dir == 'down' else 'drop'} "
                                f"({actual_obs_pct:+.1f}%). "
                                f"The actual {direction_word} occurred in {comp_label} "
                                f"({redirect_pct:+.1f}% vs prior period "
                                f"{prior_start} → {prior_end}). "
                                f"Investigation re-anchored to this window."
                            )
                            # Prepend a prominent correction finding
                            correction_finding = InvestigationFinding(
                                finding_id="premise_correction",
                                title=f"⚠️ Window Corrected — actual {direction_word} is in {comp_label}",
                                sql=three_way_sql,
                                columns=["obs_value", "comp_value", "prior_value"],
                                rows=[[obs_v, comp_v, prior_v]],
                                row_count=1,
                                error=None,
                                interpretation=correction_note,
                                key_numbers=[
                                    PhaseKeyNumber(
                                        label=f"{comp_label} (re-anchored window)",
                                        value=f"{comp_v:,.0f}",
                                        delta=f"{redirect_pct:+.1f}%",
                                        context=f"vs prior period {prior_start} → {prior_end}",
                                    ),
                                ],
                                chart_type="none",
                                stat_note=None,
                                is_significant=True,
                            )
                            findings = [correction_finding] + findings
                            summary = f"⚠️ {correction_note} | {summary}"
                            passes_to_next = correction_note + " " + passes_to_next

                            # Update _ada_intake so all downstream phases use correct periods
                            updated_intake = dict(intake_data)
                            updated_intake["observation_start"] = comp_start
                            updated_intake["observation_end"] = comp_end
                            updated_intake["observation_label"] = comp_label
                            updated_intake["comparison_start"] = prior_start
                            updated_intake["comparison_end"] = prior_end
                            updated_intake["comparison_label"] = (
                                f"Prior period ({prior_start} → {prior_end})"
                            )
                            updated_intake["_premise_corrected"] = True
                            updated_intake["_premise_correction_note"] = correction_note
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
    except Exception:
        pass  # Premise check is best-effort — never crash the pipeline

    phase = _phase_result(
        "baseline", "Baseline & Anomaly Assessment", "📊",
        "complete" if any(not f["error"] for f in findings) else "partial",
        summary, findings,
    )
    ret: dict = {
        "investigation_phases": phases + [phase],
        "_baseline_summary": summary,
        "_baseline_passes": passes_to_next,
        "_baseline_significant": code_significant,
        "_baseline_sigma": code_sigma,
    }
    if updated_intake is not None:
        ret["_ada_intake"] = updated_intake
    return ret


@_telemetry.node_span("ada_decompose")
def ada_decompose(state: AgentState, conn: "DatabaseConnection") -> dict:
    """
    Phase 3 — Metric Decomposition.
    Splits the metric into sub-drivers (volume vs value, new vs returning, etc.)
    """
    from aughor.agent.prompts_investigate import (
        DECOMPOSE_PLAN_PROMPT, DECOMPOSE_INTERPRET_PROMPT,
        PhasePlan, PhaseInterpretation,
    )

    question = state["question"]
    intake_data = state.get("_ada_intake") or {}
    schema = _with_ledger(state, intake_data.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT))
    phases = state.get("investigation_phases", [])
    baseline_summary = state.get("_baseline_summary", "Baseline established.")

    metric_label = intake_data.get("metric_label", "the metric")
    metric_sql = intake_data.get("metric_sql", "SUM(revenue)")
    obs_start = intake_data.get("observation_start", "")
    obs_end = intake_data.get("observation_end", "")
    obs_label = intake_data.get("observation_label", "observation period")
    comp_start = intake_data.get("comparison_start", "")
    comp_end = intake_data.get("comparison_end", "")
    date_col = intake_data.get("date_column", "")
    metric_table = intake_data.get("metric_table", "")

    plan_prompt = DECOMPOSE_PLAN_PROMPT.format(
        question=question,
        baseline_summary=baseline_summary,
        total_change="(see baseline findings)",
        metric_label=metric_label,
        metric_sql=metric_sql,
        observation_period=obs_label,
        obs_start=obs_start,
        obs_end=obs_end,
        comp_start=comp_start,
        comp_end=comp_end,
        date_column=date_col,
        metric_table=metric_table,
        schema=schema,
    )
    try:
        plan: PhasePlan = _provider("coder").complete(
            system="Write SQL for metric decomposition. Decompose the metric into additive sub-drivers.",
            user=plan_prompt,
            response_model=PhasePlan,
        )
    except Exception as e:
        phase = _phase_result(
            "decomposition", "Metric Decomposition", "🧩", "error",
            "Could not plan decomposition queries.",
            [_skipped_finding("decomposition", str(e))],
        )
        return {"investigation_phases": phases + [phase]}

    results = _parallel_execute_safe(conn, "decomposition", plan.queries, cap=4)

    if not results:
        phase = _phase_result(
            "decomposition", "Metric Decomposition", "🧩", "error",
            "Decomposition queries failed.",
            [_skipped_finding("decomposition", "No results.")],
        )
        return {"investigation_phases": phases + [phase]}

    results_text = _results_to_text([r for _, r in results])
    prior_summary = f"Baseline: {baseline_summary}"
    interpret_prompt = DECOMPOSE_INTERPRET_PROMPT.format(
        question=question,
        baseline_summary=baseline_summary,
        results_text=results_text,
    )
    try:
        interpretation: PhaseInterpretation = _provider("narrator").complete(
            system="Interpret metric decomposition results. State clearly whether volume or value drove the change.",
            user=interpret_prompt,
            response_model=PhaseInterpretation,
        )
    except Exception:
        interpretation = None

    if interpretation and interpretation.findings:
        findings = [
            _finding_from_result_and_model(
                f"decomp_{i}", r, interpretation.findings[min(i, len(interpretation.findings) - 1)],
                q.chart_type,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = interpretation.phase_summary
        passes_to_next = interpretation.passes_to_next
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"decomp_{i}", title=q.title, sql=r.sql,
                columns=r.columns, rows=r.rows[:50], row_count=r.row_count,
                error=r.error, interpretation="Query executed.",
                key_numbers=[], chart_type=q.chart_type,
                stat_note=None, is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = "Metric decomposition complete."
        passes_to_next = summary

    phase = _phase_result(
        "decomposition", "Metric Decomposition", "🧩",
        "complete" if any(not f["error"] for f in findings) else "partial",
        summary, findings,
    )
    return {
        "investigation_phases": phases + [phase],
        "_decomp_summary": summary,
        "_decomp_passes": passes_to_next,
    }


@_telemetry.node_span("ada_dimensional")
def ada_dimensional(state: AgentState, conn: "DatabaseConnection") -> dict:
    """
    Phase 4 — Dimensional Drill-Down.
    Contribution analysis: WHERE did the change concentrate?
    """
    from aughor.agent.prompts_investigate import (
        DIMENSIONAL_PLAN_PROMPT, DIMENSIONAL_INTERPRET_PROMPT,
        PhasePlan, PhaseInterpretation,
    )

    question = state["question"]
    intake_data = state.get("_ada_intake") or {}
    schema = _with_ledger(state, intake_data.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT))
    phases = state.get("investigation_phases", [])

    metric_label = intake_data.get("metric_label", "the metric")
    metric_sql = intake_data.get("metric_sql", "SUM(revenue)")
    obs_start = intake_data.get("observation_start", "")
    obs_end = intake_data.get("observation_end", "")
    obs_label = intake_data.get("observation_label", "observation period")
    comp_start = intake_data.get("comparison_start", "")
    comp_end = intake_data.get("comparison_end", "")
    date_col = intake_data.get("date_column", "")
    metric_table = intake_data.get("metric_table", "")
    dimensions = intake_data.get("dimensions", [])

    baseline_summary = state.get("_baseline_summary", "")
    decomp_summary = state.get("_decomp_summary", "")
    prior_summary = f"Baseline: {baseline_summary}\nDecomposition: {decomp_summary}"

    # Sort dimensions by spec-mandated priority: customer → channel → category → geo
    # This ensures the LLM picks the analytically highest-value dimensions first.
    prioritized_dims = _prioritize_dimensions(dimensions)
    dimensions_list = "\n".join(
        f"  - {d}" for d in prioritized_dims[:8]
    ) if prioritized_dims else "  (none identified)"

    plan_prompt = DIMENSIONAL_PLAN_PROMPT.format(
        question=question,
        baseline_summary=baseline_summary,
        decomposition_summary=decomp_summary,
        metric_label=metric_label,
        metric_sql=metric_sql,
        observation_period=obs_label,
        obs_start=obs_start,
        obs_end=obs_end,
        comp_start=comp_start,
        comp_end=comp_end,
        date_column=date_col,
        metric_table=metric_table,
        schema=schema,
        dimensions_list=dimensions_list,
    )
    try:
        plan: PhasePlan = _provider("coder").complete(
            system="Write contribution-analysis SQL for each dimension. Sort by absolute_change ASC.",
            user=plan_prompt,
            response_model=PhasePlan,
        )
    except Exception as e:
        phase = _phase_result(
            "dimensional", "Dimensional Analysis", "🔬", "error",
            "Could not plan dimensional queries.",
            [_skipped_finding("dimensional", str(e))],
        )
        return {"investigation_phases": phases + [phase]}

    results = _parallel_execute_safe(conn, "dimensional", plan.queries, cap=4)

    if not results:
        phase = _phase_result(
            "dimensional", "Dimensional Analysis", "🔬", "error",
            "Dimensional queries failed.",
            [_skipped_finding("dimensional", "No results.")],
        )
        return {"investigation_phases": phases + [phase]}

    results_text = _results_to_text([r for _, r in results])
    interpret_prompt = DIMENSIONAL_INTERPRET_PROMPT.format(
        question=question,
        prior_summary=prior_summary,
        results_text=results_text,
    )
    try:
        interpretation: PhaseInterpretation = _provider("narrator").complete(
            system="Interpret contribution analysis. Identify concentrated vs. diffuse decline.",
            user=interpret_prompt,
            response_model=PhaseInterpretation,
        )
    except Exception:
        interpretation = None

    if interpretation and interpretation.findings:
        findings = [
            _finding_from_result_and_model(
                f"dim_{i}", r, interpretation.findings[min(i, len(interpretation.findings) - 1)],
                q.chart_type,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = interpretation.phase_summary
        passes_to_next = interpretation.passes_to_next
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"dim_{i}", title=q.title, sql=r.sql,
                columns=r.columns, rows=r.rows[:50], row_count=r.row_count,
                error=r.error, interpretation="Query executed.",
                key_numbers=[], chart_type=q.chart_type,
                stat_note=None, is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = "Dimensional analysis complete."
        passes_to_next = summary

    phase = _phase_result(
        "dimensional", "Dimensional Analysis", "🔬",
        "complete" if any(not f["error"] for f in findings) else "partial",
        summary, findings,
    )
    return {
        "investigation_phases": phases + [phase],
        "_dimensional_summary": summary,
        "_dimensional_passes": passes_to_next,
    }


@_telemetry.node_span("ada_behavioral")
def ada_behavioral(state: AgentState, conn: "DatabaseConnection") -> dict:
    """
    Phase 5+6 — Behavioral & Operational Diagnostics.
    WHO changed behaviour + WHAT changed operationally.
    """
    from aughor.agent.prompts_investigate import (
        BEHAVIORAL_PLAN_PROMPT, BEHAVIORAL_INTERPRET_PROMPT,
        PhasePlan, PhaseInterpretation,
    )

    question = state["question"]
    intake_data = state.get("_ada_intake") or {}
    schema = _with_ledger(state, intake_data.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT))
    phases = state.get("investigation_phases", [])
    events = state.get("events_context") or ""
    events_section = f"BUSINESS CALENDAR:\n{events}\n" if events else ""

    metric_label = intake_data.get("metric_label", "the metric")
    metric_sql = intake_data.get("metric_sql", "SUM(revenue)")
    obs_start = intake_data.get("observation_start", "")
    obs_end = intake_data.get("observation_end", "")
    obs_label = intake_data.get("observation_label", "observation period")
    comp_start = intake_data.get("comparison_start", "")
    comp_end = intake_data.get("comparison_end", "")
    date_col = intake_data.get("date_column", "")
    metric_table = intake_data.get("metric_table", "")

    prior_summary = " | ".join(filter(None, [
        state.get("_baseline_summary", ""),
        state.get("_decomp_summary", ""),
        state.get("_dimensional_summary", ""),
    ]))

    # Dominant finding from Tier 2: the `passes_to_next` string from dimensional
    # interpretation carries the most concentrated finding (e.g. "channel=mobile
    # accounts for 68% of the order drop"). Injecting this makes Tier-3 queries
    # targeted instead of running the same generic checklist every time.
    dominant_finding = (
        state.get("_dimensional_passes")
        or state.get("_dimensional_summary")
        or "No specific segment concentration identified — run broad diagnostics."
    )

    plan_prompt = BEHAVIORAL_PLAN_PROMPT.format(
        question=question,
        prior_summary=prior_summary,
        dominant_finding=dominant_finding,
        metric_label=metric_label,
        metric_sql=metric_sql,
        observation_period=obs_label,
        obs_start=obs_start,
        obs_end=obs_end,
        comp_start=comp_start,
        comp_end=comp_end,
        date_column=date_col,
        metric_table=metric_table,
        schema=schema,
        events_section=events_section,
    )
    try:
        plan: PhasePlan = _provider("coder").complete(
            system="Write SQL for behavioral and operational diagnostics.",
            user=plan_prompt,
            response_model=PhasePlan,
        )
    except Exception as e:
        phase = _phase_result(
            "behavioral", "Behavioral & Operational", "👥", "error",
            "Could not plan behavioral queries.",
            [_skipped_finding("behavioral", str(e))],
        )
        return {"investigation_phases": phases + [phase]}

    results = _parallel_execute_safe(conn, "behavioral", plan.queries, cap=4)

    if not results:
        phase = _phase_result(
            "behavioral", "Behavioral & Operational", "👥", "skipped",
            "Behavioral/operational tables not available in this schema.",
            [_skipped_finding("behavioral", "Required tables (sessions, refunds, etc.) not in schema.")],
        )
        return {"investigation_phases": phases + [phase]}

    results_text = _results_to_text([r for _, r in results])
    interpret_prompt = BEHAVIORAL_INTERPRET_PROMPT.format(
        question=question,
        prior_summary=prior_summary,
        results_text=results_text,
    )
    try:
        interpretation: PhaseInterpretation = _provider("narrator").complete(
            system="Interpret behavioral and operational findings. Be specific about what changed.",
            user=interpret_prompt,
            response_model=PhaseInterpretation,
        )
    except Exception:
        interpretation = None

    if interpretation and interpretation.findings:
        findings = [
            _finding_from_result_and_model(
                f"beh_{i}", r, interpretation.findings[min(i, len(interpretation.findings) - 1)],
                q.chart_type,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = interpretation.phase_summary
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"beh_{i}", title=q.title, sql=r.sql,
                columns=r.columns, rows=r.rows[:50], row_count=r.row_count,
                error=r.error, interpretation="Query executed.",
                key_numbers=[], chart_type=q.chart_type,
                stat_note=None, is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = "Behavioral and operational analysis complete."

    phase = _phase_result(
        "behavioral", "Behavioral & Operational", "👥",
        "complete" if any(not f["error"] for f in findings) else "partial",
        summary, findings,
    )
    return {
        "investigation_phases": phases + [phase],
        "_behavioral_summary": summary,
    }


@_telemetry.node_span("ada_synthesize")
def ada_synthesize(state: AgentState) -> dict:
    """
    Phase 8 — Synthesis: Attribution Waterfall + Recommendations.
    Assembles all phase findings into an ADAReport.
    """
    from aughor.agent.prompts_investigate import ADA_SYNTHESIZE_PROMPT, ADASynthesisModel
    from aughor.agent.state import ADAReport, WaterfallEntry, ADARecommendation

    question = state["question"]
    phases = state.get("investigation_phases", [])
    events = state.get("events_context") or ""
    events_section = f"BUSINESS CALENDAR:\n{events}\n" if events else ""
    intake_data = state.get("_ada_intake") or {}

    # Detect early-stop: if only baseline (and intake) phases exist, the Tier-0
    # gate fired and we should label this as a "no anomaly" report.
    phase_ids = {p["phase_id"] for p in phases}
    early_stop = phase_ids <= {"intake", "baseline"}
    sigma = state.get("_baseline_sigma")
    early_stop_note = ""
    if early_stop:
        sigma_str = f" (z={sigma:.2f})" if sigma is not None else ""
        early_stop_note = (
            f"\n\nNOTE: The investigation stopped at Tier 0{sigma_str}. "
            "The observed change is within normal historical variance — no anomaly was detected. "
            "Your headline, executive_summary, and waterfall should reflect this: "
            "explain that the change is consistent with typical fluctuation, not a new problem. "
            "Set confidence by EVIDENCE QUALITY, not by the fact that you stopped early: HIGH only "
            "if the baseline queries actually returned data across the comparison periods; if "
            "queries errored or returned zero rows, you could not measure anything and confidence "
            "must be LOW. recommendations should be empty or advisory only."
        )

    phases_summary = _phases_summary(phases)
    evidence_log = _phases_evidence(phases)

    # ── Cross-phase contradiction detection ───────────────────────────────────
    # Before synthesis, deterministically check phase summaries for contradictions.
    # Example: baseline says "significant drop (z=-2.4)" while dimensional says
    # "no segment deviates from baseline" — the synthesizer must not silently paper
    # over this.  We inject any contradictions as a hard instruction in the prompt.
    contradiction_section = _detect_phase_contradictions(phases)

    # Build metric targets block for synthesis guidance
    metric_targets_section = ""
    try:
        from aughor.semantic.metrics import list_metrics
        targeted = [m for m in list_metrics() if m.target_value is not None]
        if targeted:
            lines = ["METRIC TARGETS (compare findings against these benchmarks):"]
            for m in targeted:
                parts = [f"  {m.label}: target={m.target_value}{' ' + m.unit if m.unit else ''}"]
                if m.warning_threshold is not None:
                    parts.append(f"warning>={m.warning_threshold}")
                if m.critical_threshold is not None:
                    parts.append(f"critical>={m.critical_threshold}")
                if m.benchmark_source:
                    parts.append(f"source: {m.benchmark_source}")
                lines.append(", ".join(parts))
            metric_targets_section = "\n".join(lines) + "\n"
    except Exception:
        pass

    # Build playbook section — match playbook entries against this investigation's context
    playbook_section = ""
    try:
        from aughor.playbook.retriever import (
            retrieve_for_metric_and_phases,
            build_playbook_prompt_section,
            build_causal_playbook_section,
        )
        labels: list[str] = []
        if intake_data.get("metric_label"):
            labels.append(intake_data["metric_label"])
        for phase in phases:
            if phase.get("title"):
                labels.append(phase["title"])
        labels.append(question)
        matched = retrieve_for_metric_and_phases(labels, limit=5)
        causal_section = build_causal_playbook_section(question, conn_id=state.get("connection_id", ""))
        playbook_section = causal_section + build_playbook_prompt_section(matched)
    except Exception:
        pass

    # Build external context section from uploaded documents
    external_context_section = ""
    try:
        from aughor.knowledge.indexer import build_external_context_section
        external_context_section = build_external_context_section(question, top_k=4)
    except Exception:
        pass

    # Build org-wide intelligence section from promoted canvas insights
    org_intelligence_section = ""
    try:
        from aughor.knowledge.org_intelligence import build_org_intelligence_section
        org_intelligence_section = build_org_intelligence_section(question, top_k=5)
    except Exception:
        pass

    synth_prompt = ADA_SYNTHESIZE_PROMPT.format(
        question=question,
        phases_summary=phases_summary,
        evidence_log=evidence_log[:6000],
        events_section=events_section,
        metric_targets_section=metric_targets_section,
        playbook_section=playbook_section,
        org_intelligence_section=org_intelligence_section,
        external_context_section=external_context_section,
    ) + contradiction_section + early_stop_note
    try:
        synth: ADASynthesisModel = _provider("narrator").complete(
            system=(
                "You are a senior data analyst writing a board-level investigation report. "
                "Every number must trace to the evidence log. No fabrication. "
                "Be definitive where evidence is strong; honest about uncertainty where it isn't."
            ),
            user=synth_prompt,
            response_model=ADASynthesisModel,
        )
    except Exception as e:
        synth = None

    # Save causal proposals from this investigation (outcome-gated promotion)
    inv_id = state.get("investigation_id") or ""
    conn_id = state.get("connection_id") or ""
    if synth and inv_id and hasattr(synth, "causal_links") and synth.causal_links:
        try:
            from aughor.process.causal import CausalProposal, save_proposals
            proposals = [
                CausalProposal(
                    from_signal=cl.from_signal,
                    to_signal=cl.to_signal,
                    from_entity=cl.from_entity,
                    to_entity=cl.to_entity,
                    confidence=cl.confidence,
                    inv_id=inv_id,
                    conn_id=conn_id,
                )
                for cl in synth.causal_links
            ]
            save_proposals(inv_id, proposals)
        except Exception:
            pass

    # ── Honest confidence floor ───────────────────────────────────────────────
    # A run that gathered no usable data can never be HIGH/MEDIUM confidence,
    # regardless of what the synthesis LLM claimed.
    if synth:
        _all_f = [f for p in phases for f in (p.get("findings") or [])]
        _with_data = [f for f in _all_f if not f.get("error") and (f.get("columns") or [])]
        if not _with_data:
            synth.confidence = "LOW"
            synth.confidence_justification = (
                "No usable data was gathered — every query errored or returned zero rows, so no "
                "finding can be confirmed. " + (synth.confidence_justification or "")
            ).strip()

    def _coerce_amount_sign(label: str, pct: float) -> str:
        """Keep a waterfall amount_label's leading sign in agreement with its
        pct_of_total, so the two never render with opposite directions."""
        s = (label or "").strip()
        if not s:
            return s
        core = re.sub(r"^[+\-]\s*", "", s)
        return ("-" + core) if pct < 0 else core

    if synth:
        waterfall = [
            WaterfallEntry(
                cause=w.cause,
                amount_label=_coerce_amount_sign(w.amount_label, w.pct_of_total),
                pct_of_total=w.pct_of_total,
                controllable=w.controllable,
                structural=w.structural,
            )
            for w in synth.attribution_waterfall
        ]
        recommendations = [
            ADARecommendation(
                action=r.action,
                expected_impact=r.expected_impact,
                owner=r.owner,
                timeline=r.timeline,
            )
            for r in synth.recommendations
        ]
        ada_report = ADAReport(
            headline=synth.headline,
            executive_summary=synth.executive_summary,
            metric=intake_data.get("metric_label", ""),
            observation_period=intake_data.get("observation_label", ""),
            comparison_basis=intake_data.get("comparison_label", ""),
            total_change_label=synth.total_change_label,
            phases=phases,
            attribution_waterfall=waterfall,
            confidence=synth.confidence,
            confidence_justification=synth.confidence_justification,
            recommendations=recommendations,
            data_gaps=synth.data_gaps,
        )
    else:
        ada_report = ADAReport(
            headline="Investigation complete — synthesis failed.",
            executive_summary="See individual phase findings above for details.",
            metric=intake_data.get("metric_label", ""),
            observation_period=intake_data.get("observation_label", ""),
            comparison_basis=intake_data.get("comparison_label", ""),
            total_change_label="",
            phases=phases,
            attribution_waterfall=[],
            confidence="LOW",
            confidence_justification="Synthesis LLM call failed.",
            recommendations=[],
            data_gaps=[],
        )

    # Also produce a legacy AnalysisReport for backward compat (history, cache)
    from aughor.agent.state import AnalysisReport, Finding
    legacy_findings = []
    for p in phases:
        for f in p["findings"]:
            if f["interpretation"] and not f["error"]:
                legacy_findings.append(Finding(
                    claim=f["title"],
                    evidence=f["interpretation"][:300],
                    confidence=0.8 if f["is_significant"] else 0.5,
                    hypothesis_id=p["phase_id"],
                ))
    legacy_report = AnalysisReport(
        headline=ada_report["headline"],
        verdict=ada_report["executive_summary"],
        key_findings=legacy_findings[:5],
        what_is_not_the_cause=[g for g in ada_report["data_gaps"]],
        risks=[r["action"] for r in ada_report["recommendations"][:2]],
        recommended_actions=[r["action"] for r in ada_report["recommendations"]],
    )

    # ── Persist evidence claims to the ledger ────────────────────────────────
    investigation_id = state.get("investigation_id") or ""
    if investigation_id:
        try:
            from datetime import datetime, timezone
            from aughor.evidence.linker import (
                extract_claims_from_ada_phases,
                extract_claims_from_report,
            )
            from aughor.evidence import store as _ev_store

            completed_ts = datetime.now(timezone.utc).isoformat()

            # Prefer ADA phases (richer provenance — has per-finding SQL)
            if phases:
                claims = extract_claims_from_ada_phases(
                    investigation_id=investigation_id,
                    phases=phases,
                    completed_at=completed_ts,
                )
            else:
                qh = [qr.model_dump() if hasattr(qr, "model_dump") else dict(qr)
                      for qr in (state.get("query_history") or [])]
                claims = extract_claims_from_report(
                    investigation_id=investigation_id,
                    report=legacy_report,
                    query_history=qh,
                    completed_at=completed_ts,
                )

            for claim in claims:
                _ev_store.append_claim(claim)

        except Exception:
            pass  # evidence ledger is non-critical — never break the investigation

    return {
        "ada_report": ada_report,
        "report": legacy_report,
        "investigation_phases": phases,
    }
