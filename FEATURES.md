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

## 1. Three answer modes (one shared safety pipeline)

- **Insight** — quick chat NL→SQL→answer with auto-charting and a plain-English headline.
- **Deep / ADA** — an autonomous investigative loop: decompose a question into hypotheses, run
  evidence-gathering SQL, synthesize, and report with a confidence verdict; resumable and crash-recoverable.
- **Explorer** — background autonomous learning: continuously probes connected warehouses to build and
  refresh the ontology, surface findings, and seed suggestions.

All three share **one SQL-safety pipeline** (`aughor/sql/safety.py` `preflight_repair`) and **one
data-understanding context**, so Insight and Deep stay at parity (mode cross-pollination).

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

- **Auto-charting** (Observable Plot), chat chart engine, nice-axis/headroom + apply-able customize knobs,
  full chart-type set, sub-day grain axis handling.
- **The Brief** — the answer surface with agent-reasoning quality + data-shape intelligence.
- **KPI highlight / ThoughtSpot-style scorecard**, smart report formatting + collapsible sections,
  thinking trace, **PDF / PowerPoint export**.

## 10. Semantic operators over SQL

LLM-grounded operators that compose with SQL: **filter · extract · top_k · aggregate**, hierarchical
tree-reduce synthesis, embedding-based entity dedup, a Query Builder "semantic step", and an AI-SQL operator.

## 11. RAG & knowledge

- **Prior-investigations RAG** — reuse past analyses for similar questions.
- **SQL Knowledge Base** + pattern enrichment; **structured playbook** retrieval for metric/phase planning.

## 12. Platform & infrastructure

- **Job Kernel / event spine** — state machine + heartbeats + boot recovery + idempotency + scope
  cancellation; investigations, monitors & briefs run as first-class kernel jobs with crash-recovery (boot salvage).
- **Real-time SSE streaming**, **resumable investigations**, **human-in-the-loop interrupt**.
- **Two-model architecture** (coder + reasoner) with **runtime provider switching** and **provider
  resilience** (per-endpoint concurrency cap + retry/backoff/deadline); per-phase rate limiting;
  plan-then-SQL separation; non-blocking FastAPI event loop; bounded job concurrency.
- **Org / workspace tenancy isolation** (data-path scoped), **licensing tiers** (Free/Pro/Enterprise,
  402 → upsell), **governed-intelligence MCP server**, time-to-first-insight instrumentation.

## 13. Quality bar & engineering discipline

- **Eval suite** — Braintrust investigation-quality evals + golden dataset + the Spider 2.0 NL2SQL harness,
  with a **reliability-banding protocol** (band runs, McNemar p-value, held-out split) so sub-2-pt effects
  aren't mistaken for temp-0 noise; guard-coverage reporting on real predictions.
- **Fail-graceful-by-contract** — never a 500 / hang / silent-wrong-success.
- **No silent failures** — the only legal way to swallow an exception is `tolerate()` (logged + counted +
  journaled), enforced by a test ratchet that can only go down.
- **Verification substrate (Bet 0)** + **Specialist Agents** (Domain Expertise Packs) + ongoing audit hardening.

---

## Frontend

Next.js / React / Tailwind. Streaming investigation UI, Databricks-brand + Genie-style chat, home page,
catalog tab (3-panel + sample data), navigation redesign + command palette + ask-hero, design system v2,
activity log (with fix-and-save / fix-all), and the Data Canvas (scoped editing, list ranking, recents, rename).

## How it fits together

A question enters one of the three modes → schema intelligence + ontology + metrics ground the context →
the LLM proposes SQL → the deterministic guard battery validates/repairs it → execution → the answer is
rendered with a chart and a trust receipt. The Explorer runs this loop continuously in the background to
keep the ontology and suggestions fresh.

## Pointers

- Full per-feature history: [`docs/archive/FEATURES_full_2026-06-29.md`](docs/archive/FEATURES_full_2026-06-29.md)
- Architecture: `docs/PLATFORM_ARCHITECTURE.md` · Roadmap: `ROADMAP.md`
- Latest repository audit: `AUDIT_2026-06-27.md`
