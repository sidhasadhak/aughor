# Adaptive Inference & Semantic Operators — Design & Integration Plan

*Three techniques from the LLM-data-processing literature that Aughor should adopt, and a grounded
plan for where each plugs in. 2026-06-14.*

---

## TL;DR

There is a body of work on running LLM operations over data as **declarative, relational-style
operators** with a query optimizer. Studied in depth, the architecture is **complementary to Aughor,
not a competitor — and it will _not_ directly improve our NL2SQL.** Those systems do not generate
SQL; they `SELECT *` a table into memory and run an LLM call _per row_ client-side. On the thing we
care about most — **grounded, push-down, deterministically-guarded analytics** — Aughor is the
stronger design. So the transfer is **one-directional (into Aughor)** and it is about three reusable
_ideas_, not adopting any framework:

1. **Model cascades with a statistical accuracy guarantee** — a cheap proxy model answers the easy
   cases, only the ambiguous middle escalates to the expensive model, and the routing thresholds are
   _proven_ to hold a target recall/precision at failure-probability δ. This is the single highest-
   leverage borrow: it cuts cost **and latency** on our many LLM judgment calls _while guaranteeing_
   accuracy relative to the expensive model — exactly our "numbers you can act on" mandate. It rides
   the per-role provider config we shipped in #33.
2. **Automatic prompt optimization** — search over prompt phrasings against a labelled eval set
   (reflective/evolutionary methods such as GEPA), instead of hand-tuning. We already have eval
   scorers (UNIFY) and a benchmark (B-10).
3. **A semantic-operator layer over SQL results** — for the _unstructured residue_ (text columns:
   tickets, reviews, notes, incident write-ups) that SQL can't reason over. SQL push-down for the
   structured work (our strength) + a small set of LLM "semantic operators" client-side for the text.
   This is a genuine **product-offering expansion**, not a re-architecture.

**Meta-lesson (per the product call):** the systems that productize these techniques win largely on
**packaging** — they consolidate a pile of LLM-data operations under _one crisp abstraction_ with
great naming, which makes powerful machinery legible and sellable. Aughor has _more_ powerful
machinery but it is scattered and under-named. §3 proposes how to consolidate.

**Recommended first step:** a cascade pilot on **hypothesis evaluation** (`aughor/agent/nodes.py`,
`score_evidence`) — which also happens to be the "quickest standalone perf win" already on the
roadmap (it scores hypotheses serially today).

---

## Part I — The techniques (the study)

### 1.1 The thesis

LLM operations over data can be expressed as **declarative relational operators**, not bespoke
pipelines. You define each operator's intended behaviour with a **"gold algorithm"** (a high-quality
reference implementation), then let an optimizer **cut cost while _provably_ staying within an
accuracy band of that gold algorithm.** Published results report **order-of-magnitude op-level
speedups** and **several-fold end-to-end gains** over high-quality baselines — _with accuracy
guarantees_.

This "gold algorithm + provable faithfulness of the fast path" discipline is _exactly_ the shape of
our own correctness guards (Phase-8 binder, fanout de-fan, grain/additivity, the finding-trust
ladder). The paradigm is intellectually aligned with us; it just applies the discipline to a
different layer (LLM-over-rows rather than SQL-over-warehouse).

### 1.2 Semantic operators

NL-parameterised analogs of SQL operators. Each takes a natural-language expression with `{column}`
placeholders, e.g. *filter where "the {title} is science fiction."*

| Operator | Kind | Meaning | Naive cost |
|---|---|---|---|
| semantic **filter** | LLM | keep rows where an NL predicate is true | 1 call / row |
| semantic **map** | LLM | NL projection → new column | 1 call / row |
| semantic **extract** | LLM | pull structured fields from text (JSON) | 1 call / row |
| semantic **aggregate** | LLM | NL many-rows → one (summarise) | tree-reduce over context windows |
| semantic **top-k** | LLM | rank by an NL criterion | pairwise compares (n² / n·log n / heap) |
| semantic **join** | LLM | join two tables on an NL predicate | \|L\|·\|R\| (full cross-product) |
| similarity-join / search / dedup / cluster | embedding | retrieval / similarity-join / near-dup removal / clustering | embeddings only, no LLM |

Notable algorithm facts (verified by reading reference implementations):
- **Semantic join = semantic filter over the Cartesian product** (no dedicated prompt). The optimized
  path first _blocks_ with an embedding similarity-join, then verifies only survivors with the LLM.
- **Semantic top-k** reduces ranking to **binary "which doc is more relevant" LLM comparisons**,
  driven by quicksort/heap/quadratic-vote; the quicksort variant prunes to the top-K so it never
  sorts the tail.
- **Semantic aggregate** is a **hierarchical tree-reduce**: greedily pack docs into a context window,
  summarise each batch, recurse over the summaries until one remains. (Directly relevant to our
  Briefing synthesis.)
- **Semantic dedup** = embedding self-similarity-join + threshold + connected-components → keep one
  per component. (Directly relevant to ontology entity merging.)

### 1.3 The architecture pattern

```
eager:  df.<semantic op>(...)                          ← pandas-style accessor, no optimization
lazy:   plan.<op>(...).optimize([...]).execute(df)     ← build a logical plan, optimize, then run
        │
        ├─ AST: immutable nodes (one per op), thin wrappers over the eager operators
        ├─ Optimizer passes: list[Node] → list[Node]  (composable, ordered)
        │     • predicate pushdown  — cheap filters before expensive semantic filters
        │     • prompt optimization — rewrite the NL prompts against an eval_fn
        │     • cascade             — learn proxy→oracle routing thresholds on train data
        └─ Runner: linear fold over nodes + content-addressable per-node cache
```

**The single most important architectural fact for us:** in these systems the SQL connector is a
plain `read_sql` straight into a dataframe — **zero push-down**. They are **not** NL2SQL systems;
their "predicate pushdown" reorders _dataframe_ filters, not SQL. Everything semantic happens
row-by-row in the client process. (This is why the borrow is about ideas, not architecture — our
push-down warehouse execution is the better substrate for structured analytics.)

### 1.4 The crown jewel — model cascades

This is the reusable IP. The mechanism, exactly as implemented in the reference (a ~150-line
statistical routine, no framework dependency):

1. **A cheap proxy scores every item.** Either (a) a cheap helper model run with `logprobs=True`,
   whose answer-token logprobs are renormalised to `P(positive) = P(True)/(P(True)+P(False))`, or
   (b) embedding similarity. Scores are calibrated by quantile-binning.
2. **Importance-sample** a small subset (weight ∝ √score, a small `sampling_percentage` of rows) and
   run the **expensive oracle** only on that sample, keeping unbiased correction factors.
3. **Learn two thresholds (τ⁺, τ⁻)** so the routing meets a **target recall & precision with
   probability ≥ 1−δ**, using Hoeffding confidence bounds:

   ```
   UB(μ,σ,s,δ) = μ + (σ/√s)·√(2·ln(1/δ))
   LB(μ,σ,s,δ) = μ − (σ/√s)·√(2·ln(1/δ))
   ```
   τ⁻ is the lowest cutoff whose (statistically corrected) recall still clears the target; τ⁺ is the
   lowest cutoff whose lower-bounded precision clears the target.
4. **Route at runtime:** `score ≥ τ⁺` → accept (proxy), `≤ τ⁻` → reject (proxy); only the ambiguous
   band `τ⁻ < score < τ⁺` pays for the oracle. In reference benchmarks ~85% of calls stay cheap.

Tunable knobs: `recall_target`, `precision_target`, `sampling_percentage`, `failure_probability`,
and the proxy choice (cheap LLM vs. embedding). Applies to any binary/graded LLM judgment (filter,
join verification, pairwise judging, ranking comparisons).

### 1.5 Automatic prompt optimization

Reflective/evolutionary prompt search (e.g. the **GEPA** technique from the DSPy line of work). You
supply labelled examples + an `eval_fn(output, example) -> (score, side_info)` + an `objective`; the
optimizer mutates the NL instructions (via an LLM reflecting on the `side_info` failure diagnostics),
evaluates candidates, and keeps a Pareto frontier — **jointly across a whole pipeline**. A per-node
content cache makes it affordable (only the mutated operator and everything downstream re-runs per
candidate).

---

## Part II — Fit with Aughor (honest positioning)

| Dimension | Aughor | These row-wise LLM-operator systems |
|---|---|---|
| Core competence | **NL → grounded SQL** over a warehouse | LLM operators **over rows** in a dataframe |
| Execution | **push-down** to DuckDB/Postgres | pull-into-memory, **LLM per row** client-side |
| Correctness | Phase-8 binder, fanout de-fan, grain/additivity, finding-trust ladder, Trust Receipts | **gold-algorithm accuracy guarantees** (cascades); otherwise prompt quality |
| Structured analytics | strong (SQL engine) | weak/expensive (row-wise LLM) |
| Unstructured/text analytics | **gap today** | strong (filter/extract/top-k/agg over text) |
| Cost/accuracy optimizer | ad-hoc | **cascades + prompt-opt** (the reusable IP) |
| Provider abstraction | instructor over 5 backends (#33) | a single client wrapper |

**Takeaways:** keep our NL2SQL and push-down — they're better than the row-wise approach for
structured work. Borrow the _optimizer ideas_ (cascades, prompt-opt) and the _unstructured-data
operators_ for the text residue. Do **not** change our provider layer (we already have abstraction +
structured output). These systems have **no** grounding/determinism guards — that asymmetry is ours
to keep.

---

## Part III — The packaging lesson, and a consolidation proposal

The systems that productize these techniques ship a one-screen operator table that makes a research
system instantly legible. Our machinery is _more_ capable but lives as scattered internal phases
(Phase-8, FAN-b, WCH, K0–K4…) with no single externally-facing vocabulary. **We should consolidate
our capabilities under a small set of named "operators/layers," presented as a clean table** — for
internal clarity _and_ marketing.

A proposed naming spine (names are placeholders — the point is the consolidation):

| Named layer | What it consolidates (today, scattered) | One-liner |
|---|---|---|
| **Grounded SQL** | Semantic Compiler · QueryIntent IR · synthesize_sql · Phase-8 binder · fanout de-fan · grain/additivity | "NL in, a number that's _provably_ what the warehouse says — or a refusal." |
| **Trust Layer** | finding-trust ladder · narration-inversion guard · quarantine · Trust Receipts · (NEW) cascade confidence | "Every finding carries calibrated confidence and evidence; the unsure ones escalate." |
| **Adaptive Inference** *(NEW)* | model cascades · per-role provider routing (#33) · optimization-tuned prompts | "Cheap model first, expensive model only where it changes the answer — with a guarantee." |
| **Temporal Scope** | Adaptive Temporal Scope (already a named USP) | "Knows _when_ matters; discovers the window instead of MAX(date)." |
| **Semantic Operators** *(NEW)* | filter/extract/top-k/agg over SQL result text | "Reason over the text columns SQL can't — ranked, extracted, summarised." |

This table is also the integration map: two of its rows ("Adaptive Inference", "Semantic Operators")
are the new capabilities this plan adds; the others are re-namings of what we already ship.

---

## Part IV — Integration plan (prioritised)

### Borrow 1 — Cascade-gated LLM judgments  ·  **Priority 1, effort S–M**

**Where.** Any surface where we make a graded/binary LLM judgment at scale, in priority order:
1. **Hypothesis evaluation** — `aughor/agent/nodes.py::score_evidence` (scores hypotheses serially
   today; this is also the roadmap's "quickest perf win"). _Pilot here._
2. **Finding-trust** — the real/quarantine/narration-inversion judgments in the explorer.
3. **The UNIFY LLM-judge eval scorer** — the canonical pairwise-judge cascade use case.

**Design.**
- Add a `proxy`/`helper` role to the provider layer (`aughor/llm/provider.py`) — a cheap, fast model
  alongside the primary. (#33 already resolves models per-role; this is one more role.)
- Define each surface's **gold algorithm** = the current expensive-model judgment. The guarantee is
  recall/precision _relative to that gold_.
- Implement the cascade core (~150 lines, no external dependency) in e.g. `aughor/llm/cascade.py`:
  importance sampling, logprob calibration, and the Hoeffding threshold learner from §1.4.
- **Confidence source.** Prefer top-logprobs → `P(true)/(P(true)+P(false))`. **Risk:** not all 5
  backends expose `top_logprobs` (OpenAI/vLLM do; some hosted providers don't). Mitigation — support
  an **embedding-similarity proxy** fallback and/or a self-reported confidence field via instructor
  when logprobs are unavailable. The cascade interface is proxy-agnostic.
- **Thresholds are learned once** on a sample and cached; steady-state runs reuse them.

**Verification (the leverage gate).** On a real investigation: (a) measure recall of "supported
hypotheses"/"real findings" of the cascade vs. the all-oracle baseline → must clear the target at δ;
(b) measure oracle-call reduction (expect the bulk resolved cheaply); (c) confirm latency drop on the
serial hypothesis loop. Lock with a unit test asserting the guarantee holds on a fixture.

**Payoff.** Accuracy preserved (provably), cost down, and the serial hypothesis-eval gets both a
parallel cheap pass _and_ fewer expensive calls.

### Borrow 2 — Automatic prompt optimization  ·  **Priority 2, effort M**

**Where.** Our highest-value prompts: explorer angle/hypothesis generation, ADA investigation, the
Semantic-Compiler intent prompt, narration. **Offline** only — optimise, then ship the winning prompt
as a versioned default; never auto-mutate in production.

**Design.** Stand up a prompt-optimization harness (a reflective/evolutionary loop such as GEPA) that
takes (eval set, eval_fn, objective) and returns improved prompt text. Reuse existing eval assets:
the **UNIFY convention-neutral scorer** and the **B-10 benchmark** as eval_fns; expand with a small
labelled set per target prompt.

**Guardrail.** An optimised prompt must still pass through the Phase-8 grounding gate — we optimise
_phrasing for accuracy on the eval_, never relax grounding. The eval_fn should _include_ a
grounding/refusal-correctness term so the optimizer can't win by hallucinating.

**Payoff.** Turns prompt-tuning from art into measured search; compounding gains across a pipeline.

### Borrow 3 — Semantic-operator layer over SQL  ·  **Priority 3, effort M–L (product expansion)**

**The hybrid architecture (respects push-down-first):**
```
NL question → Grounded SQL (push-down: structured filter/agg/join in the warehouse)
            → result set (rows incl. TEXT columns)
            → Semantic Operators (client-side, over the text residue only):
                  filter   — keep rows matching an NL predicate over a text column
                  extract  — pull structured fields out of free text
                  top-k    — rank rows by an NL criterion
                  aggregate — synthesise many text rows → one answer
            → (optionally back into SQL / a Canvas / a finding)
```
Start with semantic **filter** + **extract** over a result set's text column; add **top-k**/
**aggregate** next. Each runs through the **same cascade** (Borrow 1) so it's cost-bounded. Surface it
as an explicit "semantic step" in the Query Builder and as a composable tool for ADA.

**Why this is the right shape:** SQL does what SQL is good at (the structured 99%); the LLM only
touches the text residue — never the bulk scan the row-wise systems pay for. This fills the gap in our
offering (text/unstructured analytics) _without_ giving up our efficiency or grounding.

### Borrow 4 — Hierarchical synthesis for Briefings  ·  **effort S**

Replace any single-stuffed-prompt synthesis in the Briefing/Hub with the hierarchical
map-reduce-over-context-windows pattern (pack → summarise → recurse). Better long-context fidelity
when synthesising many findings; partition-aware so it won't blend unrelated domains.

### Borrow 5 — Semantic dedup + calibrated confidence  ·  **effort S**

- **Ontology entity merging:** embedding self-similarity-join + threshold + connected-components to
  collapse near-duplicate entities (cleaner ontology board).
- **Calibrated trust numbers:** the `P(true)/(P(true)+P(false))` logprob technique gives a real
  confidence for finding-trust scores (feeds the Trust Layer in §3).

---

## Part V — Sequencing

- **Phase 1 (now):** Borrow 1 cascade core (`aughor/llm/cascade.py` + a `helper` provider role) →
  pilot on **hypothesis-eval**. Prove the guarantee + the cost/latency win on a real run. _This is
  the recommended starting point._
- **Phase 2:** extend the cascade to finding-trust + the UNIFY judge; ship the **"Adaptive
  Inference" / "Trust Layer"** naming (§3).
- **Phase 3:** prompt-optimization harness over the top 2–3 prompts, scored on UNIFY/B-10.
- **Phase 4:** the **Semantic-Operator layer** over SQL results (the product expansion), cost-bounded
  by the Phase-1 cascade, surfaced in Query Builder + ADA.

---

## Part VI — Non-goals, risks, open questions

**Non-goals.** Replace NL2SQL with a row-wise operator system (no — we're better). Move structured
compute client-side (no — keep push-down). Change the provider layer (no — we have abstraction +
structured output). Take on an external framework as a dependency (no — port the ~150-line cascade
core; optionally use an existing prompt-optimizer library for Borrow 2 only).

**Risks.**
- _Logprob availability_ across our 5 backends — mitigated by the embedding-proxy / self-reported-
  confidence fallback (Borrow 1).
- _Defining the "gold algorithm"_ per judgment surface — required for the guarantee to mean
  something; needs a short design pass per surface.
- _Eval-set investment_ for prompt optimization — we have UNIFY + B-10 to seed it, but coverage per
  target prompt must grow.
- _Cascade thresholds drift_ if the data distribution shifts — re-learn periodically (cheap).

**Open questions for product.**
1. First cascade target — hypothesis-eval (perf + accuracy, lowest risk) vs. finding-trust (most
   user-visible trust win)?
2. Is the **Semantic-Operator layer** (Borrow 3) a near-term product bet, or a Phase-4 follow-on
   after the cascade lands?
3. Do we want the §3 naming consolidation done as a deliberate product/marketing pass alongside the
   engineering?

---

## Part VII — Build outcomes & learnings (2026-06-14/15)

We built and stress-tested Borrows 1 and 2. Both ended in **honest negative results that the built-in
guardrails caught** — which is the system working, not failing.

### Borrow 1 — model cascade: BUILT, then PARKED (blocked on a model)
- **Shipped (#49):** the generic cascade core (`aughor/llm/cascade.py`, Hoeffding guarantee proven on
  synthetic data), `get_proxy_provider`, and an opt-in cascade on hypothesis scoring
  (`AUGHOR_CASCADE_HYPOTHESIS`, fail-safe). Calibration harness = **PR #50 (parked-open)**.
- **The wall:** the proxy signal is the cheap model's self-reported `EvidenceScore.confidence`, and on a
  live 45-example calibration **every accessible cheap model is miscalibrated** — gemma4:31b,
  qwen2.5-coder:14b, and Cohere command-r7b all cluster confidence at 0.6–0.8 regardless of the evidence
  (command-r7b even *confirmed* a clearly-refuting case). So the cascade can't trust them → escalates
  ~85% → only **~15% oracle-call saving**. The one well-calibrated model tried (Cohere
  `command-a-reasoning`, confidence spanning 0.0–0.6) is a **slow reasoning model**, not cheap.
- **The crucial constant:** in *every* run the **recall guarantee held at 1.0** — the cascade never traded
  accuracy for cost. A bad proxy yields fewer savings, never wrong answers. That's the guarantee doing
  its job.
- **The grail, and why it's parked:** the cheap-*and*-calibrated candidate is **Cohere North Mini Code**
  (30B/3B-active MoE) — but it's **access-gated** (Cohere's enterprise "North" platform; not on the trial
  API; its 128-expert MoE isn't runnable on Ollama/llama.cpp; needs an H100). Parked until a
  cheap+calibrated proxy + access exists. (A Cohere backend was wired to test it, then reverted.)

### Borrow 2 — prompt optimization (GEPA-style): BUILT, then DROPPED
- A reflective hill-climb over `CHAT_SQL_SYSTEM`, scored on the 53-pair golden NL2SQL set with the
  deterministic `sql_accuracy` scorer, **held-out gated** (a candidate is adopted only if it beats the
  current best on train).
- **Result:** it **overfit** — train 0.645 → 0.674 but **held-out 0.645 → 0.644 (no lift)**. The held-out
  split correctly **refused to certify a fake win**. The conclusion: the hand-tuned `CHAT_SQL_SYSTEM` is
  already strong, and naive reflective optimization on a thin (53) eval set can't beat it. **Dropped.**
- **To revisit:** a larger eval set (>53), held-out (not train) selection inside the loop, and a
  *less-tuned* target prompt (e.g. an explore-mode prompt) — there isn't enough headroom on the
  battle-tested chat prompt.

### Model decision
Kept **`qwen3-coder-next:cloud`** as the main coder model. In a 53-question golden-SQL bake-off,
`kimi-k2.7-code:cloud` was *more accurate* (+0.047 mean, +4 pass@80, winning the medium-difficulty band)
but **~6× slower** (~20s vs ~3s) — unacceptable latency for the interactive coder role.

### Borrow 3 — semantic operators over SQL: NOT STARTED
The remaining, highest-upside borrow (§4). Unblocked by the above (it doesn't depend on the cascade
landing) and the clearest *new capability* — see §3/§4. The recommended next adaptive-inference step.

**Meta-learning:** the two guardrails we designed in — the cascade's recall **guarantee** and GEPA's
**held-out split** — each independently caught a result that *looked* like a win but wasn't. Measuring
honestly saved us from shipping a miscalibrated cascade and an overfit prompt.
