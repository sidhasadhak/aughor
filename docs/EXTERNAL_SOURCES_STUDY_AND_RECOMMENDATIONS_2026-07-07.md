# External-Sources Study & Recommendations — DocETL · Palimpzest · Hasura/PromptQL · DAB

**Date:** 2026-07-07 · **Author:** 10x assessment session · **Status:** recommendation doc (one increment shipped)

> **Mandate.** Study four external systems/papers — [Palimpzest](https://palimpzest.org/),
> [Hasura graphql-engine](https://github.com/hasura/graphql-engine), [PromptQL](https://promptql.io/about),
> the **DocETL** paper (arXiv 2410.12189), and the **DataAgentBench (DAB)** paper (arXiv 2603.20576) —
> extract their concepts and workings, and translate them into concrete, iterable improvements for Aughor.

---

## 0 · Executive summary

**The single most important finding is that all four sources independently converge on Aughor's own thesis:**
*a declarative plan separated from deterministic execution, with the LLM's non-determinism confined to
small, bounded, **validated** operations.* This is exactly Aughor's "deterministic guards > LLM machinery
on strong models" principle (see the [NL2SQL benchmarking conclusion](../AGENT_NOTES.md) and
`SPIDER2_PROGRESS_AND_CHALLENGES_2026-06-28.md` §14). These systems therefore **do not redirect Aughor —
they validate its direction and supply specific mechanisms it has not yet built.**

Two external data points make the case that grounding-first is correct, not just comfortable:
- On **DAB**, PromptQL's semantic/context layer beat a plain ReAct agent by **+7 pts pass@1** on the same model.
- On **CRMArena-Pro** (database querying + numerical computation), PromptQL scored **100% vs ~58%** for
  leading single-turn agent loops.

**Where the leverage is** — DAB (the frontier benchmark that supersedes single-DB Spider 2.0) quantifies it.
Best frontier model = **38% pass@1**, so the headroom is enormous, and the difficulty decomposes into four
axes. Aughor's position on each:

| DAB difficulty axis | Query coverage | Aughor today | Gap size |
|---|---|---|---|
| Multi-database integration | **54/54** | thin `connectors/federated.py` (DuckDB `ATTACH`/Arrow); no cross-source entity resolution | **Large** |
| Unstructured-text → structured value | **47/54** (0% on the hardest, patents) | `semops.semantic_extract`, single-call, **no validation** | **Medium** → *addressed this session* |
| Domain knowledge (conventions) | 30/54 | ontology / metrics catalog / Specialist Packs | **Small** (well-positioned) |
| Ill-formatted join keys | 26/54 | overlap-probe join guard, single-DB only | **Medium** |

And the failure-mode split is decisive: **85% of frontier failures are planning + implementation**
(FM2 40% + FM4 45%); data selection is only 15%. The bottleneck is *reasoning about how to combine and
compute over data* — precisely what a deterministic plan + guard battery attacks.

**Recommendation, one line:** ship guarded operators now (done — §5), then invest in **cross-source
federation** (DAB's master gap, and the "enterprise platform of the future" the mandate calls for), with
**plan-as-program + artifacts** as the deeper follow-on. Do *not* adopt the LLM-judge machinery these
systems use for plan selection — that is the one place they bet opposite to Aughor's proven finding.

---

## 1 · DAB — the benchmark that reframes the target

**Paper:** "Can AI Agents Answer Your Data Questions? A Benchmark for Data Agents," Ma, Shankar, Chen, Lin,
Zeighami, Ghosh, Gupta×2, Gopal, Parameswaran (UC Berkeley EPIC / Hasura PromptQL). arXiv:2603.20576.
Repo: `github.com/ucbepic/DataAgentBench`.

- **Composition:** 54 queries · 12 datasets · 9 domains · **4 DBMS (PostgreSQL, MongoDB, SQLite, DuckDB)**.
  Extreme table-count range (2 → 2,754). Answer-substring grading (`validate.py` per query), so heterogeneous
  SQL/Python/multi-DB solution paths are all gradable; **pass@1 primary**, n=50 trials/query.
- **Scores:** Gemini-3-Pro 38% · GPT-5-mini 30% · GPT-5.2 25% · Kimi-K2 23% · Gemini-2.5-Flash 9%.
  Note GPT-5-mini **beating** GPT-5.2 — raw scale does not predict data-task accuracy; **scaffolding dominates.**
- **Why so low:** every query composes multiple hard axes at once. The **patents dataset scores 0% across
  every model** because it needs dates parsed out of prose and *every agent falls back to regex; none attempts
  NER/LLM extraction.* Even pass@50 never exceeds ~69% → a capability ceiling, not sampling variance.
- **Failure modes** (1,147 incorrect trajectories): FM4 incorrect-implementation **45%**, FM2 incorrect-plan
  **40%**, FM3 incorrect-data-selection **15%**, FM1 fails-before-planning ~0%, FM5 runtime small.
  → **plan + implementation = 85%.**
- **Takeaways for builders:** ship dedicated extraction/parsing tools (not regex); push aggregation into the
  DBMS (Python-heavy strategies were ~20× more expensive *and* less accurate); invest in planning/decomposition
  not execution retries; a semantic/context layer helps (+7 pts); right-size exploration (~20% of tool calls);
  treat cross-DB integration + key reconciliation as first-class.

**Implication for Aughor.** Aughor's Spider-2.0 pedigree covers exactly one axis (single-DB complex SQL).
It already *owns* the domain-knowledge axis (ontology/metrics/Packs) and has the right *shape* for
key-reconciliation (the value-overlap join guard). The two axes that would move the score most and that
Aughor cannot currently touch are **multi-DB federation** and **guarded unstructured-text extraction** — and
the latter is the strategic wedge because it is where Aughor's deterministic-guard philosophy can *beat*
frontier models rather than tie them.

---

## 2 · Concept extraction, source by source

### 2.1 DocETL — agentic rewriting + gleaning (accuracy, not cost)

**Paper:** arXiv 2410.12189 (VLDB 2025), UC Berkeley EPIC. Thesis: prior declarative LLM-data frameworks
optimize *cost* and run ops as-is in one LLM call; DocETL optimizes *accuracy* via agent-generated logical
rewrites + agent-guided evaluation, yielding outputs 25–80% more accurate.

- **Operators:** LLM-powered (map, parallel_map, filter, reduce, resolve, equijoin) + auxiliary
  (split, gather, unnest, sample, code). **Reduce** uses incremental *fold + scratchpad* (LLM state carried
  across folds) for groups larger than the context window. **Resolve** = two-stage entity resolution:
  *blocking* (embedding threshold auto-tuned to 0.95 recall, OR a code predicate) → *comparison* (Union-Find
  clustering via an LLM binary-match prompt) → *canonicalization*.
- **Agentic query rewriting:** the optimizer walks each op, synthesizes a validation prompt, runs on a sample;
  if satisfactory it leaves the op **unchanged**, else applies rewrite directives (document-chunking
  `Map ⇒ Split→Gather→Map→Reduce`, multi-level aggregation, projection chaining/isolating, duplicate-resolution)
  and recursively optimizes the new ops.
- **★ Gleaning** (the load-bearing transfer): a validate-and-refine loop on any LLM op. Run the op → **append
  a validation prompt to the same chat thread** → the judge returns an assessment (needs-refinement + how) →
  if so, re-run with the feedback in context → **terminate when the validator passes or `num_rounds` is hit.**
  Optional `if` gate skips gleaning entirely. At least doubles LLM calls per op, so it is applied selectively.
- **Plan selection:** top-k absolute rating (1–4 scale) then pairwise tournament among the top-k.

**Transfer to Aughor:** gleaning maps directly onto the text semops (§5, shipped). Resolve's
blocking-at-0.95-recall + Union-Find is the template for cross-source entity resolution (§7.3). *Caveat:*
DocETL's whole premise (base ops are inaccurate, need LLM rewrite scaffolding) is the **opposite** of
Aughor's proven finding on strong models — so adopt gleaning on the *unstructured* surface (where no
deterministic guard is possible), **not** as LLM-judge scaffolding around SQL generation.

### 2.2 Palimpzest — a declarative optimizer for semantic operators

**Papers:** arXiv 2405.14696 (tech report), CIDR 2025, and the follow-on **Abacus** (arXiv 2505.14661).
MIT DB Group. Treats an AI workload as *relational views*: typed `Schema`s with natural-language field
descriptions, operators `project / filter / convert(χ) / groupby / limit / aggregate`.

- **★ `convert(χ)`** — the core novelty: "transform an object of schema A into schema B" (i.e. extract
  structured fields from unstructured input) as a **first-class relational operator** with *many physical
  implementations* (different model, prompt strategy, synthesized code, fine-tuned student).
- **Optimizer** — finds a **Pareto-optimal physical plan** over {runtime, cost, quality}; the user picks a
  point via a **policy** (`MinCostAtFixedQuality`, `MaxQualityAtFixedCost`, `MaxQuality`, `MinCost`, `MinTime`).
  Search space: model selection, **code synthesis** (replace an LLM call with a generated function where deep
  semantics aren't needed), input/output token reduction (micro-RAG), prompt marshaling, ensembles (MoA),
  refinement (propose→critique→refine — same shape as gleaning).
- **★ Reference-free quality estimation** — rank a cheap operator's quality by comparing its output to a
  **"champion model"** (e.g. the strongest model) on a small sample, **with no labeled data**. Later
  generalized to an optional `Validator` / labels. Plan quality ≈ *product* of per-op qualities, cost ≈ *sum*,
  under an operator-independence assumption; Abacus upgrades sentinel sampling to a **Multi-Armed Bandit** over
  a fixed `sample_budget`.

**Transfer to Aughor:** (a) a **cost/quality cascade on the semops** — run the cheap `fast` role first,
validate against a strong `reasoner` "champion" on a sample, escalate only the rows that disagree (§7.4);
(b) code-synthesis for deterministic extractions (a generated regex/parser that the champion validates —
turns a repeated LLM extract into a one-time synthesized function); (c) the `convert` framing legitimizes a
proper document-extraction operator (§7.4).

### 2.3 Hasura GraphQL Engine (DDN v3) — reliable cross-source access

**Repo:** `github.com/hasura/graphql-engine` (`v3/`, Rust). **Spec:** `github.com/hasura/ndc-spec`.

- **★ NDC (Native Data Connectors)** — every source sits behind a connector that declares its **capabilities**
  (`/capabilities`: which filters/aggregates/relationships/variables it supports) and **schema** (`/schema`).
  The planner pushes down an operation **only when the connector's contract advertises support**; unsupported
  ops are handled engine-side or rejected — *no silent lowest-common-denominator wrong results.* The contract
  is **frozen into metadata at build time**, so the plan can't drift from what the source actually supports.
- **★ Batched foreach remote joins** — to join source A → source B across different systems: run A, **collect
  the join-key values, dedup them into a set, and issue ONE keyed request** to B carrying N variable sets
  (`query.variables` capability); B returns one RowSet per key, in order; the engine re-assembles by key.
  **N+1 is avoided structurally by the protocol**, not by per-connector hacks. A cross-source *filter* is
  handled by `remote_predicates`: pre-fetch the keys, rewrite the predicate as an **OR-of-equalities pushed
  into a single WHERE** on the primary source.
- **★ Declarative permissions compiled into the predicate** — per-role boolean row-filters + column allow-lists
  parameterized by session variables; the filter is **ANDed into the pushed-down WHERE at the source**
  (including remote-join legs), so a role physically cannot read rows outside its filter.

**Transfer to Aughor:** (a) an **internal connector-capability contract** so the semantic compiler decides
pushdown-vs-engine-side deterministically per dialect (fewer probe-repair round trips); (b) **batched-foreach
remote joins** as the correct-by-construction cross-source path where DuckDB `ATTACH` can't reach
(Snowflake↔BigQuery↔Postgres); (c) compile Aughor's RBAC row policy **into the WHERE** for data-level,
cross-source-safe enforcement (rides `aughor/rbac/policy.py`).

### 2.4 PromptQL — plan-as-program + artifacts

**Source:** promptql.io (Hasura). Inverts the standard pattern: instead of retrieving data into the LLM's
context and letting it loop, an LLM **generates a query plan and then a Python program** implementing it,
**executed deterministically in a sandbox outside the LLM.** "The LLM plans; code executes."

- **★ The plan is a program** with two op families: **deterministic data/compute ops** (`executor.run_sql`,
  vector/keyword/attribute search, API calls, ordinary Python joins/filters/arithmetic) and **LLM primitives
  as functions** (`classify`, `summarize`, `extract`) that operate on *rows the program hands them*, not on a
  context dump. Plans can self-modify mid-execution and can insert a **human-confirmation step before an action**.
- **★ Artifacts = structured working memory** — every intermediate result is stored in a named artifact (table
  or text) referenced by later steps; **raw data never floods the context window**, so accuracy doesn't decay
  with data volume (their documented RAG failure: 208,600 tokens > 200,000 max). Artifacts persist across a
  thread and across API calls.
- **★ Repeatability** — once emitted, the program runs as deterministic code; re-running yields the same
  result. Plan + program are both visible, editable, verifiable. The stated contrast with tool-calling loops:
  probabilistic tool selection ⇒ inconsistent approach; conflating plan-creation with plan-execution in one
  context ⇒ compounding failure surface.

**Transfer to Aughor:** this is the deepest and highest-ceiling transfer — investigations become
**deterministic, replayable typed programs** (§7.2), attacking DAB's 85% plan/implementation failure and
Aughor's known "strong-on-WHERE, weak-on-WHY" gap. Aughor already has the pieces: semops are the primitives,
the evidence ledger / Finding Dossier is a proto-artifact store, the LangGraph HITL interrupt is the
confirmation step, and `trusted_queries` is the save-and-replay sink.

---

## 3 · Aughor's current state — the seams these ideas land on

| Concept | Aughor seam (file) | State |
|---|---|---|
| Semantic operators | `aughor/semops/operators.py` (`apply_step`, filter/extract/top_k/aggregate) | live; single-call fail-open, **now guarded on extract** |
| Cross-source SQL | `aughor/connectors/federated.py` (`FederatedConnection`) | thin: DuckDB `ATTACH`/Arrow, `{ns}__{table}` views, `Capability.FEDERATION`-gated; no entity resolution |
| Typed intent IR | `aughor/semantic/compiler.py` (`QueryIntent`) | typed symbolic query → deterministic SQL |
| Join value-domain guard | `aughor/sql/` (overlap probe) | single-DB; the right *shape* for key reconciliation |
| Evidence / artifacts | `aughor/kernel/ledger.py`, Finding Dossier | capture exists; not yet a planner-readable artifact store |
| Save-and-replay | `aughor/semantic/trusted_queries.py`, `closed_loop` | trusted SQL sink; not yet trusted *plans* |
| RBAC row policy | `aughor/rbac/policy.py` | route-level; not yet compiled into the WHERE |
| Provider roles | `aughor/llm/provider.py` (`fast` / `coder` / `reasoner`) | the cascade tiers a champion-validation cascade needs |

---

## 4 · Ranked recommendations (leverage × effort × risk)

| # | Recommendation | Source | DAB gap | Dimension | Leverage | Effort | Risk | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | **Guarded extraction** (validate + gleaning re-extract) | DocETL/Palimpzest | GAP-2 (47/54) | Correctness | High | S | Low | ✅ shipped |
| 2 | **Cross-source federated planner** (decompose→per-source→batched-foreach integrate + cross-source guards) | Hasura/DAB | GAP-1 (54/54) | Robustness/breadth | Very high | L | Med | ✅ **COMPLETE** — engine · API · self-heal · N-source planner · driver-selection · cap-lift · connection selection · `/ask` auto-federation |
| 3 | **Ill-formatted key reconciliation** (extend overlap probe: detect prefix/format skew, synthesize normalizer) | DocETL resolve / DAB | GAP-3 (26/54) | Correctness | High | M | Low | ✅ shipped |
| 4 | **Plan-as-program + artifacts** (deterministic replayable investigation programs) | PromptQL | FM2+FM4 (85%) | Correctness/maintainability | Very high | XL | High | ◑ **Stage 2–3 shipped** — IR · validator · deterministic executor · named-artifact ledger mirror · LLM planner · flag-gated API; graph-wiring / replay / HITL deferred |
| 5 | **Champion-model cost/quality cascade** on semops | Palimpzest/Abacus | GAP-2 | Performance/cost | Med | M | Low | ✅ shipped |
| 6 | **Connector-capability contract** (deterministic pushdown decisions) | Hasura NDC | GAP-1 enabler | Maintainability | Med | M | Low | proposed |
| 7 | **RBAC row-policy compiled into the WHERE** | Hasura perms | — | Security | Med | M | Low | proposed |

---

## 5 · Shipped this session — Guarded extraction (Recommendation 1)

Branch `2026-07-07-guarded-extraction`, commit `c07c445`.

**What:** `semops/operators.py::semantic_extract` gains `validate=` / `max_rounds=`. When on, it infers a
type (`year` / `date` / `email` / `number`) from each field's name+description, **deterministically validates**
every extracted value, and **re-extracts only the off-type cells** with targeted per-field feedback in a
bounded gleaning loop. Off-type residuals are **surfaced in the operator notes and kept, never dropped or
blanked** (the never-silently-lose-data contract holds); empty (absent) values are always valid, so the guard
never pressures the model into inventing data.

**Why here and not on SQL:** this is the one axis where every frontier model scores 0% (regex, no
validation), and it is unstructured text — the place where a deterministic guard is *complementary* to
Aughor's thesis rather than the LLM-judge scaffolding the thesis warns against.

**Discipline:** flag `semops.guarded_extract` / `AUGHOR_GUARDED_EXTRACT`, default off = byte-identical; wired
into both live callers (`routers/query.py::query_semantic`, `agent/investigate.py` ADA semantic step); 12
hermetic tests (validators, type inference, re-extract, bounded rounds, empty-is-valid, untyped-skip,
`apply_step` passthrough). **Full suite 2690 passed** (from 2663), ruff 0.

**Follow-ons for this operator (small, when the accuracy track is resumed):** explicit per-field type in the
field spec (currently inferred from the description); code-synthesis of a deterministic parser the champion
validates (Palimpzest); a `validate`/`max_rounds` surface on the Query Builder "semantic step" UI.

---

## 6 · Recommended sequence

1. **(done)** Guarded extraction — proves the pattern on the wedge axis.
2. **Ill-formatted key reconciliation (Rec 3)** — ✅ **SHIPPED** (`aughor/sql/join_guard.py`,
   flag `join.key_reconciliation` / `AUGHOR_JOIN_KEY_RECONCILIATION`, default off). When a value-domain
   mismatch fires, `reconcile_join_keys` tries a fixed set of deterministic DuckDB normalizations
   (trim+lower, digits-only, strip-prefix, strip-leading-zeros, alnum-lower) on both keys, re-probes overlap,
   and — if one lifts overlap to ≥60% and ≥+30pp over raw — attaches a `KeyReconciliation` to the warning
   whose `to_prompt_text()` surfaces the exact normalized-join expression (`ON regexp_replace(...) = ...`).
   Distinguishes "same entity, different format" (`bid_123` vs `bref_123`) from genuinely disjoint entities;
   deterministic, monotonic, fail-open, no LLM. 6 tests (real-DuckDB skew fixture, off-by-default byte-identity,
   disjoint-negative, fail-open); suite 2695 green.
3. **Cross-source federated planner (Rec 2)** — the master gap; §7.1.
4. **Plan-as-program + artifacts (Rec 4)** — the deep bet; §7.2. ✅ **Stage 2–3 shipped** (engine · validator ·
   deterministic executor · named-artifact ledger mirror · LLM planner · flag-gated `/query/plan-run` +
   `/query/plan-answer`, default off). Graph-wiring, DATA-reads-artifact dataflow, trusted-plan replay, and
   HITL are the deferred follow-ons.
5. **Champion-model cascade (Rec 5)** and **capability contract (Rec 6)** as they unblock 3–4.

---

## 7 · Design sketches for the big bets

### 7.1 Cross-source federated planner (Rec 2) — staged

**Staging:** Stage 1 = the deterministic join engine (✅ shipped); Stage 2 = the flag-gated
`POST /query/cross-source-join` API (✅ shipped); Stage 2b = self-healing cross-source keys (✅ shipped);
Stage 3 = the LLM planner that decomposes a cross-source question into per-source sub-queries and picks the
join keys (✅ shipped).

**✅ Stage 3 — the LLM decompose-planner** (`aughor/agent/federated_planner.py`, flag `federation.planner`
/ `AUGHOR_FEDERATION_PLANNER`, default off → 404). `POST /query/federated-answer` takes a question + two
`conn_ids`; `answer_federated` grounds both schemas and makes **one** LLM call for a structured
`FederatedPlan` (a grounded sub-query per source + the join keys + join type), **validates it
deterministically** (`validate_plan`: each sub-query executes as a derived table and must output its declared
join key — a bad plan returns issues, never executes), then runs it through `cross_source_join` (the right
side is now a grounded sub-query via the engine's new `right_sql` path). Plan-then-execute (PromptQL),
deterministic-first: the LLM only produces the plan; guards validate it and the engine joins. The plan +
per-source SQL are returned for inspection. 6 tests (404-when-off, two-conn validation, end-to-end
plan→validate→execute across two DuckDB sources, validation-failure surfacing, `validate_plan` good/bad).
**✅ N-source + driver auto-selection.** The plan generalized from a fixed left/right pair to an ordered
list of `FederatedStep`s (`{source index, sql, join_key, left_key, how}`); `steps[0]` is the driver and each
later step joins its source onto the assembled result on a key already present. `answer_federated` folds the
steps through the engine; `validate_plan` tracks the assembled columns so a `left_key` that isn't yet present
is caught before execution. Because the planner chooses the step order, it also **picks which source drives
(driver auto-selection)**. `/query/federated-answer` now accepts ≥2 `conn_ids`. Tests include a real 3-source
chain (orders → customer region → region manager).

**✅ Answer-path — deterministic connection selection.** `aughor/agent/connection_selector.py`:
`select_connections(question, candidates)` reduces each candidate connection's schema to a bag of lexical
terms, matches the question's content terms against each, and runs a greedy **set-cover** to pick the
smallest set of connections that ground the question — **no LLM** (the LLM stays confined to the downstream
plan, per the deterministic-first thesis). Returns the chosen connections (driver = highest coverage), the
terms each grounded, and `multi_source`. `POST /query/auto-federated-answer` takes a question + a candidate
pool, selects the spanning subset, and answers over exactly those via the planner — so the caller no longer
names the connections. 9 tests (pure set-cover + tokenizer, schema-relevance selection dropping an irrelevant
source, end-to-end select-then-join over 3 registered sources).

**✅ `/ask` auto-federation (the last piece).** `_stream_ask` (`aughor/routers/investigations.py`) now, on a
fresh auto turn and behind `federation.planner` (default off = byte-identical), gathers the org-visible
connections (`_federation_candidates`, current first, capped), runs the deterministic selector off the event
loop, and — only when the question is genuinely `multi_source` — streams a federated answer (`_stream_federated`:
a `route` receipt naming the sources + the merged table via the same `columns`/`rows`/`headline`/`sql`/
`tables_used` events the quick path uses, so it renders in the existing surface). Fail-safe: any selection error
falls through to the normal single-connection path. 5 tests (candidate gathering incl. org-visibility filter +
cap; federated emission incl. the error path); the full suite stays green, proving the flag-off path is
byte-identical. **Rec 2 is complete end-to-end** — a plain chat question spanning two of your databases now
answers across them automatically.

**✅ Follow-up — per-source row cap lifted.** The connection layer caps `execute()` at 500 rows, which had
silently bounded every federated join (surfaced as `PARTIAL`). Added `execute_bounded(hyp, sql, max_rows)` to
the connection contract — the base default delegates to `execute` (so non-overriding connectors are
unchanged), and DuckDB/Postgres override it to actually return more rows (their `execute` bodies refactored
into a shared `_run`). The engine reads the driver (≤50k) and each keyed right fetch (≤100k) through it, so
joins scale past 500 rows; connectors without the override still cap and flag `PARTIAL`. 2 tests (700-row
right fetch + 600-row end-to-end driver); suite 2721 green.

**✅ Stage 2b — self-healing cross-source keys.** When a batched-foreach join's raw match rate is low and
`reconcile=True`, `batched_foreach_join` retries under a set of **paired** normalizations — a Python function
(applied to the materialized left keys) and the equivalent SQL expression (applied to the right key in the
batch query), so both sides normalize identically (`bid_123` and `bref_123` both → `123`). It adopts the
first transform that lifts the match rate to ≥60% and ≥+30pp over raw, else the raw result stands. Gated by
the same `join.key_reconciliation` flag (the cross-source twin of Rec 3), passed through by the endpoint. 3
tests (raw misses skewed keys, reconcile heals them, truly-disjoint keys don't false-reconcile).

**✅ Stage 2 — the reachable API.** `POST /query/cross-source-join` (`aughor/routers/query.py`, flag
`federation.remote_join` / `AUGHOR_FEDERATION_REMOTE_JOIN`, default off → 404) takes
`{left_conn_id, left_sql, left_key, right_conn_id, right_table, right_key, how, right_cols}`, runs the left
SQL through the standard safety gate, and calls `cross_source_join`. 3 integration tests (disabled-by-default
404, end-to-end join across two registered DuckDB sources, field validation). The federated planner (Stage 3)
will emit calls to this same engine.

**✅ Stage 1 — batched-foreach remote-join engine** (`aughor/connectors/remote_join.py`). The correct-by-
construction, N+1-free join across heterogeneous connections: `batched_foreach_join` executes the LEFT
sub-query, dedups the join keys, issues ONE keyed `WHERE right_key IN (...)` query per key-chunk to the
RIGHT connection, and hash-joins in memory (inner/left). Bounded (key-chunk 1000, right-rows 100k, out-rows
50k), injection-safe (escaped literals), and fail-safe (any error → the LEFT result unchanged, never a
raise). `cross_source_join(left_conn_id, left_sql, left_key, right_conn_id, right_table, right_key)` is the
by-id entry point the planner and API will call. 7 tests (two real in-memory DuckDB sources + a counting
wrapper proving N+1-avoidance and key-chunking). This complements — does not replace — `federated.py`'s
DuckDB-ATTACH path: ATTACH when data co-locates, batched-foreach for true cross-engine joins.

**Goal (remaining stages):** answer a question that spans two+ connections, correctly and N+1-free.

- **Planner:** decompose the question into per-source sub-queries (reuse the explore decompose machinery),
  each grounded against its own connection's schema/ontology, plus an **integration step** naming the join keys.
- **Execution:** keep DuckDB `ATTACH` (`federated.py`) as the fast path when sources co-locate; add a
  **batched-foreach** path for true cross-engine joins — run the left sub-query, dedup the join keys, issue
  **one keyed query per remote source** (a `WHERE key IN (…)` batch), re-assemble by key. This is Hasura's
  `variables`/RowSet mechanism expressed in SQL.
- **Guards, extended to cross-source:** the grain/fan-out guard must run on the *federated* join (a cross-source
  join can fan out just as a within-DB one can); the value-overlap guard becomes the trigger for Rec 3.
- **Measure:** stand up a local DAB-shaped fixture (Postgres + SQLite + DuckDB) and score pass@1 on a handful
  of multi-DB questions; the guards' firing rate is the deterministic signal.
- **Guardrails:** materialization caps already exist (`MATERIALIZE_CAP`); push aggregation into each source
  (DAB takeaway #2 — Python-heavy integration was ~20× costlier); MongoDB (non-SQL) is out of first scope.

### 7.2 Plan-as-program + artifacts (Rec 4)

**Goal:** make an investigation a deterministic, inspectable, replayable program — attacking the 85%
plan/implementation failure.

**✅ Stage 2–3 shipped — the engine, validator, API, and LLM planner** (`aughor/agent/program_planner.py`,
flag `plan.program` / `AUGHOR_PLAN_PROGRAM`, default off → the routes 404). Mirrors the federated planner
(§7.1) one-for-one, generalized from "per-source sub-queries folded by joins" to "DATA/SEMOP steps folded by
**named artifacts**". A typed `Program` is an ordered list of `ProgramStep`s — each a **DATA** op (a grounded
SELECT run through the shipped guard battery, `execute_guarded`) or a **SEMOP** (`filter`/`extract`/`top_k`/
`aggregate` over ONE prior artifact's text column, via `apply_step`). `validate_program` runs the deterministic
gate BEFORE anything executes (order-is-topology, so every `reads` must name an earlier `writes` — forward-refs
and cycles are rejected with no sort; DATA steps must ground/parse at `LIMIT 0`; a SEMOP must target a column
that exists in the read artifact where knowable). `run_program` executes step-by-step, threading each result
through an in-run `by_name` dict (the source of truth for reads) and **mirroring it to the ledger as a named,
versioned artifact** (`kind="program_step"`, `natural_key=artifact:{conn}:{inv}:{name}`) with `reads`/`program`
lineage edges — so `Ledger.receipt(...)` answers "how was this produced" and raw rows never re-flood the LLM
context. Fail-open + stop-on-error (a failing step records its artifact then returns, exactly like
`answer_federated`). `plan_program` makes **one** structured LLM call for the typed program; `answer_program`
is the full `plan → gate (every DATA sql through `gate_user_sql`) → validate → run` shape (a planning failure
is an answer, not a 500). API: `POST /query/plan-run` (hand-authored program, no LLM) + `POST /query/plan-answer`
(plan+run from NL), both 404 when off, returning `{columns, rows, …, program, artifacts, warnings, issues}`
(inspectable). 14 hermetic tests (off-by-default 404s, validator good/bad-read/forward-ref/bad-column/bad-sql,
executor threads DATA→SEMOP→SEMOP, artifact written + read back via `receipt`, stop-on-failing-step,
`answer_program` plan→validate→run + planning-failure). **Full suite green.** *Live finding surfaced while
building:* the per-step guard battery **deterministically repaired** a wrong table name (`no_such_table` →
the nearest real table) — the exact "guards validate each step" behavior Rec 4 wants, observed for free.

**Deferred (sketched below, kept OUT of the first increment — respecting "not a big-bang change"):** graph-wiring
into a live investigate mode behind the flag (the current LangGraph loop stays the byte-identical fallback);
**DATA-step-reads-artifact** (register a prior artifact's rows as a temp view before a DATA step's SQL — the
highest-value next enhancement, unlocking true SQL-over-semop-output dataflow); trusted-plan replay via
`priors.py` (persist a validated `Program` as the compoundable unit); HITL confirmation via the existing
`interrupt_before` seam. In v1, `reads` is meaningful only for SEMOP steps — DATA ops run SQL against the live
connection, so realizable programs are one-or-more DATA ops each followed by SEMOP chains over their text residue.

- **Plan IR:** a typed list of steps, each either a **data op** (grounded SQL via the existing guard battery,
  or a search) or a **semantic primitive** (`classify`/`extract`/`summarize`/`filter` — the semops, already
  built). Steps read/write **named artifacts** rather than re-feeding rows into the LLM context.
- **Artifact store:** promote the evidence ledger / Finding Dossier into a per-thread, planner-readable
  artifact table (`kernel/ledger.py` is the seam). This is also what makes follow-ups and long investigations
  cheap to resume.
- **Executor:** deterministic runner over the IR; the LLM emits the plan once, the runner executes it. Guards
  validate *each step*, not just a final SQL string. HITL interrupt = the human-confirmation step.
- **Replay:** persist a validated plan into `trusted_queries` — a *trusted plan* (not just SQL) becomes the
  compoundable unit, pairing with `closed_loop` and the Ambiguity Ledger.
- **Risk (why it's XL/High):** this reshapes the agent runtime; must land flag-gated and mode-by-mode, default
  byte-identical, with the current graph as fallback. Do not attempt as one big-bang change.

### 7.3 / 7.4 Key reconciliation (Rec 3) and champion cascade (Rec 5)

- **Rec 3:** DocETL-resolve's *blocking then match*, but deterministic-first — value-overlap probe detects the
  near-miss, a small set of candidate transforms (strip `^[a-z]+_`, trim, upper/lower, zero-pad) are tried,
  the one that maximizes verified overlap on a sample is bound. LLM only as a last-resort tie-break.
- **Rec 5:** ✅ **SHIPPED** (`aughor/semops/operators.py`, flag `semops.champion_validate` /
  `AUGHOR_SEMOPS_CHAMPION_VALIDATE`, default off). `semantic_filter` runs the cheap `fast` tier, then (when
  on) re-judges an evenly-spread sample with the strong `coder` "champion"; if sample disagreement exceeds
  20% the whole batch is escalated to the champion, else the cheap tier is trusted — Palimpzest's
  reference-free (label-free) quality estimation applied to bound cost. Refactored the batch loop into a
  reusable `_filter_verdicts` helper; byte-identical when off. 3 tests (off-by-default, agreement-trusts-cheap,
  disagreement-escalates); suite 2698 green. *Follow-on:* the full LOTUS calibrated-threshold cascade with
  statistical (precision, recall, δ) guarantees — the strongest idea from the deeper research pass — is the
  principled successor; this ships the tractable estimator first.

---

## 8 · What NOT to do (respecting the proven findings and scope discipline)

- **Do not** wrap SQL generation in an LLM-judge plan-selection tournament (DocETL/Palimpzest do; Aughor's
  measured finding is that this *perturbs correct queries* on strong models — 4× confirmed, ±7–10 noise floor).
  Keep the LLM-validation loops on the **unstructured** surface only.
- **Do not** rebuild the removed Spider2 eval harness or probe_repair on faith (see the consolidation note);
  rebuild is sanctioned only when the campaign restarts with a dedicated endpoint.
- **Do not** add MongoDB/non-SQL federation, a full Pareto optimizer, or a plan DSL beyond what a step actually
  needs — every one of these earns its place against a measured gap, or it waits.
- **Do** keep the flag-gated, default-byte-identical, then-flip-via-ledger discipline for every increment.

---

## 9 · Correctness / security audit (parallel track)

A separate three-agent audit (SQL-safety & guards · API/security boundary · agent concurrency) ran alongside
this study. Its verified findings are tracked separately from the external-sources roadmap above and will be
folded into the reliability backlog; they are orthogonal to the capability recommendations here.

---

## 10 · Sources

- DocETL — paper https://arxiv.org/abs/2410.12189 · docs https://ucbepic.github.io/docetl/ · repo `github.com/ucbepic/docetl`
- Palimpzest — https://arxiv.org/abs/2405.14696 · CIDR 2025 `vldb.org/cidrdb/papers/2025/p12-liu.pdf` · Abacus https://arxiv.org/abs/2505.14661 · repo `github.com/mitdbg/palimpzest`
- Hasura DDN v3 — repo `github.com/hasura/graphql-engine` (`v3/`) · NDC spec `hasura.github.io/ndc-spec/`
- PromptQL — https://promptql.io/about · blog `promptql.io/blog/how-promptql-achieves-100-accuracy-for-ai-on-enterprise-data` · Program API `promptql.io/blog/introducing-promptql-program-api-dynamic-integrations-made-simple`
- DataAgentBench — https://arxiv.org/abs/2603.20576 · repo `github.com/ucbepic/DataAgentBench`
