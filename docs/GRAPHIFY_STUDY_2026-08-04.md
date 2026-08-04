# Graphify study — and the answer-provenance wave it points at (2026-08-04)

Queued 2026-08-02 in `ROADMAP_INTELLIGENCE_AND_CHAT_2026-08-01.md` §"Parked for study" with four
prepared questions. Method honored the pre-check rule (6-for-6): **the Graphify source was cloned
and read before designing anything** — every claim about it below cites its actual modules, not
its README. The Aughor side is grounded in a fresh full code-mapping pass over this tree at
`9fcde2e`, with the four load-bearing claims re-verified by hand.

**The one-line verdict:** same as Neo4j and Cognee — *adopt the shape, not the dependency* — but
Graphify is the first of the three where the shapes are genuinely new to us, because it is the
first system studied that closes the loop **deterministically**. Five shapes are worth taking.
Together they scope the wave the user asked for: an enterprise-DW knowledge graph where **every
answer is a walkable subgraph — each node checkable, each edge carrying its warrant.**

---

## 1. What Graphify actually is (measured from source)

~102k stars, Apache-2.0, Python. Pipeline of pure functions communicating through plain dicts and
NetworkX: `detect → extract → build_graph → cluster → analyze → report → export`, side effects
confined to `graphify-out/`. Code parsed locally via tree-sitter (~40 languages), **no LLM and no
vector store in the structural path**; the LLM appears only at leaves (doc/PDF/media description,
optional community labels). Retrieval is IDF-weighted lexical matching (exact=1000 / prefix=100 /
substring=1 bonuses) seeding a BFS depth-3 subgraph, served over MCP
(`query_graph/get_node/get_neighbors/shortest_path`) or CLI (`query/path/explain`).

Three details that mark serious engineering discipline:

- **Determinism is defended, not assumed** — Leiden runs with `random_seed=42`, `trials=1`, over a
  rebuilt graph with *sorted* node and edge insertion (`cluster.py`); the reflection artifact is
  "byte-stable for a given input and a given now" (`reflect.py` docstring).
- **Privacy posture is enforced in defaults** — the query log is opt-in OFF because "a default-on
  record of proprietary queries contradicts graphify's on-device posture" (`querylog.py`, #1797).
- **They publish effect sizes on an open harness** (`BENCHMARKS.md`, 2026-07-05): LOCOMO
  recall@10 0.497 (BM25 0.362, mem0 0.048), QA 45.3%, LongMemEval-S 76%, $0 LLM credits to build,
  competitors run as adapters under one model and a blind-validated judge (κ=0.81).
  ⚠️ This **updates the Cognee study's claim** that "nobody in this market publishes effect
  sizes" — Graphify now does, and credibly.

---

## 2. The four queued questions, answered from source

### Q1 — Edge provenance vs J4. **They have citation provenance, not measurement provenance.**

Every Graphify edge is
`{source, target, relation, confidence: EXTRACTED|INFERRED|AMBIGUOUS, source_file, source_location}`
(`ARCHITECTURE.md` schema, enforced by `validate.py`). The SQL extractor
(`extractors/sql.py`) walks tree-sitter DDL for `create_table/view/function/procedure/trigger` and
emits `references` (FK), `reads_from` (FROM/JOIN in view/proc bodies), `triggers`, `contains` —
each stamped with the file and line **where the claim is written**. There is **no data probing
anywhere in the codebase** — `pg_introspect.py` reconstructs DDL from `information_schema` and
feeds the same text extractor. No value-overlap equivalent exists.

So the answer to J4's question: structural adjacency *is* enough for them, because their substrate
(source code) is one where the declaration **is** the ground truth — an import statement cannot be
"stale" the way a declared FK can. In a warehouse the declaration and the data diverge (undeclared
joins are the common enterprise case; declared FKs rot), which is exactly why our `joins_on`
carries measured `value_overlap` and drops value-disjoint edges. **The two provenance kinds are
complementary, not competing** — see §5.2.

What they do better: the confidence class is **serialized into every context the agent sees**
(`[relation] [confidence] @location`, `serve.py:1571`) and audited as a first-class MCP resource
(`graphify://audit` — the EXTRACTED/INFERRED/AMBIGUOUS breakdown). Our measured number renders as
a percentage only inside the `graph.readback` block — which is OFF — so the prompt path every user
actually runs still collapses accepted joins to `✓` (`join_guard.py`, noted in the Wave C arc,
still true).

### Q2 — Leiden vs ontology-derived domains. **Keep ours as the view; take theirs as a check.**

Their clustering is purely topological (Leiden, resolution knob, oversized-community splitting,
LLM labels optional). Our level-1 anti-hairball view groups by ontology-derived domains — a
*semantic* grouping a CFO can read. Topological communities are not that; on a DW graph they would
regroup tables by join-degree, which is sometimes the ELT accident, not the business.

But `analyze.py`'s **`surprising_connections`** (cross-community edges ranked by a surprise score)
suggests the right use: run Leiden **as a disagreement detector**. Where the topological community
cuts across the declared domain — a `finance` table whose join neighborhood is entirely
`logistics` — the disagreement is itself a finding ("this table is filed under the wrong subject
area" / "this join is doing something nobody documented"). Deterministic (seeded), cheap, and it
produces review-queue items rather than a competing view.

### Q3 — Distribution vs C6. **C6 keeps the honesty edge; take their merge driver.**

Graphify's freshness is *by construction*: an mtime manifest, `--update` re-extracting only changed
files, post-commit/post-checkout hooks, and committed `graphify-out/` so a teammate checks out a
portable graph. There is **no traveled staleness state and no refusal of an empty pack** — C6's two
honesty properties (`export_pack` refuses an empty graph rather than shipping a pack that "answers
confidently from nothing", `context_graph_export.py:386`; the typed staleness state travels and the
offline skill leads with the lag caveat) have no equivalent. C6 stands.

Two mechanics are worth taking: (a) a **git merge driver that union-merges `graph.json`** so
parallel writers never produce conflict markers — directly relevant to our committed artifacts
(`data/context_graph/{org}/{conn}/{schema}.json`, three tracked today) the moment two branches
rebuild the same connection's graph; (b) their `benchmark.py` measures **corpus-tokens vs
subgraph-tokens per query** — the cheap, deterministic version of the measurement T3
(arXiv 2505.24478) says we never varied: which *serialization* of the graph slice earns its
context budget.

### Q4 — Is a codebase graph a real second substrate? **Not ours. The customer's.**

Graphing Aughor's own source would stall at BUILT (the 2026-07-12 review pattern; no consumer on
the answer path). But the question was aimed wrong: the codebase worth graphing is **the
customer's transform layer** — the dbt/ELT/SQL repo that *produces* the warehouse. Graphify's SQL
extractor already emits exactly the edges a warehouse cannot reveal about itself: `reads_from`
(view/proc lineage) and `references` (declared intent), each with file+line citation. Fused into
the connection graph (`dbt model --materializes--> table:X`), that is declaration-side lineage
joining our measurement-side evidence — and it answers "why does this table exist and what feeds
it" with a citation into the customer's own repo. This is the real second substrate, and it has a
consumer on day one: the provenance panel (§5.1) and impact analysis (§5.4).

---

## 3. The disagreement map (the payload)

Convergences first, briefly — deterministic projection over LLM extraction; explained edges over
similarity scores; no vector store as a position; determinism-hardened clustering; privacy-first
defaults. All three bets we made in Waves C/N, reached independently at 102k stars. The
disagreements:

| Axis | Graphify | Aughor today | Verdict |
|---|---|---|---|
| Edge warrant | citation (file:line where declared) | measurement (`value_overlap`; value-disjoint dropped) — but **only `joins_on` carries a number**; every other edge's `measured` is `None` | **Both.** Declaration + measurement on one edge beats either (§5.2) |
| Confidence surface | 3-class tag on *every* serialized edge + audit resource | number renders only in the OFF readback block; main path shows `✓` | **Theirs.** Adopt the always-visible warrant class (§5.2) |
| Answer artifact | answer = a graph node citing `source_nodes`, outcome-tagged | receipts/evidence/dossiers exist; `last_cited_nodes()` built to carry graph citations into the receipt — **zero consumers** | **Theirs — the wave.** (§5.1) |
| Learning loop | deterministic `reflect`: signed, time-decayed, corroboration-gated; **sidecar, never stamped into graph.json** | L2 readback measured null and stays OFF; verdicts/evidence captured, not aggregated | **Theirs, reframed** — trust annotation for *humans/UI*, not prompt injection (§5.3) |
| Verification agenda | `suggest_questions`: the graph emits its own doubts (AMBIGUOUS edges, INFERRED-heavy god nodes, isolates, low-cohesion communities) | freshness/drift exists (`/graph/drift` — no UI caller); no structural-doubt generator | **Theirs.** For a DW graph this writes the review queue (§5.5) |
| Impact analysis | `affected.py` BFS where each hit carries the **site** of the traversed edge (`via_location`), not the definition | `govern/lineage.py` walker (grounded_in+derived_from, depth 4) — built, tested, **no route, no caller** | **Theirs.** Wire ours, add sites (§5.4) |
| Clustering | Leiden = the primary view | ontology domains = the primary view | **Ours** for the view; theirs as a disagreement detector (Q2) |
| Freshness honesty | by construction (hooks, manifest) | typed staleness that travels; empty pack refused | **Ours** (Q3) |

---

## 4. Ground truth: what exists on `main` today (verified 2026-08-04)

The user's instinct that "some of it is built already" understates it — the substrate is merged,
and the flag endgame already hardwired most of it on:

- **The typed graph is real and J4-clean.** `aughor/ontology/context_graph.py`: six `NodeKind`s
  (`table/metric/glossary_term/domain/finding/brief`), five `EdgeKind`s
  (`joins_on/defines/derived_from/grounded_in/resolves`), `Provenance{source, measured, note}`
  **required on every node and edge** ("an edge without provenance is not constructible", `:91`);
  no `llm_inferred` source exists and model self-confidence is banned by name (`:16-20`).
  Committed artifacts live at `data/context_graph/{org}/{conn}/{schema}.json` — the workspace
  graph is at v12 with 255 glossary terms, 100 findings, 138 `grounded_in` edges.
- **Build is deterministic projection, always on.** `context_graph_build.py` gathers ontology +
  glossary + ambiguity resolutions + explorer findings + Ledger answer receipts + briefs; N3
  consolidation runs unconditionally inside it (supersede on same-question, `contested` carries
  alternatives inline, staleness = reachability). Every graph flag except one was hardwired and
  deleted on 2026-08-02 (`flags.py:37-40`); **`graph.readback` is the only survivor** —
  disposition EXPERIMENT, default OFF, standing on L2's measured null.
- **Rebuild triggers:** exploration completion, on-demand HTTP 404-fill, and two per-answer
  incremental writes (`note_finding` via `_write_answer_receipt`, `note_brief`). No scheduler.
- **Freshness has both axes** — structural fingerprints plus `content_drift()`
  (`graph_freshness.py:231`) and `GET /graph/drift` — but **no frontend calls the drift
  endpoint**; the panel's Fresh badge is the schema axis only, the exact blindness
  `content_drift` was written to prevent.
- **The read path is one choke point.** The graph reaches prompts through exactly one function
  (`feedback/priors.py::build_corrections_section` → `context_graph_readback.py`), used by both
  the quick `/ask` path and deep-analysis planning. The injected block is well-made: every line
  carries `[node_id]`/`[edge_id]`, joins render `overlap 98%`, governance trims with an
  out-of-band notice. But it is OFF, and in the grounding receipt it renders under the title
  **"Ambiguity-ledger priors (corrections)"** — a reader cannot tell the graph fired.
- **The answer-side capture is rich**: `_write_answer_receipt` (`routers/investigations.py:166`)
  writes lineage tuples (`source_sql`, `input` tables, `metric_used/drift/proposed`,
  `resolved_ambiguity`, guard edges) into the kernel Ledger; `build_public_receipt`
  (`trust/receipt.py:164`) projects them; `WhyThisNumber.tsx` renders the drawer (SQL, guards,
  trusted patterns, settled readings, input tables, confidence). The evidence ledger
  (`EvidenceClaim.sql_source`, keyed by investigation) and human verdicts
  (`feedback/verdicts.py`) capture the rest.
- **The frontend graph surface is real**: `ConnectionGraphPanel` (Map/Explore/Tour, entity page
  with per-join `overlap {pct}` and provenance chips) and `GraphCanvas` (d3-force, domain-seeded
  layout, selection→Ask per node kind, temporal replay of findings).

### 🔴 The one missing piece — and it is precisely the user's ask

**No per-answer trace connects an answer to the graph nodes that produced it.**
`context_graph_readback.py:26-51` sets a ContextVar of every cited node id per injection and
exposes `last_cited_nodes()` — **whose only consumers are its own tests**. Nothing in
`_write_answer_receipt`, the public receipt, or the frontend reads it. The `graph.readback` flag
description even claims "the block the context receipt shows names exactly what grounded the
plan" — for the *receipt*, that is aspirational, not implemented. Both ends of the feature exist;
the feature does not (the Wave H5 pattern, again). This is simultaneously the gap and the good
news: the spine of Wave P is a bridge, not a build.

### Defects found in passing (verified; chips filed)

1. **Demo pack ships `staleness="unknown"` always** — `demo/pack.py::_collect_graph` never passes
   staleness to `build_pack_payload` (default `"unknown"`), directly under a comment claiming
   "staleness travels WITH the data."
2. **~9 stale docstrings** still claim deleted flags gate the graph (`context_graph_build.py:9`,
   `context_graph_export.py:27,375`, `graph_freshness.py:123,149`, `investigations.py:308`,
   `briefing.py:704`, `cli.py:734` telling users to enable a deleted flag, `flags.py:432`).
3. **`_project_resolutions` mints ids prefixed `resolution:` under `kind="glossary_term"`**
   (`context_graph.py:465-477`), breaking the documented kind-prefixed id contract.

---

## 5. The five cherry-picks (= Wave P — Provenance) — **BUILT 2026-08-04**

> **All five shipped**, in the order below, on `claude/enterprise-dw-knowledge-graph-fff87a`:
> `c93ffbb` P2 · `07e13d5` P1 · `2378d5a` P5 · `3ed8d43` P4 · `953bc70` P3 · `e365de6`
> vocabulary ratchet · `965f435` the defect repair described at the end of this section.
> Full suite **5,734 passed / 0 failed**; ruff, the five frontend gates and every ratchet
> green. Nothing pushed — local commits only.
>
> **Two scopes moved when measured** (the pre-check rule, now seven for seven):
> - **P3 was rescoped by its own premise check.** It was to aggregate human verdicts and
>   evidence-ledger feedback; the real stores hold **zero verdicts and no evidence rows**
>   — neither file exists. Built as scoped it would have read "no signal" on every node
>   forever. The primary signal became citation corroboration, which exists on every real
>   connection, with the human channel wired to light up on the first verdict cast.
> - **P1 stopped depending on `graph.readback`.** A trace built only from cited nodes is
>   empty on every production answer, since the flag is an off-by-default experiment. It
>   resolves the tables the SQL demonstrably read instead, so every receipt ever written
>   already has a walk.
>
> **An adversarial review of the diff found 14 defects, four HIGH** — repaired in
> `965f435`, each now pinned by a test. Two were the exact traps the new modules'
> docstrings warn about, which is the case for running the review rather than trusting
> the docstring:
> 1. **The graph citations were structurally dead on the deep-analysis path.** A
>    `ContextVar.set()` inside `contextvars.copy_context().run()` never propagates back to
>    the submitter, and ADA builds its priors in exactly such a pool — so the receipt
>    always read `[]`, silently, because that is also what "the flag is off" looks like.
> 2. **P3's human channel could never fire** — a verdict is keyed by investigation, a
>    finding node by a random Ledger artifact uuid. Different namespaces; every verdict
>    scored nothing while the summary still claimed human signal.
> 3. **`warrant_for` returned the strongest class from its own except-branch** — any
>    non-numeric `measured` (including a bool, which floats to 1.0) reported as measured.
> 4. **The resolution projection defaulted a missing tier to `probe`**, which P2 reads as
>    a measurement: a harmless-looking `or "probe"` published a probe nobody ran.
>
> And one lesson worth carrying: **fixing an overclaim can overshoot into an underclaim.**
> Replacing the fabricated `overlap=1.0` with the `-1.0` couldn't-probe sentinel also
> dropped the *verification* for explorer-checked FKs that carry no counts, demoting a
> real check to "name match". The verification and the number are separate claims and now
> travel on separate fields.

### The five, as scoped

Ordered; each is a shape re-implemented on our stores, zero Graphify dependency. Constraints
honored throughout: J4 (no unmeasured number on an edge), the L2 verdict (no new prompt injection
without a grid), N1's rule (the platform never picks the winner), and the enterprise
re-sequencing from the closed-loop study (fail-closed tenancy before any auto-promotion).

### 5.1 P1 — The answer node: every answer becomes a walkable subgraph *(the wave's heart)*

Graphify's `save_query_result` files each Q&A as a doc whose `source_nodes` become graph
citations, with outcomes (`useful/dead_end/corrected`) riding along; `reflect` then aggregates
deterministically. Our version is a **bridge across parts that all exist**:

1. Consume `last_cited_nodes()` in `_write_answer_receipt` → new lineage tuples
   `("grounded_in_graph", "node:<id>", …)`. One seam, already the choke point for chat, deep,
   and monitor answers. (When `graph.readback` is off the list is empty — the trace then carries
   the blocks that *did* fire; see 3.)
2. Project the receipt into the graph as the existing `finding` node (already happens via
   `note_finding`) **plus** typed `used` edges to the cited nodes — provenance
   `source="answer_receipt"`, note naming the receipt id. Deterministic; no LLM writes anything.
3. Widen the trace beyond the graph block: the grounding assembly (`agent/grounding.py::_BLOCKS`)
   already enumerates schema slice, glossary, trusted queries, metrics, ambiguity bindings —
   record which entries of each block entered the prompt as trace rows with their store ids.
   The N mutually-unaware blocks stay mutually unaware; the *trace* is the one place they are
   named together.
4. Surface it: `build_public_receipt` gains a `grounding_graph` field;
   `WhyThisNumber.tsx` gains the walk — *these nine nodes made this answer* — each node linking
   into the graph panel (selection→Ask already exists for the reverse direction), each edge
   showing its warrant class (§5.2). Deep-analysis reports embed the same subgraph.

No prompt changes anywhere (L2-safe); no grid needed — this is an audit property, not an accuracy
claim. The exit question is a product one: can a user click from a number to the nodes that
produced it, and from any node to its evidence?

### 5.2 P2 — The warrant class, always visible

Derive a four-class warrant from fields that already exist (`Provenance.source` +
`measured`): **measured** (`join_guard` with a number) · **declared** (glossary, metrics catalog,
ontology, dbt once Q4's substrate lands — with file:line citation) · **human**
(`ambiguity_ledger` user/verdict resolutions, overrides) · **derived** (dossier/exploration/
receipt-sourced findings, carrying their `earned_confidence` at the node level). `contested`
stays a state, not a class (N3 already computes and carries it). Then port Graphify's two
surfaces: the per-edge warrant tag in *every* serialization — panel, pack, readback block, and
the join guard's main-path prompt line (stop collapsing accepted joins to `✓`; render the number
we paid to measure) — and a `graph://audit` counts endpoint (% of edges per warrant class per
connection) as the graph's public honesty scorecard in the panel, next to a **content-drift chip
finally wired to the existing `GET /graph/drift`**.

### 5.3 P3 — The trust sidecar (reflect, reframed for humans)

Graphify's `reflect.py` is the deterministic closed loop we kept refusing when it was framed as
prompt injection — reframed as **display-time annotation**: signed, time-decayed citation scores
(a fresh dead-end outweighs a months-old useful); promotion to "preferred" only on corroboration
by multiple distinct results ("one save can't mint a trusted lesson"); contested carries both
signals; and — the architecturally important part — **a sidecar file merged at display time,
never stamped into the structural graph**. Feed it from `feedback/verdicts.py` +
evidence-ledger `owner_feedback` + P1 answer outcomes. Output: per-node trust chips in the panel
and the answer trace ("cited by 14 accepted answers, 0 disputes" / "contested — two open
readings"). Not injected into prompts until a grid earns it through the E6 gate; L2's null
stands until then.

### 5.4 P4 — Impact analysis with sites

The walker already exists: `govern/lineage.py` (`grounded_in` + `derived_from`, depth 4,
reporting-only by design) — built, tested, **zero callers**. Wire it (route + panel node
inspector: "this table feeds 3 metrics, 7 findings, 2 briefs") and add Graphify's one good idea
from `affected.py`: each hit carries the **site** of the traversed edge — the SQL span, metric
definition, or (post-Q4) dbt model line that would break — not just the node name. Column-level
lineage is explicitly out of scope until a real consumer demands it (today's metric→table edges
are table-name matching, honestly labeled as such).

### 5.5 P5 — The graph writes its own review queue

Port `suggest_questions` to DW semantics, deterministic: unprobed-join hub tables → "verify
these joins" (one click to the existing overlap probe — doubt to measurement in one gesture);
isolated tables → "connected to nothing — dead or undocumented?"; Leiden-vs-domain disagreements
(Q2) → "filed under the wrong subject area?"; contested findings (N3) → "two readings await a
decision"; drift/staleness states → refresh prompts. Each item `{type, question, why, one-click
check}`, feeding the panel and the tour. This is the proactive half of "check each node": the
graph tells the user *which* nodes are worth checking before any question is asked.

**Sequencing.** P2 → P1 → P5 → P4 → P3. The Q4 substrate (customer dbt-repo ingestion; sqlglot
vs tree-sitter decided by testing both on one real dbt repo) lands any time after P2 and
enriches P1/P4. P3 last — it is the only piece with a governance surface (tenancy fail-closed
and scope-tiered promotion first; the sidecar never mutates shared truth on its own).

---

## 6. Explicitly not taken

- **Tree-sitter as a dependency** for warehouse introspection (we introspect live; their
  extractor matters only for the Q4 dbt-repo substrate, where sqlglot may suffice).
- **Leiden as the primary view**; LLM community labels; god-node rankings as product surface.
- **Their retrieval** (IDF-lexical BFS) — ours (RRF α-blend with a lexical floor that never
  degrades unranked) is measured and stays.
- **PreToolUse nudge hooks / `--strict` graph-first enforcement** — C6 deliberately refused
  coercive skill language; that stands.
- **Answer-quality claims for any of this** — Wave P is an auditability wave. If P3's sidecar
  ever wants into a prompt, it goes through the E6 gate like everything else.

---

## 7. What this study changes in standing docs

- `COGNEE_STUDY_2026-07-28.md`'s "nobody publishes effect sizes" → superseded; Graphify's
  `BENCHMARKS.md` is the market's first credible public harness. Our measured-and-refused L2/L3
  results remain the stronger *methodology* story (noise floors, refusal to graduate on noise).
- The T3 follow-up (arXiv 2505.24478, graph-slice serialization) gains a concrete cheap
  instrument: a `benchmark.py`-shaped corpus-vs-slice token measurement over our own packs.
- `ROADMAP_INTELLIGENCE_AND_CHAT_2026-08-01.md` §"Parked for study" → resolved by this doc;
  Wave P is the proposed successor arc, sequenced after the flag endgame per the standing plan.
