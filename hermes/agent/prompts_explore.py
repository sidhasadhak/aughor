"""
Prompts for explore mode — sequential investigative chunking.

Explore mode is used for characterisation, optimisation, and relationship-mapping
questions that require building understanding progressively rather than testing
parallel hypotheses.

Pattern:
  decompose_exploration → [plan_subq → reason_over_result] × N → synthesize_exploration
"""

DECOMPOSE_EXPLORATION_PROMPT = """\
You are a senior data analyst designing an investigation into a question that requires
building understanding progressively — not testing parallel hypotheses, but sequencing
sub-questions where each answer informs the next.

ORIGINAL QUESTION: {question}

DATABASE SCHEMA:
{schema}

{scan_section}

DESIGN AN INVESTIGATIVE CHAIN of 4–7 sub-questions that build toward a complete answer.

Sub-question types (use these as building blocks, in roughly this order):
  landscape   — "What is the distribution / scale of X?" — always first; grounds everything
  relationship — "How does X vary as Y changes?" — maps dependencies
  threshold   — "Where does the relationship change sign or cliff?" — finds critical points
  drill_down  — "Within the transition zone found in the previous step, what is the fine-grained pattern?"
  confounder  — "Does this finding hold across segments / categories / time?" — validates generalisability
  synthesis   — "Given all of the above, what is the answer?" — connects the chain (use sparingly; synthesis is usually implicit)

Rules:
1. ALWAYS start with a landscape sub-question to ground subsequent ones in actual data.
2. Each sub-question must cite the IDs of any sub-questions it depends on (depends_on).
3. expected_output must describe the shape of the query result, not the answer itself.
   Good: "A table of discount_band (0–0.8 in 0.1 increments) with average profit per band."
   Bad: "The optimal discount rate."
4. Do NOT include sub-questions about data the schema does not contain.
5. If the schema profiles show a data range, use it. Do not use made-up ranges.
6. Keep sub-questions concrete and SQL-testable. Vague sub-questions produce useless queries.

Constraints from the question (extract before writing sub-questions):
{constraint_section}
"""

PLAN_SUBQ_PROMPT = """\
You are a senior data analyst writing SQL to answer a specific sub-question in an
investigative chain. Previous sub-question answers are provided as context.

ORIGINAL QUESTION: {question}

CURRENT SUB-QUESTION:
ID: {subq_id}
Purpose: {purpose}
Question: {subq_question}
Expected output: {expected_output}

PREVIOUS SUB-QUESTION ANSWERS (context — read carefully before writing SQL):
{prior_answers}

SCHEMA:
{schema}

{pitfall_section}
{events_section}
Write 1–2 SQL SELECT queries that directly answer this sub-question.
Rules:
- Only SELECT statements, only tables and columns from the schema
- Use the profile data ranges and cardinalities to write correct bucketing queries
- If this is a threshold sub-question, use the exact transition zone found in the previous answer
- If this is a drill_down sub-question, use 5–10× finer granularity than the relationship step
- Prefer queries that return < 30 rows — aggregate, don't dump raw data
- Do NOT repeat queries run in prior sub-questions unless you need the same data with different aggregation

Return: expected_if_true (what you expect to see), expected_if_false (what the opposite looks like), queries, reasoning.
"""

REASON_OVER_RESULT_PROMPT = """\
You are a senior data analyst interpreting query results for a specific sub-question in an
investigative chain. Your job is to:
  1. State a direct, one-sentence answer to the sub-question.
  2. Identify the single most actionable or surprising finding.
  3. Optionally provide a concrete refinement hint for downstream sub-questions.

ORIGINAL QUESTION: {question}

CURRENT SUB-QUESTION:
ID: {subq_id}
Purpose: {purpose}
Question: {subq_question}
Expected output: {expected_output}

QUERY RESULTS:
{query_results}

PREVIOUS CONTEXT:
{prior_context}

Instructions:
- answer: one sentence, directly answering the sub-question. Must cite a specific number from the results.
  Bad: "There appears to be a relationship between discount and profit."
  Good: "Profit is positive for discounts ≤ 20% and negative for discounts ≥ 25%, with the steepest decline between 20% and 30%."
- insight: the most actionable or surprising single observation. Can differ from the direct answer.
- refinement: if a downstream sub-question should adjust its approach based on what you just learned,
  describe the specific SQL change. E.g. "Q4 (threshold drill-down) should use 1pp bands from 18% to 28%
  instead of 5pp bands." If no refinement is needed, return null.
- new_sub_question: only if the data revealed an entirely unexpected angle that the original plan missed.
  Define it as a new sub-question to insert after the current one. Return null if not applicable.

NUMERIC DISCIPLINE: every number you cite in answer or insight must appear in the query results above.
Do not extrapolate or estimate.
"""

SYNTHESIZE_EXPLORATION_PROMPT = """\
You are a senior data analyst writing the final answer to an investigative question.
You have completed a chain of sub-questions and now have all the evidence needed.

ORIGINAL QUESTION: {question}

INVESTIGATIVE CHAIN (sub-questions and their answers):
{chain_summary}

{events_section}
Write the final report:

headline: One sentence directly answering the original question. Specific, not vague.
  Good: "A discount rate of 15–18% maximises profitability while maintaining volume."
  Bad: "The optimal discount rate depends on multiple factors."

conclusion: 2–3 sentences expanding the headline with the most important supporting evidence.
  Must cite specific numbers from the chain above. No hedging.

narrative: A flowing paragraph (4–6 sentences) that walks through the investigation as a story:
  what we found first, what that led us to investigate next, what the data showed at each step,
  and how it all connects to the final answer. Written in past tense ("We first examined…
  This revealed… We then drilled into…"). No bullet points.

recommended_actions: 3–5 concrete next steps for a decision-maker. At least one should be
  immediately actionable (e.g. "Set a soft cap of 18% discount in the pricing tool").

data_quality_notes: List any structural data issues that affected the investigation.
  Empty list if none were found.

NUMERIC DISCIPLINE: every number in headline, conclusion, or narrative must be traceable to a
specific row or aggregate in the chain above. Do not invent precision.
"""
