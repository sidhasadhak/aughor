# Answer Truthfulness Roadmap — Program AT (2026-08-16)

**What this combines:** the concept-typing plan (five layers of evidence for what a
column *is*, drawn from the "how did BigQuery know Latitude?" question) and the
scientific-agent-skills study (K-Dense-AI, MIT), reduced to the two mechanisms that
change outcomes rather than produce receipts. Both were built on top of one live
investigation, re-run six times in one day, so every wave below cites the run that
motivated it. Slots into `PLATFORM_ROADMAP_2026-08-12.md` as **Program AT**, on the agent
plane, and it is the accuracy half of what Arc CI's prompt-economy section (§2.6) began:
trust the model, verify in code.

**Baseline:** branch `claude/answer-truthfulness-at1`. `aughor/agent/relationship.py`,
`aughor/agent/claim_type.py`, `_ranking_noise_caveat`, `check_noise_findings_not_cited`,
`check_significance_claims`, `check_claim_type`, `assess_correlation` / `assess_group_means`,
and 108 tests across `tests/unit/test_relationship_scan.py` and `tests/unit/test_claim_type.py`.
Eight live runs of *"Is there a correlation between shipping delay and customer location?"* on
`workspace/data_co`.

**Status 2026-08-17: Track 1 COMPLETE** (AT-1, AT-2, AT-3 — §2, receipts in §7).
**Track 2 COMPLETE** (AT-4, AT-6, AT-7, AT-8 — §8) plus **AT-5's bounded-numeric half — §9**.
All five evidence layers now exist. AT-5's remaining half — the bundled vocabulary
(ISO-3166/4217, US states, country and weekday names) — is scoped and not built.
**AT-0 re-measured and verified — §3.2.**

---

## 0 · The thesis — one witness is not a type, and a computed verdict is not a delivered one

Six runs of one question, and every defect had one of two shapes.

**Shape A — one witness spoke and the system believed it.** The column NAME said
`Late_delivery_risk` was a risk score; the VALUES said it was a 0/1 flag. The LOADER said
`Latitude` was `VARCHAR`; the values said coordinates. `_GEO_CODE_PATTERN` in the profiler
still says a latitude is a *key*. Intake read "shipping delay" twice and produced a metric
and a driver segment from the same column — a 100%/0% tautology that every SQL-shape guard
passed, because they all check the SQL string and none check whether the two sides are two
things.

**Shape B — a verdict was computed and not delivered to whoever wrote the next claim.** The
statistic sat on the finding as `stat_note`; the finding narrator wrote *"the significantly
higher delay in Oklahoma"* over `p = 0.072`; the synthesis wrote *"driven by localized
bottlenecks"* over `Ilam | 3.2 | n=5` because `_one_phase_evidence` emitted rows and never
the verdict; then the summary said *"not significant (p > 0.05)"* over `p = 2.4e-155`. Three
altitudes — finding narrator, synthesis, report check — three separate fixes, one cause.

Two corollaries the day proved:

- **Every guard that keyed on a WORD produced a false positive within two runs**
  (`significant` under negation, `Central Asia` named as one end of a stable range). The two
  that keyed on **code-written verdicts** (`stat_note`, a parsed p-value) did not. Guards
  key on claims and structure, never on vocabulary.
- **Fixing one thing moves the defect one layer, not away.** Right metric → wrong column →
  right column but overclaimed → honest conclusion with a false reason → honest, with a
  guard misfiring. Each round was smaller. Plan for the next round, not for "done".

Program AT is those two theses as engineering: **two independent witnesses before a
concept becomes a type**, and **the claim type is set once at intake and gates every
sentence after it.**

---

## 1 · What was built (2026-08-16) — the floor this program stands on

All live-proven on `data_co` (180,519 rows); all uncommitted at time of writing.

| seam | what | run that motivated it |
|---|---|---|
| `relationship.self_referential_segment` | driver segment ∩ metric columns ⇒ dropped with a receipt in `intake_notes` | `5dc26c2c` (100%/0% led the report) |
| intake MAGNITUDE GUARD + TWO SIDES RULE | prefer the measured quantity over a 0/1 flag; X and Y must be different columns | `5dc26c2c` |
| `relationship.plan_relationship` | numeric×numeric → `CORR`; numeric×category → group means → one-way ANOVA; category×category → existing chi-square. Typed by the pair, not by a planner | `8f83b1b4` (country-only, two values) |
| `numeric_expression` | `TRY_CAST` probe on text; a failed probe = "not a number", never a confident zero | `8f83b1b4` (`Latitude` VARCHAR) |
| `relationship_right_alternatives` | test every column of one concept, report the strongest, name the rivals with their share | `8f83b1b4` |
| `_ranking_noise_caveat` (rate + mean branches) | Wilson/Bonferroni for a rate; ANOVA from group SDs for a mean; a volume-only fallback | `8f83b1b4`, `3bfce2ee` (n=1–21 as "bottlenecks") |
| `_population_note` follows sort order | the interpret prompt said "BOTTOM of the distribution" over a DESC scan | `5dc26c2c` (73–81% "range" = top 15 of 563) |
| `_is_saturated` in `_finding_earns_place`; re-plan accepted only if it REDUCES saturation | the old acceptance was `not all(saturated)` — admitted the tautology | `5dc26c2c` |
| `_one_phase_evidence` + `_condense_phase_evidence` carry `stat_note` | synthesis never saw the verdicts | `3bfce2ee` |
| `_results_text_with_verdicts` | finding narrator sees the verdict BEFORE writing | `54df16fa` |
| `_lead_with_verdict` (negation-aware) | backstop: verdict prepended when the model contradicts it anyway | `c88a3baf` |
| `check_noise_findings_not_cited` (claim-in-sentence, not label) | headline can't cite a noise-flagged standout | `3bfce2ee`, false-positive fixed after `34932b1f` |
| `check_significance_claims` | "not significant" refused when the run's own p < 0.05 | `54df16fa` |
| `assess_group_means` 1–6% η² band | "does differ" → "accounts for 1.1% … too little to treat as a driver" | `3bfce2ee` |
| `read_relationship(truncated=…)` | `MAX_ROWS=500` truncates BELOW the SQL LIMIT and the prose stays self-consistent | proof harness |

Known-remaining in the last run (`34932b1f`): the PE-2 waterfall check fires on a
cross-sectional null (the synthesis invents a `-0.011 days` "cause" at 100%) — a template
applied to a design that has no attribution to decompose. That is Wave AT-1's first customer.

---

## 2 · The waves

Two tracks, sequenced so each wave retires guards rather than adding them.

### Track 1 — Claims (from the skills study; the accuracy lever)

**AT-1 · Typed claims at intake, gating every sentence after.** ✅ **DONE 2026-08-17.**
Add `claim_type ∈ {descriptive, associational, predictive, causal}` to `IntakeOutput`,
set deterministically from the question shape and the design (a cross-sectional scan of an
observational table is at most `associational`; a period-over-period decomposition with a
baseline is `descriptive` of a change; `causal` requires an intervention column or an
explicit user assertion). Then:
- the phase narrator and synthesis system prompts receive the type and the **verbs it
  admits** — one line, not a lecture;
- `report_checks.check_claim_type` refuses causal verbs (`drives`, `driven by`, `leads to`,
  `causes`, `results in`, `improves`, `reduces`) in headline / summary / closing when
  `claim_type` is below `causal` — negation-aware, sentence-scoped, using the
  `makes_unnegated_standout_claim` shape;
- the attribution waterfall is **not requested** when the type is `associational` on a
  cross-sectional design (retires the `-0.011 days` false cause and the PE-2 misfire).
*Retires:* `_STANDOUT_CLAIM_RE` as a primary guard (it becomes the backstop);
the two synthesis retries per run that runs 5 and 6 spent on precludable violations.
*Proof:* re-run the six-run question; `report_check_retry` = 0; headline contains no
causal verb; ≥ 5 of the 38 pitfalls provably unwritable.

**AT-2 · The numbered-pitfalls contract.** ✅ **DONE 2026-08-17** — `docs/PITFALLS.md`.
`docs/PITFALLS.md` — the 38 from `statistical_pitfalls.md`, renumbered and reworded for
aughor's vocabulary, each tagged *enforced-by:* a check name or *advisory*. The narrator
prompts cite by number (`avoid #3, #11, #32`); each existing check names the pitfall it
enforces in its violation string; the report's `confidence_justification` cites the number.
Writer, checker, and reader share one vocabulary. Zero model cost.
*Proof:* every `report_checks` violation string carries a `#n`; the doc lists which of the
38 are enforced, which advisory, which not applicable — no silent gaps.

**AT-3 · Percent-scale-aware grounding.** ✅ **DONE 2026-08-17.** `check_grounding` false-positived on
`81.32` vs `0.8131868` in run 1 and knocked a correct report to MEDIUM. Add ×100 / ÷100
to the rounding set. The claim↔evidence ID binding from the study is *not* adopted — it is
a receipt system whose only accuracy win this fix delivers in twenty lines.

### Track 2 — Concept typing (from the five-layer plan; the comprehension lever) — NOT STARTED

**AT-4 · The contract: two witnesses make a type.** ~½ day.
`ColumnProfile` gains `concept: str`, `concept_confidence: float`,
`concept_evidence: list[str]`. **`semantic_type` is untouched** — 15 modules read it as
truth, and the plan is to add a stricter field beside it, not to break them. One function,
`_resolve_concept(witnesses)`, is the only writer: a concept is assigned when ≥ 2 witnesses
from **different layers** agree; a lone witness is stored as a hint with confidence < 0.5
and drives nothing. A human override in `ColumnFlags` is a witness with confidence 1.0.
*Ratchet from day one:* `concept` may only be set by `_resolve_concept`; any consumer must
read `concept_confidence`. Same shape as `test_no_model_id_ships_in_the_product`.

**AT-5 · Value-shape witnesses.** ~2 days. `aughor/tools/shape.py` — pure functions
`(sample) → (concept, confidence, evidence)`, run at profile time on the samples the
profiler already holds plus one `TRY_CAST` probe for text:
bounded numeric (lat ±90 with ≥4 dp and high cardinality; lon ±180; percent 0–1 / 0–100;
binary 0/1) · checksummed (Luhn, IBAN mod-97, ISBN-13, EAN) · grammar (ISO-8601 in text,
E.164, RFC-5322, UUID, ISO-4217, ISO-3166 alpha-2/3, ZIP/ZIP+4, IPv4/6) · categorical
fingerprint (values ⊂ weekday/month/country names in ~6 languages — `EE. UU.`).
The name is never consulted here; that is the point. Immediate consequence: a coordinate
column carries range + cardinality evidence that outvotes `_GEO_CODE_PATTERN`'s "key".

**AT-6 · Pair coherence.** ~2 days. `aughor/tools/pairs.py` — the concepts that only exist
as pairs, each with a *computed* test:
- **coordinates**: one column in ±90, one in ±180, and the sampled (lat, lon) points cluster
  on populated land against a bundled ~1,000-city centroid table (small, offline). Only
  coordinates pass this.
- **actual/planned** (`Days for shipping (real)` / `Days for shipment (scheduled)`): same
  unit, shared stem, one carries a planning word, the difference is centred near zero with a
  right tail → derived concept `duration.delay` with the subtraction as its expression.
  *This is what intake had to invent by itself in runs 2–6.*
- **start/end** → duration; **gross/net** → deduction; **qty × unit_price ≈ total** → an
  arithmetic identity verified on the sample.
Pair coherence is itself a second witness for each member — `Latitude` reaches a type on
range (L2) + partner (L3) without its name ever being read.

**AT-7 · The operations vocabulary.** ~1½ days. A small YAML in `ontology/` — not ingested
standards; a curated concept → *admissible operations* map:
```
geo.coordinate_pair:  distance, containment, cluster, corr_with_numeric; never SUM/AVG
duration.delay:       AVG, percentile, group_means, corr; signed
flag.binary:          rate = AVG; never a magnitude; never a driver of its own source
code.iso3166:         join to country dims; group; never arithmetic
money.amount:         SUM only within one currency; requires a currency witness
```
Consumers: `plan_relationship` (reads `coordinate_pair` → tries `CORR` and clustering
unprompted), the intake MAGNITUDE GUARD (reads "flag derived from a delay" → picks the
delay), `_semantic_type` (reads `geo.latitude` → stops calling it a key), the
currency-VARCHAR guard already in memory.

**AT-8 · Usage-role witnesses.** ~1 day, last. Feed `query_log_miner` + `column_popularity`
back: `GROUP BY`'d → dimension; `SUM`'d → additive; `WHERE col = 1` → flag; joined-on →
key; never grouped, never summed, always co-travelling → geometry. Accretes without config.

---

## 3 · Sequencing and the pre-check that could kill Track 2

```
AT-1 typed claims ─┐
AT-2 pitfalls ─────┼─ Track 1: ~2 days, retires guards, proves on the six-run question
AT-3 grounding ────┘
                      ▼
AT-0 pre-check ─── ½ day: MEASURE THE PREMISE before AT-5/6
                      ▼
AT-4 contract ─── AT-5 shapes ─── AT-6 pairs ─── AT-7 ops ─── AT-8 roles
                    (~7 days total; ~2½ for the part that changes the six-run outcome)
```

**AT-0 — grep the data, not the docs.** Across the demo canvases and every uploaded
workspace: how many text columns are numeric-castable; how many numeric columns sit in
±90/±180 with a partner; how many binary flags sit beside a same-stem duration. If the
answer is "one dataset", **AT-6 is over-engineering and AT-4 + AT-5 are the deliverable.**
Every wave in this repo's history moved its own scope on the pre-check (8 for 8); two were
live defects. Spend the half-day.

### 3.1 · AT-0 SPENT (2026-08-17) — 105 tables, 890 columns, 13 datasets

Measured through the app's own loaders (`LocalUploadConnection` for uploads, read-only
DuckDB for the demo canvases), so the dtypes are the ones the profiler actually sees. Two
false starts are part of the finding: a hand-rolled `read_csv_auto` silently returned
**zero rows for data_co** — the motivating dataset — and reported it as a clean negative,
and an `all_varchar` fallback made every column look like castable text. *A failed probe
and a true negative look identical.*

| # | question | measured | scope move |
|---|---|---|---|
| Q1 | text columns numeric-castable | **15 of 522** (2.9%) in 4 tables; 11 of them data_co | build as a witness; query-time is already covered by `numeric_expression` |
| Q2 | coordinate pairs | **1 real** (data_co) + **1 false-positive table** (scm `Shipping costs`/`Price`). Of 5 columns passing a bounded-±90 value test, **only 2 are coordinates — 60% false positive** | **cut the bundled city-centroid table** (1 dataset does not earn it). Keep a cheap structural partner test as *one* witness |
| Q3 | binary flag beside a same-stem duration | **0 by shared stem** — and the motivating case is one of them: `Late_delivery_risk` vs `Days for shipping (real)` share no stem ("delivery" ≠ "shipping") | **the spec's lexical test would miss its own motivating case.** Replaced by a computed rule, below |
| Q4 | name-witness vs value-witness disagreement | **27, across 9 of 13 datasets**, in 5 kinds | AT-4 + AT-5 justified corpus-wide, not by one dataset |
| Q5 | grammars | 3 fire: email (4), ISO-3166-ish (4), ISO-4217 (2). **UUID, E.164, ZIP, IPv4, ISO-8601-in-text: zero. Checksums (Luhn/IBAN/ISBN/EAN): zero** | build the regex table (a row is nearly free); **skip the checksum module** — real code, real tests, zero customers |
| Q6 | percent scale | 12 columns bounded 0–1, 3 percent-named bounded 0–100, across 6 datasets | build `percent.fraction` vs `percent.whole` |
| Q7 | pairs | **arithmetic identity `a*b≈c`: 7, in 6 datasets — the most prevalent pair signal by far.** start/end timestamps: 4 datasets. actual/planned: 1. gross/net: 1, **a false positive on inspection** (`net_sales_eur_m` vs `gross_profit_eur_m` are different measures) | **reorder AT-6**: identity first, start/end second, actual/planned third. **Drop gross/net** |

**Three findings that changed the design, not just the scope:**

1. **Single witnesses false-positive at a measurable rate.** 3 of 5 bounded-±90 columns are
   not coordinates; `^[A-Z]{2}$` matched `Customer State` (`UT`, `MD`, `GA`) as an ISO-3166
   country code; and the arithmetic-identity sweep returned
   `transactionID * unitPrice ≈ franchiseID` at 100% because `unitPrice` is the constant 3
   and the tolerance was relative. The two-witness rule of AT-4 is **load-bearing, not
   ceremony** — and identity witnesses must reject constant factors.
2. **The derived-flag link is computable, and it is a PAIR rule.** No single-column
   threshold explains `Late_delivery_risk` (nothing reaches 90%), but
   `Late_delivery_risk == (real > scheduled)` holds on **97.55%** of 180,519 rows. So the
   flag is recognised from the actual/planned pair AT-6 already finds — which is what turns
   the prompt-only MAGNITUDE GUARD into a computed fact.
3. **The categorical fingerprint must be multilingual and set-based, not pattern-based.**
   data_co's `Order Country` holds 164 **Spanish** country names (`Brasil`, `Níger`,
   `Papúa Nueva Guinea`, `EE. UU.`). A pattern cannot separate them from any other proper
   noun; set membership can.

**One live defect found by the pre-check** (the 9th wave in a row to find one): seven
identifier columns in data_co — `Customer Id`, `Order Id`, `Order Item Id`, `Category Id`,
`Department Id`, `Product Card Id`, `Product Category Id` — are **not recognised as keys**.
`_KEY_PATTERN` requires `_id$` and `_KEY_PATTERN_CAMEL` requires `customerId`; a
space-separated `Customer Id` matches neither, so it profiles as free `text` at 9,754
distinct values.

**Verdict: Track 2 proceeds, with AT-6 halved and AT-5 trimmed.** AT-4 in full, AT-5 minus
checksums, AT-6 minus the centroid table and minus gross/net but plus the computed
derived-flag rule, AT-7 and AT-8 as written.

Track 1 first because it is cheaper, self-contained, and its proof is already running (the
same question, the same counters). Track 2's contract (AT-4) can start in parallel; its
witnesses cannot, until AT-0 says which are worth building.

### 3.2 · AT-0 VERIFIED (2026-08-17) — re-measured after Track 2 shipped

Every number above re-run against the same corpus, plus the three claims the pre-check
script does not itself compute. **Six of seven questions reproduce exactly.** The two that
move both move for a reason that is now written down.

| claim | re-measured | verdict |
|---|---|---|
| 105 tables, 890 columns, 13 datasets | 105 / 890 / 13 | ✅ exact |
| Q1 · 15 of 522 castable (2.9%), 4 tables, 11 in data_co | 15 of 522, 4 tables, 11 in data_co | ✅ exact |
| Q2 · 1 real pair + 1 false-positive table; 5 bounded-±90, 2 real ⇒ 60% FP | 2 pair tables (data_co real, `scm.supply_chain_data` false); 5 bounded-±90 | ✅ exact |
| Q3 · 0 flag/duration pairs by shared stem | 0 | ✅ exact |
| Q4 · 27 name-vs-value disagreements, 5 kinds | **19**, 5 kinds | ⚠️ **−8, fully accounted** |
| Q5 · email 4, ISO-3166-ish 4, ISO-4217 2; every other grammar 0 | 4 / 4 / 2, all others 0 | ✅ exact |
| Q6 · 12 bounded 0–1, 3 percent-named bounded 0–100 | 12 / 3 | ✅ exact |
| Q7 · identity `a*b≈c` 7 in 6 datasets; start/end 4; actual/planned 1; gross/net 1 (FP) | **8** in **6**; 4; 1; 1 | ⚠️ **+1, explained** |

**Q4 −8 is this wave's own fix, exactly.** The eight columns that left the disagreement
list are `Category Id`, `Customer Id`, `Department Id`, `Order Customer Id`, `Order Id`,
`Order Item Id`, `Product Card Id`, `Product Category Id` — each moved `text → key` when
`_KEY_PATTERN` learned that a separator can be a space. 19 + 8 = 27. AT-0's count was
right and the live defect it found is closed.

**Q7 +1 is one dataset counted twice, not a new finding.** data_co yields two identities
(`Order Item Product Price × Order Item Quantity = Sales` and `Order Item Quantity ×
Product Price = Sales`) because `Product Price` is a duplicate of `Order Item Product
Price` — which AT-6's duplicate-column rule reports separately. Dataset count is unchanged
at 6, and the claim the number supports — *the most prevalent pair signal by far* — holds.

**And finding 1's false positive is gone.** AT-0 measured the identity sweep returning
`transactionID × unitPrice ≈ franchiseID` at 100%. `scm.sales_transactions.unitPrice` is
still the constant `3` across all 3,333 rows; the shipped rule returns **no identity for
that table**. The constant-factor rejection works on the data that produced the defect.

**Finding 2 reproduces to the digit:** `Late_delivery_risk == ("Days for shipping (real)" >
"Days for shipment (scheduled)")` on **176,096 of 180,519 rows = 97.55%**, measured on the
full table.

**One methodological warning worth more than any of the numbers.** The first re-run
reported *45 tables, 350 columns, 6 datasets* and clean zeros for Q1, Q2 and Q3 — the whole
upload half of the corpus silently absent, because the script resolves the upload root
RELATIVELY and it was run from a scratch directory. It printed no error. That is the third
time in this program's history that a failed probe has been indistinguishable from a true
negative, and the second time on this exact script. **Run it from the repo root, and check
the table count against 105 before reading a single answer.**

---

## 4 · Measurement — what "improved" means here

No receipts. Three numbers per wave, all already emitted:

- **accuracy** — `deep_analysis.report_check_retry` and `…violations_shipped` on the six-run
  question (baseline run 6: 1 retry, 1 shipped — the shipped one a false positive);
  `deep_analysis.finding_contradicted_its_verdict` (baseline: 1 correct firing).
  Target after AT-1: 0 / 0 / 0 on the same question, and the headline free of causal verbs
  by construction.
- **latency** — wall time per run (baseline 35–103 s; variance is LLM round-trips). AT-1's
  gain is the retry it removes (~15–20 s when it fired). Nothing in either study touches
  the plan → interpret → synthesize floor; that is `?timings=1` work, not this program.
- **comprehension** — the share of report-check violation strings and
  `confidence_justification` sentences that carry a `#n` the reader can look up
  (baseline 0%; target 100% after AT-2), and — the only qualitative one — a reader of the
  report can name which statistic each headline claim rests on without opening a card.

---

## 5 · Decisions locked, and what is not

**Locked (from the two studies — do not relitigate without new facts):**
- Guards key on claims, types and code-written verdicts — **never on vocabulary alone**.
  A word-list is a backstop, not a gate.
- `semantic_type` is not redefined; `concept` is added beside it under the two-witness rule.
- The claim↔evidence ID system, the match-strategy receipt, and the `_meta` drift ratchets
  are **not** in this program — hygiene, not accuracy. (Drift ratchets are worth a separate
  half-day; they protect the guards this program adds from going silently blind.)
- From the skills repo, take **scripts and rule tables**, never the SKILL.md prose — PE-2
  moved that style *out* of aughor's prompts and this program does not put it back.
- `what-if-oracle` (CC BY-NC-SA) and `consciousness-council` are never a source.

**Open — user input wanted:**
- Whether `causal` is *ever* assignable from an observational table by user assertion
  ("assume promotions cause the lift"), or only from a declared intervention column.
- Whether AT-7's operations vocabulary should be user-extensible from day one
  (`ontology_column_config` is the natural home) or curated-only until AT-8 exists.
- The η² band boundaries (0.01 small / 0.06 medium are Cohen's conventions; pitfall #14
  warns they are not laws — a domain pack could override).

---

## 7 · Track 1 delivered — what run 8 shows, including what it disproves

Built on branch `claude/answer-truthfulness-at1`, 2026-08-17. `aughor/agent/claim_type.py`
owns the ladder; `_stamp_claim_type` resolves it at intake from the DESIGN;
`_claim_licence_section` carries it into synthesis; `check_claim_type` verifies it.
31 tests in `tests/unit/test_claim_type.py`, 6,335 in the suite.

**Run `0b3f2192` (33 s), against run 3's failure:**

| | run 3 (`3bfce2ee`) | run 8 (`0b3f2192`) |
|---|---|---|
| headline | "correlated with geography, **driven by** localized state-level bottlenecks" | "Show **No Material Correlation** with Customer Location" |
| licence | none — the concept did not exist | `claim_type.associational = 1`, resolved from the design |
| waterfall | a fabricated cause of `-0.011 days` at 100% | `[]`, `total_change_label: ''` — not requested |
| significance vs effect | conflated | *"statistical tests confirm a real difference across cities, the effect size is negligible"* |
| `check_claim_type` | — | never fired: no causal verb was written |

**The prediction that did not hold.** §2 said *proof: `report_check_retry` = 0*. Run 8
retried once and shipped one violation. **The check was right and the prediction was wrong.**
The flagged sentence claimed *"all 563 cities and 50 states"*; `COUNT(DISTINCT)` gives 563
and **46** — the model wrote the round number a human would guess. `#36` was a true positive,
the retry failed to repair it, and it shipped disclosed with confidence capped. AT-1 retired
the retries *it* was responsible for; this one came from a pitfall no earlier run tripped.
Record it as: **the retry counter is not a Track 1 success metric — the class of violation
is.** Runs 5–7 retried on precludable overreach; run 8 retried on a fabricated count.

Also confirmed: AT-3's cross-scale widening did not blind `check_grounding` — `1.1%` grounded
against `0.0109` in the same report where `50` was still caught.

**Open at hand-off:** `_lead_with_verdict` fired once more on prose that agreed with its
verdict (the fourth such false positive in one day, all from word-list matching). It is a
harmless backstop and it is the standing argument for finishing the shift from vocabulary to
claim types rather than patching the regex again.

---

## 6 · Receipts (kept short — the point is the outcome, not the trail)

Six runs, one question, one day: `5dc26c2c` → `8f83b1b4` → `3bfce2ee` → `54df16fa` →
`c88a3baf` → `34932b1f`. Run 1's headline rested on a tautology and computed no
correlation. Run 6's reads *"consistent across all customer locations with negligible
geographic impact… explaining only 1.1% of total performance variance… (p = 2.38e-155)"* —
significant and immaterial, both said, with the number. What is left is one guard
misfiring on a correct sentence, and the two tracks above are the plan for making the next
misfire structurally impossible rather than patched.

---

## 8 · Track 2 delivered (2026-08-17) — what a column IS, and what reads it

`aughor/tools/pairs.py` (AT-6), `aughor/tools/usage.py` (AT-8),
`aughor/ontology/operations.{py,yaml}` (AT-7), the witness/stamping seams in
`aughor/tools/profiler.py`, `ColumnFlags.concept`, `profile_cache.load_concepts`, and
`plan_relationship(col_concepts=…)`. 82 tests across five files; 6,431 in the suite.

### 8.1 · What data_co resolves to now, and on what evidence

Profiled live through the app's own loader — 53 columns, 1.5 s, the same
`get_or_build_profiles` the API calls.

| column | concept | conf | the two layers |
|---|---|---|---|
| `Late_delivery_risk` | `flag.derived_comparison` | 0.90 | named like an indicator **+** equals `real > scheduled` on 97.7% of sampled rows |
| `Latitude` | `geo.latitude` | 0.86 | named like a latitude **+** partnered with a column that leaves ±90, both at 8 dp |
| `Longitude` | `geo.longitude` | 0.86 | same pair, other side |
| `Order Item Quantity` | `count.quantity` | 0.82 | named like a count **+** the whole-number factor of `price × qty = Sales` |

Everything else resolved to a HINT or to nothing, which is the design. `Latitude` is
`VARCHAR` in this export: it reaches its concept without its type, and without its name
being the deciding vote.

The schema the agent reads now carries the consequence, not just the label:

```
Latitude   text  | IS geo.latitude — a latitude in degrees — never SUM, AVG
DERIVED QUANTITIES in data_co_supplychain (measured on sampled rows …):
  · "Late_delivery_risk" holds 0/1 and equals ("Days for shipping (real)" >
    "Days for shipment (scheduled)") on 97.7% of 300 sampled rows … The magnitude
    behind it is "Days for shipping (real)" - "Days for shipment (scheduled)"
```

That last line is the MAGNITUDE GUARD stopping being a paragraph of prompt and becoming a
measured fact about the table — the subtraction intake had to invent by itself in six
consecutive runs.

**Run 9 (`fce12fa9`, 19 s)** on the six-run question: headline *"Shipping delays are not
meaningfully correlated with customer location across geographic dimensions"*, metric
`AVG("Days for shipping (real)" - "Days for shipment (scheduled)")`, waterfall `[]`,
`total_change_label` empty, confidence HIGH justified by effect size. Track 1's guarantees
hold and nothing regressed.

### 8.2 · Three things the build changed about its own plan, each on a measurement

1. **AT-6's actual/planned rule was CUT.** The spec's signature — difference centred near
   zero with a right tail — does not discriminate. Measured on data_co: the true pair sits
   at a median absolute difference of 0.250× its own magnitude, `Sales per customer` ×
   `Order Item Product Price` (unrelated) at 0.226, `Sales` × `Order Item Total` at 0.070.
   No threshold admits the first and refuses the others. The first implementation shipped
   **18 findings on the one table the rule existed for, all but one nonsense.** The concept
   survives: the derived-flag rule names the same two columns from an *equality*.
2. **A duplicate-column rule took the slot**, and earns it on the same table: data_co
   carries **six** pairs that hold identical values on every sampled row (`Benefit per
   order`/`Order Profit Per Order`, `Sales per customer`/`Order Item Total`, `Customer
   Id`/`Order Customer Id`, `Category Id`/`Product Category Id`, `Order Item Cardprod
   Id`/`Product Card Id`, `Order Item Product Price`/`Product Price`). The relationship
   primitive refuses two sides naming the same COLUMN; nothing refused two names for one
   column, and correlating those returns r = 1.0 as a discovery — Track 1's tautology,
   through a door Track 1 did not close.
3. **The first identity sweep found nothing and said nothing.** Its 20-column cap dropped
   `Sales`, `Order Item Total` and `Product Price` from a 27-numeric-column table — exactly
   where the identity lives. The cap is now 40, the search early-aborts instead of scoring
   every triple, and **every truncation is printed**. A silent cap reads as "we looked at
   everything".

Two false positives AT-0 named in advance are refused by the shipped rules and pinned by
regression tests: `scm.supply_chain_data`'s `Shipping costs`/`Price` (every range test
passes; sixteen significant digits are a float printed in full, not a recorded precision),
and `transactionID × unitPrice ≈ franchiseID` (the factor is the constant 3).

### 8.3 · What is missing because AT-5 was dropped, stated plainly

No value layer exists. Concretely, the following are **not** built and nothing else covers
them:

- **percent scale** — `percent.fraction` vs `percent.whole` is unresolved, so the 12
  columns bounded 0–1 and the 3 percent-named columns bounded 0–100 that AT-0 measured are
  still indistinguishable to every consumer;
- **grammar/code witnesses** — email, UUID, ISO-4217, ISO-3166, US-state, E.164, ZIP,
  IPv4/6, ISO-8601-in-text. AT-0's `^[A-Z]{2}$` false positive on `Customer State` is
  therefore **not** retired: it remains a live 4-column disagreement in Q4;
- **the categorical fingerprint** — data_co's 164 Spanish country names in `Order Country`
  still reach no concept;
- **numeric-castable text as a witness enabler** — `numeric_expression` still covers this
  at query time, so nothing is broken, but the 15 castable text columns AT-0 found do not
  contribute evidence at profile time.

The consequence for the contract: with only four layers and no value layer, **most columns
resolve to a hint or to nothing**. On data_co that is 4 confident concepts out of 53
columns. That is the honest floor of a four-layer system, not a defect in the resolver.

### 8.4 · Two live limitations, said now rather than found later

- **AT-8 has almost nothing to read.** Mining `workspace`'s real history returns **3**
  logged SQL statements and 3 (column, role) pairs, every one below `MIN_SUPPORT = 3` — so
  the usage layer currently witnesses nothing anywhere. It is wired, correct, and idle
  until real usage accumulates.
- **Usage moves without the schema moving.** Profiles are cached by schema fingerprint, so
  a column that becomes popular today is witnessed at the next profile REBUILD, not the
  next query. `PROFILE_LOGIC_VERSION` was bumped `v4-valsample → v5-concept` for this wave
  precisely because `from_dict` reads an old entry happily: without the bump every existing
  connection would have kept serving concept-free profiles and the wave would have been
  built, cached out, and invisible.

---

## 9 · AT-5, bounded-numeric half (2026-08-17) — the fifth layer

`aughor/tools/shape.py`, 51 tests. Reads the row-aligned sample AT-6 already pulls, so it
costs **zero extra queries**. Neither the column's NAME nor its declared DTYPE is consulted:
the name is a different layer, and the dtype is the LOADER's opinion — the witness that was
wrong about `Latitude` in the first place, and wrong in a way that depends on which
warehouse the same file was loaded into.

### 9.1 · What the four shapes say about all 105 tables

| witness | fires on | correct |
|---|---|---|
| `flag.binary` | 2 — `Late_delivery_risk`, `housing.waterfront` | **2 / 2** |
| `percent.fraction` | 10 — discounts, duty rates, open rates, fraud scores | **9 / 10** (`attribution.weight`, 0.4–1.0 over 3 values) |
| `geo.longitude` | 1 — `Longitude` | **1 / 1** |
| `geo.latitude` | 2 — `Latitude`, `Order Item Profit Ratio` | **1 / 2** — the false positive AT-0 predicted, and it stays a hint |

Corpus-wide, name + value alone now type **9 of 890 columns (1.0%)** to CONFIDENT, and all
nine are right on inspection. Six of them — `duty_rate`, `markdown_pct`, `open_rate`,
`Order Item Discount Rate` and two duplicates — had **no concept at all** before this wave.

On data_co the resolved set went 4 → 5 columns, and the three that already resolved are now
carried by three agreeing layers instead of two: `Late_delivery_risk` 0.90 → **0.97**,
`Latitude` / `Longitude` 0.86 → **0.93**.

### 9.2 · `percent.whole` is not buildable, and AT-0 asked for it

Q6's scope note reads "build `percent.fraction` vs `percent.whole`". Measured during this
build: `0 ≤ v ≤ 100` fires on **82 of 890 columns** and about **two** are percentages. The
band is where every small number lives — `quantity` 1–14, `csat` 1–5, `month` 1–12,
`fiscal_quarter` 1–4, `bathrooms` 1–5.25, `weeks_of_cover` 2–29.9. Requiring a fractional
part cuts it to 15, of which 13 are still wrong, and one of the survivors is `Latitude`.

There is no range test that separates a whole-scale percentage from a small count, because
there is no difference in the values. **The scale ambiguity AT-0 found is real and remains
UNRESOLVED**; what this measures is that the value layer is not where it can be resolved.
`percent.fraction` — bounded 0–1 *and* fractional — is a genuine signal and stays.

### 9.3 · Two structural changes this wave forced

1. **`flag.derived_comparison` collapsed into `flag.binary`.** Splitting them meant the
   name and value layers voted for one concept while the pair layer voted for the other, so
   the best-evidenced flag in the corpus resolved to a hint — a vote-split that would have
   grown with every new layer. The concept now answers WHAT the column is (a 0/1
   indicator); the comparison is WHY, and it survives in the evidence sentence and in the
   table's derived quantities, which is where a reader looks anyway.
2. **A latitude no longer needs a longitude.** Before the value layer, `latitude` was a
   name with nothing to second it. Now its own values are the second witness, so a table
   storing only a latitude gets one — while a column with identical values and a name that
   says nothing (`score`, `Defect rates`) still types nothing. Both halves are pinned.

`aughor/tools/pairs.py` no longer carries its own value parser or coordinate-precision
band; both are imported from `shape`, which owns them. Two parsers over one sample is two
chances to disagree about the same column.

### 9.4 · What the vocabulary half would still buy

Unbuilt, scoped, and each with its measured demand: ISO-4217 currency codes (2 columns —
and AT-7's `money.amount` already says it "requires a currency witness" that nothing
supplies), ISO-3166 vs US-state codes (4 columns — retires the `^[A-Z]{2}$` /
`Customer State` false positive, still live), country names (data_co's 164 Spanish values),
weekday/month names (**zero** columns measured across 105 tables). Checksums stay refused.

---

## 10 · AT-5 complete (2026-08-17) — the bundled vocabulary

`aughor/tools/vocab.py` (the lists), the grammar and set tables in `shape.py`, seven name
rules so each new witness has something it can agree WITH, seven new operations rows.
105 tests across `test_vocab.py` and `test_shape.py`.

**Membership in a real set, never a pattern that resembles one.** `^[A-Z]{2}$` matched
`Customer State` because every two-letter code has the same shape. Measured on that exact
column: **95.7% US state codes, 50.0% ISO-3166 country codes.** One list accepts it, the
other refuses it, and the share is the discriminator. **AT-0's false positive is retired** —
`Customer State` now resolves to `geo.region` with the evidence reading *"100% of 38
distinct values are US state codes"*.

Coverage: **91 of 890 columns (10.2%)** now reach a confident concept from name + value
alone, up from 9. The corpus counts reproduce AT-0's grammar measurement exactly — email
**4**, ISO-4217 **2** — and add what AT-0 had no vocabulary to see: 21 place columns
(including data_co's 164 Spanish country names at 100%) and 2 weekday columns AT-0 recorded
as zero because its script had no weekday list.

**Three design rules this wave had to obey, each bought earlier in the program:**

1. **A concept is never finer than the coarsest layer that can see it.** The value layer
   knows `Customer State` holds US state codes; the name layer only knows it is a place. So
   both emit `geo.region` and the *kind* goes in the evidence. Country codes, country names
   and US states all answer `geo.region` for the same reason, and a UUID answers
   `key.identifier` rather than inventing a second name for an id.
2. **Competing lists are settled inside the layer, not by the resolver.** `Customer State`
   clears the threshold against two vocabularies; only the better-supported one is
   reported, so a layer says one thing about one column.
3. **Shares are computed over DISTINCT values.** One address repeated 10,000 times would
   otherwise carry a column, and a skewed dimension would beat a varied one for reasons
   unconnected to what the column is.

**Two refusals worth reading as successes.** data_co's `Customer Email` holds `[REDACTED]`
on every row: the name says email, the values say otherwise, the layers disagree and
nothing is claimed. `Customer Zipcode` holds `725` and `95125` — three- and five-digit
numbers with no distinguishing shape — so the name's suggestion stands unconfirmed. Both
stay hints, which is the correct answer in both cases.

**One independence caveat, recorded rather than discovered later.** A DATE-typed column
stringifies to `2026-08-17`, so the ISO-8601 grammar matches *because of* its type, and the
name layer's timestamp rule reads that same type — two witnesses, one source. It is left in
because it cannot produce a wrong answer (a column the loader typed as a date is a date),
but a confident `time.instant` on a DATE column is not two independent opinions. On a
VARCHAR date column — data_co's `order date (DateOrders)` — the independence is real.

**And the coverage ratchet caught itself going blind.** Its source scan read only
`_witness(...)` calls, so it never saw the grammar and set TABLES — and still passed,
because most of those concepts happen to have a name rule too. A guard reporting success
while reading nothing is the failure this file exists to prevent, and it had it. It now
reads both tables and asserts they are still there.

Checksums remain refused: Luhn, IBAN mod-97, ISBN-13 and EAN are real code with real tests
and, measured across 105 tables, zero customers.
