ROUTE_QUESTION_PROMPT = """\
You are a routing classifier for an analytics agent.
Classify the user's business question into one of two modes based on the TYPE OF REASONING required — not on how many SQL queries it might take.

QUESTION: {question}

MODES:

1. "direct"
   Use when the user primarily wants: facts, metrics, aggregations, rankings, comparisons, summaries, or filtered/sliced data.
   The answer mainly involves RETRIEVING and PRESENTING information.
   A question can require 5+ SQL queries and complex joins and still be "direct" — complexity does not determine the mode, intent does.

2. "investigate"
   Use when the user wants: explanations, root-cause analysis, diagnosis, hypothesis testing, anomaly investigation, or causal reasoning.
   Use when the task requires interpreting WHY something happened, evaluating competing explanations, or identifying drivers behind an outcome.

KEYWORD GUIDANCE (semantic hints, not strict rules):
   Lean direct:      "what", "how much", "how many", "show", "list", "top", "compare", "breakdown", "summary", "trend"
   Lean investigate: "why", "cause", "driver", "reason", "explain", "diagnose", "investigate", "what changed", "what's behind", "what's causing"

BORDERLINE EXAMPLES:
   Q: "Compare churn across pricing tiers"            → direct      (comparison/reporting, not causal)
   Q: "Why is churn higher in enterprise?"            → investigate  (asks for explanation of cause)
   Q: "Activation funnel by week"                     → direct      (aggregation/slice)
   Q: "What changed in activation after the redesign?"→ investigate  (causal, implies anomaly)
   Q: "Revenue by region this quarter"                → direct      (aggregation/slice)
   Q: "What's behind the APAC revenue decline?"       → investigate  (diagnosis required)
   Q: "How are renewals doing this quarter?"          → direct      (retrieval/reporting)
   Q: "What's causing the renewal drop?"              → investigate  (root-cause)
   Q: "Which segment is underperforming?"             → investigate  (implies diagnosis, not just ranking)
   Q: "Top 10 customers by revenue"                   → direct      (ranking/retrieval)

CONFIDENCE GUIDANCE:
   Return confidence >= 0.75 only when the mode is unambiguous.
   For gray-zone questions, set confidence < 0.65 — the system will default to "investigate" when confidence is low.
   False-direct is worse than false-investigate: a missed hypothesis is recoverable, a shallow direct answer is not.

Return: mode, confidence (0.0–1.0), and a one-sentence reasoning explaining the classification.
"""

CHAT_SQL_SYSTEM = "You are a concise data analyst. Write exactly one correct SELECT statement to answer the question. Return a short headline (one sentence) describing what the result will show."

CHAT_PROMPT = """\
DATABASE SCHEMA:
{schema}

{history_section}QUESTION: {question}

Write a single SELECT query using only tables and columns present in the schema.
Use the detected join paths when joining tables.
If the question references previous results ("also", "add", "filter by", "compare to"), extend or refine the previous SQL rather than starting from scratch.
"""

DECOMPOSE_PROMPT = """\
You are a senior data analyst. A business stakeholder has asked you the following question:

QUESTION: {question}

AVAILABLE DATA (schema):
{schema}

{kb_domain_section}

Your job is to decompose this question into 3-5 concrete, independently-testable hypotheses.
Each hypothesis must be specific enough that a SQL query can confirm or refute it.

Think like an analyst: what are the most likely explanations? Cover different angles:
- Time-based patterns (seasonality, day-of-week effects)
- Segment breakdowns (by region, product, customer type)
- External events (outages, promotions, seasonality)
- Funnel/pipeline changes (conversion, churn, acquisition)
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

INVESTIGATION CONTEXT (queries already run this session):
{prior_context}

{prior_analyses_section}
{pitfall_section}
{kb_patterns_section}
Write 1-3 SQL SELECT queries that together confirm or refute this hypothesis.
Rules:
- Only SELECT statements — no DDL, no DML
- Use only tables and columns from the schema above
- Include relevant GROUP BY, ORDER BY, and LIMIT clauses
- For time comparisons: compare the anomaly period against a 30-day baseline
- Prefer queries that produce small, interpretable result sets (< 50 rows)
- Do not re-run queries that are already in the investigation context
- If a past investigation already answered this hypothesis conclusively, note it and skip redundant queries
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

QUERY RESULTS:
{query_results}

IMPORTANT DISTINCTION:
- If queries returned DATA that contradicts the hypothesis → verdict: "refuted", low confidence
- If queries returned DATA that supports the hypothesis → verdict: "confirmed", high confidence
- If queries ERRORED or returned no rows due to SQL failures → verdict: "inconclusive", confidence: 0.5,
  should_continue: true, key_finding: explain that queries failed technically, NOT that the hypothesis
  was disproven. A SQL error is not evidence against a hypothesis.

Based on the data above, score this hypothesis.
- Confidence 0.0 = the data clearly refutes this hypothesis
- Confidence 0.5 = inconclusive — data is mixed, or queries failed to execute
- Confidence 0.8+ = the data strongly supports this hypothesis
- Confidence 1.0 = fully confirmed, no doubt

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

{pitfall_section}{human_feedback_section}
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
