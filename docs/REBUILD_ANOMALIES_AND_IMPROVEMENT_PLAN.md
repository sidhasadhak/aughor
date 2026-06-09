# From-Scratch Rebuild — Anomaly Report & Internal Improvement Plan

_Generated 2026-06-09 from a full platform reset + from-scratch rebuild watch on branch `backlog-next`._

## 1. What was done

- **Reset (reversible):** quarantined **47 derived artifacts** (exploration/episodes/knowledge JSON, schema+ontology+briefing+patterns caches, watermark/metrics, canvases/monitors/evidence/history/checkpoints/audit/artifacts/workspaces/mat-cache DBs) into `data/_reset_backup_<ts>/`. **Kept** the 6 connections, all source data (`uploads/`, source `.duckdb`), config/seeds, and the encryption key. Nothing hard-deleted.
- **Rebuild:** restarted the API on the healthy cloud-model config (`qwen3-coder-next:cloud`), triggered `POST /exploration/{id}/restart` on all 6 connections, and watched the background (status polling + filtered log capture).

## 2. Rebuild outcome (insight counts)

| Connection | Type | Result | Insights | Note |
|---|---|---|---|---|
| `989f0788` tpch (dup) | duckdb star | ✅ complete | 42 | healthy |
| `eed00c42` tpch_sf1 | duckdb star | ✅ complete | 36 | healthy |
| `f809a5c6` tpcds_sf1 | duckdb + calendar spine | ✅ complete | 30 | calendar-spine exclusion holding (item-anchored) |
| `workspace` | local_upload multi-dataset | ✅ complete | 25 | dataset-isolation holding (no cross-dataset joins) |
| `c1c664b0` beautycommerce | duckdb big-fact | ✅ complete | 18 | recovered (2→18); slow via Tier-3 approx governor on 10M-row facts |
| `9fbaa6f9` clickbench | duckdb 1 wide table | ✅ complete | 0 | single-table benchmark; all temporal cols integer-typed (Anomaly A) |

**All 6 complete, 151 insights total, zero hard errors.** Grounding-guard sanity: 0 ungrounded/degenerate/re-grounding drops anywhere — the numeral-grounding guard is **not** over-dropping.

**Aggregate anomaly volume (233 captured log lines):** 56× hallucinated-column (`Table X has no column Y`), 4× `Referenced table not found`, 4× ambiguous reference, 3× referenced-column-not-found, 2× `non-inner join on subquery` (DuckDB), 2× `USMALLINT vs DATE` (now fixed). The hallucinated-column class dominates → biggest budget reclaim is Anomaly B.

## 3. Anomaly inventory

### A. ClickBench `USMALLINT vs DATE` — date-named integer vouched as a timestamp ✅ FIXED
- **Symptom:** `Cannot compare values of type USMALLINT and type DATE` on ClickBench phase-8 queries.
- **Root cause:** `profiler.py` `primary_timestamp` selection falls back to **name-matching** (`event_date`, `*_date`, `*_at`) when no real DATE/TIMESTAMP-typed column exists — *without a type check*. ClickBench stores `EventDate`/`EventTime` as integers (USMALLINT epoch-days / BIGINT), so a date-named integer got vouched as the timestamp and compared to a date literal. Compounded by `_NUMERIC_TYPES` using `\bSMALLINT\b`, which **misses `USMALLINT`** (the `U` prefix breaks the word boundary).
- **Fix:** (1) broadened `_NUMERIC_TYPES` to cover DuckDB unsigned ints (`U?(?:TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|INT)`); (2) extracted a testable `_select_timestamp_cols()` that excludes numeric-typed columns from the name-based fallback; (3) hardened the phase-8 `time_window_block` to name only profiler-vetted timestamp columns and forbid inventing date filters elsewhere.
- **Verified:** 10 unit tests + **live** against the real ClickBench schema — all 4 date-named columns are integer-typed; `_select_timestamp_cols` now returns none → no date filter → no type error.

### B. Hallucinated columns on unanswerable questions ✅ FIXED (T1)
- **Symptom (workspace):** repeated `Table "sc" does not have a column named "region"` (4×); also `oi.item_id`, `oi.seller_id`. The dominant failure class (56 of 233 captured anomaly lines).
- **Root cause:** the phase-8 next-question generator re-proposes business questions needing a dimension the dataset doesn't have (e.g. *customers by region* on a CRM with no region), wasting an execute + 3 repair attempts each time.
- **Fix (platform-generic):** a **dead-reference memory** — `_extract_dead_refs()` harvests nonexistent column/table names from the engine's own errors (DuckDB *and* Postgres patterns), accumulated per run into `self._dead_refs`, and injected into the next-question prompt as a "NONEXISTENT NAMES — do not reference" block. Ambiguous-column errors are deliberately *not* harvested (that column exists). No schema/connection specifics — the learning is driven by the live engine. 7 unit tests.
- **Live-verified (workspace re-run on the fix):** Phase-8 fix-failures **29 → 5 (−83%)**, repeated `region` hallucinations **4 → 0**, same insight yield (25) at fewer queries. The generator stops re-proposing a nonexistent column after the first failure.

### C. SQL construction failures on hard schemas (beautycommerce) ✅ FIXED (T2)
- **Symptoms:** `Referenced table "oi" not found!` (unjoined table), `Referenced column "order_tier" not found in FROM clause`, ambiguous `item_count`, and `Cannot perform non-inner join on subquery!` (engine limit).
- **Root cause:** the attribution schema is join-heavy; the LLM references tables it forgot to join and writes outer-joins-on-subquery DuckDB rejects. The shared fixer (`_make_diagnosis`) handled *column* errors but not these classes.
- **Fix (platform-generic):** added four `_make_diagnosis` branches — (i) referenced-table-not-found → add-the-join-or-drop-the-ref (+ lists tables actually in the query); (ii) referenced-column-not-found → "select it out of the subquery / qualify it"; (iii) ambiguous-reference → qualify with alias (DuckDB *and* Postgres phrasings); (iv) non-inner-join-on-subquery → rewrite as INNER or a CTE. Because `_make_diagnosis` is shared, this lifts the **chat/ADA** repair path too. 6 unit tests. 261 unit tests green overall.

### D. Watcher self-bug (tooling) ✅ FIXED
- The first watcher counted a transient `NA` status as terminal and exited early. Fixed to treat only `complete`/`failed` as terminal and require 2 consecutive all-terminal ticks.

## 4. Internal improvement plan (from 3 architecture audits)

### 4a. Wiring & coupling — top refactors (ranked impact × commercial value)
1. **One explorer-spawn entry point.** 7 copy-pasted spawn rituals (`_shared.py:67`, `exploration.py:285/334/365/448/590/624`, `api.py:142`) with subtly different registry/cleanup. → `spawn_explorer(scope, *, mode, reset, tables_filter)`. **M.**
2. **`Scope` value object** to merge per-connection vs per-canvas duplication (6 store clones + ~12 endpoint clones, ~250 LOC). The agent already proves the `store_key` pattern (`agent.py:342`) — push it up to store + routers. **L.**
3. **De-dup `build_intelligence`** (DuckDB `connection.py:704` ≈ Postgres `~1010`, ~190 LOC, already drifting) onto the ABC. **M.**
4. **Split the 607-LOC `_phase8_domain_intelligence` god-method** into `DomainCuriosityLoop` (propose/execute-repair/interpret/ground/persist) — also lets the ADA path reuse the grounding + ratio guards. **L.**
5. **Kill the silent ontology-gate no-op** (`build_intelligence` outer `except: pass` at `connection.py:792` + agent `1273`): return `BuildResult(ok, stage, error)`, persist the failing stage into status, surface "enrichment failed: …" + Retry. **S, high value** — this is the documented "empty Hub" cause.
6. **Pause canvas explorers during investigations** (`investigations.py:1047` only touches conn explorers) — real DB-contention bug. **S.**

### 4b. DRY / reusable components (~900–1,200 LOC removable)
| Cluster | #sites | Shared component | LOC | Effort |
|---|---|---|---|---|
| Keyed JSON cache/store family (`profile_cache`, `ontology/store`, `briefing`, `patterns`, `schema_cache`, `briefs`, `watermark`, `actions`, `playbook`…) | 17+ | `KeyedJsonStore` + `JsonListStore` | 250–350 | M |
| LLM phase plan→execute→interpret blocks (`agent/investigate.py` ×7) | 7 | `run_analysis_phase(...)` | 200–280 | M |
| SQL-execution adapters (`.execute`→error-swallow→rows/scalar) | 15 | `db.rows()` / `db.scalar()` | 120–180 | M |
| Async LLM boilerplate (`run_in_executor(None, lambda: llm.complete)`) | ~6 | `await acomplete(...)` | 40–70 | S |
| `_now()`/`age_hours` time helpers (incl. an in-file double-def in `process/causal.py`) | 13 | `aughor/util/time.py` | 40 | S |
| group-insights-by-domain | 5 | `group_by_domain()` | 25 | S |

### 4c. Commercial tiering + feature flags (the "A/B/C free, D/E/F paid" ask)
- **Today:** no licensing layer; gating is ad-hoc env flags (`AUGHOR_COMPILER`, `AUGHOR_KB_ENABLED`, …) and an **unwired** `AUGHOR_API_KEY`. ~40 sellable capabilities catalogued from FEATURES.md × routers × components.
- **Proposed tiers:**
  - **Free (adopt):** connections, schema profiling/ER/catalog, NL2SQL chat (quota), query builder, auto-charting, glossary, ontology *view*, a *sample* briefing.
  - **Pro (autonomy + actionability):** autonomous exploration + domain intelligence, live Briefing/Hub, evidence ledger, monitors, scheduled briefs, action hub/push, deep analysis, metric definition, playbook, ontology/semantic *edit*, multi-canvas, Temporal Tier 0/1/2, federation.
  - **Enterprise (scale/governance/trust):** Temporal **Tier 3 cost governor**, **Semantic Compiler** (deterministic SQL), security suite (audit/PII/budgets/sandbox), eval suite, RBAC/SSO/multi-tenancy, query-cancel, full observability export.
- **Architecture (minimal blast radius):** new `aughor/licensing/` with a `Capability` enum + `Tier→capabilities` map + `has_capability(conn/workspace, cap)`; a FastAPI `require_capability(cap)` dependency returning **402** + upgrade hint; a `GET /capabilities` endpoint + a React `useCapabilities()` hook that locks/upsells UI. **Tier stored per-connection** in the existing `connection_settings.json` (runtime-flippable, no redeploy); env `AUGHOR_TIER` default `enterprise` so **today's behavior = everything on**. Fold existing env flags into the capability check incrementally. SaaS: add `tier` to `Workspace` + Stripe-webhook writer.

## 5. Status / next
- Fixes shipped this session (uncommitted, awaiting explicit "commit"): the ClickBench timestamp-typing fix (`profiler.py` + `agent.py` + `tests/unit/test_profiler_timestamp.py`). 248 unit tests green.
- Rebuild still finishing on beautycommerce/workspace/tpcds/tpch-dup (final phase). Anomalies B and C have recommended fixes ready to implement on request.
- The refactors in §4 are sequenced; #4a.5 (silent-gate → actionable error) and #4a.6 (pause canvas explorers) are the quick correctness wins; §4c is the commercial-packaging foundation.
