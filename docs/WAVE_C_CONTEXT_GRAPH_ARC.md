# Wave C — The connection knowledge graph: PR arc

Scoped 2026-07-25 from [`FIVE_REPO_STUDY_2026-07-23.md`](FIVE_REPO_STUDY_2026-07-23.md) §T3.1 and
[`PLATFORM_PROGRAM_2026-07-24.md`](PLATFORM_PROGRAM_2026-07-24.md) §2 + J4/J5/J6, on the context model
in [`CONTEXT_ENCODING_ARCHITECTURE.md`](CONTEXT_ENCODING_ARCHITECTURE.md). **Five parallel
code-mapping passes over the repo grounded every claim below in real signatures** — the eleven context
stores, the join-guard provenance, the Qdrant substrate, and the two plan-time assemblers.

---

## 0. What this is, and what it is not

**Not** a new graph built from scratch, and **not** a port of Understand-Anything's pipeline. UA's
orchestration is an 858-line SKILL.md the host model executes, and its docs are "littered with scars
of the host model not obeying it" (`FIVE_REPO_STUDY` §1.4). Two of its load-bearing pieces are also
fake: LLM-inferred edges carry hardcoded per-type weights *cosplaying* as confidence, and its semantic
search is BUILT-not-WIRED (`store.ts:540` runs the fuzzy engine under both toggles). Wave C exists
because Aughor is better-positioned on **exactly the two things UA fakes** — it has *measured* edge
confidence and a *live* vector path — and it must not throw that lead away by copying the fake.

### The two findings that reshaped the scope

**Finding 1 — the typed graph already exists.** `aughor/ontology/` is a typed nodes-plus-edges graph
per connection, not a metaphor: `OntologyGraph.entities` (`ontology/models.py:303`) are nodes,
`OntologyGraph.relationships` (`:304`) are edges, each relationship already carrying
`join_confidence ∈ {exact, inferred, verified}` and `value_overlap: float` (`:171`, `:176`). It is
keyed `{connection_id}:{schema_name}:{fingerprint}` (`ontology/store.py:39`), has a
version-controllable human-override layer (`data/ontology_overrides/{conn}/{schema}/{kind}/{id}.yaml`,
`overrides.py:122` — the dir currently untracked in `git status`), is built per connection
(`schema_annotators.py:171`) and is *already rendered into the answer path*
(`render_semantic_layer`, `investigations.py:1320`). `load_latest_ontology(connection_id)` calls
itself "THE shared authority point" (`store.py:198-201`). **Wave C extends this graph; it does not
invent a parallel one.** The one thing it is not: similarity-searchable — it is an exact-match JSON
cache looked up by fingerprint.

**Finding 2 — the "open loop" is a precise boundary, not a blanket.** Aughor does not fail to read
context back. It reads *most* of it back — as **N mutually-unaware blocks** assembled by two separate
functions (`routers/investigations.py::_stream_chat:1127` for quick `/ask`; `agent/nodes.py::plan_queries:534`
+ `execute_planned_queries:641` for deep ADA). What is **never** read back is one specific half. The
map:

| Context store | Captures | Keyed by | Read back at plan time? |
|---|---|---|---|
| Glossary (`semantic/glossary.py`) | table/column descriptions, grain | **table name (global)** | ✅ folded into schema (`schema.py:641`) |
| Metrics catalog (`semantic/metrics.py`) | governed KPI formulas | **metric name (global)** | ✅ `metrics_section` (`canonical.py:175`) |
| Ontology (`ontology/`) | entities + relationships (**the graph**) | `conn:schema:fp` | ✅ `render_semantic_layer` (`investigations.py:1320`) |
| Ontology overrides (`ontology/overrides.py`) | human overlay, override-wins | `conn:schema` | ✅ inside `load_latest_ontology` (`store.py:202`) |
| Ambiguity ledger (`semantic/ambiguity_ledger.py`) | resolved readings | `org\|conn\|facet` | ✅ priors + hard-bind (`priors.py:131`, `investigate.py:3133`) |
| Verdicts (`verify/verdicts.py`) | human accept/correct/reject + `corrected_sql` | `org, conn` | ✅ "PAST CORRECTIONS" (`priors.py:88`, flag `closed_loop`) |
| Trusted queries (`semantic/trusted_queries.py`) | verified SQL | `conn` | ✅ `build_trusted_block` (`:108`) — but **zero in-app writers** |
| Trusted programs (`semantic/trusted_programs.py`) | verified plans | `org, conn` | ✅ replay (`program_planner.py:399`) |
| Connection KB (`semantic/connection_kb.py`) | typed business entries (`join` kind incl.) | `conn` | ◐ quick path only; **vector path is dead** (see C2) |
| Exploration findings (`explorer/store.py`) | discovered insights | `conn` / `conn__schema` | ◐ *annotations* read back; full derivation not |
| **Evidence ledger** (`evidence/store.py`) | verifiable claims + `sql_source` + owner feedback | **`investigation_id`** | ❌ **write-only** — UI/API GET only |
| **Finding dossiers** (`explorer/dossier.py`) | full derivation of a finding | `conn, org` (versioned in `system.db`) | ❌ **write-only** — read only by revalidation |
| **Overview / TOUR** (`overview/`) | 7-lens interesting facts | ephemeral compute | ❌ **write-only** — drills rank only the *next* tour |
| **Briefs** (`knowledge/briefing.py`) | executive narrative | `conn:schema` (TTL 2h cache) | ◐ only the brief *on screen*, flag `ask.brief_context` |

The rule that falls out is clean: **the definitional / corrective artifacts are read back; the
evaluative / derivational artifacts are not.** Evidence claims (and their `validated/disputed`
feedback), dossiers, and the tour are write-only with respect to the answer path — a question about a
table Aughor already investigated last week inherits *nothing* from that investigation. That, exactly,
is the `finding` and `brief` half of Wave C's node set, and closing it is the product bet.

### So what Wave C actually is

**One committed, versioned, searchable graph per connection that every question passes through
first** — assembled by *promoting* the ontology, not replacing it:

1. **Extend** the graph to Wave C's node/edge type set — adding the two unread node types
   (`finding`, `brief`) and formalizing the three that exist only as sub-structures today
   (`glossary-term`, `metric`, `domain`).
2. **Commit** it as a version-controlled artifact (nothing per-connection is in git today — §C1).
3. **Make it searchable** (Qdrant; the one thing the ontology is not — §C2).
4. **Read it back as one prior** at the single choke point both paths already share (§C2).
5. **Keep it fresh** at cost proportional to the change (§C3).
6. **Render, teach, and distribute** it (§C4–C6).

### The honest ceilings, stated up front

- **Injecting context is necessary but not sufficient — the model frequently ignores it.**
  `CONTEXT_ENCODING_ARCHITECTURE.md` §5 records this being learned twice: a verified metric formula
  proven-injected, and the generated SQL byte-identical with and without it. So a graph slice added to
  a prompt is the *weakest* form of read-back. Where a graph node maps to a deterministic resolver
  (ambiguity-ledger hard-bind at `investigate.py:3133`; the metric compiler at `semantic/compiler.py`),
  C2 must **feed the resolver, not just the prompt.** The reliability ranking is fixed:
  *enforced substitution > template/compiler > injected hint.* A grep-the-graph step that only adds a
  prompt block is a demo of the mechanic, not the mechanic.
- **The graph is a per-connection, per-org artifact and the spine is not yet clean.** `connection_id`
  threads most stores, but **glossary and metrics are keyed by name, globally** (`glossary.py:198`
  openly flags "`orders` alone has five competing entries", `:184`), and `org_id` exists in only four
  stores (verdicts, trusted-programs, ambiguity-ledger, pack-deltas). A graph that unifies these must
  pick **`(org_id, connection_id, schema)` as its spine** and re-key or read-time-scope the two global
  outliers — or it will manufacture a cross-tenant / cross-connection bleed with a receipt attached.
- **This is not the trust flywheel.** Auto-promotion of validated findings into trusted queries, the
  decision dimension (insight→action→outcome), and the per-user dimension are the *enterprise reframe*
  ([[context-graph-closed-loop-gap]]) and are **explicitly out of Wave C** — sequenced into G/later.
  Wave C closes exactly one gap: **context read back.** It surfaces the `finding` node; it does not
  auto-act on it.

---

## 1. The graph — the type system (and where each piece already lives)

Six node types, five edge types. The discipline of **J4 — every edge carries real, measured
provenance or it does not exist** — is not aspirational here: the strongest edge already computes and
persists its confidence, and the weakest self-reported numbers are explicitly banned from use.

### Nodes

| Node | Already exists as | Home (file:line) | Keyed | Wave C work |
|---|---|---|---|---|
| `table` | `OntologyEntity` + glossary + profile cache | `ontology/models.py:85`, `glossary.py`, `profile_cache.py` | `conn:schema:fp` (ontology); **global** (glossary) | project as node; carry profile stats + past findings |
| `metric` | `MetricDefinition` + `OntologyMetric` | `metrics.py:39`, `ontology/models.py` | **metric name (global)** | re-key / read-time scope; node carries `owner, lineage[], status, version` |
| `glossary-term` | glossary entries | `glossary.py` | **table name (global)** | promote to first-class node; re-key to connection |
| `domain` | exploration domains / LLM grouping | `explorer/`, new | `conn` | LLM emits grouping (narrow emission only) |
| `finding` | exploration insights **+** evidence claims **+** dossiers | `explorer/store.py`, `evidence/store.py`, `explorer/dossier.py:121` | `conn` / **`investigation_id`** (evidence) | **unread today** — becomes a node; evidence needs conn→investigation resolve |
| `brief` | briefing narrative | `knowledge/briefing.py:31` | `conn:schema` (TTL cache) | **unread today** — becomes a node; persist beyond the 2h cache |

### Edges — each annotated with the provenance that already exists

| Edge | Meaning | Provenance (J4) | Status today |
|---|---|---|---|
| `joins_on` | table → table | **measured `value_overlap` ∈ [0,1]** — containment `matched/total` (`join_guard.py:144`) or HLL `inter/a` for >1M rows (`sketches.py:93`); persisted on `OntologyRelationship.value_overlap` (`models.py:176`); value-disjoint edges *dropped* (`builder.py:1019`) | **exists** — but prompt collapses it to `✓` on accepted joins; number only shown when *rejecting* (`join_guard.py:481`) |
| `defines` | glossary-term → metric | glossary text + `MetricDefinition.lineage[]` | partial (both stores exist) |
| `derived_from` | metric → columns | `MetricDefinition.tables/dimensions` + entity properties | exists as fields |
| `grounded_in` | finding → tables / SQL | `dossier.sql` + `dossier.grounding{grounded,checked,ungrounded}` (`dossier.py:121`); `EvidenceClaim.sql_source` (`models.py:28`) | exists, **unread** |
| `resolves` | ambiguity entry → term | `AmbiguityResolution.resolution_source ∈ {probe,user,verdict}` + `evidence` (`ambiguity_ledger.py`) | exists, read back |

**The measured-confidence ranking is fixed** (from the guard map), and it is the rule for what may
annotate an edge:

1. `value_overlap` — measured containment, already an edge attribute. **Strongest.**
2. orphan-based containment `(fk_distinct − orphan_count)/fk_distinct` (`join_guard.py:463`).
3. verdict `acceptance_rate` (`verdicts.py:147`) — externally-measured human calibration (node-level).
4. `VerificationManifest.earned_confidence` (`state.py:229`) — computed guard coverage (finding-level).

**Banned from edge provenance:** `EvidenceClaim.confidence` ("from scoring node", `models.py:31`) and
`pack_deltas.confidence` (default 0.5, `deltastore.py:76`) — both LLM-self-reported. An edge that
carried one of these would be UA's hardcoded weight wearing Aughor's badge.

**Builder = a real program** (the anti-pattern table is binding: no pipeline-as-prompt). It is
deterministic from schema + dbt + profiler + guard evidence, reusing the ontology builder
(`ontology/builder.py`), `join_guard`, `compute_join_map` (`tools/schema.py:76`), the glossary, the
metrics catalog, and the dossier/exploration stores. **The LLM is called only for narrow emissions**:
node summaries/tags, and domain grouping. Every LLM emission is a leaf, never an edge, never a number.

---

## PR-C1 — The graph artifact: promote the ontology, commit it, complete its provenance

> **Status: BUILT** (branch `2026-07-25-wave-c1-context-graph`, unpushed; 18 tests).
> `aughor/ontology/context_graph.py` (the `ContextGraph`/`GraphNode`/`GraphEdge`/`Provenance`
> models + the pure `project_graph` projection) · `context_graph_store.py` (the committed
> artifact) · `context_graph_build.py` (orchestration + the finding loader) · flag `graph.build`
> (default off). **Decision gate MET, proven live on `samples`:** 5 `table` + 3 `domain` + 2
> `metric` nodes and 7 edges; **every edge carries provenance, zero without it**; all 5 `joins_on`
> edges surface the *measured* `value_overlap` as a number (1.000, `join_confidence=verified`) —
> not the boolean the prompt path collapses it to; the committed artifact
> (`data/context_graph/default/samples/ecommerce.json`, git-trackable, `check-ignore` clean)
> carries that provenance in-file. The finding-node half (the write-only loop, now a node) is
> proven through the **real** stores by an integration test — a persisted exploration insight + a
> real Ledger dossier → a `finding` node sourced `dossier` with a `grounded_in` edge — because no
> connection in this environment has been explored (0 insights everywhere), so a synthetic-only
> proof would have been dishonest.
>
> Two things the live path taught, both carried forward:
> - **A real bug caught by suspecting wiring, not by a test.** The store's root was hard-coded to
>   `data/context_graph` — exactly the un-isolated `Path("data")` shape that destroyed real
>   findings twice (`aughor/db/paths.py`'s reason to exist). Fixed to `state_dir()/"context_graph"`,
>   which gives *both* properties for free: `AUGHOR_STATE_DIR`→temp under the suite (isolated), env
>   unset→`data/` in production (committable). The whole-tree `test_storage_vending` +
>   `test_platform_agent_boundary` + `test_kernel_contracts` ratchets (invisible to the local gate)
>   were run locally and are green.
> - **J4's measured number already existed; the work was not throwing it away.** `value_overlap`
>   was on the relationship object all along; the projection surfaces it, and `Provenance` is a
>   *required* field on every edge so an edge without evidence is not constructible — J4 by
>   construction, not by convention. The banned self-reported confidences
>   (`EvidenceClaim.confidence`, `pack_deltas.confidence`) are absent from the allowed
>   `ProvenanceSource` set, with a ratchet test pinning it.

**Why first.** Everything downstream (read-back, freshness, rendering, tour, distribution) is a
consumer of one artifact that does not exist yet: a *committed, org-scoped, Wave-C-typed* graph.
Today the ontology is an exact-match JSON **cache** (`data/ontology_cache.json`, LRU max 20,
`store.py:24`) with no `org_id` and no `finding`/`brief` nodes, and **nothing per-connection is
committed to git** (agents confirmed every `data/` store is gitignore-matched; the only version
history anywhere is the Ledger `finding` artifact's `version`/`superseded_by` in `system.db`).

**Scope**

1. **A graph projection over the ontology**, `aughor/ontology/graph.py` — a typed `ContextGraph`
   view that projects `OntologyGraph` **plus** the narrative stores into the six node / five edge
   types above. Reuse `OntologyEntity`/`OntologyRelationship` verbatim as the `table`/`joins_on`
   carriers; add `FindingNode` (from dossier + exploration insight + evidence claim) and `BriefNode`.
   The projection is pure and deterministic; it does not call the LLM.
2. **The committed artifact.** Persist the graph as a per-connection, version-controlled file beside
   the override tree — `data/context_graph/{org}/{conn}/{schema}.json` — following the
   `ontology/overrides.py` precedent (human-editable, override-wins, git-reviewable) and the Ledger's
   **supersede-not-delete** version model (`ledger.py:383`), *not* the LRU cache's last-write-wins.
   Reuse `KeyedJsonStore` (`util/json_store.py`) for the runtime index.
3. **Fix the spine.** The graph is keyed `(org_id, connection_id, schema)`. The two global outliers
   (glossary, metrics) are read-time-scoped to the connection during projection (the mechanism
   `build_metrics_block` already uses, `metrics.py:484`), so a node inherits the right owner. This is
   the one place the multi-tenant seam is closed for the graph's own purposes; the broader
   fail-closed-tenancy hardening stays Wave G.
4. **Complete the provenance (J4).** Every edge carries a `provenance` field naming its evidence and,
   where measured, its number. Surface `value_overlap` as a **number** on accepted `joins_on` edges —
   the data is on the object today and the prompt path throws it away on the positive side
   (`join_guard.py:481`). Value-disjoint edges continue to be dropped, not down-weighted.
5. **Pull the two unread node types in.** `finding` nodes from `explorer/dossier.py` (cleanest — conn+org
   keyed, already versioned) and `explorer/store.py` insights; `EvidenceClaim` findings via a
   conn→investigation resolve (`db.history.list_investigation_ids`, since the ledger is
   investigation-keyed). `brief` nodes from `briefing.py`, persisted past the 2h TTL as graph nodes.

**Flag** `graph.build` (default off; byte-identical when off — the projection writes its artifact but
nothing reads it until C2) · **Tests** ~30 · **Decision gate:** the builder emits a graph for a real
connection (fixture `samples`) in which **every edge carries a provenance field citing measured
evidence, zero edges exist without it**, the accepted `joins_on` edges show their `value_overlap`
number, and the graph contains `finding` nodes sourced from a prior investigation's dossier. If any
edge lands without provenance, the projection is wrong — not the gate.

---

## PR-C2 — Grep-the-graph-first: read the graph back as one prior (closes the loop)

**Why.** This is the product bet — "context finally read back" (`FIVE_REPO_STUDY` §T3.1). Today the
read-back that exists is N disjoint blocks; the read-back that matters (findings, dossiers, tour) does
not exist at all. And the ontology graph, the one artifact that *is* per-connection typed structure,
is not similarity-searchable — so you cannot ask it "which tables handle churn?".

**The single choke point is already identified and shared.** `aughor/verify/priors.py::retrieve_priors`
(`:142`) / `build_corrections_section` (`:183`) is documented as "read the captured feedback loop BACK
into the planner" (`priors.py:1-23`) and is **already called by both paths before SQL generation** —
the quick path at `investigations.py:1490` and the deep plan node at `nodes.py:578`. A connection-graph
slice injected here reaches both paths at one site. (The intended long-term unifier is
`agent/grounding.py`'s `_BLOCKS` registry + `build_grounding_context:223`, whose own docstring flags
folding the live paths onto it as a follow-up — note it, don't block on it.)

**Scope**

1. **Make the graph searchable (J4 — Qdrant on day one).** A new collection `aughor_context_graph`
   indexing node summaries/tags and edge descriptions, built on the **live** substrate:
   `semantic/vector_store.py` (768-dim nomic, `nodes.py:554` proves it live on the answer path) with
   the per-connection scope pattern copied verbatim from `semantic/retriever.py`
   (`scope_key` + `_scope_filter`, `:19-49`). Hybrid vector + lexical, mirroring `connection_kb`.
2. **Fix the dead vector path found in the map.** `connection_kb.py:176` imports
   `get_qdrant_client`/`VECTOR_SIZE` from `embedder.py` — **neither symbol exists**, so `_qdrant()`
   raises `ImportError`, swallowed by a broad `except`, silently degrading to a non-ranked
   `entries[:top_k]` fallback. Repoint it at `vector_store.py` (the working path) as part of standing
   up the graph index — same substrate, one fix.
3. **The grep-the-graph step.** In `retrieve_priors`: match graph nodes for the question (hybrid
   search) → pull the **1-hop subgraph** (which now includes `finding` nodes and `resolves` edges on
   the matched tables) → emit one `CONNECTION GRAPH` prior block, token-budgeted (§C3).
4. **Supply, don't just suggest** (the honest ceiling). Where a matched node maps to a deterministic
   resolver, feed the resolver: a `resolves` edge hard-binds through the ambiguity ledger's existing
   `_apply_resolved_metric_reading` path (`investigate.py:3133`); a `derived_from`/`metric` node routes
   through `semantic/compiler.py`. The prompt block is the fallback layer, not the mechanism.
5. **Cite it.** The trust receipt records which graph node ids grounded the plan (the receipt plumbing
   exists; this adds a `grounded_by_nodes` lineage edge), so the read-back is auditable, not asserted.

**Flag** `graph.readback` (default off) · **Tests** ~35 · **Decision gate (two halves, both required).**
(a) **It reads back what was unread:** a real `/ask` about a table that a prior investigation produced
a dossier for pulls that finding into the plan and the receipt cites its node id — reconstructing a
link that returns *nothing* today. (b) **It changes the answer, measurably** (`verify-features-actually-ran`,
`CONTEXT_ENCODING` §5): on a case where the graph holds a correcting `finding`/`resolves`, assert the
generated SQL differs in the intended way with the flag on vs off — not merely that the block was
injected. An override that no-ops looks exactly like "the variant didn't help."

---

## PR-C3 — Freshness + token-proportional refresh

**Why.** A graph that silently lags the schema is worse than none — it grounds answers in a world that
moved. And the read-back slice (C2) competes for the same context budget as everything else, with no
trimmer to keep it honest.

**What exists to build on.** The schema fingerprint is already the ontology cache key
(`schema_fingerprint`, md5 of sorted `{table}:{row_count}:{grain_col}`, `store.py:263`) — but note it
**includes `row_count`, so every data refresh mints a new key** (the reason overrides were
externalized). The context-budget module exists (`llm/context_budget.py`) but enforcement is
**warn-only** — `_warn_if_over_window` (`provider.py:1304`) never truncates, and the only real trimmer
(`schema_scan_char_limits`, `:49`) sizes the ADA intake, not the quick-path prepend stack.

**Scope**

1. **A change-classifier** (UA's mechanic, as a real decision matrix — `ontology/graph_freshness.py`):
   a structural fingerprint diff classifies a schema change as **SKIP** (cosmetic DDL, comments →
   no refresh) / **PARTIAL** (column adds → re-profile the touched tables only) / **FULL** (new
   tables/schema → re-cluster domains). Separate the *structural* fingerprint (tables/columns/types)
   from the *data* fingerprint (`row_count`) so a nightly load doesn't trigger a FULL rebuild.
2. **Typed staleness states** `fresh / dirty / stale / unknown` on the graph artifact, surfaced in the
   UI banner and — the part with teeth — **gating briefings** (a brief built on a stale graph says so).
3. **A real token-proportional trimmer for the injected slice.** The grep-the-graph block is trimmed
   to a budget *before* assembly (curation, like every other block), not left to the warn-only
   provider check. Node inclusion is ranked by search score × edge provenance strength.
4. **J5 seam:** the staleness vocabulary and the change-classifier shape are written to be *lifted* by
   Wave V (one vocabulary for graph, briefs, profiles, exploration caches). C owns the first
   implementation; V generalizes it. Do not invent a second freshness dialect in V.

**Flag** `graph.freshness` (default off) · **Tests** ~25 · **Decision gate:** a cosmetic DDL change
(rename in a comment) classifies **SKIP** and costs zero refresh; a single column-add classifies
**PARTIAL** and re-profiles only its table; a nightly data reload (row counts change, structure
identical) does **not** trigger a rebuild; and the injected graph slice respects its token budget on a
57-table workspace schema (the R3 stress fixture).

---

## PR-C4 — Anti-hairball rendering (the surface)

**Why.** A join graph over a real warehouse is a hairball at one zoom level; UA's 75k stars are
substantially *this* — "the hairball is structurally impossible, not stylistically discouraged"
(`FIVE_REPO_STUDY` §1.4). This is also where Wave S gets its entity pages nearly free (J6).

**Scope** — three levels, copied in structure from UA, grounded in Aughor's data:

1. **Level 1 — domain cluster cards** with all cross-domain `joins_on` edges collapsed to one
   aggregated edge per pair with a count label.
2. **Level 2 — containers** grouped by schema, with **Louvain community detection over the join graph
   as the fallback** when schema grouping degenerates (FK graphs degenerate exactly like flat folder
   trees). Two-stage lazy layout (containers as opaque atoms first; children only on expand).
   Cross-schema references render as **portal nodes** (click → navigate), never edges to invisible
   nodes.
3. **Level 3 — table detail:** columns, profile stats (`profile_cache`), glossary links, and **the
   past findings touching this table** — which the `finding` nodes from C1 make **$0**, since the
   dossier system already holds them.
4. **Persona filter:** one line hides column/SQL-level nodes for an exec persona.

**Flag** `graph.surface` (default off; UI behind `Capability.EVAL_SUITE`-style gate — reuse the
pattern) · **Tests** ~15 (+ web gates: `gen:api`, `<Button>` ratchet, no `var(--rN)`-as-colour per
[[css-var-kind-gate]]) · **Decision gate:** the surface renders a real 57-table connection without a
hairball at any zoom level (every level aggregates edges), and a table-detail panel shows a real past
finding sourced from a dossier node. No screenshots of stubbed data.

---

## PR-C5 — The connection tour

**Why.** "Teach > impress." The 7-lens interesting-facts TOUR (`aughor/overview`, #154/#157) already
generates the *content* — but it is ephemeral compute (built per ask, `investigations.py:3509`, never
stored) and it is a **listicle**, not a curriculum. The graph turns it into an ordered reading path.

**Scope**

1. **Deterministic topology first** (`ontology/graph_tour.py`): fact tables = fan-in entry points;
   BFS from the entry point = natural dimension reading order; coupled clusters = star schemas; the
   metrics layer = capstone. Pure graph topology, no LLM.
2. **LLM narrates the ordered steps** (narrow emission): 5–15 steps mapped from BFS depth, each
   *required to connect to the previous step*. Reuse the `overview` lens content as the per-step
   substance; the graph supplies the order and the connective tissue.
3. **Materialize it** as tour narration on the graph artifact (the tour is ephemeral today; C1 gives
   it a home), refreshed under C3's staleness rules.

**Flag** `graph.tour` (default off) · **Tests** ~12 · **Decision gate:** the tour is an **ordered
curriculum** — every step after the first cites its connection to a prior step, and the order is the
graph's BFS order, not the notability ranking a listicle would use. A tour whose steps don't connect
fails the gate.

---

## PR-C6 — Distribution: the committed artifact + the skills pack

**Why.** This is the mechanic UA proved converts single users into teams: the graph is *just a
committed file*, so a teammate consumes it with **no LLM, no API key, no infrastructure** — generation
paid once, consumption free. It is also the cheapest possible "Aughor everywhere" — an agent in a dbt
repo answers "what does `net_revenue` mean and which tables feed it" from an exported pack with Aughor
**not running.**

**Scope**

1. **Export the graph** as a self-contained JSON (nodes + edges + provenance + summaries), the C1
   artifact plus its narration — the committed-artifact trick.
2. **An "Aughor skills pack":** markdown skills + an `install.sh` that symlinks them into agent
   platforms (no MCP server, mirroring UA's distribution). The grounded-Q&A protocol is the read-back
   one, offline: freshness-check the exported graph → grep node names/summaries/tags → pull the 1-hop
   subgraph → **answer only from that subgraph, citing tables**, warning when the graph lags.
3. **Every skill ships the freshness-gate preamble** — a trust receipt in prose (the typed staleness
   state travels with the export). **No coercive hook injection** (the anti-pattern table forbids UA's
   "You MUST … do not ask" auto-update hook — Aughor surfaces staleness and lets the user act).

**Flag** `graph.export` (default off) · **Tests** ~12 · **Decision gate:** an agent in a separate repo,
with Aughor not running, answers a definitional question ("what feeds `net_revenue`?") **correctly and
with table citations** from the exported pack alone, and refuses/warns when the pack's freshness state
is `stale`.

---

## The joints (how Wave C changes the waves around it)

- **J4 — C's edges carry real provenance or don't exist.** Satisfied by construction: `joins_on`
  carries the measured `value_overlap` the join guard already computes (`join_guard.py:144`), the
  self-reported confidences are banned from edges, value-disjoint edges are dropped, and graph search
  wires to the *live* Qdrant substrate on day one (C2.1) — Aughor delivers the "which tables handle
  churn?" query UA only promised.
- **J5 — V generalizes C's freshness, doesn't reinvent it.** C3 owns the first `fresh/dirty/stale/unknown`
  vocabulary and the change-classifier decision matrix; V lifts that one shape to briefs, profiles, and
  exploration caches. C3 is written to be lifted (a `graph_freshness` module, not inline logic).
- **J6 — S renders C.** C4's table-detail panel *is* the Foundry study's "zero-config entity page":
  node + dossier edges + past findings. In S it stops being a build and becomes a view.

## Sequencing

```
PR-C1 (graph artifact: promote + commit + provenance)
   │
   ├─→ PR-C2 (grep-the-graph-first read-back)  ← the product bet; needs the artifact + search
   │
   ├─→ PR-C3 (freshness + token-proportional refresh)  ← J5 seam for Wave V
   │
   ├─→ PR-C4 (anti-hairball surface)  ← J6 seam for Wave S
   │      │
   │      └─→ PR-C5 (connection tour)  ← reads the graph's topology + C4's rendering
   │
   └─→ PR-C6 (distribution: committed artifact + skills pack)
```

C1 is the keystone — every other PR consumes its artifact. C2 is the bet and should land second (it is
the reason the wave exists). C3/C4/C6 are independent consumers of C1 and can be built in any order;
C5 depends on C4. Arc total ≈ **130 tests**.

---

## Risks

1. **Building a parallel graph instead of promoting the ontology.** The single biggest way to waste
   this wave. `ontology/` already *is* the typed per-connection graph with measured edges and an
   override layer. C1 must extend it; a greenfield `ContextGraph` that re-derives entities/edges would
   duplicate the builder, diverge from the answer path's authority (`load_latest_ontology`), and pay
   for the provenance twice. Reuse is the design, not an optimization.
2. **Read-back that only decorates the prompt.** The honest ceiling: models ignore injected free-text
   (`CONTEXT_ENCODING` §5, learned twice). If C2 ships as a prompt block and nothing more, the decision
   gate's half (b) will fail — and it should. Feed the deterministic resolvers where the node maps to
   one.
3. **Pipeline-as-prompt orchestration.** The binding anti-pattern (UA's 858-line SKILL.md). The builder
   is a real program; the LLM is called only for summaries/tags/domain grouping — never for an edge,
   a number, or control flow. If a graph build step reads like a runbook the model executes, it is
   wrong.
4. **The multi-tenant seam.** Glossary and metrics are global-by-name; four stores have no `org_id`. A
   graph that unifies them without picking `(org_id, connection_id, schema)` as its spine bleeds across
   tenants/connections *with a receipt attached* — worse than the current honest ambiguity. C1.3 is not
   optional.
5. **Freshness over-claim.** The ontology fingerprint includes `row_count`, so a naive "is it fresh?"
   marks the graph stale every nightly load. C3 must split structural from data fingerprints or the
   staleness banner cries wolf until users ignore it.
6. **The dead vector path is a warning, not a footnote.** `connection_kb`'s swallowed `ImportError`
   (C2.2) is the exact shape to avoid: a search feature that silently degraded to a non-ranked fallback
   and shipped. C2's graph index must fail *loud* if embeddings can't be generated, never quietly serve
   `nodes[:k]`.

## Rules of engagement (inherited, non-negotiable)

Per [`PLATFORM_PROGRAM_2026-07-24.md`](PLATFORM_PROGRAM_2026-07-24.md) §6: default-off flags,
byte-identical when off; pre-registered decision gates per PR (above); **prove it on the live path
before saying done** (C2's half-(b) is this rule as a gate); snapshot `data/` before any full-suite run
and diff after; push once per branch, CI advisory, local gate = `uvx ruff@0.15.20 check .` + targeted
tests; strictly `:free` model bindings (C1/C5 LLM emissions and C2 embeddings budget requests
explicitly and run off-loop where batched); the anti-patterns table is binding (no pipeline-as-prompt,
no provenance-free edges, no coercive hook injection, no read-by-default); an unused param is worse
than a missing one, ratchet the call site not the function, a delete is durable only when the tombstone
is the authority.
