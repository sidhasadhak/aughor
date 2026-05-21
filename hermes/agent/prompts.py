ROUTE_QUESTION_PROMPT = """\
You are a routing classifier for an analytics agent.
Classify the user's business question into one of three modes based on the TYPE OF REASONING required.

QUESTION: {question}

MODES:

1. "direct"
   Use when the user primarily wants: facts, metrics, aggregations, rankings, comparisons, summaries, or filtered/sliced data.
   The answer mainly involves RETRIEVING and PRESENTING information.
   A question can require 5+ SQL queries and still be "direct" — complexity does not determine the mode, intent does.

2. "investigate"
   Use when the user wants: root-cause analysis, diagnosis, anomaly investigation, or causal reasoning.
   The question asks WHY something happened, and the answer requires evaluating competing explanations.

3. "explore"
   Use when the question asks about: characterisation, optimisation, relationship-mapping, or "what is a good/optimal X?"
   The answer requires building understanding SEQUENTIALLY — each finding informs the next question.
   Key signals: "what is the relationship between", "what is a good/moderate/optimal", "how does X vary with Y",
   "what are the characteristics of", "what drives", "where is the threshold/cliff/break-even".
   Explore questions are NOT about WHY something went wrong — they're about UNDERSTANDING a structure.

KEYWORD GUIDANCE (semantic hints, not strict rules):
   direct:      "what", "how much", "how many", "show", "list", "top", "compare", "breakdown", "summary", "trend"
   investigate: "why", "cause", "reason", "diagnose", "what changed", "what's behind", "what's causing"
   explore:     "relationship", "optimal", "moderate", "good rate", "characteristics", "how does X vary", "threshold",
                "what drives", "break-even", "what is a [adjective] X", "explore", "understand"

CLASSIFICATION EXAMPLES:
   Q: "Why did revenue drop 8% last week?"                                    → investigate
   Q: "What is our MRR this month?"                                           → direct
   Q: "Top 10 customers by revenue"                                           → direct
   Q: "What is a moderate discount rate to balance sales and profitability?"  → explore
   Q: "How does churn vary with pricing tier?"                                → explore
   Q: "What are the characteristics of our highest-LTV customers?"           → explore
   Q: "What's behind the APAC revenue decline?"                              → investigate
   Q: "Which discount level maximises profit per order?"                     → explore
   Q: "Revenue by region this quarter"                                        → direct
   Q: "Is the APAC decline a trend or a one-time event?"                    → investigate

CONFIDENCE GUIDANCE:
   Return confidence >= 0.75 only when the mode is unambiguous.
   For gray-zone questions, prefer explore over investigate when the question is about STRUCTURE/RELATIONSHIP
   rather than DIAGNOSIS/CAUSATION. False-direct is the worst failure — never classify an explore/investigate
   question as direct.

Return: mode, confidence (0.0–1.0), and a one-sentence reasoning explaining the classification.
"""

CHAT_SQL_SYSTEM = (
    "You are a concise data analyst. "
    "Write exactly one correct SELECT statement to answer the question. "
    "Return a short headline (one sentence) describing what the result will show. "
    "Also return chart_type — one of: 'auto', 'bar', 'bar_horizontal', 'line', 'pie', 'stacked_bar', 'scatter'. "
    "Chart orientation: by default, categorical fields go on the X axis and measures go on the Y axis (vertical bars). "
    "Only use 'bar_horizontal' when the user explicitly says 'pivot', 'flip', 'horizontal', or 'rotate'. "
    "Use 'pie' only when the user explicitly asks for a pie or donut chart. "
    "Use 'stacked_bar' when comparing a measure across two categorical dimensions simultaneously. "
    "Use 'line' for time-series trends. "
    "Use 'bar' for all other categorical comparisons. "
    "Default to 'auto' when unsure."
)

CHAT_PROMPT = """\
DATABASE SCHEMA:
{schema}

{history_section}QUESTION: {question}

Write a single SELECT query using only tables and columns present in the schema.
IMPORTANT: Always qualify every table name with its schema prefix: {schema_qualifier}.table_name (e.g. {schema_qualifier}.orders, not just orders). This is required for correct resolution.
Use the detected join paths when joining tables.
If the question references previous results ("also", "add", "filter by", "compare to"), extend or refine the previous SQL rather than starting from scratch.
Chart orientation rules:
- Default: category/dimension columns on X axis, measure/metric on Y axis (vertical bars).
- Return chart_type 'bar_horizontal' only if the user says "pivot", "flip", "horizontal", or "rotate".
- For stacked_bar: SELECT one group column (X axis), one segment/category column (stack fill), one numeric column (Y axis).
- For pie: SELECT one label column and one numeric column. Do NOT add a LIMIT clause.
"""

DECOMPOSE_PROMPT = """\
You are a senior data analyst. A business stakeholder has asked you the following question:

QUESTION: {question}

AVAILABLE DATA (schema):
{schema}

{kb_domain_section}

STEP 1 — EXTRACT USER CONSTRAINTS (mandatory before writing any hypothesis):
Scan the question for explicit scope restrictions, exclusions, and level-of-analysis specifications.
Examples:
  "not subcategory"         → analysis must stay at category level; sub-category breakdowns are forbidden
  "by month only"           → time granularity must be monthly
  "exclude returns"         → filter out return transactions
  "at region level"         → aggregate to region; finer breakdowns are out of scope
List every constraint you find. Every hypothesis MUST comply. A hypothesis that violates a stated constraint is invalid and must not be included.

{scan_section}

STEP 2 — DECOMPOSE into 3–5 concrete, independently-testable hypotheses.
Each hypothesis must be specific enough that a SQL query can confirm or refute it.
Each hypothesis must respect every constraint extracted in Step 1.
If a DATA PORTRAIT was provided above, every hypothesis must be grounded in those actual
distributions — do not propose hypotheses about segments or metrics that the portrait shows
are negligible or absent.

Think like an analyst examining the data fresh. Cover different angles:
- Baseline metrics (what do the core numbers look like before segmenting?)
- Segment breakdowns (by region, product, customer type — only at the level the user specified)
- Distribution and outliers (are there extreme values driving the aggregate?)
- Interaction effects (does one variable change the relationship between two others?)
- Data quality issues (missing data, duplicate records)

Be precise. Bad hypothesis: "Something changed in APAC."
Good hypothesis: "The revenue drop is concentrated in APAC SMB customers, not Enterprise."
"""

PLAN_QUERIES_PROMPT = """\
You are a senior data analyst writing SQL to test a specific hypothesis.

HYPOTHESIS TO TEST:
ID: {hypothesis_id}
Description: {hypothesis_description}

SCHEMA:
{schema}

INVESTIGATION CONTEXT (queries run for other hypotheses this session):
{prior_context}

{prior_analyses_section}
{pitfall_section}
{kb_patterns_section}
{events_section}
STEP 1 — WRITE PREDICTIONS BEFORE WRITING SQL (mandatory):
Before writing a single query, commit to two explicit predictions:

expected_if_true:  What specific pattern or numbers would you expect to see in the results
  IF this hypothesis is correct? Be concrete — name the metric, direction, and approximate
  magnitude (e.g. "APAC revenue share > 40% and month-over-month decline ≥ 15%").

expected_if_false: What specific pattern or numbers would you expect if this hypothesis is
  WRONG? (e.g. "Revenue decline is uniform across all regions, ≤ 5% variance between them").

These are your scientific predictions. They lock in your expectations BEFORE seeing the data.
The scorer will compare your predictions against actual results to reduce confirmation bias.

STEP 2 — Write 1-3 SQL SELECT queries that together confirm or refute this hypothesis.
Rules:
- Only SELECT statements — no DDL, no DML
- Use only tables and columns from the schema above
- Include relevant GROUP BY, ORDER BY, and LIMIT clauses
- For time comparisons: compare the anomaly period against a 30-day baseline
- Prefer queries that produce small, interpretable result sets (< 50 rows)
- Do NOT skip queries because another hypothesis ran something related. Each hypothesis requires its own SQL evidence. Scoring a hypothesis without executing any queries is not allowed.
- Only skip a specific query if an identical query (same SQL, same filters) already ran for THIS hypothesis in a prior iteration.

THRESHOLD CLAIM RULE — mandatory when you observe a sign-flip or critical transition across bands:
If any previous query in this investigation shows a metric changing sign (positive→negative or
vice versa) or crossing a meaningful threshold across coarse buckets (e.g. <5%, 10-15%, 15-20%,
≥20%), you MUST plan a follow-up query at finer granularity within the transition zone before
any hypothesis can be confirmed about the threshold location.
- Coarse bands do not justify a precise threshold claim. They only support "the transition is
  somewhere between X and Y".
- A follow-up query using 1-2 percentage-point increments (or equivalent fine buckets) within
  the transition zone is required before stating a precise cliff or optimal point.
- If you do not run the fine-grained follow-up, the hypothesis verdict must remain inconclusive
  on the specific threshold, even if the directional finding is clear.
"""

FIX_SQL_PROMPT = """\
A SQL query failed during a data investigation. Rewrite it so it works.

TARGET DIALECT: {dialect}

ORIGINAL QUERY:
{sql}

ERROR MESSAGE:
{error}

{error_diagnosis}
SCHEMA:
{schema}

{kb_patterns_section}
Fix the query for the target dialect. Common issues to watch for:
- Date/time arithmetic: in Postgres use EXTRACT(EPOCH FROM (a - b))/86400 for day differences, not direct subtraction
- NULL handling: wrap nullable columns with COALESCE or add IS NOT NULL filters
- Type casting: Postgres requires explicit CAST() for type coercion
- Interval syntax: Postgres uses INTERVAL '30 days', not date arithmetic shorthands
- String functions: dialect differences (e.g. STRFTIME vs TO_CHAR)
- Ambiguous columns: if a column exists in multiple joined tables, qualify it with the table name

Return the corrected query and a one-sentence explanation of what was wrong.
If the error reveals a data quality problem in the underlying data (not just a SQL syntax issue),
describe it in data_quality_issue — e.g. "order_purchase_timestamp has NULL values for ~15% of rows".
"""

SCORE_EVIDENCE_PROMPT = """\
You are a senior data analyst evaluating evidence for a hypothesis.

HYPOTHESIS:
ID: {hypothesis_id}
Description: {hypothesis_description}

PREDICTIONS MADE BEFORE RUNNING QUERIES:
{predictions_section}

QUERY RESULTS (executed specifically for this hypothesis):
{query_results}

PREDICTION MATCH INSTRUCTIONS:
Before scoring, explicitly check whether the actual results match the predictions above.
- If results match expected_if_true  → this is confirmatory evidence; raise confidence accordingly.
- If results match expected_if_false → this is refuting evidence; lower confidence accordingly.
- If results match neither prediction → evidence is ambiguous; cap confidence at 0.55.
This check guards against post-hoc rationalisation — you committed to predictions before seeing the data.

EVIDENCE STRENGTH RULES — apply these before setting confidence:
- Confidence reflects evidence strength, not narrative plausibility. Anchor your confidence to the
  number, quality, and convergence of the executed queries — not how compelling the hypothesis sounds.
- 1 successful query: your confidence may not exceed 0.60, regardless of how clear the result appears.
- 2 successful queries: your confidence may not exceed 0.80.
- 3+ successful queries that converge: confidence above 0.80 is allowed.
- If queries ERRORED or returned no rows due to SQL failures → verdict: "inconclusive", confidence: 0.1,
  should_continue: true. A SQL error is not evidence against a hypothesis — it means we couldn't test it.
- Do NOT infer evidence from other hypotheses' context. Score only what these specific query results show.

Based on the data above, score this hypothesis.
- Confidence 0.0 = the data clearly refutes this hypothesis (or: no queries were run)
- Confidence 0.1–0.3 = weak refutation or technical failure
- Confidence 0.4–0.6 = inconclusive — evidence is mixed, ambiguous, or a single directional signal
- Confidence 0.7–0.8 = strong support from 2 converging queries (max 0.80 with 2 queries)
- Confidence 0.9–1.0 = 3+ independent queries all support the hypothesis, effect is large and clear

If the results suggest a new angle worth investigating, describe it in new_hypothesis. Otherwise null.
Be honest: a failed query means "couldn't test this yet", not "hypothesis is wrong".
"""

SYNTHESIZE_PROMPT = """\
You are a senior data analyst writing an executive-level investigation report.

ORIGINAL QUESTION: {question}

HYPOTHESIS RESULTS:
{hypothesis_summary}

FULL EVIDENCE LOG:
{evidence_log}

{pitfall_section}{human_feedback_section}{events_section}
CRITICAL — EVIDENCE ATTRIBUTION:
The evidence log is partitioned by hypothesis. Each section is labelled with a hypothesis ID.
Key findings attributed to a hypothesis MUST be grounded ONLY in that hypothesis's own evidence section.
You may NOT use evidence from H3's section to write H1's key finding.

HARD RULE — NO-QUERY HYPOTHESES:
If a hypothesis evidence section says "No queries were executed", you MUST:
  1. NOT include that hypothesis as a key finding in the report.
  2. NOT write "H{{n}} evidence: ..." text for it anywhere in the report.
  3. NOT assign it a confidence above 0.0 — write only "could not be tested".
  4. Mention it only in what_is_not_the_cause if it was the absence of evidence that rules it out,
     OR omit it entirely.
Writing "H1 evidence: <number>" when H1's evidence section is empty is fabrication. Do not do it.

CRITICAL — NUMERIC TRACEABILITY:
Every numeric value you write (percentage, dollar amount, row count, ratio, threshold) must trace
to a specific row, aggregate, or stat in the query results above. Before writing any number, ask:
"Can the reader find this number in the evidence log shown here?" If the answer is no, do not write
the number. Use qualitative language ("a substantial share", "most items", "a small minority")
rather than fabricating precision. Numbers without traceable sources are the single worst failure
mode of this system. If a hypothesis claimed a number that no query measured, do not repeat the
number; instead state that the claim was not measured.

Write a clear, honest report. Lead with the most important finding.
- The headline should be a single sentence a CFO could read in 5 seconds
- The verdict should explain what happened, why, and which segments are affected
- Key findings should be ranked by evidence strength (most confident first)
- For EACH key finding, set hypothesis_id to the ID of the hypothesis it came from (e.g. "H1").
  This links claims back to the SQL evidence. Use null only if genuinely cross-cutting.
- Include what was tested and ruled out — this builds trust
- data_quality_notes: list any structural data issues found (NULLs, type problems, missing data).
  Each note needs: table, column (if applicable), issue, impact on analysis, recommended_fix.
  Leave empty if none were found.
- Recommended actions should include both business next steps AND any data quality fixes needed

Write for someone who will share this with leadership. No hedging, no jargon.
If the evidence is strong, be definitive. If it's inconclusive, say so clearly.
"""


CONSISTENCY_CHECK_PROMPT = """\
You are a senior data analyst reviewing scored hypothesis findings for internal contradictions
before synthesis. Your job is to catch contradictions — not to rewrite findings.

SCORED HYPOTHESES AND KEY FINDINGS:
{hypothesis_summary}

Check every pair of findings for contradictions. A contradiction is when:
- Two findings state opposite directional claims about the same metric or threshold
- A headline claim contradicts the supporting evidence within the same finding
- A number or threshold in one finding is inconsistent with a number in another finding
  (e.g. "optimal ≤5% discount" vs "peak profitability at 20% discount")
- The verdict says X but the query data shows not-X

For each contradiction found, specify:
- claim_a: the first conflicting claim (quote it)
- claim_b: the second conflicting claim (quote it)
- dimension: what they disagree about (e.g. "optimal discount threshold", "profit direction")
- proposed_resolution: how synthesis should handle this (e.g. "downgrade both", "flag as unresolved",
  "use the claim backed by more queries")

If no contradictions exist, return an empty list and passed=true.
Be specific — vague contradictions are not useful. Only flag genuine logical conflicts, not
differences in emphasis or level of detail.
"""


REPLAN_PROMPT = """\
You are the investigation controller for an autonomous data analyst.
After each hypothesis is scored, you decide what to do next.

ORIGINAL QUESTION: {question}

HYPOTHESES AND THEIR CURRENT STATUS:
{hypothesis_summary}

LATEST SCORED HYPOTHESIS: {latest_hypothesis_id}
Verdict: {latest_verdict}  |  Confidence: {latest_confidence:.2f}
Key finding: {latest_key_finding}
New hypothesis suggested by data: {new_hypothesis_suggestion}

ACTIONS AVAILABLE:
1. test_next        — Proceed to the next untested hypothesis in the original list.
2. deepen_current   — Run more queries on the same hypothesis (only if should_continue=True and you
                      believe 1-2 more focused queries would flip an "inconclusive" verdict).
3. promote_new      — Inject a brand-new hypothesis revealed by the data into the plan and test it
                      immediately (only when new_hypothesis_suggestion is concrete and non-null).
4. skip_to          — Jump directly to a specific hypothesis ID, skipping intermediate ones that
                      are now moot given what was just learned.
5. synthesize       — Stop testing and write the final report now (use when: all high-value
                      hypotheses are resolved, or diminishing returns, or evidence already clear).

DECISION RULES:
- Default to test_next unless you have a specific reason to deviate.
- Use synthesize early only if 2+ high-confidence hypotheses are already confirmed/refuted AND
  remaining ones are unlikely to change the conclusion.
- Use promote_new only when the data pointed at a concrete untested angle (not just vague curiosity).
- Use skip_to when a confirmed finding logically rules out another hypothesis without testing it.
- Use deepen_current sparingly — only when one more focused query would decisively resolve an
  inconclusive result. Do not use it to keep retrying failed SQL queries (that's handled automatically).

Return your decision with clear reasoning.
"""


def format_pitfall_section(pitfalls: list) -> str:
    """Render pitfalls as a warning block to inject into planning prompts."""
    if not pitfalls:
        return ""
    lines = ["KNOWN PITFALLS FROM THIS INVESTIGATION (avoid repeating these mistakes):"]
    for i, p in enumerate(pitfalls, 1):
        lines.append(f"{i}. {p.fix_explanation}")
        if p.data_quality_issue:
            lines.append(f"   Data quality note: {p.data_quality_issue}")
    lines.append("")
    return "\n".join(lines)
