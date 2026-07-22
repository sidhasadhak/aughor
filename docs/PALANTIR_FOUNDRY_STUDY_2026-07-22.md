# Palantir Foundry — Full-Platform Deep Study (2026-07-22)

**Method.** Nine parallel research passes over https://www.palantir.com/docs/foundry (~230 doc pages read
across 8 areas: data connection, pipelines/datasets, Ontology, analytics apps, Workshop/app-building,
AIP, ML lifecycle, security/governance/admin) plus a full inventory of Aughor's current surface for the
gap analysis. Builds on the 2026-07-01 AI FDE study (3 pillars: user-owned context, graduated autonomy,
declarative modes/skills) and the Databricks parity program (Genie head-to-head, HAR wire study, MLflow,
Unity-Catalog-shaped metastore).

**Thesis in one line.** Databricks sells the *substrate* (lakehouse + catalog + compute); Palantir sells
the *loop* (data → semantics → human/AI decision → write-back → data). Aughor already has a lean
substrate story (DuckDB compute + pushdown, UC-shaped metastore) and a trust story Palantir lacks
(deterministic guard battery). What Foundry teaches us is the **kinetic half** — actions, automations,
evals, artifact lifecycle, and governance that propagates through lineage. That is the path to the
all-inclusive agentic platform.

---

## 1. The Foundry platform map

### 1.1 Connectivity (Data Connection)
- **Source = locator + credential + worker + egress policy** — four orthogonal, separately-permissioned
  objects. Worker (where compute runs: in-platform container vs legacy on-prem agent), egress (where
  traffic may go: proposal→approval lifecycle, immutable destinations, revoke-not-delete), credential
  (encrypted, secret-less options).
- **Capability matrix per connector** is the central UX contract: each of ~200 connectors advertises
  typed capabilities (batch sync / incremental / CDC / streaming / media / virtual tables / exports /
  webhooks / explore / use-in-code) with 🟢GA/🟡Beta status; the catalog is searchable *by capability*.
- **Virtual tables**: zero-copy pointers into Snowflake/BigQuery/Databricks/S3+Iceberg with compute
  pushdown and **version-aware update detection** (downstream work re-runs only when the source
  verifiably changed).
- **Syncs are transactional** (all-or-nothing; failed sync = dataset unchanged) with a small set of
  *named* ingestion modes (mirror / incremental append / update / trailing-window) and docs that
  enumerate which config combinations break which mode.
- **Webhooks** = the outbound write-back path: typed input/output params, chained calls with
  `@`-references into prior responses, one-unsafe-call rule, "did the external system change?" capture
  on failure, live test panel that auto-suggests output schema, import-from-cURL.
- **Exports are a marking-gated privilege, not a feature**: off by default, enabled per source by an
  InfoSec role that enumerates exactly which sensitivity markings may leave.

### 1.2 Pipelines, datasets, builds, health
- **Dataset = files → transactions → branches → views → schema.** Append-only transaction log gives
  time travel, as-of reproducibility, and one-click rollback. At most one open transaction per branch.
- **Builds are staleness-resolved**: an output is "fresh" if inputs AND logic-hash are unchanged; fresh
  outputs are skipped; force-build documented as "almost never required."
- **Schedules**: triggers = cron OR dataset-updated OR job-succeeded OR schedule-status, combinable
  with AND/OR; explicit ignore lists "for transparency"; abort/retry/exceed-limit knobs.
- **Pipeline Builder**: visual DAG; LLM steps are ordinary palette boards with a **"Trial run"**
  single-example harness and a 50-row preview before scale-out. Same tool does batch/incremental/streaming.
- **Code Repositories**: git-backed, protected branches, approval policies with ALL/ANY composition and
  file-regex conditional rules; automated upgrade-bot commits flow through the same review gate.
- **Data Health**: ~30 declarative check types; **median-deviation auto-thresholds** (compare to
  historical median, not hand-set bounds); event-triggered evaluation; failing check **auto-creates an
  assigned Issue and auto-closes it on recovery**; scope-based *monitoring views* over whole projects so
  new resources get coverage automatically (per-resource check groups were sunset — they don't scale).
- **Expectations-in-code**: one assertion API both aborts a bad write AND becomes a standing monitored
  check.
- **Data Lineage is a control plane, not a viewer**: one graph, recolorable by health / staleness /
  ownership / permissions; batch actions from the graph (multi-select → apply checks, build, rollback);
  marking-change impact simulation; **Compare tab pairs the data diff with the transform-code diff**
  between two dataset versions.
- **Global branching**: code + pipelines + datasets + ontology entities branch together under one
  proposal with per-resource checks and merge-time build choice.

### 1.3 The Ontology (the crown jewel)
- **Nouns**: object types (schema over backing datasets, stable **API names** distinct from display
  names — renames never break consumers), properties (incl. vector, time-series, geo, media, struct,
  cipher), link types (each side has its own API name), **interfaces** (abstract shapes for
  polymorphism), derived properties (≤3 link hops, fixed aggregation menu, read-only).
- **Verbs**: **Action types** — the *only* write path. Parameterized rules (create/modify/delete
  object/link, or a function), **submission criteria** (declarative AND/OR/NOT conditions over user +
  parameters + object state, each carrying a human-authored failure message rendered identically in
  every app), side effects (notifications, webhooks, schedule triggers). One compiled edit per object,
  transactional.
- **Edits are a layer, never a mutation**: user/agent edits live in an overlay with an explicit
  per-property precedence policy ("edit always wins" vs "most recent timestamp wins"), merged at read
  time via a read-your-writes queue, periodically persisted, and **materializable back into datasets**
  that pipelines consume. Apps write back without ever touching source pipelines.
- **Schema changes are PRs**: branch → proposal → per-resource review tasks → rebase with per-resource
  conflict resolution → merge; the killer feature is **indexing on the branch** so reviewers run real
  queries against proposed semantics before merging.
- **Zero-config Standard Object View**: every modeled entity instantly gets an auto-generated hub page
  (properties, links, special rendering for TS/geo/media) — instant payoff is what makes people
  maintain the ontology. Configured (Workshop-built) views never remove the standard fallback.
- **Agents get exactly three tools**: query objects (scoped types/properties), execute actions (same
  submission criteria as humans, confirm-or-auto), call functions. **No raw SQL tool.** The ontology is
  simultaneously the context store, the guardrail, and the write API for AI.
- **Observability lives in the modeling tool**: every action/function definition page shows 30-day
  usage + monitoring; every object type shows dependents — cleanup and trust decisions are data-driven.

### 1.4 Analytics apps
- **Contour** (tabular path analysis): linear top-down paths of boards; the "active dataset" concept;
  **"Save as Dataset" compiles a click-path into a real scheduled pipeline node with lineage**, with an
  explicit "Update" gate separating logic changes from data refreshes.
- **Quiver** (object/time-series analysis): typed cards (object set, time series, chart, *number*);
  canvas for presentation + graph mode for the true dependency DAG; hover **"next actions"** menus that
  propose each card's legal continuations; dashboards declare **typed inputs/outputs** with documented
  per-host conversions for bidirectional embedding; writeback via Action buttons with inputs pre-filled
  from chart selections.
- **Notepad** (living documents): every embed is **live-by-default; freezing is an explicit "Lock data"
  act** that stamps a lock icon + snapshot timestamp; locking refused on data it can't govern; dead
  snapshots error rather than silently lie. Templates with typed object inputs + row/section generators
  → one-click per-entity document generation from an operational app.
- **Fusion** (spreadsheets over governed data), **Code Workspaces** (Jupyter/RStudio; notebook registers
  as a pipeline transform with inferred inputs/outputs).
- Ships a **"which tool when" decision guide** and an Excel-idiom translation table (VLOOKUP→join).

### 1.5 App building & developer platform
- **Workshop**: uniform widget contract (every widget = typed input variables + output variables +
  display options — one mental model for 60+ widgets); a **variable lineage graph with per-node compute
  timing** (doubles as profiler); lazy recompute (only what a visible widget needs); fill-in-the-blank
  event vocabulary ("Switch to {page}", "Set variable", **"Stream LLM response into variable"**);
  **save≠publish** with auto semantic versions, JSON changelog diffs (adds/deletes/changes/moves/unused),
  one-click revert; Scenarios = immutable ontology forks storing only edits (sandboxed what-if).
- **Module interface** = variables with external IDs, settable identically by (a) a parent module,
  (b) URL query params, (c) portal navigation — one mechanism, three features.
- **Carbon** portals: typed inter-module navigation — modules declare input/output types; "Open in"
  menus show only type-compatible destinations and pass the current selection.
- **Marketplace / DevOps**: products declare OUTPUTS; the dependency graph is walked automatically and
  unresolved dependencies become installer-mapped INPUTS with presets; release channels
  (Stable⊂Test⊂Release), maintenance windows, recallable versions, pre-publish linter.
- **Developer Console + OSDK**: SDK codegen *from the granted resource list* — capability surface and
  auth surface are identical by construction; token scope = intersection(user perms, app restrictions,
  requested scopes).

### 1.6 AIP (the agentic layer)
- **AIP Logic** (no-code LLM functions: block chain, ontology tools, debugger with per-block reasoning +
  token bars) and **Chatbot Studio** (assistants with retrieval contexts + tools + application state) —
  both **publish as versioned Functions** with typed I/O (incl. `sessionRid` continuation), so the same
  artifact runs in apps, pipelines, actions, automations, and evals.
- **AIP Evals** — the discipline: suites = test cases × functions × evaluators; deterministic evaluator
  library (exact/regex/Levenshtein/numeric-temporal ranges/object-set membership) + LLM-as-judge +
  custom evaluators returning multi-metric structs with per-metric objectives; N iterations for
  variance; run-to-run diff; **"Add as test case" one click from the debugger**; "Generate evals"
  bootstraps suites; **grid-search Experiments** (parameterize model/prompt, run all combos, group by
  parameter); **ontology simulation** for write-producing functions (assert on resulting state in a
  sandbox). Positioned as "the foundation of stable, reliable AIP workflows" — enforced culturally, not
  technically.
- **Automate**: condition (time / object-set change / streaming, combinable) → effects (action, Logic
  function, notification) with **fallback effects, jittered retries, muting/pausing/expiration**, and
  per-object batched execution. Agent edits can be **staged-for-review: a Proposals queue where each
  proposal carries the LLM's reasoning ("Agent decision log")**; accept → Applied.
- **Session logging**: 9 structured event types (`user_request`, `tool_call`, `tool_call_result` w/
  duration+success, `final_response`, `execution_error`, …) with traceId/sessionRid, exported to a
  queryable dataset; documented recipes for tool reliability/latency analysis; real sessions feed evals.
- **LLM plumbing**: all model calls route through a managed proxy (contractual zero-data-retention,
  geo-routing, rate limits, audit) — including **provider-compatible API endpoints** so any OSS SDK
  inherits governance for free; model catalog with lifecycle stages + per-model tri-state opt-in
  (Enabled / Disabled-until-terms-accepted / Disallowed); 3-tier TPM/RPM capacity (enrollment/project/
  user) with reserved capacity and interactive-over-batch priority; every request attributed to exactly
  one bucket (project vs user).
- **Tool-approval UX**: per-tool auto vs user-confirm; command payload review gates on by default;
  **"Request Clarification" is itself a tool** the LLM can call; citations are interactive objects that
  can update application state.
- **AI FDE**: autonomous platform operator under the user's own identity; minimal user-owned context;
  branch-proposals by default. (Detail in the 2026-07-01 study.)

### 1.7 ML lifecycle
- **Model adapter**: one typed `api()` declaration drives every consumption surface (batch pipeline,
  live REST endpoint, typed ontology function) — enforced at publish time.
- **Modeling Objectives**: submission-as-PR (immutable candidate → identical auto-eval suite on the
  same pinned dataset transaction → visible PASS/REJECT/PENDING checks, advisory but loudly filterable
  → staging/production **release channels that consumers subscribe to** — promotion auto-upgrades all
  deployments zero-downtime).
- **Inference history ledger**: every live inference logged {who, when, model_version, input, output,
  error} into a queryable dataset, explicitly marketed for drift detection + retraining; best-effort
  writes (never block serving on logging).
- External models (OpenAI/SageMaker/…) wrapped as governed proxy assets flowing through the *same*
  eval/release/deploy machinery.

### 1.8 Security, governance, operations
- **Two-plane access algebra**: Access = (satisfies ALL mandatory markings — AND-composed) AND (holds a
  discretionary role granting the operation). Mandatory always trumps discretionary; **removing a
  marking requires the marking's own "Expand Access" permission — ownership never declassifies**.
- **Markings propagate two ways**: file hierarchy AND **data lineage** — marking a source dataset
  protects every derived artifact platform-wide. **Simulation-before-apply** previews the propagation
  blast radius. Two legible failure modes: invisible-by-default (hierarchy) vs metadata-shell
  (lineage).
- **Checkpoints**: justification middleware at 60+ sensitive interaction points (acknowledgment /
  free-text / dropdown / re-auth), org-authored Markdown prompts, records reviewable + auto-redacted,
  reuse-last-5 to kill friction.
- **Approvals**: one inbox; requests hold N tasks with independent reviewers/states; "Action Required"
  = approved-but-blocked-on-justification; completed requests persist as the audit trail.
- **Audit**: every event carries an enforced category enum (`dataExport`, `llmInference`, `userJustify`,
  `managementMarkings`, …) — monitors written once against categories; **the model call itself is a
  first-class audit event**; the control plane audits itself.
- **Usage attribution**: compute-seconds/GB-months attributed per project on completion date, rolled to
  usage accounts, sliced in an Analysis tab; resource queues with pre-saturation alerts; anomaly
  detection + budgets.
- **Lineage-aware deletion** (Data Lifetime): deleting a transaction cascades to all downstream derived
  transactions — the same lineage index powers both protection and purge.
- Docs consistently state each control's limitations and point at the complementary layer; anti-patterns
  are documented explicitly (don't grant per-file, don't skip simulation, download controls ≠ containment).

---

## 2. The meta-patterns (what actually makes Foundry work)

1. **One substrate, many surfaces.** Everything reduces to datasets-with-transactions; every app,
   check, agent, and permission speaks that substrate. No feature invents its own storage or lineage.
2. **The loop, not the catalog.** Semantic layer (nouns) + kinetic layer (verbs). Write-back through
   declared Actions only — for humans AND agents. This is the single biggest differentiator vs
   Databricks, and the reason Foundry apps are *operational* rather than analytical.
3. **Everything is a versioned, branchable resource with proposals.** Code, pipelines, datasets,
   schema, apps, agents — same branch/propose/review/merge grammar everywhere, with real-data preview
   on branches.
4. **Typed contracts at every seam.** Widget variables, dashboard inputs/outputs, module interfaces,
   model adapter APIs, function signatures, connector capabilities. Composition is always "plug typed
   output into typed input" — one mental model platform-wide.
5. **Exploration graduates to production.** Contour path → scheduled dataset; debug run → eval test
   case; notebook → pipeline transform; ad-hoc analysis → published dashboard. The on-ramp from playing
   to production is always one click, and the graduation creates a *governed* artifact.
6. **Live-by-default, snapshot-by-choice, staleness legible.** Every embed is live; freezing is an
   explicit visible act; dead snapshots error loudly; embedders choose pin-version vs auto-follow.
7. **The platform mediates all agent access.** LLMs only *ask* for tools; writes only via Actions with
   the same submission criteria as humans; permissions from the executing principal; evals before
   deploy; proposals with reasoning logs for autonomous edits.
8. **Mandatory + discretionary security with lineage propagation and simulation.** Protection follows
   the data wherever it flows, and every governance act can be dry-run first.
9. **Observability and usage attribution live on the definition page.** Every type/action/function/
   model shows who uses it, how often, and what it costs — cleanup and trust are data-driven.
10. **Products, not features.** Anything can be packaged (ontology + pipelines + apps + agents) into a
    versioned, installable, upgradeable product with dependency-walked inputs. That's the ecosystem play.

**Foundry's weakness (our edge):** no deterministic answer-guard layer. Their correctness story is
evals + human review end-to-end. Aughor's guard battery (grain/fan-out, value-domain, E1 footguns,
lifecycle, read-only AST) is a plane Foundry simply doesn't have. Adopting their evals harness *around*
our guards covers both flanks.

---

## 3. UI/UX playbook worth copying

- **Hover "next actions"**: every card/answer proposes its legal continuations (drill, compare period,
  save as metric, alert on this) — the system enumerates what's possible next.
- **Uniform widget/card contract** (typed in/out) + a **variable lineage graph** as the explain/debug
  surface.
- **Save≠publish + JSON changelog diff + one-click revert** for every user-authored artifact.
- **Zero-config entity pages** the moment something is modeled; configured views never remove the
  fallback.
- **Preview-before-commit everywhere**: source preview, sync 20-row preview, webhook test panel with
  response→schema suggestion, LLM board trial-run, marking-change simulation, policy test-as-user.
- **Status color language** (🟢GA/🟡Beta/🔴deprecated) on capability tables; explicit
  Beta/Legacy/Sunset banners with migration pointers.
- **Check Access panel**: simulate any user; mandatory-plane result + role chain + inherited-lineage
  requirements with colored pass/fail — governance made testable, on every resource.
- **Lock icon + snapshot timestamp** on frozen numbers; "Overridden" tags on temporary viewer parameter
  overrides.
- **Docs-as-product**: per-app Overview → Getting started → per-feature pages, "which tool when"
  decision guides, documented anti-patterns and limits *with escape hatches*.

---

## 4. Gap matrix — Aughor vs Foundry

**Where Aughor is already strong (keep investing, don't copy):**
| Plane | Aughor | Foundry equivalent |
|---|---|---|
| Deterministic answer guards | grain/fan-out, value-domain, E1, lifecycle, read-only AST (`aughor/sql/`) | **None** — evals+review only |
| NL2SQL + investigation | ask router, ADA, explorer, ground-first resolution, ambiguity ledger | AIP Analyst (shallower, no guards) |
| Trust receipts | signed public receipt + context receipt + evidence ledger | citations + audit (no unified receipt) |
| Semantic resolve-once | `semantic/context.py` SemanticContext | ontology retrieval (heavier) |
| Briefings | scheduled narrative briefs w/ trust scope | Notepad templates (manual) |
| Lean compute | DuckDB + dialect pushdown | Spark (heavy) |
| Catalog | UC-shaped metastore/volumes | Compass (proprietary) |

**Where Foundry is ahead (ranked by leverage for us):**
1. **Kinetic plane** — Actions with submission criteria + side effects; edits-as-overlay; webhook
   builder; agents write through the same gates as humans. Aughor is read-only end-to-end (ActionHub
   triggers exist but there is no declared-action substrate).
2. **Evals as a product** — suites, deterministic evaluators + LLM judge, add-run-as-test-case,
   grid experiments, sandbox simulation. We removed our bench harness (rightly — bench-only shim);
   this is the *product feature* version (`build-real-feature-not-bench-hack`). Also answers the open
   P7 model-bakeoff need with a reusable harness.
3. **Automations** — condition→effect with object/metric conditions, fallback effects, jittered
   retries, muting/expiration, staged proposals with agent decision logs. Our monitors/briefs are
   time-only and have no proposal queue.
4. **Artifact lifecycle** — save≠publish, semantic versions, changelog diffs, pin-or-follow embeds,
   live-vs-frozen badges, staleness-resolved rebuilds. Our briefings/charts/canvases have persistence
   but no version/publish semantics.
5. **Governance depth** — two-plane markings with lineage propagation + simulation, checkpoints,
   audit categories (incl. `llmInference`), usage attribution, lineage-aware deletion. Our RBAC is
   discretionary-only; audit exists but uncategorized; no tag plane; no usage attribution surface.
6. **Session/trace schema** — 9-event structured logs feeding evals. We have task_history spans but
   not a stable event schema or session→test-case flow.
7. **Typed contracts + entity pages** — module interfaces, typed embeds, next-action verbs,
   zero-config object views. Our ontology YAML has entities but no auto entity pages; embeds are ad hoc.
8. **Packaging** — packs exist (`aughor/packs/`) but there's no product packaging/install/upgrade
   story with dependency walking.
9. **Connector capability surfacing** — we *have* `db/capabilities.py`; Foundry makes the capability
   matrix the catalog UX and gates affordances on it.
10. **Change detection** — virtual-table version polling as the rebuild trigger ("re-brief only when
    the source verifiably changed") vs our staleness-days heuristic.

**What NOT to copy:** Spark-scale machinery (DuckDB + pushdown is the right lean bet) · thick on-prem
agent workers · full CBAC classification machinery · dual object-storage generations · 200-connector
breadth (depth on few beats breadth) · Slate-style arbitrary HTML apps · multi-enrollment Marketplace
machinery. Keep the *patterns*, skip the *mass*.

---

## 5. Proposed roadmap — six waves toward the all-inclusive platform

Sequenced by leverage × how much existing Aughor substrate each wave can reuse. Each wave is a
PR-arc-sized unit in the style of prior arcs (briefing arc, cockpit arc).

**Wave K — Kinetic plane (the Palantir differentiator).**
`actions:` block in the per-connection ontology YAML — name, typed parameters, rule (SQL template or
function), **submission criteria with authored failure messages** (verbatim to humans AND the LLM),
side effects (notify / webhook / trigger-investigation). One executor path reusing `govern/actions.py`
graduated autonomy + approvals. **Edits-as-overlay ledger** generalizing the ambiguity ledger from
resolutions to data annotations/corrections ("this outlier is a known event") with explicit precedence,
merged at read time, surviving refreshes. Agent tool surface becomes: scoped query + trusted queries +
declared actions — never freeform writes. Builds on: ontology/actions.py, ActionHub, approvals, RBAC.

**Wave E — Sessions + Evals (the trust flywheel).**
First: stable 9-event session schema (user_request / tool_call / tool_call_result / final_response /
execution_error …) with traceId, layered on `obs/task_history`. Then the Evals app: suites = cases ×
targets (ask / investigate / brief as callable functions) × evaluators (our deterministic guards as the
evaluator library + numeric/temporal range + LLM-judge), per-metric objectives, N-iteration variance,
run-to-run diff, **"add this run as a test case"** from any receipt/trace, and grid Experiments
(model × prompt × flags) — which finally executes the P7 frontier-model bakeoff as a product feature.
Eval SQL asserts on *executed results against a snapshot DB*, not strings.

**Wave A — Automations (condition → effect).**
Unify monitors + briefs + explorer re-arm under one engine: conditions = time OR metric/object
condition ("when metric crosses X", "when new entity appears", "when source transaction lands"),
combinable; effects = run investigation / generate brief / notify / execute declared action; fallback
effect + jittered retries + muting/pausing/expiration + per-run history. **Staged proposals queue with
agent decision log** for any autonomous write (glossary edits, ontology recommendations, fix-episodes):
agent proposes with reasoning → human accepts → applied + receipted. Change-detection triggers via
cheap source version probes (max transaction id / snapshot fingerprint) instead of staleness-days.

**Wave V — Artifact lifecycle (versions, publish, staleness).**
Save≠publish for briefings/charts/canvases: drafts for editors, published versions for viewers,
auto semantic versioning, JSON changelog diff (add/delete/change/move), one-click revert; embeds pin
a version or auto-follow. **Live-by-default + explicit "freeze" with lock icon + as-of timestamp**;
frozen artifacts whose backing data is gone error loudly. Staleness-resolved rebuilds for
profile/exploration/brief caches: rebuild only when input transaction or logic version changed, with
explicit force. Every brief/chart records the source "view" (as-of) it was computed on.

**Wave G — Governance uplift (two-plane + attribution).**
Mandatory tag plane: `tags: [pii, finance]` on connection/schema/table; user/group clearances;
`clearances ⊇ tags` checked BEFORE roles; expand-access as a separate permission from ownership.
**Tag propagation through our lineage** (evidence ledger / dossiers) to every derived artifact —
briefings inherit source tags; serve-time checks. Simulation-before-apply ("this will also restrict:
3 briefings, 2 explorations") + a Check Access panel (why can/can't user X see this). Audit category
enum on every row (`dataExport`, `llmInference`, `userJustify`, `managementPermissions`, …) with the
LLM call as a first-class event. ~5 checkpoint types (export, cross-schema query, marked-data access,
credential change, agent write) as justification middleware. Usage attribution: per-request
{tokens, cost, wall-time, rows} → {user, connection, mode} → usage-account rollup + one Analysis view.
Lineage-aware cascade invalidation on connection/dataset delete (same index: protect + purge).

**Wave S — Surface & composition (the daily-driver feel).**
Zero-config **entity pages** per ontology entity (profile + relationships + recent findings + metrics
touching it) with configured-view escape hatch. **Next-action verbs** on every answer/finding/chart
card (drill, compare period, save as metric, watch, open-in), gated by typed compatibility
(Carbon-style "Open in"). Typed briefing/canvas **module interfaces** (external-ID params settable via
URL/embed/navigation — one mechanism). "Stream LLM response into variable" as the generic agentic-UI
primitive for the Ask panel ⇄ chart/canvas state. Connector **capability matrix in the catalog UI**
gating affordances. Packs → installable *products*: outputs + auto-walked dependencies as
installer-mapped inputs, versioned, with a pre-publish linter.

**Sequencing note.** K and E are the two flanks (kinetic loop + trust flywheel) and can run as
independent arcs; A depends on K (effects execute declared actions); V and S are frontend-heavy and
pair well with ongoing briefing-arc momentum; G is orthogonal and can interleave. Suggested order:
**E → K → A → V → G → S** if trust-first, or **K → A → E → V → S → G** if product-differentiation-first.

---

## 6. Where this leaves the strategy

- **vs Databricks**: substrate parity is largely achieved for our scale (UC-shaped catalog, DuckDB
  compute + pushdown, MLflow hooks, Genie-parity answering with *stronger* guards). Remaining
  Databricks-side items (lakehouse connectors, P7 model pin) stay on the existing roadmap.
- **vs Palantir**: the gap is the kinetic loop + agent governance + artifact lifecycle — Waves K/A/E/V.
  Notably, none of it requires Spark-scale infrastructure; every wave is a lean pattern over
  substrates Aughor already has (ontology YAML, ledgers, receipts, task_history, approvals, RBAC).
- **The unique position**: Foundry has no deterministic guard plane; Databricks has no kinetic loop.
  Aughor with Waves K+E becomes the only platform whose agents are *deterministically guarded on the
  read path and governed-by-declaration on the write path* — that's the defensible "all-inclusive
  agentic AI platform" claim.

**Full per-area research digests** (feature inventories, workflows, URL indexes) live in the session
transcripts of 2026-07-22; the durable summary is this document plus the memory topic file
`foundry-full-study-2026-07-22`.
