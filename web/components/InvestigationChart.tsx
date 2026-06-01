"use client";

import { useState } from "react";
import { VegaChart, timeseriesSpec, barSpec } from "@/components/VegaChart";
import { ChartWrapper }        from "@/components/charts/ChartWrapper";
import { ChartTypeToggle }     from "@/components/charts/ChartTypeToggle";
import { inferChartType, isShareColumn, type ChartType } from "@/components/charts/chartTypeInference";

interface Props {
  columns: string[];
  rows: unknown[][];
  title?: string;
}

function rowsToRecords(columns: string[], rows: unknown[][]): Record<string, unknown>[] {
  return rows.map(row =>
    Object.fromEntries(columns.map((col, i) => {
      let v = (row as unknown[])[i];
      if (typeof v === "string") v = v.replace(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})$/, "$1T$2");
      return [col, v];
    })),
  );
}

function normDateStr(v: string): string {
  return v.replace(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})/, "$1T$2");
}

// Aggregate rows for bar charts (avg for share columns, sum otherwise)
function aggregateForBar(
  records: Record<string, unknown>[],
  labelKey: string,
  valueKey: string,
  useAvg: boolean,
): { label: string; value: number }[] {
  const sum = new Map<string, number>();
  const cnt = new Map<string, number>();
  for (const d of records) {
    const k = String(d[labelKey]);
    sum.set(k, (sum.get(k) ?? 0) + Number(d[valueKey]));
    cnt.set(k, (cnt.get(k) ?? 0) + 1);
  }
  return Array.from(sum.entries()).map(([label, s]) => ({
    label,
    value: useAvg ? s / (cnt.get(label) ?? 1) : s,
  }));
}

export function InvestigationChart({ columns, rows, title }: Props) {
  const inferred = inferChartType(columns, rows);
  const [override, setOverride] = useState<ChartType | "auto">("auto");

  if (!inferred) return null;

  const effectiveType: ChartType = override === "auto" ? inferred.type : override;

  // Available type toggle options based on inferred type
  const available: ChartType[] = (() => {
    switch (inferred.type) {
      case "line":       return ["line", "bar"];
      case "multi-line": return ["multi-line", "heatmap", "stacked-bar"];
      case "heatmap":    return ["heatmap", "multi-line", "stacked-bar"];
      case "scatter":    return ["scatter", "bar"];
      case "pie":        return ["pie", "bar", "treemap"];
      case "treemap":    return ["treemap", "bar", "pie"];
      default:           return ["bar", "line"];
    }
  })();

  if (effectiveType === "table") return null;

  const records  = rowsToRecords(columns, rows);
  const xKey     = columns[inferred.xCol];
  const yKey     = columns[inferred.yCols[0]];
  const colorKey = inferred.colorCol !== undefined ? columns[inferred.colorCol] : undefined;
  const chartTitle = title ?? (
    effectiveType === "line" || effectiveType === "multi-line" ? "Trend" :
    effectiveType === "heatmap" ? "Distribution" : "Breakdown"
  );

  let content: React.ReactNode;

  // ── LINE ──────────────────────────────────────────────────────────────────
  if (effectiveType === "line") {
    const spec = timeseriesSpec(xKey, yKey);
    content = <VegaChart spec={spec} data={records} height={200} />;

  // ── MULTI-LINE ────────────────────────────────────────────────────────────
  } else if (effectiveType === "multi-line" && colorKey) {
    const multiData = records.map(d => ({
      ...d,
      [xKey]: typeof d[xKey] === "string" ? normDateStr(d[xKey] as string) : d[xKey],
    }));
    const spec = {
      mark: { type: "line", strokeWidth: 1.5, point: { size: 20, filled: true, opacity: 0.8 } },
      encoding: {
        x: { field: xKey,      type: "temporal",     axis: { format: "%b %y", labelAngle: -30 } },
        y: { field: yKey,      type: "quantitative",  axis: { format: "~s", grid: true } },
        color: { field: colorKey, type: "nominal",    legend: { title: colorKey.replace(/_/g, " ") } },
        tooltip: [
          { field: xKey,      type: "temporal",     format: "%b %Y" },
          { field: colorKey,  type: "nominal" },
          { field: yKey,      type: "quantitative",  format: ",.2~f" },
        ],
      },
    };
    content = <VegaChart spec={spec} data={multiData} height={220} />;

  // ── HEATMAP ───────────────────────────────────────────────────────────────
  } else if (effectiveType === "heatmap" && colorKey) {
    const heatData = records.map(d => ({
      group: typeof d[xKey] === "string"
        ? new Date(normDateStr(d[xKey] as string)).toLocaleDateString("default", { month: "short", year: "numeric" })
        : String(d[xKey]),
      stack: String(d[colorKey]),
      val:   Number(d[yKey]),
    }));
    const groupOrder = [...new Set(heatData.map(d => d.group))];
    const spec = {
      mark: { type: "rect" },
      encoding: {
        x: {
          field: "group", type: "ordinal", sort: groupOrder,
          axis: { labelAngle: -40, title: xKey.replace(/_/g, " ") },
        },
        y: {
          field: "stack", type: "ordinal",
          sort: { field: "val", op: "sum", order: "descending" },
          axis: { title: colorKey.replace(/_/g, " "), labelLimit: 100 },
        },
        color: {
          field: "val", type: "quantitative",
          scale: { scheme: "blues" },
          legend: { title: yKey.replace(/_/g, " "), orient: "right" },
        },
        tooltip: [
          { field: "group", type: "nominal" },
          { field: "stack", type: "nominal" },
          { field: "val",   type: "quantitative", format: ",.2~f" },
        ],
      },
    };
    const uniqueStacks = new Set(heatData.map(d => d.stack)).size;
    content = <VegaChart spec={spec} data={heatData} height={Math.max(200, Math.min(uniqueStacks * 18 + 60, 480))} />;

  // ── SCATTER ───────────────────────────────────────────────────────────────
  } else if (effectiveType === "scatter") {
    const yKey2 = columns[inferred.yCols[0]];
    const spec: Record<string, unknown> = {
      mark: { type: "point", opacity: 0.7, filled: true, size: 40 },
      encoding: {
        x: { field: xKey,  type: "quantitative", axis: { format: "~s", grid: true } },
        y: { field: yKey2, type: "quantitative", axis: { format: "~s", grid: true } },
        tooltip: [
          { field: xKey,  type: "quantitative" },
          { field: yKey2, type: "quantitative" },
        ],
      },
    };
    content = <VegaChart spec={spec} data={records} height={200} />;

  // ── PIE / DONUT ───────────────────────────────────────────────────────────
  } else if (effectiveType === "pie") {
    const agg = new Map<string, number>();
    records.forEach(d => {
      const k = String(d[xKey]);
      agg.set(k, (agg.get(k) ?? 0) + Number(d[yKey]));
    });
    const pieData = [...agg.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([label, value]) => ({ label, value }));
    const spec = {
      mark: { type: "arc", innerRadius: 40, outerRadius: 90 },
      encoding: {
        theta: { field: "value", type: "quantitative" },
        color: { field: "label", type: "nominal", legend: { title: xKey.replace(/_/g, " "), orient: "right" } },
        tooltip: [
          { field: "label", type: "nominal" },
          { field: "value", type: "quantitative", format: ",.2~f" },
        ],
      },
    };
    content = <VegaChart spec={spec} data={pieData} height={220} />;

  // ── STACKED BAR ───────────────────────────────────────────────────────────
  } else if (effectiveType === "stacked-bar" && colorKey) {
    const stackData = records.map(d => ({
      group: String(d[xKey]),
      stack: String(d[colorKey]),
      val:   Number(d[yKey]),
    }));
    const spec = {
      mark: { type: "bar" },
      encoding: {
        x: { field: "group", type: "ordinal", axis: { labelAngle: -20 } },
        y: { field: "val",   type: "quantitative", stack: "zero", axis: { format: "~s", grid: true } },
        color: { field: "stack", type: "nominal", legend: { title: colorKey.replace(/_/g, " ") } },
        tooltip: [
          { field: "group", type: "nominal" },
          { field: "stack", type: "nominal" },
          { field: "val",   type: "quantitative", format: ",.2~f" },
        ],
      },
    };
    content = <VegaChart spec={spec} data={stackData} height={240} />;

  // ── BAR (default) ─────────────────────────────────────────────────────────
  } else {
    const labelKey  = xKey;
    const valueKey  = yKey;
    const useAvg    = isShareColumn(valueKey, rows, inferred.yCols[0]);
    const isPct     = useAvg;
    const aggData   = aggregateForBar(records, labelKey, valueKey, useAvg);
    const xFormat   = isPct ? ".1%" : "~s";
    const spec      = barSpec("value", "label", { xFormat, maxBars: 15 });
    const barHeight = Math.max(120, Math.min(aggData.length, 15) * 26 + 40);

    content = (
      <VegaChart
        spec={{ ...spec, data: { values: aggData } }}
        height={barHeight}
      />
    );
  }

  return (
    <ChartWrapper
      title={chartTitle}
      chartType={override}
      availableTypes={available}
      onChartTypeChange={setOverride}
    >
      {content}
    </ChartWrapper>
  );
}
