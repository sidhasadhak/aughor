/**
 * tier3.ts — the escape hatch, exercised.
 *
 * Four chart types Vega-Lite cannot express: a treemap needs a hierarchy layout, a sankey
 * needs a flow layout Vega has no transform for at all, a funnel needs marks that are not
 * an encoding of a scale, and a gantt needs spans. These are hand-authored RAW VEGA specs
 * — tier 3 of the control ladder, and the reason the ladder exists.
 *
 * Two rules carry over from tier 1 and are the point of the whole exercise:
 *   - no colour is written into a spec. Everything comes from the runtime config, so an
 *     ejected chart still follows the token layer and still flips with the theme.
 *   - the output is pure JSON. Layout maths that Vega cannot express (the sankey) is
 *     computed here and emitted as DATA, never as a function in the spec.
 *
 * The ledger records zero uses of all four. They are ported rather than deleted because
 * the alternative is keeping a second chart engine alive to draw them.
 */

import { cleanLabel } from "@/lib/format";

export interface Tier3Args {
  columns: string[];
  rows: unknown[][];
  chartType: string;
  title?: string | null;
}

export interface Tier3Spec {
  spec: Record<string, unknown>;
  defaultH: number;
  tier: 3;
  resolved: string;
}

/** Chart types tier 3 draws. Anything else is not its business. */
export const TIER3_TYPES = new Set(["treemap", "sankey", "funnel", "gantt"]);

const SCHEMA = "https://vega.github.io/schema/vega/v5.json";

const num = (v: unknown): number => {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
};

/** Column pick: first non-numeric as the label, first numeric as the measure. */
function pickCols(columns: string[], rows: unknown[][]): { label: string; value: string } | null {
  if (!columns.length || !rows.length) return null;
  const numericIdx = columns.findIndex((_, i) => rows.some((r) => typeof r[i] === "number" || (r[i] !== null && r[i] !== "" && Number.isFinite(Number(r[i])))));
  const labelIdx = columns.findIndex((_, i) => i !== numericIdx);
  if (numericIdx < 0 || labelIdx < 0) return null;
  return { label: columns[labelIdx], value: columns[numericIdx] };
}

const base = (title?: string | null) => ({
  $schema: SCHEMA,
  ...(title ? { title: { text: title } } : {}),
  padding: 0,
  autosize: { type: "fit", contains: "padding" },
});

// ── treemap ──────────────────────────────────────────────────────────────────
function treemap(columns: string[], rows: unknown[][], title?: string | null): Tier3Spec | null {
  const cols = pickCols(columns, rows);
  if (!cols) return null;
  const li = columns.indexOf(cols.label);
  const vi = columns.indexOf(cols.value);
  // A stratify transform needs a root, and a flat (category, value) result has none —
  // so one is synthesised here rather than asking the caller for a hierarchy.
  const values = [
    { id: 0, name: "root" },
    ...rows.map((r, i) => ({ id: i + 1, parent: 0, name: String(r[li] ?? ""), value: num(r[vi]) })),
  ];
  return {
    tier: 3, resolved: "treemap", defaultH: 360,
    spec: {
      ...base(title),
      data: [
        {
          name: "tree", values,
          transform: [
            { type: "stratify", key: "id", parentKey: "parent" },
            {
              type: "treemap", field: "value", method: "squarify", round: true,
              sort: { field: "value", order: "descending" },
              size: [{ signal: "width" }, { signal: "height" }], paddingInner: 2,
            },
          ],
        },
        { name: "leaves", source: "tree", transform: [{ type: "filter", expr: "!datum.children" }] },
      ],
      scales: [{ name: "color", type: "ordinal", domain: { data: "leaves", field: "name" }, range: "category"  /* the string names the RANGE in the runtime config. The object form, {scheme:"category"}, asks Vega for a colour SCHEME by that name -- there is none, and the error kills every mark bound to the scale while leaving the marks that are not (the text labels), so the chart looks half-drawn rather than broken. */ }],
      marks: [
        {
          type: "rect", from: { data: "leaves" },
          encode: {
            enter: { fill: { scale: "color", field: "name" } },
            update: { x: { field: "x0" }, y: { field: "y0" }, x2: { field: "x1" }, y2: { field: "y1" } },
          },
        },
        {
          type: "text", from: { data: "leaves" },
          encode: {
            update: {
              x: { signal: "(datum.x0 + datum.x1) / 2" },
              y: { signal: "(datum.y0 + datum.y1) / 2" },
              align: { value: "center" }, baseline: { value: "middle" },
              text: { field: "name" },
              // A label wider than its own tile is noise; hide it rather than clip it.
              opacity: { signal: "(datum.x1 - datum.x0) > 54 && (datum.y1 - datum.y0) > 18 ? 1 : 0" },
            },
          },
        },
      ],
    },
  };
}

// ── funnel ───────────────────────────────────────────────────────────────────
function funnel(columns: string[], rows: unknown[][], title?: string | null): Tier3Spec | null {
  const cols = pickCols(columns, rows);
  if (!cols) return null;
  const li = columns.indexOf(cols.label);
  const vi = columns.indexOf(cols.value);
  const values = rows.map((r) => ({ stage: String(r[li] ?? ""), value: num(r[vi]) }));
  return {
    tier: 3, resolved: "funnel", defaultH: Math.max(200, values.length * 46 + 40),
    spec: {
      ...base(title),
      data: [{ name: "stages", values }],
      scales: [
        { name: "y", type: "band", domain: { data: "stages", field: "stage" }, range: "height", padding: 0.25 },
        { name: "w", type: "linear", domain: { data: "stages", field: "value" }, range: [0, { signal: "width" }], nice: true, zero: true },
      ],
      axes: [{ orient: "left", scale: "y", grid: false, domain: false, ticks: false }],
      marks: [
        {
          // Centred bars: a funnel is a magnitude read down the page, and centring is what
          // makes the taper legible. Vega-Lite has no centred-bar encoding.
          type: "rect", from: { data: "stages" },
          encode: {
            update: {
              x: { signal: "width / 2 - scale('w', datum.value) / 2" },
              width: { scale: "w", field: "value" },
              y: { scale: "y", field: "stage" },
              height: { scale: "y", band: 1 },
            },
          },
        },
        {
          type: "text", from: { data: "stages" },
          encode: {
            update: {
              x: { signal: "width / 2" },
              y: { signal: "scale('y', datum.stage) + bandwidth('y') / 2" },
              align: { value: "center" }, baseline: { value: "middle" },
              text: { signal: "format(datum.value, '~s')" },
            },
          },
        },
      ],
    },
  };
}

// ── gantt ────────────────────────────────────────────────────────────────────
function gantt(columns: string[], rows: unknown[][], title?: string | null): Tier3Spec | null {
  if (columns.length < 3 || !rows.length) return null;
  const [taskC, startC, endC] = [columns[0], columns[1], columns[2]];
  const values = rows.map((r) => ({
    task: String(r[0] ?? ""),
    start: String(r[1] ?? ""),
    end: String(r[2] ?? ""),
  }));
  void taskC; void startC; void endC;
  return {
    tier: 3, resolved: "gantt", defaultH: Math.max(180, values.length * 34 + 44),
    spec: {
      ...base(title),
      data: [{
        name: "spans", values,
        transform: [
          { type: "formula", as: "s", expr: "toDate(datum.start)" },
          { type: "formula", as: "e", expr: "toDate(datum.end)" },
        ],
      }],
      scales: [
        { name: "y", type: "band", domain: { data: "spans", field: "task" }, range: "height", padding: 0.3 },
        { name: "x", type: "time", domain: { data: "spans", fields: ["s", "e"] }, range: "width", nice: true },
      ],
      axes: [
        { orient: "bottom", scale: "x", grid: true },
        { orient: "left", scale: "y", grid: false, domain: false, ticks: false },
      ],
      marks: [{
        type: "rect", from: { data: "spans" },
        encode: {
          update: {
            x: { scale: "x", field: "s" }, x2: { scale: "x", field: "e" },
            y: { scale: "y", field: "task" }, height: { scale: "y", band: 1 },
          },
        },
      }],
    },
  };
}

// ── sankey ───────────────────────────────────────────────────────────────────
/**
 * Vega has no sankey transform, so the layout is computed HERE and emitted as data.
 *
 * That is the deliberate tier-3 move: geometry a grammar cannot express becomes numbers in
 * the spec, not a function in it. The spec stays pure JSON, so it can still be persisted,
 * diffed and re-rendered — which a spec carrying a layout callback could not.
 *
 * A two-column layout: sources on the left, targets on the right, node heights proportional
 * to the flow through them, links drawn as cubic beziers between the two.
 */
function sankey(columns: string[], rows: unknown[][], title?: string | null): Tier3Spec | null {
  if (columns.length < 3 || !rows.length) return null;
  const links = rows.map((r) => ({ source: String(r[0] ?? ""), target: String(r[1] ?? ""), value: num(r[2]) }))
    .filter((l) => l.source && l.target && l.value > 0);
  if (!links.length) return null;

  const sources = [...new Set(links.map((l) => l.source))];
  const targets = [...new Set(links.map((l) => l.target))];
  const total = (name: string, side: "source" | "target") =>
    links.filter((l) => l[side] === name).reduce((a, l) => a + l.value, 0);

  const H = Math.max(220, Math.max(sources.length, targets.length) * 46 + 40);
  const gap = 10;
  const NODE_W = 12;

  const column = (names: string[], side: "source" | "target") => {
    const sum = names.reduce((a, n) => a + total(n, side), 0) || 1;
    const usable = H - gap * Math.max(0, names.length - 1);
    let y = 0;
    return names.map((name) => {
      const h = Math.max(2, (total(name, side) / sum) * usable);
      const node = { name, y0: y, y1: y + h, side };
      y += h + gap;
      return node;
    });
  };

  const left = column(sources, "source");
  const right = column(targets, "target");
  const byName = (side: "source" | "target", name: string) =>
    (side === "source" ? left : right).find((n) => n.name === name)!;

  // Walk each node's edge once, stacking its links so ribbons leave and arrive in order.
  const offset: Record<string, number> = {};
  const ribbons = links.map((l) => {
    const s = byName("source", l.source);
    const t = byName("target", l.target);
    const sk = `s:${l.source}`, tk = `t:${l.target}`;
    const sh = ((s.y1 - s.y0) * l.value) / (total(l.source, "source") || 1);
    const th = ((t.y1 - t.y0) * l.value) / (total(l.target, "target") || 1);
    const sy = s.y0 + (offset[sk] ?? 0);
    const ty = t.y0 + (offset[tk] ?? 0);
    offset[sk] = (offset[sk] ?? 0) + sh;
    offset[tk] = (offset[tk] ?? 0) + th;
    return { source: l.source, target: l.target, value: l.value, sy0: sy, sy1: sy + sh, ty0: ty, ty1: ty + th };
  });

  return {
    tier: 3, resolved: "sankey", defaultH: H,
    spec: {
      ...base(title),
      // The x positions are signals so the ribbons re-draw with the container width; the
      // vertical layout is fixed, which is what makes it computable here.
      signals: [{ name: "nodeW", value: NODE_W }],
      data: [
        { name: "nodes", values: [...left, ...right] },
        {
          name: "ribbons", values: ribbons,
          transform: [{
            type: "formula", as: "path",
            expr: "'M ' + (nodeW) + ',' + datum.sy0 + " +
                  "' C ' + (width/2) + ',' + datum.sy0 + ' ' + (width/2) + ',' + datum.ty0 + ' ' + (width - nodeW) + ',' + datum.ty0 + " +
                  "' L ' + (width - nodeW) + ',' + datum.ty1 + " +
                  "' C ' + (width/2) + ',' + datum.ty1 + ' ' + (width/2) + ',' + datum.sy1 + ' ' + (nodeW) + ',' + datum.sy1 + ' Z'",
          }],
        },
      ],
      scales: [{ name: "color", type: "ordinal", domain: { data: "nodes", field: "name" }, range: "category"  /* the string names the RANGE in the runtime config. The object form, {scheme:"category"}, asks Vega for a colour SCHEME by that name -- there is none, and the error kills every mark bound to the scale while leaving the marks that are not (the text labels), so the chart looks half-drawn rather than broken. */ }],
      marks: [
        {
          type: "path", from: { data: "ribbons" },
          encode: { update: { path: { field: "path" }, fill: { scale: "color", field: "source" }, fillOpacity: { value: 0.35 } } },
        },
        {
          type: "rect", from: { data: "nodes" },
          encode: {
            update: {
              x: { signal: "datum.side === 'source' ? 0 : width - nodeW" },
              width: { signal: "nodeW" },
              y: { field: "y0" }, y2: { field: "y1" },
              fill: { scale: "color", field: "name" },
            },
          },
        },
        {
          type: "text", from: { data: "nodes" },
          encode: {
            update: {
              x: { signal: "datum.side === 'source' ? nodeW + 6 : width - nodeW - 6" },
              y: { signal: "(datum.y0 + datum.y1) / 2" },
              align: { signal: "datum.side === 'source' ? 'left' : 'right'" },
              baseline: { value: "middle" },
              text: { field: "name" },
            },
          },
        },
      ],
    },
  };
}

/** Resolve one tier-3 chart, or null when this is not a tier-3 type / the data cannot carry it. */
export function resolveTier3Spec({ columns, rows, chartType, title }: Tier3Args): Tier3Spec | null {
  const t = String(chartType ?? "").toLowerCase();
  if (!TIER3_TYPES.has(t) || !rows?.length || !columns?.length) return null;
  const named = title ?? (columns.length ? cleanLabel(columns[0]) : null);
  switch (t) {
    case "treemap": return treemap(columns, rows, named);
    case "funnel": return funnel(columns, rows, named);
    case "gantt": return gantt(columns, rows, named);
    default: return sankey(columns, rows, named);
  }
}
