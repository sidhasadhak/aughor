"use client";

import { useEffect, useState } from "react";
import {
  getExplorationStatus,
  getExplorationFindings,
  type ExplorationStatus,
  type ExplorationFindings,
} from "@/lib/api";
import { DomainIntelPanel } from "@/components/DomainIntelPanel";

// ── Phase progress bar ────────────────────────────────────────────────────────

const PHASES = [
  { key: "null_meaning",      label: "Null meanings" },
  { key: "join_verification", label: "Join integrity" },
  { key: "lifecycle_mapping", label: "Lifecycles" },
  { key: "distribution",      label: "Distributions" },
  { key: "cross_table",       label: "Patterns" },
  { key: "domain_intel",      label: "Intelligence" },
  { key: "complete",          label: "Complete" },
];

const PHASE_ORDER = PHASES.map(p => p.key);

function phaseIndex(phase: string): number {
  const i = PHASE_ORDER.indexOf(phase);
  return i === -1 ? -1 : i;
}

function PhaseBar({ status }: { status: ExplorationStatus }) {
  const cur = phaseIndex(status.phase);
  const isComplete = status.phase === "complete";
  const isFailed = status.phase === "failed";

  return (
    <div className="mb-5">
      <div className="flex items-center gap-0.5 mb-2">
        {PHASES.map((p, i) => {
          const done = isComplete || i < cur;
          const active = !isComplete && i === cur;
          return (
            <div key={p.key} className="flex-1 relative group">
              <div className={[
                "h-1 rounded-full transition-colors",
                done ? "bg-emerald-500" :
                active ? "bg-violet-400 animate-pulse" :
                isFailed && i === cur ? "bg-red-500" :
                "bg-white/10",
              ].join(" ")} />
              <span className="absolute -bottom-4 left-1/2 -translate-x-1/2 text-[11px] text-zinc-600 whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
                {p.label}
              </span>
            </div>
          );
        })}
      </div>
      <div className="flex items-center justify-between mt-5">
        <span className="text-[11px] text-zinc-500">
          {isComplete ? "Exploration complete" :
           isFailed ? `Failed: ${status.error ?? "unknown error"}` :
           status.paused ? `Paused · ${PHASES[cur]?.label ?? status.phase}` :
           `${PHASES[cur]?.label ?? status.phase}…`}
        </span>
        <span className="text-[11px] text-zinc-600">
          {status.queries_executed > 0 && `${status.queries_executed} queries · `}
          {status.facts_discovered > 0 && `${status.facts_discovered} facts`}
        </span>
      </div>
    </div>
  );
}

// ── Null Meanings ─────────────────────────────────────────────────────────────

const NULL_LABELS: Record<string, { label: string; color: string }> = {
  pending:                 { label: "Pending event",    color: "text-sky-400" },
  not_applicable_terminal: { label: "Terminal state",   color: "text-zinc-500" },
  missing:                 { label: "Data quality gap", color: "text-amber-400" },
  mixed:                   { label: "Mixed pattern",    color: "text-violet-400" },
  not_applicable:          { label: "Always populated", color: "text-emerald-400" },
  unknown:                 { label: "Unknown",          color: "text-zinc-600" },
};

function NullMeaningsSection({ nullMeanings }: { nullMeanings: ExplorationFindings["null_meanings"] }) {
  const entries = Object.entries(nullMeanings).filter(([, v]) => v.meaning !== "not_applicable" && v.meaning !== "unknown");
  if (entries.length === 0) return (
    <p className="text-xs text-zinc-600 italic">No meaningful nulls detected.</p>
  );

  return (
    <div className="space-y-2">
      {entries.map(([key, nm]) => {
        const [table, col] = key.split(":");
        const info = NULL_LABELS[nm.meaning] ?? { label: nm.meaning, color: "text-zinc-400" };
        return (
          <div key={key} className="bg-white/[0.03] rounded-lg p-3">
            <div className="flex items-start justify-between gap-2">
              <span className="text-xs font-mono text-zinc-300">{table}<span className="text-zinc-600">.</span>{col}</span>
              <span className={`text-[11px] shrink-0 font-medium ${info.color}`}>{info.label}</span>
            </div>
            {nm.business_rule && (
              <p className="text-[11px] text-zinc-500 mt-1 font-mono">{nm.business_rule}</p>
            )}
            {nm.null_rate != null && (
              <p className="text-[11px] text-zinc-500 mt-0.5">{(nm.null_rate * 100).toFixed(1)}% null rate</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Lifecycle Maps ────────────────────────────────────────────────────────────

function LifecycleMapsSection({ maps }: { maps: ExplorationFindings["lifecycle_maps"] }) {
  const entries = Object.entries(maps);
  if (entries.length === 0) return (
    <p className="text-xs text-zinc-600 italic">No lifecycle state machines found.</p>
  );

  return (
    <div className="space-y-3">
      {entries.map(([table, lm]) => (
        <div key={table} className="bg-white/[0.03] rounded-lg p-3">
          <div className="flex items-baseline gap-1.5 mb-2">
            <span className="text-xs font-mono text-zinc-200">{table}</span>
            <span className="text-zinc-600 text-[11px]">.{lm.status_column}</span>
          </div>
          <div className="flex flex-wrap gap-1 mb-1.5">
            {lm.active_states.map(s => (
              <span key={s} className="text-[11px] bg-emerald-500/10 text-emerald-400 px-1.5 py-0.5 rounded">{s}</span>
            ))}
            {lm.terminal_states.map(s => (
              <span key={s} className="text-[11px] bg-zinc-500/10 text-zinc-500 px-1.5 py-0.5 rounded">{s}</span>
            ))}
          </div>
          {lm.transitions.length > 0 && (
            <p className="text-[11px] text-zinc-600">{lm.transitions.length} state transitions mapped</p>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Distributions ─────────────────────────────────────────────────────────────

const DIST_SHAPE_PILL: Record<string, { label: string; bg: string; text: string; border: string; barColor: string }> = {
  fraction_0_1:  { label: "0–1 ratio",    bg: "#1e2a1e", text: "#4ade80", border: "#2a4a2a", barColor: "#2a4a2a" },
  normal:        { label: "Normal",        bg: "#1a1e2e", text: "#7ba8f7", border: "#2a3050", barColor: "#2a3050" },
  concentrated:  { label: "Concentrated", bg: "#2a1a2e", text: "#c084fc", border: "#3e2a50", barColor: "#4a4b5a" },
  skewed_right:  { label: "Right-skewed", bg: "#2a1e14", text: "#f97316", border: "#3e2a1e", barColor: "#3e2a1e" },
  skewed_left:   { label: "Left-skewed",  bg: "#2a1e14", text: "#f97316", border: "#3e2a1e", barColor: "#3e2a1e" },
  uniform:       { label: "Uniform",      bg: "#1a2a1e", text: "#4ade80", border: "#2a4a2a", barColor: "#2a4a2a" },
  bimodal:       { label: "Bimodal",      bg: "#2a1a1a", text: "#f87171", border: "#3e2a2a", barColor: "#3e2a2a" },
};

function miniBarHeights(shape: string): number[] {
  switch (shape) {
    case "normal":        return [4, 8, 22, 24, 16, 6];
    case "fraction_0_1": return [6, 14, 24, 16, 8, 4];
    case "concentrated":  return [3, 10, 24, 18, 8, 3];
    case "skewed_right":  return [24, 20, 14, 8, 4, 2];
    case "skewed_left":   return [2, 4, 8, 14, 20, 24];
    case "uniform":       return [20, 22, 22, 21, 20, 21];
    case "bimodal":       return [20, 8, 4, 8, 22, 16];
    default:              return [10, 14, 18, 16, 12, 8];
  }
}

function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(2);
}

function DistributionsSection({ distributions }: { distributions: ExplorationFindings["distributions"] }) {
  const [search, setSearch] = useState("");
  const allEntries = Object.entries(distributions).filter(([, d]) => d.shape !== "unknown");

  if (allEntries.length === 0) return (
    <p className="text-xs text-zinc-600 italic">No distributions profiled yet.</p>
  );

  const normalCount = allEntries.filter(([, d]) => d.shape === "normal").length;
  const ratioCount  = allEntries.filter(([, d]) => d.shape === "fraction_0_1").length;
  const concCount   = allEntries.filter(([, d]) => d.shape === "concentrated").length;
  const otherCount  = allEntries.length - normalCount - ratioCount - concCount;

  const q        = search.toLowerCase();
  const filtered = q ? allEntries.filter(([key]) => key.toLowerCase().includes(q)) : allEntries;

  return (
    <div className="space-y-3">
      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-1.5">
        {([
          { label: "Normal",       count: normalCount, color: "#7ba8f7" },
          { label: "0–1 Ratio",    count: ratioCount,  color: "#4ade80" },
          { label: "Concentrated", count: concCount,   color: "#c084fc" },
          { label: "Other",        count: otherCount,  color: "#9a9ba4" },
        ] as const).map(({ label, count, color }) => (
          <div key={label} className="rounded-md p-2.5" style={{ background: "#13141a", border: "0.5px solid #1e1f24" }}>
            <p className="text-[11px] uppercase tracking-widest mb-1" style={{ color: "var(--t4)" }}>{label}</p>
            <p className="text-xl font-medium font-mono" style={{ color, letterSpacing: "-0.02em" }}>{count}</p>
          </div>
        ))}
      </div>

      {/* Filter row */}
      <div className="flex items-center justify-between">
        <span className="text-[11px]" style={{ color: "#5a5b62" }}>{allEntries.length} columns profiled</span>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Filter columns…"
          className="text-[11px] rounded-md px-2.5 py-1 focus:outline-none w-32"
          style={{ background: "#13141a", border: "0.5px solid #1e1f24", color: "#9a9ba4" }}
        />
      </div>

      {/* Column header */}
      <div className="grid gap-2 px-3 pb-1 text-[11px] uppercase tracking-[0.06em]"
        style={{ gridTemplateColumns: "180px 1fr 80px 80px", color: "var(--b0)" }}>
        <div>Column</div>
        <div>Distribution</div>
        <div className="text-center">Mean</div>
        <div className="text-right">Shape</div>
      </div>

      {/* Rows */}
      <div className="flex flex-col gap-0.5">
        {filtered.map(([key, d]) => {
          const [table, col] = key.split(":");
          const pill     = DIST_SHAPE_PILL[d.shape] ?? { label: d.shape, bg: "#1a1a1e", text: "#6e6f78", border: "#2a2b30", barColor: "#2a2b35" };
          const barH     = miniBarHeights(d.shape);
          const maxH     = Math.max(...barH);
          return (
            <div
              key={key}
              className="flex items-center gap-2 px-3 py-2.5 rounded-md cursor-pointer transition-all"
              style={{ background: "#13141a", border: "0.5px solid transparent" }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = "#2a2b30")}
              onMouseLeave={e => (e.currentTarget.style.borderColor = "transparent")}
            >
              {/* Column name + type */}
              <div style={{ flex: "0 0 180px", minWidth: 0 }}>
                <div className="flex items-center gap-1.5">
                  <span className="text-[11px] font-mono" style={{ color: "#5a5b62" }}>{table}</span>
                  {d.col_type && (
                    <span className="text-[11px] font-mono" style={{ color: "var(--t4)" }}>{d.col_type}</span>
                  )}
                  {d.col_type === "BIGINT" && /(^ts$|_ts$|_at$|timestamp|time)/i.test(col) && (
                    <span className="text-[8.5px] px-1 py-0 rounded" style={{ background: "#2a1a2e", color: "#c084fc", border: "0.5px solid #3e2a50" }}>unix ts</span>
                  )}
                </div>
                <div className="text-[12.5px] font-medium font-mono mt-0.5" style={{ color: "#c8c7c3" }}>{col}</div>
              </div>

              {/* Stats */}
              <div className="flex-1 flex font-mono text-[11px]">
                {([
                  { label: "p25",  value: d.p25 },
                  { label: "p50",  value: d.p50 },
                  { label: "p75",  value: d.p75 },
                  { label: "mean", value: d.mean },
                ] as const).map(({ label, value }) => (
                  <div key={label} className="flex-1 flex flex-col items-center">
                    <span className="text-[11px] mb-0.5" style={{ color: "var(--b0)", letterSpacing: "0.04em" }}>{label}</span>
                    <span style={{ color: label === "p50" || label === "mean" ? "#9a9ba4" : "#6e6f78" }}>
                      {fmtNum(value as number | null | undefined)}
                    </span>
                  </div>
                ))}
              </div>

              {/* Mini histogram bars */}
              <div style={{ flex: "0 0 80px" }}>
                <div className="flex items-end gap-0.5" style={{ height: "24px" }}>
                  {barH.map((h, i) => (
                    <div
                      key={i}
                      className="flex-1"
                      style={{
                        height: `${h}px`,
                        background: h >= maxH * 0.6 ? pill.barColor : "#2a2b35",
                        borderRadius: "2px 2px 0 0",
                      }}
                    />
                  ))}
                </div>
              </div>

              {/* Shape pill */}
              <div style={{ flex: "0 0 80px", textAlign: "right" }}>
                <span
                  className="inline-flex items-center text-[11px] px-2 py-0.5 rounded-[4px] whitespace-nowrap"
                  style={{ background: pill.bg, color: pill.text, border: `0.5px solid ${pill.border}` }}
                >
                  {pill.label}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Cross-table Insights ──────────────────────────────────────────────────────

function InsightsSection({ insights }: { insights: ExplorationFindings["insights"] }) {
  if (insights.length === 0) return (
    <p className="text-xs text-zinc-600 italic">No cross-table patterns discovered yet.</p>
  );

  return (
    <div className="space-y-2">
      {insights.map(ins => (
        <div key={ins.id} className="bg-white/[0.03] rounded-lg p-3">
          <p className="text-[11px] text-zinc-300 leading-relaxed">{ins.finding}</p>
          <div className="flex items-center gap-2 mt-2">
            <span className="text-[11px] text-zinc-600">
              {ins.entities_involved.join(" × ")}
            </span>
            <span className="text-[11px] text-emerald-500/70 ml-auto">
              {(ins.confidence * 100).toFixed(0)}% confidence
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

interface Props {
  connectionId: string;
  initialSection?: SectionKey;
}

type SectionKey = "nulls" | "lifecycles" | "distributions" | "insights" | "intelligence";

export function ExplorationPanel({ connectionId, initialSection }: Props) {
  const [status, setStatus] = useState<ExplorationStatus | null>(null);
  const [findings, setFindings] = useState<ExplorationFindings | null>(null);
  const [activeSection, setActiveSection] = useState<SectionKey>(initialSection ?? "nulls");

  useEffect(() => {
    if (initialSection) setActiveSection(initialSection);
  }, [initialSection]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const [s, f] = await Promise.all([
          getExplorationStatus(connectionId),
          getExplorationFindings(connectionId),
        ]);
        if (!cancelled) {
          setStatus(s);
          setFindings(f);
        }
      } catch {
        // silent
      }
    };

    load();
    // Poll while exploration is active
    const t = setInterval(load, 12_000);
    return () => { cancelled = true; clearInterval(t); };
  }, [connectionId]);

  if (!status || !findings) {
    return (
      <div className="flex items-center justify-center h-40 text-zinc-600 text-sm">
        Loading exploration data…
      </div>
    );
  }

  const nullCount = Object.values(findings.null_meanings).filter(
    n => n.meaning !== "not_applicable" && n.meaning !== "unknown"
  ).length;
  const distCount = Object.keys(findings.distributions).length;
  const lifecycleCount = Object.keys(findings.lifecycle_maps).length;

  const sections: { key: SectionKey; label: string; badge?: string; badgeColor?: string }[] = [
    {
      key: "nulls",
      label: "Null Meanings",
      badge: nullCount > 0 ? String(nullCount) : undefined,
    },
    {
      key: "lifecycles",
      label: "Lifecycles",
      badge: lifecycleCount > 0 ? String(lifecycleCount) : undefined,
    },
    {
      key: "distributions",
      label: "Distributions",
      badge: distCount > 0 ? String(distCount) : undefined,
    },
    {
      key: "insights",
      label: "Patterns",
      badge: findings.insights.filter(i => !i.domain).length > 0
        ? String(findings.insights.filter(i => !i.domain).length)
        : undefined,
    },
    {
      key: "intelligence" as SectionKey,
      label: "Intelligence",
      badge: findings.insights.filter(i => !!i.domain).length > 0
        ? String(findings.insights.filter(i => !!i.domain).length)
        : undefined,
      badgeColor: "text-violet-400",
    },
  ];

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Phase progress */}
      <div className="px-4 pt-4 pb-0 shrink-0">
        <PhaseBar status={status} />
      </div>

      {/* Section tabs */}
      <div className="flex gap-0 px-4 border-b border-white/10 shrink-0 mt-2">
        {sections.map(s => (
          <button
            key={s.key}
            onClick={() => setActiveSection(s.key)}
            className={[
              "flex items-center gap-1.5 px-3 py-2 text-[11px] border-b-2 transition-colors whitespace-nowrap",
              activeSection === s.key
                ? "border-violet-400 text-zinc-200"
                : "border-transparent text-zinc-500 hover:text-zinc-300",
            ].join(" ")}
          >
            {s.label}
            {s.badge && (
              <span className={`text-[11px] font-medium ${s.badgeColor ?? "text-zinc-500"}`}>
                {s.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Section content */}
      <div className="flex-1 overflow-y-auto p-4">
        {activeSection === "nulls" && (
          <NullMeaningsSection nullMeanings={findings.null_meanings} />
        )}
        {activeSection === "lifecycles" && (
          <LifecycleMapsSection maps={findings.lifecycle_maps} />
        )}
        {activeSection === "distributions" && (
          <DistributionsSection distributions={findings.distributions} />
        )}
        {activeSection === "insights" && (
          <InsightsSection insights={findings.insights.filter(i => !i.domain)} />
        )}
        {activeSection === "intelligence" && (
          <DomainIntelPanel connectionId={connectionId} isActive={activeSection === "intelligence"} />
        )}
      </div>
    </div>
  );
}
