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
    InvestigationFinding,
    InvestigationPhaseResult,
    PhaseKeyNumber,
)
from aughor.tools.executor import format_result_for_llm
from aughor.agent.progress import emit_phase_progress
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

# Causal / diagnostic dimensions (return reason, item condition, defect, fit, …). For an outcome
# question — "why is X high/low" — these ARE the answer, yet the descriptive taxonomy above buries
# them in "other" (rank 6) where the per-phase query cap truncates them before the scan reaches them.
# When the caller flags a causal scan we float them AHEAD of the descriptive population dims so the
# WHERE scan covers the differentiators, not brand/tier. (Event-TABLE dims — return reason living on a
# returns table — are peeled off separately into a composition/WHY lens; see `_causal_split`.)
_CAUSAL_DIMENSION_KEYWORDS: list[str] = [
    "reason", "cause", "condition", "driver", "fault", "defect", "damage",
    "quality", "fit", "status", "issue", "complaint", "root_cause",
]

# Operational / logistics event dimensions — WHO shipped the return, HOW it was refunded. These live
# on the event table (so they'd tautologically rate to 100%) but, unlike a return *reason*, they are
# downstream ops metadata, NOT a cause of the elevated event rate. A "why is X high" composition should
# not lead with — or clutter itself with — them (the womenswear WHY came back with 4 pies, 3 of them
# ops noise: carrier/refund_method scored non-significant). Kept distinct from the causal vocabulary.
_OPERATIONAL_DIMENSION_KEYWORDS: list[str] = [
    "carrier", "courier", "shipping", "ship_method", "shipment", "tracking",
    "refund_method", "payment_method", "warehouse", "logistics", "fulfillment",
]


def _prioritize_dimensions(dimensions: list[str], causal_first: bool = False) -> list[str]:
    """Sort dimensions by spec-mandated priority: customer → channel → category → geo → other. When
    ``causal_first`` (an outcome / 'why is X high/low' scan) diagnostic dimensions
    (reason/condition/defect/…) float to the FRONT — for those questions the causal dimension is the
    answer, not an afterthought, so it must survive the per-phase query cap."""
    def _rank(dim: str) -> int:
        dl = dim.lower()
        if causal_first and any(kw in dl for kw in _CAUSAL_DIMENSION_KEYWORDS):
            return -1
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


def route_after_intake(state: AgentState) -> str:
    """Diagnostic / cross-sectional questions (where-which-is-weakest, or no usable
    time axis) skip the temporal baseline and go straight to the dimensional
    weakness scan; everything else takes the normal temporal path."""
    intake = state.get("_ada_intake") or {}
    return "ada_cross_section" if intake.get("cross_sectional") else "ada_baseline"


def route_after_intake_clarify(state: AgentState) -> str:
    """P4 clarify_gate: route intake through the clarify gate ONLY when ada_intake stashed a material
    metric ambiguity (`_clarify_pending`); otherwise the normal intake routing. The gate is a
    passthrough armed with `interrupt_before`, so reaching it pauses the run for the user's choice.
    With no pending clarify this is byte-identical to `route_after_intake`."""
    if state.get("_clarify_pending"):
        return "clarify_gate"
    return route_after_intake(state)


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

    # Decompose-under-abstention (fix 5): a "why did X change/decline/rise?" question presupposes a
    # real movement and asks for its CAUSE. If the aggregate moved materially (≥5% between the
    # series' earlier and later halves), run ONE dimensional pass even when the single-point anomaly
    # test is sub-threshold — offsetting or gradual segment moves are invisible in the aggregate, and
    # answering "it's just noise, here's everything I didn't look at" is the failure we're fixing.
    # A genuinely-flat series (immaterial move, e.g. the "did refunds spike?" false premise) still
    # stops cleanly below. route_after_decompose caps the cost at Tier 1 for non-dimensional questions.
    rel_change = state.get("_baseline_rel_change")
    if (_is_temporal_change_question(question) and rel_change is not None
            and abs(rel_change) >= 0.05 and not code_sig):
        from aughor.stats import stats as _s; _s.inc("tier0_decompose_on_why")
        return "ada_decompose"

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


def _build_grounded_schema(full_schema: str, metric_table: str, dimensions, date_column: str, question: str) -> str:
    """A JOIN-COMPLETE filtered schema for the ADA coder. Keeping only the metric +
    dimension tables drops the table that holds the date/join columns (revenue on
    `invoices`, the timestamp on `orders`), so the coder hallucinates a date column on
    the metric table. This keeps the metric + dimension tables, the date column's host
    table, FK-joinable neighbours, and temporal dimension tables, then appends the
    DETECTED JOIN PATHS hints (which _filter_schema strips) — what the /chat path does."""
    try:
        from aughor.tools.schema import parse_schema_tables
        # If the schema isn't TABLE:-format (e.g. an already-scoped Data Catalog from the
        # /investigate route), don't re-filter it — that would drop the FK-neighbour tables
        # the route already added. The route owns scoping in that case.
        if not parse_schema_tables(full_schema):
            return full_schema
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "grounded-schema format probe is advisory; fall through to manual "
                       "table filtering", counter="ada.schema_grounding")
    relevant = [metric_table] + [d.rsplit(".", 1)[0] for d in (dimensions or []) if "." in d]
    if date_column and "." in date_column:
        relevant.append(date_column.rsplit(".", 1)[0])
    relevant = list(dict.fromkeys(t for t in relevant if t))
    try:
        from aughor.tools.schema import fk_neighbor_expand, temporal_dimension_tables, infer_joins
        for dt in temporal_dimension_tables(full_schema, relevant, question or ""):
            if dt not in relevant:
                relevant.append(dt)
        relevant = fk_neighbor_expand(full_schema, relevant, cap=10)
        sch = _filter_schema(full_schema, relevant)
        hints = infer_joins(sch)
        return sch + "\n\n" + hints if hints else sch
    except Exception:
        return _filter_schema(full_schema, relevant)


_DATE_TYPE_RE = re.compile(r"\b(date|timestamp|datetime|time)\b", re.I)
_DATE_NAME_RE = re.compile(r"(_ts$|_at$|_date$|date|timestamp|created|updated|ordered|invoiced|shipped)", re.I)
_KEYISH_RE = re.compile(r"(_id|_key|_sk|_code|_num|_no)$", re.I)


def _typed_columns(schema: str) -> dict:
    """Parse a schema into {qualified_table: [(col, type), ...]}. Handles BOTH the
    TABLE: format and the Data Catalog markdown (## headers, `| col | type |` rows).
    Stops at each table's "Sample (N rows)" block so data rows aren't read as columns."""
    out: dict = {}
    cur = None
    for line in (schema or "").splitlines():
        h = re.match(r"^(?:TABLE:\s+|##\s+)([\w.]+)", line)
        if h:
            cur = h.group(1)
            out[cur] = []
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.lower().startswith("sample"):   # data-sample table — stop collecting columns
            cur = None
            continue
        mc = re.match(r"^\|\s*([A-Za-z_]\w*)\s*\|\s*([A-Za-z]\w*)", line)   # | col | TYPE | ...
        if mc:
            if mc.group(1).lower() != "column":
                out[cur].append((mc.group(1), mc.group(2)))
            continue
        cm = re.match(r"^\s{2}(\S+)\s{2,}(\S+)", line)                       # TABLE: "  col  TYPE"
        if cm and not s.startswith("--"):
            out[cur].append((cm.group(1), cm.group(2)))
    return out


def _resolve_date_column(date_column: str, metric_table: str, full_schema: str, dimensions):
    """Ensure date_column is a REAL date/timestamp column present in the schema. The intake
    can pin a hallucinated one (e.g. `invoices.invoice_date` when invoices has no date — the
    timestamp lives on `orders`). Find the actual date column, preferring the metric table
    then FK-joinable neighbours, and return (qualified_name, changed)."""
    typed = _typed_columns(full_schema)
    if not typed:
        return date_column, False

    def _is_date(col, ty):
        return bool(_DATE_TYPE_RE.search(ty) or (_DATE_NAME_RE.search(col) and not _KEYISH_RE.search(col)))

    # Already valid? (exists as a real date/timestamp column)
    if date_column and "." in date_column:
        tbl, col = date_column.rsplit(".", 1)
        for t, cols in typed.items():
            if _bare(t) == _bare(tbl):
                for c, ty in cols:
                    if c.lower() == col.lower() and _is_date(c, ty):
                        return date_column, False

    # Resolve: search the metric table + FK neighbours first, then EVERY table in scope
    # (the catalog is already narrowed to relevant tables, so a date column on any of them
    # is fair game — this is what finds orders.order_ts when the metric sits on invoices).
    seeds = list(dict.fromkeys(
        [metric_table] + [d.rsplit(".", 1)[0] for d in (dimensions or []) if "." in d]
    ))
    try:
        from aughor.tools.schema import fk_neighbor_expand
        seeds = fk_neighbor_expand(full_schema, seeds, cap=10)
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "fk-neighbour expand best-effort; date-column resolution proceeds "
                       "with bare seeds", counter="ada.date_resolve")
    ordered: list = []
    seen: set = set()
    for group in (seeds, list(typed.keys())):
        for s in group:
            for t in typed:
                if _bare(t) == _bare(s) and t not in seen:
                    ordered.append(t)
                    seen.add(t)
    for type_first in (True, False):
        for t in ordered:
            for c, ty in typed[t]:
                hit = _DATE_TYPE_RE.search(ty) if type_first else (_DATE_NAME_RE.search(c) and not _KEYISH_RE.search(c))
                if hit:
                    return f"{t}.{c}", True
    return date_column, False


def _provider(role="coder"):
    from aughor.llm.provider import get_provider
    return get_provider(role)


_ID_COLUMN_SUFFIXES = ("_id", "_key", "_code", "_num", "_no", "_ref", "_sk", "_nk", "_pk")


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


# WS2 — the zero-row / missing-column diagnosis helpers moved to the shared runner
# (aughor/sql/executor.py) with `_execute_safe`'s body. Aliased here because external
# callers import them from this module (routers/investigations.py, evals/run_golden.py,
# tests/unit/test_quality_fixes.py).
from aughor.sql.executor import (  # noqa: F401  (re-exports)
    missing_column_hint as _missing_column_hint,
    zero_row_suspicious as _zero_row_suspicious,
)


def _execute_safe(conn: "DatabaseConnection", phase_id: str, sql: str, schema: Optional[str] = None):
    """Execute SQL with one self-correction retry. Returns QueryResult.

    Retries on:
    - Hard SQL errors (syntax, missing column/table)
    - Suspicious zero-row results (e.g. CAST of identifier column as DATE)

    `schema` is the canvas-scoped schema for the fix prompt; without it the fix
    LLM would see the full connection schema (every dataset on a multi-dataset
    connection) and could "fix" a query by switching to an out-of-scope table.

    WS2: thin delegate to the shared guard-battery runner
    (aughor.sql.executor.execute_guarded) — the body moved there verbatim. The
    FIX prompt and provider are passed from this layer so the runner stays
    below aughor/agent (and so tests that monkeypatch `_provider` on this
    module keep steering the repair loop).
    """
    from aughor.agent.prompts import FIX_SQL_PROMPT
    from aughor.sql.executor import execute_guarded

    return execute_guarded(
        conn,
        sql,
        query_id=phase_id,
        schema=schema,
        fix_prompt_template=FIX_SQL_PROMPT,
        provider_factory=_provider,
    )


def _parallel_execute_safe(
    conn: "DatabaseConnection",
    phase_id: str,
    plan_queries: list,
    cap: int = 4,
    schema: Optional[str] = None,
) -> list[tuple]:
    """Run up to `cap` PhasePlan queries in parallel using per-thread reader connections.

    Each worker calls _execute_safe() on its own make_reader() clone so shared
    connection state is never touched concurrently. Falls back to serial if
    ThreadPoolExecutor fails or there is only one query.

    Returns a list of (PlanQuery, QueryResult) tuples in the same order as
    plan_queries[:cap].
    """
    from concurrent.futures import as_completed
    from aughor.kernel.concurrency import ContextThreadPoolExecutor

    valid = [(q, q.sql.strip()) for q in plan_queries[:cap] if q.sql and q.sql.strip()]
    if not valid:
        return []
    if len(valid) == 1:
        q, sql = valid[0]
        r = _execute_safe(conn, phase_id, sql, schema=schema)
        r.hypothesis_id = phase_id
        return [(q, r)]

    def _run(item: tuple) -> tuple:
        q, sql = item
        reader = conn.make_reader()
        r = _execute_safe(reader, phase_id, sql, schema=schema)
        r.hypothesis_id = phase_id
        return (q, r)

    # P2 — per-dimension progress: emit as each query completes so a long scan reports progress
    # DURING the node (`ada.progress_events`); no-op when no SSE sink is bound (the default).
    total_n = len(valid)
    try:
        with ContextThreadPoolExecutor(max_workers=len(valid)) as pool:
            futures = {pool.submit(_run, item): i for i, item in enumerate(valid)}
            ordered: list[tuple | None] = [None] * len(valid)
            done_n = 0
            for fut in as_completed(futures):
                res = fut.result()
                ordered[futures[fut]] = res
                done_n += 1
                emit_phase_progress(phase_id, done_n, total_n, getattr(res[0], "title", "") or "")
            return [r for r in ordered if r is not None]
    except Exception:
        # Serial fallback — never let parallelization break the investigation
        results = []
        for i, (q, sql) in enumerate(valid, 1):
            r = _execute_safe(conn, phase_id, sql, schema=schema)
            r.hypothesis_id = phase_id
            results.append((q, r))
            emit_phase_progress(phase_id, i, total_n, getattr(q, "title", "") or "")
        return results


def _apply_semantic_steps(results: list[tuple]) -> list[tuple]:
    """Apply any planner-attached semantic operator to its query's result (opt-in, fail-open).

    A ``PhaseQueryPlan`` may carry a ``.semantic`` step (filter/extract/top_k/aggregate over a free-text
    column). When it does — and the target column actually reads as text — the operator transforms that
    result so the phase interpreter reasons over the text-derived evidence. A step attached to a missing
    or non-text column is skipped safely, and any operator failure leaves the raw result in place.
    Returns the same ``(PlanQuery, QueryResult)`` shape; never raises."""
    from aughor.stats import stats as _s

    out: list[tuple] = []
    for q, r in results:
        step = getattr(q, "semantic", None)
        if step and not getattr(r, "error", None):
            try:
                from aughor.semops.operators import apply_step, detect_text_columns
                if step.column in detect_text_columns(r):
                    from aughor.kernel.flags import flag_enabled
                    op = apply_step(
                        r, step.operator, step.column,
                        predicate=(step.predicate or ""),
                        fields=[(f.name, f.description) for f in step.fields],
                        criterion=(getattr(step, "criterion", "") or ""),
                        k=getattr(step, "k", 10),
                        instruction=(getattr(step, "instruction", "") or ""),
                        validate=flag_enabled("semops.guarded_extract"),
                    )
                    r = op.result
                    _s.inc("ada.semantic_steps_applied")
                else:
                    _s.inc("ada.semantic_steps_skipped_nontext")
            except Exception as _e:
                from aughor.kernel.errors import tolerate
                tolerate(_e, "ADA semantic step is best-effort; raw result still used",
                         counter="ada.semantic_step_failed")
        out.append((q, r))
    return out


def _results_to_text(results, max_rows: int = 12) -> str:
    """Render a list of QueryResults as compact text for LLM interpretation. `max_rows` caps each
    result; the default is small to save tokens, but a full-series phase (a temporal trend) raises it
    so the interpreter doesn't reason over a truncated window while the chart plots every row."""
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(f"--- Query {i} ---")
        parts.append(format_result_for_llm(r, max_rows=max_rows))
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


# ── Robust narrator↔query binding ─────────────────────────────────────────────
# The narrator returns one finding per query, but as a free-form LIST it can
# reorder, merge, or drop entries. Binding by list position (the old
# `findings[min(i, len-1)]`) then pairs a finding describing dimension A with the
# query/data for dimension B — the "card says city but the chart shows country"
# bug. We instead bind each executed query to the narrator finding that names its
# SAME dimension (token overlap), and ground the displayed title in the query that
# actually produced the rows whenever that match is dimension-certain.

_LABEL_STOP = frozenset({
    "by", "per", "across", "of", "the", "a", "an", "and", "or", "for", "in", "on",
    "to", "vs", "versus", "with", "each", "every", "from",
    "total", "net", "gross", "sum", "avg", "average", "mean", "median", "count",
    "number", "num", "share", "pct", "percent", "proportion", "ratio", "rate",
    "value", "values", "amount", "amounts", "metric", "level",
    "revenue", "sales", "sale", "profit", "margin", "cost", "costs", "spend", "gmv",
    "income", "orders", "order", "units", "unit", "quantity", "qty", "price",
    "prices", "earnings", "loss", "losses", "money",
    "monthly", "weekly", "daily", "yearly", "quarterly", "trend", "trends", "time",
    "over", "period", "periods", "mom", "yoy", "pop", "wow", "qoq", "change",
    "growth", "delta", "scan", "ranked", "weakest", "lowest", "top", "bottom",
    "breakdown", "analysis", "distribution", "contribution",
})


def _label_tokens(label: str, extra_stop=frozenset()) -> set:
    """Reduce a label to its distinctive (dimension) tokens, dropping structural and
    measure words so 'Net revenue by city' and 'By City' both collapse to {'city'}."""
    return {
        t for t in re.findall(r"[a-z0-9]+", (label or "").lower())
        if len(t) > 1 and t not in _LABEL_STOP and t not in extra_stop
    }


def _align_narrator_findings(queries, narrator_findings, extra_stop=frozenset(), result_rows=None):
    """Bind each query to the narrator finding describing its SAME dimension.
    Returns (aligned, by_token): aligned[i] is the finding model for queries[i] (or
    None when no trustworthy match exists); by_token[i] is True when the match was
    made on a shared dimension token (so the query's own title is authoritative).

    When ``result_rows`` is given, ties on dimension-token overlap are broken by NUMERIC
    grounding — each finding binds to the query whose result cells actually contain its
    numbers. Without this, two queries over the SAME dimension but a different measure
    (e.g. a z-score-by-tier and a PoP-change-by-tier) tie on {tier} and the finding can bind
    to the wrong measure, so a z-score card inherits the PoP finding's figures (its title is
    then overwritten to the query's, masking the swap)."""
    n, m = len(queries), len(narrator_findings)
    aligned = [None] * n
    by_token = [False] * n
    if m == 0:
        return aligned, by_token
    q_tok = [_label_tokens(getattr(q, "title", ""), extra_stop) for q in queries]
    f_tok = [_label_tokens(getattr(f, "title", ""), extra_stop) for f in narrator_findings]
    gmat = None
    if result_rows:
        from aughor.explorer.verify import grounded_fraction
        gmat = [[grounded_fraction(getattr(narrator_findings[fi], "interpretation", "") or "",
                                   result_rows[qi] if qi < len(result_rows) else None)
                 for fi in range(m)] for qi in range(n)]
    used = set()
    cands = sorted(
        ((len(q_tok[qi] & f_tok[fi]), (gmat[qi][fi] if gmat else 0.0), qi, fi)
         for qi in range(n) for fi in range(m) if q_tok[qi] & f_tok[fi]),
        key=lambda c: (-c[0], -c[1], c[2], c[3]),
    )
    for _ov, _g, qi, fi in cands:
        if aligned[qi] is None and fi not in used:
            aligned[qi] = narrator_findings[fi]
            by_token[qi] = True
            used.add(fi)
    # Positional fallback: fill a leftover query from the SAME-index narrator finding
    # only when that finding is still unused. Never clamp to the last one (old bug).
    for qi in range(n):
        if aligned[qi] is None and qi < m and qi not in used:
            aligned[qi] = narrator_findings[qi]
            used.add(qi)
    return aligned, by_token


def _has_usable_data(results) -> bool:
    """True if at least one query in the phase returned rows without error. Used to skip the
    narrator interpret call (a 30-80s LLM round-trip) when every query failed or came back
    empty — there is nothing to interpret, and the phase falls back to data-only findings."""
    return any((not r.error and (r.row_count or 0) > 0) for _, r in (results or []))


def _extreme_tie_note(columns, rows) -> Optional[str]:
    """When several entities share the extreme value of a ranked scan, name ALL of them.

    The narrator tends to headline the top 1–2 outliers and drop ties (live incident:
    three franchises all at $3.00/txn; only two were named, the third vanished from the
    report). Deterministic: find the first label column + the last numeric column of a
    ranked result, cluster rows within 1.5% of the extreme (min), and if the cluster has
    ≥2 members return a note enumerating every member — criterion-complete by construction."""
    try:
        if not columns or not rows or len(rows) < 2:
            return None
        def _num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        label_idx = next((i for i, _ in enumerate(columns) if _num(rows[0][i]) is None), None)
        num_idx = next((i for i in range(len(columns) - 1, -1, -1)
                        if i != label_idx and _num(rows[0][i]) is not None), None)
        if label_idx is None or num_idx is None:
            return None
        vals = [(str(r[label_idx]), _num(r[num_idx])) for r in rows if _num(r[num_idx]) is not None]
        if len(vals) < 3:
            return None
        worst = min(v for _, v in vals)
        cluster = [n for n, v in vals if abs(v - worst) <= 0.015 * max(abs(worst), 1e-9)]
        rest = [v for _, v in vals if abs(v - worst) > 0.015 * max(abs(worst), 1e-9)]
        # Only a real anomaly cluster: ≥2 tied members, clearly separated from the rest.
        if len(cluster) < 2 or not rest or min(rest) < worst * 1.5:
            return None
        col = str(columns[num_idx]).replace("_", " ")
        return (f"{len(cluster)} entities share the extreme {col} of {worst:g}: "
                f"{', '.join(cluster[:6])}" + (" …" if len(cluster) > 6 else ""))
    except Exception:
        return None


def _assemble_phase_findings(results, narrator_findings, id_prefix, metric_label=""):
    """Build phase findings by binding each (query, result) to the narrator finding for
    its OWN dimension — never by list position. The displayed title is grounded in the
    query that produced the rows whenever the match is dimension-certain, so a card can
    never describe a different slice than its chart."""
    extra = _label_tokens(metric_label)
    aligned, by_token = _align_narrator_findings(
        [q for q, _ in results], narrator_findings, extra,
        result_rows=[getattr(r, "rows", None) for _, r in results],
    )
    out: list[InvestigationFinding] = []
    for i, (q, r) in enumerate(results):
        model = aligned[i]
        if model is not None:
            f = _finding_from_result_and_model(f"{id_prefix}_{i}", r, model, q.chart_type)
            if by_token[i]:
                f["title"] = q.title  # ground the label to the query that produced the rows
        else:
            f = InvestigationFinding(
                finding_id=f"{id_prefix}_{i}", title=q.title, sql=r.sql,
                columns=r.columns, rows=r.rows[:50], row_count=r.row_count,
                error=r.error, interpretation=(r.error or "Query executed."),
                key_numbers=[], chart_type=q.chart_type, stat_note=None, is_significant=False,
                trust_caveat=None,
            )
        # ADVISORY trust check — reuse the explorer's verify_insight battery (impossible
        # magnitude, fan-out artifact, vacuous CASE, ungrounded claim). It NEVER blocks: the
        # answer is always shown; an untrusted result just carries a caveat the UI surfaces.
        # conn=None → static checks only (no live cardinality probe), to keep ADA snappy.
        f["trust_caveat"] = None
        if not r.error and r.rows:
            try:
                from aughor.explorer.agent import verify_insight
                _ok, _why = verify_insight(r.rows, f.get("interpretation", ""), r.sql, columns=r.columns)
                if not _ok:
                    f["trust_caveat"] = _why
            except Exception as _e:
                from aughor.kernel.errors import tolerate
                tolerate(_e, "ada: advisory trust check", counter="ada.trust_advisory_failed")
        # WP-1a — live-detected guard caveats from `execute_guarded` (a value-disjoint
        # join / unbound filter the retry could not clear). These were detected against
        # the REAL data at execute time, so they lead; the static verify_insight caveat
        # (conn=None) follows. Flows into the existing HIGH→MEDIUM confidence cap via
        # `_cap_confidence_on_trust_advisory` — a detected-but-unrepaired guard finding
        # now costs confidence instead of evaporating.
        _live_caveats = list(getattr(r, "caveats", None) or [])
        if _live_caveats:
            _parts = _live_caveats + ([f["trust_caveat"]] if f.get("trust_caveat") else [])
            f["trust_caveat"] = "; ".join(dict.fromkeys(_parts))
        # Criterion-complete enumeration: when several entities TIE at the extreme of a
        # ranked scan, stamp the full list into stat_note — the narrator drops ties
        # (live: 3 franchises at $3.00/txn, only 2 named), the stamp can't.
        if not r.error and r.rows and not f.get("stat_note"):
            _tie = _extreme_tie_note(r.columns, r.rows)
            if _tie:
                f["stat_note"] = _tie
        out.append(f)
    return out


_SHARE_COL_RE = re.compile(r"(pct|percent|share|proportion|_of_total)", re.I)


def _chart_primary_is_metric(finding) -> None:
    """Drop share/percent columns from a finding's rendered table+chart so the bar plots
    the metric MAGNITUDE, not its share-of-total. The web chart prefers any pct/share
    column as the primary axis (PREFER_COL), which made the chart show a % while the
    narrative cited absolute dollars — the 'says X but shows Y' bug. The narrator still
    saw the share via results_text; only the rendered view is cleaned."""
    cols = finding.get("columns") or []
    if len(cols) <= 2:
        return
    keep = [i for i, c in enumerate(cols) if not _SHARE_COL_RE.search(c)]
    if len(keep) == len(cols) or len(keep) < 2:
        return
    finding["columns"] = [cols[i] for i in keep]
    finding["rows"] = [[row[i] for i in keep] for row in (finding.get("rows") or [])]


_RATIO_AGG_RE = re.compile(r"\b(sum|count|avg|min|max|median|stddev|variance|var_pop|var_samp)\s*\(", re.I)
_RATIO_LABEL_RE = re.compile(r"%|percent|\brate\b|ratio|share of|average|\bavg\b|\bmean\b|per[ -](order|unit|customer|capita|record)", re.I)


def _metric_is_ratio(metric_sql: str, metric_label: str = "") -> bool:
    """Deterministic gate: is the metric a RATIO / percentage / per-unit average rather than a
    plain additive total? A ratio (SUM(num)/SUM(den), anything *100, an AVG/mean) must be
    re-aggregated per group as numerator/denominator — it can NEVER be SUM'd across groups or
    divided by COUNT(*). The cross-sectional weakness scan used an additive-SUM template that
    silently dropped the denominator and reported SUM(numerator) as the metric; this detector
    routes such metrics to the ratio-aware plan/interpret path instead.

    Detection (any one): a top-level *100 scaling; a division between two aggregate expressions;
    or a label that names a percentage / rate / ratio / average / per-unit measure."""
    s = metric_sql or ""
    compact = s.replace(" ", "")
    if "*100" in compact:
        return True
    if "/" in s and len(_RATIO_AGG_RE.findall(s)) >= 2:
        return True
    # a bare AVG/MEAN/MEDIAN aggregate is a per-record mean — non-additive
    if re.search(r"\b(avg|mean|median)\s*\(", s, re.I):
        return True
    if _RATIO_LABEL_RE.search(metric_label or ""):
        return True
    return False


def _metric_is_composite_ratio(metric_sql: str) -> bool:
    """The subset of ratio metrics that are genuinely BUILT FROM two aggregates — a division
    between aggregates (SUM(num)/SUM(den)) or a *100 percentage scaling. These NEED their
    numerator/denominator surfaced so the ratio is auditable and re-aggregates correctly per group.

    A bare AVG/MEAN/MEDIAN is non-additive (so `_metric_is_ratio` is True) but is NOT composite — it
    is self-contained and needs no numerator/denominator instrumentation. Distinguishing the two
    lets the cross-section scan emit a clean `AVG(x)`-only query instead of padding it with redundant
    SUM(x)/COUNT(*) columns."""
    s = metric_sql or ""
    if "*100" in s.replace(" ", ""):
        return True
    if "/" in s and len(_RATIO_AGG_RE.findall(s)) >= 2:
        return True
    return False


_PCT_LABEL_RE = re.compile(r"(rate|percent|pct|share|proportion|ratio)", re.I)


def _metric_is_percent(metric_sql: str, metric_label: str = "", values=None) -> bool:
    """Is the metric a PERCENTAGE (a 0–100% concept), as opposed to a plain average (avg rating,
    AOV) or an additive total? A percentage must be displayed as "41.0%" everywhere — the signal the
    `column_units` hint carries to the UI. True when: it's a composite ratio (SUM/SUM or *100), its
    label/SQL names a rate/percent/share/ratio, OR (a bare AVG that) reads as a proportion in [0,1].
    A plain AVG(rating) (values > 1, no rate-ish label) is correctly NOT a percent."""
    if _metric_is_composite_ratio(metric_sql):
        return True
    if _PCT_LABEL_RE.search(f"{metric_sql or ''} {metric_label or ''}"):
        return True
    if values:
        nums = [v for v in values if isinstance(v, (int, float))]
        if nums and all(0 <= float(v) <= 1.0001 for v in nums):
            return True
    return False


def _fmt_pct(v, digits: int = 1) -> str:
    """Scale-aware percent for display: a ratio in [-1,1] is ×100 (0.4096 → "41.0%"); a value already
    scaled to a percent (40.96) is left as-is. One canonical formatter so a rate never renders three
    ways (chart "0.4", key number "0.41%", prose "40.96%"). Mirrors the web `formatPercent`."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    p = n * 100 if abs(n) <= 1.0001 else n
    return f"{p:.{digits}f}%"


# The cross-sectional scan defaults to a WEAKNESS frame (rank ascending, surface the lowest).
# Some diagnostics instead seek the MAXIMUM ("which category carries the HIGHEST out-of-stock
# burden") — for those the answer is the largest value, not the smallest, so orient the ranking
# and interpretation toward the top. Conservative: an explicit max superlative with no min word.
_XSEC_MAX_RE = re.compile(r"\b(highest|largest|biggest|greatest|maximum|most)\b", re.I)
_XSEC_MIN_RE = re.compile(r"\b(lowest|weakest|least|smallest|minimum|bottom|underperform\w*)\b", re.I)


def _xsec_max_seeking(question: str) -> bool:
    q = question or ""
    return bool(_XSEC_MAX_RE.search(q)) and not _XSEC_MIN_RE.search(q)


_RATIO_METRIC_COL_RE = re.compile(r"metric_total|metric_value|\bratio\b|pct|percent|\brate\b", re.I)

# Columns that carry the PRIOR-PERIOD baseline a temporal change is measured against, and the
# columns that express the CHANGE / its attribution. When the baseline is entirely empty the latter
# are meaningless (a "change" with nothing to change from) — see _neutralize_baseless_contribution.
_COMP_COL_RE = re.compile(r"(^|_)comp(_|$)|comparison|baseline|prior[_-]|[_-]prior|prev[_-]|[_-]prev|\byoy\b", re.I)
_CONTRIB_COL_RE = re.compile(r"contribut|abs[_-]?change|absolute[_-]?change|(^|_)delta(_|$)|[_-]change(_|$)", re.I)


def _neutralize_baseless_contribution(finding: dict) -> None:
    """G1 — a temporal dimensional finding computes abs_change / contribution_pct against a
    prior-period baseline. When that baseline is ENTIRELY missing (the comp column is all-NULL),
    abs_change collapses to the current-period LEVEL and contribution_pct becomes a fabricated
    "share of the decline" — the "fragrance_women = 57.8% of the decline / severity alert" class,
    which directly contradicts a top-level "100% unexplained" attribution. Detect the empty baseline
    and strip the change/contribution columns (chart + key numbers), drop the significance flag, and
    caveat the finding, so neither the chart nor synthesis can name a driver of a change never measured.
    No-op when a real baseline is present."""
    cols = finding.get("columns") or []
    rows = finding.get("rows") or []
    if not cols or not rows:
        return

    def _is_null(v) -> bool:
        if v is None:
            return True
        if isinstance(v, float):
            return v != v  # NaN
        if isinstance(v, str):
            return v.strip().upper() in ("", "NULL", "NONE", "NAN")
        return False

    comp_idxs = [i for i, c in enumerate(cols) if i != 0 and _COMP_COL_RE.search(str(c))]
    if not comp_idxs:
        return
    baseline_missing = all(
        all(_is_null(r[i]) for r in rows if i < len(r))
        for i in comp_idxs
    )
    if not baseline_missing:
        return

    # Drop the change/contribution columns AND the now-empty comp columns from the rendered view,
    # keeping the dimension (col 0) + the honest current-period level columns.
    drop = {i for i, c in enumerate(cols)
            if i != 0 and (_CONTRIB_COL_RE.search(str(c)) or _COMP_COL_RE.search(str(c)))}
    keep = [i for i in range(len(cols)) if i not in drop]
    if len(keep) >= 2:
        finding["columns"] = [cols[i] for i in keep]
        finding["rows"] = [[row[i] for i in keep if i < len(row)] for row in rows]

    # Neutralize the contribution/severity key numbers and the significance flag.
    finding["key_numbers"] = [
        kn for kn in (finding.get("key_numbers") or [])
        if not _CONTRIB_COL_RE.search((kn.get("label", "") or "") + " " + (kn.get("value", "") or ""))
        and "decline" not in (kn.get("label", "") or "").lower()
    ]
    finding["is_significant"] = False
    finding["trust_caveat"] = finding.get("trust_caveat") or (
        "No prior-period baseline (comparison data is empty), so change-contribution cannot be "
        "computed — the figures shown are current-period levels, not drivers of any change."
    )


def _suppress_fanned_ratio(findings: list, metric_label: str, eff_caveat: str) -> str:
    """Fix B — when a RATIO metric fans out (a join multiplies its rows), the value is CORRUPTED,
    not merely inflated: the numerator and denominator are multiplied by DIFFERENT per-group
    factors, so the ratio and its ranking are meaningless (the ROAS 0.0–0.01 case). Suppress them
    instead of presenting + rationalising an artifact — drop the chart, replace the interpretation,
    and clear the bogus key numbers. Returns the reframed phase summary; mutates ``findings``.
    Cold-start safety net: Fix C avoids this whenever a grain-correct finding SQL exists to reuse."""
    honest = (
        f"{metric_label} could not be computed reliably across the scanned dimensions: {eff_caveat} "
        f"The values are fan-out artifacts, not real {metric_label} — a grain-correct recompute "
        "(pre-aggregate each side to the dimension grain, then divide) is needed before this can be "
        "ranked or trusted.")
    for f in (findings or []):
        f["interpretation"] = honest
        f["chart_type"] = "none"
        f["key_numbers"] = []
    return (f"⚠ {metric_label} could not be computed reliably across the scanned dimensions — a "
            "fan-out across the join corrupts the ratio, so the values are suppressed (a "
            "grain-correct recompute is needed).")


_VERDICT_PREFIX_RE = re.compile(r"^\s*VERDICT\s*:\s*", re.I)


def _strip_verdict_prefix(text: str) -> str:
    """'VERDICT: UNIFORM. The leading reason…' → 'Uniform. The leading reason…'.

    Drops the machinery label and sentence-cases the ALL-CAPS token that followed it
    ('AT the peer range' → 'At the peer range'). Prose without the label is untouched."""
    if not _VERDICT_PREFIX_RE.match(text or ""):
        return text
    rest = _VERDICT_PREFIX_RE.sub("", text)
    m = re.match(r"([A-Z][A-Z ]+?)(\b)", rest)
    if m and len(m.group(1)) >= 2:
        word = m.group(1)
        rest = word.capitalize() + rest[len(word):]
    return rest


def _scrub_suppressed_metric_everywhere(phases: list, suppressed: dict) -> int:
    """A suppressed ratio is corrupt at the METRIC level, so every phase that renders it is
    corrupt — but only the cross-section phase ran the guard. Walk every phase and neutralise
    any finding that displays the same metric (its label appears as a result COLUMN or in a
    key-number label): drop the chart, clear the metric key numbers, carry the caveat. This is
    what stopped the temporal 'June 2024 Refund Leakage Rate: 58.8%' tile + line chart shipping
    beside a report that elsewhere calls the metric an artifact. Deterministic; returns the count
    scrubbed."""
    label = (suppressed or {}).get("metric_label") or ""
    caveat = (suppressed or {}).get("caveat") or ""
    if not label:
        return 0
    norm = _norm_measure(label)
    scrubbed = 0
    for ph in phases or []:
        for f in ph.get("findings") or []:
            if f.get("chart_type") == "none" and not (f.get("key_numbers") or []):
                continue                                    # already suppressed at source
            cols = [_norm_measure(c) for c in (f.get("columns") or [])]
            kn_labels = [_norm_measure(k.get("label", "")) for k in (f.get("key_numbers") or [])]
            renders_metric = norm in cols or any(norm and norm in kl for kl in kn_labels)
            if not renders_metric:
                continue
            f["chart_type"] = "none"
            # Drop only the key numbers that quote THIS metric; a co-located record count stays.
            f["key_numbers"] = [k for k in (f.get("key_numbers") or [])
                                if norm not in _norm_measure(k.get("label", ""))]
            f["is_significant"] = False
            f["trust_caveat"] = f.get("trust_caveat") or caveat
            # The interpretation prose quotes the artifact ("...is 58.83%..."); replace it so the
            # number appears nowhere the reader can mistake for a fact. Dedupe collapses the repeat.
            f["interpretation"] = (
                f"{label} could not be computed reliably for this cut — the value is a "
                "computation artifact of the same conditioned denominator, not a real level.")
            scrubbed += 1
    return scrubbed


def _norm_measure(s: str) -> str:
    """Normalise a measure name for matching: lowercase, drop a units suffix like '(%)' and
    non-alphanumerics. 'Refund Leakage Rate (%)' and 'refund_leakage_rate' → 'refundleakagerate'."""
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", "", str(s or "")).lower())


def _dedupe_repeated_caveats(phases: list) -> None:
    """One honest detection was rendering as eight: the same suppression text was stamped on
    every fanned finding as BOTH its interpretation and its trust_caveat, and the UI draws a box
    per caveat. Keep the first occurrence of each identical caveat / suppression interpretation
    across the whole report; blank the exact-duplicate repeats so it reads once. In place."""
    seen_caveats: set = set()
    seen_interps: set = set()
    for ph in phases or []:
        for f in ph.get("findings") or []:
            cav = (f.get("trust_caveat") or "").strip()
            if cav:
                if cav in seen_caveats:
                    f["trust_caveat"] = None
                else:
                    seen_caveats.add(cav)
            # Only collapse the SUPPRESSION interpretation (the identical machine-written one);
            # a real per-finding interpretation is never an exact repeat of another's.
            interp = (f.get("interpretation") or "").strip()
            if interp and "could not be computed reliably" in interp:
                if interp in seen_interps:
                    f["interpretation"] = "See the note above — the same computation caveat applies."
                else:
                    seen_interps.add(interp)


# ── Global-ratio plausibility guard (conditioned-denominator / implausible-magnitude) ─────────
# The catastrophic inv1 failure: a "why is the Fragrance refund RATE so high?" scan generated
# per-dimension SQL that used the EVENT table (refunds) as the JOIN BASE and INNER-joined the
# population (revenue) onto it — so every segment's denominator counted only orders that HAD a
# refund. Result: a refund rate of ~73% (true ≈ 10.4%), and the report told the user their premise
# was INVERTED. No existing guard caught it (values sit inside [0,100], no row fan-out). This guard
# computes the metric's TRUE global level independently — each aggregate over its OWN full table,
# the population a rate must span — and flags when every scanned segment is implausibly far above it
# (the systematic-inflation signature of a conditioned denominator or a broken ratio computation).
_AGG_ANY_RE = re.compile(
    r'\b(?:SUM|COUNT|AVG)\s*\(\s*(?:DISTINCT\s+)?("?[\w.]+"?)\s*\)', re.I)


def _parse_ratio_sources(metric_sql: str) -> Optional[dict]:
    """Parse a composite-ratio formula ``AGG(col) / AGG(col)`` into its numerator and denominator
    SOURCES, so the true global ratio can be recomputed with each side aggregated over its OWN full
    table. Columns may be qualified (``table.col`` / ``schema.table.col``) or bare (``col``); a bare
    column is resolved to its table later via ``information_schema``. Returns None unless there are
    exactly one division and a distinct numerator/denominator column (the cross-measure rate shape
    where a conditioned denominator is possible). Handles a ``*100`` percent scale and a ``NULLIF``
    denominator wrapper. Fail-open: any parse ambiguity → None."""
    s = metric_sql or ""
    if s.count("/") != 1:          # exactly one division — skip nested/ambiguous ratios
        return None
    left, right = s.split("/", 1)
    lm = _AGG_ANY_RE.search(left)
    rm = _AGG_ANY_RE.search(right)
    if not lm or not rm:
        return None

    def _split_ref(ref: str) -> "tuple[Optional[str], str]":
        parts = [p.strip('"') for p in ref.split(".")]
        if len(parts) >= 2:
            return ".".join(parts[:-1]), parts[-1]
        return None, parts[-1]   # bare column — resolve its table later

    num_table, num_col = _split_ref(lm.group(1))
    den_table, den_col = _split_ref(rm.group(1))
    # distinct measures on the two sides; a same-table qualified ratio has no conditioned-denom risk
    if not num_col or not den_col or num_col == den_col:
        return None
    if num_table and den_table and num_table == den_table:
        return None
    _agg = lambda side: (re.search(r"\b(SUM|COUNT|AVG)\b", side, re.I) or [None, "SUM"])[1].upper()
    return {
        "num_table": num_table, "num_col": num_col, "num_agg": _agg(left),
        "den_table": den_table, "den_col": den_col, "den_agg": _agg(right),
        "scale": 100.0 if "*100" in s.replace(" ", "") else 1.0,
    }


def _resolve_table_for_column(conn, col: str) -> Optional[str]:
    """Resolve a bare column to its owning ``schema.table`` via information_schema — needed when the
    metric formula names columns unqualified (a common LLM shape). Returns None when the column is
    absent or lives in MORE THAN ONE table (ambiguous → fail-open, don't guess). ``col`` is a
    regex-captured identifier (``\\w+``), so the literal is safe to inline."""
    if not col or not re.fullmatch(r"\w+", col):
        return None
    try:
        r = conn.execute(
            "__col_table_probe__",
            "SELECT table_schema, table_name FROM information_schema.columns "
            f"WHERE column_name = '{col}' GROUP BY 1, 2")
        if r and not getattr(r, "error", None) and r.rows and len(r.rows) == 1:
            sch, tbl = r.rows[0][0], r.rows[0][1]
            return f"{sch}.{tbl}" if sch else tbl
    except Exception:
        return None
    return None


def _independent_global_ratio(conn, sources: dict) -> Optional[float]:
    """The metric's TRUE whole-population value: numerator aggregated over its full table divided by
    the denominator aggregated over ITS full table — no conditioning join, so the denominator spans
    the entire population the rate is defined over. One cheap deterministic query. None on any error."""
    try:
        num = f'{sources["num_agg"]}("{sources["num_col"]}")'
        den = f'{sources["den_agg"]}("{sources["den_col"]}")'
        sql = (f'SELECT (SELECT {num} FROM {sources["num_table"]}) * {sources["scale"]} '
               f'/ NULLIF((SELECT {den} FROM {sources["den_table"]}), 0) AS global_ratio')
        r = conn.execute("__global_ratio_probe__", sql)
        if r and not getattr(r, "error", None) and r.rows and r.rows[0] and r.rows[0][0] is not None:
            return float(r.rows[0][0])
    except Exception:
        return None
    return None


def _ratio_metric_values(findings: list) -> list:
    """Pull the per-segment ratio values from the scan's findings — the metric column
    (`metric_total`/`metric_value`/`*rate*`) across every row of every finding."""
    def _f(v):
        try:
            return float(str(v).replace(",", "").replace("%", ""))
        except (TypeError, ValueError):
            return None
    vals: list[float] = []
    for f in (findings or []):
        cols = [str(c).lower() for c in (f.get("columns") or [])]
        m_idx = next((i for i, c in enumerate(cols) if _RATIO_METRIC_COL_RE.search(c)), None)
        if m_idx is None:
            continue
        for row in (f.get("rows") or []):
            if m_idx < len(row):
                v = _f(row[m_idx])
                if v is not None:
                    vals.append(v)
    return vals


_GLOBAL_RATIO_INFLATION = 2.5   # every segment ≥ this × the true global ⇒ systematic inflation


def _global_ratio_plausibility_guard(findings: list, conn, metric_sql: str,
                                     metric_label: str) -> Optional[dict]:
    """Fix 1+2 — detect a conditioned-denominator / broken ratio by magnitude. Compute the metric's
    true global level independently; if EVERY scanned segment is ≥ 2.5× that global (systematic
    inflation the eye reads as 'every segment is an outlier'), the per-segment ratio is a computation
    artifact, not a business signal. Suppress the corrupted numbers and return an honest caveat that
    STATES the true global. Returns None (no-op) when it can't parse the metric, can't compute the
    global, or the segments are plausibly distributed around it. Deterministic; never raises.

    Returns a dict ``{caveat, true_global_str, true_global}`` — the structured true level lets
    synthesis be handed the antidote (2.8%), not just told the segment values are wrong, so it
    can't headline the artifact for want of a real number to cite instead."""
    sources = _parse_ratio_sources(metric_sql)
    if not sources:
        return None
    # Resolve any bare (unqualified) column to its owning table — the LLM writes the metric formula
    # qualified on some runs and bare on others, and we need both tables to aggregate each side over
    # its OWN full population.
    if not sources["num_table"]:
        sources["num_table"] = _resolve_table_for_column(conn, sources["num_col"])
    if not sources["den_table"]:
        sources["den_table"] = _resolve_table_for_column(conn, sources["den_col"])
    if not sources["num_table"] or not sources["den_table"] or sources["num_table"] == sources["den_table"]:
        return None
    global_ratio = _independent_global_ratio(conn, sources)
    if global_ratio is None or global_ratio <= 0:
        return None
    seg_vals = [v for v in _ratio_metric_values(findings) if v is not None and v > 0]
    if len(seg_vals) < 2:
        return None
    # Systematic inflation: even the SMALLEST segment sits far above the true global — the signature
    # of a denominator that lost most of its population (not a real spread with a few high segments).
    if min(seg_vals) < _GLOBAL_RATIO_INFLATION * global_ratio:
        return None
    _fmt = _fmt_pct if sources["scale"] == 100.0 or max(seg_vals) <= 100.0 else (lambda v: f"{v:,.2f}")
    true_global_str = _fmt(global_ratio)
    caveat = (
        f"metric-computation error: every scanned segment of {metric_label} ({_fmt(min(seg_vals))}–"
        f"{_fmt(max(seg_vals))}) sits far above the metric's TRUE whole-population level of "
        f"{true_global_str} (numerator over {sources['num_table']} ÷ denominator over "
        f"{sources['den_table']}, each on its full population). This is the signature of a conditioned "
        "denominator — the per-segment query joined the denominator through the numerator's event "
        f"table, so it counted only the population that already had the event. The true global "
        f"{metric_label} is {true_global_str}; the per-segment ranking is not trustworthy until the "
        "denominator is computed over the full population per segment.")
    return {"caveat": caveat, "true_global_str": true_global_str, "true_global": global_ratio}


def _chart_ratio_primary(finding) -> None:
    """For a RATIO metric, plot metric_total (the ratio itself), not the large numerator/
    denominator dollar aggregates it was built from. Keep the dimension column + the ratio
    column in the rendered table/chart; drop n / numerator_total / denominator_total from the
    VIEW (the narrator still saw them in results_text). Mirror image of _chart_primary_is_metric,
    which drops share columns to plot a magnitude — here we drop magnitudes to plot the ratio."""
    cols = finding.get("columns") or []
    if len(cols) <= 2:
        return
    keep = [0]  # the dimension column always leads
    for i, c in enumerate(cols):
        if i == 0:
            continue
        if _RATIO_METRIC_COL_RE.search(c):
            keep.append(i)
            break
    if len(keep) < 2:
        keep = [0, 1]  # fallback: dimension + first metric column
    if len(keep) == len(cols):
        return
    finding["columns"] = [cols[i] for i in keep]
    finding["rows"] = [[row[i] for i in keep] for row in (finding.get("rows") or [])]


# A pie/donut stays legible for only a handful of parts; past this a ranked bar reads better.
_PIE_MAX_SLICES = 6
# Column-name signals used to keep the intent resolver honest about a finding's ACTUAL shape.
_FINDING_DATE_RE = re.compile(
    r"(?:^|_)(?:date|month|week|day|year|quarter|period|created|updated|timestamp)s?(?:_|$)|_at$|_ts$", re.I)
_FINDING_CHANGE_RE = re.compile(
    r"(change|delta|growth|\bmom\b|\byoy\b|\bwow\b|\bqoq\b|_chg$|_diff$|vs_prev|^prev_|_prev$|contribution)", re.I)


def _chart_type_for_finding(finding: dict, intent: str) -> str:
    """Pick a finding's chart from its NARRATIVE intent, VERIFIED against the data's actual shape so a
    mislabelled intent degrades to 'auto' (frontend inference) instead of forcing a wrong chart. See
    docs/CHART_SELECTION_GUIDE.md. Intents:
      trend        → line — but only when a date/period column is actually present, else 'auto'.
      composition  → a donut for a few parts-of-a-whole, a ranked bar once there are too many slices.
      ranking      → sorted horizontal bar — but a CHANGE/contribution finding keeps 'auto' so the
                     frontend's sign-aware diverging bar isn't flattened.
      relationship → scatter.
    Anything else keeps the finding's own chart_type (or 'auto')."""
    cols = [str(c) for c in (finding.get("columns") or [])]
    n = len([r for r in (finding.get("rows") or []) if r])
    has_date = any(_FINDING_DATE_RE.search(c) for c in cols)
    has_change = any(_FINDING_CHANGE_RE.search(c) for c in cols)
    if intent == "composition":
        # Chart grammar: a composition is a RANKED BAR, never a donut — the reference
        # reports use three forms (ranked h-bar, labeled scatter, table) and zero pies;
        # a 60.7/39.3 split reads faster as two sorted bars with data labels than as
        # arc angles. Flag-off keeps the legacy pie byte-identical.
        from aughor.kernel.flags import flag_enabled as _fe
        if _fe("chart.exhibit_grammar"):
            return "bar_horizontal"
        return "pie" if 2 <= n <= _PIE_MAX_SLICES else "bar_horizontal"
    if intent == "relationship":
        return "scatter"
    if intent == "trend":
        return "line" if has_date else "auto"
    if intent == "ranking":
        return "auto" if has_change else "bar_horizontal"
    return finding.get("chart_type") or "auto"


# The metric SQL names its source column (SUM(tickets.fare_chf)) — the currency code
# embedded there is the DATA's currency, which no display preference may overwrite.
_SRC_CURRENCY_RE = re.compile(r"_(chf|usd|eur|gbp|jpy|cny|inr|aud|cad|sgd|brl|zar)\b", re.I)
_MONEYISH_COL_RE = re.compile(r"(revenue|fare|amount|cost|price|spend|gmv|sales|value|profit|total)", re.I)


def _tag_currency_columns(finding: dict, metric_sql: str) -> None:
    """Carry the metric's SOURCE currency (fare_chf → CHF) on `column_units` as
    "currency:CHF", so no surface relabels CHF data with the org's display symbol
    (the live A/B showed a €2.0M axis beside "CHF" prose). Additive — an existing
    unit (percent) always wins; no currency token in the SQL → no-op."""
    m = _SRC_CURRENCY_RE.search(metric_sql or "")
    if not m:
        return
    code = m.group(1).upper()
    units = dict(finding.get("column_units") or {})
    changed = False
    for c in finding.get("columns") or []:
        name = str(c)
        if name not in units and _MONEYISH_COL_RE.search(name) and not _SHARE_COL_RE.search(name):
            units[name] = f"currency:{code}"
            changed = True
    if changed:
        finding["column_units"] = units


def _tag_percent_columns(findings: list, match) -> None:
    """Mark every finding column whose name matches `match` (a compiled regex) as a percent on the
    finding's `column_units`, so the UI formats it the one consistent way. Additive; idempotent."""
    for f in findings:
        u = {c: "percent" for c in (f.get("columns") or []) if match.search(c)}
        if u:
            f["column_units"] = {**(f.get("column_units") or {}), **u}


def _apply_percent_formatting(finding: dict, is_pct: bool) -> None:
    """Make a percent-metric finding read consistently everywhere: tag its metric / share columns as
    `percent` (so the chart axis + data labels format via the one scale-aware formatter) and rebuild
    its key numbers to the canonical `41.0%` scale + precision. No-op when the metric isn't a percent
    (so a plain-total or average finding is byte-identical). Idempotent."""
    if not is_pct:
        return
    units = {c: "percent" for c in (finding.get("columns") or [])
             if _RATIO_METRIC_COL_RE.search(c) or _SHARE_COL_RE.search(c)}
    if units:
        finding["column_units"] = {**(finding.get("column_units") or {}), **units}
    _normalize_pct_key_numbers(finding)


# Leading number of a key-number value, tolerating an approx "~" and a wrapping "(".
_PCT_KN_LEAD_RE = re.compile(r"^\s*(~\s*)?\(?\s*(-?\d+(?:\.\d+)?)\s*(%?)")
# A percentage-POINTS value ("0.36pp", "1.5 pp") — a SPREAD/GAP between two percentages, already
# absolute. It must NOT go through the ratio→percent ×100 path below (that turned a correct "0.36pp"
# into "36.0%pp": the number is ≤1 so the fraction heuristic wrongly scaled it and injected a "%").
_PP_UNIT_RE = re.compile(r"^\s*~?\s*-?\d+(?:\.\d+)?\s*pp\b", re.I)
# A parenthetical that ONLY restates a number (± %) — the LLM's redundant "(32.8%)" duplicate. A
# parenthetical with words ("(15,612 / 48,320 items)") or a dimension ("(Germany)") is NOT this.
_PCT_KN_REDUNDANT_TAIL_RE = re.compile(r"^\s*\(\s*~?\s*-?\d+(?:\.\d+)?\s*%?\s*\)\s*$")


def _normalize_pct_key_numbers(finding: dict) -> None:
    """For a percent-unit finding, rewrite each key-number value to ONE canonical form so the section
    values match the chart beside them. Re-derives through the single scale-aware formatter, unifying
    scale AND precision, and collapses the LLM's redundant "value (value)" duplicates:
      "0.41%" / "0.4096" → "41.0%";  "32.31%" → "32.3%";  "~0.328 (32.8%)" → "~32.8%";
      "34.5%(34.5%)" → "34.5%";  "31.2%(31.3%)" → "31.2%".
    A bare number > 1 with NO "%" is left alone (a count "5000" / an average "42.50"), and a
    meaningful parenthetical ("(Germany)", "(15,612 / 48,320 items)") is preserved. Idempotent."""
    for kn in finding.get("key_numbers") or []:
        val = str(kn.get("value") or "").strip()
        label = (kn.get("label") or "").lower()
        if any(w in label for w in ("count", "record", "rows", "volume", "orders", "customers", "= n", " n ")):
            continue
        if _PP_UNIT_RE.match(val):
            continue  # percentage-POINTS values are already absolute — the %/ratio canonicalizer skips them
        m = _PCT_KN_LEAD_RE.match(val)
        if not m:
            continue
        num = float(m.group(2))
        had_pct = m.group(3) == "%"
        if not (had_pct or abs(num) <= 1.0001):
            continue  # a bare count / average, not a percentage
        approx = "~" if m.group(1) else ""
        tail = val[m.end():]
        if _PCT_KN_REDUNDANT_TAIL_RE.match(tail):
            tail = ""   # drop the duplicate "(32.8%)" the LLM appended
        kn["value"] = approx + _fmt_pct(num) + tail


def _fallback_headline(summary: str) -> str:
    """First sentence of a phase summary as a headline, cut at a WORD boundary when
    over length — the raw [:160] slice used to shear mid-clause ("…while the
    lowest-ranked individual"), which read as a rendering bug in the report head."""
    first = re.split(r"(?<=[.!?])\s", summary or "")[0].strip()
    if len(first) <= 160:
        return first
    return first[:160].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"


def _fmt_compact_num(v: float) -> str:
    """1951747 → '1.95M' — the compact scale every chart axis already speaks; a key
    number sitting beside that chart must not read '1951747.00'."""
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.2f}B"
    if a >= 1e6:
        return f"{v / 1e6:.2f}M"
    if a >= 1e3:
        return f"{v / 1e3:.1f}K"
    return f"{v:,.2f}" if a != int(a) else f"{int(v):,}"


_AVG_COL_RE = re.compile(r"avg|average|per[\s_/-]|mean", re.I)
_COUNT_COL_RE = re.compile(r"^(n|count|records|n_records|row_count)$", re.I)


def _fix_xsec_extreme_key_numbers(finding: dict, is_pct: bool = False) -> None:
    """F4 — make the 'lowest'/'highest' key numbers agree with the finding's OWN charted rows.
    The interpret LLM occasionally reports an extreme that is not the actual min/max of the result
    set (e.g. 'highest 42.68%' when the top bar in the very same chart is 43.07%). Recompute both
    extremes deterministically from the rows so a key number can never contradict the chart.

    A cross-section grid carries TWO measures — a total (metric_total) and a per-record average —
    so a tile is routed to its OWN column by label: an 'avg/per' tile reads the average column, a
    'total' tile the total column. Getting this wrong is what stamped a total's extreme onto the
    avg tile ('Poland avg/ticket: 1951747.00 (Egypt)') and left the total unformatted. Magnitudes
    format compact (1.95M) to match the axis; the '(top N)' parenthetical is stripped (weakest-first
    ⇒ these are the LOWEST)."""
    cols = finding.get("columns") or []
    rows = finding.get("rows") or []
    kns = finding.get("key_numbers") or []
    if len(cols) < 2 or not rows or not kns:
        return

    def _num(v):
        try:
            return float(str(v).replace(",", "").replace("%", "").strip())
        except Exception:
            return None

    # Identify the dimension (first non-numeric), the PRIMARY total metric, and the AVG column.
    def _is_numeric_col(i):
        return any(_num(r[i]) is not None for r in rows[:20] if i < len(r))
    numeric = [i for i in range(len(cols)) if _is_numeric_col(i)]
    dim_idx = next((i for i in range(len(cols)) if i not in numeric), 0)
    measures = [i for i in numeric if not _COUNT_COL_RE.match(str(cols[i]).strip())]
    avg_idx = next((i for i in measures if _AVG_COL_RE.search(str(cols[i]))), None)
    total_idx = next((i for i in measures if i != avg_idx), None)
    # Ratio/percent metric: the total IS the rate; there is no separate avg tile.
    ratio_idx = next((i for i in measures if _RATIO_METRIC_COL_RE.search(str(cols[i]))), None)
    if ratio_idx is not None:
        total_idx, avg_idx = ratio_idx, None

    def _extremes(midx):
        if midx is None:
            return None, None
        vals = [(_num(r[midx]), r[dim_idx]) for r in rows
                if midx < len(r) and dim_idx < len(r) and _num(r[midx]) is not None]
        if not vals:
            return None, None
        return min(vals, key=lambda x: x[0]), max(vals, key=lambda x: x[0])

    total_lo, total_hi = _extremes(total_idx)
    avg_lo, avg_hi = _extremes(avg_idx)

    def _reformat(template: str, num: float, dim) -> str:
        """Replace the numeric part of the LLM's value string, preserving its unit (% / €) and a
        trailing '(dimension)' so value and label stay self-consistent. A percent is scale-aware
        (0.4096 → '41.0%'); a magnitude is compact (1.95M) — matching the chart's axis, never a
        raw '1951747.00'."""
        t = template or ""
        if is_pct:
            return f"{_fmt_pct(num)} ({dim})"
        unit = "%" if "%" in t else ""
        return f"{_fmt_compact_num(num)}{unit} ({dim})"

    for kn in kns:
        lbl = (kn.get("label") or "")
        low = lbl.lower()
        kn["label"] = re.sub(r"\s*\(top\s*\d+\)", "", lbl).strip()  # weakest-first ⇒ not "top"
        # Route the tile to its own measure — an avg/per label reads the avg column, else the
        # total. An avg tile with NO avg column in the grid is left alone: falling back to the
        # total would stamp the total's extreme onto it — the exact bug this routing exists to fix.
        is_avg_tile = bool(_AVG_COL_RE.search(low))
        lo, hi = (avg_lo, avg_hi) if is_avg_tile else (total_lo, total_hi)
        if lo is None:
            continue
        if any(w in low for w in ("lowest", "weakest", "min")):
            kn["value"] = _reformat(kn.get("value", ""), lo[0], lo[1])
        elif any(w in low for w in ("highest", "strongest", "max", "best", "top")):
            kn["value"] = _reformat(kn.get("value", ""), hi[0], hi[1])


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
    """Back-compat thin wrapper: the detection now lives in the Orchestrator as a typed
    ``ContradictionReport`` (so the tension is a first-class artifact), and this returns
    its ``to_prompt_section()`` — byte-identical to the string this used to build, so the
    synthesizer sees exactly what it always did. Callers wanting the typed report should
    use ``orchestrator.detect_contradictions`` directly."""
    from aughor.agent.orchestrator import detect_contradictions
    return detect_contradictions(phases).to_prompt_section()


def _phases_summary(phases: list[InvestigationPhaseResult]) -> str:
    lines = []
    for p in phases:
        lines.append(f"[{p['phase_name']}] {p['summary']}")
        for f in p["findings"]:
            if not f["error"] and f["interpretation"]:
                lines.append(f"  • {f['title']}: {f['interpretation'][:200]}")
    return "\n".join(lines)


def _one_phase_evidence(p: InvestigationPhaseResult) -> str:
    """Verbatim evidence block for ONE phase — its findings' SQL + result tables (≤20 rows each)."""
    lines = [f"\n=== {p['phase_name']} ==="]
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


def _phases_evidence(phases: list[InvestigationPhaseResult]) -> str:
    return "\n".join(_one_phase_evidence(p) for p in phases)


_EVIDENCE_BUDGET = 6000
_EV_DIGEST_SYS = (
    "You compress a single investigation phase's query evidence into 1-2 sentences, PRESERVING the key "
    "numbers (values, deltas, percentages, counts). No preamble, no commentary — just the facts."
)


def _phases_evidence_budgeted(phases: list[InvestigationPhaseResult], budget: int = _EVIDENCE_BUDGET) -> str:
    """Per-phase evidence packed VERBATIM up to ``budget`` chars (exact numbers preserved for grounding);
    phases that overflow are folded into a number-preserving digest (tree-reduce) rather than truncated
    away. Replaces the old ``evidence_log[:6000]``; fails open to plain truncation. Small investigations
    (under budget) are returned unchanged with no LLM call."""
    blocks = [(p["phase_name"], _one_phase_evidence(p)) for p in phases]
    full = "\n".join(b for _, b in blocks)
    if len(full) <= budget:
        return full

    try:
        from pydantic import BaseModel

        from aughor.llm.provider import get_provider
        from aughor.llm.reduce import partitioned_reduce

        class _EvidenceDigest(BaseModel):
            text: str

        provider = get_provider("fast")

        kept: list[str] = []
        overflow: list[tuple[str, str]] = []
        used = 0
        for name, block in blocks:
            if used + len(block) <= budget:
                kept.append(block)
                used += len(block)
            else:
                overflow.append((name, block))

        if not overflow:                       # everything fit (the >budget was just join slack)
            return full
        if not kept:                           # nothing fit verbatim — truncate rather than a
            return full[:budget]               # digest-only evidence log (no verbatim to ground on)

        def _summ(name: str, blocks_: list[str]) -> str:
            body = blocks_[0][:4000]
            out = provider.complete(
                system=_EV_DIGEST_SYS,
                user=f"Phase evidence:\n{body}\n\nCompress to 1-2 sentences, keeping the key numbers.",
                response_model=_EvidenceDigest, temperature=0.2,
            )
            return f"[{name}] {out.text.strip()}"

        digest = partitioned_reduce(
            {name: [block] for name, block in overflow},
            summarize_group=_summ,
            combine=lambda parts: "\n".join(parts),
        )
        return (
            "\n".join(kept)
            + f"\n\n=== ADDITIONAL EVIDENCE (summarized — {len(overflow)} phase(s) beyond the "
            f"verbatim budget) ===\n{digest}"
        )
    except Exception:
        return full[:budget]                   # fail-open to today's behavior


# ── Phase nodes ───────────────────────────────────────────────────────────────

def _extract_data_date_range(scan_context: str, table: str = "") -> tuple:
    """Pull the (min, max) date the data actually covers from the DATA PORTRAIT
    text — the [PROFILE] lines carry 'YYYY-MM-DD → YYYY-MM-DD'.

    When ``table`` is given, read THAT table's [PROFILE] line only: on a
    multi-dataset connection the global min/max mixes datasets (ecommerce's
    24 months beside bakehouse's 17 days), which let an empty comparison window
    pass validation because a *sibling* dataset had data there."""
    if table:
        bare = str(table).split(".")[-1].lower()
        for line in (scan_context or "").splitlines():
            if "[PROFILE]" not in line:
                continue
            m = re.search(r"\[PROFILE\]\s+(\S+)", line)
            name = (m.group(1) if m else "").lower()
            if name == str(table).lower() or name.split(".")[-1] == bare:
                dates = re.findall(r"\d{4}-\d{2}-\d{2}", line)
                if dates:
                    return min(dates), max(dates)
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", scan_context or "")
    if not dates:
        return None, None
    return min(dates), max(dates)


def _resolve_probe_ref(table: str, date_column: str) -> tuple[str, str]:
    """Resolve (table_ref, column) for a cheap date probe. The date column frequently lives in a
    DIFFERENT table than the metric table (the metric is in order_items but order_purchase_ts is in
    orders, reachable only via a join). Probing the metric table then errors ("column not found"),
    the bounds come back empty, and the window clamp silently no-ops. When date_column is qualified,
    probe the table it names. Shared by the span and density probes; pure string logic."""
    col = str(date_column).split(".")[-1].replace('"', "").replace(";", "")
    _dc = str(date_column).replace('"', "").replace(";", "").strip()
    _dparts = [p for p in _dc.split(".") if p]
    if len(_dparts) >= 3:
        ref = ".".join(_dparts[:-1])                       # schema.table.col → schema.table
    elif len(_dparts) == 2:
        _sch = str(table).replace('"', "").split(".")
        ref = f"{_sch[0]}.{_dparts[0]}" if len(_sch) >= 2 else _dparts[0]   # borrow metric schema
    else:
        ref = str(table).replace('"', "").replace(";", "")
    return ref.replace(";", ""), col


def _measure_date_span(conn_id: str, table: str, date_column: str) -> tuple:
    """Authoritative (min, max) of the metric table's date column via one cheap
    probe. The DATA PORTRAIT is empty on the ADA path (scan_context is never
    populated before intake), so profile-text parsing alone leaves the window
    validation blind — this asks the database itself. Returns (None, None) on
    any failure; the clamp then no-ops."""
    if not conn_id or not table or not date_column:
        return None, None
    db = None
    try:
        from aughor.db.connection import open_connection_for
        db = open_connection_for(conn_id)
        ref, col = _resolve_probe_ref(table, date_column)
        res = db.execute("intake_span", f"SELECT MIN({col}), MAX({col}) FROM {ref}")
        if res.error or not res.rows or len(res.rows[0]) < 2:
            return None, None
        lo, hi = str(res.rows[0][0])[:10], str(res.rows[0][1])[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", lo) and re.match(r"^\d{4}-\d{2}-\d{2}$", hi):
            return lo, hi
        return None, None
    except Exception:
        return None, None
    finally:
        if db is not None:
            try:
                db.close()
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "intake probe connection close failed; probe result already "
                               "returned", counter="ada.intake_probe_close")


def _metric_definition_receipt(intake_data: dict) -> str:
    """T4-1 — a plain-language receipt of HOW the metric was computed, so a silently-chosen definition
    is visible to the reader and can be challenged. Every deep run picks ONE reading of an ambiguous
    metric (a "refund rate" as value-weighted refund$/revenue$ vs a count-based orders-with-refund/
    orders; "revenue" off invoices vs line items) with no disclosure. Surfaces: the formula, the ratio
    interpretation (value-weighted vs a plain average), the observation grain, and the data-coverage
    window. Deterministic; "" when no metric is set. Never raises."""
    try:
        label = (intake_data.get("metric_label") or "").strip()
        sql = (intake_data.get("metric_sql") or "").strip()
        if not label and not sql:
            return ""
        parts: list[str] = []
        if sql:
            parts.append(f"computed as `{sql}`")
        if _metric_is_composite_ratio(sql):
            # Describe the ACTUAL aggregates (a composite ratio can be value-weighted SUM/SUM OR a
            # count-based COUNT/COUNT — the two can diverge, and which was chosen is the silent call
            # this receipt exists to disclose; don't assume SUM).
            _src = _parse_ratio_sources(sql)
            _na = (_src or {}).get("num_agg", "")
            _da = (_src or {}).get("den_agg", "")
            if _na == "SUM" and _da == "SUM":
                parts.append("a value-weighted ratio — SUM(numerator) ÷ SUM(denominator), not a "
                             "count-based rate")
            elif _na == "COUNT" and _da == "COUNT":
                parts.append("a count-based rate — COUNT(events) ÷ COUNT(population), not value-weighted")
            else:
                parts.append("a ratio of two aggregates")
            parts.append("(a value-weighted and a count-based reading can differ materially; this "
                         "reading was chosen automatically)")
        elif re.search(r"\b(avg|mean|median)\s*\(", sql, re.I):
            parts.append("a per-record average (non-additive — not summed across groups)")
        _table = (intake_data.get("metric_table") or "").strip()
        if _table:
            parts.append(f"on {_table}")
        coverage = (intake_data.get("data_coverage_label") or "").strip()
        if coverage:
            parts.append(f"over data spanning {coverage}")
        body = "; ".join(parts)
        return f"{label or 'Metric'} — {body}." if body else ""
    except Exception:
        return ""


def _observation_window_is_wrong(obs_start, obs_end, cov_min: str, cov_max: str) -> bool:
    """T4-2 — should the intake's observation window be replaced by the probed data-coverage window?
    True when the LLM left it empty, or it falls (partly) OUTSIDE the real data span — the sample-
    inferred-guess case (intake said "2023-01 to 2023-03" on data spanning 2023-01 → 2025-01). ISO
    dates compare lexically. Conservative: a window fully inside the real span is left untouched."""
    s = (obs_start or "")[:10]
    e = (obs_end or "")[:10]
    return not s or not e or e < cov_min or s > cov_max


def _populated_month_count(conn_id: str, table: str, date_col: str, start: str, end: str) -> "int | None":
    """Count of distinct POPULATED months of the metric's date column within [start, end]. A
    cheap, dialect-robust probe (COUNT DISTINCT of the 'YYYY-MM' text prefix). Returns None on any
    failure (fail-open, like the span probe). Feeds the density guard: a window whose calendar span
    survived the clamp but whose real data is sparse (a gap / slow ramp) is still a thin PoP baseline."""
    if not conn_id or not table or not date_col or not start or not end:
        return None
    s, e = str(start)[:10], str(end)[:10]
    if not (re.match(r"^\d{4}-\d{2}-\d{2}$", s) and re.match(r"^\d{4}-\d{2}-\d{2}$", e)):
        return None
    db = None
    try:
        from aughor.db.connection import open_connection_for
        db = open_connection_for(conn_id)
        ref, col = _resolve_probe_ref(table, date_col)
        res = db.execute(
            "intake_density",
            f"SELECT COUNT(DISTINCT substr(CAST({col} AS VARCHAR), 1, 7)) "
            f"FROM {ref} WHERE {col} >= '{s}' AND {col} <= '{e}'",
        )
        if res.error or not res.rows or res.rows[0][0] is None:
            return None
        return int(res.rows[0][0])
    except Exception:
        return None
    finally:
        if db is not None:
            try:
                db.close()
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "intake probe connection close failed; probe result already "
                               "returned", counter="ada.intake_probe_close")


def _monthly_counts(conn_id: str, table: str, date_col: str, start: str, end: str) -> "list | None":
    """Ordered [(YYYY-MM, row_count)] for the metric's date column within [start, end]. Cheap and
    dialect-robust (GROUP BY the 'YYYY-MM' text prefix). Feeds the trailing-partial guard. Returns
    None on any failure (fail-open, like the other probes)."""
    if not conn_id or not table or not date_col or not start or not end:
        return None
    s, e = str(start)[:10], str(end)[:10]
    if not (re.match(r"^\d{4}-\d{2}-\d{2}$", s) and re.match(r"^\d{4}-\d{2}-\d{2}$", e)):
        return None
    db = None
    try:
        from aughor.db.connection import open_connection_for
        db = open_connection_for(conn_id)
        ref, col = _resolve_probe_ref(table, date_col)
        res = db.execute(
            "intake_monthly",
            f"SELECT substr(CAST({col} AS VARCHAR), 1, 7) AS m, COUNT(*) AS n "
            f"FROM {ref} WHERE {col} >= '{s}' AND {col} <= '{e}' GROUP BY 1 ORDER BY 1",
        )
        if res.error or not res.rows:
            return None
        return [(str(r[0]), int(r[1])) for r in res.rows if r[0] is not None]
    except Exception:
        return None
    finally:
        if db is not None:
            try:
                db.close()
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "intake probe connection close failed; probe result already "
                               "returned", counter="ada.intake_probe_close")


def _question_pins_period(question: str, obs_start: str, obs_end: str) -> bool:
    """True when the question explicitly names a calendar period (a 4-digit year) that the
    observation window already covers — the user asked for THIS specific period, so it must
    NOT be re-anchored to 'most recent'. A relative framing ('last N months', 'recent',
    'trailing', or no date at all) returns False, so the clamp is free to re-anchor it to the
    data's latest window."""
    q = (question or "").lower()
    q_years = set(re.findall(r"\b(20\d{2})\b", q))
    if not q_years:
        return False  # no explicit year → relative framing, safe to re-anchor
    obs_years = {(obs_start or "")[:4], (obs_end or "")[:4]}
    return bool(q_years & obs_years)


# When the (clipped) prior window is shorter than this fraction of the observation
# window, an absolute period-over-period total or % change between them is a duration
# artifact (a sum scales with length), NOT a run-rate shift — flag it and steer the
# planner to average per-period run-rate rather than headlining the raw totals.
_POP_DURATION_MISMATCH = 0.66
# Stable machine-readable marker embedded in the coverage note when the mismatch fires.
# The synthesis reads it back to ENFORCE the run-rate reframe deterministically (rather
# than trusting the narrator to heed an advisory note). Single source of truth for both.
_POP_MISMATCH_SIGNATURE = "DURATION ARTIFACTS"
# The density guard only fires on a comparison window of at least this many calendar months —
# below it, "few populated periods" is normal (a genuinely short window), not a sparse baseline.
_MIN_SPARSE_SPAN_MONTHS = 4
# Trailing-partial guard: the final observation month is flagged as likely-incomplete when its row
# count falls below this fraction of the window's typical (median) month, over at least N months.
_TRAILING_PARTIAL_RATIO = 0.5
_MIN_TRAILING_MONTHS = 3


def _clamp_intake_to_coverage(intake, dmin, dmax, question: str = ""):
    """Deterministically fit the intake's windows to the data that actually exists.
    The LLM-retry path merely *asks* for a correction; this enforces it. Returns a
    coverage note (str) when anything was adjusted, else None.

    - Observation is clipped to [dmin, dmax]; if it misses the data entirely it
      becomes the full available history.
    - A RELATIVE 'last-N / recent' window the LLM mis-anchored to an OLDER in-range
      period is re-anchored to END at dmax (the data's latest point), and its
      comparison set to the prior window — so we analyse the most recent data and a
      real prior-period (YoY) comparison becomes available instead of being forfeited.
      Specific periods named in the question (an explicit year) are left literal.
    - A comparison with NO overlap collapses onto the observation window and is
      relabelled — "compare vs an empty period" is the bug class this kills.
    - When the available history is short (<~45 days), the label says so and the
      note tells the planner to use a daily/weekly grain and skip MoM/YoY.
    """
    from datetime import datetime, timedelta

    if not dmin or not dmax or getattr(intake, "cross_sectional", False):
        return None
    notes = []

    def _clip(start, end):
        s, e = (start or "")[:10], (end or "")[:10]
        if not s or not e:
            return s, e, False
        if e < dmin or s > dmax:           # no overlap at all
            return dmin, dmax, True
        cs, ce = max(s, dmin), min(e, dmax)
        return cs, ce, (cs != s or ce != e)

    os_, oe_, o_changed = _clip(intake.observation_start, intake.observation_end)
    if o_changed:
        notes.append(
            f"observation window clipped to the data's actual coverage [{os_} → {oe_}] "
            f"(requested {intake.observation_start} → {intake.observation_end}, data spans {dmin} → {dmax})"
        )
        intake.observation_start, intake.observation_end = os_, oe_

    # ── Re-anchor a mis-placed RELATIVE window to the data's most-recent point ──
    # The LLM picks observation dates for a "last N / recent / trailing" framing, but it
    # sometimes anchors to an OLDER window that happens to sit inside the data (e.g. "last
    # 12 months" → calendar 2023 when the data runs through 2024) — analysing stale data
    # AND forfeiting the prior-period comparison the data actually supports. Deterministically
    # shift the window to END at dmax (preserving length) and set the comparison to the prior
    # equal-length window — UNLESS the question pins a specific period the window matches.
    try:
        _os0 = (intake.observation_start or "")[:10]
        _oe0 = (intake.observation_end or "")[:10]
        if _os0 and _oe0 and not _question_pins_period(question, _os0, _oe0):
            _dmax_d = datetime.fromisoformat(dmax[:10])
            _dmin_d = datetime.fromisoformat(dmin[:10])
            _oe_d = datetime.fromisoformat(_oe0)
            _os_d = datetime.fromisoformat(_os0)
            _win = (_oe_d - _os_d).days
            _gap = (_dmax_d - _oe_d).days
            if _win >= 0 and _gap > 31:   # window ends >1 month before the data's latest point
                _new_os = max(_dmax_d - timedelta(days=_win), _dmin_d)
                intake.observation_start = _new_os.date().isoformat()
                intake.observation_end = _dmax_d.date().isoformat()
                _new_ce = _new_os - timedelta(days=1)
                intake.comparison_start = (_new_ce - timedelta(days=_win)).date().isoformat()
                intake.comparison_end = _new_ce.date().isoformat()
                _months = max(1, round(_win / 30.44))
                intake.observation_label = f"Last {_months} months (most recent in data)"
                intake.comparison_label = f"Prior {_months} months"
                notes.append(
                    f"observation re-anchored to the data's most recent window "
                    f"[{intake.observation_start} → {intake.observation_end}] — a relative "
                    f"'last/recent' framing had been placed at an older window ending {_oe0}, "
                    f"{_gap} days before the latest data {dmax[:10]}; the prior-period (YoY) "
                    f"comparison is now available"
                )
    except (ValueError, TypeError) as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "re-anchor is best-effort on malformed dates; leave the window as the "
                 "clip step left it", counter="intake.reanchor_parse_failed")

    cs_ = (getattr(intake, "comparison_start", "") or "")[:10]
    ce_ = (getattr(intake, "comparison_end", "") or "")[:10]
    if cs_ and ce_:
        if ce_ < dmin or cs_ > dmax:   # no overlap → no prior period exists
            intake.comparison_start, intake.comparison_end = intake.observation_start, intake.observation_end
            intake.comparison_label = "Same period (no prior period exists in the data)"
            notes.append(
                f"comparison period {cs_} → {ce_} contains no data (data spans {dmin} → {dmax}); "
                f"no prior period exists — trend/YoY/baseline comparisons are not possible"
            )
        else:                          # partial overlap → clip (a half-empty baseline skews stats)
            ncs, nce, c_changed = _clip(cs_, ce_)
            if c_changed:
                intake.comparison_start, intake.comparison_end = ncs, nce
                notes.append(
                    f"comparison window clipped to the data's actual coverage [{ncs} → {nce}] "
                    f"(requested {cs_} → {ce_})"
                )

    # ── Duration-mismatch guard ────────────────────────────────────────────────
    # After clipping, the prior window can end up FAR shorter than the observation
    # (e.g. a "last 56 months" run whose prior-56-month window was clipped to the ~3
    # real months that exist before the data starts). The re-anchor step labelled it
    # "Prior 56 months", but it is now a stub — so an absolute period-over-period total
    # or % change between the two is a duration artifact (~18× purely from length), not
    # a run-rate shift. Relabel the comparison honestly and tell the planner to report
    # an AVERAGE per-period run-rate instead of headlining the raw totals.
    try:
        _cs2 = (getattr(intake, "comparison_start", "") or "")[:10]
        _ce2 = (getattr(intake, "comparison_end", "") or "")[:10]
        _obs_s = (intake.observation_start or "")[:10]
        _obs_e = (intake.observation_end or "")[:10]
        _is_same = (_cs2 == _obs_s and _ce2 == _obs_e)   # comparison already collapsed onto obs
        if _cs2 and _ce2 and not _is_same:
            _obs_days = (datetime.fromisoformat(_obs_e) - datetime.fromisoformat(_obs_s)).days + 1
            _cmp_days = (datetime.fromisoformat(_ce2) - datetime.fromisoformat(_cs2)).days + 1
            if (_obs_days > 0 and _cmp_days > 0
                    and min(_obs_days, _cmp_days) < _POP_DURATION_MISMATCH * max(_obs_days, _cmp_days)):
                _obs_m = max(1, round(_obs_days / 30.44))
                _cmp_m = max(1, round(_cmp_days / 30.44))
                intake.comparison_label = f"Prior ~{_cmp_m} month(s) available (data begins {dmin[:10]})"
                notes.append(
                    f"comparison window (~{_cmp_m} month(s), {_cs2} → {_ce2}) is far shorter than the "
                    f"observation window (~{_obs_m} months) — absolute period-over-period totals and % "
                    f"changes between them are {_POP_MISMATCH_SIGNATURE}, not run-rate shifts; report "
                    f"AVERAGE per-period run-rate and do NOT headline the absolute totals or their % change"
                )
    except (ValueError, TypeError) as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "duration-mismatch guard is best-effort on malformed dates",
                 counter="intake.duration_mismatch_parse_failed")

    try:
        cov_days = (datetime.fromisoformat(intake.observation_end)
                    - datetime.fromisoformat(intake.observation_start)).days + 1
    except (ValueError, TypeError):
        cov_days = None
    if cov_days is not None and cov_days < 45:
        intake.observation_label = (
            f"Available history ({intake.observation_start} → {intake.observation_end}, ~{cov_days} days)"
        )
        notes.append(
            f"only ~{cov_days} days of history exist — analyse at daily/weekly grain; "
            f"month-over-month, year-over-year and 12-month framings are not applicable"
        )

    if not notes:
        return None
    return "DATA COVERAGE: " + "; ".join(notes) + "."


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


def _months_between(a: str, b: str) -> "int | None":
    """Inclusive calendar-month span between two ISO dates (a ≤ b): (y2−y1)·12 + (m2−m1) + 1."""
    try:
        ya, ma = int(a[:4]), int(a[5:7])
        yb, mb = int(b[:4]), int(b[5:7])
    except (ValueError, TypeError, IndexError):
        return None
    return (yb - ya) * 12 + (mb - ma) + 1


def _sparse_comparison_decision(intake, span_months, populated) -> "str | None":
    """Pure decision half of the density guard: when a comparison window spans enough calendar
    months but only a fraction are populated, its absolute total is a thin baseline. Relabel the
    window honestly and return a run-rate note carrying the mismatch signature (so the enforcing
    reframe applies). Returns None when the window is dense enough or the inputs are unknown."""
    if span_months is None or populated is None:
        return None
    if span_months >= _MIN_SPARSE_SPAN_MONTHS and 0 <= populated < _POP_DURATION_MISMATCH * span_months:
        intake.comparison_label = (
            f"Prior window sparsely populated ({populated} of ~{span_months} months have data)"
        )
        return (
            f"the comparison window spans ~{span_months} months but only {populated} contain data — its "
            f"absolute total is a thin baseline, so period-over-period totals and % changes are "
            f"{_POP_MISMATCH_SIGNATURE}, not run-rate shifts; use AVERAGE per-populated-period run-rate"
        )
    return None


def _flag_sparse_comparison(intake, conn_id: str, table: str, date_col: str,
                            span_guard_fired: bool) -> "str | None":
    """Density guard — complements the date-SPAN guard in `_clamp_intake_to_coverage`. A comparison
    window whose calendar span survived the clamp but is SPARSELY populated (an internal gap, or a
    slow product ramp) is still a thin PoP baseline that the span check cannot see. Probes populated
    months in the FINAL comparison window and, on a sparse result, relabels + returns a run-rate note.
    Skipped when the span guard already fired (no double-flag), for a cross-sectional intake, or when
    no distinct prior period exists."""
    if span_guard_fired or getattr(intake, "cross_sectional", False):
        return None
    cs = (getattr(intake, "comparison_start", "") or "")[:10]
    ce = (getattr(intake, "comparison_end", "") or "")[:10]
    os_ = (getattr(intake, "observation_start", "") or "")[:10]
    oe_ = (getattr(intake, "observation_end", "") or "")[:10]
    if not cs or not ce or (cs == os_ and ce == oe_):   # no distinct prior period
        return None
    span_months = _months_between(cs, ce)
    populated = _populated_month_count(conn_id, table, date_col, cs, ce)
    return _sparse_comparison_decision(intake, span_months, populated)


def _trailing_partial_decision(intake, monthly_counts) -> "str | None":
    """Pure decision half of the trailing-partial guard: when the LAST month of the observation
    window carries far fewer rows than the window's typical (median) month, it is likely an
    INCOMPLETE period that reads as a false drop. Flag it honestly (do NOT overclaim a real
    decline — a genuine crash looks the same, so the note asks the reader to verify completeness).
    Returns a note, else None."""
    if not monthly_counts or len(monthly_counts) < _MIN_TRAILING_MONTHS:
        return None
    counts = [n for _, n in monthly_counts]
    last_m, last_n = monthly_counts[-1]
    prior = sorted(counts[:-1])
    if not prior:
        return None
    mid = (prior[len(prior) // 2] if len(prior) % 2
           else (prior[len(prior) // 2 - 1] + prior[len(prior) // 2]) / 2)
    if mid > 0 and last_n < _TRAILING_PARTIAL_RATIO * mid:
        intake.observation_label = (
            (getattr(intake, "observation_label", "") or "").rstrip()
            + f" — final period {last_m} may be incomplete"
        ).strip()
        return (
            f"the final observation period {last_m} has {last_n} rows vs a typical ~{mid:.0f}/month — it "
            f"is likely an INCOMPLETE (partial) period, so a drop in the last period may be a reporting "
            f"artifact, not a real decline; verify the period is complete before attributing a decline to it"
        )
    return None


def _flag_trailing_partial(intake, conn_id: str, table: str, date_col: str) -> "str | None":
    """Trailing-partial guard — the profiler computes `trailing_partial` for the whole table, but
    the intake window selection never consumed it, so an incomplete final month reads as a sharp
    drop. Probe the observation window's monthly volumes and flag a likely-incomplete final period.
    Skipped for a cross-sectional intake or a window with no dates."""
    if getattr(intake, "cross_sectional", False):
        return None
    os_ = (getattr(intake, "observation_start", "") or "")[:10]
    oe_ = (getattr(intake, "observation_end", "") or "")[:10]
    if not os_ or not oe_:
        return None
    return _trailing_partial_decision(intake, _monthly_counts(conn_id, table, date_col, os_, oe_))


def _cap_confidence_on_trust_advisory(synth, phases) -> bool:
    """Report-quality wiring gap #2: a report cannot honestly stand at HIGH confidence while a
    trust advisory (an unverified/flagged finding) is shown unreconciled beneath it. Cap
    HIGH → MEDIUM when any finding carries a ``trust_caveat``; returns True when it demoted.
    Deterministic, no-op unless confidence is currently HIGH. Deliberately downstream of the
    claim-grounding check being derived-number-aware (fix #3) so a valid % derivation, which no
    longer trips the caveat, never costs confidence."""
    if not synth or getattr(synth, "confidence", "") != "HIGH":
        return False
    caveats = [f.get("trust_caveat") for p in (phases or []) for f in (p.get("findings") or [])
               if f.get("trust_caveat")]
    if not caveats:
        return False
    synth.confidence = "MEDIUM"
    synth.confidence_justification = (
        "Capped below HIGH — a trust advisory fired on the evidence: "
        + str(caveats[0])
        + (f" (+{len(caveats) - 1} more)" if len(caveats) > 1 else "")
        + ". " + (getattr(synth, "confidence_justification", "") or "")
    ).strip()
    return True


# A trust caveat that says the NUMBER IS WRONG (a computation artifact) — as opposed to merely
# uncertain. These must not just cap confidence; the flagged figures must be visibly reframed so the
# headline/summary can't present an artifact as fact (the inv1 "73% refund rate, premise inverted" miss).
_COMPUTATION_ERROR_CAVEAT_RE = re.compile(
    r"computation error|conditioned denominator|fan-?out|corrupt\w*|not trustworthy|"
    r"could not be computed|formula drift|grain-correct recompute|artifact", re.I)


def _reframe_on_trust_caveat(synth, phases) -> bool:
    """Report-quality fix 4 — make a trust advisory STRUCTURAL, not just a confidence label. The
    prior wiring only demoted HIGH→MEDIUM (``_cap_confidence_on_trust_advisory``); the corrupted
    numbers still rode into the LLM-written headline/executive_summary (inv1 headlined a 73% refund
    rate the guard had already flagged as a conditioned-denominator artifact).

    SCOPED (T3-1): a computation-ERROR caveat is only allowed to floor the WHOLE report when a flagged
    finding's numbers actually appear in the headline/summary — i.e. the conclusion is built on a wrong
    number. When the flagged finding is peripheral (its numbers are NOT headlined — the inv3 case, where
    3 clean channel drivers carried the conclusion and only one internal decomposition finding tripped),
    the report is NOT floored to LOW: the caveat is surfaced in ``data_gaps`` and the existing MEDIUM cap
    stands, so a supporting-evidence hiccup doesn't nuke a grounded answer. Mirrors
    ``_reframe_on_pop_duration_mismatch``; returns True when it acted. Never raises on a missing field."""
    if not synth:
        return False
    err_findings = [(f.get("trust_caveat"), f.get("rows"))
                    for p in (phases or []) for f in (p.get("findings") or [])
                    if f.get("trust_caveat") and _COMPUTATION_ERROR_CAVEAT_RE.search(str(f.get("trust_caveat")))]
    if not err_findings:
        return False

    # Which flagged findings are actually HEADLINED — i.e. a number from the flagged finding appears in
    # the conclusion prose (reuse the numeric-grounding core from the report-quality binding fix)?
    _headline_text = (getattr(synth, "headline", "") or "") + " " + (getattr(synth, "executive_summary", "") or "")
    try:
        from aughor.explorer.verify import grounded_fraction
        headlined = [cav for cav, rows in err_findings if rows and grounded_fraction(_headline_text, rows) > 0.0]
    except Exception:
        headlined = [cav for cav, _ in err_findings]   # fail-safe: treat as headlined (be cautious)

    if headlined:
        lead = headlined[0]
        _es = synth.executive_summary or ""
        if str(lead)[:48].lower() not in _es.lower():
            reframe = (
                f"⚠ A trust check flagged the evidence and the figures below are NOT reliable: {lead} "
                "Do not read the numbers or ranking as fact until they are recomputed. "
            )
            synth.executive_summary = (reframe + _es).strip()[:900]
        # A wrong number carried into the conclusion can't underwrite a confident verdict.
        if getattr(synth, "confidence", "") != "LOW":
            synth.confidence = "LOW"
            synth.confidence_justification = (
                "Floored to LOW — a computation-error trust check fired on a headlined figure: "
                + str(lead) + " " + (getattr(synth, "confidence_justification", "") or "")
            ).strip()
        return True

    # Flagged findings exist but none is headlined — surface honestly without nuking a grounded answer.
    lead = err_findings[0][0]
    _gaps = list(getattr(synth, "data_gaps", None) or [])
    _note = ("A supporting finding was excluded from the conclusion after a trust check flagged it: "
             + str(lead))
    if not any("trust check flagged" in g.lower() for g in _gaps):
        _gaps.insert(0, _note)
    synth.data_gaps = _gaps
    return True


def _reframe_on_pop_duration_mismatch(synth, intake_data, question: str = "") -> bool:
    """Report-quality wiring gap #1 (enforcing half): when the coverage clamp flagged a duration
    mismatch (a short prior window against a long observation), an absolute period-over-period
    total or its % change is a duration artifact. Rather than trust the narrator to heed the
    advisory note, DETERMINISTICALLY neutralise the absolute-change decomposition and reframe the
    summary to run-rate — mirrors the cross-sectional reframe below. Keyed off the coverage note's
    stable signature so it fires exactly when the deterministic guard did. Returns True when it acted."""
    if not synth or not intake_data:
        return False
    if _POP_MISMATCH_SIGNATURE not in (intake_data.get("intake_notes") or ""):
        return False
    # an absolute-change waterfall between mismatched-length windows is meaningless
    synth.attribution_waterfall = []
    _reframe = (
        "The observation and prior windows differ sharply in length, so absolute totals and their "
        "% change between the two periods are duration artifacts, not run-rate shifts — read the "
        "figures below as average per-period run-rate. "
    )
    _es = synth.executive_summary or ""
    if "duration artifact" not in _es.lower() and "run-rate" not in _es.lower():
        synth.executive_summary = (_reframe + _es).strip()[:900]
    _gap = ("The prior period is far shorter than the observation window, so no like-for-like absolute "
            "period-over-period comparison is possible; average per-period run-rate is used instead.")
    _gaps = list(getattr(synth, "data_gaps", None) or [])
    if not any("run-rate" in g.lower() for g in _gaps):
        _gaps.insert(0, _gap)
    synth.data_gaps = _gaps
    return True


_DIAGNOSTIC_RE = re.compile(
    r"where are we losing|losing money|\b(where|which|what)\b[^?]*\b(losing|lose|lost|leak\w*|"
    r"weak\w*|worst|lowest|underperform\w*|hurting|dragging|bleeding|inefficien\w*)\b",
    re.IGNORECASE,
)


def _is_diagnostic_question(q: str) -> bool:
    """Cross-sectional 'where/which is weakest / where are we losing money' questions —
    these have no useful time axis and should run a dimensional weakness scan."""
    return bool(_DIAGNOSTIC_RE.search(q or ""))


# A TEMPORAL-CHANGE question presupposes a movement over time and asks its cause
# ("what drove the change", "why did margin drop", "MoM/YoY change"). These are the OPPOSITE
# of a cross-sectional weakness scan: the honest answer is a period-over-period decomposition,
# or — when no time axis exists — an explicit "no change could be measured". The intake LLM
# frequently mislabels them as cross_sectional "driver" questions, which silently answers
# "where is X weakest" instead of "what changed"; this detector lets us override that.
_TEMPORAL_CHANGE_RE = re.compile(
    r"\b(drove|driver[s]?\s+of|caused|cause\s+of|reason[s]?\s+for|behind|why)\b[^?]*\b"
    r"(change[d]?|drop\w*|fell|fall\w*|declin\w*|decreas\w*|increas\w*|rose|rise|grew|grow\w*|"
    r"jump\w*|spike[d]?|surg\w*|plung\w*|shift\w*|moved?|swing\w*|trend\w*)\b"
    r"|\bwhat\s+changed\b"
    r"|\b(month[-\s]over[-\s]month|year[-\s]over[-\s]year|mom|yoy|qoq|wow)\b"
    r"|\b(vs\.?|versus|compared\s+to|relative\s+to|since)\s+(last|prior|previous|the\s+previous)\b",
    re.IGNORECASE,
)


def _is_temporal_change_question(q: str) -> bool:
    """Does the question ask what changed over time (a period-over-period premise)?"""
    return bool(_TEMPORAL_CHANGE_RE.search(q or ""))


def _scrub_xsec_reasoning(notes: str) -> str:
    """After F1 forces the TEMPORAL route, the intake LLM's own prose may still argue the opposite
    ("cross_sectional=true … compare ACROSS dimensions, not over time"). Displaying that verbatim
    makes the spec contradict the analysis that actually ran. Drop the sentences that assert the
    cross-sectional conclusion; the authoritative routing line we prepend says what we actually did.
    Conservative — only removes clauses that name the cross-sectional decision."""
    if not notes:
        return notes
    out = notes
    for pat in (
        r"[^.]*\bcross[_\s-]?sectional\s*=?\s*true[^.]*\.",
        r"[^.]*\bset\s+cross[_\s-]?sectional[^.]*\.",
        r"[^.]*\bRevised:\s*cross[_\s-]?sectional[^.]*\.",
        r"[^.]*\btreat\s+(?:this\s+)?as\s+cross[_\s-]?sectional[^.]*\.",
        r"[^.]*compare[^.]*\bacross\b[^.]*\bdimensions?\b[^.]*\.",
    ):
        out = re.sub(pat, "", out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip()


_AGG_RE = r"(?:SUM|AVG|COUNT|MIN|MAX|MEDIAN|STDDEV|VARIANCE)"

# Shared grounding rule appended to every ADA plan node's terse system prompt so the
# coder treats the SCHEMA as authoritative and JOINs to reach columns on other tables
# (e.g. a timestamp on `orders` when the metric is on `invoices`) instead of inventing one.
_ADA_SQL_GROUNDING = (
    " SCHEMA FIDELITY: use ONLY table and column names that appear EXPLICITLY in the SCHEMA — "
    "never invent or rename a column. If a column you need (a date/timestamp, a dimension, or a "
    "key) is not on the metric table, find the table in the SCHEMA that HAS it and JOIN to it "
    "using the DETECTED JOIN PATHS; never attach a date column to a table that lacks one. "
    "CRITICAL: when a column is given as table.column (e.g. orders.order_ts), reference it with "
    "THAT EXACT table qualifier everywhere (SELECT, WHERE, GROUP BY) — do NOT re-qualify it to the "
    "metric table. Writing `invoices.order_ts` when the column lives on `orders` is the #1 error; "
    "join orders and write `orders.order_ts`."
    " TEMPORAL GROUNDING: the observation and comparison periods are given to you as EXPLICIT date "
    "ranges. Filter using those LITERAL dates as DATE literals — e.g. `WHERE orders.order_ts >= "
    "DATE '2023-03-10' AND orders.order_ts < DATE '2024-03-10'`. NEVER use CURRENT_DATE, NOW(), "
    "GETDATE(), SYSDATE, or DATE_SUB/DATE_ADD/DATEADD interval arithmetic relative to today — the "
    "data is HISTORICAL, so a window relative to the current date silently returns ZERO rows (and "
    "DATE_SUB/DATE_ADD are not DuckDB functions). Use the given literal dates verbatim."
)


_RELATIVE_DATE_RE = re.compile(
    r"\bcurrent_date\b|\bcurrent_timestamp\b|\bsysdate\b|\b(?:now|getdate|date_sub|date_add|dateadd)\s*\(",
    re.IGNORECASE,
)


def _uses_relative_date(sql: str) -> bool:
    """True when SQL anchors a date window to TODAY (CURRENT_DATE / NOW() / DATE_SUB / …) instead
    of the literal observation/comparison dates. On HISTORICAL data those windows return ZERO rows
    — the WCH-DS failure class — so the phase runner uses this to force a corrective re-plan."""
    return bool(_RELATIVE_DATE_RE.search(sql or ""))


def _unsafe_metric_sql(sql: str):
    """Flag a metric EXPRESSION that will over-count / inflate. A metric is a single
    aggregate over columns — it must NOT embed a subquery (the global-scalar-subquery-
    in-SUM that produced -$3.1B/dimension) or multiply/nest aggregates. Returns a reason
    string or None. High-precision: stays silent on clean metrics like SUM(price*qty)."""
    if not sql:
        return None
    s = sql.strip()
    if re.search(r"\bSELECT\b", s, re.I):
        return "the metric embeds a subquery (a SELECT inside the aggregate) — a global value subtracted per row over-counts massively"
    if re.search(rf"{_AGG_RE}\s*\([^()]*\)\s*\*\s*{_AGG_RE}\s*\(", s, re.I):
        return "the metric multiplies two aggregates (product-of-aggregates) — this over-counts; use SUM(a*b), not SUM(a)*SUM(b)"
    if re.search(rf"{_AGG_RE}\s*\((?:[^()]*)\b{_AGG_RE}\s*\(", s, re.I):
        return "the metric nests an aggregate inside another aggregate"
    return None


def _safe_metric_fallback(sql: str) -> str:
    """Deterministically reduce an unsafe metric to a clean single aggregate: SUM of the
    first measure-looking column referenced (revenue/margin/sales/...), else SUM of the
    first aggregated column, else COUNT(*)."""
    measure = re.search(
        r"\b([a-z_][a-z0-9_]*(?:revenue|sales|margin|price|amount|spend|cost|profit|value|gmv|paid|net)[a-z0-9_]*)\b",
        (sql or "").lower(),
    )
    if measure:
        return f"SUM({measure.group(1)})"
    m = re.search(r"\b(?:SUM|AVG)\s*\(\s*([a-z_][a-z0-9_.]*)", sql or "", re.I)
    if m:
        return f"SUM({m.group(1)})"
    return "COUNT(*)"


def _render_origin_finding_section(origin: Optional[dict]) -> str:
    """Render the structured ``origin_finding`` into INTAKE_PROMPT's additive ORIGIN
    FINDING section. Returns "" when there is no origin (a cold-start question), so a
    normal investigation's prompt is byte-for-byte unchanged. When present, it binds
    ADA's spec to the finding the explorer already established — so a drill EXTENDS that
    work (explains why) instead of re-deriving the metric/tables/window from scratch."""
    if not origin:
        return ""
    finding = (origin.get("finding") or "").strip()
    sql = (origin.get("sql") or "").strip()
    tables = ", ".join(origin.get("tables") or [])
    cells = (origin.get("result_cells") or "").strip()
    lines = [
        "ORIGIN FINDING — this investigation is DRILLING a specific result that background",
        "exploration ALREADY established. Do NOT re-derive or re-prove it; your job is to",
        "explain/decompose WHY it holds. Anchor your spec on it:",
    ]
    if finding:
        lines.append(f'  Established finding: "{finding}"')
    if tables:
        lines.append(f"  Tables it used: {tables}")
    if cells:
        lines.append(f"  Grounded result values it produced: {cells}")
    if sql:
        lines.append("  Source query (the exact SQL that produced it):")
        lines.append("  " + sql.replace("\n", "\n  "))
    lines.append(
        "  BINDING: set metric_sql / metric_table / date_column to MATCH this query's "
        "metric and tables, and PRESERVE its filters (e.g. a WHERE status='delivered') "
        "— they are part of the finding's definition; carrying them is what makes your "
        "numbers reconcile with the established result. Reuse them verbatim where the "
        "question targets the same metric (this overrides the default 'include all rows' "
        "rule above); only extend for the NEW angle the question asks, and keep the same "
        "observation window unless the question explicitly changes it."
    )
    return "\n".join(lines) + "\n"


# ── P1: canonical-metric pinning at intake ─────────────────────────────────────────────
# A live audit run parsed the "Fragrance refund rate" question into a count-based rate
# (COUNT(DISTINCT refund_id) / COUNT(DISTINCT order_id) * 100) that the cross-section scan could
# not decompose → the report degraded to "the cause remains unidentified", and the count-vs-value
# reading varied run-to-run. When the connection GOVERNS the same metric (curated catalog /
# north-star / verified ontology), pin the intake's formula to the governed one so the breakdown
# computes on a stable, decomposable definition — closing the loop between T4-1's *disclosure* of
# the reading and actual accuracy. Deterministic, flag-gated (`ada.pin_canonical_metric`), and
# conservative: the LLM's formula is only replaced when a governed metric matches the label on its
# distinctive tokens, its SQL is a bare substitutable aggregate, and a dry-run confirms it runs over
# the metric table — so pinning can never make a run worse (fail-open on every uncertainty).

_UNIT_CONVERSION_RE = re.compile(
    r"(?:SUM|AVG|MIN|MAX)\s*\(\s*([A-Za-z_][\w.]*)\s*\)\s*(?:/\s*(100|1000)(?:\.0+)?|\*\s*0?\.0*1)\b"
    r"|([A-Za-z_][\w.]*)\s*(?:/\s*(100|1000)(?:\.0+)?|\*\s*0?\.0*1)\b",
    re.IGNORECASE,
)


def _detect_unit_conversion(sql: str) -> Optional[str]:
    """The column an LLM-planned metric divides by a 100/1000 constant, or None.

    A planner sometimes invents a unit story for an integer money column ("totalPrice
    is stored in cents") and bakes ``SUM(totalPrice)/100.0`` into the metric — every
    downstream number is then 100x off. The conversion is detectable syntactically;
    whether it's RIGHT is decidable from data (see _unit_conversion_disproved)."""
    if not sql:
        return None
    m = _UNIT_CONVERSION_RE.search(sql)
    if not m:
        return None
    col = (m.group(1) or m.group(3) or "").split(".")[-1].strip()
    return col or None


def _unit_conversion_disproved(conn, connection_id: str, metric_table: str, col: str) -> bool:
    """True when the data PROVES the converted column is already in base units.

    Deterministic probe: if the table has a multiplicative sibling relation
    ``col ≈ other × qty`` holding on (a sample of) rows, then ``col`` shares
    ``other``'s unit — dividing only ``col`` by 100 is provably inconsistent.
    Candidate pairs come from the table's other numeric, non-identifier columns
    (≤6 → ≤15 pairs, one probe query total). False on any doubt (fail-open:
    an unproven conversion is caveated, never rewritten)."""
    if conn is None or not metric_table or not col:
        return False
    try:
        from aughor.tools.profiler import is_key_like
        bare = str(metric_table).replace(";", "").strip().rsplit(".", 1)[-1]
        tres = conn.execute(
            "intake_unit_probe",
            "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_name = '{bare}'",
        )
        if getattr(tres, "error", None) or not getattr(tres, "rows", None):
            return False
        numeric = [
            str(c) for c, t in tres.rows
            if any(k in str(t or "").upper() for k in ("INT", "DECIMAL", "DOUBLE", "FLOAT", "NUMERIC", "REAL"))
            and str(c).lower() != col.lower()
            and not is_key_like(str(c))
        ][:6]
        if len(numeric) < 2:
            return False
        ref = str(metric_table).replace(";", "").strip()
        checks, labels = [], []
        for i, a in enumerate(numeric):
            for b in numeric[i + 1:]:
                labels.append((a, b))
                checks.append(
                    f"AVG(CASE WHEN ABS({col} - ({a} * {b})) <= 0.01 * GREATEST(ABS({col}), 1) "
                    f"THEN 1.0 ELSE 0.0 END)"
                )
        probe = f"SELECT {', '.join(checks)} FROM {ref}"
        res = conn.execute("intake_unit_probe", probe)
        if getattr(res, "error", None) or not res.rows:
            return False
        row = res.rows[0]
        vals = [float(v) for v in row
                if isinstance(v, (int, float)) or (isinstance(v, str) and v.replace(".", "", 1).isdigit())]
        # col == a*b for (nearly) every row — same unit as its factors
        return any(v >= 0.999 for v in vals)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "unit-conversion probe is best-effort (unproven conversion is "
                      "caveated, never rewritten)", counter="ada.unit_probe")
        return False


_STRIP_CONVERSION_RE = re.compile(r"\s*(?:/\s*(?:100|1000)(?:\.0+)?|\*\s*0?\.0*1)\b")


def _is_substitutable_metric_sql(sql: str) -> bool:
    """True when ``sql`` is a bare aggregate EXPRESSION (no SELECT / FROM / ;), so it can be inlined
    into the phase templates the scan builds (``CASE WHEN <dim> THEN {metric_sql} END``, additive and
    ratio SUM scans). Excludes a governed north-star ``value_sql`` (a full query with FROM/WHERE) and
    any statement terminator, either of which would break substitution."""
    s = (sql or "").strip()
    if not s or ";" in s:
        return False
    up = f" {s.upper()} "
    if "SELECT" in up or " FROM " in up:
        return False
    return bool(re.search(r"\b(SUM|COUNT|AVG|MIN|MAX)\s*\(", up))


def _match_canonical_metric(metric_label: str, metric_sql: str, metrics: list):
    """Deterministically match the intake's metric to a governed ``CanonicalMetric`` on DISTINCTIVE
    tokens. ``_label_tokens`` drops structural/measure words, so 'Fragrance refund rate' → {fragrance,
    refund} and a governed 'refund_rate' → {refund}; requiring the governed tokens ⊆ the label tokens
    is a strong, conservative match (a bare generic name like 'total revenue' → {} never matches).
    Returns the best substitutable candidate or None. Tie-break: prefer a candidate whose ratio-ness
    matches the intake's, then higher provenance rank, then more distinctive tokens (more specific)."""
    label_toks = _label_tokens(metric_label)
    if not label_toks:
        return None
    intake_ratio = _metric_is_ratio(metric_sql, metric_label)
    best = None
    best_key = None
    for m in metrics:
        if not _is_substitutable_metric_sql(getattr(m, "sql", "")):
            continue
        canon_toks = _label_tokens(f"{getattr(m, 'name', '')} {getattr(m, 'label', '')}")
        if not canon_toks or not canon_toks <= label_toks:
            continue
        ratio_align = int(_metric_is_ratio(m.sql, getattr(m, "label", "")) == intake_ratio)
        key = (ratio_align, int(getattr(m, "rank", 0)), len(canon_toks))
        if best_key is None or key > best_key:
            best, best_key = m, key
    return best


def _strip_metric_alias(sql: str) -> str:
    """Drop a trailing output alias (``… AS foo``) from a metric aggregate expression. The intake LLM
    sometimes emits ``metric_sql`` carrying its SELECT-list alias (``SUM(…)/COUNT(*) AS item_return_rate``);
    an aggregate EXPRESSION has no alias of its own, and leaving it breaks a probe that wraps it as
    ``SELECT {expr} AS v FROM …`` (a live pass caught the clarify silently no-firing because of this).
    Only removes a trailing ``AS <identifier>``; the expression is otherwise untouched."""
    return re.sub(r"\s+AS\s+\w+\s*$", "", (sql or "").strip(), flags=re.I)


def _pinned_metric_runs(conn, connection_id: str, metric_table: str, sql: str) -> bool:
    """One cheap dry-run probe: does ``sql`` execute as an aggregate over ``metric_table``? Guards the
    pin so a governed formula referencing a column absent from the metric table can never replace a
    working LLM formula. Prefers the bound connection; else a pooled checkout. Fail-CLOSED (any error /
    no connection → False → keep the LLM formula)."""
    if not metric_table or not sql:
        return False
    ref = str(metric_table).replace(";", "").strip()
    probe = f"SELECT {_strip_metric_alias(sql)} AS _pin_probe FROM {ref}"
    db = conn
    opened = False
    try:
        if db is None:
            if not connection_id:
                return False
            from aughor.db.connection import open_connection_for
            db = open_connection_for(connection_id)
            opened = True
        res = db.execute("intake_metric_pin_probe", probe)
        return not getattr(res, "error", None)
    except Exception:
        return False
    finally:
        if opened and db is not None:
            try:
                db.close()
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "intake pin-probe connection close failed; probe result already "
                               "returned", counter="ada.intake_probe_close")


def _crystallize_metric_resolution(connection_id: str, metric_label: str, metric_table: str,
                                   llm_sql: str, governed_name: str, governed_sql: str) -> None:
    """P4 — when intake resolved a metric to its GOVERNED definition over a materially-different parsed
    reading, crystallize that as an Ambiguity-Ledger resolution so the definition BURNS DOWN per
    connection and is read back as a plan-time prior on EVERY path (chat + future ADA), not just this
    run. The two candidate readings are the LLM's parsed formula and the governed one; the resolution
    is execution-grounded (P1 dry-ran the governed formula before pinning). Source=``probe`` — the
    lowest ledger authority, so it never clobbers a user clarify or a reviewer verdict (override-wins).
    Fail-safe: a ledger error must never perturb the investigation."""
    try:
        from aughor.org.context import current_org_id
        from aughor.semantic.ambiguity_ledger import (
            AmbiguityResolution,
            Reading,
            save_resolution,
        )
        governed_label = f"governed: {governed_name}"
        save_resolution(AmbiguityResolution(
            connection_id=connection_id, org_id=current_org_id() or "",
            schema_scope=metric_table or "",
            dim_kind="AmbiIntent", dim_facet="aggregation",
            subject=f"definition of {metric_label}",
            readings=[
                Reading(label="parsed reading", sql_evidence=llm_sql),
                Reading(label=governed_label, sql_evidence=governed_sql),
            ],
            resolved_reading=governed_label,
            resolved_sql=governed_sql,
            resolution_source="probe",
            evidence=(f"intake pinned the governed definition of {governed_name} over the parsed "
                      f"formula `{llm_sql}` (dry-run-validated)"),
        ))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "ledger crystallization of the metric pin is best-effort; the pin itself is "
                      "unaffected", counter="ada.metric_pin_ledger")


def _pin_canonical_metric(intake, connection_id: str, schema_text: str, conn) -> Optional[str]:
    """Pin the intake's ``metric_sql`` to the connection's GOVERNED definition when one matches, so the
    scan decomposes on a stable formula. Mutates ``intake`` in place (metric_sql + metric_is_ratio),
    and crystallizes the definition resolution to the Ambiguity Ledger so it compounds per connection
    (P4). Returns a transparency note (or None when nothing was pinned). Flag-gated
    (``ada.pin_canonical_metric``); deterministic; fail-open on every uncertainty."""
    try:
        from aughor.kernel.flags import flag_enabled
        if not flag_enabled("ada.pin_canonical_metric"):
            return None
    except Exception:
        return None
    llm_sql = (getattr(intake, "metric_sql", "") or "").strip()
    if not llm_sql:
        return None
    try:
        from aughor.semantic.canonical import resolve_canonical_metrics
        metrics = resolve_canonical_metrics(connection_id, schema_text=schema_text or "")
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "canonical-metric resolve for intake pin is best-effort; keeping the LLM "
                      "metric formula", counter="ada.metric_pin")
        return None
    cand = _match_canonical_metric(intake.metric_label, llm_sql, metrics or [])
    if cand is None:
        return None
    canon_sql = (cand.sql or "").strip()
    # No-op when the governed formula already matches (whitespace/case-insensitive) — nothing to pin.
    if re.sub(r"\s+", "", canon_sql.lower()) == re.sub(r"\s+", "", llm_sql.lower()):
        return None
    if not _pinned_metric_runs(conn, connection_id, getattr(intake, "metric_table", "") or "", canon_sql):
        return None
    intake.metric_sql = canon_sql
    intake.metric_is_ratio = _metric_is_ratio(canon_sql, intake.metric_label)
    # P4 — the resolution compounds: record it in the Ambiguity Ledger (source=probe) so the same
    # definition burns down per connection and feeds the plan-time prior on every path.
    _crystallize_metric_resolution(
        connection_id, intake.metric_label or "", getattr(intake, "metric_table", "") or "",
        llm_sql, cand.name, canon_sql)
    return (
        f"Metric pinned to the governed definition of {cand.name}: {canon_sql} "
        f"(the parsed formula was {llm_sql}) — so the breakdown computes on the same decomposable "
        f"definition every run."
    )


# ── P4 clarify_gate: detect a MATERIAL metric-reading divergence and ask, not guess ────
_METRIC_DIVERGENCE_REL = 0.05   # readings must differ ≥5% (relative) to be worth interrupting for


def _probe_metric_scalar(conn, connection_id: str, metric_table: str, sql: str) -> Optional[float]:
    """Evaluate a metric aggregate to its single global scalar over ``metric_table``. Returns None on
    any error (a reading that doesn't run isn't a plausible alternative worth asking about). Prefers
    the bound connection; else a pooled checkout. Mirrors ``_pinned_metric_runs``."""
    if not metric_table or not sql:
        return None
    ref = str(metric_table).replace(";", "").strip()
    probe = f"SELECT {_strip_metric_alias(sql)} AS v FROM {ref}"
    db = conn
    opened = False
    try:
        if db is None:
            if not connection_id:
                return None
            from aughor.db.connection import open_connection_for
            db = open_connection_for(connection_id)
            opened = True
        res = db.execute("clarify_metric_probe", probe)
        if getattr(res, "error", None) or not res.rows or res.rows[0][0] is None:
            return None
        return float(res.rows[0][0])
    except Exception:
        return None
    finally:
        if opened and db is not None:
            try:
                db.close()
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "clarify metric-probe connection close failed; probe result already "
                               "returned", counter="ada.clarify_probe_close")


def _metrics_materially_diverge(a: float, b: float) -> bool:
    """Two metric readings are materially different when their relative gap clears the bar (so a
    rounding-level difference never interrupts). Symmetric; guards a zero denominator."""
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom >= _METRIC_DIVERGENCE_REL


def _lookup_metric_resolution(connection_id: str, metric_label: str):
    """The crystallized resolution of this metric's definition on this connection, or None. Matches on
    the ``definition of {label}`` subject. Fail-open (a lookup error → None → the caller asks/pins)."""
    if not (connection_id and metric_label):
        return None
    try:
        from aughor.semantic.ambiguity_ledger import retrieve_resolutions
        for res, _score in retrieve_resolutions(f"definition of {metric_label}", connection_id):
            if metric_label.lower() in (res.subject or "").lower():
                return res
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "clarify ledger lookup is best-effort; a miss just means we ask/pin",
                 counter="ada.clarify_ledger")
    return None


def _metric_reading_already_resolved(question: str, connection_id: str, metric_label: str) -> bool:
    """Ledger burn-down: don't re-ask a metric-definition ambiguity already resolved on this connection."""
    return _lookup_metric_resolution(connection_id, metric_label) is not None


def _apply_resolved_metric_reading(intake, connection_id: str, conn) -> Optional[str]:
    """P4 burn-down: when this metric's definition was already resolved (by a user clarify) on this
    connection, HARD-BIND the resolved reading's SQL — so the user's choice is honored on EVERY
    subsequent run (never re-asked, and P1's silent pin can't override a 'use the parsed reading'
    choice). Returns a transparency note when it binds, else None. Flag-gated (`ada.clarify_gate`);
    fail-open: only binds a substitutable formula that actually runs over the metric table."""
    try:
        from aughor.kernel.flags import flag_enabled
        if not flag_enabled("ada.clarify_gate"):
            return None
    except Exception:
        return None
    label = (getattr(intake, "metric_label", "") or "").strip()
    metric_table = (getattr(intake, "metric_table", "") or "").strip()
    if not (label and metric_table):
        return None
    res = _lookup_metric_resolution(connection_id, label)
    sql = (getattr(res, "resolved_sql", "") or "").strip() if res is not None else ""
    if not sql or not _is_substitutable_metric_sql(sql):
        return None
    if re.sub(r"\s+", "", sql.lower()) == re.sub(r"\s+", "", (getattr(intake, "metric_sql", "") or "").lower()):
        return None   # already bound to the resolved reading — nothing to do
    if _probe_metric_scalar(conn, connection_id, metric_table, sql) is None:
        return None
    intake.metric_sql = sql
    intake.metric_is_ratio = _metric_is_ratio(sql, label)
    return (f"Using your previously-chosen reading of {label} ({getattr(res, 'resolved_reading', '')}): "
            f"{sql}.")


def _detect_metric_clarify(intake, connection_id: str, schema_text: str, conn, question: str) -> Optional[dict]:
    """P4 — when a RATIO metric's GOVERNED reading and the LLM's parsed reading BOTH run over the
    metric table but give materially different numbers, this is a genuine two-plausible-readings
    ambiguity (the count-vs-value 'refund rate' class). Return a clarify payload (the two readings +
    their probed previews) so the run can PAUSE and ask, instead of silently choosing one. Returns None
    (proceed silently) when: the flag is off, the metric isn't a ratio, no governed reading matches,
    the readings agree / one doesn't run, or the ambiguity was already resolved on this connection.
    Deterministic; fail-open on every uncertainty."""
    try:
        from aughor.kernel.flags import flag_enabled
        if not flag_enabled("ada.clarify_gate"):
            return None
    except Exception:
        return None
    parsed_sql = (getattr(intake, "metric_sql", "") or "").strip()
    label = (getattr(intake, "metric_label", "") or "").strip()
    metric_table = (getattr(intake, "metric_table", "") or "").strip()
    if not (parsed_sql and label and metric_table):
        return None
    if not _metric_is_ratio(parsed_sql, label):
        return None   # only a ratio has a count-vs-value split worth interrupting for
    try:
        from aughor.semantic.canonical import resolve_canonical_metrics
        cand = _match_canonical_metric(label, parsed_sql, resolve_canonical_metrics(
            connection_id, schema_text=schema_text or "") or [])
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "clarify governed-metric resolve is best-effort; proceed without a clarify",
                 counter="ada.clarify_resolve")
        return None
    if cand is None:
        return None
    governed_sql = (cand.sql or "").strip()
    if not _is_substitutable_metric_sql(governed_sql):
        return None
    if re.sub(r"\s+", "", governed_sql.lower()) == re.sub(r"\s+", "", parsed_sql.lower()):
        return None   # same formula → no ambiguity
    if _metric_reading_already_resolved(question, connection_id, label):
        return None   # burned down already — don't re-ask
    parsed_v = _probe_metric_scalar(conn, connection_id, metric_table, parsed_sql)
    governed_v = _probe_metric_scalar(conn, connection_id, metric_table, governed_sql)
    if parsed_v is None or governed_v is None:
        return None   # a reading that doesn't run isn't a plausible alternative
    if not _metrics_materially_diverge(parsed_v, governed_v):
        return None
    _is_pct = _metric_is_percent(parsed_sql, label)
    _fmt = (lambda v: _fmt_pct(v)) if _is_pct else (lambda v: f"{v:,.2f}")
    gov_label = f"Governed: {cand.name}"
    parsed_label = "As I read the question"
    return {
        "subject": f"definition of {label}",
        "metric_label": label,
        "question": (f"“{label}” can be computed two ways that give different answers "
                     f"({_fmt(governed_v)} vs {_fmt(parsed_v)}) — which did you mean?"),
        "options": [gov_label, parsed_label],
        "previews": [f"= {_fmt(governed_v)}", f"= {_fmt(parsed_v)}"],
        "readings": [
            {"label": gov_label, "sql": governed_sql, "is_ratio": _metric_is_ratio(governed_sql, label)},
            {"label": parsed_label, "sql": parsed_sql, "is_ratio": _metric_is_ratio(parsed_sql, label)},
        ],
    }


@_telemetry.node_span("ada_intake")
def ada_intake(state: AgentState, conn: "DatabaseConnection" = None) -> dict:
    """
    Phase 1 — Question Intake.
    Parses the question into: metric SQL, observation period, comparison period,
    date column, metric table, available dimensions.
    Returns updated state with ada_intake stored in investigation_phases[0].

    `conn` (bound in the graph) lets the deterministic temporal-axis recovery below probe the
    live DB for a join-reachable population date; it is optional and the recovery fails open
    (falling back to the schema-string parse) when a connection isn't supplied.
    """
    from aughor.agent.prompts_investigate import INTAKE_PROMPT, IntakeOutput

    question = state["question"]
    # Size the intake caps to the bound model's window (Layer A, §5b.3): unchanged on a
    # large context, tighter on a small BYO model so the curated payload fits instead of
    # overflowing. Defaults preserved exactly when the window is generous.
    from aughor.llm.context_budget import schema_scan_char_limits
    from aughor.platform import vend_llm
    _schema_cap, _scan_cap = schema_scan_char_limits(vend_llm("coder").max_context,
                                                     default_schema=_SCHEMA_CHAR_LIMIT,
                                                     default_scan=_SCAN_CHAR_LIMIT)
    schema = _trim(state["schema_context"], _schema_cap)
    scan = _trim(state.get("scan_context") or "", _scan_cap)
    events = state.get("events_context") or ""
    events_section = f"BUSINESS CALENDAR:\n{events}\n" if events else ""
    origin_finding_section = _render_origin_finding_section(state.get("origin_finding"))

    prompt = INTAKE_PROMPT.format(
        question=question,
        schema=schema,
        scan_context=scan,
        events_section=events_section,
        origin_finding_section=origin_finding_section,
    )
    # Loss-intent questions get a deterministic directive naming the loss signals THIS
    # schema carries (contra-revenue / capacity columns) — a revenue ranking cannot find
    # losses, and the live A/B showed it concluding "no losses" over 2.4M of refund
    # leakage. Prepended so it is the topmost instruction the intake sees. Flag-gated;
    # '' when the question/schema don't apply, so the prompt is byte-identical otherwise.
    # The detected signals are kept (stored on _ada_intake below) so the cross-section
    # can forward-chain the loss lenses the primary metric doesn't cover.
    _loss_sig = None
    from aughor.kernel.flags import flag_enabled as _loss_flag
    if _loss_flag("intake.loss_signals"):
        from aughor.agent.loss_signals import detect_loss_signals, directive_from_signals
        _loss_sig = detect_loss_signals(question, schema)
        if _loss_sig:
            prompt = directive_from_signals(_loss_sig) + "\n" + prompt

    try:
        intake: IntakeOutput = _provider("coder").complete(
            system="You are a precise data analyst parsing a business question. Return a structured investigation specification.",
            user=prompt,
            response_model=IntakeOutput,
        )
    except Exception as e:
        intake = None
        intake_error = str(e)

    # Code-level validation: collect ALL spec errors and fix them in ONE combined LLM retry
    # (was up to 3 sequential round-trips on the critical path of every investigation). The
    # date column needs no LLM retry — the deterministic _resolve_date_column below fixes an
    # ID-like / non-date column far more reliably.
    if intake is not None:
        _errs = []
        mt_error = _validate_intake_metric_table(intake.metric_table, schema)
        if mt_error:
            _errs.append(mt_error)
        _dmin, _dmax = _extract_data_date_range(scan, getattr(intake, "metric_table", "") or "")
        win_error = _validate_intake_windows(intake, _dmin, _dmax)
        if win_error:
            _errs.append(win_error)
        if _errs:
            retry_prompt = (
                prompt
                + "\n\nCORRECTION REQUIRED — fix ALL of the following:\n- "
                + "\n- ".join(_errs)
                + "\nReturn the corrected spec (use only tables that exist in the schema, and a "
                "comparison window that actually contains data)."
            )
            try:
                intake = _provider("coder").complete(
                    system="You are a precise data analyst parsing a business question. Return a structured investigation specification.",
                    user=retry_prompt,
                    response_model=IntakeOutput,
                )
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "intake correction retry failed; keeping the original intake "
                               "spec despite validation errors", counter="ada.intake_retry")

    # RC1 — metric-feasibility caveat: when the question needs a metric the schema can't
    # support (margin/profit with no cost column; efficiency with no spend/outcome), record
    # it so synthesis reports what IS measurable instead of fabricating a verdict from an
    # assumed cost (the bakehouse "COGS = price·qty·0.5 → constant 50% margin" class).
    if intake is not None:
        try:
            from aughor.semantic.metric_feasibility import unsupported_metric_gap
            _feas = unsupported_metric_gap(question, schema)
        except Exception:
            _feas = None
        if _feas:
            intake.intake_notes = (
                (intake.intake_notes or "").rstrip() + f" FEASIBILITY: {_feas}"
            ).strip()

    # Temporal-feasibility recovery — when the intake declares NO usable time axis, a real
    # PURCHASE/population date may still be JOIN-REACHABLE: the metric sits on an event/child
    # table with no date of its own (an event RATE like returns, whose only date covers the
    # numerator), while the parent order/purchase table IS dated. Recover it deterministically
    # so EVERY downstream path sees the true axis — the temporal-change route below, the coverage
    # clamp, and the displayed spec — instead of NONE. (Previously only the parallel multi-lens
    # WHEN lens recovered this, so the default/single-scan path stayed temporally blind.) Event-rate
    # aware: `_resolve_temporal_axis` excludes the event table's own date and prefers a real
    # date-typed column; fails open (no change) when nothing is join-reachable.
    if intake is not None and (intake.date_column or "").strip().upper() in ("", "NONE"):
        try:
            _axis = _resolve_temporal_axis(state, conn, intake_data=intake.model_dump())
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "intake temporal-axis recovery best-effort", counter="ada.intake_temporal")
            _axis = None
        if _axis and _axis.get("date_column"):
            intake.date_column = _axis["date_column"]
            intake.intake_notes = (
                f"TEMPORAL AXIS RECOVERED: the metric table carries no date of its own, but "
                f"{_axis['date_column']} is join-reachable — trending on it instead of treating the "
                f"question as non-temporal. " + (intake.intake_notes or "")
            ).strip()

    # Deterministic cross-sectional trigger — the intake LLM is unreliable at
    # setting the flag, so force it for diagnostic "where/which is weakest / where
    # are we losing money" questions OR when there is no usable time axis (no date
    # column). This routes to the dimensional weakness scan instead of a temporal
    # baseline (also fewer phases → faster).
    if intake is not None:
        no_time = (intake.date_column or "").strip().upper() in ("", "NONE")
        # A populated comparison_segment_sql means intake recognised a DRIVER question —
        # force cross-sectional so it routes to the group comparison, never a blind trend.
        has_segment = bool((getattr(intake, "comparison_segment_sql", "") or "").strip())
        if _is_diagnostic_question(question) or no_time or has_segment:
            intake.cross_sectional = True

        # F1 — temporal-change premise OVERRIDES the cross-sectional flag. "What drove the CHANGE /
        # why did X drop" asks about movement over time, not which segment is structurally weakest.
        # When a usable time axis exists, force the temporal baseline path so the actual change is
        # measured (it decomposes a real change, or honestly reports "no material change"). With no
        # time axis we keep the cross-sectional fallback, and ada_synthesize reframes honestly (F2).
        if _is_temporal_change_question(question) and not no_time:
            intake.cross_sectional = False
            # G3 — make the displayed spec self-consistent with the route we forced: lead with an
            # authoritative routing statement and strip the LLM's now-contradicted cross-sectional
            # conclusion, so the intake doesn't argue "compare across dimensions" above a temporal run.
            intake.intake_notes = (
                "ROUTING: this is a temporal-change question (\"what drove the change\") — running a "
                "period-over-period analysis of the most recent period vs the prior period. An initial "
                "cross-sectional lean was overridden because the data has a usable time axis. "
                + _scrub_xsec_reasoning(intake.intake_notes or "")
            ).strip()

    # Post-process: ensure all table references are fully-qualified when the schema uses them
    if intake is not None:
        _qualify_intake_table_names(intake, schema)

    # Code-level validation: neutralise an over-counting metric (subquery-in-aggregate /
    # product-of-aggregates) — the class that produced -$3.1B per dimension. Retry once for
    # a clean single aggregate, then deterministically simplify and note it.
    _metric_note = None
    if intake is not None:
        _unsafe = _unsafe_metric_sql(intake.metric_sql)
        if _unsafe:
            retry_prompt = (
                prompt
                + f"\n\nCORRECTION REQUIRED: {_unsafe}. Re-express metric_sql as a SINGLE safe aggregate "
                "(e.g. SUM(column), SUM(col_a*col_b), or SUM(a)-SUM(b)) over ONE table. NEVER put a SELECT "
                "subquery inside an aggregate and NEVER multiply two aggregates. If the true metric needs "
                "another table, pick the closest single-column proxy instead. Return the fixed spec."
            )
            try:
                _retry = _provider("coder").complete(
                    system="You are a precise data analyst parsing a business question. Return a structured investigation specification.",
                    user=retry_prompt,
                    response_model=IntakeOutput,
                )
                if _retry is not None and not _unsafe_metric_sql(_retry.metric_sql):
                    intake = _retry
                    _qualify_intake_table_names(intake, schema)
                    _unsafe = None
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "unsafe-metric retry failed; the deterministic safe fallback "
                               "applies instead", counter="ada.intake_retry")
        if _unsafe:
            _safe = _safe_metric_fallback(intake.metric_sql)
            _metric_note = (
                f"Metric adjusted for safety: the parsed metric would over-count ({_unsafe}); "
                f"ranking instead by {_safe} for a trustworthy magnitude."
            )
            intake.metric_sql = _safe

    # Metric↔question coherence: a money question answered with a COUNT of entities is a
    # premise mismatch (live recurrence: "Where are we losing money?" ran with metric =
    # franchise COUNT(*), so the report concluded "no revenue data exists"). Deterministic
    # detection, one LLM retry with an explicit correction; fail-open if the retry is no better.
    if intake is not None and re.search(
            r"\b(money|revenue|sales|cost|price|profit|margin|spend|losing|loss|earn)\w*\b",
            question or "", re.IGNORECASE):
        _msql = intake.metric_sql or ""
        _has_money_col = re.search(
            r"(price|amount|revenue|cost|total|spend|value|sales|mrr|gmv|fee|charge)", _msql, re.IGNORECASE)
        if not _has_money_col and re.search(r"\bCOUNT\s*\(", _msql, re.IGNORECASE):
            try:
                _retry2 = _provider("coder").complete(
                    system="You are a precise data analyst parsing a business question. Return a structured investigation specification.",
                    user=prompt + (
                        "\n\nCORRECTION REQUIRED: the question is about MONEY, but the previous "
                        "metric_sql counted rows instead of aggregating a monetary column. "
                        "Re-express metric_sql as an aggregate over an actual money column "
                        "(price/amount/revenue/total) from the schema. Return the fixed spec."),
                    response_model=IntakeOutput,
                )
                if _retry2 is not None and re.search(
                        r"(price|amount|revenue|cost|total|spend|value|sales)",
                        _retry2.metric_sql or "", re.IGNORECASE):
                    intake = _retry2
                    _qualify_intake_table_names(intake, schema)
                    _note2 = ("Metric corrected: the question asks about money, so the metric was "
                              "re-parsed to a monetary aggregate instead of an entity count.")
                    _metric_note = f"{_metric_note} {_note2}".strip() if _metric_note else _note2
            except Exception as _exc2:
                from aughor.kernel.errors import tolerate
                tolerate(_exc2, "money-coherence retry is best-effort; the parsed metric stands",
                         counter="ada.intake_money_retry")

    # Unit-conversion guard: a planner sometimes invents a unit story for an integer
    # money column ("stored in cents") and bakes /100.0 into the metric — every number
    # downstream is then 100x off (live incident: SUM(totalPrice)/100.0 turned a $66,471
    # network into €664.71). When the data PROVES the column is already in base units
    # (a multiplicative sibling relation like totalPrice == unitPrice*quantity holds),
    # strip the conversion; otherwise keep it but caveat it as unverified. Deterministic,
    # one probe query, fail-open.
    if intake is not None:
        _conv_col = _detect_unit_conversion(intake.metric_sql)
        if _conv_col:
            if _unit_conversion_disproved(conn, state.get("connection_id") or "",
                                          intake.metric_table, _conv_col):
                intake.metric_sql = _STRIP_CONVERSION_RE.sub("", intake.metric_sql)
                _unit_note = (
                    f"Unit correction: the plan divided {_conv_col} by a constant (a 'stored in "
                    f"cents' assumption), but the data proves {_conv_col} is already in base units "
                    f"(it equals the product of two sibling columns row-for-row). The conversion "
                    f"was removed; absolute values are reported as stored."
                )
            else:
                _unit_note = (
                    f"Unverified unit conversion: the plan divides {_conv_col} by a constant "
                    f"(an assumed minor-unit encoding) that could not be verified against the "
                    f"data. Absolute magnitudes may be off by that factor; ratios and rankings "
                    f"are unaffected."
                )
            _metric_note = f"{_metric_note} {_unit_note}".strip() if _metric_note else _unit_note

    # P4 metric-definition resolution precedence: a previously-resolved reading (burn-down) > a pending
    # clarify > P1's silent pin. (1) If the user already answered this ambiguity on this connection,
    # HARD-BIND their choice. (2) Else, if the governed and parsed readings both run but disagree
    # materially, stash a clarify so the run PAUSES to ask. (3) Else fall through to the silent pin.
    # All flag-gated + fail-open (byte-identical when the flags are off).
    _conn_id = state.get("connection_id") or ""
    _full_schema = state.get("schema_context") or schema
    _resolved_note = None
    _clarify_pending = None
    if intake is not None:
        _resolved_note = _apply_resolved_metric_reading(intake, _conn_id, conn)
        if _resolved_note:
            _metric_note = f"{_metric_note} {_resolved_note}".strip() if _metric_note else _resolved_note
        else:
            _clarify_pending = _detect_metric_clarify(intake, _conn_id, _full_schema, conn, question)

    # P1 — canonical-metric pinning: prefer the connection's GOVERNED definition of this metric over
    # the LLM's (possibly non-decomposable / run-varying) formula, when one matches the label and
    # actually runs. Runs AFTER the safety fallback so a governed formula supersedes a degenerate one;
    # SKIPPED when the reading was already resolved (1) or a clarify is pending (2) — the user's choice
    # binds the metric, not a silent pin. Flag-gated (`ada.pin_canonical_metric`) + fail-open.
    if intake is not None and _clarify_pending is None and _resolved_note is None:
        _pin_note = _pin_canonical_metric(intake, _conn_id, _full_schema, conn)
        if _pin_note:
            _metric_note = f"{_metric_note} {_pin_note}".strip() if _metric_note else _pin_note

    # Resolve a hallucinated / non-date `date_column` to a REAL date/timestamp column —
    # often on a joinable table (orders.order_ts) rather than the metric table (invoices).
    if intake is not None and intake.date_column and intake.date_column.upper() != "NONE":
        _resolved_dc, _dc_changed = _resolve_date_column(
            intake.date_column, intake.metric_table, state["schema_context"], intake.dimensions
        )
        if _dc_changed:
            intake.date_column = _resolved_dc

    # Deterministic coverage clamp — fit the windows to the data that exists for the
    # METRIC TABLE (not the whole connection: on multi-dataset connections the global
    # range mixes datasets and masks an empty window). The LLM retry above only asks;
    # this enforces. The portrait parse is the cheap path, but scan_context is empty
    # on the ADA entry points — the DB probe is the authoritative fallback.
    # Deterministic DATA COVERAGE span — one MIN/MAX probe of the metric's date column, run
    # UNCONDITIONALLY (T4-2): it drives the temporal window clamp below AND lets the report state the
    # real coverage window (even a cross-sectional scan spans a real range the reader should see),
    # instead of the intake LLM's sample-inferred guess. Fail-open (no date column / probe error → "").
    _cov_min = _cov_max = ""
    if intake is not None and (intake.date_column or ""):
        _pmn, _pmx = _measure_date_span(
            state.get("connection_id") or "", intake.metric_table or "", intake.date_column or "")
        _cov_min, _cov_max = (_pmn or ""), (_pmx or "")

    if intake is not None and not intake.cross_sectional:
        # The data's true date span drives temporal windowing (esp. the re-anchor of a
        # 'last-N' window to the most recent data). The scan PORTRAIT undercounts the max
        # (it reported 2024-05 when the orders table runs to 2024-12 — mis-anchoring "last
        # 12 months"); the DB MIN/MAX probe is authoritative. UNION both so neither a short
        # portrait nor a failed probe can shrink the range. ISO date strings → lexical min/max.
        _smin, _smax = _extract_data_date_range(scan, intake.metric_table or "")
        _cmin = min([d for d in (_smin, _cov_min) if d], default="")
        _cmax = max([d for d in (_smax, _cov_max) if d], default="")
        _cov_note = _clamp_intake_to_coverage(intake, _cmin, _cmax, question=state.get("question", ""))
        # Density guard: a comparison window whose date-SPAN survived the clamp but is sparsely
        # populated (internal gap / slow ramp) is still a thin PoP baseline — probe it. Skipped when
        # the span guard already flagged the same window (no double-flag).
        _dens_note = _flag_sparse_comparison(
            intake, state.get("connection_id") or "", intake.metric_table or "",
            intake.date_column or "",
            span_guard_fired=bool(_cov_note and _POP_MISMATCH_SIGNATURE in _cov_note),
        )
        # Trailing-partial guard: an incomplete final observation month reads as a false drop.
        _tp_note = _flag_trailing_partial(
            intake, state.get("connection_id") or "", intake.metric_table or "", intake.date_column or "",
        )
        _notes = " ".join(n for n in (_cov_note, _dens_note, _tp_note) if n)
        if _notes:
            intake.intake_notes = f"{_notes} {intake.intake_notes or ''}".strip()

    if intake is None:
        phase = _phase_result(
            "intake", "Question Intake", "🔍", "error",
            "Could not parse investigation specification.",
            [_skipped_finding("intake", intake_error)],
        )
        return {
            "investigation_phases": [phase],
            "answer_report": None,
        }

    # Store the intake spec in state via a synthetic phase (no SQL, just metadata)
    finding = InvestigationFinding(
        finding_id="intake_spec",
        title="Investigation Specification",
        sql="",
        columns=["field", "value"],
        rows=([
            ["Metric", f"{intake.metric_label} ({intake.metric_sql})"],
            ["Approach", "Cross-sectional — rank the metric across dimensions to find where value is weakest (no time comparison)"],
            ["Primary table", intake.metric_table],
            ["Dimensions", ", ".join(intake.dimensions[:8])],
        ] if intake.cross_sectional else [
            ["Metric", f"{intake.metric_label} ({intake.metric_sql})"],
            ["Observation", f"{intake.observation_label} ({intake.observation_start} → {intake.observation_end})"],
            ["Comparison", f"{intake.comparison_label} ({intake.comparison_start} → {intake.comparison_end})"],
            ["Date column", intake.date_column],
            ["Primary table", intake.metric_table],
            ["Dimensions", ", ".join(intake.dimensions[:8])],
        ]),
        row_count=6,
        error=None,
        interpretation=intake.intake_notes or (
            f"Cross-sectional scan of {intake.metric_label} across dimensions."
            if intake.cross_sectional else
            f"Investigating {intake.metric_label} in {intake.observation_label}."
        ),
        key_numbers=[],
        chart_type="none",
        stat_note=None,
        is_significant=False,
    )
    if _metric_note:
        finding["rows"].append(["Data quality", _metric_note])
        finding["row_count"] = len(finding["rows"])
        finding["interpretation"] = _metric_note + " " + (finding["interpretation"] or "")
    phase = _phase_result(
        "intake", "Question Intake", "🔍", "complete",
        (
            f"Scanning {intake.metric_label} across {len(intake.dimensions)} dimensions to find where value is weakest."
            if intake.cross_sectional else
            f"Measuring {intake.metric_label} in {intake.observation_label} vs {intake.comparison_label}."
        ),
        [finding],
    )
    # Build a JOIN-COMPLETE filtered schema. Keeping only the metric + dimension tables
    # (the old behaviour) drops the table that actually holds the date/join columns — e.g.
    # revenue on `invoices` but the timestamp on `orders` — so the coder can't see it and
    # hallucinates a date column on the metric table. Include the date column's host table,
    # FK-joinable neighbours, and temporal dimension tables, then re-attach the DETECTED JOIN
    # PATHS hints (which _filter_schema strips, being TABLE-block-only) — what the /chat path does.
    filtered_schema = _build_grounded_schema(
        state["schema_context"], intake.metric_table, intake.dimensions,
        intake.date_column, question,
    )

    intake_dict = intake.model_dump()
    intake_dict["filtered_schema"] = filtered_schema
    if _loss_sig:
        # The loss signals travel with the intake so the cross-section can forward-chain
        # the lens phases the primary metric leaves uncovered (leakage vs utilization).
        intake_dict["loss_signals"] = _loss_sig
    if _metric_note:
        intake_dict["metric_safety_note"] = _metric_note

    # T4-2: record the real DATA COVERAGE window (from the MIN/MAX probe above) so the report states
    # the period it actually covers, and correct a sample-inferred observation window that lies
    # outside the real data span (inv1's intake guessed "2023-01 to 2023-03" on data spanning
    # 2023-01 → 2025-01, and the report's observation_period came out empty).
    if _cov_min and _cov_max:
        intake_dict["data_coverage_start"] = _cov_min
        intake_dict["data_coverage_end"] = _cov_max
        intake_dict["data_coverage_label"] = f"{_cov_min} → {_cov_max}"
        if _observation_window_is_wrong(intake.observation_start, intake.observation_end, _cov_min, _cov_max):
            intake_dict["observation_start"] = _cov_min
            intake_dict["observation_end"] = _cov_max
            if intake.cross_sectional or not (intake.observation_label or "").strip():
                intake_dict["observation_label"] = f"{_cov_min} → {_cov_max}"

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
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "ontology entity enrichment is best-effort; intake proceeds without "
                       "lifecycle context", counter="ada.intake_ontology")

    # Pin canonical entity/metric definitions once so every phase uses the same
    # identifiers/expressions (prevents figures drifting between phases).
    try:
        from aughor.agent.explore import build_analysis_ledger
        analysis_ledger = build_analysis_ledger(state)
    except Exception:
        analysis_ledger = ""

    # R3 — build the phase-planner grounding block ONCE, here, for the whole run.
    # baseline / decompose / dimensional / behavioral all ground from the SAME
    # (connection, ledger+filtered_schema, question); building it per phase re-ran
    # measure-grain probing + trusted-query retrieval ~4× for a byte-identical result
    # (build_data_understanding has no internal cache). Compute it against the EXACT
    # schema the phases pass (_with_ledger over filtered_schema) and stash it on
    # _ada_intake; run_analysis_phase reuses it verbatim. No-op safe — on failure the
    # key is absent and each phase falls back to building it itself (prior behavior).
    try:
        from aughor.semantic.data_understanding import build_data_understanding
        _phase_schema = _with_ledger({"analysis_ledger": analysis_ledger}, filtered_schema)
        intake_dict["data_understanding_block"] = build_data_understanding(
            conn, connection_id=state.get("connection_id", ""),
            schema=_phase_schema, question=question,
        ).grounding_block()
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "shared data-understanding grounding is advisory; phases build it "
                       "per-phase when the shared block is absent", counter="ada.plan_grounding")

    # Orchestrator: declare the phase path the deterministic routers will execute, so the
    # Analyst's autonomy is legible (a plan of record, not emergent gate-by-gate routing).
    # Derived from the SAME signals the routers key on — it can't disagree with what runs.
    plan_dict = None
    try:
        from aughor.agent.orchestrator import plan_phases
        plan = plan_phases(
            question=question,
            cross_sectional=bool(intake.cross_sectional),
            dimension_ask=_question_asks_for_dimension(question),
            behavioral=_question_needs_behavioral(question),
        )
        plan_dict = plan.to_dict()
        from aughor.agent.handoff import emit_handoff
        emit_handoff("orchestrator", "analyst", "intake",
                     {"plan": plan.summary(), "planned_ids": plan.planned_ids},
                     conn_id=state.get("connection_id") or None)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "orchestration plan", counter="orchestrator")

    out = {
        "investigation_phases": [phase],
        "_ada_intake": intake_dict,
        "analysis_ledger": analysis_ledger,
    }
    if plan_dict is not None:
        out["_orchestration_plan"] = plan_dict
    # P4 clarify_gate: signal a pending metric-reading clarify so route_after_intake_clarify sends the
    # run through the interrupt gate. Only ever set when the flag is on and the readings materially diverge.
    if _clarify_pending is not None:
        out["_clarify_pending"] = _clarify_pending
    return out


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


class _PhaseRun:
    """Outcome of the shared plan→execute→interpret skeleton. On failure `error_phase` is a
    ready phase the caller returns; on success the caller proceeds with its bespoke tail."""
    def __init__(self, ok, results=None, results_text="", interpretation=None, error_phase=None,
                 fanout_caveat=None):
        self.ok = ok
        self.results = results or []
        self.results_text = results_text
        self.interpretation = interpretation
        self.error_phase = error_phase
        # Set when a metric still aggregates across a fan-out join AFTER the corrective
        # re-plan — the magnitude is unreliable and must not be presented as trustworthy.
        self.fanout_caveat = fanout_caveat


def _phase_grounding(
    grounding_block: Optional[str], conn, *,
    connection_id: str, schema: Optional[str], question: str,
) -> str:
    """The data-understanding grounding text for a phase planner (measure-grain
    PREVENTION + trusted-query reuse).

    ``grounding_block`` is the block ada_intake built ONCE for the whole run (R3):
    when it is not None it is reused verbatim — including an empty string, which
    means intake determined there is nothing to ground, so we must NOT rebuild.
    Only when it is None (callers that don't thread it, e.g. the cross-section
    lenses, which vary the question) do we build it here. No-op safe — returns ""
    and never raises."""
    from aughor.stats import stats as _s
    if grounding_block is not None:
        # Reused the block ada_intake built once — the R3 dedupe working. Counting it
        # makes the optimization observable on real runs: reused ≫ built per phase means
        # the shared block is threading through; a spike in "built" means it isn't.
        _s.inc("ada.grounding_reused")
        return grounding_block
    if not schema:
        return ""
    _s.inc("ada.grounding_built")
    try:
        from aughor.semantic.data_understanding import build_data_understanding
        return build_data_understanding(
            conn, connection_id=connection_id, schema=schema, question=question
        ).grounding_block() or ""
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "data-understanding grounding block is advisory; planner prompt "
                       "unchanged", counter="ada.plan_grounding")
        return ""


def run_analysis_phase(
    conn, *, phase_id: str, title: str, emoji: str,
    plan_system: str, plan_user: str,
    interpret_system: str, interpret_user_fn,
    cap: int = 4,
    schema: Optional[str] = None,
    plan_error_msg: str = "Could not plan queries.",
    exec_error_msg: str = "Queries failed to execute.",
    exec_status: str = "error",
    exec_skipped_reason: str = "No results.",
    preplanned=None,
    question: str = "",
    connection_id: str = "",
    interpret_max_rows: int = 12,
    grounding_block: Optional[str] = None,
    sql_transform=None,
) -> "_PhaseRun":
    """The plan(coder) → execute(parallel, safe) → interpret(fast) skeleton every ADA phase
    shares. Returns a _PhaseRun; a planning or execution failure carries a ready error/skipped
    phase for the caller to return. The interpret prompt is built by ``interpret_user_fn(
    results_text)`` since it depends on the executed results.

    ``preplanned`` (a PhasePlan): when a drilled finding hands us its already-grounded,
    grain-correct query, REUSE it verbatim instead of re-deriving — so the phase reproduces the
    finding's numbers rather than risking a fresh fan-out. The LLM re-plan guards (temporal,
    fan-out) are then skipped, since re-planning would defeat the reuse.

    ``sql_transform(sql) -> sql``: a caller-supplied deterministic pass applied to every
    planned query right before execution — AFTER the re-plan guards, so a corrective re-plan
    can't shed it. This is how a lens ENFORCES a contract the planner keeps ignoring (the
    lifecycle filter survived neither plan_user nor plan_system as prose). Fail-open is the
    transform's own responsibility; a raised exception here is tolerated per query."""
    from aughor.agent.prompts_investigate import PhasePlan, PhaseInterpretation

    # Ground the phase planner with the SHARED data-understanding bundle (measure-grain
    # PREVENTION + trusted-query reuse), built once behind one module so the assembly never
    # drifts across modes. Grain prevents SUM-at-wrong-grain by construction; trusted patterns
    # let the planner reuse known-correct join/aggregation shapes instead of re-deriving them
    # (and re-risking the fan-outs the library already solved). The block is built ONCE in
    # ada_intake and threaded in via grounding_block (R3) — baseline/decompose/dimensional/
    # behavioral share identical grounding, so each phase no longer re-runs grain probing +
    # trusted retrieval for the same result. No-op safe — an empty bundle leaves the prompt as-is.
    plan_system_eff = plan_system
    _block = _phase_grounding(
        grounding_block, conn, connection_id=connection_id, schema=schema, question=question)
    if _block:
        plan_system_eff = f"{plan_system}\n\n{_block}"

    # Step 1 — plan (or reuse a preplanned, grain-correct query).
    _preplanned = bool(preplanned is not None and getattr(preplanned, "queries", None))
    if _preplanned:
        plan = preplanned
    else:
        try:
            plan: PhasePlan = _provider("coder").complete(
                system=plan_system_eff, user=plan_user, response_model=PhasePlan)
        except Exception as e:
            return _PhaseRun(ok=False, error_phase=_phase_result(
                phase_id, title, emoji, "error", plan_error_msg, [_skipped_finding(phase_id, str(e))]))

    # Temporal guard (WCH-DS) — the intake clamp put LITERAL observation/comparison windows into
    # plan_user, but a coder that reaches for CURRENT_DATE / NOW() / DATE_SUB produces ZERO rows on
    # historical data. The prompt rule is advisory; this ENFORCES it with one corrective re-plan
    # that must use the literal dates. (Shared by every phase, so baseline/decompose/dimensional/
    # behavioral are all covered.)
    if not _preplanned and plan and plan.queries and any(_uses_relative_date(q.sql) for q in plan.queries):
        from aughor.stats import stats as _s; _s.inc("temporal_guard_retries")
        try:
            _fixed = _provider("coder").complete(
                system=plan_system_eff,
                user=plan_user + (
                    "\n\nCORRECTION REQUIRED: a previous attempt used CURRENT_DATE / NOW() / "
                    "DATE_SUB / DATE_ADD / relative date arithmetic. That is FORBIDDEN — the data "
                    "is HISTORICAL, so any window relative to today returns ZERO rows. Re-write "
                    "EVERY query using ONLY the LITERAL observation and comparison date ranges given "
                    "above, as DATE literals (WHERE col >= DATE 'YYYY-MM-DD' AND col < DATE "
                    "'YYYY-MM-DD'). Never use CURRENT_DATE / NOW / DATE_SUB / DATE_ADD / DATEADD / "
                    "SYSDATE."),
                response_model=PhasePlan)
            if _fixed and _fixed.queries:
                plan = _fixed
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "temporal-guard re-plan is best-effort; the prompt rule still applies "
                     "and the original plan still runs", counter="temporal_guard.replan_failed")

    # Fan-out guard (CHASM) — a metric aggregated across a join that MULTIPLIES its home
    # table's rows inflates the total. Real failure: a "stockout days by category" scan summed
    # inventory_snapshots (product×month grain) AFTER joining order_items (2.37M line-items),
    # inflating the total ~1000× at HIGH confidence. The /chat path guards this; the ADA phases
    # did not. Detect SUM/AVG/COUNT-over-chasm on the planned SQL and force ONE corrective re-plan
    # that reaches the dimension via a UNIQUE lookup key instead of fanning out through a fact table.
    _fanout_caveat = None
    try:
        from aughor.agent.verifier import Verifier as _Verifier, FANOUT_CAVEAT as _FANOUT_CAVEAT
        from aughor.tools.schema import parse_schema_tables
        _tc = parse_schema_tables(schema) if schema else {}
        _dialect = getattr(conn, "dialect", "duckdb")

        def _augment_tc(queries):
            # The intake's FILTERED phase schema can omit a table the coder reaches for (e.g.
            # order_items joined only to grab a category dimension). Without that table's columns
            # the chasm detector is BLIND to the fan-out (the 11-trillion stockout total that
            # slipped past). Introspect any referenced-but-missing table so the detector sees the
            # whole join — for the ORIGINAL plan and again after a re-plan.
            try:
                import sqlglot as _sg
                from sqlglot import exp as _sgx
                _have = {k.lower() for k in _tc}
                _refs = set()
                for _q in (queries or []):
                    try:
                        for _t in _sg.parse_one(_q.sql, read=_dialect).find_all(_sgx.Table):
                            _refs.add(f"{_t.db}.{_t.name}" if _t.db else _t.name)
                    except Exception as _e2:
                        from aughor.kernel.errors import tolerate
                        tolerate(_e2, "fanout schema-augment: query parse", counter="ada.fanout_augment_parse")
                for _ref in _refs:
                    if not _ref or _ref.lower() in _have:
                        continue
                    _p = _ref.split(".")
                    _probe = (
                        f"SELECT column_name FROM information_schema.columns "
                        f"WHERE table_name = '{_p[-1]}'"
                        + (f" AND table_schema = '{_p[0]}'" if len(_p) == 2 else "")
                    )
                    try:
                        _res = conn.execute("__fanout_schema_probe__", _probe)
                        _rows = getattr(_res, "rows", None) or []
                        if _rows:
                            _tc[_ref] = [r[0] for r in _rows]
                            _have.add(_ref.lower())
                    except Exception as _e2:
                        from aughor.kernel.errors import tolerate
                        tolerate(_e2, "fanout schema-augment: column probe", counter="ada.fanout_augment_probe")
            except Exception as _e1:
                from aughor.kernel.errors import tolerate
                tolerate(_e1, "fanout schema-augment is best-effort", counter="ada.fanout_augment_failed")

        def _scan_fanout(queries):
            # The owned Verifier runs the deterministic detector battery (fan-out / id-
            # arithmetic / ratio-of-sums) over this phase's queries — schema-augmented above.
            _augment_tc(queries)
            return _Verifier.scan(queries, _tc, _dialect)

        _fanout_hints = [] if _preplanned else _scan_fanout(plan.queries)
        if _fanout_hints:
            from aughor.stats import stats as _s; _s.inc("ada.fanout_guard_retries")
            try:
                _fixed = _provider("coder").complete(
                    system=plan_system_eff,
                    user=plan_user + (
                        "\n\nCORRECTION REQUIRED — FAN-OUT DETECTED: a previous attempt aggregated a "
                        "metric across a join that MULTIPLIES its home table's rows, inflating the "
                        "total. Problems found:\n  - " + "\n  - ".join(dict.fromkeys(_fanout_hints)) +
                        "\nRe-write so the metric's OWN table is aggregated at ITS own grain: reach the "
                        "GROUP BY dimension through a key UNIQUE in the dimension's lookup table (e.g. a "
                        "product's category from the products table, NOT from order_items), and do NOT "
                        "join to a second transaction/fact table that fans the metric out. Do NOT change "
                        "what the metric measures. If a many-side join is unavoidable, pre-aggregate EACH "
                        "satellite in its own CTE keyed by the shared id BEFORE joining."),
                    response_model=PhasePlan)
                if _fixed and _fixed.queries:
                    plan = _fixed
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "fan-out guard re-plan is best-effort; the prompt rule still applies",
                         counter="ada.fanout_guard.replan_failed")
            # Fail-safe: the LLM re-plan is unreliable on a known fan-out (it often returns a
            # plausible query that still double-counts). If the metric STILL aggregates across a
            # chasm, we must not present the magnitude as trustworthy — carry a caveat downstream.
            if _scan_fanout(plan.queries):
                _s.inc("ada.fanout_guard_unresolved")
                _fanout_caveat = _FANOUT_CAVEAT
    except Exception:
        _fanout_caveat = None

    # Step 2 — execute (parallel — each query gets its own reader connection)
    # Caller's deterministic per-query pass (e.g. the lifecycle guard). Applied to the FINAL
    # plan — after the temporal/fan-out re-plans — so no corrective re-plan can shed it.
    if sql_transform is not None:
        for _pq in plan.queries or []:
            try:
                _new = sql_transform(getattr(_pq, "sql", "") or "")
                if _new:
                    _pq.sql = _new
            except Exception as _st_exc:
                from aughor.kernel.errors import tolerate
                tolerate(_st_exc, "caller sql_transform is best-effort; original SQL runs",
                         counter="ada.sql_transform_failed")
    # Phase-level unit-conversion strip: the intake guard cleans intake.metric_sql, but
    # each phase's coder writes FRESH SQL and can re-invent the '/100 cents' story there
    # (live recurrence: the temporal phase emitted SUM(totalPrice)/100.0 on its own,
    # resurfacing the $13.85 phantom). Same detection + same one-probe disproof, cached
    # per column so a phase costs at most one extra probe.
    try:
        _conv_cache: dict = {}
        for _pq in plan.queries:
            _ccol = _detect_unit_conversion(getattr(_pq, "sql", "") or "")
            if not _ccol:
                continue
            _m = re.search(r"\bFROM\s+([A-Za-z_][\w.]*)", _pq.sql, re.IGNORECASE)
            _tbl = _m.group(1) if _m else ""
            _key = (_tbl.rsplit(".", 1)[-1].lower(), _ccol.lower())
            if _key not in _conv_cache:
                _conv_cache[_key] = _unit_conversion_disproved(conn, "", _tbl, _ccol)
            if _conv_cache[_key]:
                _pq.sql = _STRIP_CONVERSION_RE.sub("", _pq.sql)
    except Exception as _uc_exc:
        from aughor.kernel.errors import tolerate
        tolerate(_uc_exc, "phase-level unit-conversion strip is best-effort",
                 counter="ada.unit_probe_phase")

    # Adaptive temporal grain: a coder defaulting to DATE_TRUNC('month') over a
    # 17-day window produces ONE bucket ("single data point — cannot establish a
    # trend") when a daily series was sitting right there. When the query's own
    # literal date range spans ≤35 days, truncate by day; ≤120 days, by week.
    try:
        for _pq in plan.queries:
            _sql = getattr(_pq, "sql", "") or ""
            if not re.search(r"DATE_TRUNC\s*\(\s*'(month|quarter|year)'", _sql, re.IGNORECASE):
                continue
            _dates = re.findall(r"DATE\s+'(\d{4}-\d{2}-\d{2})'", _sql) or \
                     re.findall(r"'(\d{4}-\d{2}-\d{2})'", _sql)
            if len(_dates) < 2:
                continue
            from datetime import date as _date
            _ds = sorted(_date.fromisoformat(d) for d in _dates[:4])
            _span = (_ds[-1] - _ds[0]).days
            if _span <= 0:
                continue
            _grain = "day" if _span <= 35 else ("week" if _span <= 120 else None)
            if _grain:
                _pq.sql = re.sub(r"(DATE_TRUNC\s*\(\s*)'(?:month|quarter|year)'",
                                 rf"\g<1>'{_grain}'", _sql, flags=re.IGNORECASE)
    except Exception as _tg_exc:
        from aughor.kernel.errors import tolerate
        tolerate(_tg_exc, "adaptive temporal grain is best-effort", counter="ada.temporal_grain")

    results = _parallel_execute_safe(conn, phase_id, plan.queries, cap=cap, schema=schema)
    if not results:
        return _PhaseRun(ok=False, error_phase=_phase_result(
            phase_id, title, emoji, exec_status, exec_error_msg,
            [_skipped_finding(phase_id, exec_skipped_reason)]))

    # Step 2b — semantic operators (opt-in per query): turn text-column results into evidence the
    # interpreter can reason over. No-op unless the planner attached a step; fail-open and guarded.
    results = _apply_semantic_steps(results)

    # Join-coverage guard: an INNER JOIN that drops base rows without a match silently
    # DEFLATES every total (live incident: a franchise×supplier query captured half the
    # network's revenue and shipped at High confidence). Probe each executed query's
    # joined SUM against the base table's SUM; a material shortfall becomes a caveat on
    # the same channel the fan-out guard uses (rendered inline + caps report confidence).
    if _fanout_caveat is None:
        try:
            from aughor.sql.join_guard import check_join_coverage
            for _q, _r in results:
                if getattr(_r, "error", None):
                    continue
                _cov = check_join_coverage(conn, getattr(_q, "sql", "") or "")
                if _cov:
                    _fanout_caveat = _cov
                    break
        except Exception as _cov_exc:
            from aughor.kernel.errors import tolerate
            tolerate(_cov_exc, "join-coverage probe is best-effort", counter="ada.coverage_probe")

    # Step 3 — interpret
    results_text = _results_to_text([r for _, r in results], max_rows=interpret_max_rows)
    interpretation = None
    try:
        if not _has_usable_data(results):
            raise RuntimeError("skip narrator — no usable data")
        interpretation = _provider("fast").complete(
            system=interpret_system, user=interpret_user_fn(results_text),
            response_model=PhaseInterpretation)
    except Exception:
        interpretation = None
    # Phase 2 — journal this phase's SQL-Engineer → Verifier → Narrator hand-offs as
    # typed events, so the collaboration is legible in the Fleet view / receipt.
    # Additive and fail-open: never touches the investigation's result.
    from aughor.agent.handoff import journal_phase_handoffs
    journal_phase_handoffs(phase_id, plan=plan, results=results, fanout_caveat=_fanout_caveat,
                           interpretation=interpretation,
                           conn_id=getattr(conn, "_connection_id", None),
                           dialect=getattr(conn, "dialect", "duckdb"))
    return _PhaseRun(ok=True, results=results, results_text=results_text, interpretation=interpretation,
                     fanout_caveat=_fanout_caveat)


@_telemetry.node_span("ada_baseline")
def ada_baseline(state: AgentState, conn: "DatabaseConnection") -> dict:
    """
    Phase 2 — Baseline & Anomaly Assessment.
    Confirms the anomaly is real and statistically significant.
    """
    from aughor.agent.prompts_investigate import (
        BASELINE_PLAN_PROMPT,
        BASELINE_INTERPRET_PROMPT,
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
    _run = run_analysis_phase(
        conn, phase_id="baseline", title="Baseline & Anomaly Assessment", emoji="📊", schema=schema,
        plan_system="Write SQL queries for baseline anomaly detection. Return a JSON object with a 'queries' list." + _ADA_SQL_GROUNDING,
        plan_user=plan_prompt,
        interpret_system="You are a senior data analyst interpreting query results. Be precise. Cite real numbers.",
        interpret_user_fn=lambda results_text: BASELINE_INTERPRET_PROMPT.format(
            question=question, results_text=results_text, events_section=events_section,
            z_threshold=2.0, pct_threshold=10),
        plan_error_msg="Could not plan baseline queries.",
        exec_error_msg="All baseline queries failed to execute.",
        question=question, connection_id=state.get("connection_id", ""),
        exec_skipped_reason="No queries produced results.",
        grounding_block=intake_data.get("data_understanding_block"),
    )
    if not _run.ok:
        return {"investigation_phases": phases + [_run.error_phase]}
    results, _results_text, interpretation = _run.results, _run.results_text, _run.interpretation

    # ── Stats.py: code-level significance check (runs before LLM interpretation) ──
    # Compute z-score on the baseline time series. The LLM is asked to compute
    # the same thing in SQL, but this gives us a deterministic Python-level gate
    # that the router can trust unconditionally.
    code_sigma: Optional[float] = None
    code_significant: Optional[bool] = None
    for _, r in results:
        if r.error or not r.rows or not r.columns:
            continue
        stat_results = analyze_query_result(r.columns, r.rows, r.sql)
        for sr in stat_results:
            if sr.sigma is not None:
                if code_sigma is None or sr.sigma > code_sigma:
                    code_sigma = float(sr.sigma)  # numpy.float64 → python float
        if code_sigma is not None:
            # bool() so a numpy.bool_ never reaches graph state — the LangGraph msgpack
            # checkpointer can't serialize numpy scalars and the whole run crashes.
            code_significant = bool(code_sigma >= 2.0)
            break  # first successful result is enough

    # Decompose-under-abstention (fix 5): capture the sustained level-shift magnitude of the primary
    # metric series so the router can still run ONE dimensional pass for a "why did X change?"
    # question whose aggregate moved materially — never answer a WHY with "it's just noise" and a
    # list of dimensions it never queried (the inv3 failure). Best-effort; router falls back to sigma.
    code_rel_change: Optional[float] = None
    try:
        from aughor.tools.stats import mean_shift_significance

        def _col_floats(rows, idx):
            out = []
            for row in rows:
                if idx < len(row):
                    try:
                        out.append(float(str(row[idx]).replace(",", "").replace("%", "")))
                    except (TypeError, ValueError):
                        pass
            return out

        for _, r in results:
            if r.error or not r.rows or not r.columns:
                continue
            # The primary metric series is the first non-leading column that reads as a run of
            # numbers (leading column is the period/label); good enough to gauge the aggregate move.
            for _ci in range(1, len(r.columns)):
                _series = _col_floats(r.rows, _ci)
                if len(_series) < 6:
                    continue
                _shift = mean_shift_significance(_series)
                if _shift is not None:
                    code_rel_change = float(_shift.rel_change)
                    break
            if code_rel_change is not None:
                break
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "level-shift magnitude is best-effort; router falls back to sigma",
                 counter="ada.level_shift_probe")

    if interpretation and interpretation.findings:
        findings = _assemble_phase_findings(results, interpretation.findings, "baseline")
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

    # A baseline is a metric over time → a line (intent-driven; shape-verified, so a non-temporal
    # baseline finding safely degrades to the frontend's auto inference).
    for _f in findings:
        _f["chart_type"] = _chart_type_for_finding(_f, "trend")

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

            val_result = _execute_safe(conn, "premise_check", three_way_sql, schema=schema)
            from aughor.kernel import metering
            metering.record_activation("ada.premise_check")   # Activation Receipt (Wave 1·E3)
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
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "premise check is best-effort; investigation proceeds with the "
                       "original window, never crash the pipeline", counter="ada.premise_check")

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
        "_baseline_rel_change": code_rel_change,
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
    _run = run_analysis_phase(
        conn, phase_id="decomposition", title="Metric Decomposition", emoji="🧩", schema=schema,
        plan_system="Write SQL for metric decomposition. Decompose the metric into additive sub-drivers." + _ADA_SQL_GROUNDING,
        plan_user=plan_prompt,
        interpret_system="Interpret metric decomposition results. State clearly whether volume or value drove the change.",
        interpret_user_fn=lambda results_text: DECOMPOSE_INTERPRET_PROMPT.format(
            question=question, baseline_summary=baseline_summary, results_text=results_text),
        plan_error_msg="Could not plan decomposition queries.",
        exec_error_msg="Decomposition queries failed.",
        question=question, connection_id=state.get("connection_id", ""),
        grounding_block=intake_data.get("data_understanding_block"),
    )
    if not _run.ok:
        return {"investigation_phases": phases + [_run.error_phase]}
    results, _results_text, interpretation = _run.results, _run.results_text, _run.interpretation

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

    # A decomposition ranks sub-drivers → a sorted bar (a change/contribution finding keeps 'auto' so
    # the frontend's sign-aware diverging bar isn't flattened).
    for _f in findings:
        _f["chart_type"] = _chart_type_for_finding(_f, "ranking")

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
    _run = run_analysis_phase(
        conn, phase_id="dimensional", title="Dimensional Analysis", emoji="🔬", schema=schema,
        plan_system="Write contribution-analysis SQL for each dimension. Sort by absolute_change ASC." + _ADA_SQL_GROUNDING,
        plan_user=plan_prompt,
        interpret_system="Interpret contribution analysis. Identify concentrated vs. diffuse decline.",
        interpret_user_fn=lambda results_text: DIMENSIONAL_INTERPRET_PROMPT.format(
            question=question, prior_summary=prior_summary, results_text=results_text),
        plan_error_msg="Could not plan dimensional queries.",
        exec_error_msg="Dimensional queries failed.",
        question=question, connection_id=state.get("connection_id", ""),
        grounding_block=intake_data.get("data_understanding_block"),
    )
    if not _run.ok:
        return {"investigation_phases": phases + [_run.error_phase]}
    results, _results_text, interpretation = _run.results, _run.results_text, _run.interpretation

    if interpretation and interpretation.findings:
        findings = _assemble_phase_findings(results, interpretation.findings, "dim")
        # G1 — strip fabricated change-attribution from any finding whose prior-period baseline is empty.
        for f in findings:
            _neutralize_baseless_contribution(f)
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

    # A dimensional drill-down ranks where the metric concentrates → a sorted bar; a contribution/
    # change finding keeps 'auto' so the frontend's diverging (green/red by sign) bar is preserved.
    for _f in findings:
        _f["chart_type"] = _chart_type_for_finding(_f, "ranking")

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
    _run = run_analysis_phase(
        conn, phase_id="behavioral", title="Behavioral & Operational", emoji="👥", schema=schema,
        plan_system="Write SQL for behavioral and operational diagnostics." + _ADA_SQL_GROUNDING,
        plan_user=plan_prompt,
        interpret_system="Interpret behavioral and operational findings. Be specific about what changed.",
        interpret_user_fn=lambda results_text: BEHAVIORAL_INTERPRET_PROMPT.format(
            question=question, prior_summary=prior_summary, results_text=results_text),
        plan_error_msg="Could not plan behavioral queries.",
        exec_status="skipped",
        exec_error_msg="Behavioral/operational tables not available in this schema.",
        question=question, connection_id=state.get("connection_id", ""),
        exec_skipped_reason="Required tables (sessions, refunds, etc.) not in schema.",
        grounding_block=intake_data.get("data_understanding_block"),
    )
    if not _run.ok:
        return {"investigation_phases": phases + [_run.error_phase]}
    results, _results_text, interpretation = _run.results, _run.results_text, _run.interpretation

    if interpretation and interpretation.findings:
        findings = _assemble_phase_findings(results, interpretation.findings, "beh")
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


_PREMISE_HIGH_RE = re.compile(
    r"\b(?:so|too|really|unusually|abnormally|very|surprisingly)\s+(?:high|elevated|excessive|many)\b"
    r"|\b(?:high|elevated|excessive|rising|surging|spiking)\b|\b(?:so|too)\s+many\b", re.IGNORECASE)
_PREMISE_LOW_RE = re.compile(
    r"\b(?:so|too|really|unusually|abnormally|very|surprisingly)\s+(?:low|poor|weak|few)\b"
    r"|\b(?:low|poor|weak|declining|dropping|falling|underperform\w*)\b|\b(?:so|too)\s+few\b", re.IGNORECASE)


def _premise_direction(question: str) -> "Optional[str]":
    """If the question ASSERTS the metric sits at an extreme ("why are returns SO HIGH"),
    return the asserted direction ("high"/"low") so the scan can VALIDATE that premise
    before explaining it — rather than assuming a gap that may not be real. None when the
    question embeds no comparative premise."""
    q = question or ""
    if _PREMISE_HIGH_RE.search(q):
        return "high"
    if _PREMISE_LOW_RE.search(q):
        return "low"
    return None


def _premise_enabled() -> bool:
    from aughor.kernel.flags import flag_enabled

    return flag_enabled("ada.premise_check")


def _causal_drill_enabled() -> bool:
    """The `ada.causal_drill` flag (env `AUGHOR_CAUSAL_DRILL`) — additive, fail-off; mirrors
    `_premise_enabled`. When on, the cross-section scan floats causal dimensions to the front (so they
    survive the query cap) and, after localising WHERE, auto-drills the event-only dims to WHY (a
    composition/share-of-returns lens) instead of stopping and merely recommending it."""
    from aughor.kernel.flags import flag_enabled

    return flag_enabled("ada.causal_drill")


def _causal_split(dimensions: list) -> "tuple[list, list]":
    """Split intake dimensions for a causal (WHERE→WHY) scan: population dims stay in the RATE scan
    (the WHERE), event-only dims (living on a return/refund/cancel table) are held out for a
    COMPOSITION lens (the WHY — share of the event by reason/condition, avoiding the tautological 100%
    rate `_is_event_dim` warns about). Mirrors `_partition_dimensions` but returns the two lists
    directly for the serial default path. Order-preserving."""
    dims = [d for d in (dimensions or []) if d]
    pop = [d for d in dims if not _is_event_dim(d)]
    event = [d for d in dims if _is_event_dim(d)]
    return pop, event


@_telemetry.node_span("ada_cross_section")
def ada_cross_section(state: AgentState, conn: "DatabaseConnection", *,
                      dims_override: Optional[list] = None,
                      phase_meta: Optional[tuple] = None,
                      period_directive: Optional[str] = None,
                      extra_dims: Optional[list] = None,
                      extra_schema: Optional[str] = None,
                      extra_directive: Optional[str] = None,
                      grain: Optional[dict] = None) -> dict:
    """Cross-sectional WEAKNESS SCAN — for diagnostic questions ("where are we
    losing money / which X is weakest") the metric has no usable time axis, so we
    rank the money metric across each available dimension to surface the lowest /
    most-concentrated values, instead of a temporal baseline.

    ``dims_override`` scopes the scan to a subset of the intake dimensions and
    ``phase_meta`` = (phase_id, title, emoji) gives the emitted phase its own identity — both
    default to the full-dimension "cross_section" phase (byte-identical to before), so the parallel
    multi-lens node can reuse this exact scan (guards and all) as a themed lens over one group."""
    from aughor.agent.prompts_investigate import (
        CROSS_SECTION_PLAN_PROMPT, CROSS_SECTION_INTERPRET_PROMPT,
        CROSS_SECTION_ADDITIVE_BLOCK, CROSS_SECTION_RATIO_BLOCK, CROSS_SECTION_AVG_BLOCK,
        CROSS_SECTION_RATIO_INTERPRET_PROMPT,
    )
    _phase_id, _phase_title, _phase_emoji = phase_meta or ("cross_section", "Cross-Sectional Scan", "🧭")
    question = state["question"]
    phases = state.get("investigation_phases", [])
    intake_data = state.get("_ada_intake") or {}
    schema = _with_ledger(state, intake_data.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT))
    if extra_schema:
        schema = schema + extra_schema
    metric_label = intake_data.get("metric_label", "the metric")
    metric_sql = intake_data.get("metric_sql", "SUM(revenue)")
    metric_table = intake_data.get("metric_table", "")
    dimensions = dims_override if dims_override is not None else intake_data.get("dimensions", [])
    # Auto-drill WHERE→WHY (flag AUGHOR_CAUSAL_DRILL) — only on a clean top-level scan, never a sub-lens
    # invocation (dims_override set), which the multilens node already partitions itself. Peel the
    # event-only dims (return reason/condition — tautological as a rate) aside for a composition/WHY
    # lens after the rate scan, and float population causal dims ahead of the descriptive ones so the
    # scan covers the differentiators, not brand/tier.
    _causal_drill = _causal_drill_enabled() and dims_override is None
    _why_event_dims: list = []
    if _causal_drill:
        dimensions, _why_event_dims = _causal_split(dimensions)
    # #4 — augment with discriminating population attributes the intake missed (price band / season),
    # + a small schema snippet so the join is reachable + a plan directive for the numeric band.
    if extra_dims:
        dimensions = list(dimensions) + [d for d in extra_dims if d not in dimensions]

    # Augmented runs (discovered price-band / season) need more room so the discriminating price
    # ranking isn't crowded out by the base dimensions under the phase's query cap.
    _augmented = bool(extra_dims or extra_directive)
    _dim_cap = 8 if _augmented else 6
    prioritized = _prioritize_dimensions(dimensions, causal_first=_causal_drill)
    dimensions_list = "\n".join(f"  - {d}" for d in prioritized[:_dim_cap]) if prioritized else "  (none identified)"

    # RATIO vs ADDITIVE metric. A ratio/percentage/per-unit metric (SUM(num)/SUM(den), *100, AVG)
    # cannot be SUM'd across groups or divided by COUNT(*) — the additive template silently dropped
    # the denominator and reported SUM(numerator) as the metric (mislabelling $/order as a %).
    # Intake's metric_is_ratio is an OR signal; the deterministic detector is the actual gate.
    is_ratio = bool(intake_data.get("metric_is_ratio")) or _metric_is_ratio(metric_sql, metric_label)
    # Three-way: a COMPOSITE ratio (SUM(num)/SUM(den), *100) needs its numerator/denominator
    # surfaced for auditability; a bare AVG/MEAN is non-additive but self-contained, so it gets the
    # clean AVG block (no redundant SUM/COUNT instrumentation); everything else is additive.
    if is_ratio and _metric_is_composite_ratio(metric_sql):
        _block = CROSS_SECTION_RATIO_BLOCK
    elif is_ratio:
        _block = CROSS_SECTION_AVG_BLOCK
    else:
        _block = CROSS_SECTION_ADDITIVE_BLOCK
    metric_computation_block = _block.format(metric_sql=metric_sql)

    # Direction: default is a weakness frame (lowest first). For a max-seeking question ("HIGHEST
    # burden / MOST X") the answer is the LARGEST value — orient the ranking and interpretation to
    # the top so synthesis doesn't lead with a mid-rank value (the D8 "makeup_lips not skincare_face"
    # miss). The metric_computation_block sorts ASC; this override flips it and re-frames the read.
    _max_seeking = _xsec_max_seeking(question)
    _direction_plan = (
        "\n\nDIRECTION OVERRIDE — this question asks for the HIGHEST / MOST: ORDER BY metric_total "
        "DESC so the LARGEST values come first, and treat the MAXIMUM as the answer (NOT the "
        "minimum). Keep every other rule above."
    ) if _max_seeking else ""
    _direction_interp = (
        " DIRECTION: this question asks for the HIGHEST / MOST — name and LEAD WITH the LARGEST "
        "value(s); the maximum is the answer, never the minimum."
    ) if _max_seeking else ""

    # PREMISE VALIDATION (flag-gated): a "why is X so high/low" question ASSERTS the metric
    # sits at an extreme. Before scanning WHERE it concentrates, validate that premise —
    # compute the subject's metric vs the overall/peer reference — so we don't spend the whole
    # investigation explaining a gap that isn't actually there. This is the deepest form of
    # questioning the data: challenge the question's own assumption before decomposing it.
    premise_check_section = ""
    _premise_dir = _premise_direction(question)
    if _premise_dir and _premise_enabled():
        premise_check_section = (
            "\nPREMISE CHECK — write this query FIRST, before the per-dimension scan:\n"
            f"  The question ASSERTS {metric_label} is \"{_premise_dir}\" for its subject. Validate that "
            "premise before explaining it. Write ONE query that computes " + metric_label + " for the "
            "SUBJECT of the question ALONGSIDE the OVERALL population (drop the subject's own filter) — and "
            "if the subject is one value of a category, also include the top few peer values of that "
            f"category. Title it exactly \"Premise check: is the subject {_premise_dir} vs the rest?\". "
            "Label the subject row and an 'overall (all)' reference row clearly and carry COUNT(*) AS n on "
            f"each. If the subject is NOT materially {_premise_dir} vs the reference, SAY SO — a false "
            "premise reframes the entire answer.\n"
        )

    # DRIVER questions ("do late deliveries lower reviews") carry a derived comparison
    # segment from intake — compare the metric ACROSS that condition (true vs false) as
    # the PRIMARY query, not a per-dimension weakness scan.
    _seg_sql = (intake_data.get("comparison_segment_sql") or "").strip()
    _seg_label = (intake_data.get("comparison_segment_label") or "").strip()
    comparison_segment_section = ""
    if _seg_sql:
        comparison_segment_section = (
            "\nPRIMARY COMPARISON (this is a DRIVER question — answer THIS first and lead with it):\n"
            f"  Condition ({_seg_label or 'segment'}): {_seg_sql}\n"
            "Write ONE query computing the metric grouped by this derived condition:\n"
            "  SELECT (<condition>) AS segment, <metric> AS metric_total, COUNT(*) AS n,\n"
            "         ROUND(<metric> / NULLIF(COUNT(*),0), 2) AS avg_per_record\n"
            "  GROUP BY 1 ORDER BY 1\n"
            "JOIN whatever tables are needed to evaluate BOTH the metric and the condition (e.g. join\n"
            "order_reviews to orders). The contrast between the two groups (true vs false) IS the answer\n"
            "to the question — it matters MORE than the per-dimension scan below.\n"
        )

    # Fix C — reuse the drilled finding's grain-correct query. When this scan is DEEPENING an
    # explorer finding (origin_finding), execute the finding's OWN grounded ranking SQL rather
    # than re-deriving it: the explorer already computed it correctly (e.g. ROAS 6.23), so
    # re-deriving only risks re-introducing the fan-out the finding avoided (the 0.0–0.01 mess).
    # Only reuse a GROUP BY ranking query — a scalar finding has no cross-sectional shape to reuse.
    _anchor = None
    _origin_sql = ((state.get("origin_finding") or {}).get("sql") or "").strip()
    if (_origin_sql and re.match(r"(?is)^\s*(select|with)\b", _origin_sql)
            and re.search(r"(?i)\bgroup\s+by\b", _origin_sql)):
        try:
            from aughor.agent.prompts_investigate import PhasePlan as _PP, PhaseQueryPlan as _PQ
            _anchor = _PP(queries=[_PQ(
                title=f"{metric_label} by dimension (established finding)",
                sql=_origin_sql, chart_type="bar_horizontal",
                rationale="Reuse the drilled finding's grain-correct query so the drill-down reproduces it exactly.")])
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "cross-section origin-finding anchor best-effort", counter="ada.xsec_anchor")

    # Period restriction (forward-chain drill): scope every ranking query to the anomalous period
    # the temporal WHEN lens flagged, so the drill explains WHICH cut concentrated the returns IN
    # THAT PERIOD. Overrides the default "no time filters".
    _period_plan = ""
    _time_rule = "No time filters."
    if period_directive:
        _time_rule = "Apply the PERIOD RESTRICTION below to every query."
        _period_plan = (
            f"\n\nPERIOD RESTRICTION — restrict EVERY query to {period_directive}. Join to the "
            "date-bearing table as needed to apply this filter. This is a drill INTO the flagged "
            "period, so the time filter is REQUIRED (it overrides the 'no time filters' rule)."
        )
    # GRAIN RECONCILIATION — when the multi-lens node hands down a canonical grain, every rate-bearing
    # lens (this WHERE scan + the WHEN trend) computes the rate at the SAME unit of observation, so the
    # report can't show 40% (per order) in one card and 76% (per line item) in another for one concept.
    _grain_plan = _grain_plan_directive(grain) if grain else ""
    _plan_system = (f"Write one ranking query per dimension. Rank the metric ascending (weakest first). "
                    f"{_time_rule}" + _ADA_SQL_GROUNDING)

    def _do_run(_sat_note=""):
        return run_analysis_phase(
        conn, phase_id=_phase_id, title=_phase_title, emoji=_phase_emoji, cap=(8 if _augmented else 5), schema=schema,
        preplanned=_anchor,
        plan_system=_plan_system + _sat_note,
        plan_user=CROSS_SECTION_PLAN_PROMPT.format(
            question=question, metric_label=metric_label, metric_sql=metric_sql,
            metric_table=metric_table, schema=schema, dimensions_list=dimensions_list,
            metric_computation_block=metric_computation_block,
            comparison_segment_section=comparison_segment_section,
            premise_check_section=premise_check_section) + _direction_plan + _period_plan + (extra_directive or "") + _grain_plan,
        interpret_system=(
            "Interpret a cross-sectional ranking scan of a RATIO / percentage metric. Read "
            "metric_total AS that ratio in its own units — NEVER as a dollar total or per-record "
            "average. DIRECTION matters: a LOW ratio is often GOOD (low cost-%, low defect-rate); "
            "judge by what the ratio measures, do not assume the minimum is the problem. Only call a "
            "value 'weak'/'underperforming' if clearly adverse vs a benchmark or a real outlier; "
            "otherwise use relative language and say the spread is tight/healthy."
            if is_ratio else
            "Interpret a cross-sectional ranking scan. Name the LOWEST-RANKED values and any "
            "concentration. SEVERITY GROUNDING: only call a value 'weak', 'critically low', "
            "'underperforming', or 'the weakest' if it is below a stated benchmark/target or far "
            "below the in-result average — being the minimum of a ranking is NOT, by itself, "
            "evidence it is unhealthy. Otherwise use relative language ('the lowest at X vs the ~Y "
            "average'). Be explicit when the spread is tight and all values are healthy."
        ) + _direction_interp,
        interpret_user_fn=(lambda results_text: CROSS_SECTION_RATIO_INTERPRET_PROMPT.format(
            question=question, metric_label=metric_label, results_text=results_text))
        if is_ratio else
        (lambda results_text: CROSS_SECTION_INTERPRET_PROMPT.format(
            question=question, metric_label=metric_label, results_text=results_text)),
        plan_error_msg="Cross-sectional planning failed.",
        exec_error_msg="Cross-sectional queries failed.",
        question=question, connection_id=state.get("connection_id", ""),
        )

    _run = _do_run()
    # #2 — reattempt ONCE on a SATURATED result: every group came back pinned at ~0% or ~100% — the
    # signature of a tautology (grouped by an event-only column) or a fan-out, NOT a real finding.
    # (A period drill / preplanned anchor is exempt.) Keep the re-plan only if it clears the
    # saturation; otherwise fall through to the honest fan-out caveat below.
    if _run.ok and _run.results and not period_directive and not _anchor and any(
            _is_saturated(r.columns, r.rows) for _q, r in _run.results if not r.error and r.rows):
        _run2 = _do_run(
            "\n\nPREVIOUS RESULT WAS SATURATED — every group came back at ~0% or ~100%. That is a "
            "tautology or a fan-out, NOT a real result: you likely grouped by a column that exists "
            "ONLY for the event (so the rate is trivially 100%), or joined a table that multiplies the "
            "metric table's rows. Recompute the RATE over the FULL population at the metric table's OWN "
            "grain — group by a column present for EVERY row, and DROP any dimension that lives on an "
            "event/child table (it cannot express a population rate).")
        if _run2.ok and _run2.results and not all(
                _is_saturated(r.columns, r.rows) for _q, r in _run2.results if not r.error and r.rows):
            _run = _run2
    if not _run.ok:
        return {"investigation_phases": phases + [_run.error_phase]}
    results, _results_text, interpretation = _run.results, _run.results_text, _run.interpretation

    # Finding-id prefix — distinct per lens so two parallel scans can't collide their ids
    # (default "cross_section" keeps the historical "xsec" prefix → byte-identical).
    _fprefix = "xsec" if _phase_id == "cross_section" else _phase_id
    if interpretation and interpretation.findings:
        findings = _assemble_phase_findings(results, interpretation.findings, _fprefix, metric_label=metric_label)
        summary = interpretation.phase_summary
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"{_fprefix}_{i}", title=q.title, sql=r.sql,
                columns=r.columns, rows=r.rows[:50], row_count=r.row_count,
                error=r.error, interpretation="Query executed.",
                key_numbers=[], chart_type=q.chart_type, stat_note=None, is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = "Cross-sectional scan complete."

    # A ratio metric that reads as a percentage (return rate, cost-%, conversion) — the value is
    # stored as a fraction/percent that must render "41.0%" on EVERY surface. Tag the column so the
    # chart axis, data labels, table, and key numbers all format it the one same way (approach a).
    _metric_is_pct = is_ratio and _metric_is_percent(metric_sql, metric_label)

    # Make the bar plot the metric itself: for a ratio, plot metric_total (the %/rate) and drop the
    # large numerator/denominator aggregates; for an additive metric, plot the magnitude not its share.
    from aughor.kernel.flags import flag_enabled as _flag_enabled
    _decision_grade = _flag_enabled("lens.decision_grade")
    _exhibit_grammar = _flag_enabled("chart.exhibit_grammar")
    for f in findings:
        if is_ratio:
            _chart_ratio_primary(f)
        else:
            _chart_primary_is_metric(f)
        # A cross-sectional scan RANKS the metric across a dimension → a sorted horizontal bar (intent-
        # driven), not a data-shape guess that could turn a 2-numeric ratio finding into a combo.
        f["chart_type"] = _chart_type_for_finding(f, "ranking")
        # F4 — key numbers must match the chart they sit beside (recompute extremes from the rows),
        # scale-aware for a percent metric so the section value can't read "0.41%" beside a "41.0%" bar.
        _fix_xsec_extreme_key_numbers(f, is_pct=_metric_is_pct)
        # Tag % columns + canonicalise every key number's scale/precision (no-op for non-% metrics).
        _apply_percent_formatting(f, _metric_is_pct)
        # Tag money columns with the metric's SOURCE currency (fare_chf → "currency:CHF") so the
        # chart axis can't say € over CHF data. Percent units win; token-less SQL is a no-op.
        _tag_currency_columns(f, metric_sql)
        # R15 — decision-grade opportunity framing: benchmark-gap × volume, computed
        # deterministically from this finding's own segment rows (no model, no extra
        # query). Flag-gated; a grid the lens can't read honestly annotates nothing.
        if _decision_grade:
            from aughor.agent.opportunity import annotate_opportunity, metric_lower_is_better
            # Orient the benchmark: for a cost-like metric (refund rate, cancellations)
            # the laggard is the HIGHEST segment, so benchmarking upward would invert the
            # claim. The renderers already derive this to pick a red ramp; the math is the
            # consumer the signal never reached.
            annotate_opportunity(f, metric_label=metric_label, is_ratio=is_ratio,
                                 is_percent=_metric_is_pct,
                                 lower_is_better=metric_lower_is_better(metric_label, metric_sql))
        # Chart-grammar exhibit — severity ramp for a rate ranking + deterministic
        # reference lines (segment-weighted average; the R15 best-peer benchmark),
        # computed from this finding's own rows. No model, no extra query; fail-open.
        if _exhibit_grammar:
            from aughor.agent.exhibit import exhibit_for_cross_section
            exhibit_for_cross_section(f, is_ratio=is_ratio, is_percent=_metric_is_pct)

    # Numeric fan-out backstop — the AST chasm detectors miss some join shapes and the coder can
    # reinterpret the metric, so verify the NUMBERS on the RAW results (all columns present). Two
    # metric-agnostic, deterministic checks against the metric table computed WITHOUT joins:
    #   • row-count: a clean per-group aggregate scans at most the metric table's rows (filters only
    #     reduce). If the COUNT(*) `n` summed across groups far exceeds that, a join multiplied the
    #     rows — the $4.4B / $11.1T stockout totals had n≈29M vs inventory's 168k.
    #   • grand-total (additive, single-table metric): the parts must sum to the metric's true total.
    # Either overshoot ⇒ fan-out, whatever the SQL shape. Fail-open.
    _fanned_sqls: set = set()   # #3: the SPECIFIC finding SQLs that over-scanned (scoped, not phase-wide)
    _numeric_fanout = None
    if metric_table and results:
        try:
            _dialect = getattr(conn, "dialect", "duckdb")
            def _num(v):
                try: return float(str(v).replace(",", ""))
                except Exception: return None
            _cnt = conn.execute("__xsec_base_rows__", f"SELECT COUNT(*) FROM {metric_table}")
            _base_rows = _num(_cnt.rows[0][0]) if (_cnt and _cnt.rows and _cnt.rows[0]) else None

            def _scanned_rows(sql):
                # Rewrite the finding's query to COUNT(*) over its FROM/JOIN/WHERE (drop the
                # projection, GROUP BY, HAVING, ORDER, LIMIT) to measure the actual post-join
                # cardinality the aggregate ran over — robust to any metric expression or column set.
                try:
                    import sqlglot as _sg
                    from sqlglot import exp as _sgx
                    _tree = _sg.parse_one(sql, read=_dialect)
                    for _k in ("group", "having", "order", "limit", "qualify", "distinct"):
                        _tree.set(_k, None)
                    _tree.set("expressions", [_sgx.Count(this=_sgx.Star())])
                    _r = conn.execute("__xsec_scanned__", _tree.sql(dialect=_dialect))
                    return _num(_r.rows[0][0]) if (_r and _r.rows and _r.rows[0]) else None
                except Exception:
                    return None

            if _base_rows and _base_rows > 0:
                for _q, r in results:
                    _sql = getattr(r, "sql", None) or getattr(_q, "sql", None)
                    if not _sql:
                        continue
                    _scanned = _scanned_rows(_sql)
                    if _scanned and _scanned > _base_rows * 1.5:
                        _fanned_sqls.add(_sql)   # record EVERY offender — don't break — so the caveat
                        _numeric_fanout = (      # lands on exactly the fanned finding, not its siblings
                            f"This finding's scan touched ~{_scanned:,.0f} rows but the metric's table "
                            f"({metric_table}) has only ~{_base_rows:,.0f} — a join multiplied the rows, "
                            "so its magnitude is inflated by a fan-out (needs a grain-correct recompute).")
        except Exception:
            _fanned_sqls = set()
            _numeric_fanout = None

    # Fail-safe: a fan-out (AST-detected re-plan-unresolved OR numeric backstop) means the magnitude
    # can't be trusted — caveat the offender + strip significance. #3: SCOPE it. The numeric backstop
    # is per-SQL, so only the findings whose OWN query over-scanned are flagged — a clean sibling like
    # 'by platform' is no longer tarred by another finding's fan-out. The AST phase caveat is
    # phase-level; apply it broadly only when the numeric backstop found no specific offender.
    # A ratio suppressed here is corrupt at the METRIC level (the shared metric_sql), so every other
    # phase that renders it — the temporal tile, a baseline chart — is corrupt too. Record a terminal
    # signal that synthesis uses to scrub those and to state the true level instead of the artifact.
    _suppressed_ratio: Optional[dict] = None
    _eff_caveat = _numeric_fanout or _run.fanout_caveat
    if _eff_caveat:
        def _finding_fanned(f):
            return (f.get("sql") in _fanned_sqls) if _fanned_sqls else True
        _fanned = [f for f in findings if _finding_fanned(f)]
        for f in _fanned:
            f["trust_caveat"] = f.get("trust_caveat") or _eff_caveat
            f["is_significant"] = False
        if _fanned:
            if is_ratio:
                # Fix B — a fanned RATIO is corrupted, not merely inflated; suppress its values + ranking
                # rather than present and let the narrator rationalise an artifact (the ROAS 0.0–0.01 mess).
                summary = _suppress_fanned_ratio(_fanned, metric_label, _eff_caveat)
                _suppressed_ratio = {"metric_label": metric_label, "caveat": _eff_caveat,
                                     "true_global_str": None}
            else:
                summary = f"⚠ {_eff_caveat} " + (summary or "")

    # Global-ratio plausibility guard (fix 1+2): for a composite-ratio metric, a conditioned
    # denominator (denominator inner-joined through the numerator's event table) or any broken ratio
    # inflates EVERY segment far above the metric's true global level — a class no fan-out/saturation
    # guard catches. Compute the true global independently and, if every segment is implausibly high,
    # suppress the corrupted numbers + state the true global so synthesis can't headline the artifact.
    if is_ratio and _metric_is_composite_ratio(metric_sql):
        _plausibility = _global_ratio_plausibility_guard(findings, conn, metric_sql, metric_label)
        if _plausibility:
            for f in findings:
                f["trust_caveat"] = f.get("trust_caveat") or _plausibility["caveat"]
                f["is_significant"] = False
            summary = _suppress_fanned_ratio(findings, metric_label, _plausibility["caveat"])
            # The conditioned-denominator guard KNOWS the true level — carry it, so synthesis
            # cites 2.8%, not the 49–69% artifacts.
            _suppressed_ratio = {"metric_label": metric_label, "caveat": _plausibility["caveat"],
                                 "true_global_str": _plausibility["true_global_str"]}

    phase = _phase_result(
        _phase_id, _phase_title, _phase_emoji,
        "complete" if any(not f["error"] for f in findings) else "partial",
        summary, findings,
    )
    result_phases = phases + [phase]
    # Auto-drill WHERE→WHY: the rate scan above localised WHERE the metric concentrates; now compose the
    # event-only dims (return reason / condition / carrier) to answer WHY — the share of returns each
    # accounts for — instead of stopping at the WHERE and merely recommending the drill. Fail-open: a
    # skipped/failed composition never costs the WHERE finding that already ran.
    if _causal_drill and _why_event_dims:
        _why_phase = _run_composition_lens(state, conn, _why_event_dims)
        if _why_phase:
            result_phases = result_phases + [_why_phase]
    # Loss-playbook lenses (flag intake.loss_signals) — mirror of the multilens path, so
    # the leakage/utilization stories run whichever cross-section variant is live. Only
    # on the ROOT invocation: the multilens node calls this function once per partitioned
    # lens (dims_override set) and appends the loss phases itself at merge time — running
    # them here too duplicated the phase in the report (seen live, run b59f9bcd).
    if dims_override is None:
        result_phases = result_phases + _run_loss_lens_phases(state, conn)
    out = {"investigation_phases": result_phases, "_cross_section_summary": summary}
    if _suppressed_ratio:
        out["_suppressed_ratio"] = _suppressed_ratio
    return out


# ── Parallel multi-lens cross-section (flag: ada.parallel_lenses) ──────────────
# A cross-sectional "why is X high/low" question has independent investigative angles: WHERE it
# concentrates (segment/product dimensions) and the MECHANISM behind it (reason/condition/logistics
# dimensions). The single bundled scan interprets all dimensions at once — shallow per-angle. This
# runs one focused cross_section lens PER angle CONCURRENTLY (each reuses the full ada_cross_section
# scan + its guards on its own make_reader clone), so a "why" question gets a deeper, multi-angle
# answer at ~flat wall-clock. In-process ContextThreadPoolExecutor (metering/budget propagate);
# ada_synthesize already reasons over every phase in investigation_phases, so the extra lens is
# picked up automatically. Off by default → the single scan above. See docs/PARALLEL_MULTIAGENT_GROUNDWORK.md.

import logging as _logging
_lens_logger = _logging.getLogger("aughor.agent.investigate")

_ADA_LENS_WIDTH = int(__import__("os").getenv("AUGHOR_ADA_LENS_WIDTH", "4"))

def _dim_column(dim: str) -> str:
    """The bare column name of a `schema.table.column` (or `table.column`) dimension ref."""
    return (dim or "").rsplit(".", 1)[-1].lower()


def _dim_table(dim: str) -> str:
    """The bare table name of a `schema.table.column` (or `table.column`) dimension ref."""
    parts = (dim or "").split(".")
    return parts[-2].lower() if len(parts) >= 2 else ""


# ── Canonical grain (follow-up A: reconcile WHERE/WHY/WHEN lens grain) ─────────
# A cross-sectional "why is the rate high" analysis can compute the SAME rate at two different
# grains — per order (~40%) vs per line-item (~76%) — across lenses, so the report contradicts
# itself. The metric's OWN table (the intake `metric_table`) is the canonical unit of observation
# (the same principle the measure-additivity guards enforce); every rate-bearing lens is handed
# this grain so they all divide by the same denominator and label the number with the same unit.
_GRAIN_ITEM_RE = re.compile(r"(item|line|_line$|lineitem)", re.I)


def _canonical_grain(intake_data: dict) -> Optional[dict]:
    """The analysis's canonical grain, derived once from the intake's metric table. Returns
    {'table': <qualified>, 'label': <human unit>} or None when no metric table is known."""
    mt = (intake_data or {}).get("metric_table") or ""
    if not mt:
        return None
    bare = _bare(mt)
    # Human unit: an *_items / *_lines table is a line-item grain; otherwise singularise the
    # table name (orders → order, returns → return, customers → customer).
    if _GRAIN_ITEM_RE.search(bare):
        label = "line item"
    else:
        singular = bare[:-1] if bare.lower().endswith("s") else bare
        label = singular.replace("_", " ").strip() or bare
    return {"table": mt, "label": label}


def _grain_plan_directive(grain: dict) -> str:
    """Plan-prompt directive pinning every rate to the canonical grain (so lenses agree)."""
    if not grain:
        return ""
    return (
        f"\n\nGRAIN (measure consistently across lenses): compute the rate at the {grain['label']} "
        f"grain — one row per {grain['table']} row (denominator = COUNT(*) over {grain['table']}, or "
        f"COUNT(DISTINCT its primary key). When you JOIN another table for a segment or a date, KEEP "
        f"{grain['table']} as the unit of observation; do NOT collapse to a coarser grain (e.g. distinct "
        f"orders) — every lens in this analysis reports this rate per {grain['label']}, so a different "
        f"grain here would contradict them."
    )


def _grain_summary_tag(grain: dict) -> str:
    """Short, deterministic phase-summary prefix naming the grain (e.g. '[per line item]')."""
    return f"[per {grain['label']}]" if grain and grain.get("label") else ""


def _is_event_dim(dim: str) -> bool:
    """True when the dimension lives on an EVENT-only table (returns/refunds/…). Such a row exists
    ONLY for the event, so a 'rate by this dimension' over the population is tautologically 100%
    (`reason='size_fit' → 100% returned`, by construction) — it must be analysed as COMPOSITION
    (share of the event) instead. Classifying by TABLE (not the column name) is what routes
    `return_logistics.restocked` correctly — a name regex missed it and let it fan out a rate scan."""
    return bool(_EVENT_TABLE_RE.search(_dim_table(dim)))


def _partition_dimensions(dimensions: list) -> list[tuple]:
    """Split the intake dimensions into lens groups by whether they describe the POPULATION (a rate
    scan — the WHERE) or the EVENT itself (a composition/share scan — the WHY). Returns a list of
    (group_name, dims, phase_meta, kind) for each NON-EMPTY group; kind ∈ {'rate','composition'}. A
    single population group keeps the canonical 'cross_section' identity (byte-identical single scan);
    a single event group runs as composition."""
    dims = [d for d in (dimensions or []) if d]
    event = [d for d in dims if _is_event_dim(d)]
    pop = [d for d in dims if not _is_event_dim(d)]
    specs: list = []
    if pop:
        specs.append(("segment", pop, ("cross_section", "Cross-Sectional Scan — Where", "🧭"), "rate"))
    if event:
        specs.append(("mechanism", event, ("cross_section_mechanism", "Mechanism / Reason Scan — Why", "🔍"), "composition"))
    if not specs:
        return [("all", dims, ("cross_section", "Cross-Sectional Scan", "🧭"), "rate")]
    if len(specs) == 1 and specs[0][3] == "rate":
        # Pure-population question → the canonical single scan (byte-identical to the un-split path).
        _, gdims, _, _ = specs[0]
        return [("all", gdims, ("cross_section", "Cross-Sectional Scan", "🧭"), "rate")]
    return specs


# ── #4: discriminating population-attribute discovery ─────────────────────────
# The intake often picks obvious dimensions (brand/tier/platform) and misses discriminating
# POPULATION attributes on a joinable dimension table — e.g. a product's price band or season,
# which really do move the metric (womenswear return rate climbs 31%→40% with price). This
# deterministically surfaces them so the rate lens looks where the answer actually is.
_PRICE_COL_RE = re.compile(r"(price|amount|revenue|gmv|_eur$|_usd$|_gbp$|value)", re.I)
_NUMERIC_TYPE_RE = re.compile(r"(int|float|double|decimal|numeric|real|money|bigint)", re.I)
_SUBJECT_FILTER_COLS = {"category", "subcategory", "sub_category", "segment", "type"}


def _discover_population_dims(state: AgentState, conn: "DatabaseConnection") -> dict:
    """Surface discriminating POPULATION attributes the intake missed: a joinable dimension table's
    low-cardinality categoricals (e.g. season) + a price/value numeric to band by. Returns
    {extra_dims, price_col, join_table, join_key, metric_table} or {}. Deterministic, fail-open."""
    try:
        intake = state.get("_ada_intake") or {}
        metric_table = intake.get("metric_table") or ""
        if not metric_table or "." not in metric_table:
            return {}
        typed = _db_typed_columns(conn, metric_table.split(".")[0])
        if not typed:
            return {}
        mcols = {c.lower() for c, _ in typed.get(metric_table, [])}
        fk_ids = {c for c in mcols if c.endswith("_id")}
        if not fk_ids:
            return {}
        existing = {_dim_column(d) for d in (intake.get("dimensions") or [])}

        # Candidate dimension tables: PRODUCT/ITEM tables (an item's OWN attributes — price, season —
        # are the most on-target) and the ORDER/population parent, ranked product-first. Tangential
        # satellites (customer_service, inventory_snapshots, …) are excluded — their attributes are
        # sparse and off-question even when the join is unique.
        def _score(t):
            return 0 if re.search(r"(product|item|sku|catalog)", _bare(t)) else 1
        cands = sorted(
            [t for t, cols in typed.items()
             if t != metric_table and not _EVENT_TABLE_RE.search(_bare(t))
             and (fk_ids & {c.lower() for c, _ in cols})
             and (_score(t) == 0 or _POP_TABLE_RE.search(_bare(t)))],
            key=_score,
        )[:8]

        extra_dims: list = []
        price_col = join_table = join_key = None
        for t in cands:
            cols = typed[t]
            shared = fk_ids & {c.lower() for c, _ in cols}
            # prefer a product/item key for the join
            _jk = sorted(shared, key=lambda k: 0 if re.search(r"(product|item|sku)", k) else 1)[0]
            # UNIQUENESS gate — only a 1:1 / many-1 DIMENSION join is safe. If the key repeats in this
            # table (e.g. many customer_service rows per order_id), the join fans out and would inflate
            # the metric — skip it. This is the guard the first cut missed.
            try:
                _u = conn.execute("__uniq_probe__", f"SELECT COUNT(*), COUNT(DISTINCT {_jk}) FROM {t}")
                _tot, _dist = int(_u.rows[0][0]), int(_u.rows[0][1])
                if _dist < _tot:
                    continue
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, f"uniqueness probe on {t} failed; skip this dim-source",
                         counter="ada.pop_discover")
                continue
            for c, ty in cols:
                cl = c.lower()
                if cl.endswith("_id") or cl in existing or cl in _SUBJECT_FILTER_COLS:
                    continue
                if price_col is None and _NUMERIC_TYPE_RE.search(ty) and _PRICE_COL_RE.search(cl) \
                        and "cost" not in cl:
                    price_col, join_table, join_key = f"{t}.{c}", t, _jk
                    continue
                if ("char" in ty.lower() or "text" in ty.lower()) and len(extra_dims) < 2 \
                        and cl not in {_dim_column(d) for d in extra_dims}:
                    try:
                        _r = conn.execute("__card_probe__", f"SELECT COUNT(DISTINCT {c}) FROM {t}")
                        _nd = int(_r.rows[0][0]) if (_r and _r.rows and _r.rows[0]) else 999
                    except Exception:
                        _nd = 999
                    if 2 <= _nd <= 25:
                        extra_dims.append(f"{t}.{c}")
                        join_table, join_key = join_table or t, join_key or _jk
            if price_col and len(extra_dims) >= 2:
                break
        if not extra_dims and not price_col:
            return {}
        return {"extra_dims": extra_dims, "price_col": price_col, "join_table": join_table,
                "join_key": join_key, "metric_table": metric_table}
    except Exception:
        return {}


def _render_join_schema(pop_aug: dict, conn: "DatabaseConnection") -> Optional[str]:
    """A minimal schema snippet for the discovered dimension table + its join, so the rate lens can
    actually reach the augmented attributes (the intake's filtered schema usually omits it)."""
    t = pop_aug.get("join_table")
    jk = pop_aug.get("join_key")
    mt = pop_aug.get("metric_table")
    if not (t and jk and mt):
        return None
    try:
        cols = [c for c, _ in _db_typed_columns(conn, t.split(".")[0]).get(t, [])]
        if not cols:
            return None
        return (f"\n\nJOINABLE DIMENSION TABLE (use for the augmented attributes):\n"
                f"TABLE: {t}\n  columns: {', '.join(cols)}\n  join: {mt}.{jk} = {t}.{jk}\n")
    except Exception:
        return None


def _price_band_directive(pop_aug: dict) -> Optional[str]:
    """Plan appendix: add ONE ranking of the metric by PRICE BAND (a numeric can't be grouped raw)."""
    pc = pop_aug.get("price_col")
    if not pc:
        return None
    t, jk, mt = pop_aug.get("join_table"), pop_aug.get("join_key"), pop_aug.get("metric_table")
    return (f"\n\nALSO add ONE ranking of the metric by PRICE BAND: join {mt} to {t} on {jk} and bucket "
            f"{pc} into bands (e.g. <500 / 500–1500 / 1500–3000 / 3000+) with a CASE, then compute the "
            "metric per band ordered by band. Higher-priced items often return more — this is a "
            "discriminating attribute worth surfacing.")


def _is_saturated(columns: list, rows: list) -> bool:
    """#2 — a rate/metric result is SATURATED when EVERY non-null group value is pinned at a boundary
    (~0, ~1.0, or ~100) across ≥2 groups — the signature of a tautology (grouped by an event-only
    column) or a fan-out. This is DISTINCT from legitimate uniformity (values clustered but NOT at a
    boundary, e.g. 32.4 / 32.8) — a real 'flat' finding, which must never be reattempted. Never raises."""
    try:
        if not rows or len(rows) < 2:
            return False
        cl = [str(c).lower() for c in columns]

        def _num(v):
            try:
                return float(str(v).replace(",", "").replace("%", ""))
            except Exception:
                return None
        # locate the metric column: prefer a rate/ratio-named one, else the first numeric non-count col
        m_idx = next((i for i, c in enumerate(cl)
                      if any(k in c for k in ("rate", "pct", "percent", "ratio", "metric_total", "metric_value"))),
                     None)
        if m_idx is None:
            for i, c in enumerate(cl):
                if any(k in c for k in ("count", "_n", "n_", "num", "denom", "event_count", "id")):
                    continue
                if any(_num(r[i]) is not None for r in rows if i < len(r)):
                    m_idx = i
                    break
        if m_idx is None:
            return False
        vals = [_num(r[m_idx]) for r in rows if m_idx < len(r) and _num(r[m_idx]) is not None]
        if len(vals) < 2:
            return False

        def _boundary(v):
            return v <= 0.001 or abs(v - 1.0) <= 0.001 or abs(v - 100.0) <= 0.05
        # saturated only if EVERY value sits at a boundary (all-0 / all-100 / a 0∪1 mix = tautology)
        return all(_boundary(v) for v in vals)
    except Exception:
        return False


# ── Temporal WHEN lens + forward-chain period drill ───────────────────────────
# A flat cross-sectional average can hide a period concentration (a brand/category whose returns
# spiked in a specific season dragging the yearly number). The WHEN lens trends the metric over
# time and deterministically flags any period that materially deviates; if one is found, a
# forward-chain drill re-runs the segment/mechanism scan SCOPED to that period. Fixes the intake's
# frequent blindness (it declares date_column=NONE when the event table has no date, even though the
# population/order date is join-reachable). See docs/PARALLEL_MULTIAGENT_GROUNDWORK.md.

# Tables that hold an EVENT (returns/refunds/cancellations) — their date column only exists for the
# event, so it cannot express an event-RATE over time (the denominator population isn't dated there).
_EVENT_TABLE_RE = re.compile(r"(return|refund|cancel|dispute|complaint|chargeback)", re.I)
_POP_TABLE_RE = re.compile(r"(order|sale|transaction|purchase|booking|invoice|shipment|line_item)", re.I)


def _db_typed_columns(conn: "DatabaseConnection", schema_name: str) -> dict:
    """Authoritative {schema.table: [(col, type)]} from the live DB (information_schema) — robust to
    whatever schema-string format the agent is carrying (the data-catalog form isn't type-parseable).
    Fail-open to {} so the caller falls back to the schema-string parse."""
    try:
        if not schema_name:
            return {}
        res = conn.execute("__temporal_types__",
                           "SELECT table_name, column_name, data_type FROM information_schema.columns "
                           f"WHERE table_schema = '{schema_name}'")
        if getattr(res, "error", None) or not getattr(res, "rows", None):
            return {}
        out: dict = {}
        for r in res.rows:
            out.setdefault(f"{schema_name}.{r[0]}", []).append((str(r[1]), str(r[2])))
        return out
    except Exception:
        return {}


def _resolve_temporal_axis(state: AgentState, conn: "DatabaseConnection" = None,
                           intake_data: Optional[dict] = None) -> Optional[dict]:
    """Deterministically find a PURCHASE/population date for the metric so it can be trended over
    time — the metric table's own date, else a population/order table's date reachable by join.
    For an event-RATE metric (returns/refunds) the event table's own date is EXCLUDED (it only
    covers the numerator). Returns {date_column, date_table, metric_table} or None. Fail-open.

    `intake_data` lets a caller pass the intake spec directly (e.g. `ada_intake`, where the spec
    isn't in `state['_ada_intake']` yet); defaults to the state-stored spec for the lens path."""
    try:
        intake = intake_data if intake_data is not None else (state.get("_ada_intake") or {})
        metric_table = intake.get("metric_table") or ""
        if not metric_table:
            return None
        blob = f"{intake.get('metric_sql','')} {intake.get('metric_label','')} {_bare(metric_table)}".lower()
        metric_is_event = bool(_EVENT_TABLE_RE.search(blob))
        # Prefer authoritative types from the live DB (the schema_context in the live path is the
        # structured data-catalog, which _typed_columns can't parse); fall back to the string parse.
        schema_name = metric_table.split(".")[0] if "." in metric_table else (state.get("scope_schema") or "")
        typed = _db_typed_columns(conn, schema_name) if conn is not None else {}
        if not typed:
            typed = _typed_columns(state.get("schema_context") or intake.get("filtered_schema") or "")
        if not typed:
            return None
        full_schema = state.get("schema_context") or intake.get("filtered_schema") or ""
        dims = intake.get("dimensions") or []
        seeds = list(dict.fromkeys([metric_table] + [d.rsplit(".", 1)[0] for d in dims if "." in d]))
        try:
            from aughor.tools.schema import fk_neighbor_expand
            seeds = fk_neighbor_expand(full_schema, seeds, cap=12)
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "fk-neighbour expand best-effort; using bare seeds", counter="ada.temporal_axis")
        seed_bare = {_bare(s) for s in seeds}

        def _score(t: str) -> int:
            b = _bare(t)
            if b == _bare(metric_table):
                return 0
            if _POP_TABLE_RE.search(b):
                return 1
            if b in seed_bare:
                return 2
            return 3

        cands = sorted(typed.keys(), key=_score)
        if metric_is_event:
            # Drop event tables (their date can't date the denominator) unless it IS the metric table.
            cands = [t for t in cands
                     if not _EVENT_TABLE_RE.search(_bare(t)) or _bare(t) == _bare(metric_table)]
        for type_first in (True, False):
            for t in cands:
                for c, ty in typed.get(t, []):
                    hit = _DATE_TYPE_RE.search(ty) if type_first else (
                        _DATE_NAME_RE.search(c) and not _KEYISH_RE.search(c))
                    if hit:
                        return {"date_column": f"{t}.{c}", "date_table": t, "metric_table": metric_table}
        return None
    except Exception:
        return None


def _detect_anomalous_period(columns: list, rows: list) -> Optional[dict]:
    """Deterministically flag a period whose metric MATERIALLY deviates above the run's baseline,
    on a sufficient sample — the honest gate that fires the forward-chain drill. Returns
    {period, value, baseline, n} for the single worst qualifying period, or None when the trend is
    flat / too few periods / small-sample blips. Expects a (period, metric_value, n) shape but
    falls back to positional numeric detection. Never raises."""
    try:
        if not rows or len(rows) < 3:  # need a few periods to call one anomalous
            return None
        cl = [str(c).lower() for c in columns]

        def _find(patterns, default_idx):
            for i, c in enumerate(cl):
                if any(p in c for p in patterns):
                    return i
            return default_idx

        p_idx = _find(["period", "month", "quarter", "year", "date", "bucket"], 0)
        n_idx = _find(["n", "count", "items", "orders", "rows", "volume"], len(columns) - 1)

        def _num(v):
            try:
                return float(str(v).replace(",", "").replace("%", ""))
            except Exception:
                return None
        # metric = the numeric column that is neither period nor n; prefer a rate/pct-named one.
        m_idx = None
        for i, c in enumerate(cl):
            if i in (p_idx, n_idx):
                continue
            if any(k in c for k in ("rate", "pct", "percent", "ratio", "metric", "value", "avg")):
                m_idx = i
                break
        if m_idx is None:
            for i in range(len(columns)):
                if i in (p_idx, n_idx):
                    continue
                if any(_num(r[i]) is not None for r in rows):
                    m_idx = i
                    break
        if m_idx is None:
            return None

        pts = []
        for r in rows:
            v = _num(r[m_idx])
            n = _num(r[n_idx]) if n_idx < len(r) else None
            if v is None:
                continue
            pts.append((r[p_idx], v, (n if n is not None else 1.0)))
        if len(pts) < 3:
            return None
        vals = [v for _, v, _ in pts]
        total_n = sum(n for _, _, n in pts)
        # weighted baseline (by sample) + population std
        baseline = sum(v * n for _, v, n in pts) / total_n if total_n else sum(vals) / len(vals)
        var = sum((v - baseline) ** 2 for v in vals) / len(vals)
        std = var ** 0.5
        min_n = max(30.0, 0.03 * total_n)   # a period must carry a material share to count
        # worst qualifying period: materially above baseline (relative AND absolute-vs-spread) on real volume
        best = None
        for period, v, n in pts:
            if n < min_n:
                continue
            if v > baseline * 1.20 and v > baseline + 1.5 * std:
                if best is None or v > best[1]:
                    best = (period, v, n)
        if best is None:
            return None
        return {"period": str(best[0]), "value": round(best[1], 2),
                "baseline": round(baseline, 2), "n": int(best[2])}
    except Exception:
        return None


_MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt_period(v) -> str:
    """A period value → a compact human label ("2022-07-01" / "2022-07" → "Jul 2022")."""
    m = re.match(r"^(\d{4})-(\d{2})", str(v))
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{_MONTHS_ABBR[int(m.group(2)) - 1]} {m.group(1)}"
    return str(v)


def _fix_temporal_extreme_key_numbers(finding: dict, is_pct: bool = True) -> None:
    """Recompute a temporal trend's peak / trough / average / range key numbers from the FULL series
    rows, so they can't disagree with the chart (which plots every row). The interpret LLM only sees a
    capped window, so left to itself it can call a "peak" from the first year while the chart's real
    maximum sits in a later month. Deterministic, scale-aware, best-effort."""
    cols = [str(c) for c in (finding.get("columns") or [])]
    rows = finding.get("rows") or []
    kns = finding.get("key_numbers") or []
    if len(rows) < 2 or not kns or not cols:
        return

    def _num(v):
        try:
            return float(str(v).replace(",", "").replace("%", "").strip())
        except (TypeError, ValueError):
            return None

    m_idx = next((i for i, c in enumerate(cols) if _RATIO_METRIC_COL_RE.search(c)), None)
    if m_idx is None:
        for i, c in enumerate(cols):
            if c.lower() in ("n", "count"):
                continue
            if any(_num(r[i]) is not None for r in rows if i < len(r)):
                m_idx = i
                break
    if m_idx is None:
        return
    p_idx = next((i for i, c in enumerate(cols) if i != m_idx and (_FINDING_DATE_RE.search(c) or "period" in c.lower())), 0)
    pts = [(_num(r[m_idx]), r[p_idx]) for r in rows
           if m_idx < len(r) and p_idx < len(r) and _num(r[m_idx]) is not None]
    if len(pts) < 2:
        return
    vals = [v for v, _ in pts]
    peak = max(pts, key=lambda x: x[0])
    trough = min(pts, key=lambda x: x[0])
    avg = sum(vals) / len(vals)
    scale = 100 if max(abs(v) for v in vals) <= 1.5 else 1   # fraction (0.36) vs already-percent (36)
    fmt = (lambda v: _fmt_pct(v)) if is_pct else (lambda v: f"{v:.2f}")

    def _delta(d):
        return f"{d * scale:+.1f} pts vs avg"

    def _set_period(kn, period):
        for k in ("label", "context"):
            t = kn.get(k)
            if t and "(" in t:
                kn[k] = re.sub(r"\([^)]*\)", f"({_fmt_period(period)})", t, count=1)

    for kn in kns:
        low = f"{kn.get('label') or ''} {kn.get('context') or ''}".lower()
        if any(w in low for w in ("peak", "highest", "maximum", "max ")):
            kn["value"] = fmt(peak[0]); kn["delta"] = _delta(peak[0] - avg); _set_period(kn, peak[1])
        elif any(w in low for w in ("trough", "lowest", "minimum", "min ", "dip")):
            kn["value"] = fmt(trough[0]); kn["delta"] = _delta(trough[0] - avg); _set_period(kn, trough[1])
        elif any(w in low for w in ("average", "mean", "overall")):
            kn["value"] = "~" + fmt(avg)
        elif "range" in low or "spread" in low:
            kn["value"] = f"{fmt(trough[0])} – {fmt(peak[0])}"
            kn["delta"] = f"{(peak[0] - trough[0]) * scale:.1f} pts spread"


def _run_temporal_lens(state: AgentState, conn: "DatabaseConnection", axis: dict,
                       grain: Optional[dict] = None) -> tuple:
    """The WHEN lens: trend the metric over time on the resolved date axis, then deterministically
    detect an anomalous period. Returns (phase_or_None, anomalous_period_or_None). Fail-open.

    `grain` (from the multi-lens node) pins the trend's rate + denominator to the SAME unit the
    WHERE scan uses, so the two lenses' rates are comparable rather than order-vs-item contradictory."""
    intake = state.get("_ada_intake") or {}
    question = state["question"]
    metric_label = intake.get("metric_label", "the metric")
    metric_sql = intake.get("metric_sql", "SUM(revenue)")
    metric_table = intake.get("metric_table", "")
    date_column = axis["date_column"]
    _grain_plan = _grain_plan_directive(grain) if grain else ""
    _grain_n = f"the {grain['label']} population" if grain else "the population"
    schema = _with_ledger(state, intake.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT))
    try:
        _run = run_analysis_phase(
            conn, phase_id="temporal_when", title="Temporal Trend — When", emoji="📈", cap=1, schema=schema,
            plan_system=("Write ONE time-series query trending the metric. Use the SPECIFIED date "
                         "column; JOIN the metric table to the date table if they differ. Bucket by "
                         "month or quarter (choose per the data's span). Restrict to the question's "
                         "subject. Order by the period ASC. Return EXACTLY three columns aliased "
                         f"`period`, `metric_value`, `n` (n = COUNT(*) of {_grain_n} in that period).")
                        + _ADA_SQL_GROUNDING + _grain_plan,
            plan_user=(
                f"QUESTION: {question}\n"
                f"METRIC: {metric_label} = {metric_sql}\n"
                f"METRIC TABLE: {metric_table}\n"
                f"DATE COLUMN (use THIS as the time axis): {date_column}\n\n"
                f"SCHEMA:\n{schema}\n\n"
                "Trend the metric over time so a period that spikes/dips vs the overall level is visible."
            ),
            interpret_system=(
                "Interpret a time trend of the metric. State plainly whether it is STABLE over time "
                "or whether a specific period MATERIALLY deviates (spike/dip) from the overall level; "
                "name the period and magnitude. If the values are flat within noise, say so — do not "
                "manufacture a trend. This answers WHEN, complementing the where/why scans."),
            interpret_user_fn=(lambda results_text:
                f"QUESTION: {question}\nMETRIC: {metric_label}\n\nTIME SERIES:\n{results_text}\n\n"
                "Is the metric stable over time, or does a period stand out? Be specific and honest."),
            plan_error_msg="Temporal trend planning failed.",
            exec_error_msg="Temporal trend query failed.",
            question=question, connection_id=state.get("connection_id", ""),
            # A trend must be read over the WHOLE series — a 12-row cap made the interpreter call a peak
            # from the first year while the chart plots every month (its real max sat in a later row).
            interpret_max_rows=72,
        )
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "temporal lens best-effort; skipped", counter="ada.temporal_lens")
        return None, None

    if not _run.ok:
        return _run.error_phase, None
    results, interp = _run.results, _run.interpretation
    if interp and interp.findings:
        findings = _assemble_phase_findings(results, interp.findings, "when", metric_label=metric_label)
        summary = interp.phase_summary
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"when_{i}", title=q.title, sql=r.sql, columns=r.columns, rows=r.rows[:50],
                row_count=r.row_count, error=r.error, interpretation="Trend computed.",
                key_numbers=[], chart_type=(q.chart_type or "line"), stat_note=None, is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = "Temporal trend complete."

    # A trend is a line (intent-driven); its peak/trough/avg key numbers are recomputed from the FULL
    # series so they match the chart (the interpret LLM only saw a window).
    _is_pct = _metric_is_percent(metric_sql, metric_label)
    for _f in findings:
        _f["chart_type"] = _chart_type_for_finding(_f, "trend")
        _fix_temporal_extreme_key_numbers(_f, is_pct=_is_pct)
    # Tag the trended value as a percent (the SAME unit as the WHERE rate) so its axis + labels read
    # "41%", directly comparable to the segment scan instead of a bare "0.41"; canonicalise key numbers too.
    if _is_pct:
        _tag_percent_columns(findings, _RATIO_METRIC_COL_RE)
        for _f in findings:
            _normalize_pct_key_numbers(_f)

    # Deterministic anomaly detection on the (first clean) trend result.
    anomalous = None
    for _q, r in results:
        if not r.error and r.rows:
            anomalous = _detect_anomalous_period(r.columns, r.rows)
            if anomalous:
                break
    if anomalous:
        summary = (f"⚠ Period concentration: {anomalous['period']} at {anomalous['value']} vs the "
                   f"{anomalous['baseline']} baseline (n={anomalous['n']}). " + (summary or ""))
    phase = _phase_result(
        "temporal_when", "Temporal Trend — When", "📈",
        "complete" if any(not f["error"] for f in findings) else "partial",
        summary, findings,
    )
    return phase, anomalous


def _select_why_dims(event_dims: list) -> list:
    """Order the event dims for the WHY composition by causal relevance and DROP the pure-operational
    ones (carrier / refund method / shipping) when a genuinely causal dim (reason / condition / defect)
    is present — a "why is X high" lens should lead with the CAUSE, not logistics metadata, which
    otherwise dilutes the finding (the womenswear WHY returned 4 pies, 3 of them ops noise). Neutral
    dims (neither vocabulary) are kept as context after the causes. Fail-safe: when NOTHING matches the
    causal vocabulary, keep every dim unchanged so an unusually-named reason column is never silently
    dropped. Order-preserving within each group."""
    causal = [d for d in event_dims if any(k in _dim_column(d) for k in _CAUSAL_DIMENSION_KEYWORDS)]
    if not causal:
        return list(event_dims)          # nothing recognisably causal → don't drop anything
    operational = [d for d in event_dims if d not in causal
                   and any(k in _dim_column(d) for k in _OPERATIONAL_DIMENSION_KEYWORDS)]
    neutral = [d for d in event_dims if d not in causal and d not in operational]
    return causal + neutral              # lead with causes, keep neutral context, drop ops noise


def _run_composition_lens(state: AgentState, conn: "DatabaseConnection", event_dims: list) -> Optional[dict]:
    """The WHY lens for EVENT-only dimensions (return reason / condition / carrier / refund method).
    A 'rate by' these is tautologically 100% (a row exists only if the event happened), so instead we
    compute the COMPOSITION — the share of the events (returns) falling in each value. THAT is the
    actual 'why' (e.g. size_fit = 42% of returns). Returns a phase dict or None. Fail-open."""
    intake = state.get("_ada_intake") or {}
    question = state["question"]
    metric_label = intake.get("metric_label", "the metric")
    schema = _with_ledger(state, intake.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT))
    # Lead the WHY with the causal dims; drop downstream ops metadata (carrier/refund method) so the
    # composition answers "why", not "how it shipped" (fail-safe keeps all when nothing looks causal).
    event_dims = _select_why_dims(event_dims)
    dims_list = "\n".join(f"  - {d}" for d in event_dims[:6])
    try:
        _run = run_analysis_phase(
            conn, phase_id="cross_section_mechanism", title="Mechanism / Reason Scan — Why", emoji="🔍",
            cap=5, schema=schema,
            plan_system=("Write one COMPOSITION query per dimension. These dimensions live on the EVENT "
                         "table (returns/refunds), so a rate over them is meaningless (a row exists only "
                         "if the event happened → always 100%). Instead compute the SHARE of the events: "
                         "COUNT(*) per dimension value AND its percentage of the total events "
                         "(100.0*COUNT(*)/SUM(COUNT(*)) OVER ()). Aggregate the EVENT table itself; "
                         "restrict to the question's subject; ORDER BY count DESC. Return exactly three "
                         "columns aliased `<dimension>`, `event_count`, `pct_of_total`.") + _ADA_SQL_GROUNDING,
            plan_user=(f"QUESTION: {question}\nMETRIC CONTEXT: {metric_label}\n"
                       f"EVENT DIMENSIONS (compose the events/returns by each):\n{dims_list}\n\n"
                       f"SCHEMA:\n{schema}\n\n"
                       "For each dimension, what share of the returns falls in each value? This is the WHY."),
            interpret_system=("Interpret a COMPOSITION of returns by reason / condition / etc. Name the "
                              "LARGEST contributor(s) and their share — that is the leading 'why'. These "
                              "are SHARES of returns that sum to ~100%, NOT rates; never read a share as a "
                              "return rate."),
            interpret_user_fn=(lambda results_text:
                f"QUESTION: {question}\n\nRETURN COMPOSITION:\n{results_text}\n\n"
                "Which reason / mechanism accounts for the largest share of the returns? Lead with it."),
            plan_error_msg="Composition planning failed.", exec_error_msg="Composition query failed.",
            question=question, connection_id=state.get("connection_id", ""),
        )
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "composition lens best-effort; skipped", counter="ada.composition_lens")
        return None
    if not _run.ok:
        return _run.error_phase
    results, interp = _run.results, _run.interpretation
    if interp and interp.findings:
        findings = _assemble_phase_findings(results, interp.findings, "why", metric_label=metric_label)
        summary = interp.phase_summary
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"why_{i}", title=q.title, sql=r.sql, columns=r.columns, rows=r.rows[:50],
                row_count=r.row_count, error=r.error, interpretation="Composition computed.",
                key_numbers=[], chart_type=(q.chart_type or "bar_horizontal"), stat_note=None, is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = "Return composition computed."
    for _f in findings:
        # Chart the SHARE only — a composition is parts-of-a-whole, so the count and the share are the
        # SAME story; a count-bar + share-line dual-axis combo is redundant clutter (the line just
        # mirrors the bars). Drop `event_count` from the rendered view (it stays in the key numbers as
        # context), then let the intent resolver pick a donut for a few parts / a ranked bar for many.
        _chart_ratio_primary(_f)
        _f["chart_type"] = _chart_type_for_finding(_f, "composition")
    # `pct_of_total` is a share (already 0–100) — tag it percent so the UI renders "42.2%", not "42"
    # (its value-range guard would otherwise reject an already-scaled percent as a share column), and
    # canonicalise the key numbers to 1-dp so the WHY cards match the WHERE cards (no "42.23%" vs "41.0%").
    _tag_percent_columns(findings, re.compile(r"pct_of_total|percent|_of_total|\bshare\b", re.I))
    for _f in findings:
        _normalize_pct_key_numbers(_f)
    return _phase_result(
        "cross_section_mechanism", "Mechanism / Reason Scan — Why", "🔍",
        "complete" if any(not f["error"] for f in findings) else "partial", summary, findings,
    )


def _run_period_drill(state: AgentState, conn: "DatabaseConnection", axis: dict,
                      anomalous: dict, lens_specs: list, grain: Optional[dict] = None) -> list:
    """Forward-chain drill: when the WHEN lens flagged a period, re-run the segment/mechanism scan
    SCOPED to that period so we learn WHICH cut concentrated inside it. Sequential (depends on the
    detection). Returns the new phase(s); fail-open to []."""
    from aughor.kernel.metering import BudgetExceeded
    directive = (f"the flagged period {anomalous['period']} (apply a date filter on "
                 f"{axis['date_column']} restricting to that period)")
    phases: list = []
    base_n = len(state.get("investigation_phases", []))
    for name, ldims, pmeta in lens_specs:
        pid, title, emoji = pmeta
        drill_meta = (f"period_drill_{name}", f"{title} · {anomalous['period']}", "🎯")
        try:
            reader = conn.make_reader()
            out = ada_cross_section(state, reader, dims_override=ldims, phase_meta=drill_meta,
                                    period_directive=directive, grain=grain)
            ph = out.get("investigation_phases", [])
            phases.extend(ph[base_n:] if len(ph) > base_n else (ph[-1:] if ph else []))
        except BudgetExceeded:
            raise
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, f"period drill '{name}' best-effort; skipped", counter="ada.period_drill")
    return phases


def _why_where_interaction_enabled() -> bool:
    """Flag `ada.why_where_interaction` (env AUGHOR_ADA_WHY_WHERE_INTERACTION or ledger override).
    Off by default; resolved fail-safe → 'off' on any error."""
    try:
        from aughor.kernel.flags import flag_enabled
        return flag_enabled("ada.why_where_interaction")
    except Exception:
        return False


def _run_interaction_lens(state: AgentState, conn: "DatabaseConnection",
                          where_summary: str, why_summary: str) -> Optional[dict]:
    """Forward-chained WHY×WHERE cross. The WHERE lens found which segment concentrates the metric and
    the WHY lens found the leading reason — but neither tested whether they're LINKED. This composes the
    leading reason's SHARE of returns across the highest-impact segment, so "size/fit is 42% of returns"
    + "high-price returns most" becomes the actionable "size/fit DRIVES the high-price returns → invest
    in fit for that tier" (or, if flat, "the cause is uniform → a broad problem, not segment-specific").
    LLM-planned: it reads the two lens summaries + schema to pick the reason + segment and write the
    join. Returns a phase dict or None. Fail-open."""
    intake = state.get("_ada_intake") or {}
    question = state["question"]
    metric_label = intake.get("metric_label", "the metric")
    schema = _with_ledger(state, intake.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT))
    try:
        _run = run_analysis_phase(
            conn, phase_id="cross_section_interaction",
            title="Interaction — Where the Cause Concentrates", emoji="🔗",
            cap=2, schema=schema,
            plan_system=(
                "Write ONE query that CROSSES the leading return REASON (from the WHY scan) with the "
                "SEGMENT dimension the WHERE scan flagged as concentrating the metric — a platform "
                "tier / price band / channel / region, NOT the question's own subject category (that "
                "stays a FILTER). KEEP the question's subject filter: you are drilling WITHIN the "
                "subject, not comparing it to its peers. For each value of that segment dimension, "
                "compute the SHARE of the subject's returns that are the leading reason: 100.0 * "
                "SUM(CASE WHEN <reason_col> = '<leading value>' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), "
                "0) AS leading_reason_share, plus COUNT(*) AS n. Join the reason (event table) to the "
                "segment dimension (this may require joining through orders / order_items / products). "
                "ORDER BY leading_reason_share DESC. Return exactly three columns: the segment, "
                "leading_reason_share, n. This is a SHARE within the subject — do NOT drop the subject "
                "filter and do NOT compute an overall return rate.") + _ADA_SQL_GROUNDING,
            plan_user=(
                f"QUESTION: {question}\nMETRIC: {metric_label}\n"
                f"WHERE scan found (the segment that concentrates the metric — cross with THIS):\n"
                f"  {where_summary}\n"
                f"WHY scan found (the leading reason):\n  {why_summary}\n\n"
                f"SCHEMA:\n{schema}\n\n"
                "KEEPING the question's subject filter, cross the LEADING reason with the specific "
                "high-impact SEGMENT the WHERE scan named (its platform tier / price band / channel — "
                "not the subject category itself): for each value of that segment, what share of the "
                "subject's returns is the leading reason? This reveals whether the cause concentrates "
                "where the metric is worst."),
            interpret_system=(
                "Interpret a WHY×WHERE cross — the leading return reason's SHARE of returns by segment. "
                "State plainly whether the leading reason CONCENTRATES in the high-metric segment (its "
                "share climbs there → the fix should target that segment) or is roughly UNIFORM across "
                "segments (→ a broad, not segment-specific, problem). Lead with that verdict + the two "
                "extreme shares. These are shares of returns, NOT return rates."),
            interpret_user_fn=(lambda results_text:
                f"QUESTION: {question}\n\nLEADING-REASON SHARE BY SEGMENT:\n{results_text}\n\n"
                "Does the leading reason concentrate in the worst segment, or is it uniform? Lead with "
                "the actionable verdict."),
            plan_error_msg="Interaction planning failed.", exec_error_msg="Interaction query failed.",
            question=question, connection_id=state.get("connection_id", ""),
        )
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "interaction lens best-effort; skipped", counter="ada.interaction_lens")
        return None
    if not _run.ok:
        return _run.error_phase
    results, interp = _run.results, _run.interpretation
    if interp and interp.findings:
        findings = _assemble_phase_findings(results, interp.findings, "interaction", metric_label=metric_label)
        summary = interp.phase_summary
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"interaction_{i}", title=q.title, sql=r.sql, columns=r.columns, rows=r.rows[:50],
                row_count=r.row_count, error=r.error, interpretation="Interaction computed.",
                key_numbers=[], chart_type=(q.chart_type or "bar_horizontal"), stat_note=None, is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = "WHY×WHERE interaction computed."
    _tag_percent_columns(findings, re.compile(r"share|pct|percent|_of_total", re.I))
    for _f in findings:
        _normalize_pct_key_numbers(_f)
        _f["chart_type"] = _chart_type_for_finding(_f, "ranking")
    return _phase_result(
        "cross_section_interaction", "Interaction — Where the Cause Concentrates", "🔗",
        "complete" if any(not f["error"] for f in findings) else "partial", summary, findings,
    )


def _why_deepen_enabled() -> bool:
    """Flag `ada.why_deepen` (env AUGHOR_ADA_WHY_DEEPEN or ledger override) — the peer-benchmark +
    second-level-drill WHY lenses. Off by default; fail-safe → 'off' on any error."""
    try:
        from aughor.kernel.flags import flag_enabled
        return flag_enabled("ada.why_deepen")
    except Exception:
        return False


def _parallel_why_lenses_enabled() -> bool:
    """Flag `ada.parallel_why_lenses` — run the forward-chained WHY lenses (interaction ∥ benchmark ∥
    drill) as one concurrent wave instead of serially. They depend only on the already-computed
    WHERE/WHY summaries, never on each other, so the merge stays byte-identical (fixed spec order).
    Off by default; fail-safe → 'off' on any error."""
    try:
        from aughor.kernel.flags import flag_enabled
        return flag_enabled("ada.parallel_why_lenses")
    except Exception:
        return False


def _run_reason_benchmark_lens(state: AgentState, conn: "DatabaseConnection", why_summary: str) -> Optional[dict]:
    """Peer benchmark for the leading reason: the WHY lens found the leading reason's share of the
    SUBJECT's returns (e.g. size/fit = 42% of womenswear returns), but is that ABNORMAL? This computes
    the same reason's share across the subject AND its peers (the other values of the subject's own
    dimension — other categories) so "42%" becomes "42% vs a 41–44% peer range → a brand-wide baseline,
    NOT a womenswear-specific problem" (or, if the subject tops the peers, "genuinely elevated → real").
    LLM-planned. Returns a phase dict or None. Fail-open."""
    intake = state.get("_ada_intake") or {}
    question = state["question"]
    metric_label = intake.get("metric_label", "the metric")
    schema = _with_ledger(state, intake.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT))
    try:
        _run = run_analysis_phase(
            conn, phase_id="reason_benchmark",
            title="Reason Benchmark — Is the Cause Abnormal?", emoji="📊",
            cap=2, schema=schema,
            plan_system=(
                "Write ONE query that BENCHMARKS the leading return reason (from the WHY scan) for the "
                "subject against its PEERS. Do NOT restrict to the subject — instead, for EACH value of "
                "the subject's own dimension (the subject is one value of it, e.g. category = "
                "'womenswear'; its peers are the other categories), compute the leading reason's share "
                "of that value's returns: 100.0 * SUM(CASE WHEN <reason_col> = '<leading value>' THEN 1 "
                "ELSE 0 END) / NULLIF(COUNT(*), 0) AS leading_reason_share, plus COUNT(*) AS n. ORDER BY "
                "leading_reason_share DESC. Return exactly three columns: the subject-dimension value, "
                "leading_reason_share, n. This tests whether the leading reason is abnormally high for "
                "the subject or a brand-wide baseline.") + _ADA_SQL_GROUNDING,
            plan_user=(
                f"QUESTION: {question}\nMETRIC: {metric_label}\n"
                f"WHY scan found (the leading reason + its share of the SUBJECT's returns):\n  {why_summary}\n\n"
                f"SCHEMA:\n{schema}\n\n"
                "Benchmark the leading reason ACROSS the subject and its peers (the other values of the "
                "subject's own dimension): is its share higher for the subject than for its peers, or "
                "about the same? This tells us whether the cause is subject-specific or brand-wide."),
            interpret_system=(
                "Interpret a PEER BENCHMARK — the leading reason's share of returns for the subject vs "
                "its peer values. State plainly whether the subject's share is ELEVATED above its peers "
                "(the cause is genuinely worse for the subject → real, subject-specific) or is AT/BELOW "
                "the peer range (a brand-wide baseline → the framing 'X is high for the subject' is "
                "misleading — it's high everywhere). Lead with that verdict + the subject's share vs the "
                "peer range. These are shares of returns, NOT return rates."),
            interpret_user_fn=(lambda results_text:
                f"QUESTION: {question}\n\nLEADING-REASON SHARE BY PEER:\n{results_text}\n\n"
                "Is the leading reason abnormally high for the subject vs its peers, or a brand-wide "
                "baseline? Lead with the verdict."),
            plan_error_msg="Benchmark planning failed.", exec_error_msg="Benchmark query failed.",
            question=question, connection_id=state.get("connection_id", ""),
        )
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "benchmark lens best-effort; skipped", counter="ada.benchmark_lens")
        return None
    return _lens_phase_from_run(_run, "reason_benchmark", "Reason Benchmark — Is the Cause Abnormal?",
                                "📊", "benchmark", metric_label, "Reason benchmark computed.",
                                peer_median_ref=True)


def _run_reason_drill_lens(state: AgentState, conn: "DatabaseConnection", why_summary: str) -> Optional[dict]:
    """Second-level drill on the leading reason: the WHY lens found WHICH reason dominates (size/fit),
    but not WHICH products drive it. This restricts to the subject AND the leading reason, then composes
    by a finer product/brand dimension → "size/fit returns concentrate in brands X/Y" = the actionable
    fix target (or "evenly spread → not product-specific"). LLM-planned. Returns a phase dict or None.
    Fail-open."""
    intake = state.get("_ada_intake") or {}
    question = state["question"]
    metric_label = intake.get("metric_label", "the metric")
    schema = _with_ledger(state, intake.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT))
    try:
        _run = run_analysis_phase(
            conn, phase_id="reason_drill",
            title="Reason Drill — Which Products Concentrate It", emoji="🎯",
            cap=2, schema=schema,
            plan_system=(
                "Write ONE query that DRILLS INTO the leading return reason (from the WHY scan) to find "
                "WHICH products drive it. Restrict to the question's subject AND the leading reason "
                "(<reason_col> = '<leading value>'), then compose by a FINER product dimension (brand / "
                "product line / product name — join through order_items / products as needed): COUNT(*) "
                "per value AS event_count, plus its share of the leading-reason returns "
                "(100.0 * COUNT(*) / SUM(COUNT(*)) OVER () AS pct_of_total). ORDER BY event_count DESC. "
                "Return exactly three columns: the product dimension, event_count, pct_of_total. This "
                "localises WHICH products the leading reason concentrates in — the fix target.") + _ADA_SQL_GROUNDING,
            plan_user=(
                f"QUESTION: {question}\nMETRIC: {metric_label}\n"
                f"WHY scan found (the leading reason to drill into):\n  {why_summary}\n\n"
                f"SCHEMA:\n{schema}\n\n"
                "Within the subject, restrict to the leading reason and compose its returns by a finer "
                "brand/product dimension: which products concentrate this reason? That is where to act."),
            interpret_system=(
                "Interpret a DRILL into the leading reason by product/brand — a composition (shares that "
                "sum to ~100%) of the leading reason's returns. Name the top brand(s)/product(s) that "
                "concentrate it (the fix target) and their share; if the reason is spread evenly, say so "
                "(then it is not product-specific). These are shares of the leading-reason returns, NOT "
                "return rates."),
            interpret_user_fn=(lambda results_text:
                f"QUESTION: {question}\n\nLEADING-REASON RETURNS BY PRODUCT:\n{results_text}\n\n"
                "Which brands/products concentrate the leading reason? Lead with the fix target."),
            plan_error_msg="Drill planning failed.", exec_error_msg="Drill query failed.",
            question=question, connection_id=state.get("connection_id", ""),
        )
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "reason drill lens best-effort; skipped", counter="ada.reason_drill_lens")
        return None
    return _lens_phase_from_run(_run, "reason_drill", "Reason Drill — Which Products Concentrate It",
                                "🎯", "drill", metric_label, "Reason drill computed.")


def _lens_phase_from_run(_run, phase_id: str, title: str, emoji: str, fprefix: str,
                         metric_label: str, empty_summary: str,
                         peer_median_ref: bool = False,
                         opportunity: Optional[dict] = None) -> Optional[dict]:
    """Shared tail for the forward-chained WHY lenses (benchmark/drill): assemble findings from a
    completed `run_analysis_phase`, tag percent/share columns, and wrap as a phase. Mirrors the
    composition lens's tail. Returns the error phase on failure, None only if there's nothing.

    `opportunity` (a lens spec's block) opts the phase into the R15 gap × volume key number,
    computed deterministically from the lens's own rows. Only a lens whose `n` IS its rate's
    denominator may pass it — see loss_signals.lens_specs. Without it the phase is unchanged,
    which is why the leakage lens (n = COUNT(*), denominator = gross) stays silent."""
    if not _run.ok:
        return _run.error_phase
    results, interp = _run.results, _run.interpretation
    if interp and interp.findings:
        findings = _assemble_phase_findings(results, interp.findings, fprefix, metric_label=metric_label)
        summary = interp.phase_summary
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"{fprefix}_{i}", title=q.title, sql=r.sql, columns=r.columns, rows=r.rows[:50],
                row_count=r.row_count, error=r.error, interpretation="Computed.",
                key_numbers=[], chart_type=(q.chart_type or "bar_horizontal"), stat_note=None, is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = empty_summary
    _tag_percent_columns(findings, re.compile(r"share|pct|percent|_of_total", re.I))
    from aughor.kernel.flags import flag_enabled as _fe
    _grammar = _fe("chart.exhibit_grammar")
    # R15 on the lens path. The utilization lens plans exactly R15's grid (segment,
    # metric_total, n) and then ASKED THE MODEL to "size the opportunity as gap ×
    # volume" — the one number the whole lens exists for, left to prose. Compute it.
    _opp = opportunity if (opportunity and _fe("lens.decision_grade")) else None
    for _f in findings:
        _normalize_pct_key_numbers(_f)
        _f["chart_type"] = _chart_type_for_finding(_f, "ranking")
        if _opp:
            from aughor.agent.opportunity import annotate_opportunity
            # The lens's rate is a percent-scaled ratio by SQL construction
            # (`100.0 * SUM(x) / SUM(y)`), which the scale normalisation expects.
            annotate_opportunity(_f, metric_label=metric_label, is_ratio=True,
                                 is_percent=True,
                                 lower_is_better=bool(_opp.get("lower_is_better")),
                                 volume_label=_opp.get("volume_label") or "records",
                                 volume_is_denominator=bool(
                                     _opp.get("volume_is_denominator")),
                                 volume_is_money=bool(_opp.get("volume_is_money")))
        # Chart-grammar exhibit: severity ramp on the share ranking; the benchmark
        # lens also draws the peer median its whole point is to compare against.
        if _grammar:
            from aughor.agent.exhibit import exhibit_for_lens
            exhibit_for_lens(_f, peer_median=peer_median_ref)
    _ph = _phase_result(
        phase_id, title, emoji,
        "complete" if any(not f["error"] for f in findings) else "partial", summary, findings,
    )
    # This lens measures its OWN thing, not the run's primary metric. Record the label so
    # the terminal alias-humanizer can't stamp "refund leakage rate" on a load-factor grid.
    _ph["metric_label"] = metric_label
    return _ph


def _probe_lifecycle_values(conn, cols: list) -> dict:
    """Distinct values of each lifecycle/status column — read-only, bounded, fail-open.

    Ground-first, and the reason this exists: the schema block gives the planner
    `segment_status VARCHAR` and no values, so a prose rule ("exclude cancelled") makes
    it INVENT the literal it filters on — and a literal that matches nothing silently
    yields a 0% rate. Probe the column, name the values, remove the guess."""
    out: dict = {}
    for qualified in (cols or [])[:4]:
        table, _, col = qualified.rpartition(".")
        if not table or not col:
            continue
        try:
            r = conn.execute_bounded(
                "loss_lifecycle_probe",
                f'SELECT DISTINCT "{col}" AS v FROM {table} WHERE "{col}" IS NOT NULL LIMIT 25',
                25)
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, f"lifecycle probe '{qualified}' best-effort; skipped",
                     counter="ada.loss_lifecycle_probe")
            continue
        vals = [str(row[0]) for row in (r.rows or []) if row and row[0] is not None]
        # One value pins nothing; 25 means it isn't a lifecycle column at all.
        if 1 < len(vals) < 25:
            out[qualified] = sorted(vals)
    return out


def _run_loss_lens_phases(state: AgentState, conn: "DatabaseConnection") -> list[dict]:
    """Forward-chained LOSS lenses (flag `intake.loss_signals`): one investigation
    carries ONE primary metric, so a 'losing money' run that (correctly) picked
    utilization leaves the leakage story untold — and vice versa. Every signal class
    the intake detected but the primary metric doesn't cover gets its own phase via
    the shared plan→execute→interpret harness, which buys percent tagging, ranking
    chart types and the exhibit grammar through `_lens_phase_from_run`. Deterministic
    gating; fail-open — a lens that can't run contributes nothing."""
    try:
        from aughor.kernel.flags import flag_enabled as _fe
        if not _fe("intake.loss_signals"):
            return []
        intake_data = state.get("_ada_intake") or {}
        sig = intake_data.get("loss_signals") or {}
        if not sig:
            _lens_logger.info("[ada] loss-lens gates: intake carried no loss_signals — nothing owed")
            return []
        from aughor.agent.loss_signals import lens_specs, lifecycle_directive
        blob = f"{intake_data.get('metric_label', '')} {intake_data.get('metric_sql', '')}"
        specs = lens_specs(sig, blob)
        # The gates are where this dies silently — a run with no loss phases looks
        # identical to a run that was never owed one. Say which it was.
        _lens_logger.info("[ada] loss-lens gates: sig={%s} owed=%s blob=%r",
                    ", ".join(f"{k}:{len(v)}" for k, v in sig.items()),
                    [s["kind"] for s in specs] or "nothing", blob[:80])
        if not specs:
            return []
        # Pin which units count BEFORE planning: without the probed values "paid units"
        # is the planner's call, and the same claim moved 77.7/79.4 → 78.0/80.8 across
        # runs depending on whether it silently counted refunded and no-show tickets.
        _probed = _probe_lifecycle_values(conn, sig.get("lifecycle") or [])
        _lifecycle = lifecycle_directive(_probed)
        # The prompt is the belt; the GUARD is the enforcement. The live planner ignored
        # the directive in BOTH prompt positions while obeying the rule beside it, so the
        # filter is injected into the planned SQL deterministically (sqlglot, per scope,
        # skipped when the planner already filtered). Counters make every repair auditable.
        from aughor.agent.loss_signals import lifecycle_rules
        from aughor.sql.lifecycle_guard import lifecycle_transform
        from aughor.stats import stats as _stats
        _rules = lifecycle_rules(_probed)
        _lc_transform = lifecycle_transform(
            _rules, dialect=getattr(conn, "dialect", "duckdb"),
            on_apply=lambda applied: _stats.inc("ada.lifecycle_guard_applied", len(applied)))
        # Auditable by design: a guard that fails silently reads as "no losses to pin".
        # This line is how the live gap was found — every offline repro passed while the
        # live path produced unpinned SQL, and only the run's own log could arbitrate.
        _lens_logger.info("[ada] loss-lens lifecycle: cols=%d probed=%d rules=%d guard=%s",
                    len(sig.get("lifecycle") or []), len(_probed), len(_rules),
                    bool(_lc_transform))
        question = state["question"]
        schema = _with_ledger(state, intake_data.get("filtered_schema")
                              or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT))
        phases: list[dict] = []
        for spec in specs:
            try:
                _run = run_analysis_phase(
                    conn, phase_id=spec["phase_id"], title=spec["title"], emoji=spec["emoji"],
                    cap=2, schema=schema,
                    # The lifecycle rule rides in plan_SYSTEM, next to the grouping rule.
                    # Live evidence (inv 0db3a6db): in ONE run the grouping constraint —
                    # in plan_system — was obeyed ("utilization by haul type"), while this
                    # rule, then in plan_user, was ignored and the SQL came back with no
                    # status filter at all. plan_user competes with _ADA_SQL_GROUNDING and
                    # the grounding block's trusted-query shapes; plan_system does not.
                    # Only the lens whose metric is DEFINED by consumption gets it — see
                    # the leakage spec for what handing it to the wrong lens costs.
                    plan_system=(spec["plan_system"]
                                 + (f"\n{_lifecycle}" if spec.get("lifecycle_filter") else "")
                                 + _ADA_SQL_GROUNDING),
                    plan_user=(f"QUESTION: {question}\n\nSCHEMA:\n{schema}\n\n"
                               f"{spec['plan_ask']}"),
                    interpret_system=spec["interpret_system"],
                    interpret_user_fn=(lambda results_text, _t=spec["title"]:
                                       f"QUESTION: {question}\n\n{_t.upper()}:\n{results_text}\n\n"
                                       "Lead with the quantified verdict. Never claim profitability "
                                       "or 'no losses' — cost data is absent."),
                    plan_error_msg=f"{spec['kind']} planning failed.",
                    exec_error_msg=f"{spec['kind']} query failed.",
                    question=question, connection_id=state.get("connection_id", ""),
                    grounding_block=intake_data.get("data_understanding_block"),
                    sql_transform=(_lc_transform if spec.get("lifecycle_filter") else None),
                )
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, f"loss lens '{spec['kind']}' best-effort; skipped",
                         counter=spec["counter"])
                continue
            ph = _lens_phase_from_run(_run, spec["phase_id"], spec["title"], spec["emoji"],
                                      spec["fprefix"], spec["metric_label"],
                                      f"{spec['title']} computed.",
                                      opportunity=spec.get("opportunity"))
            if ph:
                phases.append(ph)
        return phases
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "loss lens phases best-effort; skipped", counter="ada.loss_lens")
        return []


def ada_cross_section_multilens(state: AgentState, conn: "DatabaseConnection") -> dict:
    """Flag-gated parallel multi-lens cross-section. Runs independent lenses CONCURRENTLY — one
    focused segment/mechanism scan per themed dimension group PLUS a temporal WHEN lens when a date
    axis resolves — then, if the WHEN lens flagged an anomalous period, forward-chains a
    period-scoped drill, and (flags `ada.why_where_interaction` / `ada.why_deepen`) a WHY×WHERE
    interaction cross + a reason benchmark + a second-level reason drill.
    Degrades to the single scan when there's nothing to fan out. Only writes
    investigation_phases (+ the primary's _cross_section_summary), assembled single-threaded here."""
    from concurrent.futures import as_completed
    from aughor.kernel.concurrency import ContextThreadPoolExecutor
    from aughor.kernel.metering import BudgetExceeded

    intake_data = state.get("_ada_intake") or {}
    dim_specs = _partition_dimensions(intake_data.get("dimensions", []))
    axis = _resolve_temporal_axis(state, conn)
    # Follow-up A — one canonical grain for the whole fan-out, so the WHERE rate and the WHEN trend
    # divide by the SAME denominator (no per-order 40% vs per-line-item 76% contradiction).
    grain = _canonical_grain(intake_data)

    # #4 — deterministic population-attribute discovery (price band / season the intake missed), fed
    # into the RATE lens so it looks where the answer actually is. Computed once, single-threaded.
    _pop_aug = _discover_population_dims(state, conn) or {}
    _aug_dims = _pop_aug.get("extra_dims") or None
    _aug_schema = _render_join_schema(_pop_aug, conn) if _pop_aug else None
    _aug_dir = _price_band_directive(_pop_aug) if _pop_aug else None

    # Parallel spec list: population dims → a RATE scan (WHERE); event-only dims → a COMPOSITION scan
    # (WHY, share-of-returns, avoiding the tautological 100%); plus an optional temporal WHEN lens.
    specs = [(("xsec:" if kind == "rate" else "comp:") + name, kind, ldims, pmeta)
             for (name, ldims, pmeta, kind) in dim_specs]
    if axis:
        specs.append(("when", "when", axis, None))
    # Degrade to the plain single scan only when there's a single RATE lens and no temporal axis
    # (still augmented with the discovered population attributes).
    if len(specs) == 1 and specs[0][1] == "rate":
        return ada_cross_section(state, conn, extra_dims=_aug_dims,
                                 extra_schema=_aug_schema, extra_directive=_aug_dir, grain=grain)

    base_phases = state.get("investigation_phases", [])
    base_n = len(base_phases)
    # Population (rate) lens groups only — used for the period-scoped forward-chain drill.
    rate_lenses = [(n, d, m) for (n, d, m, k) in dim_specs if k == "rate"]

    def _run_spec(spec):
        # Returns (name, new_phases, summary, anomalous, suppressed_ratio). The last is the
        # terminal-suppression signal a rate lens raises when the shared metric is proven
        # corrupt — it MUST ride back up: without it the multilens merge dropped it and the
        # temporal 58.8% tile + synthesis citation survived a report that suppressed the
        # same metric elsewhere (inv 1aa22321).
        name, kind, payload, pmeta = spec
        try:
            reader = conn.make_reader()
            if kind == "when":
                phase, anomalous = _run_temporal_lens(state, reader, payload, grain=grain)
                return name, ([phase] if phase else []), None, anomalous, None
            if kind == "composition":
                phase = _run_composition_lens(state, reader, payload)
                return name, ([phase] if phase else []), None, None, None
            # kind == 'rate' — the WHERE scan, augmented with the discovered population attributes.
            out = ada_cross_section(state, reader, dims_override=payload, phase_meta=pmeta,
                                    extra_dims=_aug_dims, extra_schema=_aug_schema,
                                    extra_directive=_aug_dir, grain=grain)
            ph = out.get("investigation_phases", [])
            new = ph[base_n:] if len(ph) > base_n else (ph[-1:] if ph else [])
            return name, new, out.get("_cross_section_summary"), None, out.get("_suppressed_ratio")
        except BudgetExceeded:
            raise
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"ada multilens '{name}' best-effort; lens skipped",
                     counter="ada.multilens_lens")
            return name, [], None, None, None

    results: list = []
    width = min(len(specs), max(1, _ADA_LENS_WIDTH))
    try:
        with ContextThreadPoolExecutor(max_workers=width) as pool:
            futs = [pool.submit(_run_spec, s) for s in specs]
            for fut in as_completed(futs):
                results.append(fut.result())   # BudgetExceeded re-raises here → abort the run
    except BudgetExceeded:
        raise
    except Exception as exc:
        # Executor-level failure must never break the investigation — fall back to serial.
        _lens_logger.warning("[ada] multilens pool failed (%s) — serial fallback", exc, exc_info=True)
        results = [_run_spec(s) for s in specs]

    # Deterministic: merge in spec order (segment primary first, WHEN last), never completion order.
    order = {s[0]: i for i, s in enumerate(specs)}
    results.sort(key=lambda r: order.get(r[0], 1 << 30))
    merged = list(base_phases)
    primary_summary = None
    anomalous = None
    suppressed_ratio = None
    for name, new_phases, summ, anom, supp in results:
        merged.extend(new_phases)
        if summ and primary_summary is None and name.startswith("xsec:"):
            primary_summary = summ
        if anom:
            anomalous = anom
        if supp and suppressed_ratio is None:
            suppressed_ratio = supp    # the metric is the same across lenses — one signal suffices

    # Forward-chain: the WHEN lens flagged a period → drill the segment/mechanism scan INTO it
    # (sequential — the drill depends on the detection). Honest no-op when the trend was flat.
    if anomalous and axis and rate_lenses:
        try:
            merged.extend(_run_period_drill(state, conn, axis, anomalous, rate_lenses, grain=grain))
        except BudgetExceeded:
            raise
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "period drill best-effort; skipped", counter="ada.period_drill")

    # Forward-chained WHY lenses (all depend on the WHY composition finding). Computed once here.
    _why_phase = next((p for p in merged[base_n:]
                       if p.get("phase_id") == "cross_section_mechanism" and p.get("findings")), None)
    _why_summary = (_why_phase.get("summary") or "") if _why_phase else ""
    _extras: list = []

    def _run_forward(label, fn, counter, c):
        """Run one forward-chained lens fn(conn)→phase|None on connection ``c``. Fail-open — a
        BudgetExceeded aborts the run; any other error skips just this lens."""
        try:
            return fn(c)
        except BudgetExceeded:
            raise
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, f"{label} lens best-effort; skipped", counter=counter)
            return None

    # The forward-chained WHY lenses, gathered as (label, fn(conn), counter) specs in FIXED order.
    # Each depends ONLY on the already-computed WHERE/WHY summaries (primary_summary / _why_summary),
    # never on each other, so they can run as one concurrent wave.
    #  • interaction (flag `ada.why_where_interaction`): cross the leading reason (WHY) with the
    #    highest-impact segment (WHERE) — needs both a WHERE (rate) summary AND a WHY finding.
    #  • benchmark + drill (flag `ada.why_deepen`): benchmark the leading reason vs peers (is it
    #    abnormal?) and drill it by product (which products drive it?) — both need only the WHY finding.
    forward_specs: list = []
    if _why_phase and primary_summary and _why_where_interaction_enabled():
        forward_specs.append(("interaction",
                              lambda c: _run_interaction_lens(state, c, primary_summary, _why_summary),
                              "ada.interaction_lens"))
    if _why_phase and _why_deepen_enabled():
        forward_specs.append(("benchmark",
                              lambda c: _run_reason_benchmark_lens(state, c, _why_summary),
                              "ada.benchmark_lens"))
        forward_specs.append(("drill",
                              lambda c: _run_reason_drill_lens(state, c, _why_summary),
                              "ada.reason_drill_lens"))

    if len(forward_specs) >= 2 and _parallel_why_lenses_enabled():
        # Parallel wave — each lens on its own reader clone; merge in FIXED spec order (never
        # completion order), so the report is byte-identical to the serial chain, just faster.
        _fwd: dict = {}
        try:
            with ContextThreadPoolExecutor(max_workers=len(forward_specs)) as pool:
                _futs = {pool.submit(_run_forward, label, fn, counter, conn.make_reader()): label
                         for (label, fn, counter) in forward_specs}
                for fut in as_completed(_futs):
                    _fwd[_futs[fut]] = fut.result()   # BudgetExceeded re-raises here → abort the run
        except BudgetExceeded:
            raise
        except Exception as _exc:
            # Executor-level failure must never break the investigation — serial fallback.
            _lens_logger.warning("[ada] why-lens wave failed (%s) — serial fallback", _exc, exc_info=True)
            for (label, fn, counter) in forward_specs:
                if label not in _fwd:
                    _fwd[label] = _run_forward(label, fn, counter, conn)
        for label, _fn, _counter in forward_specs:
            _ph = _fwd.get(label)
            if _ph:
                merged.append(_ph)
                _extras.append(label)
    else:
        for (label, fn, counter) in forward_specs:
            _ph = _run_forward(label, fn, counter, conn)
            if _ph:
                merged.append(_ph)
                _extras.append(label)

    # Loss-playbook lenses (flag intake.loss_signals): the leakage/utilization phases the
    # primary metric left uncovered — independent of the WHY chain, appended last so the
    # narrative reads scan → causes → the other loss stories.
    for _lp in _run_loss_lens_phases(state, conn):
        if any(p.get("phase_id") == _lp.get("phase_id") for p in merged):
            continue    # defensive: never show the same loss story twice
        merged.append(_lp)
        _extras.append(_lp.get("phase_id", "loss"))

    _lens_logger.info("[ada] multilens ran %d lens(es)%s%s → %d phase(s)",
                      len(specs), (" + period drill" if anomalous else ""),
                      (" + " + "+".join(_extras) if _extras else ""), len(merged) - base_n)
    out = {"investigation_phases": merged}
    if primary_summary is not None:
        out["_cross_section_summary"] = primary_summary
    if suppressed_ratio is not None:
        out["_suppressed_ratio"] = suppressed_ratio    # terminal suppression reaches synthesis
    return out


# ── T4-3 / P5: tiered adversarial verification ─────────────────────────────────────────
def _adversarial_should_run(synth, *, full: bool, high_stakes: bool) -> bool:
    """Whether the ReFoRCE-style refuter should spend its ONE skeptic LLM call on this verdict. The
    caller has already confirmed the verdict is DECISION-CHANGING (a premise rejection / abstention).
      • ``full`` (``ada.adversarial_verify``) — challenge EVERY decision-changing verdict.
      • ``high_stakes`` (``ada.adversarial_high_stakes``) — the deterministic materiality gate: fire
        ONLY when the verdict is asserted with **HIGH** confidence. That's the costly-if-wrong minority
        AND the only case where the HIGH→MEDIUM cap can bite — so the refuter earns a default-path place
        without paying an LLM call on the many MEDIUM/LOW verdicts. Confidence-triggered activation."""
    if full:
        return True
    if high_stakes:
        return (getattr(synth, "confidence", "") or "").upper() == "HIGH"
    return False


def _apply_adversarial_refutation(synth, verdict) -> None:
    """Apply a SURVIVING refutation to the synthesis (deterministic; the LLM call is upstream): record
    the objection in ``data_gaps`` and cap a **HIGH** confidence to **MEDIUM** — a decision-changing
    verdict that didn't survive a skeptic pass can't ship as HIGH. No-op unless the verdict refutes;
    idempotent on the note; leaves MEDIUM/LOW confidence untouched (the cap only lowers HIGH)."""
    if verdict is None or not getattr(verdict, "refuted", False):
        return
    obj = (getattr(verdict, "reason", "") or "").strip()
    alt = (getattr(verdict, "alternative", None) or "").strip()
    note = ("An adversarial verification challenged this conclusion: " + obj
            + (f" Alternative reading: {alt}." if alt else ""))
    gaps = list(getattr(synth, "data_gaps", None) or [])
    if not any("adversarial verification" in g.lower() for g in gaps):
        gaps.insert(0, note)
    synth.data_gaps = gaps
    if (getattr(synth, "confidence", "") or "").upper() == "HIGH":
        synth.confidence = "MEDIUM"
        synth.confidence_justification = (
            "Capped below HIGH — a decision-changing verdict did not survive an adversarial "
            "refutation: " + obj + " " + (getattr(synth, "confidence_justification", "") or "")).strip()


@_telemetry.node_span("ada_synthesize")
def ada_synthesize(state: AgentState) -> dict:
    """
    Phase 8 — Synthesis: Attribution Waterfall + Recommendations.
    Assembles all phase findings into an AnswerReport.
    """
    from aughor.agent.prompts_investigate import ADA_SYNTHESIZE_PROMPT, ADASynthesisModel
    from aughor.agent.state import AnswerReport, WaterfallEntry, AnswerRecommendation

    question = state["question"]
    phases = state.get("investigation_phases", [])
    events = state.get("events_context") or ""
    events_section = f"BUSINESS CALENDAR:\n{events}\n" if events else ""
    intake_data = state.get("_ada_intake") or {}

    # Terminal suppression (P0): a ratio proven corrupt in the cross-section guard is corrupt
    # wherever the shared metric is rendered. Scrub it from every OTHER phase (the temporal tile
    # + line chart the guard never reached), collapse the one caveat that was repeating ~8×, and
    # hand synthesis the TRUE level so it states 2.8% instead of headlining the 58.8% artifact.
    _suppressed = state.get("_suppressed_ratio")
    suppression_section = ""
    if _suppressed:
        _scrub_suppressed_metric_everywhere(phases, _suppressed)
        _true = _suppressed.get("true_global_str")
        _mlabel = _suppressed.get("metric_label") or "the metric"
        suppression_section = (
            f"\n\nSUPPRESSED METRIC — HARD RULE: '{_mlabel}' could not be computed reliably; its "
            "per-segment and per-period values in the evidence (any large percentage such as 58.8%, "
            "or a 49–69% range) are COMPUTATION ARTIFACTS of a conditioned denominator / join "
            "fan-out, NOT real levels. You MUST NOT cite, rank, or headline those values as facts. "
            + (f"The metric's TRUE whole-population level is {_true} — cite THAT if you state a level, "
               "and say plainly it needs a grain-correct recompute before segments can be compared. "
               if _true else
               "State plainly that the metric needs a grain-correct recompute before it can be "
               "trusted, and do not invent a level. ")
            + "Do not let a suppressed number appear anywhere in the headline or executive summary.")
    _dedupe_repeated_caveats(phases)

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
    # Budget-aware: phases are kept verbatim (exact numbers, for grounding) up to the budget; any
    # overflow is folded into a number-preserving digest (tree-reduce) instead of being truncated away.
    evidence_log = _phases_evidence_budgeted(phases)

    # ── Cross-phase contradiction detection (typed) ───────────────────────────
    # Before synthesis, deterministically check phase summaries for contradictions.
    # Example: baseline says "significant drop (z=-2.4)" while dimensional says
    # "no segment deviates from baseline" — the synthesizer must not silently paper
    # over this. The Orchestrator returns a typed ContradictionReport: .to_prompt_section()
    # is the byte-identical hard instruction the synthesizer always received, and .to_dict()
    # rides along on the report as a first-class trust artifact (surfaced to the UI).
    from aughor.agent.orchestrator import detect_contradictions, reconcile
    contradiction_report = detect_contradictions(phases)
    contradiction_section = contradiction_report.to_prompt_section()
    # Reconcile the Analyst's declared plan against the phases that actually ran, and
    # journal the seam so planned-vs-actual autonomy is legible in the Fleet view.
    orchestration_plan = state.get("_orchestration_plan")
    plan_reconciliation = reconcile((orchestration_plan or {}).get("planned_ids", []), phase_ids)
    try:
        from aughor.agent.handoff import emit_handoff
        emit_handoff("analyst", "orchestrator", "synthesis",
                     {"reconciliation": plan_reconciliation,
                      "contradictions": contradiction_report.severity},
                     conn_id=state.get("connection_id") or None)
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "plan reconciliation journal", counter="orchestrator")

    # Cross-sectional runs have no temporal "change" — tell synthesis to frame the
    # report as a where-is-value-weakest diagnostic, not a period-over-period decline.
    cross_section_note = ""
    if "cross_section" in phase_ids or intake_data.get("cross_sectional"):
        cross_section_note = (
            "\n\nNOTE: This is a CROSS-SECTIONAL diagnostic (where/which is weakest), not a temporal "
            "change. Do NOT frame it as a period-over-period decline. Lead with WHERE value is lowest "
            "or most concentrated across the dimensions scanned; total_change_label should be the "
            "metric total or 'N/A'; the attribution_waterfall should attribute the weakness across "
            "those dimensions (signed negative as loss contributors); recommendations target the "
            "weakest areas. Be honest about which areas are healthy and NOT a problem. "
            "SEVERITY GROUNDING: do NOT label the lowest-ranked value 'weak', 'critically low', or "
            "'underperforming' unless it is below a benchmark/target or far below the average — if "
            "the spread is tight and all values are healthy, say the dimension is healthy and DROP "
            "the weakness framing (an empty waterfall is correct when nothing is actually weak)."
        )
        if intake_data.get("metric_is_ratio") or _metric_is_ratio(
            intake_data.get("metric_sql", ""), intake_data.get("metric_label", "")
        ):
            cross_section_note += (
                "\n\nRATIO METRIC: the metric is a RATIO / percentage / per-unit rate (e.g. "
                f"'{intake_data.get('metric_label', 'the metric')}'), NOT a dollar total. Report every "
                "value in the metric's OWN units (%, rate) — NEVER restate it as a dollar amount or a "
                "per-order average, and NEVER manufacture a percentage from a dollar column. DIRECTION: "
                "for a cost/defect/freight-style ratio a LOW value is FAVOURABLE; do not call the lowest "
                "ratio a weakness unless the ratio's meaning makes low genuinely bad. total_change_label "
                "should be the overall ratio or 'N/A', not a summed percentage."
            )
        if any("fan-out" in (f.get("trust_caveat") or "").lower()
               for p in phases for f in (p.get("findings") or [])):
            cross_section_note += (
                "\n\nFAN-OUT CAVEAT: a metric below was aggregated across a one-to-many join that "
                "INFLATES the magnitude (the rows being summed were multiplied), so the figures are "
                "unreliable and the ranking may be volume-weighted. Do NOT present these numbers as "
                "exact, do NOT rank confidently on them, and set confidence to at most MEDIUM (LOW if "
                "the inflated metric is the only evidence). Say plainly the figure needs a grain-correct "
                "recompute before it can be trusted."
            )
        if _xsec_max_seeking(question):
            cross_section_note += (
                "\n\nDIRECTION: this question asks for the HIGHEST / MOST. The cross-sectional ranking's "
                "answer is the value with the LARGEST metric — lead with the MAXIMUM, not the minimum or "
                "a mid-rank value. Order the attribution_waterfall from the largest contributor down."
            )

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
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "metric-targets section is advisory; synthesis proceeds without "
                       "benchmark targets", counter="ada.synth_context")

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
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "playbook section is advisory; synthesis proceeds without playbook "
                       "guidance", counter="ada.synth_context")

    # Build external context section from uploaded documents
    external_context_section = ""
    try:
        from aughor.knowledge.indexer import build_external_context_section
        external_context_section = build_external_context_section(question, top_k=4)
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "external-document context is advisory; synthesis proceeds without "
                       "uploaded-document grounding", counter="ada.synth_context")

    # Build org-wide intelligence section from promoted canvas insights
    org_intelligence_section = ""
    try:
        from aughor.knowledge.org_intelligence import build_org_intelligence_section
        org_intelligence_section = build_org_intelligence_section(question, top_k=5)
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "org-intelligence section is advisory; synthesis proceeds without "
                       "promoted canvas insights", counter="ada.synth_context")

    # agents.user_defined — the active persona's standing instructions lead the
    # synthesis prompt (mirrors the quick path's rules_block seam; the document
    # sections above are already agent-scoped via build_external_context_section).
    # Inert ("") when no agent is active.
    _agent_brief = ""
    try:
        from aughor.user_agents.context import agent_brief_block
        _agent_brief = agent_brief_block()
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "agent brief is advisory; synthesis proceeds without it",
                 counter="ada.synth_context")

    synth_prompt = _agent_brief + ADA_SYNTHESIZE_PROMPT.format(
        question=question,
        phases_summary=phases_summary,
        evidence_log=evidence_log,
        events_section=events_section,
        metric_targets_section=metric_targets_section,
        playbook_section=playbook_section,
        org_intelligence_section=org_intelligence_section,
        external_context_section=external_context_section,
    ) + contradiction_section + early_stop_note + cross_section_note + suppression_section
    # Issue-1 fix (frugal) — BOUND the synthesis LLM call. The cloud narrator can stall for many
    # minutes, and a hung synthesis used to leave the user with no report at all even though every
    # phase had finished. Run it under a hard timeout; on timeout we fall through to the SAME
    # deterministic fallback report (assembled from the phase findings below) that an LLM error
    # already triggers — no extra model call, no new code path. Tunable via AUGHOR_SYNTH_TIMEOUT_S.
    import os as _os
    import concurrent.futures as _cf
    _synth_timeout = float(_os.getenv("AUGHOR_SYNTH_TIMEOUT_S", "120"))
    _synth_ex = _cf.ThreadPoolExecutor(max_workers=1)
    # R16 P2 — the narrator's system prompt lives with the other prompts; under
    # `report.argument_style` it carries the Genie-study writing contract.
    from aughor.agent.prompts_investigate import synthesis_system_prompt
    _synth_system = synthesis_system_prompt()
    # R6 — stream the report prose (executive_summary) to the client as the narrator
    # writes it, so a multi-minute deep run isn't silent between phase_complete and the
    # final report. Capture the sink emitter HERE (node body, sink visible) so the closure
    # still works inside the plain synthesis executor thread. None when ada.progress_events
    # is off → blocking .complete(), byte-identical to before. complete_streaming self-heals
    # to .complete() on any streaming failure; the terminal answer_report stays authoritative.
    from aughor.agent.progress import report_delta_emitter
    _emit_report = report_delta_emitter()

    def _run_synth():
        prov = _provider("narrator")
        if _emit_report is not None:
            return prov.complete_streaming(
                system=_synth_system, user=synth_prompt, response_model=ADASynthesisModel,
                text_field="executive_summary", on_text=_emit_report)
        return prov.complete(system=_synth_system, user=synth_prompt,
                             response_model=ADASynthesisModel)

    try:
        _synth_fut = _synth_ex.submit(_run_synth)
        synth: ADASynthesisModel = _synth_fut.result(timeout=_synth_timeout)
    except Exception as e:
        synth = None
        if isinstance(e, _cf.TimeoutError):
            from aughor.stats import stats as _s
            _s.inc("ada.synthesis_timeout")
    finally:
        # Don't block the investigation on a hung LLM call — abandon the worker, keep the fallback.
        _synth_ex.shutdown(wait=False)

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
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "causal-proposal save is best-effort; the synthesis output is "
                           "already complete", counter="ada.synth_causal_save")

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
            # RC5 — with NO usable data, the confidence floor alone left a LOW-confidence
            # report still carrying a confident, fabricated waterfall ("apparel −7.0pp =
            # −100%") and recommendations built from queries that all failed. Suppress them
            # deterministically and replace the confident prose with an honest verdict, so a
            # failed investigation reads as "could not analyze", never as invented causes.
            synth.attribution_waterfall = []
            synth.recommendations = []
            _ml = intake_data.get("metric_label") or "the requested metric"
            synth.headline = f"Data unavailable — {_ml} could not be analyzed"
            synth.executive_summary = (
                "Every diagnostic query failed or returned zero rows, so no cause can be "
                "attributed and no recommendation can be made. " + (synth.executive_summary or "")
            ).strip()[:600]

    # Trust-advisory floor (report-quality wiring gap #2) — cap HIGH → MEDIUM when an advisory fired.
    _cap_confidence_on_trust_advisory(synth, phases)
    # Fix 4: a computation-ERROR caveat is structural, not advisory — lead the summary with the honest
    # reframe and floor confidence to LOW so a flagged-artifact number can't be headlined as fact.
    _reframe_on_trust_caveat(synth, phases)

    # T4-4: self-coherence — the cross-phase contradiction detector sees only phase summaries, so a
    # report whose VERDICT rejects the premise ("X is not the problem" / "within normal variance")
    # while still shipping actionable recommendations reads as coherent (severity "none"). Add that
    # headline↔recommendations check to the contradiction report so the incoherence is surfaced.
    if synth:
        try:
            from aughor.agent.orchestrator import detect_verdict_recommendation_incoherence
            _incoh = detect_verdict_recommendation_incoherence(
                synth.headline, synth.executive_summary, getattr(synth, "recommendations", None))
            if _incoh is not None:
                contradiction_report.items.append(_incoh)
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "verdict-recommendation coherence check is best-effort; report proceeds",
                     counter="ada.coherence_check")

    # T4-3 / P5: confidence-tiered adversarial verification (ReFoRCE-style). Spend ONE skeptic LLM call
    # to try to REFUTE a DECISION-CHANGING verdict (a premise rejection or an abstention) before
    # shipping — the few high-stakes conclusions, never per finding. A surviving refutation records the
    # objection and caps a HIGH confidence to MEDIUM. Two opt-in tiers, both default-off (the
    # deterministic default path is byte-identical): `ada.adversarial_verify` challenges EVERY
    # decision-changing verdict; `ada.adversarial_high_stakes` is the cheaper materiality-gated tier —
    # only a HIGH-confidence decision-changing verdict (where being wrong is costly and the cap bites).
    from aughor.kernel.flags import flag_enabled as _flag_enabled
    _adv_full = _flag_enabled("ada.adversarial_verify")
    _adv_high_stakes = _flag_enabled("ada.adversarial_high_stakes")
    if synth and (_adv_full or _adv_high_stakes):
        try:
            from aughor.agent.orchestrator import is_decision_changing_verdict
            if is_decision_changing_verdict(synth.headline, synth.executive_summary) \
                    and _adversarial_should_run(synth, full=_adv_full, high_stakes=_adv_high_stakes):
                from aughor.agent.explore import run_refutation
                _verdict = run_refutation(question, synth.headline or "", _phases_summary(phases))
                _apply_adversarial_refutation(synth, _verdict)
                if _adv_high_stakes:                          # Activation Receipt (Wave 1·E3)
                    from aughor.kernel import metering
                    metering.record_activation("ada.adversarial_high_stakes")
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "adversarial verification is best-effort; report proceeds",
                     counter="ada.adversarial_verify")

    # F3/F2 — a CROSS-SECTIONAL scan ranks the metric ACROSS dimensions at a point in time; it
    # measures no temporal change, so:
    #   F3: never emit a "share of total CHANGE" attribution waterfall — there is nothing to
    #       decompose, and "gift_sets = -100% of total change" is fabricated structure.
    #   F2: if the QUESTION asked what changed over time but ran cross-sectional (no usable time
    #       axis — F1 routes the rest to the temporal path), lead with that fact instead of
    #       silently answering "where is the metric weakest". Non-droppable.
    if synth and intake_data.get("cross_sectional"):
        synth.attribution_waterfall = []
        if _is_temporal_change_question(question):
            _reframe = (
                "This question asks what changed over time, but no period-over-period comparison "
                "was possible, so the analysis cannot identify a temporal driver — it shows where "
                f"{intake_data.get('metric_label') or 'the metric'} is structurally weakest instead. "
            )
            _es = synth.executive_summary or ""
            if "changed over time" not in _es.lower():
                synth.executive_summary = (_reframe + _es).strip()[:900]
            _gap = ("No period-over-period analysis was performed, so the temporal driver of any "
                    "change over time remains unidentified.")
            _gaps = list(synth.data_gaps or [])
            if not any("period-over-period" in g.lower() for g in _gaps):
                _gaps.insert(0, _gap)
            synth.data_gaps = _gaps

    # Enforcing half of report-quality fix #1: if the coverage clamp flagged a duration mismatch,
    # deterministically reframe to run-rate — don't rely on the narrator heeding the advisory note.
    _reframe_on_pop_duration_mismatch(synth, intake_data, question)

    # T3-2: render-boundary number hygiene — the narrator occasionally copies a raw multi-digit float
    # into prose ("0.20829576194770064"); collapse any over-long decimal run in the prose fields so a
    # report never ships a 17-significant-digit number. Deterministic, no unit inference.
    if synth:
        from aughor.tools.executor import round_long_decimals, unify_percent_fractions
        # P3: when the metric is a PERCENTAGE, also unify a value written both as a fraction and a
        # percent in the same prose ("0.208" next to "20.8%") — self-grounded, so it can't rescale an
        # unrelated sub-1 number. Composed after the long-decimal collapse. No-op for a non-percent
        # metric (byte-identical), so a plain-total / average report is untouched.
        _is_pct_metric = _metric_is_percent(
            intake_data.get("metric_sql", "") or "", intake_data.get("metric_label", "") or "")
        _hygiene = (lambda s: unify_percent_fractions(round_long_decimals(s))) if _is_pct_metric else round_long_decimals
        synth.headline = _hygiene(getattr(synth, "headline", "") or "")
        synth.executive_summary = _hygiene(getattr(synth, "executive_summary", "") or "")
        synth.confidence_justification = _hygiene(getattr(synth, "confidence_justification", "") or "")
        synth.data_gaps = [_hygiene(g) for g in (getattr(synth, "data_gaps", None) or [])]
        for _rec in (getattr(synth, "recommendations", None) or []):
            for _fld in ("action", "expected_impact"):
                if hasattr(_rec, _fld):
                    setattr(_rec, _fld, _hygiene(getattr(_rec, _fld) or ""))

    def _coerce_amount_sign(label: str, pct: float) -> str:
        """Keep a waterfall amount_label's leading sign in agreement with its
        pct_of_total, so the two never render with opposite directions."""
        s = (label or "").strip()
        if not s:
            return s
        core = re.sub(r"^[+\-]\s*", "", s)
        return ("-" + core) if pct < 0 else core

    # Clean-output: the interpret prompts ask lens narrators to "lead with the verdict",
    # and the model obliges LITERALLY — "VERDICT: UNIFORM. The leading reason…" is
    # analysis-machinery speak in the reader's body text (flags-on soak). Strip the label
    # and un-shout the word it modified; the sentence that follows already carries it.
    for _p in phases:
        _ps = _p.get("summary")
        if _ps:
            _p["summary"] = _strip_verdict_prefix(_ps)
        for _f in (_p.get("findings") or []):
            _fi = _f.get("interpretation")
            if _fi:
                _f["interpretation"] = _strip_verdict_prefix(_fi)

    # Humanize the scan template's internal SQL aliases at the LAST touch before the
    # report ships — charts/tooltips were labelling series "Metric Total" and "Avg Per
    # Record" (live screenshot). Terminal on purpose: the chart-shaping helpers above
    # pattern-match on the raw alias names. column_units keys are renamed in sync.
    _mlabel = (intake_data.get("metric_label") or "").strip()
    if _mlabel:
        _alias_map = {
            "metric_total": _mlabel,
            "metric_value": _mlabel,
            "avg_per_record": f"{_mlabel} per record",
            "n": "records",
            "pct_of_total": "% of total",
        }
        # A forward-chained LENS measures something else entirely, so the run's primary
        # label is a lie on its grid: the soak shipped a load-factor chart whose axis read
        # "refund leakage rate" (inv 0db3a6db) because this pass stamps the intake's metric
        # onto every phase. Each lens names its own measure; only phases that actually ran
        # the primary metric may take the primary label.
        _lens_labels = {p.get("phase_id"): (p.get("metric_label") or "").strip()
                        for p in phases if p.get("metric_label")}
        for _p in phases:
            _own = _lens_labels.get(_p.get("phase_id"))
            _map = dict(_alias_map)
            if _own and _own != _mlabel:
                _map["metric_total"] = _own
                _map["metric_value"] = _own
                _map["avg_per_record"] = f"{_own} per record"
            for _f in (_p.get("findings") or []):
                _cols = _f.get("columns") or []
                if not any(c in _map for c in _cols):
                    continue
                _f["columns"] = [_map.get(c, c) for c in _cols]
                _units = _f.get("column_units") or {}
                if _units:
                    _f["column_units"] = {_map.get(k, k): v for k, v in _units.items()}

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
            AnswerRecommendation(
                action=r.action,
                expected_impact=r.expected_impact,
                owner=r.owner,
                timeline=r.timeline,
            )
            for r in synth.recommendations
        ]
        # A cross-sectional weakness scan has NO temporal comparison — it ranks across a dimension.
        # Don't stamp it with a fabricated MoM/YoY ("vs December 2021") or a "total change" label;
        # those fields belong only to the temporal baseline path.
        _xsec = bool(intake_data.get("cross_sectional"))
        answer_report = AnswerReport(
            headline=synth.headline,
            executive_summary=synth.executive_summary,
            metric=intake_data.get("metric_label", ""),
            observation_period=(intake_data.get("data_coverage_label", "") if _xsec else intake_data.get("observation_label", "")),
            metric_definition=_metric_definition_receipt(intake_data),
            comparison_basis="" if _xsec else intake_data.get("comparison_label", ""),
            total_change_label="" if _xsec else synth.total_change_label,
            phases=phases,
            attribution_waterfall=waterfall,
            confidence=synth.confidence,
            confidence_justification=synth.confidence_justification,
            recommendations=recommendations,
            data_gaps=synth.data_gaps,
            contradiction_report=contradiction_report.to_dict(),
            orchestration_plan=orchestration_plan,
            plan_reconciliation=plan_reconciliation,
        )
    else:
        # Issue-1 fix — when the narrator is slow/failed, assemble a DETERMINISTIC report from the
        # phase summaries instead of a bare "synthesis failed". Every phase already produced a
        # one-line summary; stitch them into a readable headline + exec summary so a stalled narrator
        # never costs the user the analysis that actually ran. (Frugal: no extra model call.)
        _xsec = bool(intake_data.get("cross_sectional"))
        _clean = lambda s: re.sub(r"\s+", " ", re.sub(r"\*+", "", (s or ""))).strip()
        _summaries = [_clean(p.get("summary")) for p in phases
                      if p.get("phase_id") != "intake"
                      and p.get("status") not in ("skipped", "error")
                      and _clean(p.get("summary"))]
        _headline = _fallback_headline(_summaries[0]) if _summaries \
            else "Investigation complete — see the phase findings below."
        _exec = (" ".join(_summaries))[:900] or "See the individual phase findings below for details."
        answer_report = AnswerReport(
            headline=_headline,
            executive_summary=_exec,
            metric=intake_data.get("metric_label", ""),
            observation_period=(intake_data.get("data_coverage_label", "") if _xsec else intake_data.get("observation_label", "")),
            metric_definition=_metric_definition_receipt(intake_data),
            comparison_basis="" if _xsec else intake_data.get("comparison_label", ""),
            total_change_label="",
            phases=phases,
            attribution_waterfall=[],
            confidence="LOW",
            confidence_justification=(
                "Narrative synthesis was unavailable (the model was slow or failed); this report is "
                "assembled deterministically from the phase findings, so treat the framing as "
                "provisional even though the underlying queries ran."
            ),
            recommendations=[],
            data_gaps=[],
            contradiction_report=contradiction_report.to_dict(),
            orchestration_plan=orchestration_plan,
            plan_reconciliation=plan_reconciliation,
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
        headline=answer_report["headline"],
        verdict=answer_report["executive_summary"],
        key_findings=legacy_findings[:5],
        what_is_not_the_cause=[g for g in answer_report["data_gaps"]],
        risks=[r["action"] for r in answer_report["recommendations"][:2]],
        recommended_actions=[r["action"] for r in answer_report["recommendations"]],
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

        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "evidence-ledger capture is non-critical; never break the "
                           "investigation output", counter="ada.evidence_ledger")

    return {
        "answer_report": answer_report,
        "report": legacy_report,
        "investigation_phases": phases,
    }
