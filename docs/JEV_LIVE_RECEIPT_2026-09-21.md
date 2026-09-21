# Live receipt — Jev measured, the framework re-decided, and the answer to "keep it or throw it out"

**Date:** 2026-09-21 · **The +2 to** `docs/TYPESAFE_JEV_STUDY_2026-09-17.md` (the shape) and
`docs/JEV_ALIGN_STUDY_2026-09-19.md` (the loop) · **Arc:** `ROADMAP.md` §3.20 / §6 item 28

**The question, as the operator put it:** prove the value of adding actual Jev from TypeSafe — or
`jevlike`, or `pg-jev` — "I want to know whether classifier framework or classifier model works or
not. If yes, we keep it; if not, we throw it out."

**The answer:** the classifier **model works** on the surface it was held for — semops-style row
judgments — and the classifier **framework works** once its seam stopped carrying every row twice.
Keep both, on the terms below. `pg-jev` is not adopted (same model, wrong surface for this
architecture), and the `jevlike` local scorer stays on hold (still nothing to train it on).

Everything here is measured; nothing is quoted from a vendor without a first-hand check beside it.
The two studies' standing refusals are untouched by this receipt: no judgment model on the verdict
path, nothing hosted on by default, and the binding rides `govern/outbound` and the PII gate because
the state is customer row text leaving the box.

---

## 0 · Evidence, and its limits

- **First-hand, live, today:** `TYPESAFE_API_KEY` entered by the operator; `POST
  api.typesafe.ai/v1/systemone` answers HTTP 200 as `jev-1.13.0` with exactly the contract the
  2026-09-17 study reconstructed second-hand (noul/choice/score, `usage` block, 429/529 backoff) —
  the vendor docs, unreachable when that study was written, were also read directly today and match.
  27 filters × 200 rows = 5,400 row-judgments in 216 bundles: **251,396 input tokens, 149 s
  sequential, ≈ $0.011 total.**
- **First-hand, recorded (2026-09-21, earlier):** the A/B runs in `evals/semops_band_decision.json`
  and the products run in `evals/semops_band_results.json` — per-row `kept_rows` for the
  `sampled` (production) and `banded` (JD-3) arms, plus a true `reference` arm on the products
  rows, all on frozen rows with a human gold set. Jev is scored **paired, on those same rows and
  gold**.
- **The limit, stated plainly:** no funded LLM backend existed on this machine tonight (Gemini
  quota exhausted and shared with the live app; Groq key 401; Together key 402; no local server
  up), so the LLM arms were **not re-run** — the paired comparison uses their recorded per-row
  verdicts, and the framework's token re-decision is a **re-cost** of the recorded runs under the
  slimmed seam's measured ratio, not a live re-run. The LLM-side ECE also remains unmeasured for
  the same reason; Jev's side is measured.
- **Scope:** one surface (semantic filter over theLook product names), six predicates from crisp to
  fuzzy, one dataset family. The verdicts scope to semops-like row judgments and say nothing about
  intake or any verdict-path use, which stay refused.

## 1 · The model — Jev, live, against the recorded arms

Challenger is **jev-solo**: Jev alone at threshold 0.5, no cascade, no champion. Yardstick is the
gold set; CI is `decide()`'s own rule (bootstrap resampling whole filters, seed 20260921).
`evals/jd5_jev_receipt.json` carries every number; the headline:

| Comparison (same rows, same gold) | Filters / rows | Accuracy | Δ | 95% CI |
|---|---|---|---|---|
| **jev-solo vs `sampled` (production today)** | 12 / 2,350 | **0.9528 vs 0.9268** | **+2.6 pp** | **[+1.1, +4.2]** |
| jev-solo vs `banded` (JD-3's full LLM cascade) | 12 / 2,350 | 0.9528 vs 0.9506 | +0.2 pp | [−1.3, +1.9] |
| jev-solo vs `sampled`, B-runs (sensitivity) | 7 / 1,375 | 0.9629 vs 0.9287 | +3.4 pp | [+1.5, +5.6] |

Jev alone **beats today's production cascade** by the same margin the banded LLM cascade does — and
is statistically indistinguishable from that full cascade while making **zero** champion calls.
Across the 24 unique corpus filters its gold accuracy is 0.9517.

**The composed cascade** (Jev cheap tier + the recorded reference champion for the 0.30–0.70 band,
exact per-row composition on the products rows): 0.966 / 0.987 / 0.987 against sampled's 0.954 /
0.920 / 1.000 — matching or beating it with **1 champion call per filter against up to 9**. The one
loss (0.987 vs 1.000) is the filter where sampled escalated the entire batch to the champion:
that is the cost/quality trade in one line.

**The falsifier ran and the model survived it.** JD-4's shuffled-context control, live: each
bundle's state lists the rows under deranged indices while the questions keep the originals. Real
0.975 / 0.990 / 0.945 → shuffled **0.755 / 0.470 / 0.750 — below even the majority-class floor**
(0.890 / 0.505 / 0.840) on all three. A prior-reciting model would have sat AT the floor; Jev
confidently answers about whatever text it is shown, which is what reading the state means.

**Repeatability:** the products rows are byte-identical to slice s0 and were (deliberately) judged
twice, in independent runs: 5 verdict flips in 600 paired judgments, mean |Δp| ≤ 0.009.

**Failure mode, named:** the fuzziest predicate ("designed for sport or exercise") drops to
0.86–0.90 with ~33 rows in the uncertainty band — ~4× the crisp predicates' band. Fuzzy predicates
are exactly where the band escalates and a champion is still needed; Jev alone is not that
champion.

**Calibration, honestly read (n = 5,400, ECE = 0.058):** the tails are excellent (stated 0.026 →
true 0.001; stated 0.964 → true 0.988) and the middle is not — inside 0.4–0.7 the stated
probability overstates truth badly (stated ≈ 0.45–0.65, true rate 19–30%). "Calibrated" is not a
global property of these numbers. What holds is exactly what the production code relies on: outside
the 0.30–0.70 band the probabilities are trustworthy, and inside it they are genuinely unreliable —
which is what the band is *for*. 7.4% of all rows landed in it (401/5,400).

**Speed and cost, measured:** median 0.68 s per 25-row bundle (p90 0.74 s), sequential; ~46.6
input tokens/row as Jev reports usage. At the corroborated price ($0.042/M input, output free —
the study's second-hand figure now matched by pg-jev's independent measurement of ≈$0.0405/M):
**$0.00196 per 1,000 rows**, against $0.00501 per 1,000 rows for the recorded sampled arm on
gemini-3.1-flash-lite at $0.25/M — **2.6× cheaper than the cheapest LLM arm on file**, before any
parallelism (the vendor and pg-jev both run bundles concurrently; tonight's 149 s for 5,400 rows
was fully sequential).

## 2 · The framework — JD-3 re-decided on total tokens, as directed

The 2026-09-21 receipt left JD-3 unswitched: banding was more accurate on both setups **and** its
request carried every row twice — once in the prompt, once again in the response schema's field
descriptions — measured at 9,021 chars per 25-row call against today's 2,306 (~3.9×), the exact
spend the arc was meant to cut (`cf695915`).

**The seam is now slimmed** (same commit series as this receipt): rows ride in the STATE once, in
the same `[index] text` listing the sampled path sends; each question is a short reference to its
row; and a noul's schema field is just its id and its [0,1] bound — the schema constrains, the
prompt carries. Measured on the same builder code, same rows: **9,021 → 5,228 chars (0.58×)**,
with today's request at 2,340. The remaining 2.23× per-call floor **is** the per-row-field
isolation — the thing that makes a row's verdict unstealable by its neighbours — and it is bought
back at the cascade level:

| Setup (recorded runs, re-costed at the measured 0.58) | sampled | banded pre-slim | banded slimmed | after-slim ratio |
|---|---|---|---|---|
| A (flash-lite / flash-lite), 12 filters | 48,288 tok | 76,772 tok | ≈ 44,492 tok | **0.92×** |
| B (flash-lite / deepseek-v4.1-flash), 7 filters | 27,785 tok | 43,978 tok | ≈ 25,487 tok | **0.92×** |

Accuracy and champion spend are unchanged from the recorded decision (they do not depend on prompt
size): +2.4 pp [CI +1.1, +3.8] with 4 champion calls against 12 (A); +3.6 pp [CI +1.9, +5.4] with
2 against 7 (B). **The token falsifier no longer fires**: banding is now more accurate, ~3× lighter
on the champion, and ~8% cheaper in total prompt tokens. The honest caveat stands: 0.92× is a
deterministic re-cost of recorded runs, not a live re-run — the first live run on a funded backend
should confirm it (the harness now records per-arm wall-clock and per-row probabilities, so that
run also buys the LLM-side ECE this receipt could not take).

## 3 · The other two names in the question

- **`pg-jev`** ([realZachi/pg-jev](https://github.com/realZachi/pg-jev), also on
  [PGXN](https://pgxn.org/dist/jev/0.2.0/)) is the same Jev model behind a Postgres-only surface:
  a `plpython3u` extension needing a superuser, Postgres 14–17, explicitly unavailable on managed
  hosts (its own README: Supabase/Neon/RDS cannot run it). Aughor's semops already sit at the
  right seam and run against every warehouse this platform speaks, not one. **Not adopted.** Its
  README still paid for the read twice over: batches of ≤20 rows were 100% correct, 40 → 92–98%,
  80 → 77–94% — independent confirmation that our batch of 25 sits at the edge of the safe zone
  (and a reason never to "optimize" it upward); and its 2,000-row cost measurement is the number
  that corroborates the price this receipt bills Jev at.
- **`jevlike` as a local model** stays exactly where the study left it (F6, hold): the decision
  corpus that would train it is still 40 rows with a constant outcome — A1's return path exists
  and nothing has flowed through it yet — and its honest ceiling makes it a pre-filter, never a
  decider. Nothing to run tonight; the framework findings it inspired (the seam, the battery, the
  shuffled control) are the parts already in the tree, and tonight the control it contributed is
  what stood between these numbers and belief.

## 4 · Verdicts

| Question | Verdict | Grounds |
|---|---|---|
| Classifier **model** (Jev) on semops-like row judgments | **WORKS — keep** | +2.6 pp over production [CI +1.1, +4.2] with zero champion calls; parity with the full LLM cascade; survives the shuffled-context falsifier; 2.6× cheaper than the cheapest LLM arm on file; sub-second bundles; deterministic to |Δp| ≤ 0.009 |
| Classifier **framework** (JD-1 seam + JD-3 bands) | **WORKS — keep** | more accurate on both recorded setups, ~3× fewer champion calls, and after the slim ~0.92× sampled's total tokens (re-cost; first live run to confirm) |
| `pg-jev` | **Not adopted** | right model, wrong surface: Postgres-superuser-only where semops are warehouse-agnostic; its measured numbers are absorbed instead |
| `jevlike` local scorer (JD-6) | **Hold, unchanged** | no corpus to train on (40 rows, constant outcome); pre-filter ceiling by its own authors' measurement |
| Jev on the verdict path / on by default | **Still refused** | unchanged from both studies; nothing tonight touches it |

**What "keep" means in the tree, and what it does not:** the seam, the slimmed shapes, the harness
with its Jev arm, and this receipt are committed. `semops.banded_cascade` **stays OFF** and the
production Jev binding (JD-5's `govern/outbound` + PII-gated backend) **stays unbuilt** — flag
flips and a hosted dependency in the serving path are the operator's call, now with the numbers on
the table. What tonight settles is the question as asked: the thing works; it earns its place; it
is not thrown out.

## 5 · Reproduction

```
# live arm (spends TypeSafe tokens; ~$0.011 as run):
uv run python evals/jev_solo_driver.py
# the falsifier (spends ~$0.001):
uv run python evals/jev_shuffled_control.py
# every comparison, from committed inputs, no model call:
uv run python evals/jev_receipt_analysis.py
# request-size measurement (no model call): the numbers in §2, method of cf695915
```

Artifacts: `evals/jev_live_results_2026-09-21.json` (per-row probabilities, per-bundle usage and
latency), `evals/jev_shuffled_control_2026-09-21.json`, `evals/jd5_jev_receipt.json` (the
composed receipt), against the pre-existing `evals/semops_band_results.json` and
`evals/semops_band_decision.json`.

## Sources

First-hand today: `api.typesafe.ai/v1/systemone` (live, `jev-1.13.0`) ·
[docs.typesafe.ai/api](https://docs.typesafe.ai/api) (read directly at last; matches the study's
reconstruction) · [realZachi/pg-jev](https://github.com/realZachi/pg-jev) README ·
[PGXN jev 0.2.0](https://pgxn.org/dist/jev/0.2.0/). Pricing: Jev $0.042/M input (study, second-hand)
× pg-jev's independent ≈$0.0405/M measurement; gemini-3.1-flash-lite $0.25/M input
([devtk.ai](https://devtk.ai/en/models/gemini-3-1-flash-lite/),
[OpenRouter](https://openrouter.ai/google/gemini-3.1-flash-lite), Sep 2026). Companions:
`docs/TYPESAFE_JEV_STUDY_2026-09-17.md` · `docs/JEV_ALIGN_STUDY_2026-09-19.md`.
