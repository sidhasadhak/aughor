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

**Status 2026-08-17: Track 1 is COMPLETE** (AT-1, AT-2, AT-3 — §2, receipts in §7).
Track 2 has not started; **AT-0 is its gate and is unspent.**

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

Track 1 first because it is cheaper, self-contained, and its proof is already running (the
same question, the same counters). Track 2's contract (AT-4) can start in parallel; its
witnesses cannot, until AT-0 says which are worth building.

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
