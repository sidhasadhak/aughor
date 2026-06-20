# Apache Superset — Study & Integration

**Date:** 2026-06-20 · **Branch:** `2026-06-20-superset-integration` · **Status:** 11 commits, tested, not yet PR'd

We deep-studied Apache Superset (Apache-2.0) across six subsystems and imported/adapted the
highest-leverage, correctness-and-presentation wins — while *deliberately not* porting the
patterns that turned out redundant against Aughor's existing architecture. This doc is the
durable record of **what shipped**, **what we chose not to do (and why)**, and **what's left**.

> Framing: Superset is the most battle-tested open-source BI *plumbing*; Aughor is AI-first
> *intelligence* on top of that kind of plumbing. The play was to import the hardened, unglamorous
> layers where Aughor was hand-rolling, and keep the intelligence layer as the moat — **not** to
> "become Superset."

---

## Shipped (this branch)

| Area | What | Key files | Commit |
|---|---|---|---|
| **Charts → Apache ECharts** | Replaced the Vega-Lite engine. Token-driven theme, lifecycle wrapper, **pure `transformProps`-style builders** (unit-testable), `buildAutoOption` reusing the existing `inferChartType`. | `web/components/charts/echarts/*` | `b275e2d` `086bf3f` |
| | Flipped `Chart.tsx` to ECharts (same public props — 9 consumers untouched); **removed** `vega`/`vega-lite`/`vega-embed`. | `web/components/Chart.tsx` | `3175000` `aa69c8b` |
| **Answer-card UX** | `ResultChartCard` — inline **grain-aware** control strip (Metric/Dimension/Aggregation/Display) that re-pivots in place + chart⇄table toggle, for Insight (chat) and Deep Analysis. SUM-of-a-rate is warned, not silently allowed. | `web/components/charts/ResultChartCard.tsx` | `421a902` |
| | Clean presentation: headline figures emphasized (`BriefHeadline`→`renderEmphasis`); decluttered repeated per-finding confidence bars (kept one subtle dot+label). | `web/components/brief/Brief.tsx`, `ReportView.tsx` | `749ae16` |
| **AST SQL read-only gate** | `is_mutating`/`is_destructive`/`disallowed_functions` (sqlglot AST) + CTE-safe `extract_tables`, wired into `SafetyChecker`. Blocks `lo_export()`/`setval()`/`EXPLAIN ANALYZE <dml>`/CTE-masked writes/`SELECT…INTO`/`pg_read_file()` the regex passed. Positive-detection only (defers to regex on parse failure). | `aughor/sql/readonly.py`, `aughor/sql/tables.py` | `114ec60` |
| **Per-dialect NL2SQL rules** | `writer_rules(db)` selects DuckDB rules (transpile-from-duckdb path) vs native rule blocks (BigQuery/Snowflake/MySQL/Exasol run LLM SQL verbatim). New `writes_native_sql` flag makes the two execution modes explicit. | `aughor/db/dialects.py` | `32c74da` |
| **Guard consolidation** | All three guards (explorer dataset-isolation, chat scope guard, read-only gate) now share the one tested CTE-safe `extract_tables` (hardened with a flat fallback). | `aughor/explorer/agent.py`, `routers/investigations.py` | `2d4dd2a` |
| **Post-processing operators** | Pure `(columns,rows)` transforms (pct_changes/shares/rolling/cumulative + table transforms), wired into `stats.analyze_query_result` to surface gated period-over-period + Pareto concentration to the LLM. | `aughor/tools/postproc.py` | `36582f6` |
| **Monitor anti-flap** | `grace_period_hours` + `_suppressed_by_grace` centralized in `run_monitor` — a sustained breach alerts once then reminds ≤ once/grace-window (was: every cron tick); escalations fire immediately; manual test bypasses. | `aughor/monitors/runner.py` | `339db19` |

Tests: 12 (read-only) + 9 (dialect) + 2 (guards) + 11 (post-proc) + 8 (anti-flap) new unit tests;
backend suites green, 0 regressions. Charts + ResultChartCard browser-verified in `/chart-lab`.

---

## Deliberately NOT ported (grounded findings)

- **Time-grain expression table** (Superset `db_engine_specs`) — **redundant**. Aughor's non-DuckDB
  `execute()` transpiles read=duckdb→dialect via sqlglot, which already renders `date_trunc` correctly
  (→ `TIMESTAMP_TRUNC` on BigQuery, etc. — verified empirically). The real gap was *prompt guidance for
  native warehouses*, which `dialects.py` fills instead.
- **pandas post-processing** — rewritten for Aughor's native `(columns, rows)` shape (Aughor is SQL-first,
  no pandas on results).
- **MCP server** — **deferred by decision** (high value; revisit when exposing Aughor to external LLMs).
- **LICENSE/NOTICE bureaucracy** — **deferred by decision.** Adapted files carry an inline
  "Adapted from Apache Superset (Apache-2.0)" comment; a top-level `NOTICE`/`THIRD_PARTY` entry is the
  follow-up. ⚠️ Aughor still has no top-level `LICENSE` file — add MIT before any distribution.

---

## Remaining backlog (each has a caveat — pick by appetite)

1. **Error-registry enrichment** — add Superset's per-dialect SQL-error regex patterns to
   `tools/error_classifier.py` (improves FIX_SQL self-repair + user messages). *Caveat: warehouse
   patterns need live BigQuery/Snowflake/MySQL errors to verify.*
2. **Declarative metric additivity** — an `additivity` field on `MetricDefinition`, validated by the
   existing `measure_grain` probe. *Caveat: overlaps the runtime probe; modest net gain.*
3. **DialectCaps capability flags** — per-dialect capability dataclass the SQL writer/guards consult.
   *Caveat: needs real consumers before it earns its keep.*
4. **Durable `SQLAlchemyJobStore`** for the schedulers. *Caveat: minor — `scheduler.start()` already
   reloads monitors from the persisted store on boot; only misfire-recovery is gained.*
5. **MCP server** (deferred) — expose NL2SQL / Deep Analysis / schema / metrics as MCP tools; blueprint
   in Superset's `mcp_service` (FastMCP, per-tool Pydantic schemas, layered auth, streaming progress).
6. **Reference-UX follow-ups** — opt-in "Validate" action on the chat answer (re-validate against live
   data); a lean feedback/remember action row.

**Deeper / riskier (flagged):** the transpile-vs-native execution split is inconsistent — the explorer
/ investigate prompts emit DuckDB SQL, but native warehouses run it verbatim (no transpile). Either route
all connectors through `translate()` or give the explorer native dialect rules. Needs live-warehouse testing.

---

## Source references (local clone studied: `/tmp/superset-study`)
`superset/sql/parse.py` (AST mutation + table extraction), `superset/db_engine_specs/*` (dialect-as-data),
`superset/utils/pandas_postprocessing/*` (operators), `superset/reports/*` (alert grace), `superset/mcp_service/*`
(MCP blueprint), `superset-frontend/plugins/plugin-chart-echarts/*` + `@superset-ui/*` (chart patterns).
