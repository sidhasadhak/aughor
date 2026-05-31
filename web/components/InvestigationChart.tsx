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

  // Nothing chartable
  if (!inferred) {
    return null;
  }

  const effectiveType: ChartType = override === "auto" ? inferred.type : override;

  // Available type toggle options based on inferred type
  const available: ChartType[] = inferred.type === "line"
    ? ["line", "bar"]
    : inferred.type === "scatter"
    ? ["scatter", "bar"]
    : ["bar", "line"];

  // "table" mode — render nothing here; the caller always shows a table alongside
  if (effectiveType === "table") return null;

  const records  = rowsToRecords(columns, rows);
  const xKey     = columns[inferred.xCol];
  const yKey     = columns[inferred.yCols[0]];
  const chartTitle = title ?? (effectiveType === "line" ? "Trend" : "Breakdown");

  let content: React.ReactNode;

  if (effectiveType === "line") {
    const spec = timeseriesSpec(xKey, yKey);
    content = <VegaChart spec={spec} data={records} height={200} />;
  } else if (effectiveType === "scatter") {
    const yKey2 = columns[inferred.yCols[0]];
    const spec: Record<string, unknown> = {
      mark: { type: "point", opacity: 0.7, filled: true, size: 40 },
      encoding: {
        x: { field: xKey, type: "quantitative", axis: { format: "~s", grid: true } },
        y: { field: yKey2, type: "quantitative", axis: { format: "~s", grid: true } },
        tooltip: [
          { field: xKey, type: "quantitative" },
          { field: yKey2, type: "quantitative" },
        ],
      },
    };
    content = <VegaChart spec={spec} data={records} height={200} />;
  } else {
    // bar — aggregate and use horizontal bar spec
    const labelKey  = xKey;   // category on y-axis
    const valueKey  = yKey;   // value on x-axis
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
