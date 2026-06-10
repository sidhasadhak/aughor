"use client";

/**
 * Sparkline + TrendStrip — a compact glanceable trend for time-series findings.
 *
 * The ADA EvidenceBlock already renders a full chart, but it never STATES the
 * period-over-period delta as a number. TrendStrip adds that: a tiny inline
 * sparkline + a signed "%  vs prior <period>" (MoM/WoW/YoY, inferred from the
 * date granularity). Net-new information, render-only — no backend change.
 */

import React, { useMemo } from "react";
import { DATE_COL, DATE_VALUE_RE, isNumeric, firstNonNull } from "@/components/charts/columnRoles";
import { detectGranularity, type Gran } from "@/lib/format";

// ── Pure SVG sparkline ─────────────────────────────────────────────────────────
export function Sparkline({
  values,
  width = 72,
  height = 18,
  color = "#818cf8",
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  const clean = values.filter(v => typeof v === "number" && !isNaN(v));
  if (clean.length < 2) return null;

  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;
  const pad = 1.5;
  const w = width - pad * 2;
  const h = height - pad * 2;
  const x = (i: number) => pad + (i / (clean.length - 1)) * w;
  const y = (v: number) => pad + (1 - (v - min) / span) * h;

  const line = clean.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(clean.length - 1).toFixed(1)},${(height - pad).toFixed(1)} L${x(0).toFixed(1)},${(height - pad).toFixed(1)} Z`;
  const lastUp = clean[clean.length - 1] >= clean[0];
  const endColor = lastUp ? "#34d399" : "#f87171";

  return (
    <svg width={width} height={height} className="shrink-0 align-middle" aria-hidden>
      <path d={area} fill={color} fillOpacity={0.12} />
      <path d={line} fill="none" stroke={color} strokeWidth={1.25} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(clean.length - 1)} cy={y(clean[clean.length - 1])} r={1.8} fill={endColor} />
    </svg>
  );
}

// ── Series-trend extraction ────────────────────────────────────────────────────
const PERIOD_LABEL: Record<Gran, string> = {
  day: "DoD", week: "WoW", month: "MoM", quarter: "QoQ", year: "YoY",
};

export interface SeriesTrend {
  values: number[];
  lastDelta: number | null;   // fractional period-over-period change (0.12 = +12%)
  periodLabel: string;        // MoM / WoW / YoY …
}

/** Pull an ordered numeric series out of a (date, …, value) result, if one exists. */
export function seriesTrend(columns: string[], rows: (string | number | null)[][]): SeriesTrend | null {
  if (!columns.length || rows.length < 3) return null;

  const looksLikeDate = (i: number) => {
    const v = firstNonNull(rows as unknown[][], i);
    return typeof v === "string" && DATE_VALUE_RE.test(v);
  };
  const dateIdx = columns.findIndex((c, i) => DATE_COL.test(c) || looksLikeDate(i));
  if (dateIdx === -1) return null;

  // First numeric column that isn't the date itself.
  const numIdx = columns.findIndex((c, i) => i !== dateIdx && isNumeric(firstNonNull(rows as unknown[][], i)));
  if (numIdx === -1) return null;

  const sorted = [...rows]
    .filter(r => r[dateIdx] != null && r[numIdx] != null)
    .sort((a, b) => String(a[dateIdx]).localeCompare(String(b[dateIdx])));
  if (sorted.length < 3) return null;

  const values = sorted.map(r => Number(r[numIdx])).filter(v => !isNaN(v));
  if (values.length < 3) return null;

  const prev = values[values.length - 2];
  const last = values[values.length - 1];
  const lastDelta = prev !== 0 ? (last - prev) / Math.abs(prev) : null;

  const gran = detectGranularity(columns[dateIdx], sorted.map(r => r[dateIdx]));
  return { values, lastDelta, periodLabel: PERIOD_LABEL[gran] ?? "vs prior" };
}

// ── TrendStrip — sparkline + signed period delta ───────────────────────────────
export function TrendStrip({
  columns,
  rows,
  className = "",
}: {
  columns: string[];
  rows: (string | number | null)[][];
  className?: string;
}) {
  const trend = useMemo(() => seriesTrend(columns, rows), [columns, rows]);
  if (!trend) return null;

  const { values, lastDelta, periodLabel } = trend;
  const up = (lastDelta ?? 0) >= 0;
  const deltaTxt = lastDelta == null
    ? null
    : `${up ? "+" : ""}${(lastDelta * 100).toFixed(1)}%`;

  return (
    <div className={`flex items-center gap-2 aug-text-xs text-zinc-500 ${className}`}>
      <Sparkline values={values} />
      {deltaTxt && (
        <span>
          <span className={`font-mono ${up ? "text-emerald-400" : "text-red-400"}`}>{deltaTxt}</span>
          <span className="text-zinc-600"> {periodLabel}</span>
        </span>
      )}
    </div>
  );
}
