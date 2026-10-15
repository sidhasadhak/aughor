# Data Canvas investigation output — study (2026-10-14)

The question: the investigations a person asks on the Data Canvas are the platform's most
important output. CLARITY was applied to the canvas chrome and to a dozen other screens; the
report body was not touched. Are the guides around the model making its answers worse than the
model would write on its own, and what in the pipeline is structurally wrong?

Method: the 88 most recent complete investigations on the live API (74 asked on the canvas,
14 scheduled Day-Briefing runs), read over HTTP; the prompt modules and the two pipelines read
from code; one stored answer opened on the live canvas; the per-site prompt weights from
`GET /obs/prompt-weight`. No model call was spent.

## 1. What actually runs

Two pipelines produce the same report shape (`AnswerReport`, `aughor/agent/state.py:401`):

* **The analyst loop** (`aughor/agent/analyst.py:1759`) — the default for an Agent question
  on the canvas since `ask.converse` graduated. Intake once, then a tool loop (`run_sql`,
  `list_tables`, `describe_table`, `z_score`, `value_lookup`, `profile_column`, plus the four
  phase tools `baseline` / `decompose` / `cross_section` / `premise_check`), then the model's
  closing prose. A regex (`investigate.question_shape`, `investigate.py:1180`) decides
  "describe" or "diagnose": a describe question loses the four phase tools and takes
  `_describe_rules` (2.7k chars); its closing prose becomes the answer with no narrator call
  (`_conclusion_as_answer`, 10713). A diagnose question goes to the narrator
  (`ada_synthesize`, 10743) with the loop's prose as "THE ANALYST'S OWN CONCLUSION".
* **The phase script** (`graph.py` / `phase_waves.py`) — intake → baseline → decomposition →
  dimensional → behavioral → synthesis, or the cross-sectional lenses. Runs for the scheduled
  Day-Briefing investigations and the legacy `POST /investigate`.

Measured on the 88: **66 of 74 canvas questions** ran the analyst loop with only `intake` +
`adhoc_N` phases (one per `run_sql`); 8 ran a phase script; all 14 scheduled runs ran the
phase script plus 36 `adhoc_N` phases between them.

## 2. What the reader gets — measured

| What | Canvas (74) | Scheduled (14) |
|---|---|---|
| findings drawn with a chart/table and **no words** | 143 of 248 (58%) | 51 of 121 (42%) |
| reports whose body tabulates rows that a finding below draws again | 46 of 88 | |
| headline over 16 words (the narrator's own rule, `SYNTHESIS_CORE_RULES`) | 43 of 88 — median 16, p90 32, max 37 | |
| body opening with "The following table lists…" (forbidden by `_describe_rules`) | 22 of 88 | |
| phase summary carrying machinery text `[stats.py: σ=3.88 — significant anomaly]` | 16 of 88 | |
| `attribution_waterfall` empty | 73 of 74 | 13 of 14 |
| recommendations with `expected_impact` "N/A" | 6 of 17 | 1 of 21 |
| `plan_reconciliation` reporting `synthesis` skipped | 73 of 74 | 14 of 14 |

One describe answer as the reader sees it (investigation `2060e143`, canvas
E-Commerce Operations Overview, History ▸ Report): a 32-word headline that is the first
sentence of the prose, the sentence "The following table lists the top 10 product categories
by revenue for this period:", the table as the model wrote it, a note, then **the same ten
rows again** as a bar chart titled by code ("Total revenue by category — 5 Mar – 4 Sep 2026")
drawing only one of the two measures the question asked for, with a source button. No
sentence belongs to the chart. (Adjacent: the stored text says `$229,793.89`; the page shows
`€229,793.89` — a currency relabel without a conversion.)

Why: every `run_sql` the analyst makes becomes an `adhoc_N` phase with `summary: ""` and
`interpretation: ""` (`analyst.py:748-778` — "the narrator writes the prose from the evidence
log"), and the canvas draws any finding that has columns (`InvestigationReport.tsx:348`). The
analyst's words about those rows live in its prose, so the page shows the reading once as
prose and the rows twice. The envelope (`answer/envelope.py`) already folds this correctly —
`lift_tables` takes the table out of the body and makes it the grid — but the canvas renders
`executive_summary`, which keeps the table, not the envelope.

The headline is `_lead_sentence(conclusion)` (10615): the first sentence of free prose,
capped at 240 chars. `_describe_rules` tells the model that sentence must carry "its figures
— what leads, what trails, by how much", so the headline is a paragraph by instruction.

## 3. What is asked of the model that nobody reads

* `ADASynthesisModel` (prompts_investigate.py:949) asks ten fields. The canvas renders five
  (`headline`, `executive_summary`, `closing_summary`, `recommendations`,
  `total_change_label`; `InvestigationReport.tsx:536-611`). `confidence`,
  `confidence_justification`, `attribution_waterfall`, `causal_links` are never on the page;
  `data_gaps` reaches only the envelope's caveats. The waterfall is empty in 86 of 88 reports
  (forced empty on every cross-sectional run, 11241) and three of the seven narrator rules,
  plus `check_signs` and `check_waterfall_sums`, govern it.
* `AnswerRecommendationModel` requires `owner` and `timeline`. The data holds neither, so
  the model invents "Logistics Operations" and "2026-10-30" and the page prints them
  ("Impact: N/A Owner: Logistics Operations Timeline: 2026-10-30").
* `ARGUMENT_STYLE_ADDENDUM` demands every figure "**bold inline**"; `DECOMPOSE_INTERPRET`
  says "bold the share" and, two lines up, "Use NO markdown emphasis";
  `_strip_emphasis_deep` (11422) then removes every bold from the shipped report. The model
  spends attention on formatting the code deletes.
* `chart_type` is asked twice per query (plan and interpret) and resolved by code at the one
  seam (`_phase_result`, 2505). `stat_note` and `is_significant` are asked and then
  overwritten whenever code computed a verdict (`_assemble_phase_findings`, 3014-3018).
* `orchestration_plan` declares the five-phase script at intake for every run, including
  analyst runs that never follow it; `reconcile` then journals `baseline / decomposition /
  dimensional` as skipped in 51–53 of 74 and `synthesis` as skipped in 87 of 88 (it is a
  node, never a phase id). The handoff journal records a plan nobody executed.
* A describe answer costs 7 model calls for one SQL statement (trace `6759cc33`: intake ×2,
  `build_analysis_ledger`, loop ×3, `judgment.seam:judge` — which failed "structured output
  empty"). 15.3k prompt tokens, 949 completion.

## 4. Guide or guard — the prompts

The repo already states the principle (PE-2, `report_checks.py:1-13`): a correctness
contract "belongs in code that verifies, not prose that hopes"; the synthesis prompt was cut
from 1,700 tokens of lecture to seven rules plus deterministic checks and one named retry.
That was done for the narrator only. Everything upstream of it is still prophylaxis:

* **`INTAKE_PROMPT`** (12.9k chars, 170 lines; 102 calls at 6,946 prompt tokens mean): seven
  numbered sections with ten `(critical)` / "all mandatory" guards, each a past failure
  written out as case law — BINDING, INTENT, LOSS (a–d), MAGNITUDE, DRIVER, TWO SIDES,
  PoP/YoY coverage guards, five DATE COLUMN "NEVER" rules. Code already verifies or
  overwrites much of it: `_clamp_intake_to_coverage` decides `no_prior_period` from the real
  dates; `_pin_canonical_metric` binds the governed metric; `resolve_claim_type` decides the
  licence; eight of 29 output fields are "set by code". The prompt refers four times to the
  PROFILE CONTEXT block ("GRAIN: the PROFILE states…", "Read the PROFILE CONTEXT date range
  FIRST") — on the analyst path that block is **empty** (`analyst.py:1678`,
  `scan_context: ""`). The guards that have no code check (date column must be a date-typed
  column that exists; metric table must be in the schema) are the two cheapest to write.
* **Phase plan prompts** are fixed scripts: "Write 2–3 SQL queries", "at least 13
  consecutive periods", "1 SQL query per dimension (up to 4)", "max 4 queries total", and a
  "DIMENSION PRIORITY — customer type › channel › product category › geography" that is an
  e-commerce assumption applied to every connection. `_ADA_SQL_GROUNDING` (1.5k) rides every
  plan call and the TABLE NAMES / NEVER CAST / NO EXTRA FILTERS paragraphs are repeated in all
  four temporal plan prompts — while `_uses_relative_date` and the fan-out check already force
  a corrective re-plan, which is the guard.
* **Interpret prompts** carry FORBIDDEN word lists (`BREAKDOWN_INTERPRET`) and a SEVERITY
  GROUNDING paragraph repeated five times, beside `_ranking_noise_caveat`,
  `_concentration_note`, `check_significance_claims` and `check_noise_findings_not_cited`,
  which verify the same thing and already prepend the verdict to the rows the model reads
  (`_results_text_with_verdicts`).
* **`_describe_rules`** (2.7k) is violated on the page in 22 of 88 answers ("The following
  table…") — the number the envelope's `lifted_tables` counter was built to report. A rule the
  model does not keep is a rule to verify or to make unnecessary, not to restate.

What is genuinely a guard and should stay exactly as it is: every check on `run_sql`
(guards, caveats, `too_few`, `first_change_missing`, `not_the_declared_measure`), the
`_every_result_warned` stop check, `_results_text_with_verdicts`, `run_report_checks` with
its one named retry and `withhold_untraced`, the claim licence, the coverage clamp.

## 5. The verdict

The loop design is right — the model chooses the slices, code verifies each one — and the
analyst's prose is, on the live specimens, the best text the run produces (the repo measured
this on 2026-09-29 and built `_conclusion_as_answer` from it). What is wrong is that the
analyst's answer is then forced through a report shape built for the phase script:

1. its results are shown as wordless "phases", so the page repeats the rows and separates the
   reading from the exhibit;
2. its prose is cut at the first sentence to make a headline, by an instruction that puts
   the figures in that sentence;
3. the narrator model carries fields with no reader, and required fields the data cannot fill;
4. the intake and phase prompts lecture about contracts that code already enforces, to a
   model that is told to read a profile block it is not given.

None of it is the model's intelligence failing; it is the scaffolding choosing the shape of
the answer before the model has read the data.

## 6. Proposal — channel, do not script

In order of reader-facing leverage. Each names the number that proves it.

**P1 — The analyst's answer carries its own structure, and the canvas draws that.**
Add a `conclude` tool to the analyst roster: `headline` (one line, the claim),
`answer` (prose, no tables), `exhibits` (the result ids the answer cites, each with a one-line
claim that becomes the exhibit's caption). Calling it ends the turn. The report is then
headline · answer · each cited exhibit once, where cited, captioned by its claim · caveats
from the guards — the envelope's fold, which already exists, with the exhibit claims it was
missing. Uncited results stay behind the source drawer and the Evidence tab. Removes
`_lead_sentence` / `_ranked_headline` guessing, the prose-table lift, the wordless
`adhoc_N` cards, and the duplicate table. Proof: duplicate-rows 46 → 0; headline words
median ≤ 12; wordless drawn findings 58% → 0; "The following table" 22 → 0. Every guard in
§4's last paragraph stays. The same tool serves the scheduled runs' `adhoc_N` phases.

**P2 — Intake on the PE-2 diet.** Split `INTAKE_PROMPT` into the ask (what to measure,
over which window, cut by what, compared with what — the seven questions, without the case
law) and verifiers: the coverage clamp and metric pin already exist; add a date-column type
check and a metric-table-in-schema check with one named retry. Drop the PROFILE references
where no profile is given, or give the analyst path the profile. Keep the LOSS reading as a
declared rule (it is a definition, not a guard). Proof: the replay harness
(`replay_args`, `GET /obs/prompt-capture`) on the eight real canvas questions and the five
benchmark ones — same `metric_sql`, same windows, same `cross_sectional`; prompt tokens at
`ada_intake` from 6.9k mean to under 4k.

**P3 — Phase prompts say the job, code enforces the SQL.** One shared grounding line; the
corrective re-plan (which exists) is the guard for relative dates, fan-out, unknown tables.
Dimensions come from the intake's `dimensions` and the ontology, not a retail priority list.
Remove the SEVERITY / FORBIDDEN paragraphs where a verifier already runs. Reconcile emphasis:
either keep inline bold through to `BriefProse` (it renders it) or stop asking for it — not
both. Proof: `run_analysis_phase` prompt mean 4.6k → ~3k with no change in the phase checks'
violation rate.

**P4 — Ask the narrator only for what has a reader.** `attribution_waterfall` requested
only under a causal licence on a change question (it is forced empty otherwise); `owner` and
`timeline` optional, `expected_impact` optional and only when the evidence supports a number
(the addendum already says so). `data_gaps` and `causal_links` keep their consumers (envelope
caveats, the Record's causal proposals). The `orchestration_plan` is declared only on the
phase script, so `plan_reconciliation` reconciles a plan that ran.

**P5 — Machinery text out of prose.** `[stats.py: σ=…]` goes to the phase's verdict slot
(the badge and warning already exist on the page), never into `summary`; "The phase narrator
wrote:" keeps the verdict in the badge and the model's sentence in the body. Proof: 16 → 0.

**P6 — One answer, one rendering.** The History panel and the chat turn render the same
object (today: chat renders the streamed report, History sniffs fields and renders
`executive_summary` with its table). With P1 that object is the envelope.

Not proposed: a second model call to caption or shorten anything. Every proposal removes an
ask or moves a rule into a check; none adds a call.

## 7. Calls made, and what was built

* The user asked for the body mocked first: `design-mockups/canvas-answer-body.html`, on `2060e143`
  (describe) and `55e58a3b` (diagnose). Words a reader faces: describe 217 → 227 (nothing said twice,
  and the asked-for order value now drawn); diagnose 856 → 539, every number and caveat kept. Then
  "let's go": P1 first; the figure row stays; uncited results are named under Sources.
* **P1 built (2026-10-14), behind `analyst.conclude`, off by default, byte-identical off:**
  - `tool_loop.ToolSpec.concludes` — a tool whose accepted result ends the turn (`stop_reason
    "concluded"`, `LoopResult.conclusion`); `stop_check` hands it back once, as a text answer.
  - `analyst.conclude(turn, args)` — headline (≤ 16 words), answer (no tables), exhibits (result ids
    this turn produced, each with its claim), figures (≤ 4), gaps. Each rule is a CHECK: a breach is
    refused with what to fix and the model writes again; nothing is cut or guessed. `run_sql` results
    and phase payloads carry the `result_id` a citation uses.
  - the report carries `exhibits` / `figures` / `gaps` (`AnswerReport`, `_attach_conclusion`); a describe
    answer takes the conclusion's own headline (`_conclusion_as_answer`), so `_lead_sentence` and
    `_ranked_headline` are the off-path only.
  - the canvas (`InvestigationReport.tsx` `ConcludedBody`): headline · figure row · period and caveat
    chips · the answer · each cited result once, numbered, captioned by its claim, with Table / SQL ·
    Next · Sources naming the uncited results. The exhibit's grid is one slot (`ExhibitGrid`), so the
    component study's one-grid consolidation changes one line here.
  - tests: `tests/unit/test_analyst_conclude.py`, `test_tool_loop.py` (+3),
    `web/components/InvestigationReport.concluded.test.tsx`.
* **Proven live (2026-10-14, 15:05–15:40 UTC)** on `:8000` with the flag on: four Agent questions, two on
  theLook (`cee3f6ed` describe, `5b6fb57c` diagnose) and two on LuxExperience (`e441d73d`, `34ca1559`),
  all ended on `conclude`. Headlines 12–14 words; words faced 232 / 554 / 206 / 449; no table in prose; no
  wordless exhibit. Every figure in all four answers traced to the rows its own queries returned. Accuracy:
  both describe answers and the Lux diagnose answer correct throughout; the theLook diagnose answer's
  exhibits (the analyst's) correct, its narrator summary not — it wrote one story over two measurements of
  revenue (the baseline's $336,383 → $385,389 and an uncited decomposition's $296,916 → $335,733), claimed
  the uncited split "reconciles to +$49.0K" (it sums to $38.8K), called 14.57% "smaller than +13%", and
  quoted a caveated z. Also found: the period chip showed the data's coverage when the intake pinned no
  window (fixed, `5eb66444`); the phase script's `_align_narrator_findings` paired the AOV prose with the
  segment rows on `34ca1559` (named, not fixed).
* **P4 built (2026-10-14), the user's call "P4 first":** the waterfall is asked for only under a causal
  licence on a change question (`synthesis_ask_model`, `widen_synthesis`; the rule rides the system prompt
  only then); `expected_impact` / `owner` / `timeline` optional, each "never invented"; an analyst turn
  declares no phase plan (`analyst_turn`) and reconciles none; and on an analyst turn that concluded the
  narrator writes from the CITED results — their rows are its evidence, the uncited are named by title, so a
  figure it cannot see it cannot state and the grounding check holds the line (`_phases_cited`). Tests:
  `tests/unit/test_narrator_asks.py`.
* **P4 proven live (2026-10-14, 15:32–15:50 UTC, `:8000` on `3fbd10b0`):** Lux diagnose `d206ec65` and theLook
  diagnose `1f925796`. Both: `plan_reconciliation` null, waterfall empty under a descriptive licence,
  recommendations with no invented owner or date, and every figure in the narrator's prose traced to a
  cited exhibit's rows — nothing from an uncited result. On theLook the two revenue scopes were both cited
  this time, and the narrator SAID they differ (385,389 vs 335,733, "a gap the analysis did not reconcile"),
  capped its confidence and made the reconciliation its first action — instead of blending them as
  `5b6fb57c` had. Two inaccuracies remain in that answer: it labelled 385,389 "all statuses" (the SQL
  excludes Cancelled), and it wrote every figure in **CHF** over data that carries no currency — the only
  CHF in the run was the example in the narrator's own style rule. Fixed at the cause (the example lost its
  unit) and guarded (`report_checks.check_currency`: a currency CODE no result, column or label carries is
  refused with the retry; symbols are left alone).
* **P2 built (2026-10-14), the user's call "Let's do P2":** the premise measured first — every guard in the
  12.9k-char intake prompt was mapped to its verifier: metric table, dimensions and windows are validated with
  one named-correction retry; the date column is resolved deterministically; the coverage clamp, `periods_asked`
  and the cross-sectional / temporal-change routers decide the windows and the route whatever the model said;
  the canonical pin, the money-coherence and over-count retries and the self-referential-segment drop guard
  the metric; the loss directive is prepended by code. Only the measure choice, the reading of "loss", the
  magnitude-vs-flag judgment and the concept-to-column resolution of a relationship's sides are the model's
  alone. So a capable binding (the live coder, 1M-token context) now reads `INTAKE_ASK` — 3,295 chars, 525
  words, the seven fields and those judgments, no case law, and the profile block as a section only when there
  is one; a baseline binding keeps the long form byte for byte (`intake_prompt(capable)`, the narrator's own
  tiering). 12,951 → 3,295 chars (25%). Tests: `tests/unit/test_intake_ask.py`.
* **P2 proven live, after a finding (2026-10-14, 16:34–17:05 UTC).** The first four runs on the P2 commit
  (`c376932a`, `2e30ff91`, `faab7bed`, `99201af8`) gave specs identical to their long-form runs and kept P4's
  behaviour — but the intake prompt was 8,667 tokens before and after: the ask never reached the model. The
  live coder is **`claude-sonnet-5-5`**, and Anthropic's models API declares no context window, so
  `tier_for` resolved every Claude binding to BASELINE — 20k of schema instead of 60k, 12 interpret rows
  instead of 36, 10 loop steps instead of 24, and the long-form prompts — and nothing said so. Fixed at the
  cause (`c434f1ea`): the catalogue records Anthropic's documented 200k floor for every model it lists;
  after a refresh the tier follows. Then, on the capable tier: theLook describe `cb4d07c6` — intake
  **8,667 → 5,153 prompt tokens (−41%)**, the spec identical field for field, every figure the same, the
  period now "16 Mar – 15 Sep 2026" (the cross-section period fix in the same commit); Lux describe
  `28ff61e1` — intake 16,537 → 25,669, because the capable tier now shows the model 60k of Lux's 42-table
  schema instead of 20k (the diet's −2.4k tokens inside a +11k schema), spec and figures unchanged.
  Every Claude binding runs on the capable budgets from here; the four P2 runs above were the last on
  baseline.
* **Recorded against myself:** the 16:34 restart ran with an active job in the pre-check — the birth of the
  user's new LuxExperience canvas (`8a93c946`, created 16:24) — and cut it at ten minutes. Its record stays
  RUNNING; the re-run is `POST /exploration/canvas/8a93c946/restart` (model calls, the user's call).
* **P3 built (2026-10-14), the user's "go for P3":** three things the planners' prose hoped for are now
  checks or facts. (1) **An extra filter is a guard, not a rule**: every planned query's WHERE is read for
  value filters beyond the spec's declared ones (`_extra_filters`, the analyst's own filter reader); one
  corrective re-plan names the filter and the declared one; what the re-plan keeps becomes the finding's
  caveat on the fan-out channel ("extra filter: this query keeps rows by status not in Cancelled,
  Returned — … over a narrower population than the baseline's"). The four temporal phases pass the
  governed metric's filters; the live gap on `1f925796` (335,733 vs 385,389) is what it catches. (2) **A
  capped scan says it is a slice**, to the narrator (a verdict line above the rows) and on the card
  (`stat_note`): "nothing here says what the largest group is or that no group exceeds a value" — the
  sentence `55e58a3b`'s 15-row worst-first slice needed. (3) **The planners' diet, tiered like the intake's**:
  a capable binding reads one 399-char paragraph of SQL rules (`plan_sql_rules`, `_sql_grounding()`
  empty), a baseline binding keeps each phase's long block; the "DuckDB dialect only" line is gone from
  every tier (it contradicted the SQL DIALECT line on BigQuery and Postgres); the retail DIMENSION
  PRIORITY paragraph is gone from every tier (the list the prompt receives is already in order — the
  question's cuts first, then `_prioritize_dimensions`; a pack-supplied order can replace the sorter
  later); and no prompt asks for bold the code strips (`_strip_emphasis_deep`). Tests:
  `tests/unit/test_phase_guards_p3.py`.
* **P3 proven live (2026-10-14, 17:45–18:10 UTC, `:8000` on `fa1dcd02`):** theLook diagnose `d4039693`. The
  extra-filter guard fired three times — the analyst called `decompose` three times and each plan had added
  `status NOT IN ('Cancelled','Returned')` — and every re-plan removed it: all fourteen stored queries carry no
  filter beyond the declared one, and the decomposition now measures July $336,383 → August $385,389, the
  baseline's and the analyst's own scope (before: $296,916 → $335,733). The planners' prompts dropped about a
  thousand tokens each (5,316 → 4,260; 5,769 → 4,687). No figure leaked from an uncited result; the plan was not
  reconciled; the waterfall stayed empty. Two gaps the proof exposed, fixed in the follow-up commit: refused a
  WHERE filter, the `baseline` planner kept the rows out through `SUM(IF(status NOT IN (…), sale_price, 0))`
  instead — the guard reads conditional aggregates now, and the measure's own conditions (a return rate's
  `CASE WHEN status = 'Returned'`) are declared so a rate is never asked to drop them; and the decomposition's
  20-row top movers carried no slice note because that path does not pass `_assemble_phase_findings` — the
  stamp moved to `_phase_result`, the seam every phase passes. The follow-up is unit-tested, not re-proven
  live. Cost note: on the capable tier a diagnose answer runs 24 loop steps, 36 interpret rows and the
  guards' re-plans; this run made 26 model calls over 168k prompt tokens on Sonnet 5.5 (~$0.50).
* Not done in P3, named: the interpret prompts' SEVERITY GROUNDING / FORBIDDEN paragraphs still ride
  every tier (their verifiers exist: `_ranking_noise_caveat`, `_lead_with_verdict`,
  `check_significance_claims`); the lens prompts keep `_ADA_SQL_GROUNDING`; the dimensional scan still
  sorts worst-first under its cap (the slice now says so).
* **P5 built (2026-10-14 PM, the user's "let's do P5 first"):** the machine's words out of the reader's prose,
  each to a slot that already had a reader. (1) The baseline's `[stats.py: σ=3.88 — significant anomaly]`
  is the phase's **`verdict`** (`{"sigma", "significant", "text"}`, `baseline_verdict`), never a bracket in
  `summary`; the page draws it as the badge the findings already wear (`PhaseVerdict`), the PDF as a small
  "Verdict" line under the summary, the narrator reads it as a `CODE VERDICT:` line beside the summary, and
  the contradiction scan, `_states_normal_variance` and the confidence ceiling read the slot first and the
  bracket on older stored phases (`phase_verdict`). The later planners still get it in words on the internal
  hand-off (`_baseline_summary`). The web also strips the bracket out of an older report's summary. (2) A
  finding that contradicted its verdict read "<verdict> The phase narrator wrote: <sentence>" — the verdict
  now goes to `stat_note` (the badge above the sentence), and the model's sentence stays the body. (3) The
  "Not independently challenged" caveat keeps the reader's half; the machine's reason stays on
  `causal_checks.refutation.why`. Not done, named: the intake's own ALL-CAPS tags (`CLAIM LICENCE:`,
  `ROUTING:`, `TEMPORAL AXIS RECOVERED:`) still ride `intake_notes`; they reach no web body (the intake phase
  is filtered from both) and are parsed by the licence readers, so moving them is a separate change. Tests:
  `tests/unit/test_phase_verdict_p5.py`, `web/components/InvestigationReport.verdict.test.tsx`. Proof: a
  stored report's phase carries `verdict` and a summary without the bracket — needs one live diagnose run
  after a restart on the fix (the user's call; ~$0.50 on Sonnet 5.5).
* **Why the Lux answer said "I rely on the phase tool's summaries" (`99201af8`, 16:34 UTC) — read back from
  the trace, and what now channels it.** The chain: the schema linker kept `order_items` and dropped
  `orders`, the table that carries the date (the intake's own notes: "the orders columns are not listed,
  orders.order_ts is an assumption"); the date resolver had no `orders` block to correct the invented column
  against, so the spec carried `orders.order_ts`; the phase planners wrote it and the SQL fixer repaired it
  **nine times** (nine model calls); the analyst copied the spec's column into its own cut, got Postgres's
  "column o.order_ts does not exist — perhaps you meant o.order_id", listed the whole schema (81k chars),
  wrote the same column again, fixed it only for the platform cut, and concluded — in the first person, about
  its tools — that it "could not run the category and brand cut". Its two `decompose` runs also carried the
  same ids (`decomp_0..2` twice): the exhibit's citation was ambiguous and the page keyed two children
  `decomp_2` (the console error the user pasted). Built: (a) **`complete_join_paths`** — the linked schema
  TEXT is completed with the tables its joins need (pinned temporal dimensions, ranked, FK-completed, scoped),
  one body for the Agent path and the deep path, which until now completed only its data catalog; (b) the
  intake's date resolver reads the un-linked **`full_schema_context`** (both paths carry it) so an invented
  column is corrected against the catalogue, not the excerpt; (c) a failed `run_sql` comes back with the
  fixer's own **diagnosis** — the real columns of the table the alias names (`diagnose_sql_error`, now reading
  Postgres, BigQuery and Snowflake's unknown-column shapes too); (d) **`conclude` holds `answer` and `gaps` to
  the reader's register** — the first person and the machinery's names ("phase tool", "the query errored",
  `result_id`) are refused once with the register asked for ("This analysis did not test…"); (e) a repeated
  phase tool's phase and finding ids are **renamed in place** before the model reads them
  (`decomposition_2`, `decomp_0_2`), and the web keys its lists with `withUniqueKeys` for older reports.
  Tests: `tests/unit/test_lux_answer_guards.py`. Adjacent, not done: `list_tables` returns the whole visible
  schema (81k chars on Lux) — a manifest of names with `describe_table` for detail would cost less; the
  prompts' `orders.order_ts` example (`INTAKE_PROMPT`, `_ADA_SQL_GROUNDING`) is a plausible column on a real
  table name — placeholder forms would not be copied; the "Mr Porter 23.15% vs 22.78%" discrepancy the
  narrator noted is unexplained.
* **The ERD** had not been removed: #610 moved the schema's diagram into Tools ▾ "as a tab of its own", and a
  view behind a menu reads as removed. It is a tab again — Overview · Tables · **Diagram** · Docs · Settings —
  at schema scope and on a one-schema connection, which is its schema (`CatalogScope.tsx`).
* **A metric's date on a table its SQL does not read** (the user's gross-margin question): a period filters
  the date's own table INSIDE the statement (`scoped_statement`), so `order_items`' gross margin cannot take
  `orders.order_date` until its SQL joins `orders` — the editor's "one join away" hint already says so, but
  the save accepted `luxexperience.order.order_date` (a table the statement never reads, spelled wrong) and
  said nothing. The save now refuses it (422) with the fix. Live: Lux `gross_margin` still carries that
  column — correct it in the editor (join `orders` in the SQL, then choose `orders.order_date`).
* **P5 and the Lux guards proven live (2026-10-14, 22:30 UTC, `:8000` pid 17362 on `77791271`, nine envs):** the same
  Lux question re-run as `2f8ad418`. Against `99201af8`: the spec's date column is `orders.order_date` (was the
  invented `orders.order_ts`); the intake took one model call (was two — the correction retry); **no
  `aughor.sql.writer:fix` calls (was nine)**; 18 model calls over 141k prompt tokens (was 30); the analyst ran
  `baseline`, `decompose`, `decompose`, `conclude` — its second decomposition is `decomposition_2` with ids
  `decomp_0_2 … decomp_2_2`, no duplicate id in the report (was two `decomposition` phases carrying `decomp_0..2`
  twice); the baseline phase carries `verdict = {sigma 0.97, significant false, "σ = 0.97 — within normal
  variance"}` and a summary with no bracket; the gaps read "This analysis did not test why the order count
  rose…" (was "I did not test… I rely on the phase tool's summaries"); no first person and no machinery word
  in gaps or summary; the "Not independently challenged" caveat carries no machine reason. The analyst's own
  `run_sql` did not run this time, so the diagnosis path is unit-tested, not live-proven. The intake chose
  `SUM(orders.gmv_eur)` on `orders` as revenue (the earlier run measured line value on `order_items`); both are
  defensible readings of an uncatalogued "revenue", and the intake notes say which and why.
  **Exposed by the proof, then fixed (the user's call):** the narrator wrote, as a data gap, that code's verdict
  (σ = 0.97) does not reconcile with the planner's own z (0.011). From the stored 15 monthly rows, September's
  revenue sits 0.19σ above the 14 prior months and 0.01σ above the 12 prior — so code's 0.97 was not revenue's.
  The cause was in the baseline node: `code_sigma` was the LARGEST σ `analyze_query_result` returned for any
  numeric column of the first result — `baseline_0` carries revenue, orders and AOV, and the orders series won.
  The marker carried the same number before; the slot made the narrator able to say so. Now a per-column stat
  result names its `column`, `_metric_sigma` takes the metric's own series (by the label's words or an
  identifier the formula reads; else the first analysed column, which the planners write first), and the
  verdict names it: "σ = 0.19 on revenue — within normal variance". Unit-tested on measured series
  (`test_phase_verdict_p5.py`), not re-proven live.
* **P6 built (2026-10-15, the user's "lets take P6 next") — the premise re-measured first.** §6 said the History
  panel and the chat turn render two objects. Measured on `2f8ad418`: the `answer_report` frame the chat turn
  renders and the stored report History renders are field-identical (the store adds `_report_type` and
  `envelope`), and both go through `InvestigationReportView`; History reads the stored `_report_type` before it
  sniffs a field. That half of P6 was closed by construction. What was still rendered twice was the answer and
  its **envelope** — the folded object the doors that are not the canvas read (Slack, the export, a scheduled
  send, the fact-checker): headline, the executive summary as body, the data gaps as caveats, a grid only when
  the model had tabulated in prose. For a concluded answer (P1) that is a prose-only fold: `2f8ad418`'s stored
  envelope carried 0 figures, 0 exhibits, no grid and no gaps sentence while the canvas drew four of each.
  Built: the envelope is **version 2** and carries the concluded answer's structure — `figures`, `exhibits`
  (each cited result with its claim as the grid's caption, its chart decision and its phase's caveats, rows capped
  as the canvas caps them, a pruned citation left out as the canvas leaves it out) and `gaps` — folded from the
  report once (`_exhibits_of`); the one-grid door takes the first exhibit under its claim; the Slack selection
  reads headline · figures line · body · gaps and prints the claim over the fenced table; the export routes a
  concluded report to the envelope builder — Summary (headline, figures as key numbers, the answer, the gaps) ·
  Evidence (each exhibit under its claim) · Caveats · Next (the report's recommendations) — and keeps the
  phase-by-phase builder for a phase-script run, which names no exhibits; the Slack bot prints the figures line
  and the gaps from the `answer_report` frame as it prints the headline. A report without the structure folds as
  before. Proof without a model call: `2f8ad418`'s stored report folded through the new fold → 4 figures, 4
  exhibits (z-score, orders-vs-AOV, by channel, by region), the gaps sentence, the first exhibit as the grid; its
  Slack message and its export read in the canvas's order. The envelope stored on a run is the one folded at its
  end, so runs before this carry v1; a new run folds v2 — not re-proven live. Tests: `test_answer_envelope.py`
  (five cases), `bots/slack/src/aughor.test.ts`. Not done, named: the web still renders the report, not the
  envelope (the envelope frame stays unrendered there by design — the parts were already drawn from the frames);
  the Slack bot renders the first exhibit only, as its one-grid rule says.
* **The named-not-done items, measured and built (2026-10-15, the user's "Lets do"):**
  * **`list_tables` dumped the schema text** — 82,232 characters on LuxExperience (33 tables, 262 columns, with
    descriptions, grain notes, sample values and a note per column). It is a manifest now (`schema_render.
    schema_manifest`: name, row count, columns with types — 5,346 characters on the same text), and
    `describe_table` returns a table's full block; the raw text only when nothing parses. Both tool descriptions
    say so. Tests: `test_list_tables_manifest.py`, `test_brief_ask_scope.py`.
  * **`orders.order_ts` in the prompts** — `_ADA_SQL_GROUNDING` and the intake's date-column rule now carry
    placeholders (`<dated_table>.<date_column>`, `<table>.<column>`); `test_sql_context_in_prompts.py` holds
    that no plausible column on a real table name stands there.
  * **The intake's ALL-CAPS tags** — nine writers prepended `CLAIM LICENCE: …`, `ROUTING: …`, `TEMPORAL AXIS
    RECOVERED: …`, `MEASURE WARNING: …`, `NOT OFFERED AS DIMENSIONS: …`, `DRIVER CONTRAST DROPPED: …`, `SPEC
    STILL INVALID …`, `FEASIBILITY: …` and the coverage note to `intake_notes`, and the licence readers, the
    coverage reframe and the departure gate parsed them back out of the prose. Each decision is a typed entry
    on `intake.record` now (`_record_intake_note`: `{"tag": "claim_licence", "type", "why"}`, `routing`,
    `temporal_axis_recovered`, `coverage` with `duration_mismatch`, …), carried on the intake phase as a
    `record` slot (the copy that survives to synthesis), and the notes carry the reader's sentence
    ("Descriptive by design: …", "Read as a change over time — …"). The readers (`_recorded_claim_licence`,
    `_claim_licence_section`, `_reframe_on_pop_duration_mismatch`, `departure_basis.analysis_claim_facts`)
    read the record first and still parse an older spec's line. The model is never asked for the field
    (`IntakeAsk` excludes it). Tests: `test_intake_record.py` and the four updated writer tests.
  * **The interpret prompts' SEVERITY paragraphs on every tier** — the cross-section interpret templates
    concatenate the paragraph from a constant, and `cross_section_interpret_prompt(ratio, capable)` swaps it
    for a one-line ask on a CAPABLE `fast` binding (`_interpreter_capable`); the interpreter's system line
    (`_cross_section_interpret_system`) and the synthesis note's sentence (`_narrator_capable`) are tiered the
    same way. Their verifiers run on every tier: the verdict above the rows, `_lead_with_verdict`,
    `check_noise_findings_not_cited`. The breakdown's FORBIDDEN list stays on both tiers: no verifier reads a
    descriptive breakdown's judgement words, and the P3 rule is to remove prose only where one does.
  * **The lens prompts' long grounding** — seven lens planners appended `_ADA_SQL_GROUNDING` on every tier and
    none carried the ask; `_lens_sql_grounding()` gives a capable coder `plan_sql_rules`' paragraph and a
    baseline one the block.
  * **The dimensional scan sorted worst-first under its cap** — `DIMENSIONAL_PLAN_PROMPT` and the phase's plan
    line order by `ABS(absolute_change) DESC`, so a capped result holds the largest movers in either direction
    (55e58a3b's slice held the 15 smallest and hid Outerwear's +13.8%); `_capped_scan_note` says so for a
    magnitude-ordered slice and keeps its wording for the others. Tests in `test_phase_guards_p3.py`.
  * **Conclude's figures were not grounding-checked; exhibit claims were sometimes titles** — measured on the six
    stored concluded answers: 2 of 24 figures were in no result's rows or totals, and 2 of 16 claims were titles
    ("Top 10 categories by revenue with order counts and AOV, last 6 months, non-cancelled" — cee3f6ed,
    e441d73d). `conclude` now refuses a figure whose numbers no result returned (`verify.ungrounded_figure_
    numbers`: a cell, a difference or share of two cells, a column's total, each at the value's written
    precision, result by result) or that states no number, and a claim with no predicate (`_reads_as_a_title`:
    no verb, comparison, change or percentage, or the finding's own title restated). The 14 real claims and 22
    grounded figures in the stored answers pass. Tests in `test_analyst_conclude.py`.
  * **"Mr Porter 23.15% vs 22.78%" — explained.** `stats._analyze_rate_segments` read the platform scan's
    `pct_change` column (a movement between two months) as a PROPORTION over `obs_orders`, reconstructed MR
    PORTER's "successes" as round(0.2278 × 108) = 25 and reported 25/108 = 23.15% (NET-A-PORTER 4.76% for 4.57%,
    the pooled "rate" 13.37%) in the statistical output the narrator reads — which it then carried into the
    report as an unexplained discrepancy. A change column is never a rate now (`_CHANGE_KEYWORDS`), and a rate
    whose implied counts are not whole numbers at the precision it is written with is not a proportion of that
    denominator (`_implied_counts_are_integers`); on the live rows the test stays silent. Tests in
    `test_rate_uniformity.py`.
  * **`_align_narrator_findings` misbound on 34ca1559** — the narrator wrote two findings from the orders-vs-AOV
    result and none from the brand result; the derivation-credited grounding scored 1.0 for every finding
    against the 85-cell segment grid (on a wide result some pair of cells derives almost any figure), so the AOV
    prose shipped over the segment rows and the segment prose over the brand rows. `verify.raw_grounded_
    fraction` (cells only; and "€"/"£" are currency now — on a EUR connection a euro figure was no salient
    number at all) scores 0.83 against the rows that hold them and 0.17 against the rest. A finding's HOME is
    the query whose rows hold its numbers raw (`_finding_homes`, best share ≥ 2× the runner-up); it binds
    nowhere else — not by a shared title token, not by position; a second reading of the same rows folds onto
    that card (`_fold_second_reading`); a query nobody wrote about keeps its title and no borrowed prose. Tests:
    `test_narrator_binding_homes.py`; the percent-claims test still holds.
  * **The export's Checks printed raw receipts** — `answer/receipts.py` carries the web's vocabulary
    (`GuardReceiptChain.tsx`'s GUARD_LABEL and ACTION_VERB, plus the seven guards neither surface had named:
    `extra_filter_replan`, `ambiguity_probe`, `count_star_entity_grain`, `repair_recheck`, `time_order`,
    `day_window`, `declared_filter`); the PDF's line is "Queries re-planned around a filter the metric does not
    declare — sent the plan back for correction: …". `test_guard_receipt_vocabulary.py` reads the TSX and
    holds the two maps equal, and holds that every guard the backend writes has a label.
  * **"The PDF draws tables, not charts, in this environment" — the premise was wrong.** Node, the SSR bundle
    and resvg are all present, here and in the live process, and the bundle renders a 3-row grid. It returned
    no chart for 2f8ad418's four exhibits because the decomposition grids carry 11–19 numeric columns, and
    `isUngraphableGrid` (≥ 4 numeric columns, no date) refuses them — in the browser too, so the screen shows
    the same tables and the PDF mirrors it, as CA-4's one renderer intends. The same rows with two or three
    columns render. Not built: a chartable projection of a wide decomposition grid (segment + change) would
    have to be the finding's own exhibit on both surfaces, which is a planner/grammar decision, not an export
    fix. Named.
* §6 is closed: P1–P6 built, and the named-not-done items above are closed as written, bar the wide-grid chart
  projection, which is named.
* **The check shape (2026-10-15, the user: "the nature of the question must be first interpreted and then the
  output structure adopted — what's the whole point of being Agentic then?").** Measured on LuxExperience
  `d14f276b`: "Do Event and Platform really join on these keys?" matched neither the read-ask nor a why-word, fell to
  `diagnose`, and the intake invented a metric ("event attendance records (rows available to join)", `COUNT(*)`), a
  date and a window for it; two ad-hoc queries then answered it correctly in 1m14s, and the page wore the
  investigation's clothes — period chip, a scatter of a five-row count by platform drawn off its date bounds, three
  recommended actions. The quick path's own router sent the same question to "direct" and answered it in 9 s. Built:
  a third shape, **`check`** — a question that asks to VERIFY a property of the data or the model (keys that join,
  duplicates, orphans, nulls, one table agreeing with another; `_ASKS_TO_VERIFY_RE`, conservative, why and advice
  outrank it). A check runs no intake (the turn keeps the engine and the clock), gets the roster without the phase
  tools, the check rules (decide what makes the answer yes or no, measure exactly that with counts, stop when the
  verdict is evidenced; the headline is the verdict with its decisive count; no cause, no recommendation, no period
  the question did not name) and the no-writer door a describe takes; the page draws no period chip and no Next on it;
  `decide_ask_route` answers a check quickly under auto depth, so "Agent" means depth, not frame. Adjacent, fixed: the
  chart inference read a per-category summary with date bounds (one row per platform, first and last event date) as a
  time series — it is a category grid now. Not unified: the quick router's taxonomy (direct · investigate · explore)
  and the Agent turn's (describe · check · diagnose) are still two vocabularies; the check is the first word they
  share in code. Tests: `test_question_shape.py` (check cases, roster, rules, the door, the router),
  `test_analyst_tools.py` (a check runs no intake), `InvestigationReport.concluded.test.tsx`,
  `chartTypeInference.test.ts`. Not proven live (a run costs a model call).
