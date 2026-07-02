# Chart selection guide — the right chart for the data + the narrative

**Why this exists.** A chart is a *sentence*, not decoration: its type must match the **data shape**,
the **analytical intent** (the narrative the finding is making), and format its numbers **honestly**.
Two live misses motivated this guide: a **rate** rendered as a raw fraction ("0.4" for 40.5%), and a
**composition** (count + share) rendered as a redundant **dual-axis combo** where the line just mirrored
the bars. This is the decision framework + the ECharts levers, grounded in our engine
(`web/components/Chart.tsx` dispatch, `web/components/charts/echarts/builders.ts`,
`web/components/charts/chartTypeInference.ts`).

## 1. The three questions (in order)

1. **What is the data's shape?** — how many dimensions (categorical / temporal) and measures, and their
   cardinality and units.
2. **What is the finding saying?** — trend over time · ranking / weakness · composition (parts of a
   whole) · relationship / correlation · distribution · flow / concentration.
3. **What are the units?** — a percentage, a currency magnitude, a count, a duration. This drives axis +
   label formatting, and whether two measures can honestly share one axis.

Never pick from data shape alone. "One category + two numerics" is *not* automatically a dual-axis combo
— see §3.

## 2. Data-shape + intent → chart type

| Intent | Data shape | Chart | Notes |
|---|---|---|---|
| **Trend over time** | 1 date + 1 measure | **line** (area if a single volume series) | Time on X, chronological. |
| Trend, several series | 1 date + 1 measure + 1 group | **multi-line** | One line per group; ≤ ~6 or it's spaghetti. |
| **Ranking / weakness** | 1 category + 1 measure | **horizontal bar**, sorted | Long labels read left-aligned; largest at top. |
| **Composition (parts of a whole)** | 1 category + 1 share | **horizontal bar of the share** (or **pie/donut** for ≤5 slices) | The count and the share are the SAME story — plot ONE. |
| Composition over time | 1 date + measure + group | **stacked bar** | ≤6 stacks; a rate → 100%-stacked. |
| **Relationship** | 2 measures | **scatter** | Correlation / outliers. |
| **Two genuinely independent measures** | 1 category + 2 measures, **different units** | **dual-axis combo** (bar + line) | Only when the combo earns it — §3. |
| Same-unit measures compared | 1 category + N same-unit measures | **grouped bar** | e.g. revenue vs profit. |
| **Concentration (80/20)** | 1 category + 1 measure | **pareto** (bars + cumulative %) | Only when concentration IS the point. |
| Distribution across 2 dims | 2 categories + 1 measure | **heatmap** | |
| Nested magnitude, many parts | 1 category + 1 measure, many rows | **treemap** | |

## 3. When a dual-axis combo earns its complexity (and when it doesn't)

A dual axis (bar + line, two Y scales) is **expensive**: two scales the reader must mentally register. It
earns that cost **only** when the two measures are **genuinely independent** and can't honestly share one
axis — a **magnitude** (revenue) alongside a **rate** (margin %) over the same category.

It does **NOT** earn it when the second measure is a **transform of the first**:
- `event_count` + `pct_of_total` — the share is just the count ÷ total; the line **mirrors** the bars. → plot the **share** as a single ranked bar; the count is context (key numbers / tooltip).
- `revenue` + `revenue_share` — same. → one bar.
- A ratio's `numerator` / `denominator` are **instrumentation**, never a second series. → plot the ratio.

Our `scoreDualAxis` (`chartTypeInference.ts`) already gates combo on *different units*; the gap was that a
**derived share** looks like a different unit. Fix: **don't hand the derived measure to the chart** — the
composition lens drops `event_count` from the rendered view (`_chart_ratio_primary`) so a single-measure
bar is chosen. Same idea as excluding `numerator_total` / `denominator_total` / `n` (`INSTRUMENTATION_COL`).

## 4. Formatting rules (the number must not lie)

- **A percentage renders as `41.0%` everywhere** — axis, data labels, key numbers, prose. Detect a
  percent by an **authoritative backend unit hint** (`InvestigationFinding.column_units = {col:"percent"}`),
  not just the column name — an aliased `metric_total` (a rate) matches no name regex. The formatter is
  **scale-aware**: a fraction (`0.4096`) is ×100; an already-scaled percent (`40.96` / `pct_of_total`) is
  left. One canonical precision (1 dp) so cards never disagree.
- **Counts stay counts** (`15,612 items`) — never a percent. **Currency** carries the reporting symbol.
- **Data labels**: on for finding charts, drawn through the SAME formatter, with `labelLayout:{hideOverlap:true}`
  so crowded labels drop rather than overprint; a thin canvas-matched halo keeps them legible over a bar.

## 5. Sizing rules

- **Bar thickness is fixed** (`barMaxWidth` ≈ 34–40px) on **every** bar builder (bar, grouped, stacked,
  combo, pareto) — a 2-bar chart must not stretch into slabs.
- **Bar-chart height adapts to bar count** for horizontal bars (`nCats * band + pad`, small floor), so few
  bars → compact, many → the max viewport (then it scrolls). Vertical bars keep a value-axis height; their
  count-adaptation is `barMaxWidth` (bars stay thin, centred).

## 6. Rules implemented (2026-07-02)

- ✅ Percent unit hint end-to-end (backend `column_units` + frontend scale-aware formatter) — §4.
- ✅ Key numbers canonicalised (scale + precision + LLM `~`/duplicate collapse) across WHERE/WHY/WHEN — §4.
- ✅ `barMaxWidth` on all bar builders + count-adaptive horizontal-bar height — §5.
- ✅ Data labels default-on, one formatter, `hideOverlap`, legible halo — §4.
- ✅ Composition → single ranked share-bar, not a redundant dual-axis combo — §3.

## 7. Follow-ups (a fuller adaptive engine)

- Teach the backend to **emit `chart_type` from the finding's intent** (trend/ranking/composition/
  relationship) rather than leaning on frontend data-shape inference, so the narrative drives the type.
- A **pie/donut** for a small composition (≤5 parts) instead of a bar when parts-of-a-whole is the whole point.
- Fold the two parallel inference paths (`Chart.tsx` + `chartTypeInference.ts`) into one, per the note in
  `columnRoles.ts`.

**References.** ECharts handbook (`get-started`, API `series-bar.barMaxWidth`, `series.labelLayout`); classic
data-viz chart-selection (magnitude→bar, trend→line, parts→bar/pie, relationship→scatter).
