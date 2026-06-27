"""
Prompts for explore mode — sequential investigative chunking.

Explore mode is used for characterisation, optimisation, and relationship-mapping
questions that require building understanding progressively rather than testing
parallel hypotheses.

Pattern:
  decompose_exploration → [plan_subq → reason_over_result] × N → synthesize_exploration
"""

BUILD_LEDGER_PROMPT = """\
You are setting up the shared definitions for a data analysis so that every step
computes the same metrics the same way. Read the question and schema, then list the
canonical definitions the whole analysis must reuse.

QUESTION: {question}

SCHEMA (already annotated with any known column caveats):
{schema}

{scan_section}

Produce a SHORT ledger (max ~10 lines, no prose) with these parts:
- ENTITIES: for each entity the question involves, the EXACT column that uniquely
  identifies it. Watch for per-row hash IDs vs stable IDs (e.g. an order-level
  customer_id vs a stable customer_unique_id) — pick the stable identifier and say so.
- METRICS: the exact SQL expression for each metric the question needs
  (e.g. revenue = SUM(payment_value); unique customers = COUNT(DISTINCT customer_unique_id);
  average order value = SUM(payment_value) / COUNT(DISTINCT order_id)).
- SEGMENTS: any standard grouping/filter the question implies (e.g. primary payment
  method per customer = the payment_type of that customer's highest-value order).

Use only tables/columns that exist in the schema. If a concept is ambiguous, pick one
definition and state it explicitly. This ledger is binding for all later steps.
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

CANONICAL DEFINITIONS (this analysis's shared ledger — every step MUST use these
exact identifiers and metric definitions so figures stay consistent across steps):
{analysis_ledger}

PREVIOUS SUB-QUESTION ANSWERS (context — read carefully before writing SQL):
{prior_answers}

SCHEMA:
{schema}

{pitfall_section}
{events_section}
DATA PORTRAIT for this sub-question (discovered cardinalities, ranges, distinct values):
{data_portrait}

Write 1–2 SQL SELECT queries that directly answer this sub-question.
Rules:
- Only SELECT statements, only tables and columns from the schema
- IMPORTANT: use the exact table names as shown in the SCHEMA. When a table name includes a schema prefix (e.g. ecommerce.orders), use the full qualified name. When no schema prefix is shown, use the bare name.
- CONSISTENCY: use the canonical identifiers and metric definitions above verbatim
  (e.g. the same column for "unique customer", the same revenue expression). Never switch
  to a different identifier or definition than an earlier step used for the same concept.
- If a figure for this exact metric was already computed in a prior sub-question, reuse that
  result — do not recompute it with different SQL that could yield a slightly different number.
- Use the profile data ranges and cardinalities to write correct bucketing queries
- If this is a threshold sub-question, use the exact transition zone found in the previous answer
- If this is a drill_down sub-question, use 5–10× finer granularity than the relationship step
- Prefer queries that return < 30 rows — aggregate, don't dump raw data
- Do NOT repeat queries run in prior sub-questions unless you need the same data with different aggregation
- RATIO AGGREGATION: to aggregate a ratio / rate / per-unit metric across a group (e.g. stock-to-sales,
  cost %, conversion rate), use the RATIO OF SUMS — SUM(numerator) / NULLIF(SUM(denominator), 0) — NOT
  the AVERAGE of per-row ratios. AVG(per_sku_ratio) over-weights tiny-denominator rows and inflates the
  result (a SKU with 2 sold and 20 on hand reads 10×, dominating the mean); SUM(on_hand)/SUM(sold) is the
  true group ratio. Only average pre-computed ratios when each row already represents an equal-weight unit.

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

CANONICAL DEFINITIONS (shared ledger for this analysis):
{analysis_ledger}

PREVIOUS CONTEXT:
{prior_context}

Instructions:
- CONSISTENCY: when this sub-question references a metric already computed earlier (per the
  canonical definitions / previous context), cite the SAME figure verbatim — do not restate a
  freshly rounded or re-derived value.
- answer: one sentence, directly answering the sub-question. Must cite a specific number from the results.
  Bad: "There appears to be a relationship between discount and profit."
  Good: "Profit is positive for discounts ≤ 20% and negative for discounts ≥ 25%, with the steepest decline between 20% and 30%."
- insight: the most actionable or surprising single observation. Can differ from the direct answer.
- refinement: if a downstream sub-question should adjust its approach based on what you just learned,
  describe the specific SQL change. E.g. "Q4 (threshold drill-down) should use 1pp bands from 18% to 28%
  instead of 5pp bands." If no refinement is needed, return null.
- new_sub_question: only if the data revealed an entirely unexpected angle that the original plan missed.
  Define it as a new sub-question to insert after the current one. Return null if not applicable.

NUMERIC DISCIPLINE: every number you cite in answer or insight must appear VERBATIM in the query
results above. Do not extrapolate or estimate. Critically, do NOT compute your own derived values —
no ratios, per-unit figures ("per order"), percentages, growth rates, or differences unless that exact
value was returned as a column by the query. If a derived metric matters, it must come from SQL, never
from your own arithmetic (which is often wrong). Cite only what the query actually returned.
"""

DISTILL_PACK_DELTAS_PROMPT = """\
You are improving a domain-expert PACK from a completed, VERIFIED investigation it steered.
Propose ONLY concrete, durable improvements to the expert that THIS run revealed — either:
  • a schema caveat (a column-level gotcha an analyst must know to avoid a wrong result), or
  • a diagnostic question the expert should always ask on this kind of question.

Be conservative and specific. Return an EMPTY list if nothing durable was learned. Do NOT
restate the findings, recommendations, or generic advice — only pack-level learnings grounded
in what the data actually showed here.

PACK: {pack_id}

INVESTIGATION SUMMARY (the chain that just ran):
{chain_summary}

Return deltas: a list where each item has
  kind: "caveat" (a column gotcha) or "diagnostic" (a question to always ask),
  target: "table.column" for a caveat, "" for a diagnostic,
  content: one precise sentence.
"""


REFUTE_FINDING_PROMPT = """\
You are a SKEPTICAL senior analyst. Your ONLY job is to REFUTE the headline finding below —
find the single strongest reason it could be WRONG, given the evidence actually gathered.

Default to refuted=true when: the sample is small, an obvious confound is unaddressed, the
number could be a data artifact (e.g. a fan-out/cardinality issue, a single time period, a
single category value), the conclusion overclaims beyond what the queries measured, or the
"driver" is one cherry-picked cell among many comparisons. Be adversarial, not agreeable.

ORIGINAL QUESTION: {question}

HEADLINE FINDING (the claim to attack):
{conclusion}

EVIDENCE — the investigative chain that produced it:
{chain_summary}

Return:
- refuted: true if the finding does NOT hold up to scrutiny, false only if it is genuinely robust.
- reason: one sentence — the strongest specific objection (cite the weak point in the evidence).
- alternative: a plausible alternative explanation for the same data, or null.
"""


SYNTHESIZE_EXPLORATION_PROMPT = """\
You are a senior data analyst writing the final answer to an investigative question.
You have completed a chain of sub-questions and now have all the evidence needed.

ORIGINAL QUESTION: {question}

CANONICAL DEFINITIONS (shared ledger used throughout this analysis):
{analysis_ledger}

INVESTIGATIVE CHAIN (sub-questions and their answers):
{chain_summary}

{events_section}
Write the final report:

CONSISTENCY: every figure in the headline, conclusion, and narrative must match the exact
numbers already computed in the chain above. Do not recompute or re-estimate — reuse the
chain's figures verbatim so the report and the chain never disagree.


headline: One sentence directly answering the original question. Specific, not vague.
  Good: "A discount rate of 15–18% maximises profitability while maintaining volume."
  Bad: "The optimal discount rate depends on multiple factors."

conclusion: 2–3 sentences expanding the headline with the most important supporting evidence.
  Lead with the answer and wrap each decisive number in **double asterisks** for bold
  (e.g. **15–18%**, **$1.2M**). Must cite specific numbers from the chain above. No hedging.

narrative: A flowing paragraph (4–6 sentences) that walks through the investigation as a story:
  what we found first, what that led us to investigate next, what the data showed at each step,
  and how it all connects to the final answer. Written in past tense ("We first examined…
  This revealed… We then drilled into…"). No bullet points.

recommended_actions: 3–5 concrete next steps for a decision-maker. At least one should be
  immediately actionable (e.g. "Set a soft cap of 18% discount in the pricing tool").

data_quality_notes: List any structural data issues that affected the investigation.
  Empty list if none were found.

NUMERIC DISCIPLINE: every number in headline, conclusion, or narrative must be traceable to a
specific row or aggregate in the chain above. Do not invent precision. Do NOT compute your own
derived values — no ratios, "per X" figures, percentages, growth rates, or differences unless that
exact value was returned by a query in the chain. Your mental arithmetic is unreliable; cite only
figures the queries actually produced.

SCOPE HONESTY: answer ONLY the original question using the evidence in the chain. If the chain did
not actually measure something the question asks about (e.g. the question asks about conversion rates
but no conversion-rate query ran), say so plainly rather than substituting a different metric and
presenting it as the answer. Never write "given all of the above" if the chain is short or incomplete —
describe only what was genuinely investigated.

MATERIALITY: if the top-line difference the question asks about is negligible (e.g. new vs returning
order value differ by <1%, or the groups are effectively equal), the honest answer is "there is no
meaningful difference" — lead with that. Do NOT rescue a non-result by slicing into ever-finer
sub-segments (country × category × tenure) and reporting the single largest cell-level reversal as if
it were "the driver": those extremes are noise from many comparisons, not a signal. Only call something
a driver when it moves the OVERALL metric materially, and prefer the direction that holds across most
segments over a cherry-picked outlier.

RECOMMENDATION COHERENCE: recommended_actions must FOLLOW FROM the headline and never contradict it.
If the headline says a rate/metric is uniform (flat across segments), do NOT then recommend a
segment-specific intervention justified by that rate (e.g. "prioritise segment X to lower its rate") —
there is no rate lever when the rate is flat. Before writing each action, check it against the
headline; drop or rewrite any that assume a driver the analysis did not find.

VALUE LEVER (when the rate is flat but cost concentrates): a uniform rate means total cost is just
value × volume, so the only real levers are (a) reduce the per-unit amount (e.g. partial-refund tiers,
a non-refundable fare component) or (b) reduce the volume of exposed high-value units (fare rules). When
recommending these, SIZE the lever from chain figures (e.g. "a 20% non-refundable component on the
long-haul-business segment's **725,114 CHF** ≈ **145,000 CHF** saved") rather than re-stating the flat
rate. If the data needed to size it (e.g. refund amount vs ticket fare) was not measured, say what
single query would size it instead of asserting a vague benefit.
"""
