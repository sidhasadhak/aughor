"use client";

import { useEffect, useState } from "react";
import { getHealthScorecard, getPlatformMetrics, getAuditStats, type ScorecardItem, type HealthStatus, type PlatformMetrics, type AuditStats } from "@/lib/api";
import { compactNumber, formatVariance } from "@/lib/format";

const STATUS_COLORS: Record<HealthStatus, { bg: string; border: string; dot: string; text: string; label: string }> = {
  green:   { bg: "var(--bg-1)", border: "var(--b1)", dot: "var(--t3)", text: "var(--t3)", label: "On target" },
  yellow:  { bg: "var(--amb1)", border: "var(--amb2)", dot: "var(--amb4)", text: "var(--amb4)", label: "Warning" },
  red:     { bg: "var(--red1)", border: "var(--red2)", dot: "var(--red4)", text: "var(--red4)", label: "Off target" },
  unknown: { bg: "var(--bg-1)", border: "var(--b1)", dot: "var(--t3)", text: "var(--t3)", label: "No data" },
};

function fmtValue(v: number | null, unit: string | null): string {
  if (v === null) return "—";
  const num = Math.abs(v);
  let formatted: string;
  if (num >= 1_000) formatted = compactNumber(v, 1);
  else if (num < 1 && num > 0 && unit === "%") formatted = (v * 100).toFixed(1);
  else formatted = v.toFixed(num < 10 ? 2 : 0);
  return unit ? `${formatted}${unit === "$" ? "" : " "}${unit === "$" ? "" : unit}` : formatted;
}

function fmtVariance(v: number | null): string {
  if (v === null) return "";
  return formatVariance(v, 1);
}

function MetricHealthCard({
  item,
  onInvestigate,
}: {
  item: ScorecardItem;
  onInvestigate: (label: string) => void;
}) {
  const s = STATUS_COLORS[item.status];
  return (
    <div
      className="flex flex-col gap-3 rounded-md p-4 transition-all"
      style={{ background: s.bg, border: `0.5px solid ${s.border}` }}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-[6px] h-[6px] rounded-full shrink-0" style={{ background: s.dot }} />
          <span className="text-[11px] font-mono" style={{ color: s.text }}>{s.label}</span>
        </div>
        {item.target_period && (
          <span className="text-[11px] font-mono px-1.5 py-0.5 rounded-[3px]"
            style={{ background: "var(--bg-0)", border: "0.5px solid var(--b0)", color: "var(--t4)" }}>
            {item.target_period}
          </span>
        )}
      </div>

      {/* Metric name */}
      <div>
        <p className="text-[13px] font-medium text-[--t1]">{item.label}</p>
        {item.benchmark_source && (
          <p className="text-[11px] mt-0.5 text-[--t4]">{item.benchmark_source}</p>
        )}
      </div>

      {/* Values */}
      <div className="flex items-end justify-between gap-2">
        <div>
          <p className="text-[22px] font-semibold font-mono leading-none text-[--t1]">
            {fmtValue(item.current, item.unit)}
          </p>
          <p className="text-[11px] mt-1 font-mono text-[--t3]">
            target {fmtValue(item.target, item.unit)}
            {item.variance !== null && (
              <span className="ml-1.5" style={{ color: item.variance < 0 ? "var(--red5)" : "var(--t3)" }}>
                {fmtVariance(item.variance)}
              </span>
            )}
          </p>
        </div>
      </div>

      {/* Investigate button — only for non-green metrics */}
      {(item.status === "yellow" || item.status === "red") && (
        <button
          onClick={() => onInvestigate(item.label)}
          className="mt-auto text-[11px] px-2.5 py-1 rounded-[4px] transition-all text-left"
          style={{ border: `0.5px solid ${s.border}`, background: "var(--bg-0)", color: s.text }}
          onMouseEnter={e => (e.currentTarget.style.background = s.bg)}
          onMouseLeave={e => (e.currentTarget.style.background = "var(--bg-0)")}
        >
          Investigate →
        </button>
      )}
    </div>
  );
}

interface ProcessHealthPanelProps {
  connectionId: string;
  onInvestigate: (question: string) => void;
}

export function ProcessHealthPanel({ connectionId, onInvestigate }: ProcessHealthPanelProps) {
  const [items, setItems] = useState<ScorecardItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!connectionId) return;
    setLoading(true);
    getHealthScorecard(connectionId)
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [connectionId]);

  if (loading) {
    return (
      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))" }}>
        {[1, 2, 3].map(i => (
          <div key={i} className="h-36 rounded-md animate-pulse" style={{ background: "var(--bg-0)" }} />
        ))}
      </div>
    );
  }

  if (items.length === 0) return (
    <div style={{ padding: "24px 16px", textAlign: "center", color: "var(--t3)" }}>
      <p style={{ fontSize: 14, fontWeight: 500, marginBottom: 8 }}>No health metrics configured</p>
      <p style={{ fontSize: 12, opacity: 0.7 }}>Define metrics with targets in the Metrics panel to see a health scorecard here.</p>
    </div>
  );

  const redYellow = items.filter(i => i.status === "red" || i.status === "yellow");
  const green     = items.filter(i => i.status === "green");
  const unknown   = items.filter(i => i.status === "unknown");
  const sorted    = [...redYellow, ...green, ...unknown];

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <p className="text-[14px] font-medium text-[--t1]">Business Health</p>
          <div className="flex items-center gap-2">
            {redYellow.length > 0 && (
              <span className="text-[11px] px-2 py-0.5 rounded-full font-mono"
                style={{ background: "var(--red1)", border: "0.5px solid var(--red2)", color: "var(--red5)" }}>
                {redYellow.length} need attention
              </span>
            )}
            {redYellow.length === 0 && green.length > 0 && (
              <span className="text-[11px] px-2 py-0.5 rounded-full font-mono"
                style={{ background: "var(--bg-1)", border: "0.5px solid var(--b1)", color: "var(--t3)" }}>
                all on target
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))" }}>
        {sorted.map(item => (
          <MetricHealthCard
            key={item.name}
            item={item}
            onInvestigate={(label) =>
              onInvestigate(`Why is ${label} off target? Investigate the root cause and contributing factors.`)
            }
          />
        ))}
      </div>
    </div>
  );
}
