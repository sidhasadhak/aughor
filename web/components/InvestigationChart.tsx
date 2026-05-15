"use client";

import { useEffect, useRef } from "react";
import * as Plot from "@observablehq/plot";

interface Props {
  columns: string[];
  rows: unknown[][];
  title?: string;
}

type ChartType = "timeseries" | "bar" | null;

const DATE_PATTERN = /date|month|week|day|period|year|time|_at$/i;
const SKIP_NUMERIC_NAMES = /id$/i;

function detectChart(columns: string[], rows: unknown[][]): {
  type: ChartType;
  xCol: number;
  yCol: number;
  labelCol?: number;
} | null {
  if (!columns.length || rows.length < 2) return null;

  const sample = rows.slice(0, 10);

  const isNumeric = (idx: number) =>
    !SKIP_NUMERIC_NAMES.test(columns[idx]) &&
    sample.every(r => r[idx] !== null && r[idx] !== "" && !isNaN(Number(r[idx])));

  const isDate = (idx: number) =>
    DATE_PATTERN.test(columns[idx]) ||
    sample.every(r => typeof r[idx] === "string" && !isNaN(Date.parse(r[idx] as string)));

  const isCategory = (idx: number) =>
    !isNumeric(idx) && !isDate(idx) && typeof sample[0]?.[idx] === "string";

  const dateIdx = columns.findIndex((_, i) => isDate(i));
  const numericCols = columns.map((_, i) => i).filter(isNumeric);
  const catIdx = columns.findIndex((_, i) => !isNumeric(i) && !isDate(i) && isCategory(i));

  if (dateIdx >= 0 && numericCols.length > 0) {
    return { type: "timeseries", xCol: dateIdx, yCol: numericCols[0] };
  }
  if (catIdx >= 0 && numericCols.length > 0) {
    return { type: "bar", xCol: numericCols[0], yCol: catIdx };
  }
  return null;
}

function rowsToObjects(columns: string[], rows: unknown[][]): Record<string, unknown>[] {
  return rows.map(row =>
    Object.fromEntries(columns.map((col, i) => [col, row[i]]))
  );
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
      const d = new Date(v as string);
      return isNaN(d.getTime()) ? v : d;
    };

    let plot: (SVGSVGElement | HTMLElement) | null = null;

    if (detected.type === "timeseries") {
      const parsed = data.map(d => ({ ...d, [xKey]: parseDate(d[xKey]), [yKey]: Number(d[yKey]) }));
      plot = Plot.plot({
        style: { background: "transparent", color: "#71717a", fontSize: "11px" },
        width: containerRef.current.offsetWidth || 480,
        height: 180,
        marginLeft: 55,
        marginBottom: 32,
        x: { label: xKey, tickFormat: (d: Date) => d instanceof Date ? d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) : String(d) },
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
      const sorted = [...data].sort((a, b) => Number(b[valueKey]) - Number(a[valueKey])).slice(0, 20);
      plot = Plot.plot({
        style: { background: "transparent", color: "#71717a", fontSize: "11px" },
        width: containerRef.current.offsetWidth || 480,
        height: Math.max(120, sorted.length * 22 + 40),
        marginLeft: 120,
        marginBottom: 32,
        x: { label: valueKey, grid: true, tickFormat: (v: number) => v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` : v >= 1_000 ? `${(v / 1_000).toFixed(0)}k` : String(v) },
        y: { label: null },
        marks: [
          Plot.barX(sorted, {
            x: valueKey,
            y: labelKey,
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
