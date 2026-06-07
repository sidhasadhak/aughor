"use client";

import { useState } from "react";
import { VegaChart, timeseriesSpec, barSpec } from "@/components/VegaChart";
import { ChartWrapper }        from "@/components/charts/ChartWrapper";
import { ChartTypeToggle }     from "@/components/charts/ChartTypeToggle";
import { inferChartType, isShareColumn, type ChartType } from "@/components/charts/chartTypeInference";
import { normDateStr, cleanLabel as cleanTitle } from "@/lib/format";

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
      // Sanitize NaN/Infinity/empty strings for Vega
      if (typeof v === "number") {
        if (Number.isNaN(v) || !Number.isFinite(v)) v = null;
      }
      if (v === "" || v === undefined) v = null;
      return [col, v];
    })),
  );
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
  const [showLabels, setShowLabels] = useState(false);

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
      case "grouped-bar": return ["grouped-bar", "bar", "line"];
      case "combo":      return ["combo", "grouped-bar", "bar"];
      case "matrix":     return ["matrix", "heatmap", "bar"];
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
    effectiveType === "heatmap" ? "Distribution" :
    effectiveType === "matrix" ? "Matrix" :
    effectiveType === "grouped-bar" ? "Comparison" :
    effectiveType === "combo" ? "Metrics" : "Breakdown"
  );

  let content: React.ReactNode;

  // ── LINE ──────────────────────────────────────────────────────────────────
  if (effectiveType === "line") {
    // Auto-detect date span and pick a readable axis format
    let xFormat = "%b %d, %Y";
    try {
      const dates = records.map(d => new Date(String(d[xKey]).replace(/ /, "T"))).filter(d => !isNaN(d.getTime()));
      if (dates.length >= 2) {
        const min = new Date(Math.min(...dates.map(d=>d.getTime())));
        const max = new Date(Math.max(...dates.map(d=>d.getTime())));
        const days = (max.getTime() - min.getTime()) / 86400000;
        if (days <= 1) xFormat = "%H:%M";
        else if (days <= 7) xFormat = "%a %H:%M";
        else if (days <= 90) xFormat = "%b %d";
        else if (days <= 730) xFormat = "%b %Y";
        else xFormat = "%Y";
      }
    } catch {}

    // If multiple numeric columns (measures), melt to multi-line
    if (inferred.yCols.length > 1) {
      const melted: Record<string, unknown>[] = [];
      for (const rec of records) {
        for (const yi of inferred.yCols) {
          const measure = columns[yi];
          melted.push({
            [xKey]: rec[xKey],
            measure,
            value: rec[measure],
          });
        }
      }
      const spec = {
        mark: { type: "line", strokeWidth: 1.5 },
        encoding: {
          x: { field: xKey, type: "temporal", axis: { format: xFormat, labelAngle: 0, labelOverlap: true } },
          y: { field: "value", type: "quantitative", axis: { format: "~s", grid: true } },
          color: { field: "measure", type: "nominal", legend: { title: "" } },
          tooltip: [
            { field: xKey, type: "temporal" },
            { field: "measure", type: "nominal" },
            { field: "value", type: "quantitative", format: ",.2~f" },
          ],
        },
      };
      content = <VegaChart spec={spec} data={melted} height={350} />;
    } else {
      const spec = timeseriesSpec(xKey, yKey, { xFormat });
      content = <VegaChart spec={spec} data={records} height={350} />;
    }

  // ── MULTI-LINE ────────────────────────────────────────────────────────────
  } else if (effectiveType === "multi-line" && colorKey) {
    let xFormat = "%b %d, %Y";
    try {
      const dates = records.map(d => new Date(String(d[xKey]).replace(/ /, "T"))).filter(d => !isNaN(d.getTime()));
      if (dates.length >= 2) {
        const min = new Date(Math.min(...dates.map(d=>d.getTime())));
        const max = new Date(Math.max(...dates.map(d=>d.getTime())));
        const days = (max.getTime() - min.getTime()) / 86400000;
        if (days <= 1) xFormat = "%H:%M";
        else if (days <= 7) xFormat = "%a %H:%M";
        else if (days <= 90) xFormat = "%b %d";
        else if (days <= 730) xFormat = "%b %Y";
        else xFormat = "%Y";
      }
    } catch {}
    const multiData = records.map(d => ({
      ...d,
      [xKey]: typeof d[xKey] === "string" ? normDateStr(d[xKey] as string) : d[xKey],
    }));
    const spec = {
      mark: { type: "line", strokeWidth: 1.5, point: { size: 20, filled: true, opacity: 0.8 } },
      encoding: {
        x: { field: xKey,      type: "temporal",     axis: { format: xFormat, labelAngle: 0, labelOverlap: true } },
        y: { field: yKey,      type: "quantitative",  axis: { format: "~s", grid: true } },
        color: { field: colorKey, type: "nominal",    legend: { title: colorKey.replace(/_/g, " ") } },
        tooltip: [
          { field: xKey,      type: "temporal",     format: "%b %d, %Y" },
          { field: colorKey,  type: "nominal" },
          { field: yKey,      type: "quantitative",  format: ",.2~f" },
        ],
      },
    };
    content = <VegaChart spec={spec} data={multiData} height={350} />;

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
          axis: { labelAngle: 0, title: xKey.replace(/_/g, " ") },
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
    content = <VegaChart spec={spec} data={heatData} height={Math.max(350, uniqueStacks * 18 + 60)} />;

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
    content = <VegaChart spec={spec} data={records} height={350} />;

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
    content = <VegaChart spec={spec} data={pieData} height={350} />;

  // ── COMBO (bar + line, dual y-axes) ─────────────────────────────────────
  } else if (effectiveType === "combo") {
    const primary   = columns[inferred.yCols[0]];   // bars
    const secondary = inferred.yCols[1] !== undefined ? columns[inferred.yCols[1]] : primary;
    const comboSpec = {
      layer: [
        {
          mark: { type: "bar", color: "#818cf8", opacity: 0.8, cornerRadiusEnd: 2 },
          encoding: {
            x: { field: xKey, type: "ordinal", sort: { field: primary, order: "descending" }, axis: { labelLimit: 160, labelAngle: 0, labelOverlap: true, title: cleanTitle(xKey) } },
            y: { field: primary, type: "quantitative", axis: { format: "~s", grid: true, title: cleanTitle(primary) } },
            tooltip: [
              { field: xKey, type: "nominal" },
              { field: primary, type: "quantitative", format: ",.2~f", title: cleanTitle(primary) },
            ],
          },
        },
        {
          mark: { type: "line", color: "#E64848", strokeWidth: 2, point: { size: 30, filled: true, opacity: 0.9 } },
          encoding: {
            x: { field: xKey, type: "ordinal", sort: { field: primary, order: "descending" } },
            y: { field: secondary, type: "quantitative", axis: { format: "~s", title: cleanTitle(secondary) } },
            tooltip: [
              { field: xKey, type: "nominal" },
              { field: secondary, type: "quantitative", format: ",.2~f", title: cleanTitle(secondary) },
            ],
          },
        },
      ],
      resolve: { scale: { y: "independent" } },
      config: { axisX: { labelAngle: 0, labelOverlap: "parity" } },
    };
    const groupCount = new Set(rows.map(r => String((r as unknown[])[inferred.xCol]))).size;
    const comboHeight = 350;
    content = <VegaChart spec={comboSpec} data={records} height={comboHeight} />;

  // ── GROUPED BAR ───────────────────────────────────────────────────────────
  } else if (effectiveType === "grouped-bar") {
    const groupKey = xKey;
    const measureKeys = inferred.yCols.map(i => columns[i]);
    const melted = records.flatMap(d =>
      measureKeys.map(mk => ({
        group: String(d[groupKey]),
        measure: mk.replace(/_/g, " "),
        value: Number(d[mk]),
      }))
    );
    const spec = {
      mark: { type: "bar" },
      encoding: {
        x: { field: "group", type: "ordinal", axis: { labelAngle: 0, title: cleanTitle(groupKey) } },
        y: { field: "value", type: "quantitative", axis: { format: "~s", grid: true, title: "" } },
        color: { field: "measure", type: "nominal", legend: { title: "" } },
        xOffset: { field: "measure", type: "nominal" },
        tooltip: [
          { field: "group", type: "nominal" },
          { field: "measure", type: "nominal" },
          { field: "value", type: "quantitative", format: ",.2~f" },
        ],
      },
    };
    const groupCount = new Set(melted.map(d => d.group)).size;
    const measureCount = measureKeys.length;
    const barHeight = Math.max(350, groupCount * measureCount * 22 + 60);
    content = <VegaChart spec={spec} data={melted} height={barHeight} />;

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
        x: { field: "group", type: "ordinal", axis: { labelAngle: 0 } },
        y: { field: "val",   type: "quantitative", stack: "zero", axis: { format: "~s", grid: true } },
        color: { field: "stack", type: "nominal", legend: { title: colorKey.replace(/_/g, " ") } },
        tooltip: [
          { field: "group", type: "nominal" },
          { field: "stack", type: "nominal" },
          { field: "val",   type: "quantitative", format: ",.2~f" },
        ],
      },
    };
content = <VegaChart spec={spec} data={stackData} height={350} />;

  // ── MATRIX (pivot / cross-tab heatmap) ────────────────────────────────────
  } else if (effectiveType === "matrix" && colorKey) {
    const matrixData = records.map(d => ({
      row: String(d[xKey]),
      col: String(d[colorKey]),
      val: Number(d[yKey]),
    }));
    const rowOrder = [...new Set(matrixData.map(d => d.row))];
    const colOrder = [...new Set(matrixData.map(d => d.col))];
    const spec = {
      mark: { type: "rect", stroke: "var(--chart-grid)", strokeWidth: 0.5 },
      encoding: {
        x: {
          field: "col", type: "ordinal", sort: colOrder,
          axis: { title: cleanTitle(colorKey), labelAngle: 0, labelLimit: 120 },
          scale: { paddingInner: 0.02 },
        },
        y: {
          field: "row", type: "ordinal", sort: rowOrder,
          axis: { title: cleanTitle(xKey), labelLimit: 120 },
          scale: { paddingInner: 0.02 },
        },
        color: {
          field: "val", type: "quantitative",
          scale: { scheme: "viridis" },
          legend: { title: cleanTitle(yKey), orient: "right" },
        },
        tooltip: [
          { field: "row", type: "nominal", title: cleanTitle(xKey) },
          { field: "col", type: "nominal", title: cleanTitle(colorKey) },
          { field: "val", type: "quantitative", format: ",.2~f", title: cleanTitle(yKey) },
        ],
      },
      config: {
        axis: { grid: false, domain: false },
        view: { stroke: "transparent" },
      },
    };
    const rowCount = rowOrder.length;
    const colCount = colOrder.length;
    const mHeight = Math.max(200, Math.min(rowCount * 24 + 60, 600));
    const mWidth  = Math.max(320, Math.min(colCount * 50 + 160, 900));
    content = (
      <div style={{ overflowX: "auto", overflowY: "hidden" }}>
        <VegaChart spec={spec} data={matrixData} height={mHeight} className="min-w-0" showLabels={showLabels} />
      </div>
    );

  // ── BAR (default) ─────────────────────────────────────────────────────────
  } else {
    const labelKey  = xKey;
    const valueKey  = yKey;
    const useAvg    = isShareColumn(valueKey, rows, inferred.yCols[0]);
    const isPct     = useAvg;
    const aggData   = aggregateForBar(records, labelKey, valueKey, useAvg);
    const xFormat   = isPct ? ".1%" : "~s";
    // Data is keyed value/label, but title the axes with the real column names.
    const spec      = barSpec("value", "label", {
      xFormat,
      xTitle: cleanTitle(valueKey),
      yTitle: cleanTitle(labelKey),
    });
    const barHeight = Math.min(350, Math.max(120, aggData.length * 26 + 40));

    content = (
      <VegaChart
        spec={{ ...spec, data: { values: aggData } }}
        height={Math.max(350, barHeight)}
      />
    );
  }

  return (
    <ChartWrapper
      title={chartTitle}
      chartType={override}
      availableTypes={available}
      onChartTypeChange={setOverride}
      actions={
        <button
          onClick={() => setShowLabels(s => !s)}
          title={showLabels ? "Hide data labels" : "Show data labels"}
          className={`w-6 h-6 flex items-center justify-center rounded transition-colors ${showLabels ? "bg-blue-500/20 text-blue-300" : "bg-zinc-800/80 hover:bg-zinc-700 text-zinc-500 hover:text-zinc-200"}`}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 7V4h3" />
            <path d="M4 17v3h3" />
            <path d="M20 7V4h-3" />
            <path d="M20 17v3h-3" />
            <path d="M9 9h6v6H9z" />
          </svg>
        </button>
      }
    >
      <div style={{ overflowX: "auto", overflowY: "auto", maxHeight: 350 }}>
        {content}
      </div>
    </ChartWrapper>
  );
}
