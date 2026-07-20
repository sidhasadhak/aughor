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
import { type ExhibitSpec, severityRamp, rampStops, refMarkLine } from "@/components/charts/exhibit";

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
  /** Gantt: the start + end date field names (each row is one task span). */
  gantt?: { start: string; end: string } | null;
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

// ── color binding (the Databricks "Color" field) ─────────────────────────────
// A chart can colour its marks by a CHOSEN column instead of the plotted measure:
//   • a dimension  → one discrete hue per value + a legend  ("categorical")
//   • a measure    → a gradient keyed to that value + a gradient legend ("continuous")
// The scale is resolved from exhibit.color.mode when set, else inferred from whether the
// field's values are numeric. Absent a field → callers keep their prior rendering.

const REF_NEUTRAL = "#9DA1A8";

/** Is the color field numeric across the rows (→ default to a continuous gradient)? */
function colorIsNumeric(rows: Row[], field: string): boolean {
  const vals = rows.map((r) => r[field]).filter((v) => v != null && v !== "");
  if (!vals.length) return false;
  return vals.every((v) => isFinite(Number(v)));
}

/** The effective color binding for a builder: null when there's no usable field. */
function colorBinding(i: BuildInput): { field: string; scale: "categorical" | "continuous"; name: string } | null {
  const c = i.exhibit?.color;
  const field = c?.field;
  if (!field || !i.rows.length || !(field in i.rows[0])) return null;
  // Explicit mode wins; else infer from the data (numeric → gradient, else discrete).
  const scale: "categorical" | "continuous" =
    c?.mode === "continuous" ? "continuous"
    : c?.mode === "categorical" ? "categorical"
    : colorIsNumeric(i.rows, field) ? "continuous" : "categorical";
  return { field, scale, name: c?.name || fieldLabel(field) };
}

/** A small vertical gradient legend (ECharts `graphic`) for a continuous color binding —
 *  the "Haul Type 300k…100k" ramp in the Databricks screenshot. Drawn top-right; callers
 *  reserve grid space so it never overlaps the marks. */
function continuousLegend(min: number, max: number, field: string, name: string, fmt: (v: unknown) => string): Record<string, unknown>[] {
  const stops = rampStops(field);
  return [{
    type: "group", right: 8, top: 6, z: 10,
    children: [
      { type: "text", left: 0, top: 0, style: { text: name, fontSize: 10, fontWeight: 600, fill: REF_NEUTRAL } },
      { type: "rect", left: 0, top: 16, shape: { width: 11, height: 92 },
        style: { fill: { type: "linear", x: 0, y: 1, x2: 0, y2: 0, colorStops: stops } } },
      { type: "text", left: 17, top: 13, style: { text: fmt(max), fontSize: 9, fill: REF_NEUTRAL } },
      { type: "text", left: 17, top: 99, style: { text: fmt(min), fontSize: 9, fill: REF_NEUTRAL } },
    ],
  }];
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
  // Reference lines: on a horizontal bar the VALUE axis is x, so the line is vertical.
  const markLine = refMarkLine(i.exhibit?.ref_lines ?? [], style.horizontal ? "x" : "y", fmt);
  const binding = colorBinding(i);

  // 1. Categorical color-by-field (the Databricks "haul → long/short" case): one stacked,
  //    single-valued series per distinct value, so ECharts renders a real legend and each
  //    bar stays centred in its band, coloured by its group.
  if (binding && binding.scale === "categorical") {
    const groups: string[] = [];
    for (const r of rows) { const g = String(r[binding.field]); if (!groups.includes(g)) groups.push(g); }
    return {
      ...withTitle(i.title),
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => fmt(v) },
      legend: { data: groups, top: 0, type: "scroll" },
      grid: { top: 30, left: 8, right: 12, bottom: 8, containLabel: true },
      xAxis: style.horizontal ? valAxis : catAxis,
      yAxis: style.horizontal ? catAxis : valAxis,
      series: groups.map((g, gi) => ({
        name: g, type: "bar", stack: "cbind", barMaxWidth: 34,
        data: rows.map((r) => (String(r[binding.field]) === g ? num(r[y]) : null)),
        label, labelLayout: i.labels ? { hideOverlap: true } : undefined,
        emphasis: { focus: "series" },
        markLine: gi === 0 ? markLine : undefined,
      })),
    };
  }

  // 2. Continuous color-by-field (the "revenue_per_flight → gradient" case): one series,
  //    each bar coloured by that field's value via a ramp, plus a gradient legend (graphic)
  //    with grid space reserved on the right so it never overlaps the bars.
  if (binding && binding.scale === "continuous") {
    const cvals = rows.map((r) => Number(r[binding.field])).filter((v) => isFinite(v));
    const lo = cvals.length ? Math.min(...cvals) : 0, hi = cvals.length ? Math.max(...cvals) : 1;
    const ramp = severityRamp(lo, hi, binding.field);
    const cfmt = valueFormatter(i.rows, binding.field, i.units);
    return {
      ...withTitle(i.title),
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => fmt(v) },
      grid: { top: 10, left: 8, right: 76, bottom: 8, containLabel: true },
      graphic: continuousLegend(lo, hi, binding.field, binding.name, cfmt) as EChartsOption["graphic"],
      xAxis: style.horizontal ? valAxis : catAxis,
      yAxis: style.horizontal ? catAxis : valAxis,
      series: [{
        name: fieldLabel(y), type: "bar", barMaxWidth: 34, label,
        labelLayout: i.labels ? { hideOverlap: true } : undefined, markLine,
        data: values.map((v, idx) => ({ value: v, itemStyle: { color: ramp(Number(rows[idx][binding.field])) } })),
      }],
    };
  }

  // 3. No color binding → the legacy single series (byte-identical to before). Semantic color:
  //    sign-diverging keeps precedence (a change metric's sign IS its meaning); otherwise a
  //    "severity" exhibit ramps the bars by their own value — the redundant encoding that makes
  //    a worst-N ranking read at a glance.
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
      markLine,
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

  // Colour binding: a CHOSEN field drives the hue — a measure → per-point gradient +
  // gradient legend; a dimension → one series per value + legend (overflow → "Other" so a
  // long-tail dimension can't explode the legend). Absent a binding, fall back to i.color
  // (the legacy per-category grouping, e.g. an entity scatter's type hue).
  const binding = colorBinding(i);
  const continuous = binding?.scale === "continuous" ? binding : null;
  const catColorField = binding?.scale === "categorical" ? binding.field : (binding ? null : i.color);
  let series: Record<string, unknown>[];
  let groups: string[] = [];
  let graphic: Record<string, unknown>[] | undefined;

  if (continuous) {
    const cvals = i.rows.map((r) => Number(r[continuous.field])).filter((v) => isFinite(v));
    const lo = cvals.length ? Math.min(...cvals) : 0, hi = cvals.length ? Math.max(...cvals) : 1;
    const ramp = severityRamp(lo, hi, continuous.field);
    const cfmt = valueFormatter(i.rows, continuous.field, i.units);
    graphic = continuousLegend(lo, hi, continuous.field, continuous.name, cfmt);
    series = [{
      type: "scatter", symbolSize: 9,
      data: i.rows.map((r) => ({ ...pointOf(r), itemStyle: { color: ramp(Number(r[continuous.field])) } })),
      label, labelLayout: showPointLabels ? { hideOverlap: true } : undefined,
      emphasis: { focus: "series" },
    }];
  } else if (catColorField) {
    const byGroup = new Map<string, Row[]>();
    for (const r of i.rows) {
      const g = String(r[catColorField]);
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
        const who = o.name || (catColorField ? o.seriesName : "");
        const head = who ? `<b>${who}</b><br/>` : "";
        return `${head}${fieldLabel(xf)}: ${fx(o.value[0])}<br/>${fieldLabel(yf)}: ${fy(o.value[1])}`;
      },
    },
    legend: groups.length > 1 ? { data: groups } : undefined,
    // A legend row on top, or a gradient legend on the right, each reserves its own margin
    // so the axis names don't collide with it.
    ...(groups.length > 1
      ? { grid: { left: 8, right: 12, top: 44, bottom: 8, containLabel: true } }
      : continuous
        ? { grid: { left: 8, right: 76, top: 12, bottom: 8, containLabel: true } }
        : {}),
    ...(graphic ? { graphic: graphic as EChartsOption["graphic"] } : {}),
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

// ── native-fit additions (2026-07 viz-type wave) ──────────────────────────────

/** Counter — a single big-number KPI of the primary measure. A rate/share AVERAGES
 *  (summing rates is meaningless); a magnitude SUMS. Rendered as a centred title so it
 *  stays in the one <Chart>/<EChart> pipeline (PNG export + theming come for free). */
export function counterOption(i: BuildInput): EChartsOption {
  const y = i.ys[0];
  const fmt = valueFormatter(i.rows, y, i.units);
  const vals = i.rows.map((r) => num(r[y])).filter((v) => isFinite(v));
  const agg = !vals.length ? NaN
    : isShareField(i.rows, y, i.units) ? vals.reduce((a, b) => a + b, 0) / vals.length
    : vals.reduce((a, b) => a + b, 0);
  return {
    title: {
      text: isFinite(agg) ? fmt(agg) : "—",
      subtext: fieldLabel(y),
      left: "center", top: "center", itemGap: 10,
      textStyle: { fontSize: 46, fontWeight: 700 },
      subtextStyle: { fontSize: 13, fontWeight: 500 },
    },
    series: [],
  };
}

/** Funnel — an ordered drop-off across a handful of stages (aggregated by category,
 *  widest first). Parts of a process, not parts of a whole (that's a pie). */
export function funnelOption(i: BuildInput): EChartsOption {
  const y = i.ys[0];
  const agg = new Map<string, number>();
  for (const r of i.rows) { const k = String(r[i.x]); agg.set(k, (agg.get(k) ?? 0) + num(r[y])); }
  const data = [...agg.entries()].map(([name, value]) => ({ name, value }));
  const fmt = valueFormatter(i.rows, y, i.units);
  const maxV = Math.max(1, ...data.map((d) => d.value));
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "item", formatter: (p: unknown) => { const o = p as { name: string; value: number }; return `${o.name}: ${fmt(o.value)}`; } },
    legend: { type: "scroll", top: 0 },
    series: [{
      type: "funnel", left: "8%", right: "8%", top: 26, bottom: 8,
      minSize: "16%", maxSize: "100%", sort: "descending", gap: 2, min: 0, max: maxV,
      label: { show: true, position: "inside", formatter: (p: unknown) => { const o = p as { name: string; value: number }; return i.labels ? `${o.name}  ${fmt(o.value)}` : o.name; } },
      labelLine: { show: false },
      emphasis: { label: { fontWeight: 700 } },
      data,
    }],
  };
}

/** Histogram — the distribution of ONE numeric column, binned. Uses the measure (ys[0])
 *  when present, else the x column. Bin count ≈ √n, capped [6, 20]; bars sit flush. */
export function histogramOption(i: BuildInput): EChartsOption {
  const f = i.ys[0] ?? i.x;
  const vals = i.rows.map((r) => num(r[f])).filter((v) => isFinite(v)).sort((a, b) => a - b);
  const fmt = valueFormatter(i.rows, f, i.units);
  const n = vals.length;
  if (!n) return { ...withTitle(i.title) };
  const lo = vals[0], hi = vals[n - 1];
  const bins = Math.min(20, Math.max(6, Math.ceil(Math.sqrt(n))));
  const width = (hi - lo) / bins || 1;
  const counts = new Array(bins).fill(0) as number[];
  for (const v of vals) { let b = Math.floor((v - lo) / width); if (b >= bins) b = bins - 1; if (b < 0) b = 0; counts[b] += 1; }
  const labels = counts.map((_, b) => fmt(lo + b * width));
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (p: unknown) => { const a = (p as { dataIndex: number; value: number }[])[0]; const b = a.dataIndex;
        return `${fmt(lo + b * width)} – ${fmt(lo + (b + 1) * width)}<br/>count: ${a.value}`; } },
    grid: { top: 16, left: 8, right: 14, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: labels, axisLabel: { hideOverlap: true }, name: fieldLabel(f), nameLocation: "middle", nameGap: 32 },
    yAxis: { type: "value", name: "count" },
    series: [{ type: "bar", data: counts, barCategoryGap: "0%", barGap: "0%",
      label: i.labels ? { show: true, position: "top", fontSize: 10 } : undefined }],
  };
}

/** Linear-interpolated quantile of a pre-sorted array. */
function quantileSorted(sorted: number[], q: number): number {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos), rest = pos - base;
  return sorted[base + 1] !== undefined ? sorted[base] + rest * (sorted[base + 1] - sorted[base]) : sorted[base];
}
function fiveNumber(vals: number[]): [number, number, number, number, number] {
  const s = vals.slice().sort((a, b) => a - b);
  return [s[0], quantileSorted(s, 0.25), quantileSorted(s, 0.5), quantileSorted(s, 0.75), s[s.length - 1]];
}

/** Box plot — the five-number distribution (min/Q1/median/Q3/max) of the measure, one box
 *  per category when the category repeats; else a single box over all values. */
export function boxplotOption(i: BuildInput): EChartsOption {
  const y = i.ys[0];
  const fmt = valueFormatter(i.rows, y, i.units);
  const groups = new Map<string, number[]>();
  for (const r of i.rows) {
    const k = String(r[i.x]); const v = num(r[y]);
    if (!isFinite(v)) continue;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(v);
  }
  const repeats = [...groups.values()].some((a) => a.length > 1);
  let cats: string[]; let boxes: { value: number[]; name: string }[];
  if (repeats && groups.size <= 40) {
    cats = [...groups.keys()];
    boxes = cats.map((c) => ({ value: fiveNumber(groups.get(c)!), name: c }));
  } else {
    const all = i.rows.map((r) => num(r[y])).filter((v) => isFinite(v));
    cats = [fieldLabel(y)];
    boxes = [{ value: fiveNumber(all), name: fieldLabel(y) }];
  }
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "item", formatter: (p: unknown) => {
      const o = p as { name: string; value: number[] };
      const v = o.value.length >= 6 ? o.value.slice(1) : o.value;  // ECharts prepends the category index
      const [mn, q1, md, q3, mx] = v;
      return `${o.name}<br/>max ${fmt(mx)}<br/>Q3 ${fmt(q3)}<br/>median ${fmt(md)}<br/>Q1 ${fmt(q1)}<br/>min ${fmt(mn)}`;
    } },
    grid: { top: 16, left: 8, right: 14, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: cats, axisLabel: { hideOverlap: true, interval: 0 } },
    yAxis: { type: "value", scale: true, axisLabel: { formatter: (v: number) => fmt(v) } },
    series: [{ type: "boxplot", data: boxes }],
  };
}

/** Sankey — flow between TWO dimensions (x = source, color = target), weighted by the
 *  measure. Source/target names are namespaced ("s:"/"t:") so a value appearing on both
 *  sides can't fuse into one node (which would draw a cycle); labels strip the prefix. */
export function sankeyOption(i: BuildInput): EChartsOption {
  const y = i.ys[0];
  const fmt = valueFormatter(i.rows, y, i.units);
  const linkMap = new Map<string, number>();
  const nodeSet = new Set<string>();
  for (const r of i.rows) {
    const v = num(r[y]); if (!isFinite(v) || v <= 0) continue;
    const s = "s:" + String(r[i.x]);
    const t = "t:" + String(r[i.color!]);
    nodeSet.add(s); nodeSet.add(t);
    const k = s + " " + t;
    linkMap.set(k, (linkMap.get(k) ?? 0) + v);
  }
  const nodes = [...nodeSet].map((name) => ({ name }));
  const links = [...linkMap.entries()].map(([k, value]) => { const [source, target] = k.split(" "); return { source, target, value }; });
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "item", formatter: (p: unknown) => {
      const o = p as { dataType?: string; name: string; value: number; data?: { source?: string; target?: string } };
      if (o.dataType === "edge" && o.data) return `${(o.data.source ?? "").slice(2)} → ${(o.data.target ?? "").slice(2)}: ${fmt(o.value)}`;
      return `${o.name.slice(2)}: ${fmt(o.value)}`;
    } },
    series: [{
      type: "sankey", left: 8, right: 12, top: 20, bottom: 8,
      emphasis: { focus: "adjacency" }, nodeAlign: "justify", nodeGap: 10,
      label: { formatter: (p: unknown) => (p as { name: string }).name.slice(2), fontSize: 11 },
      lineStyle: { color: "gradient", opacity: 0.42 },
      data: nodes, links,
    }],
  };
}

/** Waterfall — running total of signed contributions building to a Total. A transparent
 *  "base" stack floats each delta to its running position; up moves render green, down red. */
export function waterfallOption(i: BuildInput): EChartsOption {
  const y = i.ys[0];
  const rows = i.rows.slice();
  if (i.xKind === "time") rows.sort((a, b) => new Date(normDateStr(String(a[i.x]))).getTime() - new Date(normDateStr(String(b[i.x]))).getTime());
  const gran: Gran | null = i.xKind === "time" ? detectGranularity(i.x, i.rows.map((r) => r[i.x])) : null;
  const cats = rows.map((r) => (gran ? fmtDate(String(r[i.x]), gran) : String(r[i.x])));
  const vals = rows.map((r) => num(r[y]));
  const fmt = valueFormatter(i.rows, y, i.units);
  const base: number[] = [];
  const ups: (number | "-")[] = [];
  const downs: (number | "-")[] = [];
  let sum = 0;
  for (const v of vals) {
    if (!isFinite(v)) { base.push(0); ups.push("-"); downs.push("-"); continue; }
    if (v >= 0) { base.push(sum); ups.push(v); downs.push("-"); }
    else { base.push(sum + v); ups.push("-"); downs.push(-v); }
    sum += v;
  }
  cats.push("Total"); base.push(0); ups.push(sum >= 0 ? sum : "-"); downs.push(sum < 0 ? -sum : "-");
  const dlabel = i.labels ? { show: true, fontSize: 10, formatter: (p: { value: unknown }) => (p.value === "-" ? "" : fmt(p.value)) } : undefined;
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (p: unknown) => {
      const arr = p as { name: string; axisValue?: string }[];
      const name = arr[0]?.axisValue ?? arr[0]?.name ?? "";
      const idx = cats.indexOf(name);
      const raw = idx >= 0 && idx < vals.length ? vals[idx] : sum;
      return `${name}: ${fmt(raw)}`;
    } },
    grid: { top: 16, left: 8, right: 14, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: cats, axisLabel: { hideOverlap: true, interval: 0 } },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => fmt(v) } },
    series: [
      { name: "base", type: "bar", stack: "wf", silent: true, itemStyle: { color: "transparent" }, emphasis: { itemStyle: { color: "transparent" } }, data: base },
      { name: "Increase", type: "bar", stack: "wf", barMaxWidth: 40, itemStyle: { color: "#2EC87B" }, data: ups, label: dlabel ? { ...dlabel, position: "top" } : undefined },
      { name: "Decrease", type: "bar", stack: "wf", barMaxWidth: 40, itemStyle: { color: "#E64848" }, data: downs, label: dlabel ? { ...dlabel, position: "bottom" } : undefined },
    ],
  };
}

// ── Tier-2 additions (heavier infra / narrower fit) ───────────────────────────

/** Line (forecast) — a single timeseries plus a DETERMINISTIC linear projection and a 95%
 *  confidence band. Least-squares fit on the historical points (no model, no query), extended
 *  `periods` steps at the data's own cadence. Falls back to a plain line when it can't fit. */
export function lineForecastOption(i: BuildInput, periods = 6): EChartsOption {
  const y = i.ys[0];
  const hist = categories(i.rows, i.x, "time");
  const byX = new Map(i.rows.map((r) => [String(r[i.x]), r]));
  const ys = hist.map((c) => { const r = byX.get(c); return r == null ? NaN : num(r[y]); });
  const fmt = valueFormatter(i.rows, y, i.units);
  const n = ys.length;
  const idx = ys.map((_, k) => k).filter((k) => isFinite(ys[k]));
  const N = idx.length;
  if (N < 2) return lineOption(i);
  // Least-squares fit on (k, value).
  const sx = idx.reduce((a, b) => a + b, 0);
  const sy = idx.reduce((a, k) => a + ys[k], 0);
  const sxx = idx.reduce((a, k) => a + k * k, 0);
  const sxy = idx.reduce((a, k) => a + k * ys[k], 0);
  const slope = (N * sxy - sx * sy) / (N * sxx - sx * sx || 1);
  const intercept = (sy - slope * sx) / N;
  const fit = (k: number) => intercept + slope * k;
  const resid = idx.map((k) => ys[k] - fit(k));
  const rstd = Math.sqrt(resid.reduce((a, r) => a + r * r, 0) / Math.max(1, N - 2));
  const band = 1.96 * rstd;
  // Future labels at the data's own average cadence.
  const ts = hist.map((c) => new Date(normDateStr(c)).getTime());
  const deltas = ts.slice(1).map((t, k) => t - ts[k]).filter((d) => isFinite(d) && d > 0);
  const step = deltas.length ? deltas.reduce((a, b) => a + b, 0) / deltas.length : 0;
  const gran: Gran = detectGranularity(i.x, i.rows.map((r) => r[i.x]));
  const histLabels = hist.map((c) => fmtDate(c, gran));
  const futureLabels: string[] = [];
  for (let k = 1; k <= periods; k++) futureLabels.push(fmtDate(new Date(ts[ts.length - 1] + step * k).toISOString().slice(0, 10), gran));
  const allLabels = [...histLabels, ...futureLabels];
  const histData: (number | null)[] = [...ys.map((v) => (isFinite(v) ? v : null)), ...new Array(periods).fill(null)];
  const fcData: (number | null)[] = new Array(allLabels.length).fill(null);
  const lower: (number | null)[] = new Array(allLabels.length).fill(null);
  const bandThick: (number | null)[] = new Array(allLabels.length).fill(null);
  fcData[n - 1] = ys[n - 1];   // anchor the forecast to the last actual
  for (let k = 1; k <= periods; k++) {
    const v = fit(n - 1 + k);
    fcData[n - 1 + k] = v; lower[n - 1 + k] = v - band; bandThick[n - 1 + k] = 2 * band;
  }
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "axis", valueFormatter: (v) => fmt(v) },
    legend: { data: [fieldLabel(y), "Forecast"], top: 0 },
    grid: { top: 28, left: 8, right: 14, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: allLabels, boundaryGap: false, axisLabel: { hideOverlap: true } },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => fmt(v) } },
    series: [
      { name: "band-lo", type: "line", stack: "band", data: lower, lineStyle: { opacity: 0 }, symbol: "none", silent: true },
      { name: "Forecast band", type: "line", stack: "band", data: bandThick, lineStyle: { opacity: 0 }, areaStyle: { color: "#4C8EEE", opacity: 0.14 }, symbol: "none", silent: true },
      { name: fieldLabel(y), type: "line", data: histData, showSymbol: n <= 40, symbolSize: 5, emphasis: { focus: "series" } },
      { name: "Forecast", type: "line", data: fcData, lineStyle: { type: "dashed" }, symbol: "none", emphasis: { focus: "series" } },
    ],
  };
}

/** Gantt — task spans on a time axis. Each row draws a bar from its start→end date at the
 *  task's row (custom series); an optional `color` field tints bars by category. */
export function ganttOption(i: BuildInput): EChartsOption {
  const g = i.gantt;
  if (!g) return { ...withTitle(i.title), series: [] };
  const tasks: string[] = [];
  for (const r of i.rows) { const t = String(r[i.x]); if (!tasks.includes(t)) tasks.push(t); }
  const catField = i.color && i.color !== i.x ? i.color : null;
  const groups: string[] = [];
  if (catField) for (const r of i.rows) { const c = String(r[catField]); if (!groups.includes(c)) groups.push(c); }
  const PALETTE = ["#4C8EEE", "#2EC87B", "#E6A23C", "#B37FEB", "#E64848", "#36CFC9", "#F2789F", "#9DA1A8"];
  const parse = (v: unknown) => new Date(normDateStr(String(v))).getTime();
  const fmtDay = (t: number) => fmtDate(new Date(t).toISOString().slice(0, 10), "day");
  const data = i.rows.map((r) => {
    const cat = catField ? String(r[catField]) : "";
    return {
      value: [tasks.indexOf(String(r[i.x])), parse(r[g.start]), parse(r[g.end]), cat],
      itemStyle: { color: catField ? PALETTE[Math.max(0, groups.indexOf(cat)) % PALETTE.length] : "#4C8EEE" },
    };
  });
  const ganttSeries = {
    type: "custom",
    renderItem: (_params: unknown, api: { value: (d: number) => number; coord: (p: number[]) => number[]; size: (p: number[]) => number[]; style: () => Record<string, unknown> }) => {
      const taskIndex = api.value(0);
      const start = api.coord([api.value(1), taskIndex]);
      const end = api.coord([api.value(2), taskIndex]);
      const h = api.size([0, 1])[1] * 0.58;
      return { type: "rect", shape: { x: start[0], y: start[1] - h / 2, width: Math.max(2, end[0] - start[0]), height: h, r: 3 }, style: api.style() };
    },
    encode: { x: [1, 2], y: 0 },
    data,
  };
  return {
    ...withTitle(i.title),
    tooltip: { formatter: (p: unknown) => {
      const o = p as { value: [number, number, number, string] };
      return `${tasks[o.value[0]]}${o.value[3] ? " · " + o.value[3] : ""}<br/>${fmtDay(o.value[1])} → ${fmtDay(o.value[2])}`;
    } },
    grid: { top: 12, left: 8, right: 14, bottom: 8, containLabel: true },
    xAxis: { type: "time", axisLabel: { hideOverlap: true } },
    yAxis: { type: "category", data: tasks, inverse: true },
    series: [ganttSeries] as EChartsOption["series"],
  };
}

// Base-map area/border colours read on both themes (the map geojson carries no colour).
const MAP_AREA = "#20242b";
const MAP_BORDER = "#3a4048";

/** Choropleth — a region column (its values must match the world map's country names)
 *  shaded by the measure via a continuous visualMap. Unmatched names simply stay neutral. */
export function choroplethOption(i: BuildInput): EChartsOption {
  const y = i.ys[0];
  const agg = new Map<string, number>();
  for (const r of i.rows) { const k = String(r[i.x]); agg.set(k, (agg.get(k) ?? 0) + num(r[y])); }
  const data = [...agg.entries()].map(([name, value]) => ({ name, value }));
  const vals = data.map((d) => d.value).filter((v) => isFinite(v));
  const fmt = valueFormatter(i.rows, y, i.units);
  const min = vals.length ? Math.min(...vals) : 0, max = vals.length ? Math.max(...vals) : 1;
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "item", formatter: (p: unknown) => { const o = p as { name: string; value: number }; return `${o.name}: ${isFinite(o.value) ? fmt(o.value) : "—"}`; } },
    visualMap: {
      type: "continuous", min, max: max > min ? max : min + 1, calculable: true, left: 8, bottom: 8,
      inRange: { color: rampStops(y).map((s) => s.color) },
      textStyle: { fontSize: 10 }, formatter: (v: number) => fmt(v),
    } as unknown as EChartsOption["visualMap"],
    series: [{
      type: "map", map: "world", roam: true, nameProperty: "name", data,
      itemStyle: { areaColor: MAP_AREA, borderColor: MAP_BORDER, borderWidth: 0.4 },
      emphasis: { label: { show: false }, itemStyle: { areaColor: "#2a2f37" } },
      select: { disabled: true },
    }],
  };
}

/** Point map — lat/lon points on the world base layer, sized by the measure when present.
 *  `pointLabel` (from BuildInput) names each point in the tooltip. */
export function pointMapOption(i: BuildInput, latField: string, lonField: string): EChartsOption {
  const y = i.ys[0];
  const fmt = y ? valueFormatter(i.rows, y, i.units) : null;
  const data = i.rows
    .map((r) => ({ name: i.pointLabel ? String(r[i.pointLabel]) : "", value: [num(r[lonField]), num(r[latField]), y ? num(r[y]) : 1] as number[] }))
    .filter((d) => isFinite(d.value[0]) && isFinite(d.value[1]));
  const sizes = data.map((d) => d.value[2]).filter((v) => isFinite(v));
  const smin = sizes.length ? Math.min(...sizes) : 0, smax = sizes.length ? Math.max(...sizes) : 1;
  const sizeOf = (v: number) => (smax > smin ? 6 + 18 * (v - smin) / (smax - smin) : 9);
  return {
    ...withTitle(i.title),
    tooltip: { trigger: "item", formatter: (p: unknown) => {
      const o = p as { name: string; value: number[] };
      const head = o.name ? `<b>${o.name}</b><br/>` : "";
      const metric = y && fmt ? `<br/>${fieldLabel(y)}: ${fmt(o.value[2])}` : "";
      return `${head}${o.value[1].toFixed(2)}, ${o.value[0].toFixed(2)}${metric}`;
    } },
    geo: { map: "world", roam: true, itemStyle: { areaColor: MAP_AREA, borderColor: MAP_BORDER, borderWidth: 0.4 }, emphasis: { itemStyle: { areaColor: "#2a2f37" }, label: { show: false } } },
    series: [{
      type: "scatter", coordinateSystem: "geo", data,
      symbolSize: (val: number[]) => sizeOf(val[2]),
      itemStyle: { color: "#4C8EEE", opacity: 0.82, borderColor: "#0e2440", borderWidth: 0.5 },
    }],
  };
}
