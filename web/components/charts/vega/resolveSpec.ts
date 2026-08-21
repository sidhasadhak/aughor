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
import { classifyColumns, HORIZONTAL_MAX_CATS } from "@/components/charts/columnRoles";
import { EXTENDED_TYPES, resolveExtendedForm } from "@/components/charts/vega/forms";
import { sanitizeExhibit, type ExhibitSpec } from "@/components/charts/exhibit";
import { inferChartType, HINT_TO_TYPE, type ChartType } from "@/components/charts/chartTypeInference";

/** The four post-processing ops the edit panel offers, mirroring aughor/tools/postproc.py. */
export type TransformOp = "pop" | "contribution" | "rolling" | "cumulative";

export interface TransformSpec {
  op: TransformOp;
  /** The measure being transformed. */
  valueCol: string;
  /** Trailing window for `rolling` (default 3). */
  window?: number;
  /** Aggregate for `rolling` (default mean). */
  agg?: "mean" | "sum" | "min" | "max";
}

/**
 * Build the Vega-Lite transform for one post-processing op, plus the name of the column it
 * derives. The names match aughor/tools/postproc.py EXACTLY, so a chart looks identical
 * whether the numbers were computed here or by the API.
 *
 * Why this exists: applying a transform today POSTs the entire result set to
 * /query/postproc and waits for transformed rows to come back, so choosing "cumulative" on
 * a 10k-row chart ships 10k rows over the network to compute a running total. Declared in
 * the spec, the same maths runs in the chart's own dataflow — no round trip, and the
 * transform travels WITH the spec instead of being a mutation that happened to the data
 * before the chart ever saw it.
 *
 * The edge semantics are copied deliberately, not approximated:
 *   pop         null on the first row, and where the previous value is 0 or missing
 *   contribution fraction of the non-null total; all null when that total is 0
 *   rolling     null until the window FILLS, and null if any point inside it is missing
 *   cumulative  nulls contribute 0 and the running total continues (never null)
 */
function transformBlocks(t: TransformSpec): { transform: Record<string, unknown>[]; derived: string } {
  const v = t.valueCol;
  switch (t.op) {
    case "pop": {
      const derived = `${v}_pct_change`;
      return {
        derived,
        transform: [
          { window: [{ op: "lag", field: v, as: "__prev" }] },
          { calculate: `datum.__prev === null || datum.__prev === 0 || datum['${v}'] === null ? null : (datum['${v}'] - datum.__prev) / datum.__prev`,
            as: derived },
        ],
      };
    }
    case "contribution": {
      const derived = `${v}_pct_of_total`;
      return {
        derived,
        transform: [
          { joinaggregate: [{ op: "sum", field: v, as: "__total" }] },
          { calculate: `datum.__total === 0 || datum['${v}'] === null ? null : datum['${v}'] / datum.__total`,
            as: derived },
        ],
      };
    }
    case "rolling": {
      const w = Math.max(1, t.window ?? 3);
      const agg = t.agg ?? "mean";
      const derived = `${v}_rolling_${agg}${w}`;
      return {
        derived,
        transform: [
          // `valid`, NOT `count`: Vega's count ignores its field and counts ROWS, so a window
          // holding a null still counted as full and produced a mean over the points that
          // happened to be there — 95 where the API returns null. `valid` counts non-null
          // values, which catches both edge rules at once: at the start of the series the
          // frame is short, and mid-series a missing point makes it short too.
          { window: [{ op: agg, field: v, as: "__roll" }, { op: "valid", field: v, as: "__cnt" }],
            frame: [-(w - 1), 0] },
          { calculate: `datum.__cnt < ${w} ? null : datum.__roll`, as: derived },
        ],
      };
    }
    default: {
      const derived = `${v}_cumulative`;
      // Vega's sum skips nulls and returns 0 for an empty frame, which is exactly
      // "nulls contribute 0, the running value keeps going".
      return {
        derived,
        transform: [{ window: [{ op: "sum", field: v, as: derived }], frame: [null, 0] }],
      };
    }
  }
}

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
  /** Post-processing applied IN the spec rather than to the data before it. */
  transform?: TransformSpec | null;
  /** The backend's exhibit spec — chart SEMANTICS, never data. */
  exhibit?: ExhibitSpec | Record<string, unknown> | null;
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
 *
 * ⚠ It must be declared on exactly ONE unit spec. Vega-Lite pushes a top-level param down
 * into every layer of a layered spec, and the compiled Vega then carries two signals with
 * the same name — "Duplicate signal name: picked_tuple" — which does not merely lose the
 * interaction, it fails the parse and renders NOTHING. That is what a line chart (line +
 * point layers) and a labelled bar did until this was moved onto a single layer.
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
  const { columns, rows, chartType, format, xTitle, yTitle, showLabels = false, title, orient,
          transform, exhibit: exhibitRaw } = args;
  // Fail-open on a malformed spec: a bad exhibit costs its semantics, never the chart —
  // the same contract the ECharts resolver held.
  const exhibit = sanitizeExhibit(exhibitRaw as Parameters<typeof sanitizeExhibit>[0]);
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
  // HINT_TO_TYPE collapses `pareto` to `bar` — true of the ECharts path, where a pareto WAS
  // a bar with a second axis bolted on. Here it is its own form, so it must survive the map.
  else if (HINT_TO_TYPE[hint] && hint !== "bar_horizontal" && !EXTENDED_TYPES.has(hint)) type = HINT_TO_TYPE[hint];
  // ORIENTATION IS A SHARED RULE, not a per-engine habit. resolveOption.ts renders BOTH
  // `bar` and `bar_horizontal` horizontally whenever x is categorical (a ranking reads
  // down, and category labels need the room), and vertically when x is time (a trend reads
  // across). Only `bar_vertical` forces the upright form. Encoding the same rule here is
  // what stops the Phase 2 diff from flagging every explicit `bar` as a regression.
  const bandCol = inferred ? columns[inferred.xCol] : (catCols[0] ?? dateCol);
  const isTimeX = bandCol === dateCol;
  // Density decides too: past HORIZONTAL_MAX_CATS distinct categories a lying-down ranking
  // either shrinks below legibility or needs a scrollbar, so it stands up.
  const bandCount = bandCol ? new Set(rows.map((r) => r[columns.indexOf(bandCol)])).size : 0;
  // A user override beats the rule; absent, the rule decides.
  const horizontal = orient
    ? orient === "horizontal"
    : (hint !== "bar_vertical" && !isTimeX && bandCount <= HORIZONTAL_MAX_CATS);

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
  if (!SUPPORTED.has(type) && !EXTENDED_TYPES.has(type)) return null;

  const data = { values: toRecords(columns, rows) };

  // A transform replaces the plotted measure with the column it derives, and rides on the
  // spec so it persists with the chart's intent instead of being a mutation applied to the
  // rows before the chart ever saw them.
  const tf = transform && columns.includes(transform.valueCol) ? transformBlocks(transform) : null;
  const measure = tf ? tf.derived : (inferred?.yCols?.length ? columns[inferred.yCols[0]] : numCols[0]);
  const band = inferred ? columns[inferred.xCol] : (catCols[0] ?? dateCol ?? columns[0]);
  const inferredSeries = inferred?.colorCol != null ? columns[inferred.colorCol] : undefined;
  const base: Record<string, unknown> = { $schema: "https://vega.github.io/schema/vega-lite/v6.json", data };
  if (tf) base.transform = tf.transform;
  if (title) base.title = title;

  // ---- the forms beyond the everyday six ------------------------------------------------
  if (EXTENDED_TYPES.has(type)) {
    const ext = resolveExtendedForm(type, {
      columns, rows, data, numCols, catCols, dateCol, measure, band,
      format, xTitle, yTitle, showLabels, base,
    });
    // A form that cannot be built from THIS data (a scatter with one measure, a point map
    // with no coordinates) refuses rather than approximating — the same contract as the
    // unsupported-type gate above.
    return ext ? { tier: 1, resolved: ext.resolved, defaultH: ext.defaultH,
                   xCategories: ext.xCategories, spec: ext.spec } : null;
  }

  // ---- counter — a single headline number, not a plot -----------------------------------
  if (type === "counter") {
    // A counter reads ONE number straight off the row, so it uses the real column — the
    // derived name a transform introduces exists only inside the chart's dataflow, and
    // indexOf would return -1 and quietly render 0.
    const rawMeasure = inferred?.yCols?.length ? columns[inferred.yCols[0]] : numCols[0];
    const v = Number(rows[0]?.[columns.indexOf(rawMeasure)] ?? 0);
    return {
      tier: 1, resolved: "counter", defaultH: 140, xCategories: 0,
      spec: {
        ...base,
        // The label goes through the ONE humanizer the rest of the app uses, so a counter
        // reads "Net Revenue" and not "net_revenue". The number keeps its value + format
        // rather than a pre-rendered string: `.2~s` is what the ECharts counter shows
        // (8.7M, not 8.66M), and a spec that stores the VALUE can be re-formatted later.
        data: { values: [{ v, label: yTitle ?? cleanLabel(rawMeasure) }] },
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

        // A line plus its points: the point layer is the hover target and the ≥8px marker
        // the mark spec asks for, and it keeps a single-observation series visible. Only the
        // POINTS respond to a selection — dimming the line itself would break its continuity,
        // which is the one thing a trend line exists to show.
        layer: [
          { mark: { type: "line" } },
          { mark: { type: "point", tooltip: true }, params: [SELECT_PARAM(x)],
            encoding: { opacity: SELECT_OPACITY } },
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
  const exColor = exhibitColor();
  const exOpacity = emphasisOpacity();
  const encoding: Record<string, unknown> = horizontal
    ? { x: valueEnc, y: bandEnc, opacity: exOpacity ?? SELECT_OPACITY }
    : { x: bandEnc, y: valueEnc, opacity: exOpacity ?? SELECT_OPACITY };
  if (exColor) encoding.color = exColor;

  /**
   * The exhibit grammar, as encodings. `severity` ramps the measure through the config's
   * single-hue `heatmap` range; `sign` reads the `diverging` pair through a threshold at
   * zero; `categorical` colours by a named field; `emphasis` keeps the question's subjects
   * at full strength and washes the rest. None names a colour — every one resolves through
   * a config range, which is what keeps a stored spec following the token layer.
   */
  function exhibitColor(): Record<string, unknown> | null {
    const mode = exhibit?.color?.mode;
    if (!mode || mode === "neutral") return null;
    if (mode === "sign") {
      return { field: measure, type: "quantitative",
               scale: { type: "threshold", domain: [0], range: "diverging" }, legend: null };
    }
    if (mode === "severity") {
      return { field: measure, type: "quantitative", scale: { range: "heatmap" },
               legend: exhibit?.color?.legend === "none" ? null : { title: exhibit?.color?.name ?? null } };
    }
    const field = exhibit?.color?.field;
    if (!field || !columns.includes(field)) return null;
    return { field, type: mode === "continuous" ? "quantitative" : "nominal", sort: null,
             legend: exhibit?.color?.legend === "none" ? null : { title: exhibit?.color?.name ?? null } };
  }

  /** Reference lines — context the reader otherwise supplies from memory. */
  function refLineLayers(horizontalForm: boolean): Record<string, unknown>[] {
    return (exhibit?.ref_lines ?? []).filter((l) => Number.isFinite(l?.value)).map((l) => ({
      data: { values: [{ __ref: l.value, __label: l.label ?? "" }] },
      layer: [
        { mark: { type: "rule", strokeDash: [4, 4] },
          encoding: { [horizontalForm ? "x" : "y"]: { field: "__ref", type: "quantitative" } } },
        { mark: { type: "text", align: horizontalForm ? "left" : "right",
                  dx: horizontalForm ? 4 : -4, dy: -4, fontSize: 10 },
          encoding: { [horizontalForm ? "x" : "y"]: { field: "__ref", type: "quantitative" },
                      text: { field: "__label" } } },
      ],
    }));
  }

  /** Emphasis — the question's subjects stay, everything else recedes. */
  function emphasisOpacity(): Record<string, unknown> | null {
    const subjects = (exhibit?.emphasis ?? []).filter(Boolean);
    if (!subjects.length || !band) return null;
    return { condition: { test: `indexof(${JSON.stringify(subjects)}, datum['${band}']) >= 0`, value: 1 },
             value: 0.32 };
  }

  const layers: Record<string, unknown>[] = [
    { mark: { type: "bar", tooltip: true }, params: [SELECT_PARAM(band)] },
  ];
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
    spec: (() => {
      // A reference line is its own layer with its own data, so any ref line forces the
      // layered form even where a lone bar would not have needed one.
      const all = [...layers, ...refLineLayers(horizontal)];
      return all.length > 1 ? { ...base, layer: all, encoding } : { ...base, ...all[0], encoding };
    })(),
  };
}
