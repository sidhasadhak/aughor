# Explorer / Intelligence — Fix List

Consolidated from the 2026-06-23 deep-dive + the cold-start experiment. Priority order is
set by **evidence**, not intuition: a destructive cold-run on the real `workspace`/missimi
connection proved that **Phase-8 token efficiency is the dominant lever** — it dwarfs the
coverage-breadth question.

## The evidence (why this order)

A true cold start (state + findings wiped, backed up first) and a warm follow-up run:

| | Cold run | Warm run (foundation cached, prior findings as context) |
|---|---|---|
| Tokens | 208,431 | 182,356 |
| LLM calls | 58 | 53 |
| Queries executed | 5 | 7 |
| New findings | 4 | 3 |
| Outcome | **CANCELLED (200k budget)** | **CANCELLED (200k budget)** |

- **Phase 8 is the cost center, not the foundation.** Phases 3-7 ran in ~6s, ~0 tokens.
  Caching the foundation barely moved cost (208k→182k).
- **~54k tokens per finding.** ~87% of LLM calls (46 of 53) never produced an executed query —
  failed / rejected / deduped question-generation cycles (a 210s zero-yield stretch).
- **Every unsaturated run blows the budget and is cancelled** at 3-4 findings. The 136
  historical findings ≈ ~40 budget-capped runs ≈ **~7M tokens**; afterwards saturated re-runs
  are cheap (~16k, +0 findings) — the earlier "77% of tokens produce nothing" finding.
- Ground-up phased construction (L0 structure → L2 KPI) is **confirmed and working**; the defect
  is isolated to Phase 8's curiosity loop and the budget interaction.

`n=2` fresh runs — direction unambiguous; replicate before hard-coding the 54k/finding figure.

---

## Tier 0 — Operational bugs (cheap, must-fix)

1. **Budget-cancel wedge.** The `except asyncio.CancelledError` handler
   (`agent.py` `_explore_run`) saves state and re-raises but never sets a terminal phase, so the
   in-memory explorer stays at `domain_intel`; `_cleanup` (`_shared.py`) pops only the *task*.
   Result: after a budget cancel, `start` refuses `"already running"` until a manual restart.
   → Set a terminal phase on cancel **and** pop the explorer from the registry on any terminal.
2. **Per-schema vs bare-conn key mismatch.** `trigger-intel` reads `_expl_store.load(conn_id)`
   (bare `workspace`, empty) while the real run is `workspace__missimi`, so it refuses with
   "phases 3-7 not complete." → Resolve the schema key(s) like `start`/`kickoff` do.
3. **Coverage-memory decoupling.** Findings live in the ledger (durable); coverage/run-state in
   `exploration_*.json` (wiped by reset/restart). Reset loses coverage memory while findings
   persist → re-derivation. → Reconcile coverage **from the ledger findings** (source of truth).

## Tier 1 — Phase-8 token efficiency (the dominant lever, ~54k tokens/finding)

4. **Deterministic, manifest-driven question generation.** A manifest cell
   (`metric × dimension × grain`) *is* a query spec — generate the baseline SQL mechanically;
   reserve the LLM for *interpretation*, not generation. (Needs the L2 manifest, already built:
   `aughor/explorer/coverage_manifest.py`.)
5. **`dry_run`/EXPLAIN before interpretation tokens.** Catch failing/rejected SQL cheaply via the
   existing dry-run binder, before paying the full interpret round-trip.
6. **Pre-LLM dedup.** Dedup candidate questions against existing findings with a cheap
   signature/embedding check *before* the LLM call, not after (today the tokens are already spent).
7. **Trim per-call context (apply the Layer-A budget).** Each call carries ~3.4k tokens (full
   schema + all findings + negative knowledge). Send only the cell's schema slice + recent
   findings, sized to `capability.max_context` (`aughor/llm/context_budget.py`).
8. **Graceful budget landing, not a guillotine.** Make Phase 8 budget-aware: allocate the per-run
   budget across the frontier and stop cleanly (save progress, mark covered cells) instead of
   being killed mid-question.

## Tier 2 — Coverage as a measured, advancing frontier

9. **Wire the L2 manifest as the completeness denominator** (sizer shipped) — completeness =
   covered cells / manifest cells, replacing the fixed `DOMAIN_ANGLES` checklist.
10. **Each run advances the frontier** — pick the highest-value *uncovered* cells; mark each
    finding against its cell. No two runs identical.
11. **Novelty-decay → per-cell, not a global stop.**
12. **Correct skip-gate** — skip the *auto* run only when the manifest is materially covered AND
    the data fingerprint is unchanged. Manual Start always runs; data changed → re-validate + delta.

## Tier 3 — Knowledge intelligence (ground-up)

13. **Layered/dependency-ordered coverage** (L0 structure → L1 metric defs → L2 baselines → L3
    anomalies → L4 explanation); completeness per-layer, bottom-up.
14. **Anomaly → foundation descent (L4, net-new).** When a KPI moves, descend the stack
    (distribution shift? grain/mix change? lifecycle change? null-rate? broken join?) using the
    `structural_ctx` already stored on each finding.
15. **Profile-led + profiled-measure fallback** (shipped — ~70% of cells came from the fallback;
    keep it to cover the business-profile's blind spots).
16. **Time-scale awareness** — act on the YoY/seasonality/cohort axes the manifest unlocks for
    long datasets (the 5-year case).

## Tier 4 — Inference plane (shipped → integrate)

17. **Integrate branch `2026-06-23-inference-plane`** (vend_llm seam · capability UI · prefix-cache
    probe · Layer-A intake budget · overflow guard). The capability profile + Layer-A budget are
    the substrate Tier-1 #7 builds on.
18. **Per-call effort/model routing in Phase 8** — cheap tier for the (now deterministic) generation
    steps, capable tier for interpretation/synthesis.

## Tier 5 — Measurement

19. **Per-phase token attribution** — metering is per-job today; make it per-phase so efficiency is
    a live metric, not archaeology.
20. **Surface coverage % + tokens/finding** as first-class KPIs (the "advancing or spinning" signal).
