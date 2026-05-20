"use client";

import { useEffect, useRef } from "react";
import * as Plot from "@observablehq/plot";

interface Props {
  columns: string[];
  rows: unknown[][];
  title?: string;
}

type ChartType = "timeseries" | "bar" | null;

// Match date/time column names broadly
const DATE_PATTERN = /_date$|_at$|_time$|created_at|updated_at|timestamp|^date$|^month$|^week$|^period$|^quarter$|^day$|^year$/i;
// Value-level date detection: YYYY-MM-DD, YYYY-MM, or ISO timestamp
const DATE_VALUE_RE = /^\d{4}-\d{2}/;
// Prefer these as the value axis in bar charts
const SHARE_PATTERN = /share|pct|percent|rate|ratio|proportion/i;
const SKIP_NUMERIC_NAMES = /id$/i;

function detectChart(columns: string[], rows: unknown[][]): {
  type: ChartType;
  xCol: number;
  yCol: number;
} | null {
  if (!columns.length || rows.length < 3) return null;

  const sample = rows.slice(0, 10);

  const isNumeric = (idx: number) =>
    !SKIP_NUMERIC_NAMES.test(columns[idx]) &&
    sample.every(r => r[idx] !== null && r[idx] !== "" && !isNaN(Number(r[idx])));

  const isDate = (idx: number) =>
    DATE_PATTERN.test(columns[idx]) ||
    (sample.length > 0 && typeof sample[0]?.[idx] === "string" && DATE_VALUE_RE.test(sample[0][idx] as string));

  const isCategory = (idx: number) =>
    !isNumeric(idx) && !isDate(idx) && typeof sample[0]?.[idx] === "string";

  const dateIdx = columns.findIndex((_, i) => isDate(i));
  const numericCols = columns.map((_, i) => i).filter(isNumeric);
  const catIdx = columns.findIndex((_, i) => isCategory(i));

  if (dateIdx >= 0 && numericCols.length > 0 && numericCols[0] !== dateIdx) {
    return { type: "timeseries", xCol: dateIdx, yCol: numericCols[0] };
  }

  if (catIdx >= 0 && numericCols.length > 0) {
    // Prefer share/rate/percent columns as the value axis
    const shareColIdx = numericCols.find(i => SHARE_PATTERN.test(columns[i]));
    const valueColIdx = shareColIdx ?? numericCols[numericCols.length - 1];
    return { type: "bar", xCol: valueColIdx, yCol: catIdx };
  }

  return null;
}

function rowsToObjects(columns: string[], rows: unknown[][]): Record<string, unknown>[] {
  return rows.map(row =>
    Object.fromEntries(columns.map((col, i) => [col, row[i]]))
  );
}

function isPercentageColumn(colName: string, data: Record<string, unknown>[]): boolean {
  if (!SHARE_PATTERN.test(colName)) return false;
  return data.every(d => {
    const v = Number(d[colName]);
    return !isNaN(v) && v >= 0 && v <= 1;
  });
}

export function InvestigationChart({ columns, rows, title }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const detected = detectChart(columns, rows);

  useEffect(() => {
    if (!containerRef.current || !detected) return;

    const data = rowsToObjects(columns, rows);
    const xKey = columns[detected.xCol];
    const yKey = columns[detected.yCol];

    const parseDate = (v: unknown) => {
      let s = typeof v === "string" ? v : String(v);
      // Normalise DuckDB timestamp "2025-05-01 00:00:00" → ISO "2025-05-01T00:00:00"
      s = s.replace(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})/, "$1T$2");
      const d = new Date(s);
      return isNaN(d.getTime()) ? v : d;
    };

    let plot: (SVGSVGElement | HTMLElement) | null = null;

    if (detected.type === "timeseries") {
      const parsed = data.map(d => ({ ...d, [xKey]: parseDate(d[xKey]), [yKey]: Number(d[yKey]) }));

      // Detect monthly cadence: all dates land on 1st of month
      const dates = parsed.map(d => d[xKey]).filter(d => d instanceof Date) as Date[];
      const isMonthly = dates.length > 1 && dates.every(d => d.getDate() === 1);
      const xTickFmt = isMonthly
        ? (d: Date) => d instanceof Date ? d.toLocaleDateString("en-US", { month: "short", year: "2-digit" }) : String(d)
        : (d: Date) => d instanceof Date ? d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) : String(d);

      plot = Plot.plot({
        style: { background: "transparent", color: "#71717a", fontSize: "11px" },
        width: containerRef.current.offsetWidth || 480,
        height: 180,
        marginLeft: 55,
        marginBottom: 32,
        x: { label: null, tickFormat: xTickFmt },
        y: { label: yKey, grid: true, tickFormat: (v: number) => v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` : v >= 1_000 ? `${(v / 1_000).toFixed(0)}k` : String(v) },
        marks: [
          Plot.areaY(parsed, { x: xKey, y: yKey, fill: "#34d399", fillOpacity: 0.08 }),
          Plot.lineY(parsed, { x: xKey, y: yKey, stroke: "#34d399", strokeWidth: 1.5 }),
          Plot.dotY(parsed, { x: xKey, y: yKey, fill: "#34d399", r: 2.5 }),
          Plot.ruleY([0], { stroke: "#3f3f46" }),
        ],
      });
    }

    if (detected.type === "bar") {
      const labelKey = columns[detected.yCol];
      const valueKey = columns[detected.xCol];
      // Aggregate per category: average for share/rate columns, sum for counts/amounts
      const aggSum = new Map<string, number>();
      const aggCnt = new Map<string, number>();
      for (const d of data) {
        const label = String(d[labelKey]);
        aggSum.set(label, (aggSum.get(label) ?? 0) + Number(d[valueKey]));
        aggCnt.set(label, (aggCnt.get(label) ?? 0) + 1);
      }
      const useAvg = SHARE_PATTERN.test(valueKey);
      const aggregated = Array.from(aggSum.entries()).map(([label, sum]) => ({
        label,
        value: useAvg ? sum / (aggCnt.get(label) ?? 1) : sum,
      }));
      const sorted = aggregated.sort((a, b) => b.value - a.value).slice(0, 15);

      const isPct = isPercentageColumn(valueKey, data);
      const xTickFormat = isPct
        ? (v: number) => `${(v * 100).toFixed(1)}%`
        : (v: number) => v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` : v >= 1_000 ? `${(v / 1_000).toFixed(0)}k` : String(v);

      plot = Plot.plot({
        style: { background: "transparent", color: "#71717a", fontSize: "11px" },
        width: containerRef.current.offsetWidth || 480,
        height: Math.max(120, sorted.length * 26 + 40),
        marginLeft: 130,
        marginBottom: 32,
        x: { label: valueKey.replace(/_/g, " "), grid: true, tickFormat: xTickFormat },
        y: { label: null },
        marks: [
          Plot.barX(sorted, {
            x: "value",
            y: "label",
            sort: { y: "-x" },
            fill: "#34d399",
            fillOpacity: 0.7,
          }),
          Plot.ruleX([0], { stroke: "#3f3f46" }),
        ],
      });
    }

    if (plot) {
      containerRef.current.innerHTML = "";
      containerRef.current.append(plot);
    }

    return () => {
      if (containerRef.current) containerRef.current.innerHTML = "";
    };
  }, [columns, rows, detected]);

  if (!detected) return null;

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wide">
        {title ?? (detected.type === "timeseries" ? "Trend" : "Breakdown")}
      </p>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 overflow-hidden">
        <div ref={containerRef} className="w-full [&_svg]:overflow-visible" />
      </div>
    </div>
  );
}
