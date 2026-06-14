# Aughor — Roadmap & Build Status

**Product:** Aughor — Autonomous Intelligence Platform ("your warehouse, always thinking")
**Repo:** https://github.com/sidhasadhak/aughor
**Stack:** LangGraph · FastAPI (SSE) · Next.js (App Router, Turbopack) · DuckDB + PostgreSQL · SQLGlot · scipy/statsmodels · Qdrant · instructor over 5 LLM backends · uv

> **This file is the single source of truth: what we set out to build → what's built (✅) → what's left.**
> Reconciled **2026-06-14**, grounded against git history + code (not prose). The detailed
> per-feature record lives in [`FEATURES.md`](FEATURES.md), the design docs under [`docs/`](docs/),
> and the git log; this file stays at the at-a-glance altitude. Trust the verdicts here over any
> older narrative — a prior backlog had drifted (it listed the already-shipped UNIFY and #14 as pending).

---

## 1 · What we set out to build

An **autonomous data-analysis platform** that replaces the dashboard-and-analyst loop. The mandate (see [`README.md`](README.md)):

- **Connect any warehouse and explore it continuously in the background** — no prompts, no dashboards to maintain.
- **Build a living business ontology from the data** — entities, relationships, metrics, lifecycles — with no docs required.
- **Answer hard analytical questions with evidence** — citations, real numbers, and statistical confidence; "numbers you can act on," not plausible-looking ones.
- **Know *when* matters** — Adaptive Temporal Scope discovers the right window (regime, cost, sufficiency) instead of `MAX(date)`.
- **Surface intelligence at three altitudes** — Domains (raw) → Hub (structured) → Briefing (narrative) — all over one trusted substrate.
- **Be trustworthy and deployable** — deterministic correctness guards, audit/lineage, secrets at rest, capability tiers.

*No dashboards to maintain. No SQL to write. No analyst backlog.*

---

## 2 · What we've built ✅

Grouped by area; each ✅ is verified shipped (git + code). Representative commits/PRs in parentheses.

### Foundation — the Aughor Kernel
- ✅ **K0 Ledger** — one transactional state store + append-only event journal (`2631d4e`).
- ✅ **K1 Job Kernel** — supervised state machines over background work; heartbeat + crash-recovery (`82c5b4d`); investigations/monitors/briefs run as first-class jobs (`78ee842`, `cf853e1`).
- ✅ **K2/K3 Event Spine** — single lifecycle seam to the UI + lineage with Trust Receipts (`9b6b97e`).
- ✅ **K4 Contracts** — `tolerate()` error taxonomy, ratchet lints (no new silent swallows), API wiring contract (`c5d6b31`).

### Autonomous explorer & correctness
- ✅ **Phase-8 grounding gate (70→0 binder errors)** — layered deterministic pre-flight (qualify → cross-dataset guard → identifier repair → unresolved-check) with **`dry_run`/EXPLAIN as the universal binder backstop** (`4e47ce3`, `340103e`, `790da0a`, `5bfec56`).
- ✅ **Explorer yield & diversity** — deterministic **semantic column repair** (`6a923ec`), structural-duplicate gate (`d89c7b9`), spurious-join fix (entity-naming join roots, `272a30d`), angle-diversity nudge (`33a2466`), dataset-scoped per-domain context (`8505761`, `1abf5b6`).
- ✅ **Measure-additivity layer** — per-unit vs per-line grain detection + prevention/caveat/feasibility gates (`a1048d5`, `8e137de`, `4587418`, `e2f4055`).
- ✅ **Fan-out de-fan** — deterministic parent + chasm rewrites of product-of-aggregates; AVG/COUNT-over-chasm drops (`4449733`, `88c7703`, `15d8484`); core shapes covered.
- ✅ **Finding-trust ladder** — narration-inversion guard, quarantine, dismiss-with-reason, semantic-drift guards (`caa82b9`, `a0a8e24`).
- ✅ **Adaptive Temporal Scope (USP)** — Tier 0 activity-anchored window, Tier 1 regime/changepoint, Tier 2 macro+micro, Tier 3 cost governor ([`docs/ADAPTIVE_TEMPORAL_SCOPE.md`](docs/ADAPTIVE_TEMPORAL_SCOPE.md)).

### Semantic & governance layer
- ✅ **Metric unification (UNIFY)** — one registered `revenue` metric (order-grain, net-of-cancelled), the global-metric leak into foreign schemas fixed, and a **convention-neutral eval scorer** (`3c97559`).
- ✅ **B-7 metric-enforcement hard gate** + propose-to-define (`1c26189`); **B-8 metric governance** lifecycle + audit-trail UI (`9b84b81`, `c2664e6`).
- ✅ **Semantic Compiler** — typed `QueryIntent` IR + deterministic `synthesize_sql` fast-path for the safe intents.
- ✅ **Shared `analyze()` facade** over SQLGlot; AST-based product-of-aggregates detection (`32d00cc`, `15d8484`).

### Intelligence surfaces
- ✅ **Briefing → Hub → Domains** — three altitudes over one substrate; shared schema selector; citations open finding-actions ([`docs/INTELLIGENCE_UNIFICATION.md`](docs/INTELLIGENCE_UNIFICATION.md), `2296ffd`, `f5a03a5`, `102ebd3`).
- ✅ **Briefing dashboard** — live charts + KPI tiles from each finding's own query, auto chart-type, fail-safe (`7823ff1`).
- ✅ **Ontology board** — zoomable org/entity graph, legend, every profiled table an entity.
- ✅ **Trust Receipts** on every chat answer + ADA report; evidence drill-through (`b7bb66f`, `2a57290`).

### Query Builder (Superset-class)
- ✅ Visual builder (dimensions + metrics), **saved queries**, first-class **time range + grain**, **HAVING** + distinct-value filter picker, **CSV export**, **pivot** cross-tab, **chart-type gallery + Customize** (color/format/legend/axes), real **SQL editor** (highlight + format), grain-misuse warnings, "Open in Query Builder" from Insights/Deep-Analysis (the `feat(query-builder)` arc).

### Product surface (the 5 directions, 2026-06-14)
- ✅ **BeautyCommerce demo seed** (`2b8f00d`) · ✅ **Onboarding first-run funnel** (`afeb018`) · ✅ **Briefing dashboard** (`7823ff1`) · ✅ **PDF/PowerPoint export** for Insight + Deep-Analysis (`9c86cd6`, `31fd188`) · ✅ **Runtime LLM provider switching** (`d6afb28`).

### Trust, security, licensing
- ✅ **Secrets-at-rest vault** — Fernet-encrypted DSNs, trigger URLs/headers, connector tokens (`aed5640`, `af7138b`).
- ✅ **Licensing capability gate (core)** — `gate()` wired across actions/briefs/investigations/metrics/monitors (`3a8da8b`).
- ✅ **Query cancellation** + orphaned-run reconciliation (kernel).

### UX & platform
- ✅ **Motion system** — tokens + primitives (`web/components/ui/motion.tsx`) + ~12 keyframes, rolled out to the worst offenders (`245b166`).
- ✅ **#14 UX polish** — ontology legend at top, canvas History-tab empty-state, Configure panel, Recents surface, completed-status tags, light/dark legible themes (`6f17393`, `364e117`, `3f31d33`).
- ✅ **WCH hardening** — Investigate→blank-canvas fix, sample-data honesty chain, data-shape-aware temporal planning (`419112c`, `ea4110f`, `1a10918`).

---

## 3 · What's left

Verified pending against code/git. `⬜` not started · `◑` partial.

### Commercialization / deploy
- ⬜ **#12 Enterprise auth** *(L — needs a product call)* — platform **OAuth2/OIDC login + user RBAC + workspace tenancy**. Today only *connector-level* OAuth exists; no platform auth.
- ⬜ **Licensing extension** *(M — proven pattern)* — extend `gate()` to the ungated surfaces (**exploration / ontology / semantic / catalog / connections each have 0 gates today**) + a frontend `402 → upsell` flow.

### Strategic arc
- ⬜ **M12 — Org Intelligence** *(XL)* — entirely unbuilt; no `aughor/org/` package. Lineage ingestor → multi-source federation → org knowledge graph → graph-traversal tools → structural-question router. Plan in [`M12_ORG_INTELLIGENCE_ROADMAP.md`](M12_ORG_INTELLIGENCE_ROADMAP.md).
- ⬜ **Multi-connection canvas** *(M, gated on M12a federation)* — `aughor/canvas/store.py:70` still raises on `len(scopes) > 1`.

### Feature depth
- ⬜ **Query Builder Layer-3** *(M)* — reverse-compile raw SQL → semantic chips (only forward `buildSql()` exists).
- ⬜ **Hypothesis-eval parallelization** *(S–M)* — the agent graph scores hypotheses **serially** (`aughor/agent/nodes.py`, `current_hypothesis_idx += 1`); SQL-gen is already parallel.
- ◑ **FAN-b — chasm-rewrite breadth** *(M)* — parent + chasm de-fan ship and are wired (`aughor/sql/fanout.py`); the **AVG-decomposition / satellite-WHERE-splitting** edge shapes still safely bail rather than auto-rewrite.

### Infra / code health
- ⬜ **K4 follow-ups** — generated typed TS client (`web/lib/api.gen.ts` absent), domain-interface module splits, the `_phase8_domain_intelligence` god-file split, WCH-8 `.duckdb` write-coordination.
- ◑ **Profiler composite-PK detection** — single-column grain only today; composite/non-obvious keys (e.g. `invoices.order_id`) aren't detected as a grain (`aughor/tools/profiler.py`).
- ⬜ **B-10 — bigger benchmark run** *(S, compute-bound)* — the UNIFY lift run is done; the larger real-warehouse deterministic-decode run isn't recorded yet.

### Small polish
- ⬜ Recents **deep-link** polish (the surface itself ships) · `Scope` value-object refactor (unify per-connection onto `CanvasScope`) · profiler PK misses noted above.

### Deferred follow-ups from the 5 shipped directions
- Onboarding step-completion checklist · export live fixtures for the ADA/explore report shapes (parser handles both) · briefing dashboard saved-metric KPI tiles + server-side citation-tied figures · provider per-connection scoping + OpenAI-direct/OpenRouter backends.

---

*Recommended next, if sequencing by leverage:* **Licensing extension** (clean M on a proven, tested pattern — completes the commercialization story alongside B-7/B-8 governance + provider config), then **#12 enterprise auth** once the auth-provider / tenancy model is decided. **Hypothesis-eval parallelization** is the quickest standalone perf win.
