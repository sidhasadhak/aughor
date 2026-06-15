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
- ✅ **Licensing capability gate** — `gate()` wired across actions/briefs/metrics/monitors (`3a8da8b`) and **extended** to investigations / exploration / ontology / semantic writes (25 gates), with a frontend **402 → upsell** modal that surfaces any locked capability via a one-time `fetch` interceptor (#46). Reads/deletes stay open; lands dark at the default enterprise tier.
- ✅ **Workspace data-path tenancy isolation** — every connection-tied surface (pickers, `/canvases`, `/investigations`, Recommendation Inbox, Catalog tree, **Monitors/Alerts**, and the **Home-dashboard first-load flash**) scoped to the active workspace via a fail-closed `workspace_connection_ids` gate + a derived workspace-clamped `selectedConn`; both UI + server layers (#38, #39, #41, #42, #45). An empty workspace shows none of another's data. See [FEATURES](FEATURES.md).
- ✅ **Query cancellation** + orphaned-run reconciliation (kernel).

### Adaptive Inference (2026-06-14/15)
- ✅ **Adaptive-inference research + plan** — [`docs/ADAPTIVE_INFERENCE_AND_SEMANTIC_OPERATORS.md`](docs/ADAPTIVE_INFERENCE_AND_SEMANTIC_OPERATORS.md) (#48): model cascades · prompt optimization · semantic operators — what's borrowable (and what isn't — *not* NL2SQL), plus a naming-spine consolidation of Aughor's capabilities. Main coder model set to `qwen3-coder-next:cloud` (won the golden-SQL bake-off at acceptable latency).
- ✅ **Model-cascade core — built (#49), then removed** — shipped as an opt-in cascade on hypothesis scoring + a generic Hoeffding threshold learner, then **deleted from the codebase** as not worth its weight: every accessible *cheap* proxy proved miscalibrated, so the best case was a ~15% call saving contingent on a model that doesn't exist on any reachable backend (the recall guarantee always held — the math was fine, the *models* weren't). The ~150-line core is reconstructable from git (#49) + the [plan doc](docs/ADAPTIVE_INFERENCE_AND_SEMANTIC_OPERATORS.md) Part VII if a cheap+calibrated proxy ever lands.

### UX & platform
- ✅ **Motion system** — tokens + primitives (`web/components/ui/motion.tsx`) + ~12 keyframes, rolled out to the worst offenders (`245b166`).
- ✅ **#14 UX polish** — ontology legend at top, canvas History-tab empty-state, Configure panel, Recents surface, completed-status tags, light/dark legible themes (`6f17393`, `364e117`, `3f31d33`).
- ✅ **WCH hardening** — Investigate→blank-canvas fix, sample-data honesty chain, data-shape-aware temporal planning (`419112c`, `ea4110f`, `1a10918`).

---

## 3 · What's left

Verified pending against code/git. `⬜` not started · `◑` partial.

### Commercialization / deploy
- ◑ **#12 Enterprise auth / tenancy** *(L — needs a product call)* — **Workspace data-path isolation is now comprehensive** across every connection-tied surface: connection pickers (#38), `/canvases` + `/investigations` (#39), Recommendation Inbox (#41), Catalog tree (#42), Monitors/Alerts + the Home-dashboard flash (#45) — all via the fail-closed `workspace_connection_ids` gate; an empty workspace shows none of another's data. Genuinely-remaining tenancy: connection-registry **ownership** (`/connections` is still a *shared* registry — the frontend filters it; per-tenant ownership belongs with auth), and platform **OAuth2/OIDC login + user RBAC** (still unbuilt — only connector-level OAuth exists). Shared resources (metrics catalog, action triggers, org-intelligence) are global *by design*, not leaks. The remainder needs the auth/ownership model decided first.

### Adaptive Inference (next)
- 🔨 **Semantic operators over SQL** *(M–L · product expansion · Borrow 3 · **active**)* — run LLM `filter / extract / top-k / agg` client-side over the **text** columns of a SQL result set (tickets, reviews, notes, incident write-ups — what SQL can't reason over). The remaining, highest-upside borrow: SQL push-down for the structured 99% + an LLM only on the text residue. **Cost-bounded by push-down + explicit row caps** (not a cascade — that was removed): the warehouse filters first so only a small text residue reaches the LLM, and each operator carries a surfaced row cap (never a silent truncation). See the [plan doc](docs/ADAPTIVE_INFERENCE_AND_SEMANTIC_OPERATORS.md) §4.
  - ✅ **Phase 1 — backend (`filter` + `extract`)** — `aughor/semops/` operators (value-based text-column detection + batched, fail-open LLM calls on role `fast`) + `POST /query/semantic` and `/query/semantic/text-columns` (re-run SQL server-side, then operate), gated by a new Pro `SEMANTIC_OPERATORS` capability. Unit + integration tested end-to-end through the real app.
  - ✅ **Phase 2a — ADA agent tool** — every ADA investigation phase can now attach an opt-in semantic step to a query (`PhaseQueryPlan.semantic`), applied in the shared `run_analysis_phase` executor after the SQL runs so the phase interpreter reasons over text-derived evidence. **Opt-in** (no-op unless the planner emits a step), **guarded** (skipped unless the target column actually reads as text — a misattached step never corrupts numeric evidence), and **fail-open**. The field's own description teaches the planner when to use it — no phase-prompt edits.
  - ⬜ **Phase 2b** — `top_k` + `aggregate` operators; the Query Builder "semantic step" UI affordance (the visible user-path leverage proof).
- ✅ **Model cascade — removed** — built (#49) then deleted as not worth its weight (see *Recently shipped* above and the plan doc Part VII). **The learning, kept:** every accessible *cheap* model (gemma4:31b, qwen2.5-coder:14b, command-r7b) is **miscalibrated** — self-reported confidence clusters high → ~85% escalation → only ~15% call saving; the well-calibrated models are slow/costly; the cheap+calibrated candidate is access-gated. The accuracy guarantee *always held* (recall 1.0); the blocker was always the proxy model, not the method. PR #50 (the calibration harness) closed unmerged.
- ⬜ **Prompt optimization — dropped (revisit later)** — a GEPA-style reflective optimizer was built then dropped: it **overfit** the already-strong hand-tuned `CHAT_SQL_SYSTEM` (train +0.029, held-out ~0 — the held-out gate correctly refused the fake win). The hand-built prompt is the better one. Revisit needs a larger eval set (>53 golden pairs) + held-out selection + a less-tuned target prompt.

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

### Parked ideas (2026-06-15 — discussed, not yet scheduled)
- ⬜ **Value-domain join guard ("fool-proof joins")** *(M)* — today's join safeguards (explorer study, tightened rules, ontology, Phase-8 binder, fanout de-fan, join pre-flight) all reason about column **names / types / semantics**; a wrong join still leaks when the names match but the **value domains are disjoint** (e.g. `customerID` = `C-000001234576` vs `c_id` = `cf-981923`, an unrelated entity's id). Add a **value-overlap / containment** check (primary signal; a format/charclass signature is the cheap fallback): precompute pairwise joinability at profile / ontology-build time → verified `joinable_with` edges (*prevention* — the compiler only joins along verified edges), plus a query-time pre-flight that **rejects and suggests the value-overlapping column** (*repair*) beside `detect_invalid_joins`. Normalize types before compare; MinHash/HLL at scale; degrade-not-block on legitimate zero-overlap. See memory `join-value-domain-guard`.
- ⬜ **External NL2SQL benchmarking** *(M–L)* — prove the NL2SQL harness on **external, contamination-resistant** suites beyond the internal 53-pair golden_sql (self-authored → not externally comparable): **Spider 2.0** (enterprise; Snowflake/BigQuery/SQLite, 1000+-col schemas, 100+-line SQL — brutally hard, top models ~17% EX) and **LiveSQLBench** (continuously-refreshed, memorization-proof; Postgres/SQLite). Run `generate_sql_chat` against each suite's (NL, DB, gold) triples with execution-match scoring + a per-suite dialect adapter; also report Aughor's grounded-**refusal** correctness (which the suites don't credit). Start with a SQLite subset (cheapest to run). Distinct from B-10's internal warehouse run. See memory `nl2sql-scientific-benchmarking`.

### Small polish
- ⬜ Recents **deep-link** polish (the surface itself ships) · `Scope` value-object refactor (unify per-connection onto `CanvasScope`) · profiler PK misses noted above.

### Deferred follow-ups from the 5 shipped directions
- Onboarding step-completion checklist · export live fixtures for the ADA/explore report shapes (parser handles both) · briefing dashboard saved-metric KPI tiles + server-side citation-tied figures · provider per-connection scoping + OpenAI-direct/OpenRouter backends.

---

*In progress:* **Semantic operators over SQL** — the highest-upside remaining borrow and a genuinely new capability for unstructured/text analysis. *Also available standalone:* **hypothesis-eval parallelization** (the quickest perf win — `score_evidence` runs serially today). **#12 enterprise auth** remains gated on the auth/tenancy product call.
