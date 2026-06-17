# Aughor — Roadmap & Build Status

**Product:** Aughor — Autonomous Intelligence Platform ("your warehouse, always thinking")
**Repo:** https://github.com/sidhasadhak/aughor
**Stack:** LangGraph · FastAPI (SSE) · Next.js (App Router, Turbopack) · DuckDB + PostgreSQL · SQLGlot · scipy/statsmodels · Qdrant · instructor over 5 LLM backends · uv

> **This file is the single source of truth: what we set out to build → what's built (✅) → what's left.**
> Reconciled **2026-06-17**, grounded against git history + code (not prose). The detailed
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
- ✅ **Fan-out de-fan** — deterministic parent + chasm rewrites of product-of-aggregates; AVG/COUNT/**SUM**-over-chasm drops + the **grain-mismatch-CTE** drop (two CTEs joined on only the coarser one's grain, accumulating its measure — caught a fabricated −149% margin) (`4449733`, `88c7703`, `15d8484`, branch `2026-06-17-briefing-trust-guards`); core shapes covered.
- ✅ **Value-domain join guard ("fool-proof joins")** (#65) — every prior join safeguard reasons about column **names / types / ontology**; this catches the case they can't — a join whose two keys share a name-shape but hold **value-disjoint domains** (`orders.customer_id` vs `campaigns.campaign_id`, both `VARCHAR` ids, 0% overlap). `aughor/sql/join_guard.py` samples both sides (DuckDB `USING SAMPLE` containment) and, below 15% overlap, **regenerates the query once** and adopts the rewrite only if it executes *and* clears the mismatch (never goes backwards). Wired with active repair on **all three SQL-execution surfaces** — direct (`execute_planned_queries`), ADA (`_execute_safe`), explore (`plan_and_execute_subq`); fail-open via `tolerate`. Proven live on `beautycommerce` (wrong join → correct FK → real rows). *Also fixed a latent `FIX_SQL_PROMPT.format()` `metrics_section` `KeyError` that had silently disabled ADA self-correction and could crash the explore node.*
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

### Industry-aware intelligence & briefing trust (2026-06-16/17)
- ✅ **Industry-aware `BusinessProfile`** — per-connection LLM-inferred industry/vertical + north-star metrics + key questions, grounded to real columns; resolved against a **per-industry metric KB** (`data/kb/industry/*.json` — retail/airline/saas/logistics/food-delivery/manufacturing, ~50 formula+grain+anti-pattern recipes). Drives Phase-8 angle selection and injects authoritative computation recipes (cart-to-order conversion fixed 1.36 → ~18%). `aughor/profile/` + `routers/profile.py`. *(merge `af9b95e` + branch `2026-06-17-briefing-trust-guards`)*
- ✅ **Build-time audited metric SQL** — each north-star metric carries an audited `value_sql` (KPI), `chart_sql` (trend/breakdown explainer) and each key-question a `key_question_sql`, all routed through the fan-out/grain + join-domain + range/shape guards (`aughor/profile/validate.py`) and **recipe-grounded-regenerated** when a draft fails. A **pinned key-questions pass** asks the curated questions deterministically every run so high-value findings are reproducible, not LLM-chance.
- ✅ **SQL-trust guards (new classes)** — **SUM-over-chasm** drop (the $48T-ROAS fan-out `defan()` couldn't rewrite), **grain-mismatch-CTE** drop (the −149% margin), and a **profile-declared-range degenerate gate** (drops a bounded conversion at 1.41 / 100%, exempts an unbounded ROAS at 2.3 — uses the profile's declared range, not a text guess). `aughor/sql/fanout.py`, `agent._is_degenerate_result`.
- ✅ **Three-tier finding dedup** — structural (grain+measures) → **token/semantic** (same claim, different SQL) → **embedding/paraphrase** (`aughor/semantic/finding_dedup.py`, cosine ≥ 0.85 via `nomic-embed-text`; calibrated paraphrase-dupes 0.87–0.93 drop, distinct ≤0.78 survive; fail-open).
- ✅ **Briefing overhaul** — AI synthesis top → live **Industry KPI strip** → **top-3 key-metric explainer charts** (trends/breakdowns, when-to-use mark selection) → impact-ranked **finding text cards**; redundant citation list + Domain-Coverage/Org-Intelligence sections removed. `web/components/brief/*`, `BriefingPanel.tsx`, `charts/chartTypeInference.ts`.

### Design v2 & conclusion-first Briefing (2026-06-17)
- ✅ **Design language v2 (token-first re-skin)** — additive `web/aughor-v2/` package: Tier 1 primitive **token override** (deeper surfaces, real elevation, rounded panels) imported after `styles/tokens.css` so every Tailwind/shadcn bridge + `.aug-*` class inherits via `var()`; Tier 2 `.aug-*` re-skin (gradient primary, lifted cards, pill tags, focus rings) loaded after `globals.css`; Tier 3 central Vega theming in `VegaChart.tsx` — `vegaV2Config()` merged at the one spec chokepoint + a `remapLegacyColors()` deep-walk (legacy mark hexes → `--chart-*` tokens, no per-builder edits) + a `MutationObserver` re-embedding charts on dark/light flip. *(Verified live both themes; tsc clean.)*
- ✅ **Conclusion-first Briefing** — new `VerdictHero` leads with the synthesized verdict + the top finding + proof-stat tiles (domains/findings/lead-confidence) + primary action; falls back to the deterministic top finding with no AI narrative. A `SupportingSignals` 3-up confidence-meter row from real `briefing.signals`; full prose + citations demoted to "Full synthesis". `BriefingPanel.tsx`.
- ✅ **Nav IA** — default landing is now the Briefing; **Investigations** promoted into the Intelligence nav (→ existing Recents/investigations history). `page.tsx`.
- ✅ **Section polish** — shared `components/ui/MiniStat.tsx`; real-count summary rows on Inbox / Investigations / Monitors (guarded, no fabricated stats — deliberately *no* "Tracked ARR" since recs are free-text); Query Builder `valid`/`error` SQL badge. Derived from an external "Aughor v2" mockup whose other screens (Catalog/QB/Semantic/Playbook/Health/Canvas) **already existed richer** in-app — adopted presentation, skipped fake controls.

### Query Builder (Superset-class)
- ✅ Visual builder (dimensions + metrics), **saved queries**, first-class **time range + grain**, **HAVING** + distinct-value filter picker, **CSV export**, **pivot** cross-tab, **chart-type gallery + Customize** (color/format/legend/axes), real **SQL editor** (highlight + format), grain-misuse warnings, "Open in Query Builder" from Insights/Deep-Analysis (the `feat(query-builder)` arc).

### Product surface (the 5 directions, 2026-06-14)
- ✅ **BeautyCommerce demo seed** (`2b8f00d`) · ✅ **Onboarding first-run funnel** (`afeb018`) · ✅ **Briefing dashboard** (`7823ff1`) · ✅ **PDF/PowerPoint export** for Insight + Deep-Analysis (`9c86cd6`, `31fd188`) · ✅ **Runtime LLM provider switching** (`d6afb28`).

### Trust, security, licensing
- ✅ **First-class SQLite connector** (#66) — `SQLiteConnection` (`dialect="sqlite"`, stdlib `sqlite3`) joins DuckDB/Postgres as a real backend: read-only by construction (`file:…?mode=ro`, never creates a DB for a missing path), `sqlite_master`/`PRAGMA` introspection, `EXPLAIN` validation, DuckDB→SQLite transpile, and the two-tier fast `get_schema` + heavy `build_intelligence` (profiles + ontology). Registry-wired (`FORM_FIELDS`/`DSN_PREVIEWS`, `file` category). Added public forwarders `security_pre`/`security_post` + `compute_join_map` so connectors import the public interface (private-import ratchet stays green). Built as a proper product feature — not a benchmark shim — so the agent's real path runs on the real engine (unblocks Spider 2.0-Lite's 135 SQLite DBs).
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
- ✅ **Semantic operators over SQL** *(Borrow 3 · **shipped, all phases**)* — LLM `filter / extract / top-k / aggregate` over the **text** columns of a SQL result set (tickets, reviews, notes, incident write-ups — what SQL can't reason over). The highest-upside borrow, now fully landed: SQL push-down for the structured 99% + an LLM only on the text residue. **Cost-bounded by push-down + explicit row caps** (not a cascade — that was removed): the warehouse filters first so only a small text residue reaches the LLM, and each operator carries a surfaced row cap (never a silent truncation). Both surfaces wired: the **Query Builder** (user) and the **ADA agent** (autonomous). See the [plan doc](docs/ADAPTIVE_INFERENCE_AND_SEMANTIC_OPERATORS.md) §4.
  - ✅ **Phase 1 — backend (`filter` + `extract`)** — `aughor/semops/` operators (value-based text-column detection + batched, fail-open LLM calls on role `fast`) + `POST /query/semantic` and `/query/semantic/text-columns` (re-run SQL server-side, then operate), gated by a new Pro `SEMANTIC_OPERATORS` capability. Unit + integration tested end-to-end through the real app.
  - ✅ **Phase 2a — ADA agent tool** — every ADA investigation phase can now attach an opt-in semantic step to a query (`PhaseQueryPlan.semantic`), applied in the shared `run_analysis_phase` executor after the SQL runs so the phase interpreter reasons over text-derived evidence. **Opt-in** (no-op unless the planner emits a step), **guarded** (skipped unless the target column actually reads as text — a misattached step never corrupts numeric evidence), and **fail-open**. The field's own description teaches the planner when to use it — no phase-prompt edits.
  - ✅ **Phase 2b operators** — `top_k` (rank rows by an NL criterion, keep the best *k*) + `aggregate` (synthesize many text rows → one answer) shipped across the operator core, the `apply_step` dispatcher, `POST /query/semantic`, and the ADA `SemanticStep` — same opt-in / guarded / fail-open contract as filter/extract. The four-operator set is complete.
  - ✅ **Phase 2b UI** — the Query Builder **"Semantic step"** panel under any result: pick an operator + a (client-side-detected) text column, fill the params, **Apply** → `POST /query/semantic` transforms the table in place, with surfaced notes (`8 → 6 rows`, the op note) and **Revert**. Verified end-to-end in the browser on real review data. The user path now matches the agent path.
- ✅ **Hierarchical tree-reduce synthesis** *(Borrow 4 · **shipped**)* — reusable pure map-reduce-over-context-windows primitive `aughor/llm/reduce.py` (`hierarchical_reduce` pack → summarize → recurse, depth-bounded; `partitioned_reduce` keeps groups isolated), wired into the briefing: when findings exceed the cited top-8, `_coverage_digest` folds **every** finding into a per-domain digest (tree-reduced within each domain) so the narrative reflects the whole picture instead of dropping findings 9+. **Partition-aware** (domains never blended) and **fail-open** (digest error → top-8-only prompt).
  - ✅ **Leveraged in `ada_synthesize`** — the investigation report's evidence log no longer truncates at 6 000 chars: `_phases_evidence_budgeted` keeps phases **verbatim** up to the budget (exact numbers preserved for grounding) and folds **overflow** phases into a number-preserving per-phase digest (`partitioned_reduce`) instead of dropping them. Fail-open to the old truncation; nothing-fits → truncate (never digest-only, to keep verbatim grounding). The primitive is reusable for the Hub next.
- ✅ **Embedding entity dedup — detection** *(Borrow 5a · **shipped**)* — `aughor/ontology/dedup.py`: a pure embedding self-similarity join + **connected-components** clustering (`cluster_by_similarity`, transitive) + `detect_duplicate_entities` (embeds name+description+tables via `aughor/semantic/embedder.py`, conservative 0.85 default, fail-open when embeddings are unavailable), exposed read-only at `GET /ontology/duplicate-entities` as merge **suggestions**. Detection only — it never mutates the graph, because a wrong merge would corrupt the ontology (and the SQL on it).
  - ✅ **Embedding entity dedup — merge-on-confirm (backend)** — `merge_entities` ([dedup.py](aughor/ontology/dedup.py)) is a pure, deterministic rewrite that collapses a cluster into a canonical entity and **repoints every cross-reference** — relationships (regenerated ids, self-loops dropped, deduped), interfaces' `implementing_entities`, metrics'/actions' `entity`, and the three reverse maps — then `store.apply_entity_merge` persists. Exposed at `POST /ontology/entities/merge` (gated `ONTOLOGY_EDIT`, validates ≥2 distinct + canonical-in-cluster). **Explicit + user-confirmed, never automatic.** Original graph untouched (pure).
  - ✅ **Ontology-board UI** — a **"Find duplicates"** action in the `OntologyPanel` header opens a drawer that calls `GET /ontology/duplicate-entities`, lists each near-duplicate cluster (entities + source tables + similarity), and lets the user pick which entity each cluster **merges into** (`POST /ontology/entities/merge`), then reloads the graph. Detection verified live in-browser on `beautycommerce` (clusters the three Order-* entities at 0.82). Borrow 5 fully landed.
- ⛔ **Calibrated confidence via logprobs** *(Borrow 5b · **blocked**)* — finding-trust numbers are self-reported by the LLM + clamped by a deterministic evidence-depth ceiling ([nodes.py:806](aughor/agent/nodes.py:806)); the `P(true)/(P(true)+P(false))` logprob technique can't be built because the provider layer (instructor over OpenAI-compat) doesn't expose `top_logprobs` — **the same wall that killed the cascade**. Needs a logprob-surfacing provider first.
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
- ◑ **Value-domain join guard — promote to *prevention*** *(M)* — the query-time guard + active repair shipped across all three SQL paths (#65, see *Autonomous explorer & correctness* above). The remaining, higher-leverage half is **prevention**: precompute pairwise joinability at profile / ontology-build time (which column pairs actually share values, bounded by a same-broad-type + name-affinity pre-filter to cap the O(cols²) cost) → store as verified `joinable_with` ontology edges → the compiler/planner only draws joins along verified edges, so a value-disjoint join can't be generated in the first place. Also still open: an explicit "suggest the value-overlapping column in B" repair hint (today the LLM infers it from the diagnosis), and MinHash/HLL overlap estimation for large tables (the probe currently caps at 100/1000-row samples).
- ⬜ **External NL2SQL benchmarking** *(M–L)* — prove the NL2SQL harness on **external, contamination-resistant** suites beyond the internal 53-pair golden_sql (self-authored → not externally comparable): **Spider 2.0** (enterprise; Snowflake/BigQuery/SQLite, 1000+-col schemas, 100+-line SQL — brutally hard, top models ~17% EX) and **LiveSQLBench** (continuously-refreshed, memorization-proof; Postgres/SQLite). Run `generate_sql_chat` against each suite's (NL, DB, gold) triples with execution-match scoring + a per-suite dialect adapter; also report Aughor's grounded-**refusal** correctness (which the suites don't credit). **Decided: Lite-first (broader dialects, lower bar to a first listing) then Snow (beat Genloop's official #1 @ 96.70 EX).** ✅ The **SQLite reader is now in place** (#66), so the cheapest on-ramp — the 135 local SQLite instances — runs on the real engine; remaining work is the BigQuery/Snowflake connectors + the prediction/scoring harness (a draft lives at `evals/spider2_lite.py`, scoring via Spider's own `evaluate.py --mode sql`; official submission = email to `lfy79001@gmail.com`). Distinct from B-10's internal warehouse run. See memory `nl2sql-scientific-benchmarking`.

### Small polish
- ⬜ Recents **deep-link** polish (the surface itself ships) · `Scope` value-object refactor (unify per-connection onto `CanvasScope`) · profiler PK misses noted above.

### Deferred follow-ups from the 5 shipped directions
- Onboarding step-completion checklist · export live fixtures for the ADA/explore report shapes (parser handles both) · briefing dashboard saved-metric KPI tiles + server-side citation-tied figures · provider per-connection scoping + OpenAI-direct/OpenRouter backends.

---

*Next up (after this point):* **industry-aware intelligence + briefing trust shipped** (2026-06-16/17 — BusinessProfile + per-industry metric KB, build-time audited metric SQL, the SUM-over-chasm / grain-mismatch-CTE / declared-range guards, three-tier dedup, metric-explainer briefing). Open follow-ups from it: extend the SQL-trust guards to the ADA/investigation paths, re-index the new industry KB into Qdrant for vector retrieval, stabilize `key_questions` across rebuilds, and a cross-vertical (airline) proof. Separately, the **SQLite connector shipped** (#66), clearing the engine blocker for **external NL2SQL benchmarking** (Spider 2.0-Lite, SQLite-first) — the live next step. Also remaining: promoting the value-domain join guard (#65, shipped query-time on all three SQL paths) to **prevention** (verified `joinable_with` ontology edges). The whole adaptive-inference borrow list is now worked through (semantic operators, tree-reduce, and entity dedup all shipped; only logprob-calibrated confidence is blocked, on a provider that exposes `top_logprobs`). *Also available standalone:* **hypothesis-eval parallelization** (the quickest perf win — `score_evidence` runs serially today). **#12 enterprise auth** remains gated on the auth/tenancy product call.
