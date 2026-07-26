# Genie Docs Teardown — 2026-07-26

**Companion to [`DATABRICKS_STUDY_2026-07-26.md`](DATABRICKS_STUDY_2026-07-26.md)** (the ecosystem
study). That doc set the wave-level recommendations (A activation → G → O ontology parity →
Q table health → S). This doc is the page-level teardown of the **entire Genie documentation
tree** — every section including the collapsed ones — and the deep "imbibe map" into Aughor:
concrete features, exact limits, UI patterns (screenshots and GIFs inspected in a live browser),
API contracts, and the docs-presentation playbook itself.

**Scanned:** `/genie/` (family, budgets, monitor-cost, cost FAQ) · `/genie-one/` (index, chat,
external-sources, documents, mobile, mobile-admin, Slack app, homepage customization) ·
`/genie-agents/` (index, concepts, set-up, tune-quality, monitor, embed, best-practices,
volumes, troubleshooting, talk-to-genie, file-upload, conversation-api, agent-mode API) ·
`/genie-code/` (index, use, full-page, skills, instructions, MCP, tips, impact, tutorial,
notebooks assistant, DS agent) · `/omnigent/` (index, quickstart, identity-access) ·
`/uc-semantics/` (index, metric-views ×11 incl. the full YAML reference, agent-metadata) ·
`/ai-gateway/budgets`. ~50 pages, 4 parallel crawl agents, plus visual inspection of the key
product screenshots.

---

## 1. The Genie system model, one page

- **Three products, one substrate.** Genie One (consumer chat surface, its own URL +
  entitlement), Genie Agents (curated per-domain NL→SQL environments, formerly Spaces),
  Genie Code (developer agent in the workspace). All ground through Unity Catalog; the
  Ontology (preview) is the auto-learned snippet graph over everything; UC metric views +
  agent metadata are the hand-governed trusted core that feeds it.
- **Routing is deterministic and curated-first:** question → matching Genie Agent →
  dashboards/queries/metric views → external sources. Docs admit too many agents degrades
  routing.
- **The knowledge store is typed and budgeted:** table/column descriptions, synonyms,
  hidden columns, entity-matching value dictionaries, format assistance, join specs with
  declared cardinality, SQL expressions in three types (measure/filter/field), example
  SQL with typed parameters + per-example usage guidance, one text-instruction block.
  Hard caps force curation (see §3).
- **Trust machinery:** trusted assets (parameterized queries + *opaque* UC SQL functions)
  → verified badge; benchmarks ≤500/agent with deterministic result-set grading (Chat
  mode) or LLM-judge with author evaluation notes (Agent mode); accuracy history.
- **The loop:** feedback (Yes / Fix it / Request review) is **telemetry, never training**
  — improvement flows through humans + **knowledge mining** (rated interactions →
  typed snippet candidates in a review modal) and **Genie Code as the tuning engine**
  ("Analyze Space Usage" reads 7 days of usage and proposes context diffs; agent
  creation itself launches Genie Code to suggest context from existing queries).
- **Agent-as-code:** `serialized_space` v2 — the whole agent (tables, column configs,
  joins with cardinality encoded as `--rt=…--` SQL comments, snippets, benchmarks) is one
  strictly-validated JSON document; deployable via bundles.
- **Two API generations:** poll-based Conversation API (statuses, attachments, DIY
  backoff) and a new **OpenAI Responses-API-compatible** Agent API (SSE, `reasoning` /
  `function_call: execute_sql` items, `model: "genie-agent"`, structured metadata declared
  the stable contract, markdown explicitly unstable).
- **Monetization:** per-user free monthly allowance (150 DBUs) as an auditable
  `GENIE_FREE_USAGE` SKU; budgets on Unity AI Gateway with alert-vs-block thresholds;
  three cost surfaces with *documented* divergence; `budget_exceeded` is a typed API
  error.

## 2. The numbers that matter (consolidated limits table)

| Thing | Limit |
|---|---|
| Tables/views per agent | 30 (best practice: start ≤5) |
| Instructions per agent | 100 (example query = 1, SQL function = 1, whole text block = 1) |
| Knowledge-store snippets | 200 (descriptions + joins + SQL expressions share it) |
| Entity matching | 120 columns/agent × 1,024 values × ≤127 chars |
| Benchmarks | 500/agent; results visible 1 week; 4-significant-digit numeric grading |
| Conversations / messages | 10,000/agent · 10,000/conversation |
| Instruction files (Genie Code / One) | 20,000 chars hard cap |
| Synonyms (metric views) | ≤10 per field/measure, ≤255 chars each |
| File upload | 25/conversation; CSV/Excel <200 MB & <100 cols; PDF <20 MB/20 pages |
| Volumes (unstructured) | 10/agent · 500 files/volume · 10 MB/file · 5 retrieved per question |
| External connectors | 10 MB/file (Drive, SharePoint); per-user OAuth, never shared |
| Free allowance | 150 DBUs/user/month; service principals: none |
| Budgets | 4 shared thresholds + 20 per-user overrides per budget; 1,000/account |
| Agent API | 90-min stream; 1 concurrent response/conversation (409) |

The meta-lesson: **every page publishes its limits.** Genie's docs treat caps as product
design ("too many instructions reduce effectiveness") — restraint is doctrine, and the
limits table is the curriculum.

## 3. The imbibe map — Genie capability → Aughor

Verdicts: **ADOPT** (build it), **ADAPT** (build the honest version), **AHEAD** (Aughor
already stronger — say it louder), **SKIP** (deliberately not). Landing = wave from the
study doc (A = activation arc, O = ontology parity, Q = table health, G, S) unless noted.

### 3.1 Knowledge store & curation

| Genie | Aughor today | Verdict → landing |
|---|---|---|
| Per-column synonyms, descriptions, hidden columns | `column_config.py` exists; **no synonym primitive** | **ADOPT** → O (B-1) |
| **Entity matching**: curated distinct-value lists per string column (120×1,024×127); wrong literals ("California" vs "CA") fixed by it; rendered as editable dropdowns; blocked on RLS-masked tables | Profiler already collects low-cardinality value sets; ground-first resolution abstains on DB-absent entities | **ADOPT** → O (B-1 second step). Candidates nearly free from the profiler; note their RLS-leakage carve-out — value dictionaries must respect Aughor RLS too (`sql/rls.py`) |
| **Format assistance** (representative values, generated with *author* permissions — a documented leakage vector) | Profile annotations exist, per-connection | ADAPT → O; generate with a service context, never a user's |
| SQL expressions catalog: **Measure / Filter / Field** typed, each w/ name, SQL, synonyms, instructions ("Common SQL Expressions" UI) | `OntologyMetric` / `ObjectSet.filter_sql` / `ComputedProperty` — richer types, no unified surface | **AHEAD on model, ADOPT the surface** → S. One catalog page listing all three, typed chips, +Add |
| Joins with declared cardinality (many-to-one / one-to-many / one-to-one); UC FK auto-suggested; **no runtime validation** ("wrong promise silently corrupts measures") | `OntologyRelationship` with **measured** `value_overlap` + `join_confidence` | **AHEAD** — measured beats declared. B-6 drift checks close the loop they leave open. Marketing line lives here |
| Per-example-query **usage guidance** field; typed parameters (`:param` + type + comment) | `TrustedQuery`/`TrustedProgram` have retrieval + binding; no usage-guidance field | ADOPT (small) → O; add `usage_note` to trusted queries |
| **Opaque SQL functions** — "logic that should not be surfaced," Genie can't view/modify the body | Nothing equivalent | ADAPT → G (a trusted program flagged `sealed`: executed, never shown; pairs with clearances) |
| Curation budgets + instruction hierarchy doctrine (SQL expr > example SQL > text; start ≤5 tables) | No stated doctrine | **ADOPT the doctrine** → docs + review-queue ranking now, not a wave |

### 3.2 The loop (feedback → mining → review)

| Genie | Aughor today | Verdict → landing |
|---|---|---|
| **"Review Suggested Queries" at creation**: mines existing SQL against selected tables → accordion of candidates, each w/ editable question-style title, collapsed code, source link, Accept/Reject (screenshot studied) | Nothing at connection-create time | **ADOPT** → O (B-4 front door). Aughor's version mines the *query log / dbt / saved queries* of the connection at onboarding |
| **Knowledge-mining modal**: post-thumbs-up, typed candidates (JOIN / MEASURE / FILTER), each editable-name + "means" + SQL + pre-checked, "Accept 3 snippets" (screenshot studied) | Verdicts→corrections exists (default-OFF); no generalization, no modal | **ADOPT** → O (B-4). The A4 resolve-once inbox is the queue; this modal is the UI spec. EXPLAIN-bind every candidate before offering (Aughor's discipline on their UX) |
| Yes / **Fix it** / **Request review** + reviewer workflow + "Add as instruction" / "Add as benchmark" kebab on any answer | Thumbs + `record_verdict` store; `AddToEvalSuite` exists | ADOPT UX → S (D-4). Verdicts store already fits; the kebab actions are the missing 2 buttons |
| **Weekly digest** + **"Analyze Space Usage"** (agent reads 7 days of usage → issues + suggested context fixes, with citations) | Briefs machinery (A5) can host this | ADOPT → S (D-5), dogfooding briefs on session-log exhaust |
| "Feedback is telemetry, never training" — nothing auto-applies | E6 promotion gate: records evidence, never flips | **PARITY of philosophy** — publish it as a trust principle |

### 3.3 Benchmarks & evals

| Genie | Aughor today | Verdict → landing |
|---|---|---|
| 500 benchmarks/agent; deterministic grading (exact SQL / result-set / sort-insensitive / 4-sig-digit) | E-suite result-set equality, floors, robustness axis (E4b/c) | **AHEAD on methodology** (floors + perturbation don't exist in Genie) |
| "Generate SQL" ground-truth helper; **"Update ground truth"** button; per-question overrule of Good/Bad | Add-as-test-case captures executed SQL | ADOPT the two buttons → S (E5 surface polish) |
| Accuracy history as a visible product number | Runs exist; not framed per-connection | ADOPT → S (D-1) |
| LLM judge for report-mode w/ author "Evaluation notes" | Deliberately rejected (E4 lesson) | **SKIP** — deterministic comparators only; if report grading ever needed, floor-verified harness first |
| Benchmarks never feed context (eval/context separation) | Same separation in evals | PARITY — keep it |

### 3.4 Semantic model (UC metric views — the YAML spec)

| Genie/UC | Aughor today | Verdict → landing |
|---|---|---|
| `MEASURE()`-enforced grain-free measures; `SELECT *` banned; direct joins banned (CTE wrap) | Grain guards enforce at query-shape level (post-hoc) | ADAPT → O: expose registered metrics as **only invocable through the metric layer** in NL2SQL priors; guards already catch violations |
| **Window/semiadditive measures**: declarative `order`/`range` (current·cumulative·trailing·leading·all)/`semiadditive: first|last`/`offset` for period-over-period; stacked windows for YTD | `OntologyMetric` has formula_sql + grain; no window vocabulary | **ADOPT** → O (new item **B-8**). "YoY growth," "trailing 7d," "balance at month end" become *declared* measures instead of per-query LLM SQL — a large NL2SQL correctness lever that rides Aughor's existing guards |
| **Agent metadata per field/measure**: synonyms (≤10×255), display_name, typed `format` (currency/percentage/decimal-places/compact, date formats) | No format spec; standing item #189 (0.275985 vs 27.6%) open | **ADOPT** → O ties to S: the format block *is* the fix for #189 — presentation semantics declared in the ontology, rendered everywhere |
| Governed unbypassable `filter` on the view | `active_filter` + `enforce_lifecycle_filters` | **PARITY** — already Aughor's shape |
| Parameters → view-as-TVF (`mv(discount => 0.1)`) | TrustedProgram parameterization | PARITY-ish; note their rule "parameterized can't be materialized" |
| Materialization w/ tiered aggregate-aware rewrite; **refuses to materialize anything invoker-dependent** (RLS/masks/`current_user()`) | matcache is sql-hash only | ADAPT → E-4 rider (scheduled materialization rung); copy the refusal rule verbatim — acceleration must never launder security context |
| Metric views as sources of metric views (composability) | Metrics are flat | Nice-to-have → O tail |
| Cardinality/`at_most_one_match` = **declared promise, no validation** | Measured overlap | **AHEAD** — B-6 makes Aughor the platform that *checks* the promise |

### 3.5 Surfaces (Genie One → Wave S blueprint)

Aughor's web app is a single-page shell; Genie One is the most complete blueprint for what
Wave S should ship. ADOPT (as S scope, not before): routing hierarchy with curated-first
(context graph read-back already implements the idea at the answer layer); **For you**
(recently opened / favorites / trending — drill records already count usage); **Domains**
(tag-driven discovery pages — G's tag plane rendered); Certified/Favorite filters on
listing pages; scheduled tasks as chat-native threads (@mention-able, email delivery —
A5 briefs adopt this UX); document canvas w/ click-through citations (briefings already
cite; the canvas pane is the missing surface); opt-in cited memory (ambiguity ledger user
choices are exactly this — surface them as "remembered, cited, revocable"). **SKIP for
now:** Slack app, mobile apps, homepage branding — distribution surfaces that follow
product-market fit, not precede it.

### 3.6 APIs & distribution

| Genie | Aughor today | Verdict → landing |
|---|---|---|
| **OpenAI Responses-API-compatible agent endpoint** (`model: "genie-agent"`, SSE reasoning/function_call/message items, structured metadata = the contract, markdown declared unstable) | Custom SSE on `/ask`; R4 typed error tail | **ADOPT** → new item **F-3** (S/distribution): an OpenAI-compatible façade over ask/investigate makes Aughor a drop-in for every existing OpenAI client/framework. R4's typed errors slot into their error taxonomy (incl. a `budget_exceeded`-style typed quota error) |
| `serialized_space` agent-as-code (one validated JSON doc, bundle-deployable) | C6 export (graph pack) + overrides in git — **no round-trip import** | ADOPT → **connection-as-code**: export/import the full curation bundle (ontology + overrides + synonyms + trusted queries + glossary + graph). Lands O tail or V; git-native beats their JSON blob — keep YAML |
| Genie Agents exposed **as MCP tools**; skills standard + AGENTS.md/CLAUDE.md auto-discovery | MCP server (7 governed tools) + C6 skills pack | **AHEAD/PARITY** — extend per F-1 (describe_entity, search_graph, get_table_health); add llms.txt (F-2) |
| Poll API: DIY backoff, no server retries, attachments readable mid-flight | SSE already | SKIP the poll paradigm; copy the *documented polling contract* honesty if a poll API ever ships |

### 3.7 Governance, cost, ops (→ Wave G enrichment)

- **Budget algebra** (most permissive within a budget, most restrictive across; alert on
  shared pools, block per-user; blocking never touches the free allowance; enforcement
  non-interrupting with admitted overspend) → the design spec for Aughor org usage caps
  (G's usage-attribution item). Aughor's provider plane already knows "a permission
  ceiling is not a balance" — same family of honesty.
- **Metered free tier as an auditable SKU** + copy-paste cost SQL + downloadable usage
  dashboard → J8 counters surfaced per org/user in a usage page (G), with documented
  queries against Aughor's own session log.
- **Split credential model** (author-embedded warehouse creds; *data* policy per user;
  "last author removed ⇒ all queries fail") → G: make connection run-as explicit and
  surfaced; document the failure mode; Aughor's org-owned connections avoid the trap —
  say so.
- **Per-user OAuth for external sources, tokens never shared** → the rule for any future
  Aughor knowledge connectors (Notion/Confluence connectors exist — audit they're
  per-user, G).
- **Auto-approve classifier disclaimed as "not a security boundary"** → Aughor's K-plane
  target-bound standing grants (J2) are *stronger* (deterministic, target-scoped, owned,
  auditable). AHEAD — and copy their honesty: any future intent classifier gets the same
  disclaimer.
- **Unauthorized data returns an empty response, not an error** → **ANTI-PATTERN by
  Aughor's own R4 ratchet** (a policy block must say so; silent absence fakes a finding
  of absence). Aughor is deliberately opposite — a trust-page talking point.

## 4. UI patterns catalog (from the screenshots studied)

1. **Review Suggested Queries modal** — accordion per candidate; editable question-style
   title ("What are the most expensive jobs in the last 30 days?"); code collapsed behind
   "…47 more lines"; Source link; Accept/Reject per row. *The* reference for every Aughor
   review queue (B-4, C-2, D-2).
2. **Review knowledge snippets modal** — typed chips (JOIN / MEASURE / FILTER), editable
   name + "means" + SQL, collapsible instructions, pre-checked boxes, bulk "Accept N
   snippets."
3. **Connect your data dialog** — search + **For you / All** pills, catalog breadcrumbs,
   checkbox tables, selected-chips row, single Create. Onboarding = one dialog.
4. **Common SQL Expressions catalog** — typed +Add (Filter/Measure/Field), Type/Name/Table
   columns. Small legible curation surface.
5. **Answer anatomy** (talk-to-genie): expandable Analysis (thinking steps: columns/
   instructions chosen → plan → one assembled query), Summary, result table w/ per-column
   format menu, viz w/ save-to-dashboard, applied-filters strip, feedback, suggested
   follow-ups, "Show code." Aughor's receipt + `trust_caveat` already carries more
   substance than their Analysis pane — the gap is rendering, not data.

## 5. The docs-presentation playbook (what "industry standard" is made of)

Worth adopting for Aughor's docs (cheap, high-credibility; mostly Wave S / OSS-readiness):

1. **Audience-grouped IA** — concepts / "For agent authors" / consumers / admin guide as
   separate nav clusters; breadcrumbs expose the hierarchy.
2. **Per-page `Last updated on <date>`** + per-page Yes/No/Send-feedback.
3. **Rename discipline** — "formerly known as Genie Spaces" as a NOTE on *every* affected
   page; old API paths kept (`/genie/spaces/`) with the rename acknowledged.
4. **A limits table on every feature page** — caps published, and taught as design
   ("too many instructions reduce effectiveness").
5. **Annotated screenshots** (numbered callouts explained below) + **GIFs for flows** +
   inline UI glyphs (trash/kebab icons) matching the product exactly.
6. **Verbatim copy-paste prompts** in tutorials and prompt libraries.
7. **Symptom → cause → fix troubleshooting page** (13 entries), with "the fastest path to
   a fix is <the product's own agent>."
8. **Copy-paste cost SQL + a downloadable usage dashboard** — cost observability as docs.
9. **Honest edge-case admonitions** — leakage vectors, credential-embedding failure mode,
   cost surfaces that won't reconcile, classifier-not-a-security-boundary.
10. **Agent-native docs** — llms.txt, per-page .md endpoints, and an embedded "Ask Genie"
    assistant *on the docs site* (dogfooding; Aughor's MCP `ask` tool could power the
    same on Aughor's docs).

## 6. Deltas to the study-doc recommendations

The wave plan (A → G → O → Q → S) stands. This teardown adds/refines:

- **New O item — B-8: window/semiadditive measure vocabulary** for `OntologyMetric`
  (order/range/semiadditive/offset). Big NL2SQL correctness lever; the YAML spec in
  §3.4 is the reference.
- **B-1 enriched:** synonyms primitive **+ entity-matching value dictionaries + typed
  format spec** (the format block closes standing item #189).
- **B-4 now has a full UI spec** (the two modals in §4) and a front door: mine the
  connection's existing saved/dbt/log queries **at onboarding**, not only from verdicts.
- **New F-3: OpenAI Responses-compatible API façade** over ask/investigate.
- **New O/V-tail item: connection-as-code round-trip** (export/import the full curation
  bundle; C6 becomes bidirectional).
- **G enrichment:** budget algebra spec, usage page with documented cost SQL, per-user
  OAuth audit for knowledge connectors, sealed trusted programs, run-as surfacing.
- **S enrichment:** Genie One as the blueprint (For you / Domains / certified filters /
  scheduled-task threads / document canvas / cited opt-in memory); answer-anatomy
  rendering; Fix-it flow; accuracy number; ground-truth update buttons; docs playbook §5.
- **Two more trust-page talking points:** measured-vs-declared cardinality (they document
  silent corruption); policy-blocked-says-so vs their empty response.

## 7. What NOT to imbibe

1. **Empty response on unauthorized data** — violates Aughor's R4 ratchet; keep loud.
2. **LLM-judge benchmark grading** — E4's deterministic comparators stay.
3. **Poll-based conversation API** as a paradigm — SSE stays; steal only its documented-
   contract honesty.
4. **Author-embedded compute credentials** — org-owned connections avoid the
   last-author-removed failure mode entirely.
5. **30-table agent scoping as a security-shaped feature** — Genie's own docs admit
   scoping is relevance-only; Aughor's scoping (RBAC + RLS + guards) is real. Don't copy
   the ambiguity.
6. **Slack/mobile/branding surfaces now** — distribution follows PMF.
7. **US-metadata processing tradeoffs** — Aughor is local-first; keep it that way and
   say it.
