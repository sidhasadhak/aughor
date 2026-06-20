/**
 * builders.ts — pure `transformProps`-style functions: (data + resolved fields)
 * → an ECharts `option`. No React, no DOM — so each builder is unit-testable in
 * isolation (the testability unlock the 1,300-line Vega cascade never had).
 *
 * Colours/axis styling come from the registered Aughor theme (theme.ts); these
 * builders own only STRUCTURE + per-field number/date formatting, which they
 * draw from the single formatting home in @/lib/format.
 */

import type { EChartsOption } from "echarts";
import { compactNumber, pct, cleanLabel, detectGranularity, fmtDate, normDateStr, type Gran } from "@/lib/format";
import { SHARE_COL } from "@/components/charts/columnRoles";
import { effectiveCurrencySymbol, isMoneyColumn } from "@/lib/orgSettings";

export type Row = Record<string, unknown>;

export interface BuildInput {
  rows: Row[];
  x: string;             // x-axis field (date or category)
  ys: string[];          // measure field(s)
  color?: string;        // series/stack group field (multi-line, stacked-bar)
  xKind?: "time" | "category";
  title?: string;
  labels?: boolean;      // draw value labels on marks
}

// ── formatting helpers ───────────────────────────────────────────────────────

const num = (v: unknown): number => Number(v);
const maxAbs = (rows: Row[], f: string): number =>
  Math.max(0, ...rows.map((r) => Math.abs(num(r[f]))).filter((v) => isFinite(v)));

/** A 0–1 share column → render as percent; otherwise SI-compact. Mirrors the
 *  per-field `fmtCol` rule in the legacy Chart.tsx (kills the percent-leak bug
 *  where a rate's format bled onto a count axis). */
export function isShareField(rows: Row[], f: string): boolean {
  return SHARE_COL.test(f) && maxAbs(rows, f) <= 1.0001;
}

export function valueFormatter(rows: Row[], f: string): (v: unknown) => string {
  const share = isShareField(rows, f);
  // Money fields carry the effective reporting currency symbol (override-wins), so a
  // chart's values read in the org's currency — matching the KPI cards + tables.
  const sym = !share && isMoneyColumn(f) ? effectiveCurrencySymbol() : "";
  return (v) => {
    const n = num(v);
    if (v == null || isNaN(n)) return "—";
    return share ? pct(n, 1) : sym + compactNumber(n);
  };
}

// Display label for a field. For a money field, when an org currency is set, the embedded
// SOURCE-currency code is dropped (the override is a display relabel, not an FX conversion)
// — the value's symbol carries the unit, so "cac_usd" → "CAC" not "CAC USD".
const _label = cleanLabel;
const _CUR_TOKEN = /(^|[_\s])(usd|eur|gbp|jpy|cny|inr|aud|cad|chf|sgd|brl|zar)(?=$|[_\s])/i;
function fieldLabel(f: string): string {
  if (effectiveCurrencySymbol() && isMoneyColumn(f) && _CUR_TOKEN.test(f)) {
    const stripped = f.replace(_CUR_TOKEN, "$1").replace(/^[_\s]+|[_\s]+$/g, "");
    return _label(stripped || f);
  }
  return _label(f);
}

/** Distinct x values, sorted chronologically for time axes else preserving order. */
function categories(rows: Row[], x: string, xKind?: "time" | "category"): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const r of rows) {
    const k = String(r[x]);
    if (!seen.has(k)) { seen.add(k); out.push(k); }
  }
  if (xKind === "time") {
    out.sort((a, b) => new Date(normDateStr(a)).getTime() - new Date(normDateStr(b)).getTime());
  }
  return out;
}

function dateAxisLabel(rows: Row[], x: string) {
  const gran: Gran = detectGranularity(x, rows.map((r) => r[x]));
  return (val: string) => fmtDate(String(val), gran);
}

/** Shared base: title + grid handled by theme; this adds the title text only. */
function withTitle(title: string | undefined): Pick<EChartsOption, "title"> {
  return title ? { title: { text: title } } : {};
}

// ── builders ─────────────────────────────────────────────────────────────────

/** Single time/category series (or several overlaid measures sharing one axis). */
export function lineOption(i: BuildInput, area = false): EChartsOption {
  const cats = categories(i.rows, i.x, i.xKind);
  const byX = new Map(i.rows.map((r) => [String(r[i.x]), r]));
  const fmt = valueFormatter(i.rows, i.ys[0]);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", valueFormatter: (v) => fmt(v) },
    legend: i.ys.length > 1 ? { data: i.ys.map(fieldLabel) } : undefined,
    xAxis: {
      type: "category",
      data: cats,
      boundaryGap: false,
      axisLabel: i.xKind === "time" ? { formatter: dateAxisLabel(i.rows, i.x), hideOverlap: true } : { hideOverlap: true },
    },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => fmt(v) } },
    series: i.ys.map((y) => ({
      name: fieldLabel(y),
      type: "line",
      data: cats.map((c) => { const r = byX.get(c); return r == null ? null : num(r[y]); }),
      showSymbol: cats.length <= 60,
      symbolSize: 5,
      areaStyle: area ? { opacity: 0.18 } : { opacity: 0.06 },
      emphasis: { focus: "series" },
      label: i.labels ? { show: true, position: "top", fontSize: 10, formatter: (p: { value: unknown }) => fmt(p.value) } : undefined,
    })),
  };
}

/** One line per distinct value of the `color` group field (long → multi-series). */
export function multiLineOption(i: BuildInput): EChartsOption {
  const y = i.ys[0];
  const cats = categories(i.rows, i.x, i.xKind ?? "time");
  const groups: string[] = [];
  const cell = new Map<string, number>(); // `${group}__${x}` → value
  for (const r of i.rows) {
    const g = String(r[i.color!]);
    if (!groups.includes(g)) groups.push(g);
    cell.set(`${g}__${String(r[i.x])}`, num(r[y]));
  }
  const fmt = valueFormatter(i.rows, y);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", valueFormatter: (v) => fmt(v) },
    legend: { data: groups },
    xAxis: {
      type: "category",
      data: cats,
      boundaryGap: false,
      axisLabel: i.xKind !== "category" ? { formatter: dateAxisLabel(i.rows, i.x), hideOverlap: true } : { hideOverlap: true },
    },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => fmt(v) } },
    series: groups.map((g) => ({
      name: g,
      type: "line",
      data: cats.map((c) => { const v = cell.get(`${g}__${c}`); return v == null ? null : v; }),
      showSymbol: cats.length <= 40,
      symbolSize: 4,
      emphasis: { focus: "series" },
    })),
  };
}

export interface BarStyle {
  /** Horizontal bars (category on Y) — the legacy default for ranked categoricals. */
  horizontal?: boolean;
  /** "value" = sort desc by measure (default); "time" = chronological; "keep" = SQL order. */
  order?: "value" | "time" | "keep";
  /** Color by sign (green ≥0 / red <0), abs-magnitude sort — for change/delta metrics. */
  diverging?: boolean;
}

/** Categorical (or temporal) bar comparison. Covers every legacy bar variant via
 *  `style`: vertical/horizontal, value/time/keep ordering, diverging change bars. */
export function barOption(i: BuildInput, style: BarStyle = {}): EChartsOption {
  const y = i.ys[0];
  const order = style.order ?? "value";
  const rows = i.rows.slice();
  if (order === "time") {
    rows.sort((a, b) => new Date(normDateStr(String(a[i.x]))).getTime() - new Date(normDateStr(String(b[i.x]))).getTime());
  } else if (order === "value") {
    rows.sort((a, b) => style.diverging ? Math.abs(num(b[y])) - Math.abs(num(a[y])) : num(b[y]) - num(a[y]));
  } // "keep" → preserve incoming order (already-aggregated time labels)
  const gran: Gran | null = i.xKind === "time" ? detectGranularity(i.x, i.rows.map((r) => r[i.x])) : null;
  const labels = rows.map((r) => (gran ? fmtDate(String(r[i.x]), gran) : String(r[i.x])));
  const values = rows.map((r) => num(r[y]));
  const fmt = valueFormatter(i.rows, y);

  const catAxis = {
    type: "category" as const, data: labels,
    axisLabel: { hideOverlap: true, ...(style.horizontal ? {} : { interval: 0 }) },
    ...(style.horizontal ? { inverse: true } : {}),   // largest at top for ranked horizontal
  };
  const valAxis = { type: "value" as const, axisLabel: { formatter: (v: number) => fmt(v) } };
  const label = i.labels
    ? { show: true, fontSize: 10, position: (style.horizontal ? "right" : "top") as "right" | "top", formatter: (p: { value: unknown }) => fmt(p.value) }
    : undefined;
  const itemStyle = style.diverging
    ? { color: (p: { value: number }) => (p.value >= 0 ? "#2EC87B" : "#E64848") }
    : undefined;

  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => fmt(v) },
    xAxis: style.horizontal ? valAxis : catAxis,
    yAxis: style.horizontal ? catAxis : valAxis,
    series: [{ name: fieldLabel(y), type: "bar", data: values, label, itemStyle: itemStyle as unknown as undefined }],
  };
}

/** Several same-unit measures over one category — grouped bars side by side. */
export function groupedBarOption(i: BuildInput): EChartsOption {
  const cats = i.rows.map((r) => String(r[i.x]));
  const fmt = valueFormatter(i.rows, i.ys[0]);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => fmt(v) },
    legend: { data: i.ys.map(fieldLabel) },
    xAxis: { type: "category", data: cats, axisLabel: { hideOverlap: true, interval: 0 } },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => fmt(v) } },
    series: i.ys.map((y) => ({ name: fieldLabel(y), type: "bar", data: i.rows.map((r) => num(r[y])) })),
  };
}

/** Volume composition over time/category — stacked bars by `color` group. */
export function stackedBarOption(i: BuildInput): EChartsOption {
  const y = i.ys[0];
  const cats = categories(i.rows, i.x, i.xKind);
  const groups: string[] = [];
  const cell = new Map<string, number>();
  for (const r of i.rows) {
    const g = String(r[i.color!]);
    if (!groups.includes(g)) groups.push(g);
    cell.set(`${g}__${String(r[i.x])}`, num(r[y]));
  }
  const fmt = valueFormatter(i.rows, y);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => fmt(v) },
    legend: { data: groups },
    xAxis: {
      type: "category", data: cats,
      axisLabel: i.xKind === "time" ? { formatter: dateAxisLabel(i.rows, i.x), hideOverlap: true } : { hideOverlap: true },
    },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => fmt(v) } },
    series: groups.map((g) => ({
      name: g, type: "bar", stack: "total",
      data: cats.map((c) => cell.get(`${g}__${c}`) ?? 0),
    })),
  };
}

/** Parts of a whole — donut, aggregated by category, sorted descending. */
export function pieOption(i: BuildInput): EChartsOption {
  const y = i.ys[0];
  const agg = new Map<string, number>();
  for (const r of i.rows) {
    const k = String(r[i.x]);
    agg.set(k, (agg.get(k) ?? 0) + num(r[y]));
  }
  const data = [...agg.entries()].sort((a, b) => b[1] - a[1]).map(([name, value]) => ({ name, value }));
  const fmt = valueFormatter(i.rows, y);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "item", formatter: (p: unknown) => {
      const o = p as { name: string; value: number; percent: number };
      return `${o.name}: ${fmt(o.value)} (${o.percent}%)`;
    } },
    legend: { orient: "vertical", right: 0, top: "middle", type: "scroll" },
    series: [{
      type: "pie",
      radius: ["42%", "70%"],
      center: ["38%", "52%"],
      data,
      label: { show: !!i.labels },
      emphasis: { scale: true, scaleSize: 6 },
    }],
  };
}

/** Two numerics, correlation / outlier detection. */
export function scatterOption(i: BuildInput): EChartsOption {
  const [xf, yf] = [i.x, i.ys[0]];
  const fx = valueFormatter(i.rows, xf);
  const fy = valueFormatter(i.rows, yf);
  return {
    ...withTitle(i.title),
    tooltip: {
      trigger: "item",
      formatter: (p: unknown) => {
        const v = (p as { value: [number, number] }).value;
        return `${fieldLabel(xf)}: ${fx(v[0])}<br/>${fieldLabel(yf)}: ${fy(v[1])}`;
      },
    },
    xAxis: { type: "value", name: fieldLabel(xf), nameLocation: "middle", nameGap: 28, axisLabel: { formatter: (v: number) => fx(v) } },
    yAxis: { type: "value", name: fieldLabel(yf), axisLabel: { formatter: (v: number) => fy(v) } },
    series: [{ type: "scatter", symbolSize: 9, data: i.rows.map((r) => [num(r[xf]), num(r[yf])]), emphasis: { focus: "series" } }],
  };
}

/** Dual-axis combo — bar (primary magnitude) + line (secondary, own right axis).
 *  ys = [barField, lineField]. Per-field formatting keeps a rate's % off the
 *  count axis (the percent-leak fix from the legacy Chart.tsx). */
export function comboOption(i: BuildInput): EChartsOption {
  const [barF, lineF] = [i.ys[0], i.ys[1]];
  const sorted = i.rows.slice().sort((a, b) => num(b[barF]) - num(a[barF]));
  const fb = valueFormatter(i.rows, barF);
  const fl = valueFormatter(i.rows, lineF);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { data: [fieldLabel(barF), fieldLabel(lineF)] },
    xAxis: { type: "category", data: sorted.map((r) => String(r[i.x])), axisLabel: { hideOverlap: true, interval: 0 } },
    yAxis: [
      { type: "value", name: fieldLabel(barF), axisLabel: { formatter: (v: number) => fb(v) } },
      { type: "value", name: fieldLabel(lineF), splitLine: { show: false }, axisLabel: { formatter: (v: number) => fl(v) } },
    ],
    series: [
      { name: fieldLabel(barF), type: "bar", yAxisIndex: 0, data: sorted.map((r) => num(r[barF])), tooltip: { valueFormatter: (v) => fb(v) } },
      { name: fieldLabel(lineF), type: "line", yAxisIndex: 1, data: sorted.map((r) => num(r[lineF])), tooltip: { valueFormatter: (v) => fl(v) } },
    ],
  };
}

/** Two-dimensional distribution — x (group) × color (stack) grid, coloured by
 *  ys[0]. Fills the FULL grid so missing cells render neutral, not as gaps
 *  (the bug the legacy heatmap fixed). */
export function heatmapOption(i: BuildInput): EChartsOption {
  const valF = i.ys[0];
  const gran: Gran | null = i.xKind === "time" ? detectGranularity(i.x, i.rows.map((r) => r[i.x])) : null;
  const groupLabel = (r: Row) => (gran ? fmtDate(String(r[i.x]), gran) : String(r[i.x]));
  const groups: string[] = [];
  const stacks: string[] = [];
  const cell = new Map<string, number>();
  for (const r of i.rows) {
    const g = groupLabel(r); const s = String(r[i.color!]);
    if (!groups.includes(g)) groups.push(g);
    if (!stacks.includes(s)) stacks.push(s);
    cell.set(`${g}__${s}`, num(r[valF]));
  }
  const data: [number, number, number | null][] = [];
  let max = -Infinity, min = Infinity;
  groups.forEach((g, gi) => stacks.forEach((s, si) => {
    const v = cell.get(`${g}__${s}`);
    data.push([gi, si, v == null ? null : v]);
    if (v != null && isFinite(v)) { max = Math.max(max, v); min = Math.min(min, v); }
  }));
  const diverging = min < 0;
  const fmt = valueFormatter(i.rows, valF);
  return {
    ...withTitle(i.title),
    tooltip: { position: "top", formatter: (p: unknown) => {
      const o = p as { value: [number, number, number] };
      return `${groups[o.value[0]]} · ${stacks[o.value[1]]}: ${fmt(o.value[2])}`;
    } },
    grid: { left: 8, right: 12, top: 28, bottom: 28, containLabel: true },
    xAxis: { type: "category", data: groups, splitArea: { show: true }, axisLabel: { hideOverlap: true } },
    yAxis: { type: "category", data: stacks, splitArea: { show: true } },
    visualMap: {
      type: "continuous" as const,
      min: diverging ? -Math.max(Math.abs(min), Math.abs(max)) : (isFinite(min) ? Math.min(0, min) : 0),
      max: isFinite(max) ? max : 1,
      calculable: true, orient: "horizontal", left: "center", bottom: 0,
      inRange: { color: diverging ? ["#E64848", "#2A2C2F", "#2EC87B"] : ["#0e2440", "#244E86", "#4C8EEE"] },
      formatter: (v: number) => fmt(v),
    } as unknown as EChartsOption["visualMap"],
    series: [{ type: "heatmap", data, emphasis: { itemStyle: { borderColor: "#fff", borderWidth: 1 } } }],
  };
}

/** Composition across many parts — proportional-area tiles (top 40). */
export function treemapOption(i: BuildInput): EChartsOption {
  const valF = i.ys[0];
  const agg = new Map<string, number>();
  for (const r of i.rows) { const k = String(r[i.x]); agg.set(k, (agg.get(k) ?? 0) + num(r[valF])); }
  const data = [...agg.entries()].sort((a, b) => b[1] - a[1]).slice(0, 40).map(([name, value]) => ({ name, value }));
  const fmt = valueFormatter(i.rows, valF);
  return {
    ...withTitle(i.title),
    tooltip: { formatter: (p: unknown) => { const o = p as { name: string; value: number }; return `${o.name}: ${fmt(o.value)}`; } },
    series: [{
      type: "treemap", data, roam: false, nodeClick: false, breadcrumb: { show: false },
      width: "100%", height: "100%", top: 24,
      label: { show: true, formatter: "{b}", fontSize: 11 },
      itemStyle: { borderColor: "#161A20", borderWidth: 2, gapWidth: 2 },
    }],
  };
}

/** Pareto (80/20) — sorted bars (left axis) + cumulative-% line (right axis,
 *  0–1) + an 80% reference line. Surfaces concentration. */
export function paretoOption(i: BuildInput): EChartsOption {
  const valF = i.ys[0];
  const agg = new Map<string, number>();
  for (const r of i.rows) { const k = String(r[i.x]); agg.set(k, (agg.get(k) ?? 0) + num(r[valF])); }
  const sorted = [...agg.entries()].sort((a, b) => b[1] - a[1]);
  const total = sorted.reduce((s, [, v]) => s + v, 0) || 1;
  let running = 0;
  const cats = sorted.map(([k]) => k);
  const bars = sorted.map(([, v]) => v);
  const cum = sorted.map(([, v]) => { running += v; return running / total; });
  const fmt = valueFormatter(i.rows, valF);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { data: [fieldLabel(valF), "Cumulative"] },
    xAxis: { type: "category", data: cats, axisLabel: { hideOverlap: true, interval: 0 } },
    yAxis: [
      { type: "value", name: fieldLabel(valF), axisLabel: { formatter: (v: number) => fmt(v) } },
      { type: "value", name: "Cumulative", min: 0, max: 1, splitLine: { show: false }, axisLabel: { formatter: (v: number) => `${Math.round(v * 100)}%` } },
    ],
    series: [
      { name: fieldLabel(valF), type: "bar", yAxisIndex: 0, data: bars, tooltip: { valueFormatter: (v) => fmt(v) } },
      {
        name: "Cumulative", type: "line", yAxisIndex: 1, data: cum, smooth: false,
        tooltip: { valueFormatter: (v) => `${Math.round(Number(v) * 100)}%` },
        markLine: { silent: true, symbol: "none", data: [{ yAxis: 0.8 }], lineStyle: { type: "dashed" }, label: { formatter: "80%" } },
      },
    ],
  };
}
