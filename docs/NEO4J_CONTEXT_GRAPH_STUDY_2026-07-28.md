# Neo4j Context-Graph Study — 2026-07-28

**Sources studied:**
[Hands on with context graphs and Neo4j](https://neo4j.com/blog/agentic-ai/hands-on-with-context-graphs-and-neo4j/) ·
[From recall to reasoning](https://medium.com/neo4j/from-recall-to-reasoning-how-context-graphs-upgrade-an-agents-brain-0d6f8506d73f) ·
[Context Graphs & Agentic Decisions](https://medium.com/neo4j/context-graphs-agentic-decisions-9a125f22f411) ·
[neo4j-labs/agent-memory](https://github.com/neo4j-labs/agent-memory) (SDK README, data model,
MCP surface, examples) · create-context-graph.dev scaffold.

**Companion docs:** plan of record
[`PLATFORM_PROGRAM_2026-07-26.md`](PLATFORM_PROGRAM_2026-07-26.md) (L done → G next).
Method follows [`FIVE_REPO_STUDY_2026-07-23.md`](FIVE_REPO_STUDY_2026-07-23.md).
Read with [`WAVE_L_ACTIVATION_ARC.md`](WAVE_L_ACTIVATION_ARC.md) §L2/§L3 — this study exists
because L2 left `graph.readback` unproven, and the question "is our memory graph built wrong?"
deserved an outside reference point.

---

## 0. Verdict up front

1. **Do not adopt the stack. Steal three ideas.** Neo4j-the-database solves scale and
   traversal problems our graphs (~28 nodes on a rich connection) will not have for years, at
   the price of a mandatory infrastructure dependency — or their hosted memory cloud (NAMS),
   which would ship customers' schema and findings to a third party. Their extraction-first
   philosophy (LLM/NER writes memory) directly contradicts the provenance discipline (J4)
   that makes our memory defensible. This is the aisuite decision again: **adopt shape, not
   dependency.**
2. **The blogs are concept marketing; the substance is an experimental labs SDK.** No schema,
   no Cypher, no benchmarks in any of the three articles — the one number cited (166% for
   GPT-4) is from a generic academic KG paper, not their product. `agent-memory` is 7 months
   old, 384 stars, explicitly Experimental/community-supported. **They ship the same
   read-back loop we refused to graduate, with no published evidence it helps.** Migrating
   would buy a prettier unproven feature.
3. **Three of their ideas are genuinely better than what we do, and all three are adoptable
   without their stack:** reasoning-trace retrieval as a distinct memory tier (T-1),
   a visualization surface for the graph (T-2), and consolidation/expiry for accumulated
   findings (T-3). Scoped in §3.
4. **The sharpest reframe for us:** L2 may have injected the *wrong memory*. Read-back
   injects conclusions ("finding: returns are high in Q3"); their reasoning tier retrieves
   *approaches* ("a question shaped like this was answered well by decomposing along
   channel"). We already capture all the raw material (receipts, session log, task history)
   and retrieve none of it. T-1 is therefore also the redesign of the L2 experiment.

---

## 1. What their offering actually is

| Layer | What it is | Status |
|---|---|---|
| Blog posts (3) | Concept framing: "context graph" = KG capturing decision traces — situation → rationale → action → outcome — vs. vector memory's "disconnected facts". One operational recipe (isolate a workflow → structure the trace → map relationships → query). | Marketing; no schema, code, or numbers |
| `neo4j-labs/agent-memory` | Python + TS SDK, three memory tiers: **short-term** (conversation), **long-term** (entity KG, POLE+O model, entity resolution/dedup), **reasoning** (traces + tool usage, "similar task retrieval", `:TOUCHED` audit edges from reasoning steps to entities). Multi-stage extraction (spaCy/GLiNER/LLM), vector+text search, buffered writes, consolidation primitives, eval harness, MCP server (6/16-tool profiles), 8 framework integrations. | Experimental, community-supported |
| NAMS | Hosted memory service — extraction runs server-side, zero infra. | The path they actually want adoption on |
| `create-context-graph` | Scaffold: FastAPI + Next.js + Neo4j + agent-memory, **three-panel UI with a live graph view**. | Demo scaffolding |

Honest credit: the SDK is well-shaped, the tier separation is right, and shipping an eval
harness shows they know memory claims need measuring. Honest debit: nothing in the offering
demonstrates the loop improves answers, and their own article concedes the unsolved problem —
*"a Context Graph requires mechanisms for scope, expiry, and review to unlearn outdated
information"* — which they also do not have.

## 2. Head-to-head with `aughor/ontology/context_graph*`

**Where Aughor is ahead — hold the line:**

| Ours | Theirs | Why ours is right for this product |
|---|---|---|
| Provenance REQUIRED on every node/edge; **no `llm_inferred` source exists** (J4) | Extraction-first: LLM/GLiNER writes entities into memory | Model-authored memory feeding answers about revenue is a self-reinforcing hallucination loop. For a chat companion, fine; for us, disqualifying. |
| Analytics-native kinds (`table`, `metric`, `glossary_term`, `finding`, `brief`); `joins_on` carries **measured** value-domain overlap | POLE+O (Person/Object/Location/Event/Org) generic entity model | Wrong shape for "which join is safe and what did we learn about returns". |
| Committed, diff-readable JSON artifact + C6 offline export pack | Database (self-hosted) or hosted cloud | Zero infra, version control, a teammate consumes it with no Aughor running. NAMS = customer schema/findings to a third party — non-starter. |
| Hybrid search with a deterministic lexical floor that never degrades | Vector+text search | Parity in shape; ours is honest about degradation. |
| E-plane measurement + refusal to graduate on noise (L2) | Eval harness exists; no published evidence | We know our read-back is unproven. They don't appear to know theirs is. |

**Where they are ahead — the three thefts:**

1. **Reasoning traces as a retrievable memory tier.** They store situation → rationale →
   action → outcome per task and retrieve *similar past tasks*. We write receipts, the E1
   session log, and task history — and retrieve none of it at plan time. Conclusions are
   read back (that was L2); approaches never are.
2. ~~**A visualization surface.**~~ **CORRECTED 2026-07-28 — we already have one.** The
   original claim here ("zero frontend components read our context graph") was **wrong**, and
   wrong in an embarrassing way: it came from grepping `web/src`, a directory that does not
   exist (the tree is `web/`), for the term "context graph", which the frontend calls the
   *connection* graph. `web/components/ConnectionGraphPanel.tsx` has rendered it since Wave
   C5 — mounted in `IntelligenceWorkspace` under a Graph tab, hitting the same `GET /graph`
   endpoint, as a three-level anti-hairball surface (domain cards → tables → table detail with
   measured join overlap, glossary terms and past findings) with the C3 staleness state shown
   as a chip. Screenshot-verified on the live app: "Knowledge Graph · Fresh", 18 tables,
   7 edges, 2 metrics, 3 terms, 5 domain cards with cross-domain join counts.
   **The lesson is the one this repo keeps re-learning: grep the tree you have, and search for
   the name the code uses, not the name the study uses.**
3. **Consolidation and expiry.** Named in their article as required, absent in both
   products. Ours is compounding: L1 made findings accumulate one per answer, bounded only
   by `_MAX_RECEIPT_FINDINGS=100` (newest-first eviction — the same window shape that
   silently narrowed the L5 corpus).

## 3. The three thefts, scoped

Slot: a short **Wave N** (memory-shape) after G1–G3 land, or interleaved — N1 is the direct
continuation of L2's open question and needs no G machinery. None of the three requires new
infrastructure. All three follow the wave discipline: flag-gated, byte-identical off,
deterministic where possible, measured before default-on.

### N1 — Reasoning-trace retrieval (the L2 redesign) · ~3–4 sessions

**Claim to test:** injecting *how a similar past question was successfully approached* helps
more than injecting *what was previously concluded* (L2 measured the latter: +0.02 vs a 0.18
band).

- **N1a — Trace projection (deterministic).** Project a compact `TraceCard` per completed
  answer from stores that already exist (receipt + task_history + E1 session log): question,
  route taken (mode/branch), tables touched, guard verdicts, outcome (pass/abstain/error),
  duration. **No LLM authorship — provenance stays J4-clean** (each card cites its receipt).
  New store keyed by connection, same `AUGHOR_STATE_DIR` family, hermetic by construction.
- **N1b — Similar-task retrieval.** Lexical floor + optional vector rank (reuse
  `context_graph_search`'s exact fusion shape) over TraceCards; top-2 injected as a
  `PAST APPROACHES` block via the same `build_corrections_section` seam, gated by a new flag
  `traces.readback` (default off).
- **N1c — Measure honestly with the L-wave tooling.** Inertness pre-check first
  (`scripts/flag_ab_grid.py` — refuse if <25% of the corpus gets a block); temperature
  pinned; corpus = repeat/follow-up/investigation-shaped questions (the 102-case suite is
  mostly one-shot lookups — expect to need a purpose-built ~30-case memory-sensitive suite,
  seeded from receipt history of *recurring* questions). Budget ≈ 1 flag-replicate-day per
  replicate. Graduation through the existing gate or the flag stays off — and if N1c shows
  nothing, **delete `graph.readback`'s injection path too** (two nulls on two memory-injection
  shapes = the idea, not the wiring).

**Gate:** a receipted graduation decision either way; zero LLM-authored memory introduced.

### ~~N2 — Context-graph visualization panel~~ — ALREADY BUILT (Wave C5); see §2 correction

**Do not build this.** `ConnectionGraphPanel.tsx` covers every item scoped below: the view API
(`GET /graph`), kind-aware rendering, the join guard's measured overlap, the freshness state as
a chip, and findings on the table detail. Verified live.

**What the verification DID find — and it is worth more than the panel would have been.** The
panel shows **0 Findings** on a connection with **793 answer receipts**, while
`load_investigation_findings("workspace")` returns projectable findings from those same
receipts. L1 built that projector and proved it on `samples`; it is not reaching the
`workspace` graph (committed under `schema_name="default"`, version 10, zero finding nodes).
So the graph a user actually looks at shows none of what Aughor has learned from 793 answers.
⏭️ **That is the real N2: not a panel, a wiring fix** — and it was invisible until somebody
looked at the picture, which is the study's underlying point about visualization, arriving by
a route nobody intended.

<details><summary>Original N2 scope (superseded)</summary>

**Claim:** the graph is a trust surface; invisible memory earns no trust. Also directly
requested: "visually present it as required."

- **N2a — API.** `GET /ontology/context-graph/{connection_id}` view endpoint returning the
  existing artifact (nodes/edges/provenance/freshness + version). Read-only; no new state.
- **N2b — Panel.** A web view (existing design language, `react-force-graph` or sigma.js —
  **not** NVL; it drags Neo4j branding/licensing for zero benefit at our node counts):
  kind-colored nodes, provenance + summary on hover, edge labels with the join-guard overlap
  number where present, **freshness state banner** (C3's `fresh|dirty|stale|unknown` — the
  export pack already treats staleness as load-bearing; the panel must too), version badge,
  click-through from a `finding` node to its receipt. Filter by kind; search box reusing the
  lexical rank.
- **N2c — Entry points.** From the connection page and from the answer receipt ("what
  grounded this") — the receipt already names node ids; make them links.

**Gate:** a screenshot-verified panel on a real connection's committed graph, rendering all
six node kinds, with freshness honestly displayed. No LLM, no new flags beyond a UI route
guard if convention requires one.
</details>

### N3 — Finding consolidation & expiry · ~2 sessions

**Claim:** an append-only memory becomes the "massive noisy diary" their article warns
about; ours already evicts *oldest-first at a cap*, which is worse than deliberate forgetting
(the L5 lesson: a newest-first window silently reshapes the corpus).

- **N3a — Dedup/supersede (deterministic).** Same-subject findings (same tables + same
  metric family, matched with the existing `dedup.py` machinery) collapse to the newest with
  a `supersedes` count on the survivor — the diary becomes a summary with provenance intact.
- **N3b — Expiry tied to source freshness, not wall-clock.** A finding grounded in a table
  whose source version (A3 probes) has materially advanced is marked `stale`, down-ranked in
  read-back, and surfaced in the graph panel (N2) as visibly aged. **Never silently deleted**
  — C1's supersede-not-delete rule; a stale finding is still evidence of what was once true.
- **N3c — Review queue (optional, small).** The panel lists stale/superseded findings with
  keep/retire actions — the human "review" mechanism their article names and neither product
  has. Retire = tombstone, not row deletion (the null-side-guard lesson: intent is the
  authority).

**Gate:** on a connection with ≥100 accumulated findings, the projected graph carries
meaningfully fewer, each surviving node citing what it superseded; zero findings silently
lost (count in = count out across survivors + tombstones + superseded).

## 4. What we are deliberately NOT taking

- **Neo4j/Cypher storage** — infra cost for scale we don't have; the JSON artifact + C6
  export is a distribution feature Cypher would destroy.
- **NAMS hosted memory** — customer schema/findings to a third-party cloud; disqualified.
- **Extraction-first entity memory (POLE+O)** — violates J4; our entities come from the
  schema and governed stores, which is the point.
- **Their MCP memory server** — interop is interesting later (post-S); today it's surface
  area without a consumer. Revisit when an external-agent story exists.
- **`:TOUCHED`-style audit edges** — we already have stronger: receipts + `grounded_in`
  with required provenance.

## 5. One-line summary

Their architecture flatters ours; their marketing is ahead of their evidence; their three
good ideas — retrieve approaches not just conclusions, show the memory, forget deliberately
— cost us a few sessions each and no new infrastructure.
