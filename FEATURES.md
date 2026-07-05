# Aughor — Feature Reference

**Product:** Aughor — an autonomous, grounded data-warehouse intelligence platform.
**This document:** a tight, current map of what Aughor does, organized by capability area. The full
chronological build log (171 numbered features, sprint by sprint) is preserved verbatim in
[`docs/archive/FEATURES_full_2026-06-29.md`](docs/archive/FEATURES_full_2026-06-29.md) — consult it for
per-feature detail, history, and the technology behind each increment.

> **One-line thesis:** not a SQL copilot — an always-thinking analyst that builds a business ontology,
> explores continuously, and is engineered so *the numbers are trustworthy, not just plausible*.
> Values, in priority order: **trustworthiness > autonomy > discipline (test ratchets) > local/privacy > breadth**.

---

## 1. One conversational agent — depth chosen for you (`POST /ask`)

A single conversational entry decides **how deep to go** instead of making the user pick a mode up
front (BIRD-INTERACT-driven, arXiv 2510.05318). A **deterministic-first router** (`aughor/agent/ask_router.py`)
picks the depth — clear lookup → quick, causal/complex → deep, with no model call on the obvious cases;
the user sees a `route` receipt explaining *why* and can re-run at another depth (**auto + transparency**).
The underlying depths:

- **Quick (Insight)** — fast NL→SQL→answer with auto-charting and a plain-English headline.
- **Deep / ADA** — an autonomous investigative loop: decompose a question into hypotheses, run
  evidence-gathering SQL, synthesize, and report with a confidence verdict; resumable and crash-recoverable.
- **Explorer** — background autonomous learning: continuously probes connected warehouses to build and
  refresh the ontology, surface findings, and seed suggestions.

On top of the depths, the conversational agent (the unified-answer-path arc, PR #89):

- **Ask-vs-guess clarification** — when a question is materially ambiguous it asks **one** targeted
  question instead of guessing: deterministic under-spec + value-term detection (`aughor/agent/clarify.py`)
  **plus SOMA candidate-disagreement** (`aughor/agent/soma.py`) — generate N candidate readings, execute
  them, and ask **only when their results diverge**, with the readings' labels as grounded option chips.
- **Conversational follow-ups** — "now break that down by region / just for the ultra tier" composes on the
  prior query (`aughor/agent/followup.py` + a result digest carried across turns), on **every** path: the
  quick Insight path, AND the deep/Direct-lookup path (a follow-up in a canvas anchors on the previous turn's
  query via an origin-finding seed — kept its metric/filters/grain, extended by the new dimension).
- **Progressive escalation (ITS)** — a quick answer that's inconclusive (errored, empty on an analytical
  question, or a "why" answered by a single figure) **offers** a deeper investigation rather than leaving
  a thin answer (`aughor/agent/escalate.py`).
- **Measured discipline** — every interaction feature is gated by the interactive eval harness
  (`evals/interactive.py`, `evals/ambiguity_eval.py`, `evals/its_structural.py`): built and measured
  before it ships (the SOMA build was justified by a measured 0/6 detection gap + a 0/3→3/3 asking gain).

All depths share **one SQL-safety pipeline** (`aughor/sql/safety.py` `preflight_repair`) and **one
data-understanding context**, so quick and deep stay at parity (mode cross-pollination). `/chat` and
`/investigate` remain as back-compat shims.

## 2. Grounded NL2SQL & trust guards (the core differentiator)

Deterministic, execution-grounded guards over LLM-generated SQL — each ships with a test that proves it fires.

- **SQL self-correction** — `SqlWriter` centralizes generation + deterministic bind-error repair (no-LLM
  candidate substitution first, typed LLM repair as fallback, every candidate dry-run-validated).
- **Error classification & SQL hardening** — classify a failure by root cause, inject the right fix hint.
- **Fan-out / grain guards** — deterministic de-fan (parent + chasm), AVG-over-chasm linter, and a
  uniqueness-probe grain guard (`COUNT(*)` vs `COUNT(DISTINCT key)`) that flags over-counting on real data.
- **Value-domain join guard** — refuse/repair joins whose key domains don't actually overlap ("fool-proof joins").
- **Filter-literal binding** — a guessed enum/literal that matches no row is bound to its confirmed stored
  value (`'cancelled' → 'canceled'`), including a CHESS-style trigram value index for high-cardinality columns.
- **Measure-additivity layer** — per-unit vs per-line grain, ratio-of-sums (never AVG of per-row ratios).
- **Semantic compiler** — typed intent IR → deterministic SQL for the well-specified core.
- **Result-trust checks (CIDR-E1)** — flag function-semantics footguns (timestamp vs date-literal boundary,
  lexicographic order of numeric text, text↔numeric comparison) as labelled caveats, never overwriting the query.
- **Finding-trust ladder** — guards → quarantine → dismiss-with-reason; pre-emission insight verification;
  numeral grounding; ratio-aware cross-sectional scans; angle-feasibility + repair intent-preservation gates.
- **Grain-aware cross-section** — an **event-only** dimension (return reason/condition) is read as a
  **composition** (share of the event), never a tautological "rate by it" (which is always 100%);
  a **saturated** result (every group pinned at 0/100%) triggers a single grain-corrected reattempt; and
  discriminating **population attributes** the plan missed (a joinable table's price band / season) are
  surfaced deterministically, gated by a uniqueness probe so the added join can't fan out.
- **One canonical grain + temporal feasibility** — every lens of a "why is X high" investigation computes
  the metric at the **same unit of observation** (the metric table's grain, via a denominator-pinning plan
  directive), so the WHERE/WHY/WHEN cards can't contradict each other (per-order 40% vs per-line-item 76%);
  and the event-rate-aware **temporal-axis recovery** runs at **intake**, so a metric on a dateless child
  table still trends on the join-reachable purchase date instead of being declared non-temporal.

## 3. Evidence, trust receipts & statistical rigor

- **Statistical Evidence Engine** — significance, effect size, and direction behind every claim.
- **Evidence Ledger / Trust Receipt** — per-answer lineage: executed SQLs, input tables, which guards fired,
  earned confidence (`kernel/ledger.py`, `_write_answer_receipt`).
- **Finding Dossier** — drill-down is a *read* of captured derivation, not a second (re-)analysis.
- **Outcome tracking & feedback loop** — close the loop on whether findings were acted on.

## 4. Business intelligence layer (ontology · metrics · glossary)

- **Business ontology** — auto-built object sets + computed properties + causal graph; refreshed by the
  domain-intelligence loop; **per-schema isolated**; org-level ontology board.
- **Human-editable, version-controlled overrides** — YAML ontology with override-wins; a Phase-8 gate
  binds every per-domain block against the live schema (dry-run/EXPLAIN as the universal binder).
- **Metrics catalog** — governed metric definitions, targets & health scorecard, one unified resolver
  (`UNIFY`) shared by chat and Deep Analysis, with cross-connection leak prevention.
- **Business glossary** — manual + dbt-manifest + LLM auto-seed (override precedence), injected into context.
- **Industry-aware intelligence** — `BusinessProfile` + per-industry metric knowledge base.

## 5. Data understanding & schema intelligence

- **Profiling** — per-column stats (distinct/null/range/top-k/semantic-type), cached by schema fingerprint.
- **Join inference & fingerprinting**, **FK-neighbour expansion**, value-verified join edges + "DO NOT JOIN" hints.
- **Schema linking & compression** — trim wide schemas to the relevant tables; collapse sharded/dated table families.
- **Query-log mining** — learn real join paths, value domains, and business formulas from past queries.
- **Vector search over schema** + semantic suggestions cache (Qdrant); ER diagram; rich schema-card UI; data catalog.

## 6. Connections & data ingestion

- **Multi-database connectors** — DuckDB, Postgres, Snowflake, BigQuery, SQLite (first-class), and more;
  Fernet-encrypted DSNs, exclusive-checkout pool, health checks.
- **Add data** — new connectors, **bulk-CSV import** (with catalog-delete intelligence cascade), workspace
  file uploads (size-capped), **document ingestion** as a context layer.
- **Integrations** — dbt (manifest-driven glossary/metrics), Superset (ECharts engine + per-dialect rules).

## 7. Briefings & proactive monitors

- **Proactive monitors** + **scheduled brief delivery** on the kernel event spine (anti-flap).
- **Briefing live dashboard**, **CEO-grade triage** (impact-ranked lead, trust gate, currency),
  **interactive briefings** (interrogate the brief in place), conclusion-first design.
- **Briefing trust** — gated on governed metrics with live re-validation; multi-tier dedup; metric-explainer charts.

## 8. Query Builder

A first-class, schema-qualified query surface: bounded preview, saved queries, first-class time range &
grain (with grain-misuse warnings on metric chips), HAVING + distinct-value picker + CSV export, a real
SQL editor (highlight + format), a chart-type gallery + customize panel, pivot mode, and "open in Query
Builder" from Insights/Deep. Schema-qualified correctness; user-typed SQL is **gated** (no safety bypass).

## 9. Charts & the answer surface

- **Auto-charting** on one **Apache ECharts** engine (chat + report + explorer + query builder share it),
  with **intent-driven chart selection** — the chart follows the finding's *narrative*, not a data-shape
  guess: composition → **donut** (parts-of-a-whole) / ranked bar, trend → **line**, ranking → **sorted
  horizontal bar**, relationship → scatter; plus **100%-stacked** (composition-over-time) and
  **small-multiples** (many-group trends). One shared column-role classifier (`columnRoles.ts`) feeds both
  inference and rendering. Fixed bar thickness + count-adaptive height, on-by-default data labels with
  overlap-drop, nice-axis/headroom + apply-able customize knobs, sub-day grain axis handling. See
  `docs/CHART_SELECTION_GUIDE.md`.
- **Consistent numbers everywhere** — a backend per-column **unit hint** (`column_units`) drives one
  scale-aware formatter so a rate reads **"41.0%"** on the chart axis, the data labels, AND the key numbers
  (never "0.4" / "0.41%" / "40.96%" for the same value); a temporal peak/trough is recomputed from the full
  series so it matches the chart.
- **Source-data panel** — a **"Source data"** trigger on every finding chart (report + quick answer) opens
  a right-side drawer: the result table + the **SQL at 50%** + an **"Explore with Query Builder"** hand-off.
- **Chart source-footers** — a provenance line under every exhibit ("Source: order_items · 12,345 rows ·
  Jan–Dec 2024"), derived from the query result (input tables, row count, date range) — a chart is only as
  trustworthy as its source, made inspectable at a glance.
- **The Brief** — the answer surface with agent-reasoning quality + data-shape intelligence. **One enforced
  3-tier design layer** (tokens → primitives → composites) behind it — a `StatusChip` vocabulary, a size-only
  type scale, and a **turn renderer registry** (`registerTurnRenderer`) so a domain pack can contribute a
  custom answer surface without a frontend release (the AI-native "the agent composes its own UI" seam).
- **KPI highlight / ThoughtSpot-style scorecard**, smart report formatting + collapsible sections,
  thinking trace, **PDF / PowerPoint export**.

## 10. Semantic operators over SQL

LLM-grounded operators that compose with SQL: **filter · extract · top_k · aggregate**, hierarchical
tree-reduce synthesis, embedding-based entity dedup, a Query Builder "semantic step", and an AI-SQL operator.

## 11. RAG & knowledge

- **Prior-investigations RAG** — reuse past analyses for similar questions.
- **SQL Knowledge Base** + pattern enrichment; **structured playbook** retrieval for metric/phase planning.

## 12. Platform & infrastructure

- **Functional-plane consolidation** (Part 2 of the 2026-07-03 review, flag-gated) — the diffused agent
  runtime is being re-drawn as clean horizontal planes, each with a typed contract + a conformance test:
  a **Trust plane** (`aughor/trust:verify(sql|code|metadata, scope) → Verdict`) hoisting the ~9 scattered
  validation guards behind one façade (the read-only/mutation gate now runs on the generation path too);
  a **Capability plane** (`aughor/capability`) — one `Generate→Validate→Execute→Interpret` template
  parameterized by domain (`data` SQL + `metadata` schema-Q&A), whose `validate` *is* the Trust plane;
  and a **Semantic plane** (`aughor/semantic/context.py:resolve → SemanticContext`) that resolves
  metrics/ontology/profile/KB **once** per run instead of ad-hoc, read back by the planner. Live-verified
  end-to-end (`POST /query/capability-answer`). Each plane is a swap-point; a new capability = register one impl.
- **One noun model at the boundaries** (Part 2 Wave 3) — **`ExecutionScope`** (`aughor/canvas/scope.py`):
  the canvas/connection/schema/table-filter precedence resolved once (was hand-rolled at 4 router call
  sites; fixes a salvage/resume sibling-schema leak). **`SemanticContract`** (`aughor/semantic/contracts.py`):
  the one governed-metric type both the curated catalog and the ontology serialize to, unified via
  `SemanticContext.contracts()` (catalog wins on collision). **`answer_report`** — the deep-report SSE
  event/field renamed from the internal `ada_report` codename across every consumer (web + MCP), old name
  kept as a `@deprecated` wire alias one release; the web report type is now `AnswerReport`.
- **Job Kernel / event spine** — state machine + heartbeats + boot recovery + idempotency + scope
  cancellation; investigations, monitors & briefs run as first-class kernel jobs with crash-recovery (boot salvage).
- **Real-time SSE streaming**, **resumable investigations**, **human-in-the-loop interrupt**.
- **Two-model architecture** (coder + reasoner) with **runtime provider switching** and **provider
  resilience** (per-endpoint concurrency cap + retry/backoff/deadline); per-phase rate limiting;
  plan-then-SQL separation; non-blocking FastAPI event loop; bounded job concurrency.
- **Parallel investigation** — independent explore sub-questions run concurrently in dependency-respecting
  waves (flag `explore.parallel_subq`), and a cross-sectional Deep-Analysis runs independent lenses
  concurrently — **segment/where ∥ mechanism/why ∥ temporal/when** — for a deeper multi-angle answer at flat
  latency (flag `ada.parallel_lenses`). The WHEN lens deterministically resolves a population/order date
  (DB-probed, event-date-excluded) so a rate can be trended over time, flags a materially anomalous period, and
  forward-chains a period-scoped drill; that same axis recovery now runs at **intake**, so even the default
  single-scan path is temporal-aware (a "what drove the change" question with a join-reachable date no longer
  misroutes to cross-sectional). All rate-bearing lenses share **one canonical grain** (the metric table's unit)
  so a report can't show 40% (per order) and 76% (per line-item) for one rate. Both fan-outs run over `ContextThreadPoolExecutor` (so the metering
  accumulator + P6 budget propagate), with budget-abort, failure isolation, serial fallback and deterministic
  merge; in-phase dimension queries already run in parallel. See `docs/PARALLEL_MULTIAGENT_GROUNDWORK.md`.
- **Org / workspace tenancy** — `org_id` on every store, and (flag-gated on `AUGHOR_REQUIRE_IDENTITY`, default
  off) **enforced on the read path**: a request-identity + object-level-authz seam (`security/authz.py` — a
  `Principal`, owner-checks on by-id routes), org-scoped `list_connections` / investigation history, a pure-ASGI
  `_OrgContextMiddleware` that binds `current_org_id()` to the request, and kernel jobs that re-bind their own
  org at execution (survives restart/boot-recovery). The same `resource → connection → org` enforcement now
  covers the **monitor / alert / brief-subscription / canvas / saved-query** surfaces too — router-level
  owner-guards (403 cross-org), `org_visible_conn_ids()` list-filtering so another org's rows never surface,
  connection owner-checks on the create/digest paths, and org-binding of the **monitor + brief background
  schedulers** (a background tick stamps the connection's tenant, not `'default'`); the agent's monitor/brief
  stores stay behind a `kernel/registries/resource_org.py` resolver registry so the platform never imports them.
  **licensing tiers** (Free/Pro/Enterprise, 402 → upsell),
  **governed-intelligence MCP server**, time-to-first-insight instrumentation.
- **Role-based access control (RBAC)** — a second authorization axis orthogonal to licensing (`aughor/rbac/`,
  flag-gated on `AUGHOR_REQUIRE_IDENTITY` **and** the `RBAC_SSO` capability → localhost/non-RBAC tiers
  unchanged). A built-in role ladder **viewer ⊂ analyst ⊂ owner** over a small permission taxonomy, an
  org-scoped assignment store, and a **first-user-is-owner** bootstrap so enabling identity never locks out
  admin. Enforcement is centralized in one auditable **declarative policy table** (`rbac/policy.py`,
  `(method, route-template) → permission`) consulted by a global dependency — a viewer reads anything but
  mutates nothing anywhere, owner-only verbs (roles/settings/grants/billing) stay owner-gated — so the whole
  surface's authz lives in one place rather than 150+ scattered decorators. Roles also impose a
  **capability ceiling** (`tier_caps ∩ role_ceiling`), surfaced through `GET /capabilities` so the UI reflects
  role, not just plan. Managed from a **Settings → Access** roster (assign/revoke; `GET /rbac/me` gates the
  admin surface). Tier still gates 402; role gates 403.
- **Security perimeter** — a **fail-closed** SQL safety gate (an errored gate BLOCKS, never allows),
  Postgres opened session-read-only, an **SSRF allowlist** on outbound webhook URLs (create + send-time),
  **prompt-injection fencing** of untrusted DB content fed to the LLM, a global exception handler (no stack
  leaks), gated inference-config, and `Idempotency-Key` on create endpoints.
- **Versioned schema migrations** — a forward-only, additive `run_migrations` framework keyed on
  `PRAGMA user_version` (`db/migrations.py`); every migrating store + the kernel ledger run through it, and every
  SQLite store is tuned (WAL + `busy_timeout`) and test-isolated.

## 13. Quality bar & engineering discipline

- **Eval suite** — Braintrust investigation-quality evals + golden dataset + the Spider 2.0 NL2SQL harness,
  with a **reliability-banding protocol** (band runs, McNemar p-value, held-out split) so sub-2-pt effects
  aren't mistaken for temp-0 noise; guard-coverage reporting on real predictions.
- **Fail-graceful-by-contract** — never a 500 / hang / silent-wrong-success.
- **No silent failures** — the only legal way to swallow an exception is `tolerate()` (logged + counted +
  journaled), enforced by a test ratchet that can only go down.
- **CI gate** (`.github/workflows/ci.yml`) — pytest (`not e2e/eval`) + frontend `tsc --noEmit` on every PR,
  plus **ruff at zero and blocking** (pinned; a sane ruleset that surfaced + fixed several real latent
  `NameError`s). ~2,300 tests; the suite is fully store-isolated so it can never mutate live data.
- **Enforced frontend design layer** (Part 2 of the 2026-07-03 review) — three baseline-zero, *blocking*
  web gates, the ruff discipline applied to the UI: a **design-token gate** (`lint:tokens` — no raw radius or
  `text-[Npx]`; the scale is the source of truth), a **formatting gate** (`lint:format` — all number/date
  rendering routes through `lib/format.ts`, so the same value can't read "45.3K" in one surface and "45,300"
  in another), and a **raw-`<button>` ratchet** (`lint:elements` — the primitive layer's adoption can only
  grow). Drift is frozen by construction, not by review vigilance.
- **Verification substrate (Bet 0)** + **Specialist Agents** (Domain Expertise Packs) + ongoing audit hardening.

---

## 14. Human-command surface (AI-FDE-derived, flag-gated)

Studied Palantir Foundry's AI FDE and adopted its *human-in-command* posture as a 7-phase program
(all flag-gated + additive — default behaviour unchanged; see `docs/`):

- **Close the loop** (`AUGHOR_CLOSED_LOOP`) — captured human corrections/verdicts + trusted queries are
  read back into the planner as priors, so a corrected mistake isn't repeated (+0.70 accuracy on a repeat set).
- **Agent Context surface** (`AUGHOR_CONTEXT_SURFACE`) — the working context is an inspectable, editable
  object (typed table set + live token budget + rescope endpoint); the ContextRibbon in the answer surface.
- **Editable plan gate** (`AUGHOR_PLAN_GATE`) — deep/explore runs pause after decomposition so the user can
  review/trim the sub-question plan before the expensive fan-out (reuses the LangGraph HITL interrupt/resume).
- **Graduated approval + audit** (`AUGHOR_ACTION_APPROVAL`) — risk-graded per-action gate under the user's
  identity: high-risk mutations require approval, every action is audited to the ledger; per-scope allowlist +
  the "Action approvals" audit view in Security & Audit.
- **Declarative modes** (`AUGHOR_DECLARATIVE_MODES`) — a mode's routing/context-scope is editable YAML with a
  hardcoded fallback (`aughor/agent/modes/`).
- **Deployment budget ceiling** (`AUGHOR_MAX_TOKEN_BUDGET`) — one hard cap floors every agent's token budget.
- **Premise validation** (`AUGHOR_PREMISE_CHECK`) — a "why is X so high" investigation validates the premise
  (subject vs overall/peers) *before* explaining it, instead of assuming it — questioning the question itself.

A delta-measurement ratchet (`evals/ratchet.py`) records accuracy + tokens/run to gate each change.

---

## Frontend

Next.js / React / Tailwind (v4). Streaming investigation UI, Databricks-brand + Genie-style chat, home page,
catalog tab (3-panel + sample data), navigation redesign + command palette + ask-hero, design system v2,
activity log (with fix-and-save / fix-all), and the Data Canvas (scoped editing, list ranking, recents, rename).
An **enforced 3-tier design layer** (Part 2 of the 2026-07-03 review): design tokens (radius/type/palette,
theme-aware light/dark) → the `ui/*` primitives → the `Brief*` composite family, kept honest by three
baseline-zero blocking CI gates (tokens · formatting · raw-element ratchet) so drift can't re-accumulate.
One **`<Workspace>` shell** (header + perspective switcher + keep-alive body) that the sidebar sections are
folded onto — Intelligence, **Operations** (Monitors / Action Hub / Security & Audit), and **Data**
(Catalog / Query Builder / Semantic Layer) each render as one perspective-switched surface instead of a row
of separate full-screen tabs (deep-links preserved). A **turn renderer registry** (`TURN_RENDERERS` +
`registerTurnRenderer`) lets a pack contribute an answer surface without editing the chat god-component.

## How it fits together

A question enters one of the three modes → schema intelligence + ontology + metrics ground the context →
the LLM proposes SQL → the deterministic guard battery validates/repairs it → execution → the answer is
rendered with a chart and a trust receipt. The Explorer runs this loop continuously in the background to
keep the ontology and suggestions fresh.

## Pointers

- Full per-feature history: [`docs/archive/FEATURES_full_2026-06-29.md`](docs/archive/FEATURES_full_2026-06-29.md)
- Architecture: `docs/PLATFORM_ARCHITECTURE.md` · Roadmap: `ROADMAP.md`
- Latest repository audit: `AUDIT_2026-06-27.md`
