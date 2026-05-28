"use client";

import { useEffect, useState } from "react";
import { getHealthScorecard, type ScorecardItem, type HealthStatus } from "@/lib/api";

const STATUS_COLORS: Record<HealthStatus, { bg: string; border: string; dot: string; text: string; label: string }> = {
  green:   { bg: "#0a1a10", border: "#1a3a20", dot: "#4ade80", text: "#4ade80", label: "On target" },
  yellow:  { bg: "#1a1500", border: "#3a2e00", dot: "#fbbf24", text: "#fbbf24", label: "Warning" },
  red:     { bg: "#1a0a0a", border: "#3a1515", dot: "#f87171", text: "#f87171", label: "Off target" },
  unknown: { bg: "#13141a", border: "#1e1f24", dot: "#5a5b62", text: "#5a5b62", label: "No data" },
};

function fmtValue(v: number | null, unit: string | null): string {
  if (v === null) return "—";
  const num = Math.abs(v);
  let formatted: string;
  if (num >= 1_000_000) formatted = (v / 1_000_000).toFixed(2) + "M";
  else if (num >= 1_000) formatted = (v / 1_000).toFixed(1) + "K";
  else if (num < 1 && num > 0 && unit === "%") formatted = (v * 100).toFixed(1);
  else formatted = v.toFixed(num < 10 ? 2 : 0);
  return unit ? `${formatted}${unit === "$" ? "" : " "}${unit === "$" ? "" : unit}` : formatted;
}

function fmtVariance(v: number | null): string {
  if (v === null) return "";
  const pct = (v * 100).toFixed(1);
  return v >= 0 ? `+${pct}%` : `${pct}%`;
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
      className="flex flex-col gap-3 rounded-xl p-4 transition-all"
      style={{ background: s.bg, border: `0.5px solid ${s.border}` }}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-[6px] h-[6px] rounded-full shrink-0" style={{ background: s.dot }} />
          <span className="text-[11px] font-mono" style={{ color: s.text }}>{s.label}</span>
        </div>
        {item.target_period && (
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-[3px]"
            style={{ background: "#13141a", border: "0.5px solid #1e1f24", color: "#3e3f47" }}>
            {item.target_period}
          </span>
        )}
      </div>

      {/* Metric name */}
      <div>
        <p className="text-[13px] font-medium" style={{ color: "#e8e6e1" }}>{item.label}</p>
        {item.benchmark_source && (
          <p className="text-[10px] mt-0.5" style={{ color: "#3e3f47" }}>{item.benchmark_source}</p>
        )}
      </div>

      {/* Values */}
      <div className="flex items-end justify-between gap-2">
        <div>
          <p className="text-[22px] font-semibold font-mono leading-none" style={{ color: "#e8e6e1" }}>
            {fmtValue(item.current, item.unit)}
          </p>
          <p className="text-[10.5px] mt-1 font-mono" style={{ color: "#5a5b62" }}>
            target {fmtValue(item.target, item.unit)}
            {item.variance !== null && (
              <span className="ml-1.5" style={{ color: item.variance < 0 ? "#f87171" : "#4ade80" }}>
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
          className="mt-auto text-[10.5px] px-2.5 py-1 rounded-[4px] transition-all text-left"
          style={{ border: `0.5px solid ${s.border}`, background: "#11171d", color: s.text }}
          onMouseEnter={e => (e.currentTarget.style.background = s.bg)}
          onMouseLeave={e => (e.currentTarget.style.background = "#0d0e11")}
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
          <div key={i} className="h-36 rounded-xl animate-pulse" style={{ background: "#13141a" }} />
        ))}
      </div>
    );
  }

  if (items.length === 0) return null;

  const redYellow = items.filter(i => i.status === "red" || i.status === "yellow");
  const green     = items.filter(i => i.status === "green");
  const unknown   = items.filter(i => i.status === "unknown");
  const sorted    = [...redYellow, ...green, ...unknown];

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <p className="text-[14px] font-medium" style={{ color: "#c8c7c3" }}>Business Health</p>
          <div className="flex items-center gap-2">
            {redYellow.length > 0 && (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-mono"
                style={{ background: "#1a0a0a", border: "0.5px solid #3a1515", color: "#f87171" }}>
                {redYellow.length} need attention
              </span>
            )}
            {redYellow.length === 0 && green.length > 0 && (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-mono"
                style={{ background: "#0a1a10", border: "0.5px solid #1a3a20", color: "#4ade80" }}>
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
