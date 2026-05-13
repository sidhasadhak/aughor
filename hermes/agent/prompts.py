DECOMPOSE_PROMPT = """\
You are a senior data analyst. A business stakeholder has asked you the following question:

QUESTION: {question}

AVAILABLE DATA (schema):
{schema}

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

INVESTIGATION CONTEXT (queries already run):
{prior_context}

{pitfall_section}
Write 1-3 SQL SELECT queries that together confirm or refute this hypothesis.
Rules:
- Only SELECT statements — no DDL, no DML
- Use only tables and columns from the schema above
- Include relevant GROUP BY, ORDER BY, and LIMIT clauses
- For time comparisons: compare the anomaly period against a 30-day baseline
- Prefer queries that produce small, interpretable result sets (< 50 rows)
- Do not re-run queries that are already in the investigation context
"""

FIX_SQL_PROMPT = """\
A SQL query failed during a data investigation. Rewrite it so it works.

TARGET DIALECT: {dialect}

ORIGINAL QUERY:
{sql}

ERROR MESSAGE:
{error}

SCHEMA:
{schema}

Fix the query for the target dialect. Common issues to watch for:
- Date/time arithmetic: in Postgres use EXTRACT(EPOCH FROM (a - b))/86400 for day differences, not direct subtraction
- NULL handling: wrap nullable columns with COALESCE or add IS NOT NULL filters
- Type casting: Postgres requires explicit CAST() for type coercion
- Interval syntax: Postgres uses INTERVAL '30 days', not date arithmetic shorthands
- String functions: dialect differences (e.g. STRFTIME vs TO_CHAR)

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

{pitfall_section}
Write a clear, honest report. Lead with the most important finding.
- The headline should be a single sentence a CFO could read in 5 seconds
- The verdict should explain what happened, why, and which segments are affected
- Key findings should be ranked by evidence strength (most confident first)
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
