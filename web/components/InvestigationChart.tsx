"use client";

/**
 * InvestigationChart — report/exploration/query-builder chart surface.
 *
 * It owns the *chrome* (card, title, the user-facing chart-type toggle, the
 * data-labels button) but delegates all rendering to the single canonical
 * <Chart> engine (chromeless mode). This is the convergence: chat and reports
 * now build their charts from ONE engine — no more parallel spec-builders.
 *
 * Type vocab bridge: chartTypeInference emits hyphenated ChartType names; the
 * <Chart> engine speaks underscore "hints". TYPE_TO_HINT maps between them.
 * grouped-bar folds into combo (multi-measure comparison) and matrix into
 * heatmap (a matrix IS a heatmap) — the two types the engine doesn't render
 * natively; both are kept out of the offered toggle options below.
 */

import { useState } from "react";
import { ChartWrapper } from "@/components/charts/ChartWrapper";
import { inferChartType, availableTypesFor, type ChartType } from "@/components/charts/chartTypeInference";
import { Chart, type ChartCustom } from "@/components/Chart";

interface Props {
  columns: string[];
  rows: unknown[][];
  title?: string;
  /** Controlled mode — an outer rail (the Query Builder Explore panel) owns the chart type
   *  and data-labels, so the internal toggle/labels chrome is hidden here. */
  controlled?: boolean;
  typeOverride?: ChartType | "auto";
  showLabels?: boolean;
  custom?: ChartCustom | null;
  /** Scale the chart height (e.g. 0.75 for compact briefing cards). */
  heightScale?: number;
}

const TYPE_TO_HINT: Record<ChartType, string> = {
  "line":        "line",
  "area":        "area",
  "multi-line":  "multi_line",
  "bar":         "bar",
  "grouped-bar": "combo",
  "combo":       "combo",
  "stacked-bar": "stacked_bar",
  "scatter":     "scatter",
  "heatmap":     "heatmap",
  "matrix":      "heatmap",
  "pie":         "pie",
  "treemap":     "treemap",
  "table":       "auto",
};

export function InvestigationChart({ columns, rows, title, controlled, typeOverride, showLabels: showLabelsProp, custom, heightScale }: Props) {
  const inferred = inferChartType(columns, rows);
  const [overrideState, setOverride] = useState<ChartType | "auto">("auto");
  const [showLabelsState, setShowLabels] = useState(false);

  // Controlled mode: the outer rail owns type + labels; otherwise use the internal toggles.
  const override = controlled ? (typeOverride ?? "auto") : overrideState;
  const showLabels = controlled ? (showLabelsProp ?? false) : showLabelsState;

  if (!inferred) return null;

  const effectiveType: ChartType = override === "auto" ? inferred.type : override;
  if (effectiveType === "table") return null;

  // Toggle options — restricted to types the unified <Chart> engine renders.
  const available: ChartType[] = availableTypesFor(inferred.type);

  const chartTitle = title ?? (
    effectiveType === "line" || effectiveType === "multi-line" ? "Trend" :
    effectiveType === "heatmap" ? "Distribution" :
    effectiveType === "combo" ? "Metrics" : "Breakdown"
  );

  // When the user hasn't overridden, let <Chart> use its own auto-inference
  // (identical to chat); a manual pick forces that type.
  const hint = override === "auto" ? "auto" : (TYPE_TO_HINT[override] ?? "auto");

  return (
    <ChartWrapper
      title={chartTitle}
      chartType={override}
      availableTypes={available}
      onChartTypeChange={controlled ? undefined : setOverride}
      actions={controlled ? undefined : (
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
      )}
    >
      <Chart
        columns={columns}
        rows={rows}
        chartType={hint}
        chrome={false}
        showLabels={showLabels}
        custom={custom}
        title={chartTitle}
        heightScale={heightScale}
      />
    </ChartWrapper>
  );
}
