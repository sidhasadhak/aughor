"""
ADA (Autonomous Data Analyst) phase prompts.

Each phase asks the LLM to: (1) plan SQL, then (2) interpret results.
All prompts are schema-adaptive — column names come from the actual schema,
never hardcoded.
"""

# ── Phase 1: Question intake (parsing only — no SQL) ─────────────────────────

INTAKE_PROMPT = """\
You are a senior data analyst performing question intake.

QUESTION: {question}

SCHEMA:
{schema}

PROFILE CONTEXT (date ranges, row counts, key columns):
{scan_context}

{events_section}

TASK: Parse this question into a precise investigation specification.

1. CORE METRIC — What single metric is the user asking about?
   Infer it from the question and schema. Use the exact SQL expression (e.g. SUM(final_price_usd)).
   Also name it (e.g. "net revenue", "order count", "average order value").

2. OBSERVATION PERIOD — What time period is in question?
   Extract explicit dates or infer from question language ("February 2026" → 2026-02-01 to 2026-02-28).
   If ambiguous, use the most recent full month/week/quarter visible in the schema date range.

3. COMPARISON BASIS — What is the baseline for comparison?
   Default: both PoP (prior period of same length) AND YoY (same period prior year).
   CRITICAL — check data availability BEFORE picking YoY:
   - Read the PROFILE CONTEXT to find the earliest date in the dataset.
   - If the earliest date in the data is AFTER the YoY period end date (e.g. data starts
     2025-01-01 but YoY would need 2024-06-01), there is NO 2024 data — do NOT set yoy_start/yoy_end.
     Use PoP only and note this in intake_notes.
   - If the schema date range covers less than 13 months total, use PoP only.
   - Only set yoy_start/yoy_end when the data actually covers the YoY period.

4. DATE COLUMN — Which table.column holds the primary transaction timestamp?
   Rules (all mandatory):
   - NEVER use an _id, _key, _code, or _num column as the date column. These are identifiers, not dates.
   - NEVER use a column of type INTEGER, BIGINT, VARCHAR, or TEXT as the date column.
   - Only use columns whose schema type contains DATE, TIMESTAMP, or TIME.
   - If the primary metric table has a "⚠ No date/timestamp columns" annotation (check schema),
     look in directly joinable tables (via foreign key) for a DATE/TIMESTAMP column.
   - Set date_column to the ACTUAL date column found (e.g. order_items.order_ts, NOT invoices.order_id).
   - If a join is required to reach the date column, document the join path in intake_notes.
   - If NO date column exists anywhere reachable by join, set date_column to "NONE" and explain in intake_notes.

5. METRIC TABLE — Which table contains the metric?
   Prefer fact tables (orders, order_items, transactions, sessions, events…).

6. AVAILABLE DIMENSIONS — List every categorical column available for drill-down.
   Include table name. Max 8 dimensions.

7. TRANSACTION STATUS FILTER — Does the metric table have a status/state column?
   If yes, identify which values represent COMPLETED/VALID transactions
   (e.g. 'PAID', 'COMPLETED', 'SETTLED', 'DELIVERED', 'CLOSED') as opposed to
   drafts, pending, cancelled, or refunded rows.
   - If a clear "completed" status exists, incorporate it into metric_sql as a CASE WHEN filter:
     e.g. SUM(CASE WHEN status IN ('PAID','SETTLED') THEN amount ELSE 0 END)
   - If all rows represent valid transactions (no status column or all rows count), use plain SUM().
   - Document your choice in intake_notes.

Be precise. Every answer must be grounded in the schema provided.
If something is genuinely unknowable from the schema, say so.
"""

# ── Phase 2: Baseline & anomaly detection ────────────────────────────────────

BASELINE_PLAN_PROMPT = """\
You are investigating: "{question}"

INVESTIGATION SPEC:
  Metric:            {metric_label} → SQL: {metric_sql}
  Observation:       {observation_period}
  Comparison:        {comparison_basis}
  Date column:       {date_column}
  Primary table:     {metric_table}

SCHEMA:
{schema}

{events_section}

PHASE: Baseline & Anomaly Assessment

Write 2–3 SQL queries to:
  1. Compute {metric_label} for at least 13 consecutive periods (months/weeks) ending
     at or after the observation period — to establish a baseline distribution.
  2. Compute period-over-period (PoP) and year-over-year (YoY) percentage changes
     for the observation period vs its comparators.
  3. Compute a z-score: how many standard deviations is the observation from the
     trailing baseline mean (EXCLUDE the observation period from baseline stats)?

SQL RULES:
  - DuckDB dialect only
  - DATE_TRUNC for period alignment
  - NULLIF(x, 0) before every division
  - Filter date column BEFORE joins (early predicate pushdown)
  - Compact result sets (≤ 20 rows)
  - Use only tables and columns present in the schema above
  - Alias every computed column with a human-readable name
  - TABLE NAMES: Use table names EXACTLY as shown in the SCHEMA section above. If the schema
    shows "inventory_movements" (no prefix), use that name as-is. If it shows "schema.table",
    include that prefix. Never add or remove schema prefixes that aren't in the schema.
  - NEVER cast an identifier column (_id, _key, _code, _num) as DATE or TIMESTAMP.
    If `date_column` is "invoices.order_id" or similar integer/string ID, it is WRONG — look for
    the real DATE/TIMESTAMP column in a joined table and JOIN to reach it instead.
  - If `date_column` belongs to a different table than the primary metric table, you MUST
    write an explicit JOIN to reach it. Never filter on a date column without joining its table.
  - NO EXTRA FILTERS: Only filter on the date range specified above. Do NOT add
    filters on status, amount thresholds, delay days, price bands, or any other column
    unless the investigation spec explicitly requires it. Arbitrary extra WHERE clauses
    will bias the results by excluding the majority of rows.

Return the queries with a short title and chart_type for each.
"""

BASELINE_INTERPRET_PROMPT = """\
INVESTIGATION: "{question}"
PHASE: Baseline & Anomaly Assessment

QUERY RESULTS:
{results_text}

{events_section}

Interpret these results clearly and honestly.

For EACH query result, write:
  - title: short descriptive label
  - interpretation: 2–3 sentences. Cite actual numbers from the data.
    State whether the observed change is statistically significant (z-score threshold: ±2.0).
    If a business calendar event may explain the anomaly, note it.
  - key_numbers: the 1–3 most important values (label, value, delta, context)
  - chart_type: "line" for time series, "bar" for comparisons, "none" for single-value outputs
  - stat_note: if z-score is available, format as "z = X.X — [significant/within normal range] at α = 0.05"
  - is_significant: true if |z| > 2.0 OR absolute change > 10% of prior period value

phase_summary: one sentence — the most important finding from this phase.
Do NOT fabricate numbers. If a query errored or returned no rows, say so honestly.
"""

# ── Phase 3: Metric decomposition ────────────────────────────────────────────

DECOMPOSE_PLAN_PROMPT = """\
INVESTIGATION: "{question}"
BASELINE FINDING: {baseline_summary}
  Total change: {total_change}

INVESTIGATION SPEC:
  Metric:        {metric_label} → {metric_sql}
  Observation:   {observation_period}  ({obs_start} to {obs_end})
  Comparison:    {comp_start} to {comp_end}
  Date column:   {date_column}
  Primary table: {metric_table}

SCHEMA:
{schema}

PHASE: Metric Decomposition

The metric {metric_label} can be decomposed into multiplicative or additive sub-metrics.
For example: Revenue = Orders × AOV = New + Returning customer revenue.

Write 2–3 SQL queries to break down WHAT drove the change:
  - If the metric is revenue/sales: decompose into volume (order count) vs. value (AOV)
  - If revenue: also decompose into new vs. returning customer revenue
  - If order count: decompose by channel or product category if available

For EACH sub-metric, compute it for BOTH the observation period AND the comparison period.
Use EXACT date ranges from the spec above. Include absolute change AND % contribution to total change.

Use the CASE WHEN date pattern to compare periods in a single query:
  SUM(CASE WHEN {date_column} >= '{obs_start}' AND {date_column} < date '{obs_end}' + INTERVAL 1 DAY
           THEN metric ELSE 0 END) AS obs_value,
  SUM(CASE WHEN {date_column} >= '{comp_start}' AND {date_column} < date '{comp_end}' + INTERVAL 1 DAY
           THEN metric ELSE 0 END) AS comp_value

SQL RULES: DuckDB, NULLIF, DATE_TRUNC, compact output.
  TABLE NAMES: Use table names exactly as shown in SCHEMA — no added/removed prefixes.
  Never CAST an _id/_key/_code column as DATE. If the date_column is in a joined table, JOIN to reach it.
  NO EXTRA FILTERS: Only filter on the two date ranges above. Do NOT add filters on status, amount,
  or any other column beyond what the metric_sql expression already includes. All rows count.
"""

DECOMPOSE_INTERPRET_PROMPT = """\
INVESTIGATION: "{question}"
PHASE: Metric Decomposition
BASELINE CONTEXT: {baseline_summary}

QUERY RESULTS:
{results_text}

For each query, interpret what sub-metric drove the overall change.
  - Was it volume (fewer transactions) or value (lower per-transaction amount)?
  - Was it new customers, returning customers, or both?
  - Which component explains the largest share of the total change?

Write clear, number-anchored interpretations. Cite values from the data.
State the key_numbers that demonstrate the decomposition.
phase_summary: "The decline was driven by X (Y%), not Z" — be definitive if the data supports it.
"""

# ── Phase 4: Dimensional drill-down ──────────────────────────────────────────

DIMENSIONAL_PLAN_PROMPT = """\
INVESTIGATION: "{question}"
BASELINE FINDING: {baseline_summary}
DECOMPOSITION FINDING: {decomposition_summary}

INVESTIGATION SPEC:
  Metric:        {metric_label} → {metric_sql}
  Observation:   {observation_period}  ({obs_start} to {obs_end})
  Comparison:    {comp_start} to {comp_end}
  Date column:   {date_column}
  Primary table: {metric_table}

SCHEMA:
{schema}

AVAILABLE DIMENSIONS (categorical columns for slicing):
{dimensions_list}

PHASE: Dimensional Drill-Down — WHERE did the change concentrate?

Write 1 SQL query per dimension (up to 4 dimensions). Each query must:
  1. Group by the dimension
  2. Compute metric for BOTH observation and comparison period
  3. Compute absolute change and CONTRIBUTION to total change (as % of total absolute change)
  4. Sort by absolute_change ASC (worst performers first)

CONTRIBUTION FORMULA (use window function):
  ROUND(100.0 * (obs - comp) / NULLIF(SUM(obs - comp) OVER (), 0), 1) AS contribution_pct

DIMENSION PRIORITY — analyse in this order (the list above is already sorted):
  1st: Customer type / segment (new vs returning — splits the entire cause tree)
  2nd: Channel / acquisition source (points to a team or budget)
  3rd: Product category / business line (assortment or pricing issue)
  4th: Geography / region (logistics, local competition, macro)
  Lower priority: device, payment method, price band

If fewer than 4 dimensions are available, analyse what exists in priority order.

SQL RULES: DuckDB, NULLIF, compact output (≤ 15 rows per query).
  TABLE NAMES: Use table names exactly as shown in SCHEMA — no added/removed prefixes.
  Never CAST an _id/_key/_code column as DATE. If the date_column is in a joined table, JOIN to reach it.
  NO EXTRA FILTERS: Filter ONLY on the two date ranges above (observation vs comparison).
  Do NOT add filters on status, price range, delay, or any other attribute. All rows count —
  adding extra filters will silently exclude data and produce biased contribution numbers.
"""

DIMENSIONAL_INTERPRET_PROMPT = """\
INVESTIGATION: "{question}"
PHASE: Dimensional Analysis
PRIOR CONTEXT: {prior_summary}

QUERY RESULTS:
{results_text}

For each dimension analysed, interpret the contribution analysis:
  - Which dimension value(s) account for > 30% of the total change? (primary drivers)
  - Is the decline concentrated (1–2 values driving 60%+ of change) or diffuse (uniform across all)?
  - Any dimension where one value has > 50% relative decline, even if small absolute? (severity alert)

Write dimension-by-dimension findings with specific numbers.
Highlight the SINGLE most actionable finding across all dimensions.
phase_summary: "X% of the total decline came from [dimension: value]" — if concentration exists.
"""

# ── Phase 5: Behavioral & operational ────────────────────────────────────────

BEHAVIORAL_PLAN_PROMPT = """\
INVESTIGATION: "{question}"
PRIOR FINDINGS SUMMARY:
{prior_summary}

DOMINANT FINDING FROM DIMENSIONAL ANALYSIS (Tier-2 output — focus your Tier-3 queries here):
{dominant_finding}

INVESTIGATION SPEC:
  Metric:        {metric_label} → {metric_sql}
  Observation:   {observation_period}  ({obs_start} to {obs_end})
  Comparison:    {comp_start} to {comp_end}
  Date column:   {date_column}
  Primary table: {metric_table}

SCHEMA:
{schema}

{events_section}

PHASE: Behavioral & Operational Diagnostics (Tier 3 — Second-Order Diagnosis)

YOUR JOB: Explain WHY the dominant finding above occurred.
Generate queries targeted at the specific segment, channel, or dimension identified
in the dominant finding — NOT generic checks. Examples:
  - If dominant = "mobile channel declined 65%" → query mobile-specific conversion,
    session quality, or mobile product coverage — NOT generic new vs. returning split.
  - If dominant = "Category X drove 72% of drop" → check stockout/pricing/promotion
    history for Category X specifically.
  - If dominant = "returning customers declined 40%" → run cohort retention analysis
    to find which acquisition cohort stopped buying.

Part A — Targeted behavioral queries (1–2):
  Directly test the most likely mechanisms behind the dominant finding.

Part B — Operational checks (1–2):
  - Refund/return rate change in the observation period?
  - Discount depth change?
  - Stockout signals for the affected segment/category (if inventory table exists)?
  - If required tables don't exist, set sql to null and explain in rationale.

Return max 4 queries total. Prioritise TARGETED queries over generic ones.
If a required table (sessions, refunds, inventory, etc.) does not exist in the schema above,
set sql to null and provide a one-line explanation in rationale — do NOT fabricate table names.

SQL RULES: DuckDB, NULLIF, compact output (≤ 15 rows per query).
  TABLE NAMES: Use table names exactly as shown in SCHEMA — no added/removed prefixes.
  Never CAST an _id/_key/_code column as DATE. If the date_column is in a joined table, JOIN to reach it.
  NO EXTRA FILTERS: Filter only on the date ranges above and the specific segment from the dominant
  finding. Do NOT add filters on amount, status, delay days, price bands, or unrelated attributes.
  Column aliases must match the actual schema column name or a clearly descriptive label — never
  alias a column with a name that belongs to a different schema column (e.g. don't alias utm_source as plan_type).
"""

BEHAVIORAL_INTERPRET_PROMPT = """\
INVESTIGATION: "{question}"
PHASE: Behavioral & Operational Diagnostics
PRIOR CONTEXT: {prior_summary}

QUERY RESULTS:
{results_text}

For behavioral findings:
  - Did new customer acquisition drop, returning customer activity drop, or both?
  - What was the magnitude of the behavioral shift?

For operational findings:
  - Did refund rate / discount depth / stockout rate change materially (> 20% relative)?
  - If so, does the magnitude explain any portion of the overall revenue change?

For untestable checks (missing data), note them as data gaps.
phase_summary: "Behaviorally, [X]. Operationally, [Y]." — two-part finding.
"""

# ── Phase 6: Synthesis — attribution waterfall ────────────────────────────────

ADA_SYNTHESIZE_PROMPT = """\
You are a senior data analyst writing an executive investigation report.

ORIGINAL QUESTION: {question}

INVESTIGATION FINDINGS BY PHASE:
{phases_summary}

FULL EVIDENCE (query results by phase):
{evidence_log}

{events_section}

Write a complete, honest investigation report.

IMPORTANT — ANSWER THE QUESTION ASKED:
  If the user asked "which channel/region/product/segment had most influence", answer that question
  directly in the headline and executive summary — even if the overall metric change is within
  normal statistical variance. Do NOT let "no anomaly detected" prevent you from reporting the
  dimensional breakdown the user requested. When the baseline is statistically normal:
  • Lead with the key dimensional finding (e.g. "Channel X accounts for 42% of February orders")
  • Then contextualise the baseline (e.g. "the MoM volume decline is calendar-driven, not a signal")
  • Still populate the attribution waterfall with dimensional contributors

ATTRIBUTION WATERFALL:
  Build a waterfall that accounts for the total observed change.
  Each entry: a root cause, its estimated contribution ($ or % of gap), controllability, structural vs. transient.
  The waterfall entries should sum to approximately 100% of the total change.
  If some portion is unexplained, include an "Unexplained / residual" entry.
  Use only numbers traceable to query results above. Do NOT fabricate values.

EVIDENCE TRACEABILITY RULE:
  Every number in headline, executive_summary, and waterfall must be traceable to a specific
  query result above. If a finding could not be measured, use qualitative language ("the data
  suggests…", "a material share…") rather than invented precision.

CONFIDENCE ASSESSMENT:
  HIGH   = multiple phases converge on the same root cause; attribution ~100%; z-score confirmed
  MEDIUM = primary cause identified but some attribution gaps; limited dimensional data
  LOW    = multiple plausible causes; data insufficient to discriminate; high residual

RECOMMENDATIONS:
  For each CONTROLLABLE root cause, provide a specific, actionable recommendation with:
  action, expected_impact (quantified if possible), owner (team/function), timeline.

DATA GAPS:
  List every hypothesis that could NOT be tested due to missing schema (no sessions table,
  no inventory table, etc.) with what data would be needed.
"""

# ── Pydantic response models for structured LLM outputs ──────────────────────

from pydantic import BaseModel, Field
from typing import Literal, Optional


class IntakeOutput(BaseModel):
    metric_label: str = Field(description="Human-readable name, e.g. 'net revenue'")
    metric_sql: str = Field(description="SQL aggregation expression, e.g. SUM(final_price_usd)")
    observation_start: str = Field(description="ISO date YYYY-MM-DD")
    observation_end: str = Field(description="ISO date YYYY-MM-DD")
    observation_label: str = Field(description="Human label, e.g. 'February 2026'")
    comparison_start: str = Field(description="ISO date of prior-period start")
    comparison_end: str = Field(description="ISO date of prior-period end")
    comparison_label: str = Field(description="e.g. 'January 2026 (MoM)'")
    yoy_start: Optional[str] = Field(default=None, description="YoY comparison start, or null if data < 13 months")
    yoy_end: Optional[str] = Field(default=None)
    date_column: str = Field(description="Fully qualified: table.column")
    metric_table: str
    dimensions: list[str] = Field(description="List of 'table.column' pairs available for drill-down")
    intake_notes: str = Field(description="Any caveats about the schema or question interpretation")


class PhaseQueryPlan(BaseModel):
    title: str
    sql: str
    chart_type: Literal["line", "bar", "bar_horizontal", "stacked_bar", "pie", "auto", "none"] = "auto"
    rationale: str


class PhasePlan(BaseModel):
    queries: list[PhaseQueryPlan]


class PhaseKeyNumberModel(BaseModel):
    label: str
    value: str
    delta: Optional[str] = None
    context: Optional[str] = None


class PhaseFindingModel(BaseModel):
    title: str
    interpretation: str
    key_numbers: list[PhaseKeyNumberModel] = Field(default_factory=list)
    chart_type: Literal["line", "bar", "bar_horizontal", "stacked_bar", "pie", "auto", "none"] = "auto"
    stat_note: Optional[str] = None
    is_significant: bool = False


class PhaseInterpretation(BaseModel):
    phase_summary: str
    findings: list[PhaseFindingModel]
    passes_to_next: str = Field(description="Key insight to carry into the next phase")


class WaterfallEntryModel(BaseModel):
    cause: str
    amount_label: str
    pct_of_total: float
    controllable: bool
    structural: bool


class ADARecommendationModel(BaseModel):
    action: str
    expected_impact: str
    owner: str
    timeline: str


class ADASynthesisModel(BaseModel):
    headline: str
    executive_summary: str
    total_change_label: str
    attribution_waterfall: list[WaterfallEntryModel]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    confidence_justification: str
    recommendations: list[ADARecommendationModel]
    data_gaps: list[str] = Field(default_factory=list)
