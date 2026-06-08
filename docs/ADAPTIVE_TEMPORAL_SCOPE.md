# Adaptive Temporal Scope — discovering *when matters*

**Status:** Planned (design). **Owner area:** Explorer / Domain Intelligence / Briefings.
**Replaces:** the fixed "last 12 months" window in `aughor/explorer/agent.py::_compute_time_window`.

---

## 1. The problem

Exploration (phases 5–8), Domain Intelligence, and Briefings currently scope every query to a
**fixed 12-month window** anchored on the latest *dense* timestamp across the schema
(`_compute_time_window` → `start = max_dense_date − 365 days`). This was a harness-era
simplification. The profiler is already metadata-first (DuckDB `SUMMARIZE`, Postgres `pg_stats`,
5 % sampling) and the window is already anchored on **data, not `now()`** — so two things are
already right. The naïveté is narrower but real:

- **Fixed size** — 12 months misses multi-year trend, seasonality, and regime context; and on a
  TB warehouse 12 months can itself be enormous.
- **Single resolution** — no cheap long-arc overview, no bounded deep-dive.
- **No role-awareness** — anchors on `MAX(any date column)`, so a **date-dimension / calendar
  table** whose spine runs to 2025 drags the window past the last *fact* (2023) → empty window
  → "no data / unknown" briefings. Silent and wrong. (See §3.)
- **No cost ceiling** — nothing bounds scan to warehouse size.

## 2. Principle — a "window" is the wrong primitive

"Last X" silently conflates three independent questions:

| Question | What it really asks |
|---|---|
| **Cost** | What can I afford to scan? |
| **Relevance** | What period is worth reasoning about? |
| **Sufficiency** | How much history does *this statistic at this grain* need to be meaningful? |

One magic number answers none well. **Decouple them and make each data-driven.** This is the USP:
*every BI tool makes you pick a date range (or defaults to a dumb one); Aughor discovers the
analytically-correct window from the data's own shape and tells you why — at a cost bounded by
sampling + partition pruning + incremental deltas, not by warehouse size.* **"We don't ask you
*when*; we discover *when matters*."**

---

## 3. Tier 0 — Temporal reconnaissance + ROLE-AWARENESS  *(HARD REQUIREMENT, gates everything)*

Before any analysis, learn the *shape of time* per table cheaply, and — critically — **anchor
recency on observed activity, never on the date spine.**

> **A calendar/dimension table describes *possible* time. A fact table records *observed* time.
> The "end of the business" is the cliff where activity drops to zero — and that cliff lives in
> fact tables, not the spine.**

**Recency is defined as:** the **consensus trailing edge of *activity* among measure-bearing
event tables**, sentinel-filtered — *never* `MAX(any date column)`.

### The calendar-table pitfall (worked example)
A date dimension holds one row per day through 2025 (uniformly dense, so `effective_date_range`
does **not** rescue you — its "dense region" *is* the full future span). Fact tables (sales,
orders) end 2023. Naive global-MAX anchors at 2025 → `start = 2024` → every fact filtered to
`>= 2024` → **zero rows**. Briefings conclude "no data."

### Catching signals (defense-in-depth; all available pre-ontology from `tp` / `cp` / `jmap`)
1. **Measure-bearing anchoring (primary).** Only tables with additive measures (amount/qty/
   revenue) define temporal extent. The profiler already classifies columns (`semantic_type`)
   and has `_FACT_SIGNALS`. A calendar table has **zero measures** → excluded from anchoring.
2. **Date-spine signature.** `row_count ≈ distinct(date)` **and** date is the grain/PK **and**
   columns are calendar attributes (year/quarter/dow/is_holiday) **and** density is uniform/
   contiguous **and** no measures → it's a spine; exclude from anchoring.
3. **Join-graph topology.** A date dimension is a **sink** (referenced *by* many fact tables,
   references nothing): in-degree ≫ out-degree. Anchor on the **sources** (facts).
4. **Cross-table consensus (safety net).** The real end-of-data is where multiple fact tables
   agree. Use a robust statistic (consensus / median trailing edge), **not** global MAX — one
   rogue table can't drag the window into a dead zone.
5. **Sentinel filter.** Drop `9999-12-31` / `1900-01-01` / epoch placeholders before any min/max
   (the SCD `valid_to = 9999` cousin).

### Transparency win
The discrepancy is itself a **data-quality finding**: *"your date dimension extends to 2025 but
all transaction activity stops 2023-06 — analyzing through 2023-06."* A fixed window never
surfaces this.

### Reconnaissance (metadata-first, ~zero scan)
- MIN/MAX/COUNT + a **density histogram over time** (rows per year/quarter) — from warehouse
  partition stats / `INFORMATION_SCHEMA.PARTITIONS` (zero scan) or one partition-pruned
  `GROUP BY date_trunc('year', ts)` (tiny result); `approx_quantile` for the density curve.
- Detect the **partition / clustering column** — the #1 cost lever at TB scale; align every
  window to it.
- At TB scale: **read the catalog, then sample, full-scan never.**

---

## 4. Tier 1 — Regime & window *inference* (statistical, not "last X")

From the cheap density/metric series (tiny — a few hundred points) derive `[start, end, grain]`:

- **Changepoint / regime detection** (PELT or binary segmentation via `ruptures`/`scipy` on the
  coarse series): the relevant window is "since the last structural break," not an arbitrary 12
  months. If volume 3×'d or the business pivoted in 2022, 2014–2021 pollutes the read.
- **Sufficiency constraint** — the window must hold enough periods for the grain (~≥ 24 for
  trend/seasonality). Couples to the existing `_choose_grain`: if the regime is too short for
  monthly, coarsen the grain or widen.
- **Density trimming** — drop sparse warmup + incomplete trailing periods (trailing already
  handled via `trailing_partial`).
- **Emit with a reason**: *"current regime since 2022-03 (volume +3×, structural break); monthly;
  47 periods"* — transparent and overridable.

> Tier 1 has the **same** calendar vulnerability — run it on the spine and it "detects" a uniform
> regime to 2030. Tier 0 role-awareness must run first.

## 5. Tier 2 — Multi-resolution build (answers "year-by-year vs stop at 3 years")

Don't pick *one* window — build at two resolutions:
- **Macro / context layer** — coarse rollups across the **full span** (yearly/quarterly). Cheap
  (one partition-pruned `GROUP BY year`, ~N_years rows). The long arc: secular trend, seasonality,
  regime history. *This* is "go year by year" — as cheap aggregates, not full domain intelligence
  per year.
- **Micro / focus layer** — the expensive LLM curiosity-loop + distributions + joins run **only
  over the Tier-1 active regime** (often 1–3 years, but *derived*, not fixed).
- **Briefings synthesize both**: micro as headline, macro as context — *"revenue up 4× over 8
  years but the current 2-yr regime is flattening."* A fixed window cannot produce that juxtaposition.
- Historical fine detail is **backfilled lazily / on-demand** if a question reaches back.

## 6. Tier 3 — Cost governor (so it never breaks sweat)

- **Partition pruning mandatory** (WHERE aligned to the partition col).
- **Sampling everywhere heavy** — `TABLESAMPLE`, `approx_count_distinct`, `approx_quantile`, with
  row/byte caps (extend the existing 5 % sampling).
- **Per-query bytes-scanned ceiling** — abort-and-downsample if exceeded.
- **Incremental / stateful re-exploration** — after the first build, only explore the *delta
  partitions since last run*. A Monday brief on a 10-yr warehouse scans last week, not 10 years.
  This is the real "without breaking sweat" lever for recurring briefings.

## 7. Edge cases the design must respect

- **No-timestamp tables** (reference/dimension) — no window; profile fully (small, cheap).
- **Snapshot / SCD** (`valid_to = 9999`) — as-of semantics, sentinel-filtered, not range.
- **Forecast / budget tables** — legitimately future **and** measure-bearing; distinguish by
  role/name so they aren't excluded as "future spine."
- **Scheduled-future rows in fact tables** (subscription `end_date`, planned deliveries) — anchor
  on the *event* timestamp (`order_date`), not the future-pointing one.
- **Multiple fact tables, differing spans** — per-table windows, reconciled at join time.
- **Timezones / late-arriving data** — UTC-normalize; tolerate a lag on the trailing edge.

## 8. Staging (impact-per-effort ordered)

| Stage | Scope | Why first |
|---|---|---|
| **1** | **Tier 0**: reconnaissance + **role-aware consensus recency + sentinel filter** — rewrite `_compute_time_window` (take `cp` + `jmap`, anchor on measure-bearing non-spine tables, robust consensus). | Cheapest fix; prevents the most embarrassing failure (empty-window briefings); foundational for 2–4; surfaces the calendar discrepancy as a finding. |
| **2** | **Tier 2 macro rollup layer** feeding briefing long-arc context. | Cheap; adds multi-year context immediately. |
| **3** | **Tier 1 regime/changepoint** window inference. | The statistical heart of the USP; depends on Tier 0. |
| **4** | **Tier 3 cost governor** (scan budget, partition pruning, incremental deltas). | The TB-scale hardening; matters most against a real warehouse; depends on 1–3. |

## 9. Success criteria

- Calendar-to-2025 + facts-to-2023 → window anchors **2023**, and the discrepancy is **surfaced
  as a finding**.
- The window is **derived**, shown **with a reason**, and **overridable** — never a hardcoded number.
- Scan cost is **bounded regardless of warehouse size** (sampling + partition pruning + deltas).
- Briefings carry **multi-year context** (macro) alongside a bounded recent deep-dive (micro).
