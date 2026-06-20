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
  return (v) => {
    const n = num(v);
    if (v == null || isNaN(n)) return "—";
    return share ? pct(n, 1) : compactNumber(n);
  };
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
    legend: i.ys.length > 1 ? { data: i.ys.map(cleanLabel) } : undefined,
    xAxis: {
      type: "category",
      data: cats,
      boundaryGap: false,
      axisLabel: i.xKind === "time" ? { formatter: dateAxisLabel(i.rows, i.x), hideOverlap: true } : { hideOverlap: true },
    },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => fmt(v) } },
    series: i.ys.map((y) => ({
      name: cleanLabel(y),
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

/** Categorical comparison — one measure, sorted descending, vertical bars. */
export function barOption(i: BuildInput): EChartsOption {
  const y = i.ys[0];
  const sorted = i.rows.slice().sort((a, b) => num(b[y]) - num(a[y]));
  const fmt = valueFormatter(i.rows, y);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => fmt(v) },
    xAxis: { type: "category", data: sorted.map((r) => String(r[i.x])), axisLabel: { hideOverlap: true, interval: 0 } },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => fmt(v) } },
    series: [{
      name: cleanLabel(y),
      type: "bar",
      data: sorted.map((r) => num(r[y])),
      label: i.labels ? { show: true, position: "top", fontSize: 10, formatter: (p: { value: unknown }) => fmt(p.value) } : undefined,
    }],
  };
}

/** Several same-unit measures over one category — grouped bars side by side. */
export function groupedBarOption(i: BuildInput): EChartsOption {
  const cats = i.rows.map((r) => String(r[i.x]));
  const fmt = valueFormatter(i.rows, i.ys[0]);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => fmt(v) },
    legend: { data: i.ys.map(cleanLabel) },
    xAxis: { type: "category", data: cats, axisLabel: { hideOverlap: true, interval: 0 } },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => fmt(v) } },
    series: i.ys.map((y) => ({ name: cleanLabel(y), type: "bar", data: i.rows.map((r) => num(r[y])) })),
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
        return `${cleanLabel(xf)}: ${fx(v[0])}<br/>${cleanLabel(yf)}: ${fy(v[1])}`;
      },
    },
    xAxis: { type: "value", name: cleanLabel(xf), nameLocation: "middle", nameGap: 28, axisLabel: { formatter: (v: number) => fx(v) } },
    yAxis: { type: "value", name: cleanLabel(yf), axisLabel: { formatter: (v: number) => fy(v) } },
    series: [{ type: "scatter", symbolSize: 9, data: i.rows.map((r) => [num(r[xf]), num(r[yf])]), emphasis: { focus: "series" } }],
  };
}
