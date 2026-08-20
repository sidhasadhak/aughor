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
   MAGNITUDE GUARD (critical): when the question names a QUANTITY — a delay, a duration, a lead
   time, an age, a distance, an amount — and the schema records BOTH the measured quantity and a
   0/1 indicator that merely flags it, the metric is the MEASURED QUANTITY. "Shipping delay" over a
   schema holding `Days for shipping (real)`, `Days for shipment (scheduled)` and `Late_delivery_risk`
   is `AVG("Days for shipping (real)" - "Days for shipment (scheduled)")`, NOT `AVG(Late_delivery_risk)`:
   the flag answers "how often", the question asked "how much", and a rate cannot be read back as a
   magnitude. Indicator columns are recognisable by name (`*_risk`, `is_*`, `has_*`, `*_flag`,
   `*_indicator`) or by holding only 0 and 1. Use the flag only when the question itself asks about
   frequency ("how often are we late", "what share of orders are late").
   METRIC KIND: set metric_is_ratio=true when the metric is a RATIO / percentage / rate / per-unit
   average (it divides one aggregate by another, scales by *100, or is an AVG / mean — e.g. "freight
   as % of order value", "cancellation rate", "average order value", "margin %"). Set it false for a
   plain additive total (SUM/COUNT of revenue, orders, units). This governs how downstream phases
   aggregate the metric across segments — a ratio is never summed or divided by row count.

2. OBSERVATION PERIOD — What time period is in question?
   Extract explicit dates or infer from question language ("February 2026" → 2026-02-01 to 2026-02-28).
   GRAIN: the PROFILE states the analytical grain and how much history exists (e.g. "53 weeks of
   history"). Use THAT grain for the observation and comparison periods — do NOT default to months.
   If ambiguous, use the most recent COMPLETE period at that grain.
   CROSS-SECTIONAL: if the PROFILE says "analyse cross-sectionally" (too few periods for a trend) OR
   the metric table has no date column OR the question asks where/which/what is weakest / losing money
   / underperforming, there is no usable time axis — set cross_sectional=true, use the full data range
   as the observation, and plan to compare across DIMENSIONS (segments / regions / products), not periods.
   DRIVER / RELATIONSHIP (critical): if the question asks whether one thing AFFECTS / RELATES TO /
   DRIVES / LOWERS / RAISES / HURTS / IMPROVES / CORRELATES WITH another — e.g. "do late deliveries
   lower review scores", "do new customers spend more", "does installment count affect cancellations"
   — it is a GROUP COMPARISON, NOT a time trend. Set cross_sectional=true and populate
   comparison_segment_sql with the boolean/CASE SQL for the condition X (e.g.
   (order_delivered_ts > order_estimated_delivery) for "late deliveries", or (is_new_customer) for
   "new customers") plus comparison_segment_label (e.g. "late vs on-time delivery"). The metric Y is
   then compared ACROSS that segment. Do NOT analyse Y as a weekly/monthly trend: the condition X may
   hold in EVERY period, so a time series is structurally blind to the relationship.
   TWO SIDES RULE (critical): X and Y must be DIFFERENT columns. If the condition you would write for
   X uses a column metric_sql already reads, you have written the metric twice — leave
   comparison_segment_sql EMPTY. Grouping a metric by its own definition returns 100% and 0% no
   matter what the data holds, which answers nothing.
   NAME BOTH SIDES: whenever the question asks how two things relate — including "is there a
   correlation between A and B" — also populate relationship_left_sql and relationship_right_sql with
   the COLUMN each side refers to (a bare column name, or the arithmetic that measures it, e.g.
   `"Days for shipping (real)" - "Days for shipment (scheduled)"`), plus a short human label for each.
   These are the two sides of the relationship, not a metric and a filter: fill them even when the
   two sides are of different kinds (a measured quantity against a category is a valid pair, and so is
   a category against a category). Resolve the user's words to the schema's columns — "shipping delay"
   means the measured delay.
   ONE CONCEPT, SEVERAL COLUMNS: a schema usually spreads a concept like "customer location" across
   city, state, country and region, and testing only one of them answers a narrower question than the
   user asked — country has two values and can hide everything city would show. Put that side on the
   RIGHT: name the most specific column in relationship_right_sql and list the others (most specific
   first, up to 3) in relationship_right_alternatives. Each is tested and the strongest is reported.
   INTERVENTION (rare, and only when real): set intervention_column ONLY when the data records an
   assignment somebody APPLIED — a treatment arm, an A/B variant, a deliberately assigned campaign
   flag, a policy switched on from a date. A column that merely moves with the outcome is not an
   intervention, and naming one that isn't grants the report causal language it has not earned.
   When in doubt leave it empty: the analysis still runs, and it reports a relationship instead of
   a cause.

3. COMPARISON BASIS — What is the baseline for comparison?
   Default: both PoP (prior period of same length) AND YoY (same period prior year).
   CRITICAL — every comparison window MUST contain data. Read the PROFILE CONTEXT date range
   (e.g. "2024-05-01 → 2024-05-31") and period count FIRST:
   - PoP guard: the prior period must fall INSIDE the data's date range. If the prior period is
     before the earliest date (e.g. data starts 2024-05-01 but PoP would need April 2024), there
     is NO prior-period data — do NOT invent it. Either pick the most recent PRIOR period that
     actually has data, or leave comparison_start/comparison_end EMPTY ("") and state in
     intake_notes "no prior period available — only N period(s) of data". NEVER set the
     comparison equal to the observation window: a period compared against itself is a
     tautology, not a baseline.
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
    the data.
    State whether the observed change is statistically significant.
    If a business calendar event may explain the anomaly, note it.
  - key_numbers: the 1–3 most important values (label, value, delta, context)
  - chart_type: "line" for time series, "bar" for comparisons, "pareto" for concentration
    (one categorical + one measure where a few categories drive most of the total — 80/20),
    "none" for single-value outputs
  - stat_note: if z-score is available, format as "z = X.X — [significant/within normal range]"
  - is_significant: true ONLY when the change is BOTH statistically significant (|z| > {z_threshold})
    AND practically material (absolute change ≥ {pct_threshold}% of the prior-period value). A large
    z-score is NOT enough on its own: at high row counts (tens or hundreds of thousands of rows) even a
    trivial 0.1–0.3pp difference produces a huge z (e.g. z = 150). That is statistical noise dressed as
    a signal — set is_significant=false and say the difference is negligible / not material. Never call a
    sub-1% relative change a "trend", "driver", or "significant" because its z-score is large.

phase_summary: one sentence that leads with the key number — the most important finding from this phase.
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

Write clear, number-anchored interpretations. Cite values from the data. Use NO markdown emphasis — no bold, no italics.
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

BASELINE GUARD (read FIRST): contribution / abs_change is a real "driver of the change" ONLY when
the prior-period comparison values are present. If the comparison column (comp_*, *_prior, yoy_*) is
NULL / empty / 0 for the rows, there is NO measured change — abs_change has collapsed to the current
LEVEL, and any "contribution_pct" is a share of the current total, NOT of a decline. In that case you
MUST NOT name a "primary driver", MUST NOT raise a "severity alert", and MUST NOT claim "X% of the
decline came from" any value. Say plainly that segment-level attribution is impossible without a
baseline, and report only the current-period levels. Do this even if a contribution_pct column exists.

For each dimension analysed (ONLY when a real baseline is present), interpret the contribution analysis:
  - Which dimension value(s) account for > 30% of the total change? (primary drivers)
  - Is the decline concentrated (1–2 values driving 60%+ of change) or diffuse (uniform across all)?
  - Any dimension where one value has > 50% relative decline, even if small absolute? (severity alert)

Write dimension-by-dimension findings with specific numbers. Use NO markdown emphasis.
Highlight the SINGLE most actionable finding across all dimensions.
phase_summary: when a baseline exists and concentration exists, "**X%** of the total decline came from
[dimension: value]" (bold the share); when the baseline is missing, state that no prior-period data is
available so the late-period change cannot be attributed to any segment.
"""

# ── Cross-sectional weakness scan (non-temporal diagnostic) ───────────────────

CROSS_SECTION_PLAN_PROMPT = """\
DIAGNOSTIC QUESTION: "{question}"

This is a CROSS-SECTIONAL question — "where / which is weakest", "where are we losing money".
There is NO useful time axis; do NOT compare periods. Instead rank the metric across each
dimension to find WHERE value is lowest or most concentrated.
{comparison_segment_section}{premise_check_section}
METRIC: {metric_label} → {metric_sql}
PRIMARY TABLE: {metric_table}

SCHEMA:
{schema}

DIMENSIONS (categorical columns to slice by, priority order):
{dimensions_list}

Write 1 SQL query per dimension (up to 5). Each query MUST:
{metric_computation_block}

SQL RULES: DuckDB. NULLIF before every division. Use table names EXACTLY as in SCHEMA. If the
dimension lives in another table, JOIN to reach it (use DISTINCT or a pre-aggregated subquery so a
one-to-many join does NOT fan out and multiply the metric). NO date filters and NO status/price/other
filters — every row counts. SELECT the dimension column FIRST, aliased with the dimension's OWN name
(e.g. channel, region, product, currency) — never a generic alias like "dimension_value"; that label
becomes the chart axis. metric_total comes SECOND. chart_type: "bar_horizontal".
"""

# The metric-computation steps are branched by metric KIND. An ADDITIVE metric (a plain
# SUM/COUNT) can be totalled, averaged-per-record and shared-of-total. A RATIO/percentage
# metric (SUM(num)/SUM(den), AVG, anything *100) CANNOT — summing a ratio or dividing it by
# COUNT(*) is nonsense, which is exactly what the additive template used to make the coder do
# (it silently dropped the denominator and reported SUM(numerator) as the metric). ada_cross_section
# selects the block; the additive block is byte-for-byte the historical instructions.
CROSS_SECTION_ADDITIVE_BLOCK = """\
  1. GROUP BY the dimension value.
  2. Compute the metric ({metric_sql}) per value AS metric_total, plus COUNT(*) AS n.
  3. Compute the AVERAGE per record: ROUND(<metric> / NULLIF(COUNT(*), 0), 2) AS avg_per_record.
     This separates per-unit weakness from sheer volume — a value can be small in total yet
     efficient per record (high average), or large in total yet inefficient (low average).
  4. Compute each value's share of the metric total:
     ROUND(100.0 * <metric> / NULLIF(SUM(<metric>) OVER (), 0), 1) AS pct_of_total
  5. ORDER BY metric_total ASC (weakest first) so the worst performers surface.
  6. LIMIT 15."""

CROSS_SECTION_RATIO_BLOCK = """\
  1. GROUP BY the dimension value.
  2. Compute the metric per value DIRECTLY as the ratio, SELECTED VERBATIM:
       {metric_sql} AS metric_total
     This metric is a RATIO / percentage / per-unit rate, NOT an additive total. It is built from
     numerator/denominator aggregates (e.g. SUM(num)/NULLIF(SUM(den),0)); adding GROUP BY re-computes
     the correct ratio WITHIN each group automatically. Keep the numerator AND denominator aggregates
     EXACTLY as written — do NOT replace the metric with SUM(numerator) alone, do NOT drop the
     denominator, and do NOT divide the ratio by COUNT(*). The WHOLE expression above is metric_total.
  3. Also SELECT COUNT(*) AS n and the raw building blocks so the ratio is auditable: the numerator
     aggregate AS numerator_total and the denominator aggregate AS denominator_total (the same
     numerator/denominator that appear INSIDE the metric expression).
  4. Do NOT compute avg_per_record (a ratio has no per-record average) and do NOT compute a
     share-of-total (you cannot meaningfully SUM a ratio across groups).
  5. ORDER BY metric_total ASC (lowest ratio first) so the extremes surface.
  6. LIMIT 15."""

# A bare AVG/MEAN/MEDIAN is a per-record average — non-additive like a ratio, but UNLIKE a
# composite ratio (SUM(num)/SUM(den), *100) it is SELF-CONTAINED: the AVG re-computes correctly
# within each GROUP BY on its own. Expanding it into numerator_total/denominator_total columns is
# pure noise for the reader (and was the source of the "why is SUM/COUNT in my AOV query?" gripe),
# so this block keeps the SELECT to just the dimension + the average + a row count.
CROSS_SECTION_AVG_BLOCK = """\
  1. GROUP BY the dimension value.
  2. Compute the metric ({metric_sql}) per value AS metric_total. This is a per-record AVERAGE and
     is already correct within each group — do NOT expand it into separate numerator/denominator
     columns, do NOT replace it with SUM(...), and do NOT divide it by COUNT(*). The AVG stands alone.
  3. Also SELECT COUNT(*) AS n — the number of records behind each group's average — AND the
     within-group spread as STDDEV_SAMP(<the same expression the AVG averages>) AS sd. Two group
     averages cannot be compared without both: a group of 3 records sits at the top of a ranking on
     noise alone, and the spread inside each group is what says whether the gap between them is real.
  4. Do NOT compute avg_per_record (the metric is already an average) and do NOT compute a
     share-of-total (you cannot meaningfully SUM an average across groups).
  5. ORDER BY metric_total ASC (weakest first) so the lowest averages surface.
  6. LIMIT 15."""

CROSS_SECTION_INTERPRET_PROMPT = """\
DIAGNOSTIC QUESTION: "{question}"
METRIC: {metric_label}
PHASE: Cross-Sectional Weakness Scan

QUERY RESULTS — each dimension value with its metric_total, avg_per_record, n, and
pct_of_total share:
{results_text}

{population_note}

For EACH dimension, write a finding:
  - title: the dimension (e.g. "By franchise", "By region", "By product"). Use the SAME
    dimension wording as the query so the card matches its chart.
  - interpretation: 2–3 tight sentences. Name the WEAKEST values by total AND read the
    AVERAGE: distinguish low TOTAL from low AVERAGE — a value can bill little in total yet be
    efficient per record, or look large yet be inefficient (low avg). Call out where the two
    lenses diverge (e.g. "11 franchises bill under $1,000; the worst, X, also averages just
    $4.20/order vs the ~$9 typical"). Use NO markdown emphasis.
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

# Ratio-metric variant: the metric is a percentage / rate / per-unit ratio, so metric_total must be
# read AS THAT RATIO (never as a dollar total or per-record average), and a LOW ratio is not
# automatically bad — direction depends on what the ratio measures (a low cost-% is GOOD).
CROSS_SECTION_RATIO_INTERPRET_PROMPT = """\
DIAGNOSTIC QUESTION: "{question}"
METRIC: {metric_label}  (this is a RATIO / percentage / rate — NOT a dollar total)
PHASE: Cross-Sectional Weakness Scan

QUERY RESULTS — each dimension value with its metric_total (the RATIO/percentage itself), n, and
the numerator_total / denominator_total it was built from:
{results_text}

{population_note}

For EACH dimension, write a finding:
  - title: the dimension (e.g. "By country", "By category"). Use the SAME dimension wording as the
    query so the card matches its chart.
  - interpretation: 2–3 tight sentences. The metric is a RATIO ({metric_label}); read metric_total
    AS THAT RATIO in its OWN units (%, rate, per-unit) — NEVER describe it as a dollar total or a
    per-order average. Name the values with the lowest and highest ratio. The numerator_total /
    denominator_total explain WHY a ratio is high or low (a low cost-ratio can come from a low
    numerator OR a large denominator). Use NO markdown emphasis. Cite real
    values only.
    DIRECTION + SEVERITY GROUNDING: "lowest in the ranking" is NOT "weak". For many ratios LOW is
    GOOD (a low cost-%, a low defect-rate, a low freight-%); for others HIGH is good. Judge direction
    by what the ratio MEASURES — do NOT assume the minimum is the problem. Only call a value
    'weak'/'a problem'/'underperforming' if it is clearly adverse versus a benchmark or a genuine
    outlier far from the rest. If the ratios are tightly clustered, say so and use relative language
    ("the lowest at **2.2%** vs the ~4.3% of the rest").
  - key_numbers: the 1–3 most telling values — include the ratio, and the numerator or denominator
    where it explains the result.
  - chart_type: "bar_horizontal".
  - is_significant: true ONLY when this dimension is clearly adverse vs a benchmark or a genuine
    outlier — not merely the minimum of a tight, healthy spread.

Be honest: if the ratios are evenly spread, say it is NOT a problem area. If the lowest ratio is the
FAVOURABLE direction, say so explicitly rather than framing it as a weakness.

phase_summary: one sentence naming where the ratio is highest/lowest and whether it actually matters
— lead with the decisive number (bold it) and the correct direction, e.g. "Freight runs **2.2%** of
order value in Germany vs ~4.3% elsewhere — the LOWEST cost ratio, a strength rather than a weakness."
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
phase_summary: "Behaviorally, [X]. Operationally, [Y]." — two-part finding, each part anchored on its own number.
"""

# ── Phase 6: Synthesis — attribution waterfall ────────────────────────────────

# PE-2: the per-call template carries ONLY what changes per call. The writing contract
# lives in the SYSTEM prompt (a stable prefix providers can cache); the field-level
# rules ride the response schema's own descriptions; and the correctness contracts the
# old 1,700-token instruction tail lectured about (signs, waterfall sums, grounding,
# question-addressed) are now VERIFIED by aughor/agent/report_checks.py after the model
# writes — one named-violation retry beats prophylaxis on every call. The specimen this
# dieted measured 45% static boilerplate against 22% evidence.
ADA_SYNTHESIZE_PROMPT = """\
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

Write the complete, honest investigation report.
"""


#: The whole writing contract, compressed to what a capable model needs stated once.
#: Lives in the SYSTEM prompt: stable across calls (cacheable prefix), and read before
#: the evidence rather than after 3,000 tokens of it.
SYNTHESIS_CORE_RULES = """REPORT RULES:
- headline: max 16 words, answering the question ASKED — a breakdown question gets its \
dimensional answer even when the overall change is normal variance.
- Every number is either quoted from FULL EVIDENCE or plain arithmetic over two evidence \
values (a change, a share, a difference). Never estimate — a figure no query returned and no \
arithmetic reaches is described qualitatively, never manufactured.
- If the evidence does not explain WHY, say "the data analysed does not reveal the \
cause" and name what to check next. A negligible spread is negligible — say so; never \
present a tiny sub-segment reversal as the driver.
- Signs: losses/declines NEGATIVE, gains POSITIVE, the same quantity never flips sign \
anywhere. Waterfall entries account for ~100% of the change (add "Unexplained / \
residual" if short); amount_label and pct_of_total share their sign.
- confidence: HIGH = phases converge, attribution ~complete · MEDIUM = cause found, \
gaps remain · LOW = evidence cannot discriminate.
- recommendations: for controllable causes and material gaps; at least one whenever a \
lever exists (a missing cost column is not a reason to go empty); prioritise metric \
targets in warning/critical.
- closing_summary: the bottom line that CLOSES the report, never a copy of \
executive_summary. data_gaps: hypotheses this schema cannot test. causal_links: only \
cause→effect pairs the evidence defends."""


#: The long-form register of the same rules, kept for BASELINE-tier models — the small
#: free models these paragraphs were originally written against, which demonstrably
#: fabricated shares and flipped signs without them. A capable model gets the short
#: contract above and the post-generation checks; a baseline model keeps the guidance.
#: (PE-2's tiering rule: prose that a stronger model makes unnecessary is a RESTRICTION
#: — scale it with the model; the CHECKS are verification and run for every tier.)
BASELINE_GUARDRAILS = """\
GROUNDING (critical): state a number ONLY if it appears in FULL EVIDENCE. This applies
especially to SHARES ("X% of total"): never divide two numbers yourself to manufacture a
percentage — if no query computed the share, say "a small share" / "the largest
contributor" instead. Drop a number you cannot find above rather than approximating it.

MATERIALITY: before asserting a "driver" or cause, confirm it is MATERIAL. If the values
cluster within a couple of percent, say "the difference is negligible" — do NOT slice
into ever-finer sub-segments for a cherry-picked reversal. At high row counts a sub-1%
change is statistically significant and practically meaningless: not a trend, not a
driver; cap confidence at MEDIUM.

SIGN CONVENTION: total_change_label is signed by the overall direction ("-$330K" decline,
"+$120K" growth); each waterfall entry's amount_label and pct_of_total share ONE sign
(down-pushers negative, offsets positive); the signed contributions net to the direction
of total_change_label."""

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
    no_prior_period: bool = Field(default=False, description="True when the data holds NO period before the observation window to compare against (set by code from the real date coverage; leave False).")
    yoy_start: Optional[str] = Field(default=None, description="YoY comparison start, or null if data < 13 months")
    yoy_end: Optional[str] = Field(default=None)
    date_column: str = Field(description="Fully qualified: table.column")
    metric_table: str
    dimensions: list[str] = Field(description="List of 'table.column' pairs available for drill-down")
    cross_sectional: bool = Field(default=False, description="True when the question asks where/which/what is weakest / losing money / underperforming, OR the data has too few periods for a trend, OR it is a DRIVER question (does X affect/relate to/drive Y) — analyse across DIMENSIONS/SEGMENTS, not time.")
    metric_is_ratio: bool = Field(default=False, description="True when metric_sql is a RATIO / percentage / rate / per-unit average rather than a plain additive total — i.e. it divides one aggregate by another (SUM(a)/SUM(b)), scales by *100, or is an AVG / per-record mean. Such a metric must NOT be summed across groups or divided by COUNT(*); it is re-aggregated per group as numerator/denominator. False for plain SUM/COUNT totals.")
    comparison_segment_sql: str = Field(default="", description="For a DRIVER question (does X lower/raise/affect/relate-to Y), the boolean/CASE SQL expression defining the contrasted condition X — e.g. (order_delivered_ts > order_estimated_delivery) for 'late deliveries', or (is_new_customer) for 'new vs returning'. Empty for non-driver questions.")
    comparison_segment_label: str = Field(default="", description="Human label for comparison_segment_sql, e.g. 'late vs on-time delivery'. Empty when comparison_segment_sql is empty.")
    relationship_left_sql: str = Field(default="", description="For a RELATIONSHIP question (how do A and B relate / is there a correlation between A and B), the column — or the arithmetic measuring it — for the FIRST side, e.g. '\"Days for shipping (real)\" - \"Days for shipment (scheduled)\"' for 'shipping delay'. NOT an aggregate: no SUM/AVG/COUNT. Empty for non-relationship questions.")
    relationship_left_label: str = Field(default="", description="Short human label for relationship_left_sql, e.g. 'shipping delay (days)'.")
    relationship_right_sql: str = Field(default="", description="The SECOND side of the relationship, same rules as relationship_left_sql — e.g. 'Customer State' for 'customer location'. Must be a DIFFERENT column from relationship_left_sql.")
    relationship_right_label: str = Field(default="", description="Short human label for relationship_right_sql, e.g. 'customer state'.")
    relationship_right_alternatives: list[str] = Field(default_factory=list, description="Other columns carrying the SAME concept as relationship_right_sql, when the schema spreads it across several — e.g. for 'customer location': ['Customer City', 'Customer Country', 'Order Region']. Most specific first, up to 3. Each is tested and the strongest relationship is reported. Empty when one column carries the concept.")
    intervention_column: str = Field(default="", description="A column recording an INTERVENTION or ASSIGNMENT that was applied to units — a treatment arm, an A/B variant, a campaign flag deliberately assigned, a policy applied from a date. This is what makes a causal contrast identifiable. Empty unless the data genuinely records an assignment; a column that merely correlates with an outcome is NOT an intervention.")
    claim_type_suggestion: str = Field(default="", description="Optional: the weakest claim this question needs — one of 'descriptive', 'associational', 'predictive'. Never 'causal'; a causal licence comes from the design, not from this field. Leave empty unless the question is clearly weaker than the design allows.")
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
    chart_type: Literal["auto", "magnitude", "trend", "identity", "change", "share", "distribution", "relation", "histogram", "boxplot", "counter", "funnel", "waterfall", "sankey", "small_multiples", "line_forecast", "gantt", "choropleth", "point_map", "treemap", "heatmap", "none"] = "auto"
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
    claim: Optional[str] = Field(
        default=None,
        description=(
            "The one-sentence CLAIM this exhibit demonstrates — it becomes the chart's "
            "title ('APAC drove the November dip', never 'Revenue by region'). State "
            "the finding with its direction; the query's descriptive name stays on "
            "`title` and moves to the source affordance."
        ),
    )
    interpretation: str
    key_numbers: list[PhaseKeyNumberModel] = Field(default_factory=list)
    chart_type: Literal["auto", "magnitude", "trend", "identity", "change", "share", "distribution", "relation", "histogram", "boxplot", "counter", "funnel", "waterfall", "sankey", "small_multiples", "line_forecast", "gantt", "choropleth", "point_map", "treemap", "heatmap", "none"] = "auto"
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


class AnswerRecommendationModel(BaseModel):
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
    closing_summary: str = Field(
        default="",
        description="A 1-2 sentence BOTTOM LINE that CLOSES the report — the single most "
        "important takeaway and its implication for the business. Distinct from "
        "executive_summary (which OPENS the report); do not copy it verbatim. Plain prose.",
    )
    total_change_label: str
    attribution_waterfall: list[WaterfallEntryModel]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    confidence_justification: str
    recommendations: list[AnswerRecommendationModel]
    data_gaps: list[str] = Field(default_factory=list)
    causal_links: list[CausalLinkModel] = Field(
        default_factory=list,
        description="Directional cause→effect pairs identified in this investigation. Only include links with clear evidence.",
    )


# R16 P2 — the argument-style writing contract.
# Distilled from the report-style study (docs/REPORT_STYLE_STUDY_2026-07-16.md):
# the strongest analyst reports ARGUE in prose — a verdict first, numbers bold
# inline in sentences, entities named by their identifiers, causes hedged
# honestly. Always appended to the synthesis system prompt.
ARGUMENT_STYLE_ADDENDUM = """WRITING STYLE — argue like an analyst, not a dashboard:
- Every figure that matters appears **bold inline** in a sentence ("operates at **74.5%** capacity vs **77.2%** on short-haul"). Never assume the UI will surface a number for you.
- Name entities by their identifier exactly as they appear in the data (route GVA-DEL, customer CU0036204). When ranking, list at most three as compact bullets: "**GVA-DEL**: 65.2% load factor (168K CHF per flight)".
- executive_summary: the verdict sentence FIRST, then one sentence per major claim, each carrying its own bolded number. 3-5 sentences total — length discipline is credibility.
- recommendations: imperative verb + **bold lever**, one line each; quantify expected_impact when the evidence supports a number, otherwise omit the number rather than invent one.
- Causes are hypotheses until proven: hedge honestly ("likely", "consistent with", "operationally impossible → points to a data-quality issue"). Never present a hypothesis as a finding."""


def synthesis_system_prompt() -> str:
    """The narrator's system prompt. R16 P2: the argument-style writing contract
    above is appended, so the prose argues like an analyst instead of pointing at a
    dashboard. Lives here (not investigate.py) both because it is a prompt and
    because module-level functions in investigate.py are auto-wrapped by the
    node-span instrumentation, which expects a `state` argument."""
    base = (
        "You are a senior data analyst writing a board-level investigation report. "
        "Every number must trace to the evidence log. No fabrication. "
        "Be definitive where evidence is strong; honest about uncertainty where it isn't."
    )
    parts = [base, ARGUMENT_STYLE_ADDENDUM, SYNTHESIS_CORE_RULES]
    # PE-2 tiering: the long-form guardrails ride along only for BASELINE-tier
    # narrators. Fail to the conservative register — an unresolvable binding means a
    # bare harness or broken config, exactly where the verbose guidance is safest.
    try:
        from aughor.llm.profile import profile_for
        capable = profile_for("narrator").capable
    except Exception:
        capable = False
    if not capable:
        parts.append(BASELINE_GUARDRAILS)
    return "\n\n".join(parts)
