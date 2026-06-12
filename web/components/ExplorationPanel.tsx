"use client";

import { useEffect, useState } from "react";
import { pct } from "@/lib/format";
import {
  getExplorationStatus,
  getExplorationFindings,
  type ExplorationStatus,
  type ExplorationFindings,
} from "@/lib/api";
import { subscribeKernelEvents } from "@/lib/events";
import { Spinner, SkeletonRows } from "@/components/ui/motion";
import { DomainIntelPanel } from "@/components/DomainIntelPanel";
import { SchemaShape } from "@/components/SchemaShape";

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
              <span className="absolute -bottom-4 left-1/2 -translate-x-1/2 text-[11px] text-zinc-500 whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
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
        <span className="text-[11px] text-zinc-500">
          {status.first_insight_seconds != null && (
            <span className="text-emerald-400" title="Time from exploration start to the first insight (B-6 KPI)">
              ⏱ first insight in {fmtDuration(status.first_insight_seconds)} ·{" "}
            </span>
          )}
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
  unknown:                 { label: "Unknown",          color: "text-zinc-500" },
};

function NullMeaningsSection({ nullMeanings }: { nullMeanings: ExplorationFindings["null_meanings"] }) {
  const entries = Object.entries(nullMeanings).filter(([, v]) => v.meaning !== "not_applicable" && v.meaning !== "unknown");
  if (entries.length === 0) return (
    <p className="text-xs text-zinc-500 italic">No meaningful nulls detected.</p>
  );

  return (
    <div className="space-y-2">
      {entries.map(([key, nm]) => {
        const [table, col] = key.split(":");
        const info = NULL_LABELS[nm.meaning] ?? { label: nm.meaning, color: "text-zinc-400" };
        return (
          <div key={key} className="bg-white/[0.03] rounded-lg p-3">
            <div className="flex items-start justify-between gap-2">
              <span className="text-xs font-mono text-zinc-300">{table}<span className="text-zinc-500">.</span>{col}</span>
              <span className={`text-[11px] shrink-0 font-medium ${info.color}`}>{info.label}</span>
            </div>
            {nm.business_rule && (
              <p className="text-[11px] text-zinc-500 mt-1 font-mono">{nm.business_rule}</p>
            )}
            {nm.null_rate != null && (
              <p className="text-[11px] text-zinc-500 mt-0.5">{pct(nm.null_rate, 1)} null rate</p>
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
    <p className="text-xs text-zinc-500 italic">No lifecycle state machines found.</p>
  );

  return (
    <div className="space-y-3">
      {entries.map(([table, lm]) => (
        <div key={table} className="bg-white/[0.03] rounded-lg p-3">
          <div className="flex items-baseline gap-1.5 mb-2">
            <span className="text-xs font-mono text-zinc-200">{table}</span>
            <span className="text-zinc-500 text-[11px]">.{lm.status_column}</span>
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
            <p className="text-[11px] text-zinc-500">{lm.transitions.length} state transitions mapped</p>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Distributions ─────────────────────────────────────────────────────────────
// The Distributions section is now rendered by the shared <SchemaShape> component
// (column profile + distribution shape merged), which also lives in the Catalog
// schema panel. The old standalone shape pills/mini-bars moved there.

// Human-readable elapsed for the time-to-first-insight KPI: "8s", "47s", "3m 12s".
function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s ? `${m}m ${s}s` : `${m}m`;
}

// ── Cross-table Insights ──────────────────────────────────────────────────────

function InsightsSection({ insights }: { insights: ExplorationFindings["insights"] }) {
  if (insights.length === 0) return (
    <p className="text-xs text-zinc-500 italic">No cross-table patterns discovered yet.</p>
  );

  return (
    <div className="space-y-2">
      {insights.map(ins => (
        <div key={ins.id} className="bg-white/[0.03] rounded-lg p-3">
          <p className="text-[11px] text-zinc-300 leading-relaxed">{ins.finding}</p>
          <div className="flex items-center gap-2 mt-2">
            <span className="text-[11px] text-zinc-500">
              {ins.entities_involved.join(" × ")}
            </span>
            <span className="text-[11px] text-emerald-500/70 ml-auto">
              {pct(ins.confidence, 0)} confidence
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
  /** Shared schema scope from the workspace header — scopes the combined
   *  Schema-Shape view in the Distributions section. */
  schema?: string;
}

type SectionKey = "nulls" | "lifecycles" | "distributions" | "insights" | "intelligence";

export function ExplorationPanel({ connectionId, initialSection, schema }: Props) {
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
    // K2: kernel events drive refresh; the interval is only a slow fallback.
    const t = setInterval(load, 60_000);
    const unsub = subscribeKernelEvents(() => load(), {
      kinds: ["exploration.", "job.state"], connId: connectionId,
    });
    return () => { cancelled = true; clearInterval(t); unsub(); };
  }, [connectionId]);

  if (!status || !findings) {
    return (
      <div className="p-5 max-w-xl">
        <div className="flex items-center gap-2 mb-4 text-zinc-500 text-sm">
          <Spinner size={13} /> Loading exploration data…
        </div>
        <SkeletonRows rows={6} />
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

      {/* Section content — keyed so a tab switch fades instead of snapping */}
      <div key={activeSection} className="flex-1 overflow-y-auto p-4 aug-anim-fade">
        {activeSection === "nulls" && (
          <NullMeaningsSection nullMeanings={findings.null_meanings} />
        )}
        {activeSection === "lifecycles" && (
          <LifecycleMapsSection maps={findings.lifecycle_maps} />
        )}
        {activeSection === "distributions" && (
          <SchemaShape connectionId={connectionId} schemaName={schema} />
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
