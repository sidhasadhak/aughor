# Aughor — Part II: UI/UX 10x, Nomenclature, and Layer Consolidation
**Reviewer:** senior half of the pipeline · **Date:** 2026-07-03 · **Commit:** `9c06aa3`
**Scope:** frontend `web/` (60 components, ~55k LOC TS/TSX) + the backend concept model. Companion to the Part I security/architecture handoff.

> Method: read the design system (`tokens.css`, `type.css`, `palette.ts`), the report renderers (`ReportView`, `InvestigationReport`, `ChatMessage`, `Brief*`, `BriefingPanel`), the chart-inference engine, the shell (`IntelligenceWorkspace`, `types.ts`), and the primitive layer first-hand; ran three deep agents (report structure, component/gen-UI vs CopilotKit/OpenUI/AG-UI, nomenclature/concept-layering) and verified every load-bearing claim against source. Numbers below (adoption counts, radius violations, jargon-leak counts) are grep-confirmed by me, not taken on faith.

---

## 0. Executive Summary

The foundations are **better than they look and worse than they should be at the same time**. Three assets are genuinely SOTA-grade: a real design-token system (`tokens.css` — Palantir Blueprint accent on Databricks surfaces, WCAG-motivated text floor, motion/radius/chart vocabularies), a principled **chart-inference engine** (`chartTypeInference.ts` picks the honest chart from data shape — most CopilotKit/OpenUI stacks can't), and a correct **report philosophy** already written down in `Brief.tsx`: *"an answer is a document, not a dashboard."*

The problem is **enforcement and consolidation collapsed under 15 months of feature branches**. The token system is violated 156× (radius), the primitive layer is orphaned (0 components import `ui/card`; 183 raw `<button>` vs 5 `<Button>`), the color model is triplicated + 11 local style-maps, the report philosophy is applied in 3 of ~5 answer surfaces, the shell has one exemplary layered workspace (`IntelligenceWorkspace`) and then 20 un-layered sibling panels, the render path is a 1,253-line `ChatMessage` god-component with no registry, and the concept vocabulary has drifted so far that a single idea ("an answer report") has three unrelated type names and the internal acronym **ADA leaks into 47 files**.

**The 10x is not a redesign — it is finishing three consolidations the codebase already started and then knew to stop mid-way:**
1. **One enforced design layer** (tokens → primitives → composites), deleting the orphaned off-brand shadcn `ui/` and promoting `Brief*` to the canonical answer-primitive family.
2. **One shell pattern** — generalize `IntelligenceWorkspace` into a reusable `<Workspace layers={…}>` and fold 20 sibling panels into ~5 workspaces; replace the `ChatMessage` branching with a **renderer registry** (the gen-UI protocol that closes the CopilotKit/AG-UI gap).
3. **One noun model** — a Palantir/Databricks-grade concept dictionary that kills the `Insight`/`Finding`/`Evidence`/`ADA`/mode-name overloads.

**Single highest-leverage move:** ship an enforced 3-tier component layer (**Tokens → Primitives → Composites**) with a lint gate, and migrate the report surfaces onto the `Brief*` composites. This one change dissolves the majority of the UI findings below (card duplication, chip duplication, typography drift, radius violations, color triplication) because they are all symptoms of *no enforced component layer*.

**Most likely silently wrong in the UI today:** number/date formatting inconsistency. `format.ts` is authoritative but under-adopted — `ReportView.KPIHighlight`, `ChatMessage.fmt`, and `HistoryDetailPanel` each re-implement it, so the same value renders "45.3K" in one surface and "45300" in another, and dates differ between a report and its evidence panel.

---

## 1. UI/UX — Observations (UX-##)

> ID · Area · Severity · Location · Observation · Evidence · Impact · Confidence

### The design system: excellent spec, unenforced

**UX-01 · Design tokens · LOW (positive, with a caveat) · `web/styles/tokens.css`**
A real token system: `--bg-0..4`, `--t1..t4` (with a documented 2026-06-10 contrast-floor raise — WCAG awareness baked in), a 6-color intent ramp (`--blue1..5` etc.), motion vocabulary (`--dur-*`, `--ease-*`), radius vocabulary (`--r1..r3`, "max is --r3 — never exceed 6px"), a chart palette, and a full Tailwind bridge with light/dark. This is above most startups. **Confidence: verified.**

**UX-02 · Token enforcement · HIGH · 156 sites, e.g. `ui/card.tsx:15`, across `components/`**
The token file's own hard rule — *"max is --r3 — never exceed 6px in product surfaces"* — is violated **156 times** (`rounded-lg`/`rounded-xl`/`rounded-2xl`/`rounded-full`). There is no lint rule enforcing the token scale, so the discipline lives only in the CSS comment. **Impact:** visual inconsistency (mix of 4/6/8/12px radii), and the token system's promise ("change once") is false in practice. **Confidence: verified (grep count 156).**

**UX-03 · Legacy color aliasing · MEDIUM · `tokens.css:132-167`, 426+ `zinc-*` uses**
The token file maintains a "Legacy zinc aliases — components still use these" bridge, and `zinc-500` alone is used **426×** (plus `zinc-700` 176, `zinc-400` 123…). Components reference raw Tailwind palette names remapped through the bridge instead of semantic tokens (`--t2`). An incomplete migration frozen in place — a leaky abstraction where `text-zinc-500` *means* `--t2` but doesn't *say* it. **Impact:** semantic intent is invisible; theme changes require the bridge forever. **Confidence: verified.**

**UX-04 · Color model triplication · HIGH · `tokens.css` `--chart-1..6` + `lib/palette.ts` `AUG_PALETTE` + `TABLE_PALETTES`/`H_PALETTES`**
The chart series palette exists in **three** places: CSS vars (`--chart-1: #4C8EEE`), `palette.ts` hardcoded hex (`C1 = "#4C8EEE"` — same values, copy-pasted, can drift), and Tailwind class bundles (`H_PALETTES`, `TABLE_PALETTES` use `border-violet-500/30`-style literals). Plus 11 components define local `*_STYLE` dictionaries (`VERDICT_STYLE`, `STAT_STYLE`, `STATUS_STYLE`, `FEEDBACK_STYLES`). `palette.ts` is also mislabeled "Vega-Lite range.category" though the app migrated to ECharts. **Impact:** brand color is not single-source; a palette change requires editing 4+ files, and verdict/status color semantics are decentralized across 11 components. **Confidence: verified (grep + read).**

### The primitive layer: built, off-brand, orphaned

**UX-05 · Orphaned off-brand primitives · HIGH · `web/components/ui/` (9 files)**
A shadcn-style primitives dir exists (`card`, `button`, `badge`, `separator`, `table`, `progress`, `scroll-area`, `motion`, `MiniStat`) but is **near-unused**: `ui/card` is imported by **0** components, `ui/button` by **1** (raw `<button>` appears **183×** vs `<Button>` **5×**), `ui/badge` by 3. And it's **off-brand**: `ui/card.tsx:15` uses `rounded-xl` (12px, violating UX-02) and `font-heading` — a token that **does not exist** in the type system. This is default shadcn output that was never reconciled with `tokens.css`, which is *why* nobody adopts it: it doesn't match the app's own visual language. **Impact:** a dead abstraction masquerading as a design system, and 183 hand-rolled buttons with no shared focus/hover/disabled/aria behavior. **Confidence: verified (import counts + file read).**

**UX-06 · Two report paradigms · HIGH · `components/brief/` (good) vs `ReportView.tsx` (div-soup)**
There is a well-designed answer-primitive family — `Brief`, `BriefHeadline`, `BriefProse`, `BriefSection`, `BriefMetrics`, `BriefFigure`, `BriefDetails` (`components/brief/Brief.tsx`) — whose docstring states the correct SOTA thesis verbatim: *"an answer is a document, not a dashboard… one linear column, prose carries the analysis, charts and tables are the ONLY framed objects, machinery behind one quiet disclosure."* It is adopted by `InvestigationReport` (21 uses), `BriefingPanel` (6), `ChatMessage`. But **`ReportView.tsx` uses it 0 times** — it hand-rolls `CollapsibleSection`, `StatCallout`, `KeyFindingCard`, `RecommendationCard`, verdict chips, all as local divs with hardcoded `emerald-500/30`-style classes. **Impact:** the same answer renders in two visual languages depending on route (`direct` → div-soup ReportView; `investigate` → clean Brief); the good pattern exists but the migration stalled. **Confidence: verified (grep 0 in ReportView).**

**UX-07 · Card/section/chip duplication · HIGH · 20+ card sites, 15+ chip sites, 3 collapsible-section impls**
Per the report agent + my reads: card chrome (`rounded-lg border … p-3/4 + tinted bg`) is redefined 20+ times (`KeyFindingCard`, `RecommendationCard`, risk/action inline, `EvidenceClaimCard`, alerts); status/verdict/confidence chips 15+ ways (three separate `Record` style-maps for essentially one "colored pill"); collapsible sections have **3** incompatible implementations (`ReportView.CollapsibleSection`, `ChatMessage.Section`, `Brief.BriefDetails`) with different chevrons and APIs. **Impact:** every spacing/color/disclosure tweak is a 20-file change; visual drift is guaranteed. **Confidence: verified.**

**UX-08 · Typography drift · MEDIUM · `type.css` (good scale) vs arbitrary sizes**
`type.css` defines a clean scale (`aug-text-h1/h2/h3/ui/sm/xs`, 11px floor, `aug-label`). `InvestigationReport`/`Brief` use it correctly. But `ReportView` and `ChatMessage` predate it and use `text-sm` for both headers and body (no hierarchy) and arbitrary `text-[11px]`/`text-[12px]` — e.g. `ChatMessage` renders a headline as raw `<p className="text-[12px] text-zinc-300">` at one site and `<BriefHeadline>` at another, in the same file. **Impact:** global type-hierarchy changes are impossible; inconsistent heading sizes across surfaces. **Confidence: verified.**

**UX-09 · Formatting under-adoption · MEDIUM · `lib/format.ts` authoritative but bypassed**
`format.ts`/`formatCell.ts`/`measureKind.ts` are a correct, centralized formatting layer (compact numbers, percent, currency-via-orgSettings, date granularity, additivity gate). But `ReportView.KPIHighlight.fmt`, `ChatMessage.fmt`, and `HistoryDetailPanel` re-implement subsets. **Impact:** "45.3K" vs "45300", inconsistent dates between a report and its evidence panel — a *correctness*-adjacent bug in a product whose thesis is trustworthy numbers. **Confidence: verified (agent, corroborated by my format.ts read).**

### Report/answer structure vs SOTA analytical exhibits

**UX-10 · Chart source-attribution missing · MEDIUM · `ResultChartCard.tsx`, `BriefFigure`**
Charts render without a "Source: table(s) · n rows · date range" footer; provenance is hidden behind a collapsed SQL toggle. A Palantir/Databricks/McKinsey exhibit always states its data source under the figure. **Impact:** reader can't judge what a chart is *of* without clicking. **Confidence: verified (agent).**

**UX-11 · Recommendations not grounded in findings · MEDIUM · `ReportView` recommended-actions, `InvestigationReport` details**
Recommended actions render as a list without linking to the finding/evidence that motivates them ("do X" with no "because top-10 customers = 63% of churn"). SOTA "so-what" framing ties every recommendation to its supporting fact. **Impact:** weakens the decision-execution story (and the Palantir-Actions comparison from Part I). **Confidence: verified (agent).**

**UX-12 · No print/export fidelity · MEDIUM · report surfaces**
No print stylesheet; grid layouts don't reflow, charts don't downscale for PDF. Investigations are exported (`reportlab`/`pptx` on the backend) but the web report itself isn't print-faithful. **Impact:** the "share this analysis" loop is lossy. **Confidence: inferred (agent; no print CSS found).**

**UX-13 · Accessibility (carried from Part I) · MEDIUM · `web/` (24 `aria-*` across 60 components)**
Icon-only buttons unlabeled (worsened by 183 raw `<button>`), modals without `aria-modal`/focus-trap, no `aria-live` on streaming status, unaudited dark-contrast on the low tiers. **Impact:** unusable with a screen reader; regulated-buyer blocker. **Confidence: verified.**

**UX-14 · Chart-inference engine · LOW (positive) · `components/charts/chartTypeInference.ts`, `columnRoles.ts`**
Genuinely strong and already consolidated (a note documents killing a prior 3-way duplication): classifies columns, picks line/multi-line/small-multiples/heatmap/stacked/pie/treemap/combo by data shape + intent, with honest-axis logic (`scoreDualAxis` refuses a misleading dual axis). This is a real gen-UI asset. **Keep and lean on it.** **Confidence: verified.**

---

## 2. Component Consolidation — into Layers (LAYER-##)

The app already contains the exemplar. **`IntelligenceWorkspace.tsx`** (250 lines) is a clean, reusable layer pattern: a `LAYERS` array of `{id, icon, label, blurb}`, a controlled `layer`/`onLayerChange` for deep-linking, lazy + keep-alive mounting, and a shared scope header (connection/schema pickers). The consolidation thesis is: **generalize this into one `<Workspace>` shell primitive and fold the 20 sibling panels into ~5 workspaces.**

### The proposed frontend layer model
```
┌─ SHELL ────────────────────────────────────────────────────────────┐
│  app/page.tsx  →  reduce from ~25 NavTabs + 8 useState to a         │
│  <Workspace> registry: { intelligence, canvas, data, operations,   │
│  chat, settings }. Each workspace = generalized IntelligenceWorkspace│
├─ WORKSPACES (each = <Workspace layers={[…]}>) ─────────────────────┤
│  Intelligence : Briefing · Hub · Ontology · Evidence · Org         │
│                 · Metrics · Monitors        (fold 7 panels → 1)     │
│  Canvas       : Browser · Creator · Editor  (fold 3 → 1)           │
│  Operations   : Health · Monitors · Activity · Security (fold 4→1) │
│  Data         : Catalog · Query Builder · Semantic                  │
├─ RENDER ENGINE (the gen-UI layer — see LAYER-05) ─────────────────┤
│  <TurnRenderer registry={{ quick, ada, explore, dossier, direct }}>│
│  replaces the 1,253-line ChatMessage branching                     │
├─ COMPOSITES (answer + intelligence primitives) ───────────────────┤
│  Brief* family (canonical) : Brief, BriefHeadline, BriefProse,     │
│  BriefSection, BriefMetrics, BriefFigure, BriefDetails             │
│  + promote: <Card variant>, <StatusChip>, <FindingCard>,          │
│    <MetricGrid>, <Placeholder state>                               │
├─ PRIMITIVES (token-bound, brand-correct) ─────────────────────────┤
│  Button · Badge · Separator · Table · ScrollArea · Progress        │
│  (rebuilt from tokens.css, NOT default shadcn; delete off-brand ui/)│
├─ TOKENS ──────────────────────────────────────────────────────────┤
│  tokens.css (single source) + type.css + one palette.ts (merged)  │
└────────────────────────────────────────────────────────────────────┘
```

**LAYER-01 · Intelligence panels · HIGH · 7 panels → 1 workspace**
`BriefingPanel` (2112), `IntelligenceHub` (1046), `DomainIntelPanel` (667, likely already merged into Hub), `OrgIntelPanel` (274), `MetricsPanel` (731), `MonitorsPanel` (748) are all *intelligence-over-a-scope* surfaces differing by lens, not architecture. `IntelligenceWorkspace` already unifies 5 of them; `MetricsPanel` + `MonitorsPanel` sit outside as separate tabs. **Action:** add them to the `LAYERS` array (a 2-line change per layer). **Evidence:** `IntelligenceWorkspace.tsx:43-49`. **Confidence: verified.**

**LAYER-02 · Canvas surfaces · MEDIUM · 3 views → 1 workspace**
`CanvasBrowser` (551), `CanvasCreator` (390), `CanvasWorkspace` (855) are sequenced ad-hoc in `page.tsx` with no shared scope header. **Action:** a `<Workspace>` with layers `browser | creator | editor`. **Confidence: verified.**

**LAYER-03 · Operations surfaces · MEDIUM · 4 dashboards → 1 workspace**
`ProcessHealthPanel` (171), `MonitorsPanel` (748), `ActivityLog` (743), `SecurityAuditPanel` (790) are scattered operational dashboards. **Action:** an Operations `<Workspace>` with those as layers. (Note: `MonitorsPanel` is intelligence-adjacent *and* ops-adjacent — pick one home; recommend Operations, deep-link from Intelligence.) **Confidence: verified.**

**LAYER-04 · Ontology Panel vs Canvas · LOW · possible orphan · `OntologyPanel` (1262) + `OntologyCanvas` (1280) + `OntologyOrgCanvas` (304)**
Two+ large ontology visualizations; only `OntologyPanel` is mounted in the workspace. **Action:** confirm whether `OntologyCanvas` is an alternate view (→ `viewMode` prop on one component) or dead (→ delete). ~2,500 lines at stake. **Confidence: inferred — needs a mount-site grep before acting.**

**LAYER-05 · Render engine (the gen-UI gap) · HIGH · `ChatMessage.tsx` (1253) + `investigationStream.ts`**
The render path is a hardcoded branch tree: `if (turn.adaReport) … else if (turn.exploreReport) … else if (turn.dossierReport) … else if direct … else InsightBrief`. Adding an answer type means editing this 1,253-line file. There is **no component registry** — the "registry-driven render engine (P5-P8)" from the roadmap was never built. **Action:** extract a `TURN_RENDERERS` registry (`{ match(turn) → bool, render(turn, props) → ReactNode }`) and make `ChatMessage` a ~150-line dispatcher. **Confidence: verified.**

**LAYER-06 · Streaming spine · LOW (positive) · `lib/investigationStream.ts`, `useChat.ts`, `events.ts`**
The SSE→reducer spine is genuinely good: immutable `updateLast`, exhaustive `ChatTurn` schema carrying the whole investigation lifecycle, resumable kernel event stream (`events.ts` with `since_seq` + backoff + fan-out subscriptions), last-3-turns history threading. Keep it; it's the substrate the registry plugs into. **Confidence: verified (agent).**

### vs CopilotKit / OpenUI / AG-UI
Aughor is **halfway to a generative-UI protocol** and, on one axis, *ahead*:
- **Ahead:** the chart-inference engine (UX-14) is real generative UI intelligence — it *derives* the right visualization from data, which CopilotKit/OpenUI leave to the LLM or the developer. The `Brief` "answer-is-a-document" model is a stronger opinion than CopilotKit's generic slots.
- **Behind:** no declarative agent→UI **render protocol** and no **component registry**. CopilotKit/AG-UI stream `{type: "component", name, props}` into a keyed registry; Aughor streams fat typed events (`ada_report: {…}`) into hardcoded branches. This is type-safe but not compositional — the backend can't introduce a render variant without a frontend release.
- **The close-the-gap move (LAYER-05 + a protocol):** define one event `{type:"render", component:string, props:unknown, slot?:string}`, back it with the `TURN_RENDERERS` registry, and keep the fat typed events as the *first registered renderers* (no rewrite, additive). That yields CopilotKit-class generative UI while keeping Aughor's type-safety and its chart-inference edge.

---

## 2·A. Architectural Layering — Aughor as a Layered Platform (the Databricks lens)

> This is the layering the request is really about: not frontend components, but the **system architecture** — taking the agent runtime (the flow diagram: Entry → Planner → Route/Processing decisions → SQL/Code/Metadata pipelines → validators → stores → outputs) and the Databricks Lakehouse/Data-Intelligence-Platform reference, and consolidating Aughor's ~20 agents+stores into a small set of **functional planes**. A plane is a block with one job, a stated contract (in/out), one owner, and a swap-point — which is exactly what makes it modular and independently *assessable* later. Section 2 (frontend layers) is a sub-case of this: it is the Experience Plane.

### The problem the diagram shows
The agent architecture is drawn — and built — as a **flat mesh of peer agents**. Inside one "CORE AGENTS" box sit twelve nodes at the same level of abstraction: a generator (`Code Generator`) next to a validator (`Code Validator`) next to a store-writer (`Chat History`) next to a router (`Planner`). Control, capability, validation, memory, and data access are interleaved, so there is no line you can cut to reason about, test, or replace one concern. Three symptoms, each grep-confirmed against the code:

- **AL-01 · Validation is duplicated per-path, not a plane.** The diagram has a `Code Validator` and a `SQL Validator` as separate inline nodes (and no metadata validator). In code the trust logic is diffused across **~9 modules in 3 packages** — `agent/{verify,soma,sql_consensus}`, `sql/{grain_guard,join_guard,readonly,safety,trust_checks}`, `tools/{semantic_validator,sql_consistency}`. This is the *architectural* form of Part I's finding that the three answer modes each grew their own SQL-safety subset (`sql/safety.py:preflight_repair` was literally built to re-unify them). Same pathology, one level up.
- **AL-02 · Two-plus isomorphic pipelines.** Data path = `SQL Generator → SQL Validator → Interpret`; Metadata path = `Metadata Handler → Metadata Interpreter`; Code path = `Code Generator → Code Validator → Code Executor → Interpreter`. These are the *same shape* — **Generate → Validate → Execute → Interpret** — implemented three times. They should be one capability template parameterized by domain.
- **AL-03 · State is written as a leaf side-effect.** `Graph Agent → Chat History → {PostgreSQL, Configuration Store}`. Persistence hangs off a rendering leaf; there is no memory boundary. This is the architectural form of Part I's "open feedback loop" gap (feedback captured but never read back).
- **AL-04 · Routing is split across three decision nodes** — `Route Decision`, `Processing Decision`, `Decision Maker` — with fuzzy ownership (the code spreads it across `ask_router`, `complexity`, `graph`, `orchestrator`, `handoff`). This is NOM-01 (intent vs depth conflation) as an architecture smell.
- **AL-05 · The semantic layer is absent from the runtime path.** The diagram has SQL, code, metadata, and stores — but no ontology / metrics / KB. The platform's *crown jewel* (Part I, COMP-01) isn't a plane in the request flow; it's consulted ad-hoc. That is the single biggest architectural gap.
- **AL-06 · Helpers are scattered toolboxes.** `SQL Helper Functions` and `File Helper Functions` are separate boxes; in code, `tools/` holds ~16 loose capability helpers with no unified tool registry — even though `kernel/registries/` already provides the seam pattern to host one.

### The consolidated model: eight functional planes
Modeled on the Databricks Lakehouse's horizontal bands (Workloads → Unity Catalog governance → Delta Lake → Cloud storage) with one **cross-cutting governance spine**. Every current component maps to exactly one plane.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ① EXPERIENCE PLANE            conversational surface · answer/report render   │  ← "Workloads / use-cases"
│                               · workspaces · Final Outputs (data+image / meta) │
├──────────────────────────────────────────────────────────────────────────────┤
│  ② ORCHESTRATION PLANE         Entry · Planner · intent×depth routing ·        │  ← "Orchestration"
│                               plan gate · decision/reconcile                   │
├──────────────────────────────────────────────────────────────────────────────┤
│  ③ AGENT CAPABILITY PLANE      one Generate→Validate→Execute→Interpret         │  ← "AI Agent Systems /
│     (parallel specialist       template, domain-parameterized:                 │     Databricks SQL /
│      pipelines = the           Data-Answer · Analytical-Compute ·              │     AI Applications"
│      "workloads")              Visualization · Metadata/Discovery ·            │
│                               Investigation · Exploration                      │
├───────────────┬──────────────────────────────────────────────────────────────┤
│               │  ④ TRUST & GOVERNANCE PLANE  (CROSS-CUTTING SPINE)             │  ← "Unity Catalog"
│  ⑧ RUNTIME    │     validators + trust guards (grain/fanout/join/CIDR-E1) +   │     (governance,
│  FOUNDATION   │     read-only/safety gate + PII + audit lineage +             │      security,
│  (cross-      │     capability licensing + action approval + reversibility    │      observability)
│   cutting)    ├──────────────────────────────────────────────────────────────┤
│               │  ⑤ SEMANTIC PLANE   ontology (objects/links/actions) ·        │  ← the "meaning" layer
│  kernel       │     SemanticContract (metrics) · glossary · KB · playbook     │     (Aughor's crown jewel)
│  (jobs/       ├──────────────────────────────────────────────────────────────┤
│   metering/   │  ⑥ MEMORY & PROVENANCE PLANE   chat history · kernel ledger · │  ← "MLflow / lineage /
│   flags) ·    │     evidence ledger · graph checkpoints · config store        │     audit"
│  LLM Provider ├──────────────────────────────────────────────────────────────┤
│  Plane ·      │  ⑦ DATA & CONNECTIVITY PLANE   connection registry · warehouse│  ← "Delta Lake +
│  Secret Vault │     drivers (PG/DuckDB/Snow/BQ) · metadata store · file/static│     Cloud Data Lake +
│  · Telemetry  │     store · volumes · unified Tool/Function registry          │     connectors"
│  · Tenancy    │                                                                │
└───────────────┴──────────────────────────────────────────────────────────────┘
```
Governance (④) is drawn as a spine because, like Unity Catalog, it must sit *between* every capability and the data — not inline inside one agent. Runtime (⑧) is the Apollo-equivalent: the deployment/execution substrate every plane runs on.

### Component → Plane mapping (every box in the diagram gets a home)
| Current component (diagram / code) | Target plane | Consolidation note |
|---|---|---|
| User, System Entry Point, Final Output (Data+Image / Metadata), web/ | ① Experience | Final Outputs unify into one `AnswerReport` renderer (NOM-02) |
| Planner Agent, Route Decision, Processing Decision, Decision Maker · `ask_router`/`complexity`/`orchestrator`/`graph`/`handoff` | ② Orchestration | 3 decision nodes + 5 modules → one router with explicit `intent × depth` (AL-04, NOM-01) |
| SQL Generator, Code Generator, Metadata Handler, Interpreter, Metadata Interpreter, Code Executor | ③ Capability | 3 pipelines → 1 domain-parameterized `Generate→Validate→Execute→Interpret` (AL-02) |
| Graph Agent | ③ Capability (Visualization) | already the chart-inference asset (UX-14) |
| Code Validator, SQL Validator · `grain_guard`/`join_guard`/`readonly`/`safety`/`trust_checks`/`soma`/`sql_consensus`/`verify`/`semantic_validator` | ④ Trust & Governance | ~9 modules → one shared, domain-parameterized validation spine every capability calls (AL-01) |
| security/{safety,pii,audit,sandbox}, licensing/, govern/ | ④ Trust & Governance | make fail-**closed** (Part I SEC-02) and first-class, not inline |
| (absent from diagram) ontology/, semantic/, knowledge/, metastore/, playbook/ | ⑤ Semantic | **new plane in the request path** — inject on every route (AL-05) |
| Chat History, Configuration Store · kernel ledger, evidence/, checkpoints.db | ⑥ Memory & Provenance | writes go through a Memory API, not off the Graph Agent leaf (AL-03) |
| PostgreSQL, Metadata Store, Static File System, SQL Helper Functions, File Helper Functions · db/, connectors/, volumes/, tools/ | ⑦ Data & Connectivity | scattered helpers → one Tool/Function registry on `kernel/registries` (AL-06) |
| kernel/{jobs,concurrency,metering,flags}, llm/, secretvault, telemetry, org/, workspace/ | ⑧ Runtime Foundation | already the strongest part (Part I) |

### Aughor ↔ Databricks Rosetta (why this shape is the right target)
| Aughor plane | Databricks Lakehouse analog | Reading |
|---|---|---|
| ① Experience | Workloads / BI / Apps / use-cases | what the user does |
| ② Orchestration | Orchestration (workflows/ETL) | the control plane — but agent-native, not job-native |
| ③ Capability | AI Agent Systems + Databricks SQL + AI Applications | the "workloads engine" |
| ④ Trust & Governance | **Unity Catalog** (governance/security/observability) | the cross-cutting spine — Aughor's is *deterministic trust*, a genuine differentiator |
| ⑤ Semantic | Unity Catalog semantic + metrics + lineage | Aughor is at parity-of-intent, lagging on metrics/lineage objects (NOM-06) |
| ⑥ Memory & Provenance | MLflow + lineage + audit | event-sourced ledger already exists (Part I) |
| ⑦ Data & Connectivity | Delta Lake + Parquet/Iceberg + connectors + ingestion | Aughor reads warehouses rather than owning storage — deliberate |
| ⑧ Runtime Foundation | Apollo (deployment) + compute | kernel = the Apollo-equivalent |

The point of the parallel: Databricks earns "Data Intelligence Platform" by presenting as **clean horizontal planes with one governance spine**, so any band can be assessed or swapped without touching the others. Aughor has the same *material* but presents (and is wired) as a flat agent mesh. Re-drawing it as these eight planes is what makes it a *platform*, not a pipeline.

### What "assessable in the future" requires (the modularity payoff)
Consolidation is only worth it if each plane becomes independently inspectable. Give every plane four things — the codebase already has the mechanism (`kernel/registries/` extension seams: `execution_hooks`, `ingestion`, `purge_hooks`, `schema_annotators`):
1. **A contract** — a typed input/output at the plane boundary (e.g. Capability takes `Question × Scope × SemanticContext`, returns `AnswerReport`; Trust takes `SQL × Scope`, returns `Verdict`).
2. **An owner + an SLO** — one team, one latency/quality target per plane.
3. **A swap-point** — planes are injected via a registry, so an alternate implementation (a new validator, a different LLM plane, an air-gapped data plane) drops in without touching callers. This is the plug-and-play boundary Part I already found the platform enforces at the platform/agent seam — generalize it to all eight planes.
4. **A conformance test suite per plane** — so "is the Trust plane correct?" is a runnable question, independent of the Capability plane.

**AL-REC (architecture) — do this as three reversible moves, not a rewrite:** (i) hoist the ~9 validation modules behind one `trust.verify(sql|code|metadata, scope) → Verdict` façade and make every capability call it (fixes AL-01 + Part I SEC-02 in one place); (ii) collapse the three pipelines into one `Capability{generate,validate,execute,interpret}` template with a `domain` param (AL-02); (iii) insert the Semantic plane into the router so every route carries `SemanticContext` (AL-05). Each is behind a flag, each has a plane-conformance test, none is a big bang. **Verify:** a new capability (say "forecast") can be added by registering one `Capability` impl + reusing the Trust/Semantic/Memory planes unchanged — no edits to Orchestration or the stores.

---

## 3. Nomenclature — the clean noun model (NOM-##)

The vocabulary drifted because concepts were added per-branch without a curator. The fixes below impose a Palantir (Object/Link/Action) / Databricks (Metastore/Catalog/Schema/Table) grade noun model. Ranked by leverage.

**NOM-01 · Answer modes conflate *intent* and *depth* · HIGHEST · `ask_router.py`, `types.ts:200-242`**
`query_mode ∈ {direct, investigate, explore, final_text}` (intent) is tangled with `depth ∈ {quick, deep}` (effort), and neither matches the UI ("Ask", "Deep Analysis", "Explore"). Is "Explore" shallow or deep? (Deep.) Is "direct" the same as "final_text"? (No.) **Fix:** two orthogonal axes, one vocabulary end-to-end:
`Answer { intent: LOOKUP | DECOMPOSE | SCAN | KNOWLEDGE, depth: QUICK | DEEP }`, UI labels "Answer / Investigate / Explore / Knowledge". **Confidence: verified.**

**NOM-02 · One concept ("answer report"), three type names · HIGH · `types.ts:41,114,172`**
`Report` (direct), `ADAReport` (investigate), `ExplorationReport` (explore) are the same idea with three shapes and no common base; the *mode* noun (`investigate`) doesn't even match its *output* noun (`ada_report`). **Fix:** one `AnswerReport` base with optional mode-specific fields; rename the wire events to `report.{lookup|investigate|explore}`. **Confidence: verified.**

**NOM-03 · "ADA" internal jargon leaks into 47 files · HIGH · backend + `web/lib` + `web/components`**
`ADA`/`ada_report`/`adaReport` appears in **47 files** including frontend types and components — an internal acronym (Autonomous Data Analyst) surfacing in the type system a user-facing client depends on. **Fix:** rename to the domain word ("Investigation"/"Deep") at the serialization boundary; keep no `ADA` token in `web/`. **Confidence: verified (grep 47).**

**NOM-04 · "Insight" means three incompatible things · HIGH · `routers/investigations.py`, `explorer/models.py`, `state.py`**
(1) a user-facing answer enrichment (`_InsightResult`), (2) a discovery from exploration (`OntologyInsight`), (3) a per-sub-question snippet (`subq_answers[].insight`). **Fix:** `AnalyticalNarrative` / `DiscoveredPattern` / `key_takeaway` — three names for three concepts. **Confidence: verified.**

**NOM-05 · "Finding" overloaded ×4, no common base · HIGH · `state.py:126,312`, `evidence/models.py:16`, guards' `*Finding`**
`Finding` (Insight path) vs `InvestigationFinding` (ADA, different shape) vs `EvidenceClaim` (persisted, feedback) vs `TrustFinding`/`FanoutFinding`/`KeyFinding` (guards). ADA refactored the shape without migrating the old path; both coexist. **Fix:** one `Fact` base `{id, claim, sql, tables, confidence, source}` with `InvestigationFact`/`ValidatedClaim` specializations; rename guard outputs to `*Signal` so "Finding" means exactly one thing. **Confidence: verified.**

**NOM-06 · "Semantic layer" is 5 modules with no unifying type · HIGH · `semantic/` + `ontology/` + `knowledge/`**
`metrics.py` (`MetricDefinition`), `kb_retriever.py` (untyped tuples), `enforcement.py`, `canonical.py`, plus `ontology.OntologyMetric` (a *different* metric shape). "What are all the metrics?" has 2+ answers. **Fix (Databricks UC pattern):** one `SemanticContract` type (`{id, definition, formula_sql, domain→entity, grain, unit, freshness_sla, lineage, trust_score}`) that `MetricDefinition` and `OntologyMetric` both serialize to; `semantic/` becomes views over it. This is also the #1 *foundational* fix from Part I's ontology bet. **Confidence: verified.**

**NOM-07 · Monitor / Brief / Playbook are siblings with no shared abstraction · MEDIUM · `monitors/`, `briefs/`, `playbook/`**
All three are "watch a metric → do something" (alert / report / recommend) but share no base. **Fix:** a `Safeguard {metric, condition, action: ALERT|REPORT|RECOMMEND, params, owner, sla}` with the three as specializations — unified lifecycle/dashboard/audit, and a cleaner Part I "operational closed loop" story. **Confidence: verified.**

**NOM-08 · Brief / Briefing / Intelligence Digest — one thing, three names · MEDIUM · `briefs/models.py` + UI + docs**
Code `BriefSubscription`, UI "Intelligence Digest", docs "Brief"; no type for the digest itself (only the subscription). **Fix:** pick one external name (recommend "Intelligence Report"), `IntelligenceReport` + `ReportSubscription`. **Confidence: verified.**

**NOM-09 · `hypothesis_id` (and dunder internal ids) leak to the client · MEDIUM · `state.py`, citations, `EvidenceClaim`**
System ids surface in citations/drill links. (Related: the `__dunder__` hypothesis-id security-bypass from Part I.) **Fix:** map to a human phase name at the serialization boundary; never ship `hypothesis_id` to `web/`. **Confidence: verified.**

**NOM-10 · `Playbook` vs `PlaybookEntry` · LOW · `playbook/models.py:7`** — same row type, two names. **Fix:** keep `Playbook`. **Confidence: verified.**

**NOM-11 · Scope is three mechanisms with unclear precedence · MEDIUM · `state.py` `canvas_id` + `connection_id` + `scope_schema` + `table_filter`**
No single scope object; precedence (canvas tables vs schema vs connection) is implicit. **Fix:** one `ExecutionScope {connection_id, canvas_id?, schema_name?, table_filter[]}` with documented precedence, threaded everywhere. Ties to Part I's tenancy work. **Confidence: verified.**

**NOM-12 · UI panel names are vague/overlapping · LOW · `IntelligenceHub` vs `BriefingPanel` vs `DomainIntelPanel` vs `OrgIntelPanel`**
Four "intelligence" panels whose names don't tell you what's different. Fold per LAYER-01 and name by lens ("Briefing", "Data Profile", "Org Knowledge"), not by "Hub/Panel/Intel". **Confidence: verified.**

---

## 4. Recommendations (for the executor)

> Same discipline as Part I: small, reversible, mechanically verifiable. Do the design-layer recs before the consolidation recs (they unblock each other). Do NOT restyle components while migrating structure, and do NOT rename concepts and move files in the same commit.

### REC-U1 — Enforce the token scale with a lint gate (Addresses UX-02, UX-03, UX-08)
1. Add an ESLint rule (or a `stylelint`/regex check in CI) that fails on `rounded-(lg|xl|2xl|3xl|full)` and on raw `text-\[\d+px\]` in `components/**` and `app/**`.
2. Codemod the 156 radius sites to `rounded-[--r2]`/`rounded-[--r3]`; codemod arbitrary `text-[11/12/13px]` to the nearest `aug-text-*`.
**Verify:** `grep -rE "rounded-(lg|xl|2xl|3xl|full)" web/components web/app | wc -l` returns 0; CI job fails on a reintroduced violation. **Risk:** a few intentional pills use `rounded-full` — allow via an explicit `rounded-[--r-pill]` token, not the raw class. **Do NOT** batch this with color changes. **Confidence: verified.**

### REC-U2 — Rebuild primitives from tokens; delete the orphaned shadcn `ui/` (Addresses UX-05)
1. Rewrite `ui/button.tsx`, `ui/badge.tsx`, `ui/card.tsx` to use token vars (`bg-[--bg-2]`, `ring-[--b1]`, `rounded-[--r3]`, `aug-text-*`) — remove `rounded-xl` and `font-heading`.
2. Codemod the **183** raw `<button>` → `<Button>` (variant inferred from existing classes) and the ad-hoc card divs → `<Card variant>`.
**Verify:** `grep -rc "<button " web/components | awk -F: '{s+=$2} END{print s}'` drops below ~20 (only primitives define raw elements); `ui/card` import count > 15. **Risk:** button behavior differences (type=submit) — preserve `type` in the codemod. **Do NOT** invent new variants; map to what exists. **Confidence: verified.**

### REC-U3 — Promote `Brief*` to canonical; migrate `ReportView` onto it (Addresses UX-06, UX-07)
1. Move `components/brief/*` to `components/composites/` and export a `<FindingCard>`, `<StatusChip>`, `<MetricGrid>`, `<Placeholder state>` built from the same tokens (fold `VERDICT_STYLE`/`STAT_STYLE`/`STATUS_STYLE`/`FEEDBACK_STYLES` into one `STATUS_SCHEMA`).
2. Rewrite `ReportView.tsx` to render via `Brief`/`BriefSection`/`BriefDetails`/`FindingCard` (delete `CollapsibleSection`, `KeyFindingCard`, `RecommendationCard`, local chip maps).
**Verify:** `ReportView` uses `BriefHeadline`/`FindingCard` (grep > 0) and defines 0 local `*_STYLE` maps; a screenshot diff shows `direct` and `investigate` answers share one visual language. **Risk:** ReportView has direct-mode-only sections (KPI highlight) — keep them as `Brief` children, don't drop. **Confidence: verified.**

### REC-U4 — One palette source (Addresses UX-04)
1. Make `palette.ts` derive from the CSS vars (read `--chart-1..6` via `getComputedStyle` or generate both from one TS constant that also emits the CSS) so there is a single source; fix the stale "Vega-Lite" label to "ECharts".
2. Replace `TABLE_PALETTES`/`H_PALETTES` literal class bundles with token-derived ramps.
**Verify:** the six brand hex values appear in exactly one file; changing `--chart-1` changes both chart series and card chrome. **Risk:** SSR can't read `getComputedStyle` — generate at build from one constant instead. **Confidence: verified.**

### REC-U5 — Generalize `<Workspace>`; fold sibling panels (Addresses LAYER-01/02/03)
1. Extract `IntelligenceWorkspace`'s shell (scope header + `LAYERS` array + keep-alive body) into a generic `<Workspace layers={Layer[]} layer onLayerChange scope>`.
2. Re-express Intelligence (+Metrics +Monitors), Canvas, and Operations as `<Workspace>` instances; map legacy `NavTab`s to `workspace + layer` deep-links (the file already does this for `intel`/`ontology` → `intelligence`+layer — copy that pattern).
**Verify:** `page.tsx` NavTab union shrinks (fewer than ~12); the 4 folded panels are no longer routed as standalone tabs; deep-links (`?tab=intelligence&layer=metrics`) resolve. **Risk:** losing deep-link back-compat — keep the `LEGACY_*_LAYER` map. **Do NOT** merge component *internals* in this rec — only routing/containment. **Confidence: verified.**

### REC-U6 — Renderer registry (Addresses LAYER-05, closes the gen-UI gap)
1. In `investigationStream.ts` or a new `renderers.tsx`, define `TURN_RENDERERS: {id, match(turn):boolean, render(turn,props):ReactNode}[]` with the existing five bodies (quick/ada/explore/dossier/direct) as the first entries.
2. Reduce `ChatMessage`'s `InvestigateBody` to `renderers.find(r => r.match(turn))?.render(turn, props)`.
**Verify:** `ChatMessage.tsx` line count drops > 300; adding a dummy renderer needs zero edits to `ChatMessage`. **Risk:** match order matters (dossier before direct) — encode priority by array order and add a unit test. **Confidence: verified.**

### REC-U7 — Chart source-footers + grounded recommendations (Addresses UX-10, UX-11)
1. Extend `BriefFigure` to accept `sourceTables`/`rowCount`/`dateRange` and render a `<FigureCaption>` footer; pass from `ResultChartCard`.
2. In report renderers, render each recommendation with its `origin_finding`/evidence link (the backend already captures finding provenance — Part I "Finding Dossier").
**Verify:** a rendered chart shows "Source: … (n rows)"; each recommendation shows a "because …" evidence chip. **Confidence: inferred (backend provenance exists; wiring to UI unverified).**

### REC-U8 — Formatting adoption gate (Addresses UX-09)
1. Delete the local `fmt` in `ReportView.KPIHighlight`, `ChatMessage`, `HistoryDetailPanel`; route through `format.ts`/`buildColumnFormatter`.
2. Add a lint rule banning `toLocaleString`/manual `Intl.NumberFormat` outside `lib/format.ts`.
**Verify:** grep finds no `toLocaleString` in `components/`; one value renders identically across report + evidence panel. **Confidence: verified.**

### REC-U9 — Concept renames at the serialization boundary (Addresses NOM-01/02/03/04/05)
> Sequence carefully; each is one reversible commit, renames only at the wire/UI boundary first (no internal churn).
1. Add a serialization layer that renames on the way out: `ada_report`→`report` with `mode:"investigate"`; strip `ADA`/`hypothesis_id` from `web/`-bound payloads.
2. Regenerate `api.gen.ts`; update `types.ts` to the `AnswerReport`/`Fact`/`AnalyticalNarrative` vocabulary; keep old names as `@deprecated` aliases for one release.
**Verify:** `grep -rc "ADA\|adaReport" web/` → 0; the app still renders every mode (screenshot each). **Risk:** high blast radius — do the boundary rename first, internal renames later, behind the alias. **Do NOT** rename backend internals and the wire in one commit. **Confidence: verified.**

### REC-U10 — `SemanticContract` unification (Addresses NOM-06; ties to Part I ontology bet)
1. Define `semantic/contracts.py:SemanticContract`; make `MetricDefinition` and `ontology.OntologyMetric` serialize to it.
2. Point planning/enforcement/display at the one type.
**Verify:** a new `list_contracts()` returns one shape; `MetricDefinition`/`OntologyMetric` become thin adapters (tests green). **Risk:** largest rec here — flag-gate and keep adapters. **Confidence: inferred (design).**

---

## 5. Executor Failure-Mode Pass
- **REC-U1:** codemod turns an intentional `rounded-full` avatar into `rounded-[--r3]`. *Guard:* introduce `--r-pill` and allowlist it; review avatar/badge sites.
- **REC-U2:** raw→`<Button>` codemod drops `type="submit"` → forms break. *Guard:* preserve all native attrs; add a form smoke test. Residual: visual hover diffs — screenshot-diff the primitives once.
- **REC-U3:** executor restyles while migrating and changes spacing everywhere. *Guard:* rec says structure-only; diff must be DOM-structure, not color. Residual: a dropped direct-mode section — enumerate ReportView's sections in the rec.
- **REC-U4:** `getComputedStyle` at SSR returns empty → charts render black. *Guard:* rec mandates build-time generation from one constant, not runtime read.
- **REC-U5:** executor merges panel internals (not just routing) and breaks a panel. *Guard:* rec is explicit "routing/containment only." Residual: broken deep-links — keep `LEGACY_*_LAYER`, test each.
- **REC-U6:** renderer match order wrong (direct shadows dossier). *Guard:* array-order priority + a unit test asserting a dossier turn picks the dossier renderer.
- **REC-U9:** renames wire + internals together → nothing compiles. *Guard:* boundary-first, `@deprecated` aliases, one mode per commit, screenshot each mode. This is the highest-risk rec — sequence it last.
- **REC-U10:** two metric shapes diverge mid-migration. *Guard:* adapters + flag; keep both readable until parity tests pass.

---

## 6. Prioritized Roadmap
| REC | Title | Effort | Leverage | Depends on |
|-----|-------|--------|----------|------------|
| **DO NOW — design layer (unblocks the rest)** |
| REC-U1 | Token/radius/type lint gate + codemod | S | High | — |
| REC-U2 | Rebuild primitives from tokens; delete off-brand ui/ | M | High | REC-U1 |
| REC-U4 | One palette source | S | Med | REC-U1 |
| REC-U8 | Formatting adoption gate | S | Med | — |
| **DO NEXT — composite + structure** |
| REC-U3 | Promote Brief*; migrate ReportView | M | High | REC-U2 |
| REC-U7 | Chart source-footers + grounded recs | M | Med | REC-U3 |
| REC-U6 | Renderer registry (gen-UI) | M | High | REC-U3 |
| REC-U5 | Generalize `<Workspace>`; fold panels | L | High | REC-U2 |
| **DO LATER — concept model + backend** |
| REC-U9 | Concept renames at the boundary | L | High | REC-U6 |
| REC-U10 | SemanticContract unification | L | High | REC-U9 |
| LAYER-04 | Resolve OntologyCanvas orphan | S | Low | — |
| NOM-07/11 | Safeguard base + ExecutionScope | L | Med | REC-U10 |

Ordering: the design layer (U1/U2/U4/U8) lands first because every structural rec renders through it; the render registry (U6) and Workspace generalization (U5) depend on brand-correct primitives; concept renames (U9/U10) go last because they have the widest blast radius and want the registry + composites stable first.

---

## 7. Introspection
**(a) What the UI encodes.** The frontend's worldview is *right* and its execution is *unfinished*. The `Brief.tsx` docstring — "an answer is a document, not a dashboard" — is a genuinely SOTA opinion (it's what separates a McKinsey exhibit from a Grafana board), and the token system + chart-inference engine show a team that knows what good looks like. But the codebase is a 15-month sediment of feature branches, each of which added a panel/report-type/style-map without a curator enforcing the layers. So every good abstraction exists *and* has an un-migrated legacy twin beside it: `Brief*` beside `ReportView` div-soup, `ui/` primitives beside 183 raw buttons, `tokens.css` beside 156 radius violations, `IntelligenceWorkspace` beside 20 sibling panels. The platform optimized for *shipping the next intelligence feature* at the expense of *finishing the last consolidation* — which is exactly the debt that compounds into a rewrite if left another 15 months.

**(b) Limits of this review.** I read the design system, the report renderers, the shell exemplar, the primitive layer, and the concept types first-hand and grep-verified every count. I did **not** run the app, screenshot the real surfaces, or audit `QueryBuilder` (2505), `CatalogScreen` (1675), or `OntologyCanvas`/`OntologyPanel` internals — so LAYER-04 (orphan or not) is unconfirmed, and the report-structure findings are code-structural, not pixel-verified. The nomenclature proposals are grounded in the type definitions but I traced only the main answer/semantic paths, not every guard's `*Finding`. To raise confidence I'd next run the app to screenshot `direct` vs `investigate` answers side by side (to prove UX-06's "two visual languages" claim visually), and grep `OntologyCanvas` mount sites (to settle LAYER-04).

---

## 8. The 20-Year View (UI/nomenclature axis)
- **Ages worst:** the un-enforced design layer. A token system that lint can't protect will keep drifting; by year 2 the "single source of truth" is fiction. Make enforcement (REC-U1) cheap-to-keep now.
- **The foundational UI bet:** a **render protocol + registry** (REC-U6). If the agent→UI contract stays hardcoded branches, every new answer type is a frontend release and the AI-native "the agent composes its own UI" thesis is impossible. A registry keyed by semantic type is the thing that lets an *AI FDE* ship a domain pack that renders custom surfaces without a web deploy — the same leapfrog Part I identified, expressed in the UI.
- **The foundational nomenclature bet:** the `SemanticContract` + `Fact` unification (NOM-05/06). Part I ranked the ontology/metrics object model the #1 20-year bet; the *naming* is the same bet's surface. As long as "metric" has two shapes and "finding" has four, no downstream layer (governance, write-back, packs) can reason about them uniformly. Impose the noun model now, while there are dozens of call sites, not thousands.
- **What to make cheap now:** (1) the lint gate (freezes drift), (2) the `<Workspace>` generalization + renderer registry (makes new surfaces additive, not invasive), (3) `@deprecated` aliasing at the type boundary (makes the concept renames reversible and incremental). All three convert "someday rewrite" into "this sprint, reversibly."
- **What it could become:** the current split — a strong intelligence engine wearing an un-consolidated UI — is exactly the gap between "impressive demo" and "platform an enterprise standardizes on." Closing it (one enforced design layer, one shell pattern, one render protocol, one noun model) is what turns Aughor's real assets (chart-inference, the Brief document model, the ontology) into something that *looks and reads* like the category leader it's architected to be.
