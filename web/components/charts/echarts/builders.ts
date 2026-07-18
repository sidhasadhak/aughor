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
import { type ExhibitSpec, severityRamp, refMarkLine } from "@/components/charts/exhibit";

export type Row = Record<string, unknown>;

export interface BuildInput {
  rows: Row[];
  x: string;             // x-axis field (date or category)
  ys: string[];          // measure field(s)
  color?: string;        // series/stack group field (multi-line, stacked-bar, scatter)
  xKind?: "time" | "category";
  title?: string;
  labels?: boolean;      // draw value labels on marks
  units?: Record<string, string>;  // authoritative per-column unit hint from the backend finding
  /** Optional backend exhibit spec (semantic color / reference lines / point labels).
   *  Absent → byte-identical legacy rendering. */
  exhibit?: ExhibitSpec | null;
  /** Field naming each scatter point (the entity id/name column) — enables
   *  exhibit.label_points and the identity line in the tooltip. */
  pointLabel?: string;
}

// ── formatting helpers ───────────────────────────────────────────────────────

const num = (v: unknown): number => Number(v);
const maxAbs = (rows: Row[], f: string): number =>
  Math.max(0, ...rows.map((r) => Math.abs(num(r[f]))).filter((v) => isFinite(v)));

/** Is this field a percentage? An explicit backend `units` hint (`{col: "percent"}`) is
 *  authoritative — it fixes the two cases the name heuristic can't: a metric aliased `metric_total`
 *  (a rate the name doesn't reveal) and an already-scaled share whose values exceed 1. Absent a hint,
 *  fall back to the legacy name + [0,1]-range rule (kills the percent-leak onto a count axis). */
export function isShareField(rows: Row[], f: string, units?: Record<string, string>): boolean {
  if (units?.[f] === "percent") return true;
  return SHARE_COL.test(f) && maxAbs(rows, f) <= 1.0001;
}

// Symbols for the SOURCE-currency unit hint ("currency:CHF"). Codes with no compact
// symbol print as a code prefix ("CHF 1.9M") — honest beats pretty.
const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: "$", EUR: "€", GBP: "£", JPY: "¥", CNY: "¥", INR: "₹",
  AUD: "A$", CAD: "C$", SGD: "S$", CHF: "CHF ", BRL: "R$", ZAR: "R",
};

/** Decimals a SHARE column needs so two DISTINCT values never collapse to the same label —
 *  fixes "return 2.8% / one_way 2.8%" printed beside visibly different-length bars (the real
 *  values were 2.76 vs 2.80). Default 1 decimal; bump to 2 only when 1 would merge distinct
 *  values (capped at 2 — closer than that and the bars are indistinguishable anyway). */
function sharePrecision(rows: Row[], f: string, isFraction: boolean): 1 | 2 {
  const scale = isFraction ? 100 : 1;
  const vals = [...new Set(
    rows.map((r) => num(r[f])).filter((v) => !isNaN(v)).map((v) => v * scale),
  )];
  if (vals.length < 2) return 1;
  const at1 = new Set(vals.map((v) => v.toFixed(1)));
  return at1.size < vals.length ? 2 : 1;
}

export function valueFormatter(rows: Row[], f: string, units?: Record<string, string>): (v: unknown) => string {
  const share = isShareField(rows, f, units);
  // The backend's SOURCE-currency unit ("currency:CHF", read from the metric SQL) is
  // authoritative and beats the org display symbol — a € axis over CHF data is a lie.
  // Absent that hint, money fields carry the effective reporting currency symbol
  // (override-wins), matching the KPI cards + tables.
  const srcCur = units?.[f]?.startsWith("currency:") ? units[f].slice("currency:".length) : null;
  const sym = share ? ""
    : srcCur ? (CURRENCY_SYMBOLS[srcCur] ?? `${srcCur} `)
    : isMoneyColumn(f) ? effectiveCurrencySymbol() : "";
  // Fraction-vs-percent is decided ONCE from the column's data, never per value: axis ticks
  // span from 0, so deciding per tick renders "0.0% 50.0% 100.0% 1.5% 2.0%…" on any
  // percent-scaled axis (ticks ≤1 individually read as fractions and get ×100 — the
  // flags-on soak, every narrow-range chart). Mirrors export charts.py `_fmt_for`.
  const shareIsFraction = share && maxAbs(rows, f) <= 1.0001;
  const prec = share ? sharePrecision(rows, f, shareIsFraction) : 1;
  return (v) => {
    const n = num(v);
    if (v == null || isNaN(n)) return "—";
    if (share) return shareIsFraction ? pct(n, prec) : `${n.toFixed(prec)}%`;
    return sym + compactNumber(n);
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
  const fmt = valueFormatter(i.rows, i.ys[0], i.units);
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
    series: i.ys.map((y, k) => ({
      name: fieldLabel(y),
      type: "line",
      data: cats.map((c) => { const r = byX.get(c); return r == null ? null : num(r[y]); }),
      showSymbol: cats.length <= 60,
      symbolSize: 5,
      areaStyle: area ? { opacity: 0.18 } : { opacity: 0.06 },
      emphasis: { focus: "series" },
      label: i.labels ? { show: true, position: "top", fontSize: 11, formatter: (p: { value: unknown }) => fmt(p.value) } : undefined,
      labelLayout: i.labels ? { hideOverlap: true } : undefined,
      // Reference lines (peer median / global average / benchmark) ride the first series.
      markLine: k === 0 ? refMarkLine(i.exhibit?.ref_lines ?? [], "y", fmt) : undefined,
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
  const fmt = valueFormatter(i.rows, y, i.units);
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

/** Small multiples — a grid of mini line charts, one per group, instead of a many-line spaghetti
 *  chart. Each cell shares ONE y-scale so the groups are comparable at a glance; only the bottom row
 *  shows x labels and the left column shows y labels (to keep the grid clean). Caps at the top 9
 *  groups by total so the grid never explodes. */
export function smallMultiplesOption(i: BuildInput): EChartsOption {
  const y = i.ys[0];
  const cats = categories(i.rows, i.x, i.xKind ?? "time");
  const totalByGroup = new Map<string, number>();
  const cell = new Map<string, number>();
  for (const r of i.rows) {
    const g = String(r[i.color!]);
    const v = num(r[y]);
    cell.set(`${g}__${String(r[i.x])}`, v);
    if (isFinite(v)) totalByGroup.set(g, (totalByGroup.get(g) ?? 0) + Math.abs(v));
  }
  const groups = [...totalByGroup.keys()].sort((a, b) => (totalByGroup.get(b) ?? 0) - (totalByGroup.get(a) ?? 0)).slice(0, 9);
  const fmt = valueFormatter(i.rows, y, i.units);
  const gran: Gran | null = (i.xKind ?? "time") === "time" ? detectGranularity(i.x, i.rows.map((r) => r[i.x])) : null;
  const xLabel = (v: string) => (gran ? fmtDate(String(v), gran) : String(v));
  const n = groups.length;
  const cols = n <= 4 ? 2 : 3;
  const rows = Math.ceil(n / cols);
  let ymax = 0;
  for (const v of cell.values()) if (isFinite(v)) ymax = Math.max(ymax, v);

  const gapX = 5, gapY = 10, titleH = 4;
  const cellW = (100 - gapX * (cols + 1)) / cols;
  const cellH = (100 - gapY - (gapY + titleH) * rows) / rows;
  const grids: Record<string, unknown>[] = [];
  const xAxes: Record<string, unknown>[] = [];
  const yAxes: Record<string, unknown>[] = [];
  const series: Record<string, unknown>[] = [];
  const titles: Record<string, unknown>[] = [{ show: false }];
  groups.forEach((g, k) => {
    const rr = Math.floor(k / cols), cc = k % cols;
    const left = gapX + cc * (cellW + gapX);
    const top = gapY + rr * (cellH + gapY + titleH);
    grids.push({ left: `${left}%`, top: `${top + titleH}%`, width: `${cellW}%`, height: `${cellH}%`, containLabel: true });
    xAxes.push({ gridIndex: k, type: "category", data: cats, boundaryGap: false,
      axisLabel: { show: rr === rows - 1, formatter: xLabel, hideOverlap: true, fontSize: 10 }, axisTick: { show: false } });
    yAxes.push({ gridIndex: k, type: "value", max: ymax || undefined, splitLine: { show: false },
      axisLabel: { show: cc === 0, formatter: (v: number) => fmt(v), fontSize: 10 } });
    series.push({ name: g, type: "line", xAxisIndex: k, yAxisIndex: k, showSymbol: false, lineStyle: { width: 1.5 },
      areaStyle: { opacity: 0.08 }, data: cats.map((c) => { const v = cell.get(`${g}__${c}`); return v == null ? null : v; }) });
    titles.push({ text: g, left: `${left}%`, top: `${top}%`, textStyle: { fontSize: 11, fontWeight: 500 } });
  });
  return {
    title: titles as EChartsOption["title"],
    tooltip: { trigger: "axis", valueFormatter: (v) => fmt(v) },
    grid: grids as EChartsOption["grid"],
    xAxis: xAxes as EChartsOption["xAxis"],
    yAxis: yAxes as EChartsOption["yAxis"],
    series: series as EChartsOption["series"],
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
    // Largest-first by default; an "asc" exhibit means the QUERY asked for the bottom of
    // the ranking (ORDER BY <measure> ASC LIMIT N), so lead with the row it led with
    // instead of burying it at the far end of the chart.
    const asc = i.exhibit?.order === "asc" && !style.diverging;
    rows.sort((a, b) => style.diverging ? Math.abs(num(b[y])) - Math.abs(num(a[y]))
      : (asc ? num(a[y]) - num(b[y]) : num(b[y]) - num(a[y])));
  } // "keep" → preserve incoming order (already-aggregated time labels)
  const gran: Gran | null = i.xKind === "time" ? detectGranularity(i.x, i.rows.map((r) => r[i.x])) : null;
  const labels = rows.map((r) => (gran ? fmtDate(String(r[i.x]), gran) : String(r[i.x])));
  const values = rows.map((r) => num(r[y]));
  const fmt = valueFormatter(i.rows, y, i.units);

  const catAxis = {
    type: "category" as const, data: labels,
    axisLabel: { hideOverlap: true, ...(style.horizontal ? {} : { interval: 0 }) },
    ...(style.horizontal ? { inverse: true } : {}),   // largest at top for ranked horizontal
  };
  const valAxis = { type: "value" as const, axisLabel: { formatter: (v: number) => fmt(v) } };
  const label = i.labels
    ? { show: true, fontSize: 11, distance: 5, position: (style.horizontal ? "right" : "top") as "right" | "top", formatter: (p: { value: unknown }) => fmt(p.value) }
    : undefined;
  // Semantic color: sign-diverging keeps precedence (a change metric's sign IS its meaning);
  // otherwise a "severity" exhibit ramps the bars by their own value — the redundant
  // encoding that makes a worst-N ranking read at a glance.
  let itemStyle: { color: (p: { value: number }) => string } | undefined;
  if (style.diverging) {
    itemStyle = { color: (p: { value: number }) => (p.value >= 0 ? "#2EC87B" : "#E64848") };
  } else if (i.exhibit?.color?.mode === "severity" && values.length >= 3) {
    const finite = values.filter((v) => isFinite(v));
    const ramp = severityRamp(Math.min(...finite), Math.max(...finite), y);
    itemStyle = { color: (p: { value: number }) => ramp(p.value) };
  }

  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => fmt(v) },
    xAxis: style.horizontal ? valAxis : catAxis,
    yAxis: style.horizontal ? catAxis : valAxis,
    series: [{
      name: fieldLabel(y), type: "bar", data: values, label,
      // Fixed bar thickness so few bars don't stretch into slabs — the chart HEIGHT adapts to the bar
      // count (Chart.tsx), the bars don't. ECharts caps at barMaxWidth and centres within each band.
      barMaxWidth: 34,
      // Drop any data label that would collide instead of overprinting a neighbour.
      labelLayout: i.labels ? { hideOverlap: true } : undefined,
      itemStyle: itemStyle as unknown as undefined,
      // Reference lines: on a horizontal bar the VALUE axis is x, so the line is vertical.
      markLine: refMarkLine(i.exhibit?.ref_lines ?? [], style.horizontal ? "x" : "y", fmt),
    }],
  };
}

/** Several same-unit measures over one category — grouped bars side by side. */
export function groupedBarOption(i: BuildInput): EChartsOption {
  const cats = i.rows.map((r) => String(r[i.x]));
  const fmt = valueFormatter(i.rows, i.ys[0], i.units);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => fmt(v) },
    legend: { data: i.ys.map(fieldLabel) },
    xAxis: { type: "category", data: cats, axisLabel: { hideOverlap: true, interval: 0 } },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => fmt(v) } },
    series: i.ys.map((y) => ({ name: fieldLabel(y), type: "bar", barMaxWidth: 34, data: i.rows.map((r) => num(r[y])) })),
  };
}

/** Stacked bars by `color` group. `percent` = a 100%-stacked bar: each x bucket is normalised to
 *  100% so the SHIFT in composition over time reads directly (the go-to for composition-over-time). */
export function stackedBarOption(i: BuildInput, percent = false): EChartsOption {
  const y = i.ys[0];
  const cats = categories(i.rows, i.x, i.xKind);
  const groups: string[] = [];
  const cell = new Map<string, number>();
  for (const r of i.rows) {
    const g = String(r[i.color!]);
    if (!groups.includes(g)) groups.push(g);
    cell.set(`${g}__${String(r[i.x])}`, num(r[y]));
  }
  // For 100%-stacked, divide each cell by its x-bucket total so every bar sums to 100.
  const totals = new Map<string, number>();
  if (percent) {
    for (const c of cats) {
      let t = 0;
      for (const g of groups) t += cell.get(`${g}__${c}`) ?? 0;
      totals.set(c, t || 1);
    }
  }
  const at = (g: string, c: string) => {
    const v = cell.get(`${g}__${c}`) ?? 0;
    return percent ? (v / (totals.get(c) ?? 1)) * 100 : v;
  };
  const fmt = percent ? (v: unknown) => `${Math.round(Number(v))}%` : valueFormatter(i.rows, y, i.units);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => fmt(v) },
    legend: { data: groups },
    xAxis: {
      type: "category", data: cats,
      axisLabel: i.xKind === "time" ? { formatter: dateAxisLabel(i.rows, i.x), hideOverlap: true } : { hideOverlap: true },
    },
    yAxis: percent
      ? { type: "value", max: 100, axisLabel: { formatter: (v: number) => `${v}%` } }
      : { type: "value", axisLabel: { formatter: (v: number) => fmt(v) } },
    series: groups.map((g) => ({
      name: g, type: "bar", stack: "total", barMaxWidth: 40,
      data: cats.map((c) => at(g, c)),
    })),
  };
}

/** Parts of a whole — donut, aggregated by category, sorted descending. */
export function pieOption(i: BuildInput): EChartsOption {
  const y = i.ys[0];
  // When the measure IS already a share (pct_of_total), its value equals ECharts' own computed
  // percent — so we show the value alone, never "42.2% (42%)" twice.
  const share = isShareField(i.rows, y, i.units);
  const agg = new Map<string, number>();
  for (const r of i.rows) {
    const k = String(r[i.x]);
    agg.set(k, (agg.get(k) ?? 0) + num(r[y]));
  }
  const data = [...agg.entries()].sort((a, b) => b[1] - a[1]).map(([name, value]) => ({ name, value }));
  const fmt = valueFormatter(i.rows, y, i.units);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "item", formatter: (p: unknown) => {
      const o = p as { name: string; value: number; percent: number };
      return share ? `${o.name}: ${fmt(o.value)}` : `${o.name}: ${fmt(o.value)} (${o.percent}%)`;
    } },
    legend: { orient: "vertical", right: 0, top: "middle", type: "scroll" },
    series: [{
      type: "pie",
      radius: ["42%", "70%"],
      center: ["38%", "52%"],
      data,
      label: i.labels
        ? { show: true, formatter: (p: unknown) => {
            const o = p as { name: string; value: number; percent: number };
            return `${o.name}  ${share ? fmt(o.value) : o.percent + "%"}`;
          } }
        : { show: false },
      labelLine: { show: !!i.labels },
      emphasis: { scale: true, scaleSize: 6 },
    }],
  };
}

// Point labels stay legible only while the plot is sparse; past this they overprint.
const _SCATTER_LABEL_MAX = 40;
// One hue per group stays readable up to the palette's brand range; beyond, group into "Other".
const _SCATTER_GROUP_MAX = 8;

/** Two numerics, correlation / outlier detection. Optionally: `color` groups the
 *  points into per-category series (hue + legend = a third dimension), `pointLabel`
 *  names each point, and the exhibit spec labels points / draws quadrant dividers —
 *  the "which entities are out there" read an outlier scatter exists for. */
export function scatterOption(i: BuildInput): EChartsOption {
  const [xf, yf] = [i.x, i.ys[0]];
  const fx = valueFormatter(i.rows, xf, i.units);
  const fy = valueFormatter(i.rows, yf, i.units);
  const showPointLabels = !!i.exhibit?.label_points && !!i.pointLabel && i.rows.length <= _SCATTER_LABEL_MAX;
  const pointOf = (r: Row) => ({
    value: [num(r[xf]), num(r[yf])] as [number, number],
    name: i.pointLabel ? String(r[i.pointLabel]) : "",
  });
  const label = showPointLabels
    ? { show: true, position: "top" as const, fontSize: 10, formatter: (p: { name?: string }) => p.name ?? "" }
    : undefined;

  // Group into one series per category value (hue + legend); overflow → "Other" so a
  // long-tail dimension can't explode the legend.
  let series: Record<string, unknown>[];
  let groups: string[] = [];
  if (i.color) {
    const byGroup = new Map<string, Row[]>();
    for (const r of i.rows) {
      const g = String(r[i.color]);
      if (!byGroup.has(g)) byGroup.set(g, []);
      byGroup.get(g)!.push(r);
    }
    const ranked = [...byGroup.entries()].sort((a, b) => b[1].length - a[1].length);
    const kept = ranked.slice(0, _SCATTER_GROUP_MAX);
    const rest = ranked.slice(_SCATTER_GROUP_MAX).flatMap(([, rs]) => rs);
    const entries: [string, Row[]][] = rest.length ? [...kept, ["Other", rest]] : kept;
    groups = entries.map(([g]) => g);
    series = entries.map(([g, rs]) => ({
      name: g, type: "scatter", symbolSize: 9, data: rs.map(pointOf),
      label, labelLayout: showPointLabels ? { hideOverlap: true } : undefined,
      emphasis: { focus: "series" },
    }));
  } else {
    series = [{
      type: "scatter", symbolSize: 9, data: i.rows.map(pointOf),
      label, labelLayout: showPointLabels ? { hideOverlap: true } : undefined,
      emphasis: { focus: "series" },
    }];
  }

  // Quadrant dividers (means/medians from the exhibit) + y-axis reference lines
  // ride the first series as silent dashed markLines.
  const q = i.exhibit?.quadrant;
  const qLines: Record<string, unknown>[] = [];
  if (q?.x != null && isFinite(Number(q.x))) qLines.push({ xAxis: Number(q.x) });
  if (q?.y != null && isFinite(Number(q.y))) qLines.push({ yAxis: Number(q.y) });
  const refs = refMarkLine(i.exhibit?.ref_lines ?? [], "y", fy);
  const markData = [...qLines, ...((refs?.data as Record<string, unknown>[]) ?? [])];
  if (markData.length && series.length) {
    series[0].markLine = {
      silent: true, symbol: "none", animation: false,
      lineStyle: { type: "dashed", width: 1.25 },
      label: {
        fontSize: 10,
        formatter: (p: { data?: { name?: string }; value?: unknown }) => {
          const name = p.data?.name;
          return name ? `${name} ${fy(p.value)}` : "";
        },
      },
      data: markData,
    };
  }

  return {
    ...withTitle(i.title),
    tooltip: {
      trigger: "item",
      formatter: (p: unknown) => {
        const o = p as { value: [number, number]; name?: string; seriesName?: string };
        const who = o.name || (i.color ? o.seriesName : "");
        const head = who ? `<b>${who}</b><br/>` : "";
        return `${head}${fieldLabel(xf)}: ${fx(o.value[0])}<br/>${fieldLabel(yf)}: ${fy(o.value[1])}`;
      },
    },
    legend: groups.length > 1 ? { data: groups } : undefined,
    // With a legend row on top, drop the grid so the y-axis name doesn't collide with it.
    ...(groups.length > 1 ? { grid: { left: 8, right: 12, top: 44, bottom: 8, containLabel: true } } : {}),
    // `scale: true`: a scatter's story lives in the data's own range — anchoring at 0
    // squashes a 13–17min delay cloud into the top tenth of an empty plot.
    xAxis: { type: "value", scale: true, name: fieldLabel(xf), nameLocation: "middle", nameGap: 28, axisLabel: { formatter: (v: number) => fx(v) } },
    yAxis: { type: "value", scale: true, name: fieldLabel(yf), axisLabel: { formatter: (v: number) => fy(v) } },
    series: series as EChartsOption["series"],
  };
}

/** Dual-axis combo — bar (primary magnitude) + line (secondary, own right axis).
 *  ys = [barField, lineField]. Per-field formatting keeps a rate's % off the
 *  count axis (the percent-leak fix from the legacy Chart.tsx). */
export function comboOption(i: BuildInput): EChartsOption {
  const [barF, lineF] = [i.ys[0], i.ys[1]];
  const sorted = i.rows.slice().sort((a, b) => num(b[barF]) - num(a[barF]));
  const fb = valueFormatter(i.rows, barF, i.units);
  const fl = valueFormatter(i.rows, lineF, i.units);
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
      { name: fieldLabel(barF), type: "bar", yAxisIndex: 0, barMaxWidth: 34, data: sorted.map((r) => num(r[barF])), tooltip: { valueFormatter: (v) => fb(v) } },
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
  const fmt = valueFormatter(i.rows, valF, i.units);
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
  const fmt = valueFormatter(i.rows, valF, i.units);
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
  const fmt = valueFormatter(i.rows, valF, i.units);
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
