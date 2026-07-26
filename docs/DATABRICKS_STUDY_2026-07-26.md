# Databricks Ecosystem Study — 2026-07-26

**Sources studied:** [databrickslabs/dqx](https://github.com/databrickslabs/dqx) ·
[databrickslabs/ontobricks](https://github.com/databrickslabs/ontobricks) ·
[databrickslabs/impulse](https://github.com/databrickslabs/impulse) ·
[Genie One / Genie Ontology / Genie Agents announcement](https://www.databricks.com/blog/introducing-genie-one-genie-ontology-and-genie-agents)
(DAIS, June 16 2026; ontology in Public Preview) · Genie One product docs ·
[Lakehouse Federation docs](https://docs.databricks.com/aws/en/query-federation/) ·
[Lakeflow Connect docs](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/) ·
plus a landscape scan (Snowflake Cortex Analyst, OSI, dbt/MetricFlow, Cube, ThoughtSpot,
Wren, Vanna, Elementary, Palantir).

**Companion docs:** the plan of record is
[`PLATFORM_PROGRAM_2026-07-24.md`](PLATFORM_PROGRAM_2026-07-24.md) (A→R→E→C→V→G→S; G next).
This study feeds the roadmap that comes after it. Method follows
[`FIVE_REPO_STUDY_2026-07-23.md`](FIVE_REPO_STUDY_2026-07-23.md).
**Page-level deep dive:** [`GENIE_DOCS_TEARDOWN_2026-07-26.md`](GENIE_DOCS_TEARDOWN_2026-07-26.md)
— the full ~50-page Genie docs tree (Agents, One, Code, Omnigent, UC semantics, budgets)
torn down with exact limits, UI-pattern screenshots, API contracts, and the per-feature
imbibe map; its §6 refines the recommendations below (adds B-8 window measures, F-3
OpenAI-compatible façade, connection-as-code, and the docs-presentation playbook).

---

## 0. Verdict up front

1. **Genie One validates Aughor's architecture almost point for point** — ontology-grounded
   answers, deterministic trust machinery, in-product benchmarks, a feedback loop into the
   context layer, deep-research agent mode. Databricks just announced, at DAIS scale, the
   product shape Aughor has been building since the Foundry study. That is good news
   (the bet is confirmed) and a deadline (the moat is now a race).
2. **The difference is not design — it is default state.** Genie ships its loop *running*.
   Aughor has 87 flags and only 17 default-ON; every context-graph flag, `closed_loop`
   (corrections read-back), and the automations engine are OFF; the two committed graphs
   contain zero `finding`/`brief` nodes and zero `defines`/`grounded_in` edges; exactly one
   ontology override file exists. **The single highest-leverage move this study yields is
   not a new system — it is graduating the built ones.** (This is the platform-review
   theme "features stall at TESTED, not LEVERAGED," now with a competitor shipping the
   LEVERAGED version.)
3. **Aughor is genuinely ahead in four places** — provenance-required graph edges (Genie's
   ontology has *no* editor, versioning, approval, or rollback; "governed" means
   permission-filtered, not change-managed), the deterministic guard battery (~25
   query-shape evaluators nobody in the field matches), honest binding discipline
   (EXPLAIN-bind before injection, refusal-first), and the version-controlled override-wins
   ontology. These are the differentiators to *say out loud*, not rebuild.
4. **Aughor has three real gaps against the now-settled industry checklist** — no synonym
   primitive, glossary/metrics still global-by-name rather than per-connection, and no
   usage-derived authority/ranking signals. And one open-lane opportunity nobody has
   shipped: **data-quality caveats inline in AI answers** — Aughor already computes and
   threads caveats (`trust_caveat`), so it is closer to this than anyone.
5. **Do not build:** CDC/replication, OWL/RDF formalism, triple stores, 50-app connectors,
   or an ontorank that lets popularity into edge evidence. Stay live-query-first,
   deterministic-first, provenance-first.

---

## 1. What each source is (one paragraph each)

**DQX** — Databricks Labs data-quality framework for Spark. Declarative checks (YAML /
typed Python / table rows, all normalizing to one schema) with per-rule criticality
(`warn` annotates, `error` quarantines), row-level *and* dataset-level checks, results
attached to the rows themselves as `_errors`/`_warnings` structs carrying rule name,
message, run_id, and SHA-256 rule/ruleset fingerprints. Profiler → candidate rules →
human review; LLM generation as an additional *candidate* source, never auto-applied.
Ships an MCP server, Claude plugin, 5 agent skills, `llms.txt`.

**Ontobricks** — Databricks Labs web app for *formal* ontology engineering (OWL/R2RML/
SHACL) that materializes Unity Catalog tables into a knowledge graph. Philosophical
opposite of Genie's auto-learned ontology: human-curated, DRAFT→IN-REVIEW→PUBLISHED
lifecycle with sign-off quorum and append-only audit; typed relationship semantics
(cardinality, directionality, functional/transitive characteristics); SHACL validation of
declared semantics **against live data**, compiled to SQL; declared attribute exclusions
so "unmapped" ≠ "out of scope"; small stateful MCP surface. No metrics, no synonyms, no
NL2SQL — it stops where a BI semantic layer begins.

**Impulse** — Databricks Labs petabyte time-series *measurement* analytics (automotive/
IoT test data). Least adjacent, but clean patterns: a lazy typed expression DSL compiled
by pluggable solvers (intent separated from dialect/layout); grain-correct weighting baked
into aggregation *types* (duration-weighted histograms); detected events reified as
durable fact rows consumed by dashboards, ad-hoc queries, and ML alike; 10 composable
SKILL.md files with a router skill.

**Genie One / Genie Ontology / Genie Agents** — the productized version of this whole
space. One org-wide conversational surface routing question → curated agent → dashboards/
queries/metric views → external sources. The **Genie Ontology** is a continuously-learned
knowledge graph auto-extracted from tables, queries, dashboards, notebooks, pipelines, and
50+ connected apps, with **ontorank** (PageRank-style authority from source, author
authority, reliance frequency, certification proximity, freshness) resolving conflicting
definitions at answer time, permission-trimmed per user. **Genie Agents** (renamed
spaces): ≤30 tables, ≤100 instructions (example SQL, parameterized queries, UC
functions), ≤200 knowledge snippets (synonyms, entity value matching up to 120 cols ×
1,024 values, declared joins with cardinality, reusable measures/filters/fields).
**Trust machinery:** per-agent benchmarks (≤500 questions, result-set equivalence with
4-significant-digit numeric tolerance; LLM judge for report mode; run history),
Yes/Fix-it/Request-review feedback with a reviewer workflow, "edit SQL → add as
instruction," **knowledge mining** (rated interactions → suggested snippets/joins),
weekly digests, and verified-answer badges when an answer executes a trusted asset.
Marketing: 84.5% first-attempt accuracy vs 52.4% on an unfalsifiable 28-question
anonymized suite. **Documented weakness: no ontology editor, no versioning, no approval
or rollback — and authority ranking cannot verify correctness (popular-but-wrong stays
wrong).**

**Lakehouse Federation** — connections as governed credential-holding securables; foreign
catalogs inherit auth and mirror external DBs; lazy metadata sync with explicit REFRESH;
documented per-source pushdown contracts with AND-split partial pushdown; `EXPLAIN
FORMATTED` shows the exact SQL sent remotely; **result caching deliberately disabled on
federated queries** (stale answers refused rather than hidden) with materialized views as
the sanctioned freshness rung.

**Lakeflow Connect** — managed ingestion (Arcion-derived CDC + query-based cursor sync +
31 SaaS connectors). The durable idea is the **managed-ness / freshness ladder**: live
federation → materialized view on schedule → query-based high-water-mark sync → full CDC,
with explicit tradeoff language and non-destructive schema evolution (new columns flow,
deleted columns marked *inactive* — never dropped).

**Landscape** — the ontology checklist is settled industry-wide (entities/relationships +
metrics + synonyms + verified queries + instructions); the 2026 differentiators are
usage-derived authority and freshness/certification trust signals. Snowflake has the most
complete closed loop (verified queries → *generalized* into semantic concepts → candidate
questions *suggested* from usage). OSI v1.0 (Jan 2026, Apache 2.0, Snowflake-led,
Google+AWS in, **Databricks conspicuously absent**) is the interchange format to watch.
MCP won as the agent surface (donated to Linux Foundation; Snowflake/dbt/Cube/Elementary
all ship servers). **Nobody yet renders DQ signals inline in AI-analyst answers** —
Elementary's MCP server proves the plumbing; the last-mile UX is open.

---

## 2. Scorecard — Aughor vs the settled checklist

| Capability (industry checklist) | Genie One | Aughor today | Verdict |
|---|---|---|---|
| Entities + relationships w/ cardinality | ✅ declared joins | ✅ **measured** — `join_confidence`, `value_overlap` from the join guard ([models.py](../aughor/ontology/models.py)) | **Ahead** (measured beats declared) |
| Governed metric definitions | ✅ metric views (UC) | ✅ `OntologyMetric` + `data/metrics.json` — but **global-by-name, not per-connection** | Par, with a scoping bug |
| Synonyms / business vocabulary | ✅ first-class, per-agent + entity value matching | ❌ **no primitive** — only KB-tag derivation in `tools/schema_linker.py` | **Behind** |
| Certified / verified queries | ✅ trusted assets + verified badge | ✅ `TrustedQuery`/`TrustedProgram` (lexical retrieval) — no badge, no generalization step | Par machinery, behind on loop + surface |
| Instructions / business rules | ✅ ≤100/agent | ✅ ambiguity ledger (per-connection, source-ranked, compounding) + overrides | **Ahead in design** — ledger > flat instructions; near-zero adoption |
| Usage-derived authority / freshness ranking | ✅ ontorank (5 signals) | ❌ nothing (deliberate: provenance enum bans model confidence) | **Behind** — but the gap is *retrieval ranking*, not edge evidence |
| Ontology change management | ❌ **none** (no editor/versioning/rollback) | ✅ YAML overrides in git + Wave V lifecycle kernel (draft/publish/freeze/diff) | **Ahead** — say it loudly |
| In-product accuracy benchmarks | ✅ 500 q/agent, result-set equivalence, history | ✅ evals suites + add-as-test-case + E5 surface — not framed as a customer-visible accuracy number | Par machinery, behind on framing |
| Feedback → context loop | ✅ Fix-it → reviewer → add-as-instruction; knowledge mining | ✅ verdicts → corrections → priors — **default-OFF** (`closed_loop`) | Built, dormant |
| Deep-research agent mode | ✅ research plan, iterate, cited report, "Answer now" | ✅ /investigate + briefings + parallel exploration | Par or ahead |
| Clarifying questions / abstention | ◐ clarifying yes; abstention undocumented | ✅ ground-first resolution, abstain on DB-absent entities, refusal-first guards | **Ahead** |
| DQ signals in answers | ❌ (nobody ships this) | ◐ `trust_caveat` threads guard caveats — query-shaped only, no table-health rules | **Open lane, closest runner** |
| Agent-native packaging (MCP/skills) | ✅ MCP app + skills standard | ✅ MCP server (7 governed tools) + C6 skills pack | Par — extend, don't build |
| Permission-trimmed context | ✅ UC/source ACLs | ◐ RBAC exists; graph/ontology retrieval not permission-trimmed per user | Behind (Wave G territory) |

---

## 3. The central finding — dormancy is the competitive gap

The capability map ran the numbers: **87 registered flags, 17 default-ON**
(`aughor/kernel/flags.py`). Off by default: every `graph.*` flag (build, readback,
freshness, export), `closed_loop`, `automations.engine`, `automations.source_probes`,
`lifecycle.freeze`. The committed context graphs are 28-node and 11-node toys with zero
findings/briefs and zero `defines`/`grounded_in` edges — the exact node/edge types the
read-back protocol exists to serve. One ontology override file exists in the tree. The
ROADMAP caveat stands: **no background/explore path builds the graph**, so read-back only
fires for a connection someone manually materialized.

Genie One's entire pitch — "context without asking your teams to hand-curate it" — is a
pitch about *defaults*. Their loop runs on every workspace from day one. Aughor's
equivalent loop (capture → graph → read-back → correction → prior) is better engineered
at every stage and running at none of them. A fresh clone of Aughor behaves like a
text-to-SQL tool with excellent guards, not like the platform the docs describe.

**Recommendation zero, before any new construction from this study: an activation arc.**
Use the machinery already built for exactly this purpose — E4 grids to measure, E6
promotion gates to graduate — and flip, in order: (1) `graph.build` wired into
explore/investigate so graphs materialize as a side effect of use (closes the ROADMAP §0
caveat); (2) `graph.readback`; (3) `closed_loop`; (4) `automations.source_probes` +
`engine`. Each graduation cites its E6 receipt. This costs almost no new code and
converts five waves of built machinery into the running loop Genie is marketing.

---

## 4. Recommendations

Grouped into five themes. Each item: what → why (evidence) → where it lands.
Effort: S (<1 PR), M (1–2 PRs), L (an arc).

### Theme A — Activate the loop (the pre-wave; mostly graduation, not construction)

- **A-1 (L, but mostly measurement).** The activation arc of §3: background graph build on
  explore/investigate → readback → closed_loop → automations, each through the E6 gate.
- **A-2 (S).** When an investigation lands a finding or a brief publishes, **write the
  `finding`/`brief` node and its `grounded_in`/`derived_from` edges** into the context
  graph at that moment (the writers exist; they are not called on the live path). The
  graph's empty node types are the "captured but never read back" gap reincarnated.
- **A-3 (M).** Seed real curation on the flagship demo connection: ~20 glossary terms,
  ~10 synonyms (once A/B-1 exists), 3–5 trusted queries, 2–3 overrides — then export the
  C6 pack from it. Zero-adoption mechanisms rot; a worked example is documentation,
  test fixture, and demo at once.

### Theme B — Ontology parity + edge (the first new wave candidate; "Wave O")

- **B-1 Synonym primitive (M).** First-class per-connection synonym store: `subject_kind`
  (entity/column/metric/glossary term) + `subject_id` + `synonym` + `source`
  (human > mined > llm_candidate) + usage count. Consumed by the schema linker and
  ground-first resolution; managed like overrides (YAML, git, override-wins). This is the
  single clearest checklist gap. Genie's *entity value matching* (curated value lists per
  column for spelling/colloquialisms) is the natural second step — Aughor's profiler
  already collects low-cardinality value sets, so candidates are nearly free.
- **B-2 Re-key glossary + metrics per-connection (M).** The known debt
  (`context_graph.py:99` acknowledges it; the stores were never re-keyed). Same shape as
  the four glossary-scoping gaps of #198: "a store keyed without the dimension
  distinguishing its owners." Migration: global entries become `(connection=*)` defaults;
  connection-scoped entries shadow them (override-wins, consistent with the ontology).
- **B-3 Retrieval-rank with usage + recency — without corrupting provenance (M).**
  Adopt the *idea* of ontorank at the only layer where it is honest: **ordering retrieval
  candidates**, never as edge evidence. Signals Aughor already records: ambiguity-ledger
  `record_hit()` counts, drill records from helpful feedback, trusted-query usage,
  freshness states from the V kernel, and `source` rank (probe < user < verdict). A
  popular-but-wrong definition must remain overridable by one human YAML file — that is
  the governance story Genie cannot tell, and typedef's critique of ontorank
  ("authority cannot verify correctness") is the marketing line for it.
- **B-4 Verified-query generalization — Snowflake's loop, Aughor's guards (L).**
  Today trusted queries are retrieved by lexical overlap and injected whole. Add the
  *generalize* step: mine accepted verdicts + trusted queries for reusable fragments —
  a WHERE clause that keeps recurring becomes a candidate `ObjectSet.filter_sql`; a
  recurring expression becomes a candidate `ComputedProperty`/`OntologyMetric`; a
  recurring join becomes a join hint. Emit as **candidates into a review queue** (the A4
  resolve-once inbox is the natural home), EXPLAIN-bound before offer, never auto-applied
  (DQX's candidate discipline; Snowflake's capture→verify→generalize→suggest). This is
  the compounding-accuracy flywheel with Aughor's binding rigor.
- **B-5 Declared exclusions + coverage rollup (S).** Ontobricks: "unmapped" and
  "intentionally out of scope" are different states. Add an `excluded` marker to ontology
  bindings (tables/columns deliberately out of scope, with a note) and a per-connection
  coverage rollup (green/orange/red). Kills the silent-gap class in curation review.
- **B-6 Declared-semantics drift checks (M).** Ontobricks validates the ontology against
  live data continuously. Aughor verifies at build time (`grain_verified`, join
  verification) but never re-checks. Add a scheduled cheap probe re-validating declared
  cardinality / grain / `active_filter` reachability; a violated declaration flips the
  edge to `dirty` in V's vocabulary and surfaces as a caveat. (Rides A3 probes + the V
  kernel; also DQX-adjacent.)
- **B-7 OSI v1.0 import/export (S–M).** An adapter mapping OSI YAML (datasets, fields,
  metrics, dimensions, relationships, AI context) ↔ Aughor ontology. Cheap portability
  optics with real substance: customers with Snowflake/dbt semantic models can bring them;
  Databricks is absent from OSI, which makes "we speak the open standard" a positioning
  line against Genie specifically.

### Theme C — Table-health plane ("Wave Q"; DQX-shaped, answer-integrated)

Aughor's guards are **query-shaped** (is this SQL sound?); DQX is **data-shaped** (is this
table sound?). The landscape scan's sharpest finding: DQ-signals-inline-in-answers is an
open lane, and Aughor's caveat threading (`trust_caveat`, receipts, the scrubbed-ratio
mechanism) is the missing last mile everyone else lacks.

- **C-1 Rule catalog (M).** One declarative check schema (name, criticality warn|error,
  check fn + args, filter, for_each_column), stored per connection as YAML (same
  override/git discipline as the ontology), **SHA-256 fingerprints per rule and per
  ruleset** with metadata excluded from the hash (DQX's exact trick — annotation edits
  don't create versions). Checks compile to source-dialect SQL via the existing sqlglot
  path; start with the ~12 that matter for BI trust: not_null, unique/grain, FK
  integrity, in_list, range, freshness (is_data_fresh vs a declared SLA), row-count
  drift, accepted-values drift. All expressible as the profiler's SQL already.
- **C-2 Profile → candidates → review (M).** The profiler's outputs (null rates,
  cardinality, ranges, date density) already imply DQX's generation thresholds
  (null_ratio < 0.05 → not_null; distinct ratio < 1% → in_list; min/max → range). Emit
  candidates into the same review queue as B-4. Deterministic first; LLM proposals
  allowed but syntax-validated and never auto-applied.
- **C-3 Persisted results + health nodes (M).** Run results (per rule: pass/fail counts,
  run_id, ruleset fingerprint) persist per table; the context graph gets a `health`
  provenance on table nodes. Monitors (threshold/anomaly/drift/freshness) already
  compute half of this — unify their outputs into the same result store rather than
  building a second one (the Wave-E consolidation lesson: Aughor had five eval surfaces;
  don't create five quality surfaces).
- **C-4 The differentiator — caveats ride the answer (M).** At answer time, tables in the
  executed SQL are joined against latest health results; failures within severity/age
  thresholds render as inline caveats with provenance: *"`orders` failed its freshness
  check 2 days ago (expected daily loads; last row 2026-07-23)."* Warn annotates, error
  can gate publish (V3's publish path) — criticality-as-data, DQX's split, mapped onto
  Aughor's existing abstain-vs-caveat distinction. **Nobody ships this. Aughor can be
  first with ~2 PRs of glue on top of C-1..C-3.**

### Theme D — Trust surface (fold into Waves G and S, not a new wave)

- **D-1 Accuracy as a product number (M).** Reframe E5: a per-connection benchmark score
  ("87% on your 40 cases, trend ↗, last run Tue") on the connection page. Buyers now ask
  for this number — Genie and Snowflake trained them to. All machinery exists; this is
  framing + one surface.
- **D-2 Auto-suggested benchmark cases (S).** Mine session logs for high-frequency
  question shapes lacking eval coverage; suggest into the review queue (Genie does this;
  Snowflake does this; Aughor's session log E1 has the data).
- **D-3 Verified-answer badge (S).** When an answer executes a TrustedQuery/Program
  verbatim or via parameter binding, badge it in the UI and receipt. The retrieval
  already knows; the answer doesn't say it.
- **D-4 Fix-it flow (M).** Upgrade thumbs-down: capture *what was wrong* (wrong table /
  wrong filter / wrong metric / stale data), offer regenerate-with-note, route to
  `record_verdict` so corrections land in the priors loop rather than a dead ledger
  event. Genie's Yes/Fix-it/Request-review maps almost 1:1 onto verdicts — the UX is the
  missing piece, not the store.
- **D-5 Weekly workspace digest as a brief (S).** "Analyze Space Usage" is just a brief
  over the session log: volume, unanswered/abstained questions, feedback trend, top
  suggested curation actions (from B-4/C-2/D-2 queues). Dogfoods briefs on Aughor's own
  exhaust.
- **D-6 Permission-trimmed context retrieval (G-scoped).** Genie trims the ontology per
  user via source ACLs. When Wave G lands tags/clearances, graph read-back and
  trusted-query retrieval must respect them — noting it here so G's scope includes
  context retrieval, not just actions.

### Theme E — Connection plane (small items; mostly V/G riders)

- **E-1 Freshness-rung labeling (S).** Formalize the ladder Aughor already implicitly
  has: `live` (direct query) · `cached` (matcache, ≤1h TTL) · `mirror` (API sync age) ·
  `upload` (file import date) · `frozen` (V4). Stamp every answer/receipt with the rung
  + as-of. Federation's honest-cache lesson: staleness surfaced, never hidden. The V
  kernel provides the vocabulary; this is labeling, not architecture.
- **E-2 Widen `DialectCapabilities` (S–M).** Two negotiated features (QUALIFY, ILIKE) is
  thin. As new dialect incidents occur, encode them as capability entries (the R2
  pattern: encode the quirk, diff against our paths); pair with surfacing "the exact SQL
  that ran, where" in receipts — the EXPLAIN-as-universal-binder principle, shown to the
  user the way `EXPLAIN FORMATTED` shows remote SQL.
- **E-3 Non-destructive schema evolution (M).** On schema sync, a dropped column marks
  ontology properties/graph nodes `inactive` (with the sync run id) instead of deleting
  them — findings and briefs that cite them keep resolvable references, and V's
  change-classifier gets a cleaner input than "node vanished." Lakeflow's
  inactive-not-dropped rule, applied to metadata.
- **E-4 Scheduled materialization rung (M, later).** For recurring briefs/dashboards over
  slow sources: a scheduled materialize-refresh (matcache + A3 probe + V freshness =
  all the parts exist) as the sanctioned middle rung — Databricks' "materialized view
  over federation" without building CDC.

### Theme F — Agent-native distribution (S items, high optics)

- **F-1 Extend the MCP server** with the context tools the Ontobricks pattern suggests:
  `describe_entity` (BFS narrative from the graph), `search_graph`, `get_table_health`
  (C-3), `list_trusted_queries`. Small, stateful, scoped — not a graph dump.
- **F-2 `llms.txt` + `AGENTS.md`** for the repo and docs site (DQX ships both; AGENTS.md
  is now an AAIF standard read by 30+ tools). C6's skills pack already follows the
  skills standard — add a router skill (Impulse's pattern) if the pack grows.

---

## 5. What NOT to build (anti-recommendations, binding like §4 of the five-repo study)

1. **No CDC/replication engine.** Arcion cost Databricks ~$100M and runs gateways inside
   customer VPCs. Aughor's live-query-first posture *is* the counter-positioning: no
   copies, no staging, answers labeled with their freshness rung (E-1). If a customer
   needs replication, they bring their own and Aughor connects to the replica.
2. **No OWL/RDF/triple store.** Ontobricks proves the formalism is authoring-hostile and
   stops short of BI semantics. Aughor's YAML + git + typed Pydantic models is the right
   substrate; steal Ontobricks' *semantics* (B-5, B-6), not its stack.
3. **No popularity-as-evidence.** Ontorank ranks retrieval; it must never create or
   weight edges (J4 stands: an edge without deterministic evidence is not constructible).
   Usage signals order candidates (B-3); they do not assert truth.
4. **No SaaS-connector arms race.** 31 managed connectors is a platform company's game.
   Aughor's existing API mirrors (Salesforce/HubSpot/Stripe/GSheets) stay; growth there
   is demand-driven only.
5. **No second quality store.** C-3 unifies monitors + health results; a DQX-style
   standalone quality product alongside monitors would recreate the five-eval-surfaces
   mistake Wave E existed to fix.
6. **No LLM judge in the benchmark loop where result-set equality suffices.** Genie uses
   an LLM judge only for report-mode grading; Aughor's E4 lesson (deterministic
   comparators beat judges) stands. If report-grading ever needs a judge, it is a
   last resort with a floor-verified harness.

---

## 6. Suggested sequencing (input to the roadmap discussion)

The program's next planned waves are **G (governance) → S (surface)**. This study slots
around them rather than displacing them:

1. **Now / pre-G: Theme A (activation arc).** Cheapest, highest leverage, uses E4/E6 as
   designed, closes the ROADMAP §0 caveat. Also the honest prerequisite: several Theme
   B/C items feed queues and graphs that only matter if the loop runs.
2. **Wave G, as planned** — with D-6 (permission-trimmed context retrieval) explicitly
   added to its scope, and E-2's receipt surfacing riding along.
3. **Wave O (Theme B) after G** — ontology parity + edge. B-1/B-2 first (the checklist
   gaps), then B-3/B-4 (the flywheel), B-5/B-6/B-7 as the tail. This is the
   competitive-response wave and the strongest candidate for "next new wave."
4. **Wave Q (Theme C) after O** — the table-health plane, culminating in C-4
   (DQ-caveats-in-answers), the first-mover feature. Q benefits from O's review queue
   and re-keyed stores.
5. **Wave S, as planned** — absorbing Theme D (D-1..D-5 are S-flavored surfaces) and E-1.
6. **Theme F items are riders** — attach F-1/F-2 to whichever wave touches the MCP/docs
   surface first.

An alternate ordering — Q before O — is defensible if go-to-market wants the
differentiator (C-4) before parity (B-1/B-2); the dependency is soft (C-4 needs C-1..3,
not B). The study's own recommendation: **A → G(+D-6) → O → Q → S**, with D and E items
riding their named hosts.

---

## 7. The positioning sentence this study earns

> Genie One auto-learns a context layer you cannot inspect, version, or correct — and its
> own docs ship no editor, no approval, no rollback. Aughor's context layer is a typed,
> provenance-required graph in git: every edge carries measured evidence, every override
> is a reviewable file, every answer cites its sources, and data-quality caveats ride the
> answer itself. Auto-learned where that is honest, human-governed where it matters.
