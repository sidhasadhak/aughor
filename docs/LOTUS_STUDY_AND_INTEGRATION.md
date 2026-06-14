# LOTUS — Study & Integration Plan

*Deep study of the LOTUS semantic-operator system + LOTUSPlan, and a grounded plan for what
Aughor should borrow. 2026-06-14.*

Sources studied file-by-file: [`lotus-data/lotus`](https://github.com/lotus-data/lotus) ·
paper *"Semantic Operators: A Declarative Model for Rich, AI-based Data Processing"*
(Patel, Jha, Pan, Gupta, Asawa, Guestrin, Zaharia — [arXiv:2407.11418](https://arxiv.org/abs/2407.11418), VLDB) ·
the [LOTUSPlan](https://liana313.github.io/blog/lotusplan.html) blog.

---

## TL;DR

**LOTUS is complementary to Aughor, not a competitor, and it will _not_ directly improve our
NL2SQL** — it does not generate SQL; it `SELECT *`s a table into pandas and runs an LLM call _per
row_ client-side. On the thing we care about most — **grounded, push-down, deterministically-guarded
analytics** — Aughor is the stronger system. The transfer is **one-directional (LOTUS → Aughor)**
and it is about three reusable _ideas_, not adopting the framework:

1. **Model cascades with a statistical accuracy guarantee** — a cheap proxy model answers the easy
   cases, only the ambiguous middle escalates to the expensive model, and the routing thresholds are
   _proven_ to hold a target recall/precision at failure-probability δ. This is the single highest-
   leverage borrow: it cuts cost **and latency** on our many LLM judgment calls _while guaranteeing_
   accuracy relative to the expensive model — exactly our "numbers you can act on" mandate. It rides
   the per-role provider config we shipped in #33.
2. **GEPA-style automatic prompt optimization** — search over prompt phrasings against a labelled
   eval set, instead of hand-tuning. We already have eval scorers (UNIFY) and a benchmark (B-10).
3. **A semantic-operator layer over SQL results** — for the _unstructured residue_ (text columns:
   tickets, reviews, notes, incident write-ups) that SQL can't reason over. SQL push-down for the
   structured work (our strength) + a small set of semantic operators client-side for the text. This
   is a genuine **product-offering expansion**, not a re-architecture.

**Meta-lesson (per the product call):** LOTUS's real edge is **packaging** — it consolidates a pile
of LLM-data operations under _one crisp abstraction_ ("semantic operators") with great naming, which
makes powerful machinery legible and sellable. Aughor has _more_ powerful machinery but it is
scattered and under-named. §4 proposes how to consolidate.

**Recommended first step:** a cascade pilot on **hypothesis evaluation** (`aughor/agent/nodes.py`,
`score_evidence`) — which also happens to be the "quickest standalone perf win" already on the
roadmap (it scores hypotheses serially today).

---

## Part I — What LOTUS is (the study)

### 1.1 The thesis

LLM operations over data should be **declarative relational operators**, not bespoke pipelines.
Define each operator's intended behaviour with a **"gold algorithm"** (a high-quality reference
implementation), then let an optimizer **cut cost while _provably_ staying within an accuracy band of
that gold algorithm.** Headline numbers from the paper: **up to 1000× op-level speedups**, **3.6×
faster end-to-end** than the highest-quality baselines, **+170% quality** vs prior LLM analytic
systems — _with accuracy guarantees_. LOTUSPlan (lazy execution + pluggable optimizers) reports **up
to 2.4× cheaper / 4.6× more accurate**.

This "gold algorithm + provable faithfulness of the fast path" discipline is _exactly_ the shape of
our own correctness guards (Phase-8 binder, fanout de-fan, grain/additivity, the finding-trust
ladder). LOTUS is intellectually aligned with us; it just applies the discipline to a different layer
(LLM-over-rows rather than SQL-over-warehouse).

### 1.2 The formal model — semantic operators

NL-parameterised analogs of SQL operators. Each is given a natural-language expression ("langex")
with `{column}` placeholders, e.g. `df.sem_filter("the {title} is science fiction")`.

| Operator | Kind | Meaning | Naive cost |
|---|---|---|---|
| `sem_filter` | LLM | keep rows where an NL predicate is true | 1 call / row |
| `sem_map` | LLM | NL projection → new column | 1 call / row |
| `sem_extract` | LLM | pull structured fields from text (JSON) | 1 call / row |
| `sem_agg` | LLM | NL many-rows → one (summarise) | tree-reduce over context windows |
| `sem_topk` | LLM | rank by an NL criterion | pairwise compares (n² / n·log n / heap) |
| `sem_join` | LLM | join two tables on an NL predicate | \|L\|·\|R\| (full cross-product) |
| `sem_search` / `sem_sim_join` / `sem_dedup` / `sem_cluster_by` | embedding | retrieval / similarity-join / near-dup removal / clustering | embeddings only, no LLM |

Notable algorithm facts (all read in source):
- **`sem_join` = `sem_filter` over the Cartesian product** (no dedicated prompt). The cascade path
  first _blocks_ with an embedding similarity-join, then verifies only survivors with the LLM.
- **`sem_topk`** reduces ranking to **binary "which doc is more relevant" LLM comparisons**, driven
  by quicksort/heap/quadratic-vote; `quick` prunes to the top-K so it never sorts the tail.
- **`sem_agg`** is a **hierarchical tree-reduce**: greedily pack docs into a context window,
  summarise each batch, recurse over the summaries until one remains. (Directly relevant to our
  Briefing synthesis.)
- **`sem_dedup`** = embedding self-similarity-join + threshold + connected-components → keep one per
  component. (Directly relevant to ontology entity merging.)

### 1.3 The structure

```
df.sem_*(...)                                       ← eager API (pandas accessor, no optimization)
LazyFrame().sem_*(...).optimize([...]).execute(df)  ← lazy API
        │
        ├─ AST: immutable Pydantic nodes (one per op), thin wrappers over the df.sem_* accessors
        ├─ Optimizer passes: list[Node] → list[Node]  (composable, ordered)
        │     • PredicatePushdownOptimizer  — cheap pandas filters before expensive sem_filters
        │     • GEPAOptimizer               — rewrite the NL prompts against an eval_fn
        │     • CascadeOptimizer            — learn proxy→oracle routing thresholds on train data
        └─ Runner: linear fold over nodes + content-addressable per-node cache
```

One LLM choke point (`lotus/models/lm.py`, LiteLLM `batch_completion`; structured output via
`response_format` — **no instructor**), a dual virtual/physical cost ledger, RPM/TPM governors.

**The single most important architectural fact for us:** the SQL connector is
`pd.read_sql(query, conn)` straight into pandas — **zero push-down**. LOTUS is _not_ a NL2SQL system;
its "predicate pushdown" reorders _pandas_ filters, not SQL. Everything semantic happens row-by-row
in the Python process.

### 1.4 The crown jewel — model cascades (`lotus/sem_ops/cascade_utils.py`)

This is the reusable IP. The mechanism, exactly as implemented:

1. **Proxy scores every item.** Either (a) a cheap helper LM run with `logprobs=True`, whose answer-
   token logprobs are renormalised to `P(positive) = P(True)/(P(True)+P(False))`, or (b) embedding
   similarity. Scores are calibrated by quantile-binning (`calibrate_llm_logprobs`).
2. **Importance-sample** a small subset (weight ∝ √score, `sampling_percentage` of rows) and run the
   **expensive oracle** only on that sample, keeping unbiased correction factors.
3. **Learn two thresholds (τ⁺, τ⁻)** so the routing meets a **target recall & precision with
   probability ≥ 1−δ**, using Hoeffding confidence bounds:

   ```
   UB(μ,σ,s,δ) = μ + (σ/√s)·√(2·ln(1/δ))
   LB(μ,σ,s,δ) = μ − (σ/√s)·√(2·ln(1/δ))
   ```
   τ⁻ is chosen as the lowest cutoff whose (statistically corrected) recall still clears the target;
   τ⁺ is the lowest cutoff whose lower-bounded precision clears the target. (`learn_cascade_thresholds`.)
4. **Route at runtime:** `score ≥ τ⁺` → accept (proxy), `≤ τ⁻` → reject (proxy); only the ambiguous
   band `τ⁻ < score < τ⁺` pays for the oracle. In their benchmarks ~85% of calls stay cheap.

`CascadeArgs` knobs: `recall_target=0.8`, `precision_target=0.8`, `sampling_percentage=0.1`,
`failure_probability=0.2`, `proxy_model ∈ {HELPER_LM, EMBEDDING_MODEL}`. Supported by `sem_filter`,
`sem_join`, `pairwise_judge`, and (fixed-threshold) `sem_topk`.

### 1.5 The other optimizer — GEPA (`lotus/ast/optimizer/gepa_optimizer.py`)

Reflective prompt evolution (from DSPy). You supply labelled examples + an `eval_fn(output, example)
-> (score, side_info)` + an `objective`; GEPA mutates the NL instructions (via an LLM reflecting on
the `side_info` failure diagnostics), evaluates candidates, and keeps a Pareto frontier. It optimises
**jointly across the whole pipeline** (every operator's prompt is one candidate genome). LOTUS's file
is just the adapter (node-tree ⇄ flat candidate dict + the evaluator); the search lives in the
external `gepa` package. The per-node content cache makes this affordable — only the mutated operator
and everything downstream re-runs per candidate.

---

## Part II — Aughor vs LOTUS (honest positioning)

| Dimension | Aughor | LOTUS |
|---|---|---|
| Core competence | **NL → grounded SQL** over a warehouse | LLM operators **over rows** in pandas |
| Execution | **push-down** to DuckDB/Postgres | pull-into-pandas, **LLM per row** client-side |
| Correctness | Phase-8 binder, fanout de-fan, grain/additivity, finding-trust ladder, Trust Receipts | **gold-algorithm accuracy guarantees** (cascades); otherwise prompt quality |
| Structured analytics | strong (SQL engine) | weak/expensive (row-wise LLM) |
| Unstructured/text analytics | **gap today** | strong (sem_filter/extract/topk/agg over text) |
| Cost/accuracy optimizer | ad-hoc | **cascades + GEPA** (the reusable IP) |
| Provider abstraction | instructor over 5 backends (#33) | LiteLLM |

**Takeaways:** keep our NL2SQL and push-down — they're better than anything in LOTUS. Borrow LOTUS's
_optimizer ideas_ (cascades, GEPA) and its _unstructured-data operators_ for the text residue. Do
**not** swap instructor→LiteLLM (we already have provider abstraction + structured output). LOTUS has
**no** grounding/determinism guards — that asymmetry is ours to keep.

---

## Part III — The packaging lesson, and a consolidation proposal

LOTUS ships a one-screen operator table (§1.2) that makes a research system instantly legible. Our
machinery is _more_ capable but lives as scattered internal phases (Phase-8, FAN-b, WCH, K0–K4…) with
no single externally-facing vocabulary. **We should consolidate our capabilities under a small set of
named "operators/layers," presented the way LOTUS presents its operator table** — for internal
clarity _and_ marketing.

A proposed naming spine (names are placeholders — the point is the consolidation):

| Named layer | What it consolidates (today, scattered) | One-liner |
|---|---|---|
| **Grounded SQL** | Semantic Compiler · QueryIntent IR · synthesize_sql · Phase-8 binder · fanout de-fan · grain/additivity | "NL in, a number that's _provably_ what the warehouse says — or a refusal." |
| **Trust Layer** | finding-trust ladder · narration-inversion guard · quarantine · Trust Receipts · (NEW) cascade confidence | "Every finding carries calibrated confidence and evidence; the unsure ones escalate." |
| **Adaptive Inference** *(NEW, from LOTUS)* | model cascades · per-role provider routing (#33) · GEPA-tuned prompts | "Cheap model first, expensive model only where it changes the answer — with a guarantee." |
| **Temporal Scope** | Adaptive Temporal Scope (already a named USP) | "Knows _when_ matters; discovers the window instead of MAX(date)." |
| **Semantic Operators** *(NEW, from LOTUS)* | sem_filter/extract/topk/agg over SQL result text | "Reason over the text columns SQL can't — ranked, extracted, summarised." |

This table is also the integration map: two of its rows ("Adaptive Inference", "Semantic Operators")
are the new capabilities this plan adds; the others are re-namings of what we already ship.

---

## Part IV — Integration plan (prioritised)

### Borrow 1 — Cascade-gated LLM judgments  ·  **Priority 1, effort S–M**

**Where.** Any surface where we make a graded/binary LLM judgment at scale, in priority order:
1. **Hypothesis evaluation** — `aughor/agent/nodes.py::score_evidence` (scores hypotheses serially
   today; this is also the roadmap's "quickest perf win"). _Pilot here._
2. **Finding-trust** — the real/quarantine/narration-inversion judgments in the explorer.
3. **The UNIFY LLM-judge eval scorer** — literally LOTUS's `pairwise_judge` cascade use case.

**Design.**
- Add a `proxy`/`helper` role to the provider layer (`aughor/llm/provider.py`) — a cheap, fast model
  alongside the primary. (#33 already resolves models per-role; this is one more role.)
- Define each surface's **gold algorithm** = the current expensive-model judgment. The guarantee is
  recall/precision _relative to that gold_.
- Port `learn_cascade_thresholds` + `importance_sampling` + `calibrate_llm_logprobs` from
  `cascade_utils.py` (~150 lines, no LOTUS dependency) into e.g. `aughor/llm/cascade.py`.
- **Confidence source.** Prefer top-logprobs → `P(true)/(P(true)+P(false))`. **Risk:** not all 5
  backends expose `top_logprobs` (OpenAI/vLLM do; some hosted providers don't). Mitigation — support
  the **embedding-similarity proxy** fallback (LOTUS's `EMBEDDING_MODEL` mode) and/or a self-reported
  confidence field via instructor when logprobs are unavailable. The cascade interface is
  proxy-agnostic.
- **Thresholds are learned once** on a sample and cached (like `CascadeOptimizer`); steady-state runs
  reuse them.

**Verification (the leverage gate).** On a real investigation: (a) measure recall of "supported
hypotheses"/"real findings" of the cascade vs. the all-oracle baseline → must clear the target at δ;
(b) measure oracle-call reduction (expect the bulk resolved cheaply); (c) confirm latency drop on the
serial hypothesis loop. Lock with a unit test asserting the guarantee holds on a fixture.

**Payoff.** Accuracy preserved (provably), cost down, and the serial hypothesis-eval gets both a
parallel cheap pass _and_ fewer expensive calls.

### Borrow 2 — GEPA automatic prompt optimization  ·  **Priority 2, effort M**

**Where.** Our highest-value prompts: explorer angle/hypothesis generation, ADA investigation, the
Semantic-Compiler intent prompt, narration. **Offline** only — optimise, then ship the winning prompt
as a versioned default; never auto-mutate in production.

**Design.** Stand up a GEPA harness (use the `gepa` package, or implement the reflective loop) that
takes (eval set, eval_fn, objective) and returns improved prompt text. Reuse existing eval assets:
the **UNIFY convention-neutral scorer** and the **B-10 benchmark** as eval_fns; expand with a small
labelled set per target prompt.

**Guardrail.** A GEPA-optimised prompt must still pass through the Phase-8 grounding gate — we
optimise _phrasing for accuracy on the eval_, never relax grounding. The eval_fn should _include_ a
grounding/refusal-correctness term so GEPA can't win by hallucinating.

**Payoff.** Turns prompt-tuning from art into measured search; compounding gains across a pipeline.

### Borrow 3 — Semantic-operator layer over SQL  ·  **Priority 3, effort M–L (product expansion)**

**The hybrid architecture (respects push-down-first):**
```
NL question → Grounded SQL (push-down: structured filter/agg/join in the warehouse)
            → result set (rows incl. TEXT columns)
            → Semantic Operators (client-side, over the text residue only):
                  sem_filter   — keep rows matching an NL predicate over a text column
                  sem_extract  — pull structured fields out of free text
                  sem_topk     — rank rows by an NL criterion
                  sem_agg      — synthesise many text rows → one answer
            → (optionally back into SQL / a Canvas / a finding)
```
Start with `sem_filter` + `sem_extract` over a result set's text column; add `sem_topk`/`sem_agg`
next. Each runs through the **same cascade** (Borrow 1) so it's cost-bounded. Surface it as an
explicit "semantic step" in the Query Builder and as a composable tool for ADA.

**Why this is the right shape:** SQL does what SQL is good at (the structured 99%); the LLM only
touches the text residue — never the bulk scan LOTUS pays for. This is the gap in our offering
(text/unstructured analytics) filled _without_ giving up our efficiency or grounding.

### Borrow 4 — `sem_agg` tree-reduce for Briefing synthesis  ·  **effort S**

Replace any single-stuffed-prompt synthesis in the Briefing/Hub with LOTUS's hierarchical
map-reduce-over-context-windows (pack → summarise → recurse). Better long-context fidelity when
synthesising many findings; partition-aware so it won't blend unrelated domains.

### Borrow 5 — `sem_dedup` + calibrated confidence  ·  **effort S**

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
- **Phase 3:** GEPA harness over the top 2–3 prompts, scored on UNIFY/B-10.
- **Phase 4:** the **Semantic-Operator layer** over SQL results (the product expansion), cost-bounded
  by the Phase-1 cascade, surfaced in Query Builder + ADA.

---

## Part VI — Non-goals, risks, open questions

**Non-goals.** Replace NL2SQL with LOTUS (no — we're better). Move structured compute client-side
(no — keep push-down). Swap instructor→LiteLLM (no — we have provider abstraction). Adopt the LOTUS
package as a dependency (no — port the ~150-line cascade core; optionally depend on `gepa` for
Borrow 2 only).

**Risks.**
- _Logprob availability_ across our 5 backends — mitigated by the embedding-proxy / self-reported-
  confidence fallback (Borrow 1).
- _Defining the "gold algorithm"_ per judgment surface — required for the guarantee to mean
  something; needs a short design pass per surface.
- _Eval-set investment_ for GEPA — we have UNIFY + B-10 to seed it, but coverage per target prompt
  must grow.
- _Cascade thresholds drift_ if the data distribution shifts — re-learn periodically (cheap).

**Open questions for product.**
1. First cascade target — hypothesis-eval (perf + accuracy, lowest risk) vs. finding-trust (most
   user-visible trust win)?
2. Is the **Semantic-Operator layer** (Borrow 3) a near-term product bet, or a Phase-4 follow-on
   after the cascade lands?
3. Do we want the §3 naming consolidation done as a deliberate product/marketing pass alongside the
   engineering?

---

*Companion: the per-file technical brief lives in the session study; the borrowable cascade math is
`lotus/sem_ops/cascade_utils.py`, GEPA is `lotus/ast/optimizer/gepa_optimizer.py`.*
