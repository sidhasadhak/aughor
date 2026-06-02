# Deep Study — NL2SQL Lean-Deterministic Advisory vs. Aughor As-Built

*Analysis deliverable. No code changed. Every "what Aughor does today" claim below is
grounded in a specific file/line read during this study, so the advisory can be judged
against the real system rather than an imagined one.*

Source advisory: `CONCEPT_NL2SQL_LEAN_DETERMINISTIC.md` (529 lines)

---

## 1. What the advisory actually proposes

The advisory's thesis in one sentence: **stop asking an LLM to be the analyst; use it only
as a linguist, and let a deterministic compiler turn parsed intent into SQL using the
ontology as the symbol table.**

Concretely it proposes a 5-stage replacement pipeline:

1. **Intent Parser** (LLM, narrow job) — NL → a typed `QueryIntent` IR. ~10 intent types:
   `scalar_lookup`, `metric_over_time`, `ranking`, `breakdown`, `comparison`, `trend`,
   `anomaly`, `correlation`, `causal_why`, `explore_relationship`.
2. **Query Intent IR** — a structured object (entity, metric, dimensions, filters, grain,
   time window, ordering, limit), not free text.
3. **Ontology-driven Synthesizer** — `synthesize_sql(intent, ontology, dialect)` builds SQL
   deterministically from ontology primitives (metric formulas, join paths, filters). No LLM.
4. **Evidence Aggregator** — deterministic roll-up of results into claims/verdicts
   (`VERDICT_TEMPLATES`).
5. **Optional Narrative Smoother** — LLM polishes the deterministic verdict into prose.

Plus a "baggage inventory" of 7 things to thrash (the SQL-writer prompt, the fix-loop, the
linter, the inspector, schema-as-text, per-intent LLM calls, checkpoint overhead) on the
argument that a deterministic compiler makes them unnecessary.

**The single strongest claim** (section 8, "philosophy"): *"The ontology already exists as a
symbolic graph but is not used to generate SQL — it is wasted."*

---

## 2. Juxtaposition — claim by claim, against the real code

### 2.1 "The LLM writes SQL freehand from schema-as-text" — **TRUE, and this is the core gap**

Verified in two places:

- **Agentic/investigate path** (`aughor/agent/nodes.py:382-449`, `execute_planned_queries`):
  the planner (`plan_queries`, line 322) deliberately produces a `QueryPlanV2` with **no SQL**
  ("Do NOT write SQL" in its system prompt, line 362). Then `_gen_sql` (line 418) makes **one
  LLM call per query intent** via `WRITE_SQL_PROMPT`, passing `schema=_schema_ctx` (the
  schema-as-text) and a `dialect` string. Multiple intents are fanned out across a
  `ThreadPoolExecutor` (line 443-447).
- **Quick/chat path** (`aughor/routers/investigations.py:295-317`, `_stream_chat`): builds
  `CHAT_PROMPT` from `schema = db.get_schema()` (text) plus retrieved sections, then
  `get_provider("coder").complete(...)` returns `answer.sql`. SQL is, again, generated freehand.

So the advisory is **correct** that the default and dominant code path is *LLM-generates-SQL-
from-text*. There is exactly one structured exception (§2.3 below).

### 2.2 "The ontology is a rich symbolic graph that already exists" — **TRUE, and richer than the advisory assumes**

`aughor/ontology/models.py` already encodes nearly every primitive the proposed
`synthesize_sql()` would need:

| Advisory wants | Already in `OntologyGraph` |
|---|---|
| Metric → canonical SQL | `OntologyMetric.formula_sql` (+ `grain`, `unit`, `entity`, `tables`) |
| Join path between entities | `OntologyRelationship.join_sql` + `cardinality` + `join_confidence` |
| Parameterized operations | `OntologyAction.sql_template` + typed `ActionParameter` list |
| Typed properties (Palantir-style) | `EntityProperty` (`semantic_type`, `data_type`, `value_interpretation`, `unit`) + `ComputedProperty.formula_sql` |
| Reusable filtered cohorts | `ObjectSet.filter_sql`; entity-level `active_filter` |
| Fast lookup | `entity_to_tables`, `table_to_entity`, `relationship_index`, `entity_for_table()`, `actions_for_entity()` |

**Implication for the advisory:** its Phase 1 ("build the ontology IR / symbol table") is
~80% already done. The advisory under-credits this — it reads as if the symbol table must be
built from scratch. It does not. The missing piece is not the *graph*; it's a **compiler that
consumes the graph**.

### 2.3 "The ontology is not used to generate SQL at all" — **MOSTLY true, with one real exception**

There is exactly **one** place the ontology touches SQL generation today, and it is *opt-in
for the model, not deterministic*:

- `aughor/ontology/actions.py` + `nodes.py:399-454`: `build_actions_prompt_section()` lists
  `ACTION:id()` tokens in the SQL-writer prompt; the model **may choose** to emit
  `ACTION:foo()`, and `expand_actions()` substitutes `action.sql_template` before execution.

This is genuinely a deterministic-template mechanism — but it is **bolted onto the freehand
path as an option the LLM elects to use**, not the spine of synthesis. It only fires in the
investigate path (not Quick chat at all), only for operations an author pre-declared as
Actions, and only if the model decides to use the token. So the advisory's claim is *directionally
right* (the ontology is not the compiler) but should be corrected to: *"the ontology is used
for SQL only as optional, model-elected templates in one of two code paths."*

Two further parallel-formula stores deserve flagging because they complicate any "single
symbol table" story:

- **Metrics catalog** (`aughor/semantic/metrics.py`, `data/metrics.json`,
  `build_metrics_block()`): approved KPI SQL (MRR, CAC, …) injected as **text** into chat and
  fix prompts. This is a *second* source of canonical formulas, separate from
  `OntologyMetric.formula_sql`. A deterministic compiler would need these two reconciled or
  it will emit divergent SQL depending on path.
- `OntologyMetric.formula_sql` is currently consumed only **post-hoc** by
  `aughor/ontology/divergence.py` (`check_metric_consistency`, called in
  `nodes.py:731-743`) — i.e. to *detect* when the LLM's SQL diverged from the canonical
  formula, **after the fact**, never to *generate* the correct formula up front. This is the
  advisory's point in microcosm: we already have the canonical formula and we use it to grade
  the LLM instead of to replace it.

### 2.4 "The linter and inspector are baggage that a compiler makes unnecessary" — **PARTIALLY true; do not thrash them**

- `aughor/sql/lint.py`: deterministic, AST-based (sqlglot) guards — `RATIO_AVG`,
  `DIV_NO_NULLIF`, `NOT_IN_NULL`, `LIMIT_AS_TIME_FILTER`, `GROUP_BY_ORDINAL`. Wired pre-execution
  in chat (`investigations.py:318`) and used to trigger a `SqlWriter.fix`.
- `aughor/sql/inspect.py`: an LLM (narrator) semantic check — "does this SQL actually answer
  the question?" — non-blocking, runs post-execution.

The advisory's logic is "a compiler can't emit `AVG(a/b)` or an un-`NULLIF`'d divide, so the
linter dies." That's true **for the subset of queries the compiler can synthesize**. But:
  - The compiler will only cover the ~10 enumerated intent types. Anything outside that set
    *still falls back to freehand SQL* (the advisory concedes a fallback exists). The linter is
    the safety net for exactly that fallback — so it must survive.
  - `inspect.py` checks *intent-vs-result alignment* (wrong table, missing filter), which is a
    different failure class than lint's *syntactic anti-patterns*. A compiler that builds SQL
    from a correctly-parsed intent removes the *need* for inspect on the compiled path — but if
    the **intent parse** is wrong, nothing downstream catches it. So inspect's job migrates
    "up" to *intent validation*, it doesn't disappear.

**Verdict:** these aren't baggage; they're the floor under the fallback path and should be
reframed, not removed. The advisory over-reaches here.

### 2.5 "Per-intent LLM calls and the fix-loop are pure overhead" — **TRUE where the compiler covers the intent; otherwise still needed**

`execute_planned_queries` does N LLM SQL-gen calls + up to one fix retry each
(`nodes.py:418-539`). For a `scalar_lookup` or `metric_over_time` that the compiler can build
directly, this is indeed wasted latency and token cost — the advisory is right. But the
self-correction loop (`FIX_SQL_PROMPT`, classify_sql_error, KB fix patterns) is what makes the
*freehand fallback* survivable. Keep it for the fallback; skip it for the compiled path.

### 2.6 "Checkpoint overhead" — **TRUE but orthogonal**

`SqliteSaver` over `data/checkpoints.db` with `interrupt_before=["ada_synthesize"]`
(confirmed in `graph.py`). This is real overhead, but it exists to power HITL and resumability,
not SQL generation. It is independent of the NL2SQL redesign and should not be bundled into it.

### 2.7 "The graph is a rigid waterfall" — **FALSE / outdated**

The advisory implies a linear pipeline. The real investigate graph already has
**demand-driven short-circuits**: `route_after_baseline` / `route_after_decompose` /
`route_after_dimensional` can jump straight to `ada_synthesize`, and `replan` (`nodes.py:834`)
does adaptive routing (`test_next` / `deepen_current` / `promote_new` / `skip_to` /
`synthesize`). There are also fast-paths (`replan` returns immediately in direct mode,
line 849; `should_continue` ceilings, line 818). The redesign should *preserve* this
adaptivity, not assume it must be added.

### 2.8 "Schema-as-text is a liability" — **TRUE in spirit; already partially mitigated**

Schema is passed as text everywhere (`state["schema_context"]`, `db.get_schema()`). But note
the system already does **schema retrieval** (`retrieve_relevant_schema` in `nodes.py:337`) and
**profile-cache portraits** (`exploratory_scan` fast path, `nodes.py:130-162`) rather than
always dumping raw DDL. A compiler that reads the ontology graph directly would bypass
text-as-interface entirely for the compiled path — a genuine win — but the text channel
remains for the fallback and for the planner's reasoning.

---

## 3. Scorecard: how much of the advisory is already built

| Advisory component | Status in Aughor today | Gap to close |
|---|---|---|
| Symbol table (ontology graph) | **Built** (`ontology/models.py`) | None — richer than assumed |
| Deterministic templates | **Partially** (`ACTION:` expansion, opt-in, one path) | Make it the spine, not an option |
| Canonical metric formulas | **Built twice** (`OntologyMetric.formula_sql` + metrics.json) | Reconcile the two stores |
| Intent IR / Intent Parser | **Missing** | This is the real new work |
| Deterministic Synthesizer | **Missing** (formulas used only to *audit*, via `divergence.py`) | The keystone |
| Evidence Aggregator | **Partially** (Evidence Ledger `aughor/evidence/`, `tools/stats.py`, score_evidence) | Add deterministic verdict templating |
| Narrative Smoother | **Built** (narrator `synthesize_report`) | Reuse as-is |
| Deterministic guards | **Built** (`lint.py`, `inspect.py`, ambiguity, divergence, verify) | Reframe as fallback floor; don't thrash |
| Materialization / caching | **Built** (`db/matcache.py`, `kpi_daily`) | Wire compiler to prefer rollups |

**Bottom line:** the advisory describes a destination Aughor is ~60% of the way to, but
mis-locates the gap. The gap is **not** "build a symbol table and templates" — those exist.
The gap is the **two missing middle layers**: a typed **Intent IR + parser**, and a
**synthesizer that compiles IR against the ontology** instead of the LLM compiling text in its
head.

---

## 4. Possible improvements if the advisory is adopted

Ordered by leverage-to-risk. These are recommendations for *later* (per the user's "major
changes first"), not a work order.

### 4.1 Highest leverage — introduce the Intent IR as an internal contract (no behavior change yet)
`QueryPlanV2` already exists as a "what to measure, no SQL" object. **Tighten it into the
typed `QueryIntent` IR** (entity, metric-ref, dimensions, filters, grain, time-window,
order, limit, intent_type). This is low-risk because the planner already emits something
shaped like it; you'd be adding types and enums, not a new LLM stage. It immediately makes the
"deterministic synth vs freehand" decision a clean branch.

### 4.2 Build `synthesize_sql(intent, ontology, dialect)` as a *coverage-gated* path, not a replacement
Implement the compiler for the intent types it can do **provably correctly** first —
`scalar_lookup`, `metric_over_time`, `ranking`, `breakdown` — drawing `formula_sql`/`join_sql`
from the ontology. Route to it **only when** (a) the intent type is covered, (b) every
referenced metric/entity resolves in the ontology, and (c) the join path exists in
`relationship_index`. **Otherwise fall through to today's freehand path untouched.** This
captures most of the latency/cost/correctness win on the common cases while keeping the long
tail working. The advisory's all-or-nothing framing is the main thing to *not* adopt.

### 4.3 Reconcile the two formula stores before the compiler reads either
Pick one source of truth for canonical SQL — either promote `data/metrics.json` entries into
`OntologyMetric` or have the compiler read both with a defined precedence. Otherwise the
compiler and the chat-path metrics-block will disagree, reintroducing the very divergence
`divergence.py` exists to catch.

### 4.4 Flip `divergence.py` from auditor to source
Today `OntologyMetric.formula_sql` is used only to *grade* LLM SQL after the fact. The cheapest
correctness win available is to **inject the canonical formula into generation** (already done
loosely for the metrics catalog; do it for ontology metrics too) and eventually to *emit* it
directly from the compiler. The divergence check then becomes a regression guard on the
fallback path only.

### 4.5 Wire the compiler to prefer materialized rollups
`db/matcache.py` (TTL materialization) and `kpi_daily` already exist. A deterministic compiler
is the natural place to decide "this `metric_over_time` at daily grain can read `kpi_daily`
instead of scanning raw" — a read-optimization the freehand LLM can't reliably make. This is
where the advisory's "optimise how data gets read" claim becomes concrete and real.

### 4.6 Keep — and reposition — the guards
- `lint.py`: keep as the floor under the freehand fallback (unchanged).
- `inspect.py`: repurpose its question-vs-result logic toward **intent-parse validation**
  (did we parse the right entity/metric/filter?), which is where errors will now concentrate.
- `verify.py` numeric verifier and the Evidence Ledger: keep; they get *easier* because
  compiled SQL has traceable provenance back to the ontology metric.

### 4.7 Preserve adaptivity
Do not let "deterministic pipeline" regress the existing demand-driven ADA short-circuits and
`replan` routing (§2.7). The compiler should slot in at the *SQL-synthesis* seam
(`execute_planned_queries` / chat `final_sql`), leaving graph-level adaptivity intact.

---

## 5. Net assessment

**Adopt the spirit, reject the absolutism.** The advisory's central insight — *the ontology is
a compiler we're using as a grader* — is correct and well-supported by the code
(`divergence.py` literally uses canonical formulas only to audit). Its proposed architecture
(Intent IR → ontology synth → deterministic aggregation → optional narration) is the right
shape and aligns with how the system is already trending (`QueryPlanV2`, `ACTION:` templates,
metrics catalog, matcache, Evidence Ledger).

Where it errs: it (a) **underestimates existing substrate** — the symbol table, templates,
guards, stats, caching, and adaptive routing are largely built; (b) **overstates the baggage**
— lint/inspect/fix-loop are the survival kit for the unavoidable freehand fallback, not dead
weight; and (c) **frames it as replacement** when the correct rollout is a **coverage-gated
compiler that shadows then progressively supersedes** the freehand path, intent type by intent
type.

The single most valuable next step (when major changes are done) is **4.1 + 4.2**: formalize
the Intent IR and stand up a coverage-gated `synthesize_sql` for the four safest intent types,
reading formulas/joins straight from the ontology graph that already holds them.
