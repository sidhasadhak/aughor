# Report quality deep dive — the Direkteingabe specimens (2026-08-19)

> **Why this exists.** Two reports on the same question, same data, same day: one from Databricks
> Genie (a multi-turn conversation), one from Aughor's deep analysis. The user's read: *"the
> fundamental approach seems deviated from expectations — our guards are choking the raw
> intelligence of the models."* This document tests that hypothesis against the stored run
> records, the source data, and the code — file:line throughout. Verdict in §0; evidence in
> §1–§6; implications in §7.
>
> Specimens: `investigations.id = cb37be54` (the report), `7774b792` (the follow-up). Data:
> `workspace` connection, CSV upload `traffic.all_dimesnsions_2` (166,030 rows, 2026-06-01 →
> 2026-08-18, 27 columns incl. `BROWSER_VERSION`, `ISP`, `BOUNCE_SESSIONS`, `ORDERS`).

---

## 0. TL;DR

1. **The hypothesis is half right, and the half that is right is not the half that hurt.**
   Two different things are called "guards" here:
   - **SQL-level verification** (fan-out, value-domain, id-arithmetic, join-coverage — the
     Verifier). Measured pure-upside in R4 (`docs/R4_ABLATION_EVAL_2026-06-21.md`). Keep.
   - **Analysis-level restriction**: a fixed phase script, metric/windows/dimensions chosen
     *once* before any result is seen, prose-linting checks keyed on vocabulary, a "never derive
     a number" rule, row/char caps on what the narrator sees. This is what the user feels — and
     it is real (§5, §6). But it is not what lost this report.
2. **What lost the report is that the model was never asked to analyze.** The deep path has
   **two decision points** (the intake spec; the SQL text inside a slot-filled template) and
   **no result-reactive re-planning anywhere** — `aughor/agent/orchestrator.py:15-24` says so by
   design. Seven LLM calls per run; three are decisions, all made before any row comes back;
   four are narration over rows the code already fixed. Genie's grammar — slice, *see*, slice
   again — is structurally unavailable to Aughor's deep path.
3. **The specific run was lost at intake by code, and the model was structurally unable to
   see it.** The coverage clamp (`investigate.py:3518-3524`) set comparison window == observation
   window ("Same period (no prior period exists in the data)"), recorded it only as a note, and
   the decomposition prompt was then handed two identical windows. Every downstream step was
   mechanically correct and semantically void: `obs_traffic == comp_traffic` on every row ⇒ the
   narrator wrote "no significant variation ⇒ broad volume-based shift" — a confident false
   inference from a tautology. **Every guard that could have caught the equality bails out on
   exactly that condition** (`:3547`, `:5549`) or keys on a column-name regex that does not
   include `abs_change` (`:2331-2332`).
4. **The checks that did fire, fired on prose, not on analysis — and leaked.** #36 flagged
   `26.8%` (a correct derived figure — the grounding check has no derivation credit, unlike
   `aughor/explorer/verify.py:469-489`) and reported *whole sentences containing correct numbers*
   as fabrications; #15 is a regex hit on the word "increase" in a title and in a negated
   descriptive sentence, while the licence text it enforces literally says *"report … how it
   changed"*. The repair instruction for the model was concatenated verbatim into the
   customer-facing `confidence_justification` (`investigate.py:8358-8361`) and the PDF renders
   it (`aughor/export/document.py:377-379`). 10 of 144 stored reports carry this leak — all since
   2026-08-15.
5. **The follow-up fabricated at confidence HIGH from zero rows**, because the honest-confidence
   floor keys on `columns` instead of `row_count` (`investigate.py:8395-8397`) and the intake-spec
   finding always satisfies it — the floor is dead code. No check fires on number-free prose.
6. **The right answer was three SQL slices away** (§2): a bot population (Chrome "105" UA,
   macOS desktop, 99.8% bounce, German ISPs on a Swedish site) quadrupled in August to 21% of
   the channel; underneath it, human Direkteingabe traffic is genuinely growing ~20–25%/month
   per day, mostly iOS/Mobile Safari in July. Genie got to the door (macOS Chrome, "suggests bot
   traffic"); one more slice — `BROWSER_VERSION` — closes it. Aughor compared the period to itself.
7. **`orchestration_plan` is null on 144 of 144 stored deep reports**: `_orchestration_plan` is
   not a declared `AgentState` channel (`aughor/agent/state.py:545-564`), so LangGraph drops the
   write (`investigate.py:4941` → read `:8120` always `None`). Same class of bug silences
   `_baseline_rel_change` on the serial path.

**One sentence:** the guards choke the *prose*; the pipeline chokes the *analysis*; and the
guards that would matter (window degeneracy, partial-period normalization, zero-row
conjunctions, row-based confidence) do not exist.

---

## 1. The two specimens

### 1.1 Genie — "Yes, Bounce Rate is the Primary Driver"

A follow-up answer in a multi-turn conversation (the user had narrowed to Direkteingabe ×
Chrome). Five numbered findings, three charts, four recommended actions. Every cited number
verified against the source (§2 method):

| Claim | Genie | Source | |
|---|---|---|---|
| Chrome bounce in Direkteingabe | 66.24% | 66.24% | ✓ |
| Channel average bounce | 45.46% | 45.46% | ✓ |
| Mobile Safari / Chrome Mobile bounce | 39.31% / 32.81% | 39.31% / 32.81% | ✓ |
| Chrome bounce Jun / Jul / Aug | 72.66 / 46.69 / 80.11% | 72.66 / 46.69 / 80.11% | ✓ |
| macOS Chrome Desktop sessions, bounce | 15,577 @ 87.91% | 15,487 @ 87.87% | ✓ (range) |
| Windows Chrome Desktop bounce | 48.65% | 47.65% | ≈ |
| Aug 8 | 1,106 sessions @ 90.14% | 1,106 @ 90.14% | ✓ |
| Conversion Jun → Aug | 1.96% → 1.23% | 1.96% → 1.23% | ✓ |

Its flaws, for balance: bounce rate is a *symptom*, not a "driver" of traffic (the title answers
a leading question); July — the peak month — had the *lowest* Chrome bounce (46.69%), so "the
traffic increase is accompanied by a severe bounce problem" conflates July's rise with
August's quality collapse; August is treated as a full month; and it stopped one slice short of
the actual cause. But the *grammar* is right: slice until a segment pops, name concrete
segments and days, state the hypothesis ("suggests bot traffic"), recommend the specific next
check.

### 1.2 Aughor — "Investigation into July 2026 Traffic Peak in Direkteingabe Channel"

Question: *"Why is traffic in Direkteingabe going up? What is the reason behind it?"*
Confidence MEDIUM. Four phases (intake, baseline, decomposition, synthesis). What it says and
what is true:

| Report says | True | Mechanism (§3) |
|---|---|---|
| "AT A GLANCE: traffic · **February 2025** · Same period (no prior period exists in the data)" | Data is Jun–Aug 2026 | LLM label never rewritten after the window was clamped (§3.1) |
| July peak 37,925, +26.8% vs June 29,903, "partially correcting in August (32,912)" | August is **18 days**; per-day 997 → 1,223 → **1,828** — August is the *highest* | No partial-period normalization anywhere; monthly sums only (§3.6) |
| Z-score "could not be performed (mean and std NULL)" | Baseline window was 2025-06-01 → 2026-06-01, before the data exists | Prompt asks for "at least 13 periods"; nothing reacts to NULL (§3.3) |
| "Decomposition … shows **no significant variation** … a broad volume-based shift rather than a segment-specific trend" | iOS/Mobile Safari carries 55% of the Jun→Jul delta; the Aug rise is 21% bots | obs window == comp window ⇒ `abs_change = 0` on every row (§3.2, §3.4) |
| Two dimensions decomposed (DEVICE_CLASS, BROWSER_NAME) of 8 listed; no OS, no version, no ISP, no daily grain | The answer lives in OS × BROWSER_VERSION × ISP × day | "Write 2–3 queries", cap 4, dimensions a free pick, no reactivity (§5) |
| "The data analysed does not reveal the cause" | Honest — and correct *given what it ran* | |
| Confidence section ends with the raw validator dump ("#36 … replace each with the evidence's own value … #15 … Restate them as what was measured") | Repair instruction shipped to the reader | §3.7 |

### 1.3 Aughor follow-up — "Lets only focus on Direkteingabe and Chrome broswer.."

Same drill-in the Genie conversation did. Result: metric became **"Total Orders"** (not
traffic); approach became **cross-sectional** ("rank the metric across dimensions to find where
value is weakest"); filter `CHANNEL_LVL_0 = 'Direkteingabe' AND BROWSER_NAME = 'Chrome'` returned
**zero rows in all five queries** (`Direkteingabe` exists only at `CHANNEL_LVL_1`); the report
shipped **confidence HIGH** with *"Desktop devices and Windows OS represent the primary segments
… accounting for the majority of order volume."* — fabricated from nothing, and no check fired.
Mechanism in §4.

---

## 2. Ground truth from the source

Method: copied the uploaded CSV to scratch, loaded it into a throwaway DuckDB, plain SQL. No
`aughor` import, no live `data/` touch. Everything below is reproducible from
`data/uploads/default/workspace/traffic/all_dimesnsions_2.csv`.

**Where the entity lives.** `Direkteingabe` appears **only** in `CHANNEL_LVL_1` (28,783 rows,
100,740 sessions), under `CHANNEL_LVL_0 = 'Organic & Brand'`, `CHANNEL_LVL_2 = 'Others'`.

**The trend, normalized for partial months.**

| Month | Days | All channels | Direkteingabe | Share | **Direkt / day** | excl. Chrome 105 / day |
|---|---|---|---|---|---|---|
| Jun | 30 | 138,990 | 29,903 | 21.5% | **997** | 900 |
| Jul | 31 | 166,925 | 37,925 | 22.7% | **1,223** | 1,119 |
| Aug | **18** | 130,188 | 32,912 | 25.3% | **1,828** | 1,439 |

Weekly: ~6–7k in June → 10.5k the last two weeks of July → 12.5–13k in August. There is no
"July peak then correction"; there is a channel growing every month and accelerating.

**Jun → Jul delta (+8,022), by segment — not uniform:**

| Segment | Jun | Jul | Δ | share of Δ |
|---|---|---|---|---|
| iOS · SmartPhone | 12,139 | 16,511 | **+4,372** | 55% |
| Windows · Desktop | 6,760 | 8,052 | +1,292 | 16% |
| Android · SmartPhone | 4,961 | 6,207 | +1,246 | 16% |
| macOS · Desktop | 4,504 | 5,152 | +648 | 8% |
| Mobile Safari (browser) | 8,474 | 12,153 | +3,679 | 46% |

The single biggest day, **Jul 26 (2,728 sessions), had a 23.6% bounce** — a genuine event, not
bots. All major Swedish ISPs rose proportionally. Two ISPs appeared from nothing (Llc
melt-internet 0 → 370; Wiredisp inc. 37 → 329).

**The August accelerant — three slices from Genie's stopping point:**

| Slice | Result |
|---|---|
| Direkteingabe × Chrome × macOS × Desktop | 15,487 sessions, **87.87% bounce** (Genie's finding) |
| … × `BROWSER_VERSION` | **13,170 of 15,487 are version "105" at 99.8% bounce**; real versions (148–151) bounce 15–22% |
| … × `ISP` | Telefónica O2 Germany 97.4%, 1&1 Versatel 98.3%, Vodafone West 99.6% — German ISPs on a `.se` site, 8–10 s sessions |
| Chrome 105 by month | 2,914 (Jun) → 3,246 (Jul) → **7,010 (Aug, 18 days)** — 4× per day; **21% of all August Direkteingabe traffic** |

Chrome 105 is a 2022 UA string. This is a scraper/bot population, and it is why August's
bounce "deteriorated" (Genie's finding 1) and why "direct entry" is rising faster than the human
trend. **Complete answer:** *Direkteingabe is genuinely growing (~20–25%/month per day, mostly
iOS/Mobile Safari in July, with a real Jul 26 event); on top of that, a bot population identified
by Chrome UA 105 / macOS desktop / German ISPs / ~100% bounce quadrupled in August and now makes
up a fifth of the channel. Exclude it before reading the trend; the human trend is still up.*

One table, plain SQL, three slices. No model strength required — only the freedom to take the
next slice after seeing the last one.

---

## 3. Anatomy of run `cb37be54` — the chain of defects

Every item below is from the stored `report_json` plus the code at the cited lines.

### 3.1 Intake: the observation label lied and the window was the whole dataset

The LLM's `IntakeOutput.observation_label` came back **"February 2025"** — the schema's own
example string (`prompts_investigate.py:697`: *"Human label, e.g. 'February 2026'"*; also
`:56`). The T4-2 coverage stamp (`investigate.py:4848-4856`) replaced the *window* with the full
coverage span `2026-06-01 → 2026-08-18` but rewrites the *label* only for cross-sectional runs or
a blank label — a temporal run keeps the stale model label. `AnswerReport.observation_period`
copies it straight through (`:8621`), and the PDF prints it as "AT A GLANCE".

### 3.2 The coverage clamp collapsed comparison onto observation — and told no one downstream

`_clamp_intake_to_coverage`, `investigate.py:3518-3524`:

```python
if ce_ < dmin or cs_ > dmax:   # no overlap → no prior period exists
    intake.comparison_start, intake.comparison_end = intake.observation_start, intake.observation_end
    intake.comparison_label = "Same period (no prior period exists in the data)"
    notes.append("… no prior period exists — trend/YoY/baseline comparisons are not possible")
```

The note goes into `intake_notes` → the intake finding's `interpretation` (`:4801`) → the
synthesis evidence log. **It never reaches `DECOMPOSE_PLAN_PROMPT`** (`prompts_investigate.py:
232-275`), which is formatted at `investigate.py:5661-5674` with `obs_start == comp_start` and
`obs_end == comp_end` as bare literals and instructs the CASE-WHEN-pair shape (`:261-268`). The
coder did exactly what it was told: `obs_traffic`, `comp_traffic`, `abs_change` — 0 on every row.

And the phases were **not told to stop**: the note says comparisons "are not possible", then
the baseline and decomposition phases run a period-over-period analysis of a period against
itself. The only place that *reads* the equality is to **skip other guards**: `:3547`
(`_is_same` suppresses the duration-mismatch guard) and `:5549` (premise check
`raise ValueError("degenerate values — skip")` when `obs_v == comp_v`). The collapse silences
its own safety net.

### 3.3 Z-score over a window that precedes the data, and nothing reacts

`BASELINE_PLAN_PROMPT` asks for *"at least 13 consecutive periods"* and a z-score that
*"EXCLUDE[s] the observation period from baseline stats"* (`prompts_investigate.py:164-172`).
With 79 days of data, the coder's 13-month baseline is 2025-06-01 → 2026-06-01: zero rows, NULL
mean/stddev. No SQL-level date guard checks literals against `[dmin, dmax]` (only the
relative-date guard at `:5088-5112`). When stats come back NULL: `code_sigma = None` →
`code_significant = None` → `route_after_baseline` (`:133-181`) falls through to "proceed
(conservative: don't block)". No grain switch, no shorter baseline, no skip. The narrator wrote
prose around NULLs because one row of `(NULL, NULL, NULL)` counts as usable data
(`_has_usable_data`, `:1637-1641`).

### 3.4 The tautological decomposition earned its place and was narrated as a finding

- `_neutralize_baseless_contribution` (G1, `:2038-2089`) catches an **all-NULL** comparison
  column, not an **equal** one.
- `_is_zero_variance_ranking` (`:2349-2362`) selects the measure column by name regex
  `_MEASURE_COL_RE = (share|rate|pct|percent|metric_total|metric_value|_of_total|factor|ratio|utili[sz])`
  (`:2331-2332`) — `abs_change` / `obs_traffic` / `comp_traffic` match nothing ⇒ `return False`
  ⇒ `_finding_earns_place` keeps it.
- No `observation_window != comparison_window` assertion exists anywhere (searched
  `investigate.py`, `orchestrator.py`, `report_checks.py`, `tools/stats.py`, `phase_waves.py`).

So the narrator received, as evidence, a table proving every segment equals itself, and wrote
the only sentence that table licenses: "uniform … not localized … broad volume-based shift."
The model was **correct about the table and wrong about the world**, and only code could have
known the difference.

### 3.5 The contradiction detector manufactured a tension and ordered the model to resolve it

`detect_contradictions` (`orchestrator.py:224-252`) reads **phase summary prose only** (`:237`)
against two word lists (`_SIG_POSITIVE`, `_SIG_NEGATIVE`, `:212-216`). Baseline said "notable
peak"; decomposition said "no significant variation" ⇒ `significance_flip`, severity high, *"You
MUST resolve this tension explicitly in your report — do NOT paper over it."* It ignores the
deterministic `is_significant` flags and `stat_note`s that exist (`aughor/tools/stats.py`). Note
`\bsignificant\b` in `_SIG_POSITIVE` also matches inside "no significant variation" — a single
phase can contradict itself. Here the "within normal variance" side was an artifact of §3.2, and
the model had no channel by which to learn that.

### 3.6 Partial month read as a "correction"

August has 18 days. Monthly `SUM(TRAFFIC)` 32,912 < July 37,925 ⇒ "partially correcting". Per
day, August is the highest month. Nothing in the temporal phases supplies day counts or
normalizes a partial terminal period; the adaptive-grain step (`:5246-5270`) rewrites
`DATE_TRUNC` only from the SQL's literal span and never from results. Genie made the same
omission; only the source query in §2 surfaces it.

### 3.7 The checks fired on prose, the wrong prose, and shipped their own repair instruction

`aughor/agent/report_checks.py` (388 lines) — seven executable checks (`:366-388`) over
`headline + executive_summary + closing_summary` only (`:377-378`):

- **#36 `check_grounding` (`:176-214`).** Thousands separators *are* normalized (`:158`,
  `:200`); `37,925` and `29,903` are grounded. **The sole trigger was `26.8`** — a correct
  derived percent change; `_evidence_number_set` (`:139-173`) does roundings and ×/÷100 and **no
  arithmetic derivation**. The explorer path *has* derivation credit
  (`aughor/explorer/verify.py:469-489`: `(b-a)/a*100`, `b/a*100`, `b-a`, within 1%) — the deep
  path does not use it. The loop `break`s at the first miss and appends the **whole sentence**
  (`:205`), so the message "these figures do not appear anywhere in FULL EVIDENCE: … 37,925 …
  29,903 …" presents two correct numbers as fabrications. The model did break the prompt rule
  (`prompts_investigate.py:645`: *"Never estimate or derive one"*) — i.e. the rule forbids the
  model from computing a percent change.
- **#15 `check_claim_type` (`:343-363`) → `overreaching_sentences` (`claim_type.py:149-170`).**
  A regex word list (`_CAUSAL_VERB_RE`, `claim_type.py:37-45`) containing
  `increas(?:e|es|ed)` / `decreas…`; the annotation "(increase)" is `m.group(0)`. At the
  `descriptive` licence all three verb families are forbidden (`:158-159`). The title was flagged
  because it has no terminal period and fused with the first summary sentence (`_SENTENCE_RE`,
  `:74`); "shows no significant variation … comparable increase" was flagged because
  `_NEGATION_RE` (`:66-72`) strips only four words after a negator. **The licence directive the
  model is given (`claim_type.py:145-148`) says "Report what the data contains and how it
  changed"** — and the checker forbids the verbs of change. Program AT's rule (*"key on claims
  and structure, never on vocabulary"*, `docs/ANSWER_TRUTHFULNESS_ROADMAP_2026-08-16.md:51,
  327-328`) is imperfectly applied: the licence is structural, the sentence match is a word list.
  No test covers `increase`/`decrease` (`tests/unit/test_claim_type.py`).
- **The leak.** `investigate.py:8323-8365`: one inline retry (`:8340`), then residual violations
  are concatenated into `confidence_justification` (`:8358-8361`) — the same second-person
  repair string (`"replace each with the evidence's own value"`, `"Restate them as what was
  measured"`) designed at `report_checks.py:9-10` as *"the shape a one-shot retry can act on"*.
  The PDF renders it verbatim (`aughor/export/document.py:377-379`); the web UI dropped the
  field from the body (`web/components/InvestigationReport.tsx:429-431`), which is why nobody saw
  it until a PDF. Documented as intended disclosure (`docs/PITFALLS.md:4-8`,
  `ANSWER_TRUTHFULNESS_ROADMAP:119, 317-319`) — the translation step from *instruction* to
  *disclosure* was never built. 10 of 144 stored deep reports carry it, all since 2026-08-15.

### 3.8 The plan that never reached the graph

`ada_intake` builds a plan (`plan_phases`, `orchestrator.py:101-146`) and writes
`out["_orchestration_plan"]` (`investigate.py:4941`). `_orchestration_plan` is **not declared on
`AgentState`** (`aughor/agent/state.py:431`; siblings `_ada_intake`, `_baseline_sigma`, …
`_wave_next` are, at `:545-564`). LangGraph filters node output to declared channels
(`langgraph/graph/state.py:1447`), so `state.get("_orchestration_plan")` at `:8120` is always
`None` and `plan_reconciliation` reconciles against `[]`. **144 / 144 stored deep reports have
`orchestration_plan: null`.** `_baseline_rel_change` (`:5628`) has the same defect, so the
decompose-under-abstention branch in `route_after_baseline` (`:158-163`) never fires on the serial
path. No test asserts either reaches state.

---

## 4. Anatomy of run `7774b792` — the follow-up that fabricated

1. **No session.** The deep branch of the frontend posts `history` but **no `session_id`**
   (`web/lib/useChat.ts:147`; the auto and quick branches do). Backend `resolve_history` could
   not reconstruct; `history` empty.
2. **Not recognized as a follow-up anyway.** `is_followup` (`aughor/agent/followup.py:24-36`)
   matches `only (the|those|that)` — "only focus" does not — and the only use of history on the
   deep path is `_followup_origin` (`routers/investigations.py:3719-3722`, `:3428-3459`), which
   also requires the prior turn to carry `sql`. No other channel carries the prior intake spec
   (metric, filters, windows) into a deep follow-up (`initial_state`, `:3732-3760`).
3. **Metric by prompt default.** The question names no metric; `INTAKE_PROMPT` falls back to
   *"the primary revenue / value measure in the schema"* (`prompts_investigate.py:37-39`) ⇒
   `SUM(ORDERS)`.
4. **Approach forced cross-sectional.** `_is_temporal_change_question` (`_TEMPORAL_CHANGE_RE`,
   `investigate.py:3836-3844`) needs a cause-word plus a change verb; "focus on X and Y" has
   neither; `has_segment` forces `cross_sectional = True` (`:4536-4551`).
5. **Filter by the coder, no value index.** The value→column resolver
   (`aughor/semantic/answer_resolution.py:608`) is called only on the quick `/chat` path
   (`routers/investigations.py:2056`, `:4557`), never under `investigate.py`. Run 1's coder hedged
   `LVL_0 OR LVL_1 OR LVL_2`; run 2's did not. `check_filter_value_domains`
   (`aughor/sql/join_guard.py:715-760`) probes each literal per column **independently**
   (`by_col[(t,c)]`) — both values exist in their columns — **there is no check that the
   conjunction matches any row.** `zero_row_suspicious` (`sql/executor.py:31-49`) recognizes only
   `CAST(… AS DATE)` and id-vs-date shapes.
6. **The honest-confidence floor is dead.** `investigate.py:8395-8397` keys on
   `(f.get("columns") or [])` — a zero-row query still has cursor columns
   (`connectors/file/local_upload.py:1343`), and the synthetic intake finding
   (`columns=["field","value"]`, `:4776-4812`) *always* satisfies it. The correct predicate exists
   at `:1637-1641` (`_has_usable_data`, `row_count > 0`) and is not reused. The zero-row honesty
   instruction (`:8095-8098`) is attached only to the Tier-0 early-stop note, which cannot occur
   on a cross-sectional run.
7. **No check sees number-free prose.** `check_grounding` skips anything `< 10` or non-numeric;
   "majority", "primary segments" are unfalsifiable to it. No check exists for claims with zero
   evidence rows, for confidence vs. evidence emptiness, or for superlatives without numbers.

Net: every deterministic gate passed, and the narrator — handed five empty tables and a rubric
("HIGH = phases converge") — converged on nothing and called it HIGH.

---

## 5. Where the intelligence actually is — the control-flow map

`aughor/agent/investigate.py` (~8.7k lines) + `prompts_investigate.py` + `orchestrator.py` +
`phase_waves.py`. Roles: `coder` (intake, phase SQL, repairs), `fast` (phase interpretation),
`narrator` (synthesis, check-retry, follow-ups) — `aughor/llm/provider.py:58, 570-573`.

| # | Call | Where | Role | Decision or narration? |
|---|---|---|---|---|
| 0 | route classifier | `nodes.py:125-130` | — | **skipped** when mode is investigate (`nodes.py:169-180`) |
| 1 | intake spec (+ up to 3 constrained retries) | `investigate.py:4454-4459` | coder | **DECISION** — the only broad one; then post-processed by ~10 code steps (§3.1–3.2) |
| 2 | phase plan ×N (SQL text in a slot-filled template) | `:5081-5082` in `run_analysis_phase` (`:5027`) | coder | **DECISION, boxed** — metric, table, date column, both windows are literals; "write 2–3 queries"; executed `cap=4` (`:5031`) |
| 2b–d | temporal-guard / fan-out re-plan; one SQL repair per failing query | `:5095-5108`, `:5179-5194`, `sql/executor.py:381-385` | coder | repair, result-blind (regex/AST over SQL text) |
| 3 | phase interpret ×N | `:5307-5309` | fast | **narration**; rows capped by `interpret_max_rows` 12/36 |
| 4 | synthesis (+ one fast rescue, + one check-retry) | `:8295-8302`, `:2776`, `:8341-8343` | narrator | **narration**; evidence budget 6,000 / 18,000 chars (`profile.py:109,135`), ≤20 rows per finding (`:3060`), overflow condensed to 6 rows / 1,200 chars (`:3094-3095`) |
| 5 | follow-up questions | `routers/investigations.py:3891-3899` | narrator | narration |

**Phase order is pure Python**: `route_after_intake` (`:115-120`, the `cross_sectional` bool) →
`route_after_baseline` (`:133-186`: regex, sigma ≥ 2.0, rel-change ≥ 0.05, LLM flag last) →
`route_after_decompose` (`:188-215`) → `route_after_dimensional` (`:896-909`). The
orchestrator's own design note (`orchestrator.py:15-24`): *"the Orchestrator does not decide
phases with a model — it mirrors the deterministic gates and makes them visible."* Under
`phase_waves.py` the three middle phases run **concurrently** (`:68-70`) and the prior-phase
summaries they inject are *"soft context with shipped fallbacks … flavour, not structure"*
(`:8-11`) — the last cross-phase link is severed for parallelism. The next phase's planner never
sees the previous phase's **rows**, only its prose summary.

**What exists that reacts to results:** `_has_usable_data` (skip the narrator), G1
neutralization (all-NULL comp), premise re-anchor (`:5487-5590`, one 3-way probe that can
rewrite windows — but aborts on `obs == comp`), `_prune_and_rank_phases`, confidence floors.
**What does not exist:** NULL stats ⇒ change grain or baseline; zero `abs_change` ⇒ other
dimensions; zero rows ⇒ relax filter; abandon a phase; re-plan after results at any altitude.
`replan`/`route_after_replan` exist (`nodes.py:1400`, `graph.py:229-235`) **only on the quick
"direct" branch**; the ADA edges (`graph.py:207-225`) go strictly forward.

**Typical run: 7 LLM calls — 3 decisions (all before any result), 4 narration.** Full 5-phase
run ≈ 12 calls, decisions still ≈ 5. Model-strength knobs (`aughor/llm/profile.py:47-155`):
schema 20k/60k chars, evidence 6k/18k, interpret rows 12/36, output 4,096/8,192,
`structured_attempts` **1 at every tier**, reasoning effort low/medium, `tool_loop_steps` 4/8
(**converse only**). Tier is earned by declared context ≥ 128k (`:159, 270-279`).

**The tool-loop analyst exists and is walled off.** `run_tool_loop`
(`aughor/agent/tool_loop.py:105-246`) driven by `converse()` (`converse_tools.py:453-483`), roster
`answer_question, run_sql, list_tables, describe_table, deep_analysis, + platform tools`
(`:365-441`), latitude-granting states-not-scripts prompt (`:486-546`), SQL guards *inside* the
tools. On this question it would `list_tables`, probe the date span, **see** that the comparison
window is empty, pick a daily grain, run the decomposition itself, **see** `abs_change = 0`, and
either widen or say plainly there is no prior period — within 4–8 steps, because it sees each
result before choosing the next call. But `_converse_eligible`
(`routers/investigations.py:4410-4434`) ends `return route.depth != "deep" or route.forced ==
"dossier"` after `if not converse_available() or req.escalate: return False` — Analysis Mode
(`depth_override`, `:4765-4770`) and "investigate deeper" are hard exclusions, and `ask.converse`
is **default off** in a deployment (`kernel/flags.py:84, 268`; local runs it on). CI-4's
`deep_analysis` tool is real (`converse_tools.py:264-308`) — a conversation can reach *down* into
deep analysis; a deep request can never come *up* into a conversation.

**Where the posture came from.** `orchestrator.py:19-23` cites the R4 ablation
(`docs/R4_ABLATION_EVAL_2026-06-21.md`): n = 12 questions, one warehouse, one model. It showed
two things: deterministic **SQL** guards (fan-out, value-domain, id-arithmetic) are pure upside,
and injecting **exploration context** into SQL generation regressed accuracy 92% → 58%.
Neither result is about whether the model may choose the next *query*. The design note
generalized a SQL-verification finding into an analysis-restriction architecture. This is the
Track-A decision rule's distinction exactly (`docs/ROADMAP_INTELLIGENCE_AND_CHAT_2026-08-01.md`):
*if a smarter model makes the mechanism unnecessary it is a RESTRICTION — scale it with the
model; if no model strength fixes the failure (fan-out) it is VERIFICATION — keep it.* The
Verifier is verification. The fixed phase script, the pre-committed windows and dimensions, the
"2–3 queries", the prose-only cross-phase link, the "never derive a number" rule, and the
word-list checks are restriction.

---

## 6. Verdict on the hypothesis

**"Our guards are choking the raw intelligence of LLM models."**

- **True for the prose layer.** A correct derived `26.8%` was flagged; the verbs of change were
  forbidden under a licence that asks the model to describe change; a capped evidence log and
  "never derive" make the narrator a formatter. And the failure mode of a misfire is
  customer-visible.
- **Not what lost the analysis.** The model was never in the loop where the analysis is
  decided. Genie's model was not smarter about this data; it was *allowed to look at a result
  and choose the next query*. Aughor's coder chose DEVICE_CLASS and BROWSER_NAME blind, was
  handed two identical windows without being told, and its narrator then faithfully described a
  table that said nothing. Removing every check in `report_checks.py` would have shipped the
  same wrong report — with a cleaner Confidence section.
- **The guards that matter are missing, and the ones present key on words.** Window
  degeneracy (code *created* it and then suppressed its own detectors on it), partial-period
  normalization, zero-row conjunctions, row-count-based confidence, a measure-column regex that
  omits `change`/`delta`, a contradiction detector over prose instead of `is_significant`, a
  sentence splitter that fuses the title into the first sentence. Vocabulary guards fail open on
  the unlisted word and fail closed on the listed one.
- **Two classes of defect, two classes of fix.** The bugs (dead `_orchestration_plan` channel,
  `columns`-vs-`row_count` floor, label not rewritten, leak concatenation, derivation credit,
  negation window, session_id on the deep branch, conjunction-domain check) are each small and
  local. The architecture (no result-reactive step; deep walled off from the tool loop) is one
  decision, already written down as CI-4 and not finished.

---

## 7. What this implies

Not a plan — the shape the evidence points at, so the next decision is made on it.

1. **The deep path needs a result-reactive analyst, not more narration.** The tool loop that
   already exists for quick chat is the right engine: phases become *tools* the model can call
   (`baseline`, `decompose(dim, windows)`, `z_score`, `premise_check`, `run_sql`), the SQL
   Verifier stays inside every tool, and the model sees each result before choosing the next
   call. CI-4 as written (*"deep routes become a `deep_analysis` tool the conversation invokes,
   streaming the investigation's frames through the turn"*) is half-built; the missing half is
   the door (`_converse_eligible`) and the frame streaming (CI-6a). The step budget (4/8) is a
   `ModelProfile` knob — it scales with the model, as Track A intends.
2. **Move the guards from the prose to the evidence.** A comparison window equal to the
   observation window is a *stop*, not a note. A terminal partial period is normalized or
   labeled. A zero-row conjunction is probed before the phase runs (the per-column check exists;
   the conjunction check does not). Confidence floors key on `row_count`. The
   contradiction detector keys on `is_significant`, not adjectives. These are verification in
   the Track-A sense: no model strength prevents them.
3. **Claim checks bind claims to evidence, not words to lists.** Derivation credit
   (`explorer/verify.py:469-489` already does it); `[claim] → [evidence id]` binding (the
   scientific-agent-skills study's pattern); a causal check keyed on *asserted relationships*
   (X caused/drove Y with both sides named), not on `increase`. And a repair instruction is never
   a reader-facing string — the reader gets the *disclosure* ("one figure in the summary is
   derived, not quoted"), the model gets the instruction.
4. **Follow-ups carry the spec.** The deep branch sends `session_id`; a deep follow-up inherits
   the prior run's metric, filters and windows unless the question changes them; `is_followup`
   is not the only door.
5. **Fix the dead channels and the dead floor first** — they are one-line each and they are
   silently falsifying 144 reports' provenance and every zero-row report's confidence.
6. **On the chat-framework question that started this thread:** the "structured chat
   framework" and the "structured investigation pipeline" are the same design instinct —
   structure where the intelligence should be, with the model narrating a shape code chose. The
   chat surface that shows *tool steps as they happen* (the parts model; what the Genie
   conversation looked like) is the natural home for an analyst that slices in the open. So the
   shell decision is downstream of this one: first let the model analyze; then the conversation
   that renders it is mostly already built.

---

## 8. Addendum — the charts (why Genie's read as "terrific" and ours as "yuck")

**What Genie does:** the subject is highlighted and the rest is gray (emphasis form: Chrome red,
seven browsers muted); the grain matches the finding (daily bars show the Jul-26 spike); values
sit on the points that matter (three monthly bounce rates); axes carry units; one theme, one
title style. One demerit: the daily chart is dual-axis (traffic bars + bounce line) — the #1
chart anti-pattern; it survives only because the spike is enormous.

**What ours do — measured, not taste** (dataviz method; palette run through the six-check
validator against our dark surface):

| Symptom | Cause | Where |
|---|---|---|
| "Red & orange" | `severityRamp` paints each bar darker-where-bigger on a RED ramp for any "cost"-named column — a value ramp on nominal categories (double-encodes length as hue). Diverging green/red is hardcoded hex, not tokens. | `web/components/charts/exhibit.ts:60-63,85`, `echarts/builders.ts:460-467` |
| Bars "miles apart" | `barMaxWidth: 34` + fixed 350px height + category band stretched across the card: 3–4 categories ⇒ 34px bars, ~150px of air. Height adapts to bar count; width never does. | `echarts/builders.ts:476-479`, `web/components/Chart.tsx:300-320` |
| Rainbow | 6 saturated hues + a 12-hue overflow ramp. Validator: the 6 tokens **FAIL the lightness band** (3/6 dark), CVD WARN ΔE 7.6; a 10-category chart with the overflow **FAILs CVD at ΔE 4.9**. | `echarts/theme.ts:38-49` |
| No focus | No emphasis mode exists; exhibit knows `severity` and `diverging` only. The backend knows the subject (intake filters) and never passes it. | `exhibit.ts` |
| A number on every bar | Deep report ships labels ON for every mark. | `ResultChartCard.tsx:139` |
| SQL aliases as legend; no axis units | Series names = humanized alias (`Obs Traffic`); raw in the PDF (`obs_traffic`). Bars have no axis title. | `echarts/builders.ts:108`, `aughor/export/charts.py:456` |
| Titles are query names | "Traffic Decomposition by Device Class" vs a claim. | finding `title` → `withTitle` |
| Wrong form | Coder picks from a 24-option `chart_type` Literal, then a 364-line inference re-guesses. A 3-point monthly line with a truncated y-axis (30K–38K) should be stat tiles or a bar; a 20-browser grouped bar of two identical series should be a top-N delta bar + Other. | `prompts_investigate.py:740`, `chartTypeInference.ts` |
| Two renderers, two looks | PDF is a separate 676-line matplotlib port mirroring hex values but not rules (white surface, autoscaled y, raw legends, rotated ISO dates). Drift is structural. | `aughor/export/charts.py` |

**What to do, in order:** ① emphasis form, default whenever a subject exists (`exhibit.emphasis`
stamped from intake filters; accent + one de-emphasis gray) — most of the "wow" is this one change
② palette by computation: re-step the 3 failing tokens, delete the overflow ramp (past 7 ⇒ "Other"
or facet), one series = one hue, no value ramp on nominal categories, diverging from tokens;
validator in CI for light and dark ③ mark specs: bar width from the band (`barCategoryGap` ~35%,
cap ~48px) + a max plot width for ≤4 categories; 2px surface gaps; 4px rounded ends; 2px lines;
solid hairline grid; SELECTIVE labels; axis titles with units; grain-formatted date ticks
④ title = claim, subtitle = scope·period·unit; query name to tooltip ⑤ form by job (magnitude →
bar one hue; trend → line at the grain that shows the event; identity ≤7 then Other; period-over-
period → delta bar/dumbbell, never grouped obs/comp; one row → stat tile; >7 classes → table) —
replace the Literal + inference ⑥ one renderer: PDF charts from the same ECharts spec via SSR
(SVG); matplotlib goes ⑦ look at it: `/chart-lab` is the harness — re-render the specimen's four
charts and screenshot. None of this depends on the model.
