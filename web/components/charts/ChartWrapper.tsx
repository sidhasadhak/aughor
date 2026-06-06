"use client";

import React from "react";
import { ChartSkeleton } from "./ChartSkeleton";
import { ChartTypeToggle } from "./ChartTypeToggle";
import type { ChartType } from "./chartTypeInference";

interface Props {
  /** Card title — rendered above the chart in standard position */
  title?: string;
  /** Sub-label: metric name, time range, row count, etc. */
  subtitle?: string;
  loading?: boolean;
  error?: string | null;
  /** True when the query returned 0 rows or the data cannot be charted */
  empty?: boolean;
  emptyMessage?: string;
  height?: number;
  /** Slot for the ChartTypeToggle or other top-right actions */
  actions?: React.ReactNode;
  /** Current user-selected chart type override (passed down from parent) */
  chartType?: ChartType | "auto";
  availableTypes?: ChartType[];
  onChartTypeChange?: (t: ChartType | "auto") => void;
  children: React.ReactNode;
}

export function ChartWrapper({
  title,
  subtitle,
  loading,
  error,
  empty,
  emptyMessage = "No data for this period",
  height = 240,
  actions,
  chartType,
  availableTypes,
  onChartTypeChange,
  children,
}: Props) {
  const showToggle = chartType !== undefined && availableTypes && onChartTypeChange;

  return (
    <div className="flex flex-col gap-1.5">
      {/* Header row */}
      {(title || subtitle || showToggle || actions) && (
        <div className="flex items-center justify-between gap-2 min-h-[20px]">
          <div className="flex flex-col gap-0">
            {title && (
              <span className="aug-text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--t3)" }}>
                {title}
              </span>
            )}
            {subtitle && (
              <span className="aug-text-xs" style={{ color: "var(--t3)" }}>
                {subtitle}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {showToggle && (
              <ChartTypeToggle
                value={chartType}
                available={availableTypes}
                onChange={onChartTypeChange}
              />
            )}
            {actions}
          </div>
        </div>
      )}

      {/* Chart body */}
      <div
        className="rounded-md"
        style={{
          border: "1px solid var(--chart-grid)",
          background: "transparent",
          padding: "10px 12px",
          minHeight: loading || empty || error ? height : undefined,

        }}
      >
        {loading ? (
          <ChartSkeleton height={height - 24} />
        ) : error ? (
          <div
            className="flex flex-col items-center justify-center gap-2 h-full"
            style={{ minHeight: height - 24 }}
          >
            <span className="text-xs font-semibold" style={{ color: "var(--red4)" }}>
              Chart error
            </span>
            <span className="text-xs text-center max-w-xs" style={{ color: "var(--t3)" }}>
              {error}
            </span>
            <span className="text-[11px] px-2 py-0.5 rounded border" style={{ borderColor: "var(--red3)", color: "var(--red4)" }}>
              Retry by refreshing the query
            </span>
          </div>
        ) : empty ? (
          <div
            className="flex flex-col items-center justify-center gap-1 h-full"
            style={{ minHeight: height - 24, color: "var(--t3)" }}
          >
            <span className="text-2xl opacity-30">◈</span>
            <span className="text-xs">{emptyMessage}</span>
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  );
}
