"""
ADA (Autonomous Intelligence Platform) phase prompts.

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
{origin_finding_section}
TASK: Parse this question into a precise investigation specification.

1. CORE METRIC — What single metric is the user asking about?
   Infer it from the question and schema. Use the exact SQL expression (e.g. SUM(final_price_usd)).
   Also name it (e.g. "net revenue", "order count", "average order value").
   BINDING RULE (critical): if a CANONICAL METRICS section appears below and the question's
   metric matches one of those names, use ITS aggregate expression VERBATIM — do not re-derive
   it, do not add or drop columns (e.g. never multiply a margin formula by a `quantity` column
   the governed formula doesn't use), and keep its filters. The governed formula is the
   authority; use the schema only for columns it doesn't already name.
   INTENT GUARD (critical): if the question is about money / profitability / "losing money" /
   cost / margin / revenue / sales, the metric MUST be a financial measure (revenue, sales,
   profit, margin, cost, or spend) — NEVER a proxy such as review count, star rating, sentiment,
   or NPS. If the question names no explicit metric and asks where/what is weakest, underperforming,
   or losing money, default to the primary revenue / value measure in the schema. A money question
   must never resolve to a sentiment or review metric.

2. OBSERVATION PERIOD — What time period is in question?
   Extract explicit dates or infer from question language ("February 2026" → 2026-02-01 to 2026-02-28).
   GRAIN: the PROFILE states the analytical grain and how much history exists (e.g. "53 weeks of
   history"). Use THAT grain for the observation and comparison periods — do NOT default to months.
   If ambiguous, use the most recent COMPLETE period at that grain.
   CROSS-SECTIONAL: if the PROFILE says "analyse cross-sectionally" (too few periods for a trend) OR
   the metric table has no date column OR the question asks where/which/what is weakest / losing money
   / underperforming, there is no usable time axis — set cross_sectional=true, use the full data range
   as the observation, and plan to compare across DIMENSIONS (segments / regions / products), not periods.

3. COMPARISON BASIS — What is the baseline for comparison?
   Default: both PoP (prior period of same length) AND YoY (same period prior year).
   CRITICAL — every comparison window MUST contain data. Read the PROFILE CONTEXT date range
   (e.g. "2024-05-01 → 2024-05-31") and period count FIRST:
   - PoP guard: the prior period must fall INSIDE the data's date range. If the prior period is
     before the earliest date (e.g. data starts 2024-05-01 but PoP would need April 2024), there
     is NO prior-period data — do NOT invent it. Either pick the most recent PRIOR period that
     actually has data, or set comparison_start/comparison_end equal to observation_start/end and
     state in intake_notes "no prior period available — only N period(s) of data".
   - YoY guard: if the earliest date is AFTER the YoY period end (e.g. data starts 2025-01-01 but
     YoY needs 2024-06-01), there is NO prior-year data — do NOT set yoy_start/yoy_end. Note it.
   - If the schema date range covers less than 13 months total, use PoP only.
   - PARTIAL trailing period: if the profile marks the last month "PARTIAL (incomplete)", do NOT
     use it as the observation period or read its low value as a decline — use the last COMPLETE
     period instead and note the partial month in intake_notes.
   - Only set windows the data actually covers. Never compare against an empty period.

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
   CRITICAL: the table name MUST appear verbatim in the SCHEMA above. Do NOT invent or assume table names.
   Prefer fact tables. Use the EXACT table name as shown in the SCHEMA (e.g. ecommerce.orders).
   If the SCHEMA shows a schema prefix (e.g. "TABLE: ecommerce.orders"), you MUST include that prefix in metric_table.

6. AVAILABLE DIMENSIONS — List every categorical column available for drill-down.
   Include table name. Max 8 dimensions.

7. TRANSACTION STATUS FILTER — Does the metric table have a status/state column?
   If yes, list the distinct status values present and note which appear terminal vs active.
   - Do NOT automatically filter by status — include ALL rows in metric_sql by default.
   - Only apply a status filter if the user's question explicitly asks about completed/valid
     transactions (e.g. "successful orders", "paid invoices", "delivered shipments").
   - If you do filter, document the exact filter and reasoning in intake_notes.
   - If all rows represent valid transactions (no status column), use plain SUM().

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
  - ALWAYS use the exact table names shown in the SCHEMA, including schema prefix (e.g. ecommerce.orders)
  - DATE_TRUNC for period alignment
  - NULLIF(x, 0) before every division
  - Filter date column BEFORE joins (early predicate pushdown)
  - Compact result sets (≤ 20 rows)
  - Use ONLY tables and columns that are explicitly listed in the SCHEMA above. NEVER invent table names.
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
  - interpretation: 2–3 tight sentences that lead with the finding. Cite actual numbers from
    the data and wrap the single most important number in **double asterisks** for bold.
    State whether the observed change is statistically significant.
    If a business calendar event may explain the anomaly, note it.
  - key_numbers: the 1–3 most important values (label, value, delta, context)
  - chart_type: "line" for time series, "bar" for comparisons, "pareto" for concentration
    (one categorical + one measure where a few categories drive most of the total — 80/20),
    "none" for single-value outputs
  - stat_note: if z-score is available, format as "z = X.X — [significant/within normal range]"
  - is_significant: true if |z| > {z_threshold} OR absolute change > {pct_threshold}% of prior period value

phase_summary: one sentence that leads with the key number (bold it with **double asterisks**) — the most important finding from this phase.
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
Choose a decomposition that fits the data — common patterns include:
  - Volume × Value (e.g. order_count × avg_value)
  - Segment breakdown (by category, region, channel, customer type — whatever dimensions exist)
  - Funnel stages (if lifecycle states exist)

Write 2–3 SQL queries to break down WHAT drove the change:
  - Use dimensions that actually exist in the SCHEMA — do not assume columns like "customer_type"
    or "channel" unless they appear in the schema.
  - Pick the decomposition that best explains the metric's components in THIS dataset.

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

Write clear, number-anchored interpretations; bold the decisive number in each with **double asterisks**. Cite values from the data.
State the key_numbers that demonstrate the decomposition.
phase_summary: "The decline was driven by X (**Y%**), not Z" — bold the share; be definitive if the data supports it.
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

Write dimension-by-dimension findings with specific numbers; bold the decisive number in each with **double asterisks**.
Highlight the SINGLE most actionable finding across all dimensions.
phase_summary: "**X%** of the total decline came from [dimension: value]" — bold the share; if concentration exists.
"""

# ── Cross-sectional weakness scan (non-temporal diagnostic) ───────────────────

CROSS_SECTION_PLAN_PROMPT = """\
DIAGNOSTIC QUESTION: "{question}"

This is a CROSS-SECTIONAL question — "where / which is weakest", "where are we losing money".
There is NO useful time axis; do NOT compare periods. Instead rank the metric across each
dimension to find WHERE value is lowest or most concentrated.

METRIC: {metric_label} → {metric_sql}
PRIMARY TABLE: {metric_table}

SCHEMA:
{schema}

DIMENSIONS (categorical columns to slice by, priority order):
{dimensions_list}

Write 1 SQL query per dimension (up to 5). Each query MUST:
  1. GROUP BY the dimension value.
  2. Compute the metric ({metric_sql}) per value AS metric_total, plus COUNT(*) AS n.
  3. Compute the AVERAGE per record: ROUND(<metric> / NULLIF(COUNT(*), 0), 2) AS avg_per_record.
     This separates per-unit weakness from sheer volume — a value can be small in total yet
     efficient per record (high average), or large in total yet inefficient (low average).
  4. Compute each value's share of the metric total:
     ROUND(100.0 * <metric> / NULLIF(SUM(<metric>) OVER (), 0), 1) AS pct_of_total
  5. ORDER BY metric_total ASC (weakest first) so the worst performers surface.
  6. LIMIT 15.

SQL RULES: DuckDB. NULLIF before every division. Use table names EXACTLY as in SCHEMA. If the
dimension lives in another table, JOIN to reach it (use DISTINCT or a pre-aggregated subquery so a
one-to-many join does NOT fan out and multiply the metric). NO date filters and NO status/price/other
filters — every row counts. SELECT the dimension column FIRST, aliased with the dimension's OWN name
(e.g. channel, region, product, currency) — never a generic alias like "dimension_value"; that label
becomes the chart axis. metric_total comes SECOND. chart_type: "bar_horizontal".
"""

CROSS_SECTION_INTERPRET_PROMPT = """\
DIAGNOSTIC QUESTION: "{question}"
METRIC: {metric_label}
PHASE: Cross-Sectional Weakness Scan

QUERY RESULTS — each dimension value with its metric_total, avg_per_record, n, and
pct_of_total share, weakest total first:
{results_text}

For EACH dimension, write a finding:
  - title: the dimension (e.g. "By franchise", "By region", "By product"). Use the SAME
    dimension wording as the query so the card matches its chart.
  - interpretation: 2–3 tight sentences. Name the WEAKEST values by total AND read the
    AVERAGE: distinguish low TOTAL from low AVERAGE — a value can bill little in total yet be
    efficient per record, or look large yet be inefficient (low avg). Call out where the two
    lenses diverge (e.g. "11 franchises bill under $1,000; the worst, X, also averages just
    **$4.20/order** vs the ~$9 typical"). Bold the decisive number with **double asterisks**.
    Cite real values only.
    SEVERITY GROUNDING: "lowest in the ranking" is NOT the same as "weak". Only call a value
    'weak', 'critically low', 'underperforming', or 'a problem' if it is below a stated
    benchmark/target OR far below the in-result average. If the values are tightly clustered
    and all healthy (e.g. margins all 47–55%), say so and use relative language ("the lowest
    at 47% vs the ~51% average") — never an absolute superlative.
  - key_numbers: the 1–3 most telling values — include a TOTAL and an AVERAGE where the
    average reveals something the total hides.
  - chart_type: "bar_horizontal".
  - is_significant: true ONLY when this dimension is below a benchmark or far below the average — not merely the minimum of a healthy spread.

Be honest: if a dimension is healthy or evenly spread, say it is NOT a problem area.

phase_summary: one sentence naming where value is most concentrated or weakest — lead with the
decisive number (bold it), e.g. "Losses concentrate in **11** underperforming franchises (< $1,000 each)."
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
phase_summary: "Behaviorally, [X]. Operationally, [Y]." — two-part finding; bold the decisive number in each part with **double asterisks**.
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

{metric_targets_section}

{playbook_section}

{org_intelligence_section}

{external_context_section}

Write a complete, honest investigation report.

WRITING STYLE (clean published brief):
  • headline: one sentence, max 16 words, lead with the answer. No "Investigation into…" preamble.
  • executive_summary: 2–4 tight sentences that lead with the finding. Wrap each decisive number
    in **double asterisks** for bold (e.g. **$2.1M**, **-18%**, **42%**). Drop hedging words
    ("appears", "seems") when the evidence is strong, and cut "as we can see" scaffolding.
  • recommendations[].action: start with an imperative verb; bold the key lever or number.
  Bold marks numbers already traceable to the evidence — it never licenses inventing precision.

IMPORTANT — ANSWER THE QUESTION ASKED:
  If the user asked "which channel/region/product/segment had most influence", answer that question
  directly in the headline and executive summary — even if the overall metric change is within
  normal statistical variance. Do NOT let "no anomaly detected" prevent you from reporting the
  dimensional breakdown the user requested. When the baseline is statistically normal:
  • Lead with the key dimensional finding (e.g. "Channel X accounts for 42% of February orders")
  • Then contextualise the baseline (e.g. "the MoM volume decline is calendar-driven, not a signal")
  • Still populate the attribution waterfall with dimensional contributors

SIGN CONVENTION (critical — keep signs consistent EVERYWHERE):
  Losses and declines are NEGATIVE; gains and improvements are POSITIVE. This applies to
  total_change_label AND every attribution_waterfall entry AND every number in executive_summary.
  • total_change_label: signed by the direction of the overall change (e.g. "-$330K" for a
    decline, "+$120K" for growth).
  • Within each waterfall entry, amount_label and pct_of_total MUST share the SAME sign: a cause
    that pushed the metric DOWN is negative in both; a cause that pushed it UP (a partial offset)
    is positive in both. Never pair a positive pct with a negative amount or vice versa.
  • The signed waterfall contributions must net to the direction of total_change_label.
  The SAME quantity must never read positive in one place and negative in another.

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
  If METRIC TARGETS are provided above, prioritise root causes where the current value
  exceeds the warning or critical threshold — those are the highest-urgency items.

DATA GAPS:
  List every hypothesis that could NOT be tested due to missing schema (no sessions table,
  no inventory table, etc.) with what data would be needed.

CAUSAL LINKS:
  Extract directional cause→effect relationships you identified with reasonable evidence.
  These will be stored as proposals and only promoted to a causal knowledge graph if a
  human later confirms the recommendations were effective.
  Format: from_signal (upstream cause) → to_signal (downstream effect).
  Only include links you can defend from the evidence above. Leave empty if none.
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
    cross_sectional: bool = Field(default=False, description="True when the question asks where/which/what is weakest / losing money / underperforming, OR the data has too few periods for a trend — analyse across DIMENSIONS, not time.")
    intake_notes: str = Field(description="Any caveats about the schema or question interpretation")


class SemanticField(BaseModel):
    """One field to pull out of a free-text column."""
    name: str = Field(description="Short snake_case column name for the extracted value, e.g. 'root_cause'.")
    description: str = Field(default="", description="What to extract, e.g. 'the product area the complaint is about'.")


class SemanticStep(BaseModel):
    """An LLM operator to run over ONE free-text column of this query's result, after the SQL runs."""
    operator: Literal["filter", "extract", "top_k", "aggregate"]
    column: str = Field(description="The free-TEXT column in this query's result to operate on.")
    predicate: str = Field(default="", description="filter only: keep rows whose text satisfies this NL predicate, e.g. 'the ticket is a billing complaint'.")
    fields: list[SemanticField] = Field(default_factory=list, description="extract only: the fields to pull from the text into new columns.")
    criterion: str = Field(default="", description="top_k only: rank rows by how well the text matches this criterion, keep the best k, e.g. 'most severe outage'.")
    k: int = Field(default=10, description="top_k only: how many top rows to keep.")
    instruction: str = Field(default="", description="aggregate only: synthesize ONE answer from all the rows' text per this instruction, e.g. 'summarize the recurring complaint themes'.")


class PhaseQueryPlan(BaseModel):
    title: str
    sql: str
    chart_type: Literal["line", "bar", "bar_horizontal", "stacked_bar", "pie", "pareto", "auto", "none"] = "auto"
    rationale: str
    semantic: Optional[SemanticStep] = Field(
        default=None,
        description=(
            "OPTIONAL. Attach ONLY when this query returns a free-TEXT column (support tickets, reviews, "
            "notes, descriptions, comments) that needs reasoning SQL cannot do. 'filter' keeps rows whose "
            "text matches a natural-language predicate; 'extract' pulls named fields from the text into new "
            "columns. Leave null for ordinary numeric/aggregate/dimensional queries — most queries."
        ),
    )


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
    chart_type: Literal["line", "bar", "bar_horizontal", "stacked_bar", "pie", "pareto", "auto", "none"] = "auto"
    stat_note: Optional[str] = None
    is_significant: bool = False


class PhaseInterpretation(BaseModel):
    phase_summary: str
    findings: list[PhaseFindingModel]
    passes_to_next: str = Field(description="Key insight to carry into the next phase")


class WaterfallEntryModel(BaseModel):
    cause: str
    amount_label: str = Field(description="Signed magnitude, e.g. '-$287K' for a loss/decline contributor, '+$120K' for a gain. The leading sign MUST match pct_of_total.")
    pct_of_total: float = Field(description="Share of the total change, SIGNED: negative if this cause reduced the metric (a loss driver), positive if it increased it. Same sign as amount_label.")
    controllable: bool
    structural: bool


class ADARecommendationModel(BaseModel):
    action: str
    expected_impact: str
    owner: str
    timeline: str


class CausalLinkModel(BaseModel):
    from_signal: str = Field(description="The upstream cause signal, e.g. 'elevated stockout rate'")
    to_signal: str = Field(description="The downstream effect signal, e.g. 'increased refund rate'")
    from_entity: Optional[str] = Field(default=None, description="Business entity id if identifiable, e.g. 'Inventory'")
    to_entity: Optional[str] = Field(default=None, description="Business entity id if identifiable, e.g. 'Order'")
    confidence: float = Field(default=0.5, description="Your confidence in this causal link, 0–1")


class ADASynthesisModel(BaseModel):
    headline: str
    executive_summary: str
    total_change_label: str
    attribution_waterfall: list[WaterfallEntryModel]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    confidence_justification: str
    recommendations: list[ADARecommendationModel]
    data_gaps: list[str] = Field(default_factory=list)
    causal_links: list[CausalLinkModel] = Field(
        default_factory=list,
        description="Directional cause→effect pairs identified in this investigation. Only include links with clear evidence.",
    )
