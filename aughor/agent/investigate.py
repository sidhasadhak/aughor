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


def route_after_intake(state: AgentState) -> str:
    """Diagnostic / cross-sectional questions (where-which-is-weakest, or no usable
    time axis) skip the temporal baseline and go straight to the dimensional
    weakness scan; everything else takes the normal temporal path."""
    intake = state.get("_ada_intake") or {}
    return "ada_cross_section" if intake.get("cross_sectional") else "ada_baseline"


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


def _build_grounded_schema(full_schema: str, metric_table: str, dimensions, date_column: str, question: str) -> str:
    """A JOIN-COMPLETE filtered schema for the ADA coder. Keeping only the metric +
    dimension tables drops the table that holds the date/join columns (revenue on
    `invoices`, the timestamp on `orders`), so the coder hallucinates a date column on
    the metric table. This keeps the metric + dimension tables, the date column's host
    table, FK-joinable neighbours, and temporal dimension tables, then appends the
    DETECTED JOIN PATHS hints (which _filter_schema strips) — what the /chat path does."""
    try:
        from aughor.tools.schema import _parse_schema_tables
        # If the schema isn't TABLE:-format (e.g. an already-scoped Data Catalog from the
        # /investigate route), don't re-filter it — that would drop the FK-neighbour tables
        # the route already added. The route owns scoping in that case.
        if not _parse_schema_tables(full_schema):
            return full_schema
    except Exception:
        pass
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
    except Exception:
        pass
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


def _missing_column_hint(err: str):
    """Turn a binder/missing-column error into a strong, specific repair diagnosis.
    Extracts the missing column + the engine's candidate bindings and tells the coder to
    JOIN to the table that actually has the column instead of dropping/renaming it — the
    exact recovery the ADA baseline missed for `invoices.order_ts` (lives in `orders`)."""
    if not err:
        return None
    low = err.lower()
    if "column" not in low and "binder" not in low:
        return None
    m = (re.search(r'does not have a column named\s+"?([A-Za-z0-9_.]+)"?', err, re.I)
         or re.search(r'Referenced column\s+"?([A-Za-z0-9_.]+)"?', err, re.I)
         or re.search(r'column\s+"?([A-Za-z0-9_.]+)"?\s+(?:not found|does not exist)', err, re.I))
    col = m.group(1) if m else "the referenced column"
    cands = re.findall(r'"([A-Za-z0-9_]+\.[A-Za-z0-9_]+)"', err)
    cand_txt = f" The engine offered candidate bindings: {', '.join(dict.fromkeys(cands))[:200]}." if cands else ""
    return (
        f"DIAGNOSIS: column '{col}' is not in the table(s) currently in the FROM/JOIN clause.{cand_txt} "
        f"Find which table in the SCHEMA actually contains '{col}' and JOIN to it using a shared key "
        f"(an *_id column). The timestamp/metric you need likely lives in a parent table (e.g. an orders "
        f"table) that must be joined — do NOT drop the column, rename it, or substitute a different one.\n"
    )


def _execute_safe(conn: "DatabaseConnection", phase_id: str, sql: str, schema: Optional[str] = None):
    """Execute SQL with one self-correction retry. Returns QueryResult.

    Retries on:
    - Hard SQL errors (syntax, missing column/table)
    - Suspicious zero-row results (e.g. CAST of identifier column as DATE)

    `schema` is the canvas-scoped schema for the fix prompt; without it the fix
    LLM would see the full connection schema (every dataset on a multi-dataset
    connection) and could "fix" a query by switching to an out-of-scope table.
    """
    from aughor.agent.prompts import FIX_SQL_PROMPT
    from aughor.agent.prompts_investigate import PhasePlan
    from pydantic import BaseModel

    # Deterministic de-fan (#1 correctness): a SUM of a parent measure across a
    # one-to-many join over-counts (5x) — and this is a deep-analysis headline
    # number. Replace it with the exact DISTINCT(parent-key, measure) dedup BEFORE
    # executing. Adopt only if it dry-runs clean; silent on anything it can't prove.
    if schema:
        try:
            from aughor.sql.fanout import detect_fanout, defan
            from aughor.tools.schema import _parse_schema_tables
            _dialect = getattr(conn, "dialect", "duckdb")
            _tc = {t: (list(c.keys()) if isinstance(c, dict) else c)
                   for t, c in _parse_schema_tables(schema).items()}
            _ff = detect_fanout(sql, _tc, dialect=_dialect)
            if _ff:
                _rw = defan(sql, _ff, dialect=_dialect)
                if _rw and _rw.strip() != sql.strip() and conn.dry_run(_rw)[0]:
                    sql = _rw
        except Exception:
            pass

    result = conn.execute(phase_id, sql)

    # Determine whether to retry: hard error OR suspicious zero-row result
    _zero_diag = None
    if not result.error and result.row_count == 0:
        _zero_diag = _zero_row_suspicious(sql)

    # Value-domain join guard: a join on value-disjoint keys produces an
    # unreliable result (0 rows on inner joins, all-NULL right side on outer)
    # without ever erroring. Detect it and feed the regenerate loop below.
    _domain_warnings = []
    try:
        from aughor.sql.join_guard import check_join_value_domains
        _domain_warnings = check_join_value_domains(conn, sql)
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "ada join-guard probe best-effort; query proceeds",
                 counter="join_guard.ada_probe")

    if result.error or _zero_diag or _domain_warnings:
        class _Fix(BaseModel):
            fixed_sql: str
            explanation: str

        try:
            _err = result.error or ""
            # Build targeted diagnosis for the fix LLM
            _col_hint = _missing_column_hint(_err)
            if _zero_diag:
                _diag = f"DIAGNOSIS: {_zero_diag}\n"
            elif _col_hint:
                _diag = _col_hint
            elif "does not exist" in _err and "table" in _err.lower():
                _diag = (
                    "DIAGNOSIS: A table name in the query does not exist. "
                    "Use ONLY the table names listed in the SCHEMA above.\n"
                )
            else:
                _diag = ""

            # Append the value-domain mismatch to the diagnosis (it may co-occur
            # with a zero-row diagnosis, or be the sole reason for the retry).
            if _domain_warnings:
                _dw_text = "\n".join(w.to_prompt_text() for w in _domain_warnings)
                _diag = (f"{_diag}\n{_dw_text}" if _diag else f"DIAGNOSIS: {_dw_text}").strip() + "\n"

            # Synthesise a fake "error" message so FIX_SQL_PROMPT has something
            # useful in the ERROR MESSAGE field when there was no hard error.
            if _err:
                fix_error = _err
            elif _domain_warnings:
                fix_error = "A join is on value-disjoint columns (see DIAGNOSIS) — the result is unreliable."
            else:
                fix_error = "Query returned 0 rows — the SQL logic is likely wrong (see DIAGNOSIS)."

            fix_prompt = FIX_SQL_PROMPT.format(
                dialect=conn.dialect,
                sql=sql,
                error=fix_error,
                schema=schema if schema else conn.get_schema(),
                kb_patterns_section="",
                metrics_section="",
                error_diagnosis=_diag,
            )
            fix = _provider("coder").complete(
                system="Fix this SQL query. Return fixed_sql and a one-line explanation.",
                user=fix_prompt,
                response_model=_Fix,
            )
            retry = conn.execute(phase_id, fix.fixed_sql)
            # Accept the fix if: hard error resolved, OR zero-row and fix got rows.
            # For a domain-mismatch retry, additionally require the regeneration to
            # actually CLEAR the mismatch — never replace a query with one that still
            # joins on value-disjoint keys (prevention > recovery; never go backwards).
            _accept = not retry.error and (retry.row_count > 0 or not _zero_diag)
            if _accept and _domain_warnings:
                try:
                    from aughor.sql.join_guard import check_join_value_domains as _cjvd
                    _accept = not _cjvd(conn, fix.fixed_sql)
                except Exception:
                    _accept = False
            if _accept:
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
    schema: Optional[str] = None,
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
        r = _execute_safe(conn, phase_id, sql, schema=schema)
        r.hypothesis_id = phase_id
        return [(q, r)]

    def _run(item: tuple) -> tuple:
        q, sql = item
        reader = conn.make_reader()
        r = _execute_safe(reader, phase_id, sql, schema=schema)
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
            r = _execute_safe(conn, phase_id, sql, schema=schema)
            r.hypothesis_id = phase_id
            results.append((q, r))
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
                    op = apply_step(
                        r, step.operator, step.column,
                        predicate=(step.predicate or ""),
                        fields=[(f.name, f.description) for f in step.fields],
                        criterion=(getattr(step, "criterion", "") or ""),
                        k=getattr(step, "k", 10),
                        instruction=(getattr(step, "instruction", "") or ""),
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


def _align_narrator_findings(queries, narrator_findings, extra_stop=frozenset()):
    """Bind each query to the narrator finding describing its SAME dimension.
    Returns (aligned, by_token): aligned[i] is the finding model for queries[i] (or
    None when no trustworthy match exists); by_token[i] is True when the match was
    made on a shared dimension token (so the query's own title is authoritative)."""
    n, m = len(queries), len(narrator_findings)
    aligned = [None] * n
    by_token = [False] * n
    if m == 0:
        return aligned, by_token
    q_tok = [_label_tokens(getattr(q, "title", ""), extra_stop) for q in queries]
    f_tok = [_label_tokens(getattr(f, "title", ""), extra_stop) for f in narrator_findings]
    used = set()
    cands = sorted(
        ((len(q_tok[qi] & f_tok[fi]), qi, fi)
         for qi in range(n) for fi in range(m) if q_tok[qi] & f_tok[fi]),
        key=lambda c: (-c[0], c[1], c[2]),
    )
    for _ov, qi, fi in cands:
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


def _assemble_phase_findings(results, narrator_findings, id_prefix, metric_label=""):
    """Build phase findings by binding each (query, result) to the narrator finding for
    its OWN dimension — never by list position. The displayed title is grounded in the
    query that produced the rows whenever the match is dimension-certain, so a card can
    never describe a different slice than its chart."""
    extra = _label_tokens(metric_label)
    aligned, by_token = _align_narrator_findings([q for q, _ in results], narrator_findings, extra)
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
                _ok, _why = verify_insight(r.rows, f.get("interpretation", ""), r.sql)
                if not _ok:
                    f["trust_caveat"] = _why
            except Exception as _e:
                from aughor.kernel.errors import tolerate
                tolerate(_e, "ada: advisory trust check", counter="ada.trust_advisory_failed")
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
        col = str(date_column).split(".")[-1].replace('"', "").replace(";", "")
        ref = str(table).replace('"', "").replace(";", "")
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
            except Exception:
                pass


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


_DIAGNOSTIC_RE = re.compile(
    r"where are we losing|losing money|\b(where|which|what)\b[^?]*\b(losing|lose|lost|leak\w*|"
    r"weak\w*|worst|lowest|underperform\w*|hurting|dragging|bleeding|inefficien\w*)\b",
    re.IGNORECASE,
)


def _is_diagnostic_question(q: str) -> bool:
    """Cross-sectional 'where/which is weakest / where are we losing money' questions —
    these have no useful time axis and should run a dimensional weakness scan."""
    return bool(_DIAGNOSTIC_RE.search(q or ""))


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
            except Exception:
                pass

    # Deterministic cross-sectional trigger — the intake LLM is unreliable at
    # setting the flag, so force it for diagnostic "where/which is weakest / where
    # are we losing money" questions OR when there is no usable time axis (no date
    # column). This routes to the dimensional weakness scan instead of a temporal
    # baseline (also fewer phases → faster).
    if intake is not None:
        no_time = (intake.date_column or "").strip().upper() in ("", "NONE")
        if _is_diagnostic_question(question) or no_time:
            intake.cross_sectional = True

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
            except Exception:
                pass
        if _unsafe:
            _safe = _safe_metric_fallback(intake.metric_sql)
            _metric_note = (
                f"Metric adjusted for safety: the parsed metric would over-count ({_unsafe}); "
                f"ranking instead by {_safe} for a trustworthy magnitude."
            )
            intake.metric_sql = _safe

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
    if intake is not None and not intake.cross_sectional:
        # The data's true date span drives temporal windowing (esp. the re-anchor of a
        # 'last-N' window to the most recent data). The scan PORTRAIT undercounts the max
        # (it reported 2024-05 when the orders table runs to 2024-12 — mis-anchoring "last
        # 12 months"); the DB MIN/MAX probe is authoritative. UNION both so neither a short
        # portrait nor a failed probe can shrink the range. ISO date strings → lexical min/max.
        _smin, _smax = _extract_data_date_range(scan, intake.metric_table or "")
        _pmin, _pmax = _measure_date_span(
            state.get("connection_id") or "", intake.metric_table or "", intake.date_column or ""
        )
        _cmin = min([d for d in (_smin, _pmin) if d], default="")
        _cmax = max([d for d in (_smax, _pmax) if d], default="")
        _cov_note = _clamp_intake_to_coverage(intake, _cmin, _cmax, question=state.get("question", ""))
        if _cov_note:
            intake.intake_notes = f"{_cov_note} {intake.intake_notes or ''}".strip()

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
    if _metric_note:
        intake_dict["metric_safety_note"] = _metric_note

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


class _PhaseRun:
    """Outcome of the shared plan→execute→interpret skeleton. On failure `error_phase` is a
    ready phase the caller returns; on success the caller proceeds with its bespoke tail."""
    def __init__(self, ok, results=None, results_text="", interpretation=None, error_phase=None):
        self.ok = ok
        self.results = results or []
        self.results_text = results_text
        self.interpretation = interpretation
        self.error_phase = error_phase


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
) -> "_PhaseRun":
    """The plan(coder) → execute(parallel, safe) → interpret(fast) skeleton every ADA phase
    shares. Returns a _PhaseRun; a planning or execution failure carries a ready error/skipped
    phase for the caller to return. The interpret prompt is built by ``interpret_user_fn(
    results_text)`` since it depends on the executed results."""
    from aughor.agent.prompts_investigate import PhasePlan, PhaseInterpretation

    # Step 1 — plan
    try:
        plan: PhasePlan = _provider("coder").complete(
            system=plan_system, user=plan_user, response_model=PhasePlan)
    except Exception as e:
        return _PhaseRun(ok=False, error_phase=_phase_result(
            phase_id, title, emoji, "error", plan_error_msg, [_skipped_finding(phase_id, str(e))]))

    # Temporal guard (WCH-DS) — the intake clamp put LITERAL observation/comparison windows into
    # plan_user, but a coder that reaches for CURRENT_DATE / NOW() / DATE_SUB produces ZERO rows on
    # historical data. The prompt rule is advisory; this ENFORCES it with one corrective re-plan
    # that must use the literal dates. (Shared by every phase, so baseline/decompose/dimensional/
    # behavioral are all covered.)
    if plan and plan.queries and any(_uses_relative_date(q.sql) for q in plan.queries):
        from aughor.stats import stats as _s; _s.inc("temporal_guard_retries")
        try:
            _fixed = _provider("coder").complete(
                system=plan_system,
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

    # Step 2 — execute (parallel — each query gets its own reader connection)
    results = _parallel_execute_safe(conn, phase_id, plan.queries, cap=cap, schema=schema)
    if not results:
        return _PhaseRun(ok=False, error_phase=_phase_result(
            phase_id, title, emoji, exec_status, exec_error_msg,
            [_skipped_finding(phase_id, exec_skipped_reason)]))

    # Step 2b — semantic operators (opt-in per query): turn text-column results into evidence the
    # interpreter can reason over. No-op unless the planner attached a step; fail-open and guarded.
    results = _apply_semantic_steps(results)

    # Step 3 — interpret
    results_text = _results_to_text([r for _, r in results])
    interpretation = None
    try:
        if not _has_usable_data(results):
            raise RuntimeError("skip narrator — no usable data")
        interpretation = _provider("fast").complete(
            system=interpret_system, user=interpret_user_fn(results_text),
            response_model=PhaseInterpretation)
    except Exception:
        interpretation = None
    return _PhaseRun(ok=True, results=results, results_text=results_text, interpretation=interpretation)


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
        exec_skipped_reason="No queries produced results.",
    )
    if not _run.ok:
        return {"investigation_phases": phases + [_run.error_phase]}
    results, results_text, interpretation = _run.results, _run.results_text, _run.interpretation

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
                    code_sigma = float(sr.sigma)  # numpy.float64 → python float
        if code_sigma is not None:
            # bool() so a numpy.bool_ never reaches graph state — the LangGraph msgpack
            # checkpointer can't serialize numpy scalars and the whole run crashes.
            code_significant = bool(code_sigma >= 2.0)
            break  # first successful result is enough

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
    _run = run_analysis_phase(
        conn, phase_id="decomposition", title="Metric Decomposition", emoji="🧩", schema=schema,
        plan_system="Write SQL for metric decomposition. Decompose the metric into additive sub-drivers." + _ADA_SQL_GROUNDING,
        plan_user=plan_prompt,
        interpret_system="Interpret metric decomposition results. State clearly whether volume or value drove the change.",
        interpret_user_fn=lambda results_text: DECOMPOSE_INTERPRET_PROMPT.format(
            question=question, baseline_summary=baseline_summary, results_text=results_text),
        plan_error_msg="Could not plan decomposition queries.",
        exec_error_msg="Decomposition queries failed.",
    )
    if not _run.ok:
        return {"investigation_phases": phases + [_run.error_phase]}
    results, results_text, interpretation = _run.results, _run.results_text, _run.interpretation

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
    _run = run_analysis_phase(
        conn, phase_id="dimensional", title="Dimensional Analysis", emoji="🔬", schema=schema,
        plan_system="Write contribution-analysis SQL for each dimension. Sort by absolute_change ASC." + _ADA_SQL_GROUNDING,
        plan_user=plan_prompt,
        interpret_system="Interpret contribution analysis. Identify concentrated vs. diffuse decline.",
        interpret_user_fn=lambda results_text: DIMENSIONAL_INTERPRET_PROMPT.format(
            question=question, prior_summary=prior_summary, results_text=results_text),
        plan_error_msg="Could not plan dimensional queries.",
        exec_error_msg="Dimensional queries failed.",
    )
    if not _run.ok:
        return {"investigation_phases": phases + [_run.error_phase]}
    results, results_text, interpretation = _run.results, _run.results_text, _run.interpretation

    if interpretation and interpretation.findings:
        findings = _assemble_phase_findings(results, interpretation.findings, "dim")
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
        exec_skipped_reason="Required tables (sessions, refunds, etc.) not in schema.",
    )
    if not _run.ok:
        return {"investigation_phases": phases + [_run.error_phase]}
    results, results_text, interpretation = _run.results, _run.results_text, _run.interpretation

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


@_telemetry.node_span("ada_cross_section")
def ada_cross_section(state: AgentState, conn: "DatabaseConnection") -> dict:
    """Cross-sectional WEAKNESS SCAN — for diagnostic questions ("where are we
    losing money / which X is weakest") the metric has no usable time axis, so we
    rank the money metric across each available dimension to surface the lowest /
    most-concentrated values, instead of a temporal baseline."""
    from aughor.agent.prompts_investigate import (
        CROSS_SECTION_PLAN_PROMPT, CROSS_SECTION_INTERPRET_PROMPT,
        PhasePlan, PhaseInterpretation,
    )
    question = state["question"]
    phases = state.get("investigation_phases", [])
    intake_data = state.get("_ada_intake") or {}
    schema = _with_ledger(state, intake_data.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT))
    metric_label = intake_data.get("metric_label", "the metric")
    metric_sql = intake_data.get("metric_sql", "SUM(revenue)")
    metric_table = intake_data.get("metric_table", "")
    dimensions = intake_data.get("dimensions", [])

    prioritized = _prioritize_dimensions(dimensions)
    dimensions_list = "\n".join(f"  - {d}" for d in prioritized[:6]) if prioritized else "  (none identified)"

    _run = run_analysis_phase(
        conn, phase_id="cross_section", title="Cross-Sectional Scan", emoji="🧭", cap=5, schema=schema,
        plan_system="Write one ranking query per dimension. Rank the metric ascending (weakest first). No time filters." + _ADA_SQL_GROUNDING,
        plan_user=CROSS_SECTION_PLAN_PROMPT.format(
            question=question, metric_label=metric_label, metric_sql=metric_sql,
            metric_table=metric_table, schema=schema, dimensions_list=dimensions_list),
        interpret_system="Interpret a cross-sectional weakness scan. Name the weakest values and any concentration; be honest about healthy areas.",
        interpret_user_fn=lambda results_text: CROSS_SECTION_INTERPRET_PROMPT.format(
            question=question, metric_label=metric_label, results_text=results_text),
        plan_error_msg="Cross-sectional planning failed.",
        exec_error_msg="Cross-sectional queries failed.",
    )
    if not _run.ok:
        return {"investigation_phases": phases + [_run.error_phase]}
    results, results_text, interpretation = _run.results, _run.results_text, _run.interpretation

    if interpretation and interpretation.findings:
        findings = _assemble_phase_findings(results, interpretation.findings, "xsec", metric_label=metric_label)
        summary = interpretation.phase_summary
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"xsec_{i}", title=q.title, sql=r.sql,
                columns=r.columns, rows=r.rows[:50], row_count=r.row_count,
                error=r.error, interpretation="Query executed.",
                key_numbers=[], chart_type=q.chart_type, stat_note=None, is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = "Cross-sectional scan complete."

    # Make the bar plot the metric magnitude, not its share-of-total (see helper).
    for f in findings:
        _chart_primary_is_metric(f)

    phase = _phase_result(
        "cross_section", "Cross-Sectional Scan", "🧭",
        "complete" if any(not f["error"] for f in findings) else "partial",
        summary, findings,
    )
    return {"investigation_phases": phases + [phase], "_cross_section_summary": summary}


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
    # Budget-aware: phases are kept verbatim (exact numbers, for grounding) up to the budget; any
    # overflow is folded into a number-preserving digest (tree-reduce) instead of being truncated away.
    evidence_log = _phases_evidence_budgeted(phases)

    # ── Cross-phase contradiction detection ───────────────────────────────────
    # Before synthesis, deterministically check phase summaries for contradictions.
    # Example: baseline says "significant drop (z=-2.4)" while dimensional says
    # "no segment deviates from baseline" — the synthesizer must not silently paper
    # over this.  We inject any contradictions as a hard instruction in the prompt.
    contradiction_section = _detect_phase_contradictions(phases)

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
            "weakest areas. Be honest about which areas are healthy and NOT a problem."
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
        evidence_log=evidence_log,
        events_section=events_section,
        metric_targets_section=metric_targets_section,
        playbook_section=playbook_section,
        org_intelligence_section=org_intelligence_section,
        external_context_section=external_context_section,
    ) + contradiction_section + early_stop_note + cross_section_note
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
