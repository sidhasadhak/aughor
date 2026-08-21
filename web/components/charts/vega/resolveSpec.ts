/**
 * resolveSpec.ts — TIER 1 of the control ladder: (finding data + hint + customization)
 * → a Vega-Lite spec. The Vega-side twin of resolveOption.ts, deliberately built on the
 * SAME shared primitives (classifyColumns, inferChartType) so a Phase 1 comparison shows
 * the difference between two ENGINES and not between two chart-selection systems.
 *
 * Scope is the six types the ledger says are ~99% of everything Aughor has ever charted:
 * bar, bar_horizontal, line, multi_line, counter, pie — plus the `auto` deferral, which is
 * 27.7% of persisted answers on its own.
 *
 * Pure: no React, no DOM, no theme. The theme arrives as `config` at render time, which is
 * what lets a spec be STORED and still follow today's tokens. Note what is absent: there is
 * not one function in the output. Today's ECharts path carries 43 function-valued fields,
 * which is precisely why a resolved chart cannot be persisted.
 */

import { cleanLabel } from "@/lib/format";
import { classifyColumns } from "@/components/charts/columnRoles";
import { inferChartType, HINT_TO_TYPE, type ChartType } from "@/components/charts/chartTypeInference";

export interface ResolveSpecArgs {
  columns: string[];
  rows: unknown[][];
  /** Backend hint (`bar_horizontal`, `auto`, …) or an internal ChartType. */
  chartType?: string | null;
  /** d3-format string for the quantitative axis, e.g. ",.0f" / "$,.2f" / "~s". */
  format?: string | null;
  xTitle?: string | null;
  yTitle?: string | null;
  /** Show a value label on each mark. Off by default — never a number on every point. */
  showLabels?: boolean;
  /** Chart title. Absent → no title block. */
  title?: string | null;
  /** Swap the axes of a bar form. Absent → the shared rule decides. */
  orient?: "vertical" | "horizontal" | null;
}

export interface ResolvedSpec {
  spec: Record<string, unknown>;
  defaultH: number;
  /** Which tier produced this. Tier 1 is re-resolvable from intent; 2 and 3 are verbatim. */
  tier: 1;
  /** The type actually rendered, after `auto` resolves. */
  resolved: string;
  /** Distinct categories on a VERTICAL band axis, else 0. Chart.tsx caps the width of a
   *  few-category vertical bar so three bars do not stretch across a whole panel; that cap
   *  used to read `option.xAxis.data`, which only exists on one engine. */
  xCategories: number;
}

/**
 * Click-to-select, declared once and shared by every plotted form.
 *
 * Clicking a mark keeps it at full strength and drops everything else to a wash; clicking
 * the background clears it. Because the selection is a PARAMETER of the spec rather than an
 * event handler, it costs no JavaScript, it survives being persisted, and — the part that
 * matters on a combo — a click on a bar dims the matching point on the OTHER series too,
 * since both layers read the same param. Wiring that by hand across layers is what makes
 * cross-highlighting expensive in an imperative chart library.
 *
 * `empty: true` (the default) is deliberate: with nothing selected the param matches every
 * mark, so an untouched chart renders at full opacity exactly as before.
 */
const SELECT_PARAM = (field: string) => ({
  name: "picked",
  select: { type: "point", on: "click", fields: [field], clear: "dblclick" },
});

/** Opacity, conditioned on the selection. No colour literal: the de-emphasis is a wash, not
 *  a second hue, so nothing about the theme is baked into a spec that may be stored. */
const SELECT_OPACITY = { condition: { param: "picked", value: 1 }, value: 0.28 };

/** Rows-as-arrays → rows-as-objects, the shape Vega-Lite consumes directly. */
function toRecords(columns: string[], rows: unknown[][]): Record<string, unknown>[] {
  return rows.map((r) => Object.fromEntries(columns.map((c, i) => [c, r[i]])));
}

/** The value-axis number format. `~s` (SI) is the default because warehouse measures are
 *  large and an unformatted axis reads as noise. A caller's format always wins. */
function valueFormat(format?: string | null): string {
  return format && format.trim() ? format : "~s";
}

/** Value axis: no domain line, horizontal grid. Band axis: domain line, no grid. */
function valueAxis(title: string | null | undefined, format?: string | null) {
  return {
    // An axis says what it measures. The reference labels both ("Values", "Date"); an
    // unlabelled axis makes the reader infer the measure from the title or the legend.
    // A caller-supplied title always wins; null means "use the field name".
    title: title ?? null, format: valueFormat(format),
    grid: true, domain: false,
    // tickCount belongs HERE, not in the config's axisY: on a horizontal bar the value
    // axis is X, so a count set per-orientation silently stops applying and the axis
    // grows a tick every half-unit.
    tickCount: 5,
    // Grid BEHIND the marks. Vega-Lite lifts a gridded axis above the marks by default,
    // which drew ruled lines straight through the bars.
    zindex: 0,
  };
}
function bandAxis(title: string | null | undefined) {
  return { title: title ?? null, grid: true, domain: true, zindex: 0 };
}

/** Humanised field name for an axis or legend title, via the app's one labeller. */
function axisTitle(explicit: string | null | undefined, field: string): string {
  return explicit && explicit.trim() ? explicit : cleanLabel(field);
}

/**
 * Resolve one chart. Returns null where there is no honest chart to draw — the same
 * verdict the ECharts resolver reaches, so both engines refuse the same data.
 */
export function resolveVegaSpec(args: ResolveSpecArgs): ResolvedSpec | null {
  const { columns, rows, chartType, format, xTitle, yTitle, showLabels = false, title, orient } = args;
  if (!rows?.length || !columns?.length) return null;

  const hint = String(chartType ?? "auto").toLowerCase();
  if (hint === "none") return null;

  const { dateIdxs, numericIdxs, catIdxs } = classifyColumns(columns, rows);
  const dateCol = dateIdxs.length ? columns[dateIdxs[0]] : undefined;
  const numCols = numericIdxs.map((i) => columns[i]);
  const catCols = catIdxs.map((i) => columns[i]);
  if (!numCols.length) return null;

  // `auto` defers to the ONE shared inference — the same function the ECharts path calls, and
  // it returns the COLUMNS too, so the two engines cannot disagree about what to draw either.
  // A null verdict is the ungraphable-grid gate: no honest chart, same as the ECharts resolver.
  const inferred = hint === "auto" ? inferChartType(columns, rows) : null;
  if (hint === "auto" && !inferred) return null;

  let type: string = hint;
  if (inferred) type = inferred.type as ChartType;
  else if (HINT_TO_TYPE[hint] && hint !== "bar_horizontal") type = HINT_TO_TYPE[hint];
  // ORIENTATION IS A SHARED RULE, not a per-engine habit. resolveOption.ts renders BOTH
  // `bar` and `bar_horizontal` horizontally whenever x is categorical (a ranking reads
  // down, and category labels need the room), and vertically when x is time (a trend reads
  // across). Only `bar_vertical` forces the upright form. Encoding the same rule here is
  // what stops the Phase 2 diff from flagging every explicit `bar` as a regression.
  const isTimeX = (inferred ? columns[inferred.xCol] : (catCols[0] ?? dateCol)) === dateCol;
  // A user override beats the rule; absent, the rule decides exactly as before.
  const horizontal = orient ? orient === "horizontal" : (hint !== "bar_vertical" && !isTimeX);

  /**
   * Tier 1 draws SIX types and refuses everything else.
   *
   * This gate is the difference between a fallback and a lie. Without it the function fell
   * through to its bar branch for any unknown type, so a `scatter` rendered as a bar chart:
   * a well-formed, correctly-themed, entirely wrong picture that no engine-parity screenshot
   * would flag, because both engines drew something. Refusing lets Chart.tsx fall back to
   * ECharts, which still draws scatter, heatmap, treemap, sankey and the rest correctly.
   */
  const SUPPORTED = new Set(["bar", "bar_horizontal", "bar_vertical", "line", "multi-line",
                             "multi_line", "area", "counter", "pie"]);
  if (!SUPPORTED.has(type)) return null;

  const data = { values: toRecords(columns, rows) };
  const measure = inferred?.yCols?.length ? columns[inferred.yCols[0]] : numCols[0];
  const band = inferred ? columns[inferred.xCol] : (catCols[0] ?? dateCol ?? columns[0]);
  const inferredSeries = inferred?.colorCol != null ? columns[inferred.colorCol] : undefined;
  const base: Record<string, unknown> = { $schema: "https://vega.github.io/schema/vega-lite/v6.json", data };
  if (title) base.title = title;

  // ---- counter — a single headline number, not a plot -----------------------------------
  if (type === "counter") {
    const v = Number(rows[0]?.[columns.indexOf(measure)] ?? 0);
    return {
      tier: 1, resolved: "counter", defaultH: 140, xCategories: 0,
      spec: {
        ...base,
        // The label goes through the ONE humanizer the rest of the app uses, so a counter
        // reads "Net Revenue" and not "net_revenue". The number keeps its value + format
        // rather than a pre-rendered string: `.2~s` is what the ECharts counter shows
        // (8.7M, not 8.66M), and a spec that stores the VALUE can be re-formatted later.
        data: { values: [{ v, label: yTitle ?? cleanLabel(measure) }] },
        layer: [
          { mark: { type: "text", fontSize: 38, fontWeight: 600, dy: -8, align: "center", baseline: "middle" },
            encoding: { text: { field: "v", type: "quantitative", format: format?.trim() || ".2~s" } } },
          { mark: { type: "text", fontSize: 11, dy: 26, align: "center", baseline: "middle", opacity: 0.72 },
            encoding: { text: { field: "label", type: "nominal" } } },
        ],
        encoding: { x: { value: { expr: "width/2" } }, y: { value: { expr: "height/2" } } },
      },
    };
  }

  // ---- pie ------------------------------------------------------------------------------
  if (type === "pie") {
    // A DONUT, matching the house form the ECharts path already renders — a hole is not a
    // decoration here, it is what the product's pies look like. Vega-Lite takes an absolute
    // radius, so it is derived from the chart's own height rather than a percentage.
    const pieH = 300;
    return {
      tier: 1, resolved: "pie", defaultH: pieH, xCategories: 0,
      spec: {
        ...base,
        mark: { type: "arc", innerRadius: Math.round(pieH * 0.28), tooltip: true },
        encoding: {
          theta: { field: measure, type: "quantitative", stack: true },
          color: { field: band, type: "nominal", sort: null, legend: { orient: "right", direction: "vertical" } },
          order: { field: measure, type: "quantitative", sort: "descending" },
        },
      },
    };
  }

  // ---- line / multi-line ----------------------------------------------------------------
  if (type === "line" || type === "multi-line" || type === "multi_line" || type === "area") {
    // A trend's x is the DATE when there is one. `band` leads with the first CATEGORY,
    // which is right for a bar and wrong here: on a month × region × revenue table it put
    // region on the x-axis, left no column for the series encoding, and drew a single line
    // zig-zagging through all 32 points with no legend. When inference ran it already chose
    // the column, so only the explicit-hint path needs the date preference.
    const x = inferred ? band : (dateCol ?? band);
    const xIsDate = x === dateCol;
    // A series column (multi-line) or a single measure (line).
    const seriesCol = inferredSeries ?? (type.startsWith("multi") ? catCols.find((c) => c !== x) : undefined);
    const enc: Record<string, unknown> = {
      x: {
        field: x,
        type: xIsDate ? "temporal" : "ordinal",
        // A month label without its year is ambiguous the moment a series crosses a year
        // boundary. Vega-Lite's temporal default drops the year; ECharts keeps it.
        axis: { ...bandAxis(axisTitle(xTitle, x)), ...(xIsDate ? { format: "%b %Y" } : {}) },
      },
      y: { field: measure, type: "quantitative", axis: valueAxis(axisTitle(yTitle, measure), format) },
    };
    // `sort: null` keeps the series in DATA order. Vega-Lite sorts a nominal domain
    // alphabetically by default, which hands the same series a different hue than the
    // ECharts path gives it — every screenshot in the Phase 2 diff would flag.
    if (seriesCol) enc.color = { field: seriesCol, type: "nominal", sort: null };
    return {
      tier: 1, resolved: seriesCol ? "multi-line" : "line", defaultH: 300, xCategories: 0,
      spec: {
        ...base,
        params: [SELECT_PARAM(x)],
        // A line plus its points: the point layer is the hover target and the ≥8px marker
        // the mark spec asks for, and it keeps a single-observation series visible. Only the
        // POINTS respond to a selection — dimming the line itself would break its continuity,
        // which is the one thing a trend line exists to show.
        layer: [
          { mark: { type: "line" } },
          { mark: { type: "point", tooltip: true }, encoding: { opacity: SELECT_OPACITY } },
        ],
        encoding: enc,
      },
    };
  }

  // ---- bar (vertical and horizontal) ----------------------------------------------------
  const valueEnc = { field: measure, type: "quantitative",
                     axis: valueAxis(axisTitle(horizontal ? xTitle : yTitle, measure), format) };
  const bandEnc = {
    field: band,
    type: (dateCol === band ? "temporal" : "nominal") as string,
    axis: bandAxis(axisTitle(horizontal ? yTitle : xTitle, band)),
    // Lead with the largest — the ranking the question implies. Ties break stably.
    sort: horizontal ? { field: measure, order: "descending" } : null,
  };
  // opacity belongs in the SHARED encoding, not on a layer: the object below is spread over
  // the spec AFTER any layer's own encoding, so a selection declared on the layer was being
  // silently overwritten — the param compiled, the click registered, and nothing dimmed.
  const encoding: Record<string, unknown> = horizontal
    ? { x: valueEnc, y: bandEnc, opacity: SELECT_OPACITY }
    : { x: bandEnc, y: valueEnc, opacity: SELECT_OPACITY };

  const layers: Record<string, unknown>[] = [{ mark: { type: "bar", tooltip: true } }];
  if (showLabels) {
    layers.push({
      mark: { type: "text", align: horizontal ? "left" : "center", baseline: "middle",
              dx: horizontal ? 5 : 0, dy: horizontal ? 0 : -8 },
      encoding: { text: { field: measure, type: "quantitative", format: valueFormat(format) } },
    });
  }

  return {
    tier: 1,
    resolved: horizontal ? "bar_horizontal" : "bar",
    xCategories: horizontal ? 0 : new Set(rows.map((r) => r[columns.indexOf(band)])).size,
    // A horizontal bar needs room per category, not a fixed canvas.
    defaultH: horizontal ? Math.max(180, Math.min(560, rows.length * 30 + 60)) : 300,
    spec: {
      ...base,
      params: [SELECT_PARAM(band)],
      ...(layers.length > 1 ? { layer: layers } : layers[0]),
      encoding,
    },
  };
}
