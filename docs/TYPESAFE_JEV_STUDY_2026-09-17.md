# Adoption study — TypeSafe "System One" (Jev) and the `jevlike` reverse-engineering

**Read 2026-09-17.** Sources: the `vinnylarouge/jevlike` repository (MIT, cloned and read in full),
`geilt/typesafe-cli` (a third-party CLI whose wire calls give the exact API contract),
`GenieRobot/awesome-typesafe`, a public reference gist, and search-engine summaries of the vendor's
own pages.

**What could NOT be read, and what that costs this study.** `docs.typesafe.ai` and `typesafe.ai` are
blocked by this environment's egress policy, as are every secondary review site tried
(`developersdigest.tech`, `kingy.ai`, `explainx.ai`). So **no number below that is attributed to
TypeSafe was read from TypeSafe.** The API contract is reconstructed from a third-party client that
calls it; the cookbook results are search-engine summaries of pages we could not open. Treat every
vendor figure here as UNVERIFIED and re-check it against the real docs before any of it is built on.
What IS first-hand: the `jevlike` source, and every claim about Aughor.

---

## 1 · The mechanism, stated precisely

Two different things wear the same name, and only one of them is a product.

**(a) Jev — the hosted model.** One HTTP call carries one **state** and a map of named, typed
**questions**. Each question is answered independently and in parallel against that state; the answer
to one never becomes context for another.

```
POST https://api.typesafe.ai/v1/systemone      Authorization: Bearer $TYPESAFE_API_KEY
{"model": "jev-latest",
 "state": "…text, or a JSON object/array…",
 "questions": {
   "is_urgent":  {"type": "noul",   "instructions": "Does this convey urgency?"},
   "department": {"type": "choice", "instructions": "Which team should handle this?",
                  "criteria": {"billing": "Payments, invoicing, refunds",
                               "technical": "Bugs, outages, integrations"}},
   "frustration":{"type": "score",  "instructions": "How frustrated is the customer?",
                  "criteria": ["Calm", "Frustrated", "Very angry"]}}}
→ {"model": …, "usage": {"input_tokens": …, "output_tokens": …},
   "answers": {"is_urgent":  {"type":"noul",   "noul": 0.96},
               "department": {"type":"choice", "choice":"billing",
                              "probabilities": {…}, "confidence": 0.84},
               "frustration":{"type":"score",  "score": 1.4, "legend": {…},
                              "probabilities": {…}, "confidence": …}}}
```

Three primitives, and the shapes matter more than the vendor does:

| Primitive | Declares | Returns | Uncertainty |
|---|---|---|---|
| **Noul** | a proposition | probability it is true | the probability itself — 0.5 *is* "unsure", there is no separate confidence |
| **Choice** | a closed map of options (≤255) | the winning key + a probability for **every** option | `confidence` = how peaked the distribution is |
| **Score** | 2–10 **ordered** levels | a continuous score that may fall **between** levels (e.g. 1.4) + per-level probabilities | `confidence` from the level distribution |

Reported properties (vendor, unverified): questions are evaluated in isolation and in parallel so
added questions barely add latency; output is schema-constrained, so an answer outside the declared
space is not representable; probabilities are trained to be calibrated (they call it RLCD) —
**and calibrated is not correct**, which their own documentation says out loud.

**(b) `jevlike` — the open re-derivation of the *shape*.** Not a copy of Jev, and it says so. It is a
~400-line PyTorch package that solves "pick one of N changing text options in ONE forward pass":
each option becomes a query vector, the query attends over the context tokens, one shared dot product
scores each (option, attended-context) pair, and a softmax runs across the options
(`jevlike/model.py:AttentionHead`). The encoder is either learned bytes (257 embeddings, 192-byte
context, 32-byte options) or a **frozen** pretrained encoder with only a small head trained; the
checkpoint stores the head and the encoder's *name*, never its weights.

Its own measured numbers, which are the honest part of the repository: ~98% on synthetic menus;
**26%** on target-disjoint Wikispeedia next-click with a frozen Qwen2.5-0.5B encoder against ~8% for
shuffled and random-encoder controls; 29% for a from-scratch model on 40,000 clicks; and at eight
options, one pass ≈ **100× faster** than a small local decoder made to write 400 tokens. Its
`AGENTS.md` also records that a flat convolutional policy beat the option head on identical data —
"the option head remains a capacity bottleneck". So the shape is fast and honest, and weak in
absolute accuracy.

---

## 2 · What the vendor's own numbers say when read carefully

Unverified (see §0), but internally consistent across the secondary sources:

- **Price** $0.042 per million input tokens, output tokens not charged.
- **Latency** 70–500 ms end-to-end; a launch demo at 0.114 s against 8.566 s for a frontier model.
- **Parallel-questions cookbook** — 13 questions over one GDPR article: batching all of them into one
  call was **12.2× cheaper and 10.0× faster, with the answers unchanged** (most identical across five
  repeats, std dev 0.0, batched or not).
- **Self-consistency cookbook** — one insurance claim, a 14-question rubric, 15 repeats: answers
  between 0.43 and 0.53 straddle the 0.5 threshold, and the recipe's answer is to turn 0.30–0.70 into
  an explicit *uncertain* outcome that routes to a person.
- **SDE cascade cookbook** — a two-stage mini → verify → reasoning cascade for most of a big model's
  quality at a fraction of its cost.
- **Accuracy** on TypeSafe's own four-workflow benchmark: **67.8%**, against GPT-5.6 Terra 67.9%,
  GPT-5.6 Sol 74.1%, Opus 5 73.1% — and at least one write-up notes that eval scores answers against
  two other models' answers rather than a human key.

**The conclusion that matters to us:** this is a **speed and cost** result, not an accuracy result. On
their own benchmark it ties one frontier model and trails two. Anywhere Aughor's correctness is the
product, Jev is not an upgrade. Anywhere Aughor spends a frontier call on a five-second judgment and
then *validates it in code anyway*, it is a large win.

---

## 3 · What is true in Aughor today (measured, first-hand)

- **The deep path's wall-clock is ~100% phase-serial LLM calls** — measured, `AGENT_NOTES.md:214`.
  The live A/B: **373 s serial vs 304 s** with `ada.parallel_phases` = **1.23×**, both arms **14 LLM
  calls**, equal coverage and conclusion. The note's own verdict: "intake + synthesis are
  serial-by-necessity and dominate… the bigger levers are intake's internal calls… NOT more
  phase-level parallelism."
- **Intake is one decoder call carrying ~25 fields** (`aughor/agent/prompts_investigate.py:755`), and
  they are not the same kind of thing. Roughly ten are pure judgments over one state —
  `descriptive_only`, `cross_sectional`, `metric_is_ratio`, `claim_type_suggestion` — and three are
  **picks from a set the schema already knows**: `date_column`, `metric_table`, `dimensions`. The rest
  (`metric_sql`, the relationship/segment expressions) are genuinely generative.
- **We already pay for those open-ended picks in repair code.** `aughor/agent/investigate.py:5498`:
  "collect ALL spec errors and fix them in ONE combined LLM retry (was up to **3 sequential
  round-trips on the critical path of every investigation**)", and the date column is repaired
  deterministically by `_resolve_date_column` because that "fixes an ID-like / non-date column far
  more reliably" than asking again.
- **The semantic operators batch 25 rows into one prompt** (`aughor/semops/operators.py`,
  `DEFAULT_BATCH = 25`, cap 200 rows), ask for a JSON array of verdicts, and **fail open on a parse
  error — a failed batch keeps 25 rows unfiltered**. The quality cascade samples a spread of rows,
  compares them against the strong tier, and escalates the **whole batch** above 20% disagreement.
- **Confidence exists but is computed, never asked for** (`agent/state.py`: `earned_confidence` is
  "COMPUTED (never asserted by the LLM) so the report's confidence reflects evidence, not a vibe").
  That is the right instinct and it is exactly the seam a calibrated probability would fill.
- **The gates a hosted judgment backend would have to ride already exist**: `security/pii`,
  `govern/outbound`, `govern/guardrails.py`, and the 428 `approval_required` graduated gate
  (`govern/actions.py:166`).
- **The noise floor forbids weak instruments** (`AGENT_NOTES.md`): ±7–10 instances of 135 churn
  between any two runs; a lever below ~+10 cannot be proven by single runs; what survives is
  "deterministic monotonic mechanisms". Every proposal below is therefore either monotonic by
  construction or arrives with its own control.

---

## 4 · The findings — what to borrow, in value order

### F1 · One state, many questions — the judgment bundle *(no vendor needed)*

The transferable idea is not the model, it is the **request shape**: independent judgments over one
state belong in **one** call, and each must be scored in isolation so batching cannot change an
answer. Aughor already batches (semops) and already bundles (intake), but does neither with isolation:
25 rows share one prompt and can contaminate each other's verdicts, and intake's ten judgments share a
prompt with its generative fields, where a wrong `metric_sql` can drag `cross_sectional` with it.

A `judge(state, questions) -> answers` seam over our *existing* providers buys the shape immediately:
one structured call per bundle, one closed schema per question, per-question isolation where the
backend allows it. It is also the only honest way to compare a Jev binding later — same seam, two
backends.

### F2 · A closed option list, where the option list is already known *(no vendor needed, monotonic)*

`date_column`, `metric_table` and `dimensions` are picks over a set the schema hands us. Asking a
decoder to *write* `table.column` as free text creates a failure class (a column that does not exist,
an ID-like column) that we then spend repair code and up to three extra round-trips on. A choice over
a declared option set **cannot return a value outside it** — the failure class stops existing rather
than being caught. This is monotonic by construction: it can only remove invalid picks, so it is
provable below the noise floor. `jevlike` shows the same shape needs no vendor at all — its whole
subject is "pick one of N options that change per row".

### F3 · Confidence bands instead of sample-and-escalate *(no vendor needed)*

Our champion cascade samples ~10 rows and escalates **all 200** above 20% disagreement — it pays the
strong tier for the rows the cheap tier already had right. The cookbook pattern is per-item:
act above a band, escalate inside it, route to a person below it, with the thresholds in **our** code.
Applied to `semantic_filter`, only the uncertain rows go to the champion — strictly cheaper and
strictly more accurate than escalating a whole batch on a sampled rate. It needs a per-row
probability, which is exactly what F1's seam should return.

### F4 · The calibration instrument, and the control that makes it honest *(no vendor needed)*

`jevlike/eval.py` is the most directly reusable thing in either source: top-1, top-3, expected
calibration error over ten bins, and a **shuffled-context control** — every menu paired with the
*wrong* context, on the rule that a useful model must beat that control. That is this repository's own
falsifier discipline, already written, for judgment seams. It is the instrument we would need before
believing any of F1–F3, and it is the one that would have caught the ON-0 "lift that wasn't".

### F5 · The hosted binding — where a wrong answer is cheap *(needs the vendor)*

Given §2, Jev is not a candidate for the verdict path. It is a candidate for the places where we
already treat the model's output as a proposal to be validated: semops filter/rank pre-passes, RAG
passage filtering, triage, skill/tool pre-selection. Off by default; behind `govern/outbound` and the
PII gate, because **the state is customer row text leaving the box**; surfaced in the Trust Receipt;
and priced against the seam of F1 rather than assumed.

### F6 · The local one-pass scorer — sovereignty without a vendor *(needs training, not a vendor)*

`jevlike`'s architecture runs on a CPU and trains on JSONL we could emit from our own logged
decisions (`{context, options, label}`). It is the only option here compatible with a local-first
install and with the standing law that weights never enter the repo or installer (§3.9's adapter
shape). Its honest ceiling — 26–29% where controls score 8%, and an option head its own authors call a
capacity bottleneck — means it is a **pre-filter and a ranker**, never a decider: cut 200 candidate
columns to 12 before a real model reads them, do not let it choose the metric.

### The ten uses, mapped to surfaces we already have

| Their use | Our surface |
|---|---|
| Agent guardrail | `govern/guardrails.py` (policy exists; no semantic check) |
| Rag filter | `semops.semantic_filter`, `knowledge/` retrieval |
| Semantic search / rerank | `semops.semantic_top_k`, `semantic/` |
| Model router | `llm/provider.py` roles (`coder`/`narrator`/`fast`) — routed by caller, never judged |
| Skill picker | `skills/`, `agent/converse_tools.py` tool choice |
| Citation checker | `evidence/`, the grounded-answer guard, HB-4's provenance envelope |
| Ticket triage | `knowledge/triage.py`, `monitors/` |
| Corpus map-reduce | `semops.semantic_aggregate`, `ontology/doctree.py` |
| Writing linter | `sql/lint.py` (deterministic), quality sweep |
| Live UI | `canvas/`, the Briefing |

---

## 5 · Verdicts

| # | Proposal | Verdict | Depends on a vendor? |
|---|---|---|---|
| F1 | Judgment-bundle seam (`judge(state, questions)`) | **ADOPT** — the shape is the win | no |
| F2 | Closed option lists for schema-known picks | **ADOPT** — monotonic by construction | no |
| F3 | Per-item confidence bands in the semops cascade | **ADOPT after F1** | no |
| F4 | ECE + shuffled-context control as a standing guard | **ADOPT FIRST** — it is the instrument | no |
| F5 | Jev as an optional decision backend | **HOLD** — build behind F1's seam, measure, then decide | yes (hosted, egress) |
| F6 | A local one-pass scorer on our own decision logs | **HOLD** — only as pre-filter/ranker, after F4 exists | no |

**Refused outright:** Jev (or any judgment model) on the verdict path or as a source of a number a
person will act on; replacing a deterministic resolver with a judgment call; a hosted dependency that
is on by default; weights in the repo or installer; and believing any vendor figure in this document
before the real docs are read.

**Falsifiers.** F1/F2: if intake's bundle shows no wall-clock gain **and** no reduction in spec-repair
retries on the golden set, the seam is ceremony — drop it. F3: if banded escalation costs more strong-
tier calls than the sampled cascade at equal agreement, keep the sampled one. F4: if the shuffled-
context control scores within noise of the real control on our own logged judgments, our judgments are
not context-dependent and the whole arc is pointless. F6: if a trained head cannot beat a shuffled
control by a margin larger than the ±7–10 noise floor, stop.

---

## Sources

First-hand: [vinnylarouge/jevlike](https://github.com/vinnylarouge/jevlike) ·
[geilt/typesafe-cli](https://github.com/geilt/typesafe-cli) ·
[GenieRobot/awesome-typesafe](https://github.com/GenieRobot/awesome-typesafe) ·
[project reference gist](https://gist.github.com/pjburnhill/adf8d28efcad9df037bfdece178ef965).
Blocked by egress, summarised second-hand only:
[docs.typesafe.ai/introduction](https://docs.typesafe.ai/introduction) ·
[/api](https://docs.typesafe.ai/api) · [/primitives](https://docs.typesafe.ai/primitives) ·
[/confidence](https://docs.typesafe.ai/confidence) · [/patterns](https://docs.typesafe.ai/patterns) ·
[/concepts/use-case-map](https://docs.typesafe.ai/concepts/use-case-map) ·
cookbooks [parallel_questions](https://docs.typesafe.ai/cookbooks/parallel_questions),
[consistency_noul_cookbook](https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook),
[sde_cascade](https://docs.typesafe.ai/cookbooks/sde_cascade),
[date_extraction_cookbook](https://docs.typesafe.ai/cookbooks/date_extraction_cookbook) ·
[the launch post](https://typesafe.ai/blog/introducing-system-one-models-and-jev).
