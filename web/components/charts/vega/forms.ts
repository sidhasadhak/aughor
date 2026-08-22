/**
 * forms.ts — the chart forms beyond the everyday six, as Vega-Lite.
 *
 * Phase 5b/5c. These are the types the ECharts builders drew that Vega-Lite can express
 * natively, plus the two geographic ones. Each is an ENCODING, not a hand-authored spec —
 * that is precisely why they belong at tier 1 and not tier 3.
 *
 * The rules from tier 1 hold without exception:
 *   - no colour literal. Sign colouring reads the config's `diverging` range and a magnitude
 *     ramp reads `heatmap`, so a spec can say "colour by sign" without naming a colour.
 *   - pure JSON. Statistics that were hand-rolled in TypeScript (histogram bins, boxplot
 *     quartiles, waterfall running totals, Pareto cumulative share) are declared as
 *     transforms and computed by the chart, which is the whole argument for the grammar.
 */

import { cleanLabel } from "@/lib/format";

export interface FormCtx {
  columns: string[];
  rows: unknown[][];
  data: { values: Record<string, unknown>[] };
  numCols: string[];
  catCols: string[];
  dateCol?: string;
  measure: string;
  band: string;
  format?: string | null;
  xTitle?: string | null;
  yTitle?: string | null;
  showLabels: boolean;
  base: Record<string, unknown>;
  /** Sanitised exhibit — the forms that can honour it read it from here. */
  exhibit?: {
    label_points?: boolean | null;
    quadrant?: { x?: number | null; y?: number | null } | null;
  } | null;
}

export interface FormResult {
  spec: Record<string, unknown>;
  defaultH: number;
  resolved: string;
  xCategories: number;
}

/** Types this module draws. Everything else falls through to the everyday six. */
export const EXTENDED_TYPES = new Set([
  "scatter", "heatmap", "matrix", "histogram", "boxplot",
  "stacked-bar", "stacked_bar", "grouped-bar", "grouped_bar",
  "small-multiples", "small_multiples", "delta-bar", "delta_bar",
  "waterfall", "pareto", "line-forecast", "line_forecast",
  "choropleth", "point-map", "point_map",
]);

const fmt = (f?: string | null) => (f && f.trim() ? f : "~s");
const title = (explicit: string | null | undefined, field: string) =>
  explicit && explicit.trim() ? explicit : cleanLabel(field);

const valueAxis = (t: string, f?: string | null) =>
  ({ title: t, format: fmt(f), grid: true, domain: false, tickCount: 5, zindex: 0 });
const bandAxis = (t: string) => ({ title: t, grid: true, domain: true, zindex: 0 });

/** The base map, as a layer. Its colours come from the config's `geoshape` mark. */
const WORLD = { url: "/geo/world.json", format: { property: "features" } };
const PROJECTION = { type: "equalEarth" };

/** A column whose name looks like a latitude / longitude / place. */
const LAT = /(^|_)(lat|latitude)$/i;
const LON = /(^|_)(lon|lng|long|longitude)$/i;

export function resolveExtendedForm(type: string, c: FormCtx): FormResult | null {
  const { columns, rows, data, numCols, catCols, dateCol, measure, base, exhibit: ex } = c;
  const yT = title(c.yTitle, measure);

  switch (type) {
    // ── relation ───────────────────────────────────────────────────────────
    case "scatter": {
      if (numCols.length < 2) return null;
      const [x, y] = numCols;
      const enc: Record<string, unknown> = {
        x: { field: x, type: "quantitative", axis: valueAxis(title(c.xTitle, x), c.format) },
        y: { field: y, type: "quantitative", axis: valueAxis(title(c.yTitle, y), c.format) },
      };
      if (catCols.length) enc.color = { field: catCols[0], type: "nominal", sort: null };

      // `label_points` puts the entity's name beside its dot — outlier IDENTITY, which is
      // the whole reason a scatter is drawn. `quadrant` adds the mean/median dividers that
      // turn a cloud into four readable regions. Both are exhibit semantics, and without
      // them a "rich" scatter was byte-identical to a plain one.
      const label = c.columns.find((n) => n !== x && n !== y && !c.numCols.includes(n));
      const layers: Record<string, unknown>[] = [{ mark: { type: "point", tooltip: true } }];
      if (ex?.label_points && label) {
        layers.push({
          mark: { type: "text", align: "left", dx: 6, dy: -4, fontSize: 10 },
          encoding: { text: { field: label, type: "nominal" } },
        });
      }
      const q = ex?.quadrant;
      if (q && Number.isFinite(q.x)) {
        layers.push({ data: { values: [{ __q: q.x }] }, mark: { type: "rule", strokeDash: [4, 4] },
                      encoding: { x: { field: "__q", type: "quantitative" } } });
      }
      if (q && Number.isFinite(q.y)) {
        layers.push({ data: { values: [{ __q: q.y }] }, mark: { type: "rule", strokeDash: [4, 4] },
                      encoding: { y: { field: "__q", type: "quantitative" } } });
      }
      return { resolved: "scatter", defaultH: 340, xCategories: 0,
               spec: layers.length > 1
                 ? { ...base, layer: layers, encoding: enc }
                 : { ...base, ...layers[0], encoding: enc } };
    }

    // ── two dimensions and a magnitude ─────────────────────────────────────
    case "heatmap":
    case "matrix": {
      // A second dimension often LOOKS numeric — an hour of "09", a week number, a year.
      // classifyColumns calls those measures, so a heatmap that clearly has two dimensions
      // and a value would refuse itself. Fall back to "any column that is not the measure".
      const dims = catCols.length >= 2 ? catCols : columns.filter((n) => n !== measure);
      if (dims.length < 2) return null;
      const [x, y] = dims;
      return {
        resolved: "heatmap", defaultH: Math.max(240, new Set(rows.map((r) => r[columns.indexOf(y)])).size * 26 + 60),
        xCategories: 0,
        spec: {
          ...base,
          mark: { type: "rect", tooltip: true },
          encoding: {
            x: { field: x, type: "nominal", axis: bandAxis(title(c.xTitle, x)) },
            y: { field: y, type: "nominal", axis: bandAxis(title(null, y)) },
            // A magnitude is a single-hue ramp, never a rainbow. `heatmap` is the config's.
            color: { field: measure, type: "quantitative", scale: { range: "heatmap" },
                     legend: { title: yT, format: fmt(c.format) } },
          },
        },
      };
    }

    // ── distribution ───────────────────────────────────────────────────────
    case "histogram": {
      if (!numCols.length) return null;
      const v = numCols[0];
      return {
        resolved: "histogram", defaultH: 300, xCategories: 0,
        spec: {
          ...base,
          mark: { type: "bar", tooltip: true },
          encoding: {
            // Binning was hand-rolled in the builders. Here it is one word.
            x: { field: v, type: "quantitative", bin: { maxbins: 30 }, axis: bandAxis(title(c.xTitle, v)) },
            y: { aggregate: "count", type: "quantitative", axis: valueAxis("Count", ",.0f") },
          },
        },
      };
    }

    case "boxplot": {
      if (!numCols.length) return null;
      const v = numCols[0];
      const enc: Record<string, unknown> = {
        y: { field: v, type: "quantitative", axis: valueAxis(title(c.yTitle, v), c.format) },
      };
      if (catCols.length) enc.x = { field: catCols[0], type: "nominal", axis: bandAxis(title(c.xTitle, catCols[0])) };
      return { resolved: "boxplot", defaultH: 320, xCategories: 0,
               // Quartiles, whiskers and outliers: a mark type, not 60 lines of arithmetic.
               spec: { ...base, mark: { type: "boxplot", extent: 1.5 }, encoding: enc } };
    }

    // ── composition ────────────────────────────────────────────────────────
    case "stacked-bar":
    case "stacked_bar":
    case "grouped-bar":
    case "grouped_bar": {
      const grouped = type.startsWith("grouped");
      // The BAND is chosen first and the series is whatever is left. Picking the series
      // first landed both on the same column whenever the band was a date, because
      // `c.band` already holds the first category — and the form then refused itself.
      const bandField = dateCol ?? catCols[0];
      const series = catCols.find((x) => x !== bandField);
      if (!bandField) return null;

      /**
       * No second dimension, but two or more measures: the MEASURES are the series.
       * `region × revenue × profit` has one category and nothing to group by, so a fold
       * turns the measure names into a series column — which is what a reader means by
       * "compare revenue and profit per region", and what the retired combo form drew with
       * a second y-axis. One scale, no second axis.
       */
      if (!series) {
        if (numCols.length < 2) return null;
        return {
          resolved: grouped ? "grouped-bar" : "stacked-bar", defaultH: 320,
          xCategories: new Set(rows.map((r) => r[columns.indexOf(bandField)])).size,
          spec: {
            ...base,
            transform: [{ fold: numCols, as: ["__measure", "__value"] }],
            mark: { type: "bar", tooltip: true },
            encoding: {
              x: { field: bandField, type: dateCol === bandField ? "temporal" : "nominal",
                   axis: bandAxis(title(c.xTitle, bandField)) },
              y: { field: "__value", type: "quantitative", stack: grouped ? null : "zero",
                   axis: valueAxis(title(c.yTitle, "value"), c.format) },
              color: { field: "__measure", type: "nominal", sort: null },
              ...(grouped ? { xOffset: { field: "__measure", sort: null } } : {}),
            },
          },
        };
      }
      const enc: Record<string, unknown> = {
        x: { field: bandField, type: dateCol === bandField ? "temporal" : "nominal",
             axis: bandAxis(title(c.xTitle, bandField)) },
        y: { field: measure, type: "quantitative", stack: grouped ? null : "zero",
             axis: valueAxis(yT, c.format) },
        color: { field: series, type: "nominal", sort: null },
      };
      if (grouped) enc.xOffset = { field: series, sort: null };
      return { resolved: grouped ? "grouped-bar" : "stacked-bar", defaultH: 320,
               xCategories: new Set(rows.map((r) => r[columns.indexOf(bandField)])).size,
               spec: { ...base, mark: { type: "bar", tooltip: true }, encoding: enc } };
    }

    case "small-multiples":
    case "small_multiples": {
      const facet = catCols[0];
      const x = dateCol ?? catCols[1];
      if (!facet || !x) return null;
      return {
        resolved: "small-multiples", defaultH: 320, xCategories: 0,
        spec: {
          ...base,
          // Faceting is a spec-level operation. The builders drew each panel by hand.
          facet: { field: facet, type: "nominal", columns: 3, header: { title: null } },
          spec: {
            width: 180, height: 110,
            mark: { type: "line" },
            encoding: {
              x: { field: x, type: x === dateCol ? "temporal" : "ordinal", axis: bandAxis("") },
              y: { field: measure, type: "quantitative", axis: valueAxis("", c.format) },
            },
          },
        },
      };
    }

    // ── change ─────────────────────────────────────────────────────────────
    case "delta-bar":
    case "delta_bar": {
      if (!catCols.length || !numCols.length) return null;
      const cat = catCols[0];
      return {
        resolved: "delta-bar", defaultH: Math.max(180, rows.length * 30 + 60), xCategories: 0,
        spec: {
          ...base,
          mark: { type: "bar", tooltip: true },
          encoding: {
            x: { field: measure, type: "quantitative", axis: valueAxis(yT, c.format) },
            y: { field: cat, type: "nominal", sort: { field: measure, order: "descending" },
                 axis: bandAxis(title(c.xTitle, cat)) },
            // Sign, not identity: a threshold scale at zero reading the config's diverging
            // pair. Two colours, and neither of them written into the spec.
            color: { field: measure, type: "quantitative",
                     scale: { type: "threshold", domain: [0], range: "diverging" }, legend: null },
          },
        },
      };
    }

    case "waterfall": {
      if (!catCols.length || !numCols.length) return null;
      const step = catCols[0];
      return {
        resolved: "waterfall", defaultH: 320,
        xCategories: new Set(rows.map((r) => r[columns.indexOf(step)])).size,
        spec: {
          ...base,
          transform: [
            // The running total and each bar's floor, declared. This was a hand-written
            // reduce in the builders, and the place an off-by-one hides.
            { window: [{ op: "sum", field: measure, as: "__end" }], frame: [null, 0] },
            { calculate: `datum.__end - datum['${measure}']`, as: "__start" },
          ],
          mark: { type: "bar", tooltip: true },
          encoding: {
            x: { field: step, type: "nominal", sort: null, axis: bandAxis(title(c.xTitle, step)) },
            y: { field: "__start", type: "quantitative", axis: valueAxis(yT, c.format) },
            y2: { field: "__end" },
            color: { field: measure, type: "quantitative",
                     scale: { type: "threshold", domain: [0], range: "diverging" }, legend: null },
          },
        },
      };
    }

    // ── concentration ──────────────────────────────────────────────────────
    case "pareto": {
      if (!catCols.length || !numCols.length) return null;
      const cat = catCols[0];
      return {
        resolved: "pareto", defaultH: 330,
        xCategories: new Set(rows.map((r) => r[columns.indexOf(cat)])).size,
        spec: {
          ...base,
          transform: [
            { window: [{ op: "sum", field: measure, as: "__rank" }], sort: [{ field: measure, order: "descending" }] },
            { joinaggregate: [{ op: "sum", field: measure, as: "__total" }] },
            { calculate: "datum.__total === 0 ? 0 : datum.__rank / datum.__total", as: "__cum" },
            { calculate: `datum.__total === 0 ? 0 : datum['${measure}'] / datum.__total`, as: "__share" },
          ],
          // ONE axis, both measures as a share. The ECharts pareto used a second y-scale;
          // §6 bans dual axes and the exhibit grammar already retired the form, so the
          // cumulative line and the bars are expressed in the same unit instead.
          layer: [
            { mark: { type: "bar", tooltip: true },
              encoding: { y: { field: "__share", type: "quantitative", axis: valueAxis("Share of total", ".0%") } } },
            { mark: { type: "line", point: true },
              encoding: { y: { field: "__cum", type: "quantitative" } } },
          ],
          encoding: {
            x: { field: cat, type: "nominal", sort: { field: measure, order: "descending" },
                 axis: bandAxis(title(c.xTitle, cat)) },
          },
        },
      };
    }

    // ── trend with a band ──────────────────────────────────────────────────
    case "line-forecast":
    case "line_forecast": {
      const x = dateCol ?? c.band;
      if (!x) return null;
      const lower = columns.find((n) => /lower|lo_|_low|p10/i.test(n));
      const upper = columns.find((n) => /upper|hi_|_high|p90/i.test(n));
      const layers: Record<string, unknown>[] = [];
      if (lower && upper) {
        layers.push({
          mark: { type: "area", opacity: 0.18 },
          encoding: { y: { field: lower, type: "quantitative" }, y2: { field: upper } },
        });
      }
      layers.push({ mark: { type: "line" }, encoding: { y: { field: measure, type: "quantitative", axis: valueAxis(yT, c.format) } } });
      return {
        resolved: "line-forecast", defaultH: 300, xCategories: 0,
        spec: {
          ...base, layer: layers,
          encoding: { x: { field: x, type: x === dateCol ? "temporal" : "ordinal",
                           axis: { ...bandAxis(title(c.xTitle, x)), ...(x === dateCol ? { format: "%b %Y" } : {}) } } },
        },
      };
    }

    // ── geography ──────────────────────────────────────────────────────────
    case "choropleth": {
      const place = catCols[0];
      if (!place || !numCols.length) return null;
      return {
        resolved: "choropleth", defaultH: 380, xCategories: 0,
        spec: {
          ...base,
          data: WORLD,
          projection: PROJECTION,
          transform: [{
            // The map is the spine and the answer is looked up INTO it, so a country with
            // no row still draws — an absent value reads as absent, not as zero.
            lookup: "properties.name",
            from: { data, key: place, fields: [measure] },
          }],
          mark: { type: "geoshape", tooltip: true },
          encoding: {
            color: { field: measure, type: "quantitative", scale: { range: "heatmap" },
                     legend: { title: yT, format: fmt(c.format) } },
          },
        },
      };
    }

    case "point-map":
    case "point_map": {
      const lat = columns.find((n) => LAT.test(n));
      const lon = columns.find((n) => LON.test(n));
      if (!lat || !lon) return null;
      return {
        resolved: "point-map", defaultH: 380, xCategories: 0,
        spec: {
          ...base,
          projection: PROJECTION,
          layer: [
            { data: WORLD, mark: { type: "geoshape" } },
            {
              data,
              mark: { type: "circle", tooltip: true },
              encoding: {
                longitude: { field: lon, type: "quantitative" },
                latitude: { field: lat, type: "quantitative" },
                ...(numCols.length
                  ? { size: { field: measure, type: "quantitative", legend: { title: yT } } }
                  : {}),
              },
            },
          ],
        },
      };
    }

    default:
      return null;
  }
}
