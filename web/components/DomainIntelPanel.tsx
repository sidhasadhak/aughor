"use client";

import { useEffect, useState } from "react";
import {
  getDomainInsights,
  extendDomainBudget,
  getExplorationEpisodes,
  type DomainInsights,
  type ExplorationInsight,
  type ExplorationEpisode,
} from "@/lib/api";

// ── Domain metadata ───────────────────────────────────────────────────────────

const DOMAIN_META: Record<string, { color: string; bg: string; border: string }> = {
  Commerce:   { color: "#60a5fa", bg: "#1a2030", border: "#2a3a50" },
  Finance:    { color: "#34d399", bg: "#1a2820", border: "#2a4030" },
  Marketing:  { color: "#c084fc", bg: "#22182e", border: "#3a2a50" },
  Operations: { color: "#fb923c", bg: "#2a1e14", border: "#4a3020" },
};

function domainMeta(domain: string) {
  return DOMAIN_META[domain] ?? { color: "#9a9ba4", bg: "#1a1a22", border: "#2a2a35" };
}

// ── Coverage angle chips ──────────────────────────────────────────────────────

const KNOWN_ANGLES: Record<string, string[]> = {
  Commerce:   ["volume", "value", "retention", "basket_composition", "seasonality"],
  Finance:    ["revenue", "margins", "payment_behavior", "refund_rate", "receivables"],
  Marketing:  ["channel_mix", "conversion", "campaign_roi", "attribution", "experiments"],
  Operations: ["fulfillment", "inventory_health", "supplier_performance", "lead_times"],
};

function AngleChips({ domain, covered }: { domain: string; covered: string[] }) {
  const angles = KNOWN_ANGLES[domain] ?? covered;
  const all = Array.from(new Set([...angles, ...covered]));
  if (all.length === 0) return null;
  const meta = domainMeta(domain);

  return (
    <div className="flex flex-wrap gap-1.5 mb-3">
      {all.map(a => {
        const done = covered.includes(a);
        return (
          <span
            key={a}
            className="text-[10px] px-2 py-0.5 rounded-full font-medium transition-all"
            style={done
              ? { background: meta.bg, color: meta.color, border: `0.5px solid ${meta.border}` }
              : { background: "#111115", color: "#3e3f4a", border: "0.5px solid #1e1f24" }
            }
          >
            {done && <span className="mr-1">✓</span>}
            {a.replace(/_/g, " ")}
          </span>
        );
      })}
    </div>
  );
}

// ── Budget bar ────────────────────────────────────────────────────────────────

function BudgetBar({ used, cap, domain }: { used: number; cap: number; domain: string }) {
  const meta = domainMeta(domain);
  const pct = cap > 0 ? Math.min(1, used / cap) : 0;
  return (
    <div className="mb-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px]" style={{ color: "#4a4b57" }}>Query budget</span>
        <span className="text-[10px] font-mono" style={{ color: meta.color }}>
          {used} / {cap}
        </span>
      </div>
      <div className="h-1 rounded-full" style={{ background: "#1a1a22" }}>
        <div
          className="h-1 rounded-full transition-all"
          style={{ width: `${pct * 100}%`, background: meta.color, opacity: 0.7 }}
        />
      </div>
    </div>
  );
}

// ── Novelty badge ─────────────────────────────────────────────────────────────

function NoveltyBadge({ score }: { score: number }) {
  const colors = ["", "#4a4b57", "#6e6f78", "#7ba8f7", "#60a5fa", "#34d399"];
  const labels = ["", "trivial", "expected", "interesting", "notable", "breakthrough"];
  const c = colors[score] ?? "#4a4b57";
  const l = labels[score] ?? String(score);
  return (
    <span
      className="text-[9px] px-1.5 py-0.5 rounded font-medium"
      style={{ background: `${c}22`, color: c, border: `0.5px solid ${c}44` }}
    >
      {l}
    </span>
  );
}

// ── Episode live feed row ─────────────────────────────────────────────────────

function EpisodeRow({ ep, domain }: { ep: ExplorationEpisode; domain: string }) {
  const [expanded, setExpanded] = useState(false);
  const meta = domainMeta(domain);

  // Parse question from think: "Domain X | angle=Y | Question text"
  const parts = ep.think.split(" | ");
  const question = parts.length >= 3 ? parts.slice(2).join(" | ") : ep.think;
  const angle = parts[1]?.replace("angle=", "");

  const isError = ep.observation.startsWith("ERROR:") || ep.observation.startsWith("EXCEPTION:");
  const obsPreview = ep.observation.slice(0, 200) + (ep.observation.length > 200 ? "…" : "");

  return (
    <div
      className="rounded-md mb-2 overflow-hidden"
      style={{ background: "#111115", border: "0.5px solid #1e1f24" }}
    >
      {/* Header row */}
      <button
        className="w-full text-left px-3 py-2.5 flex items-start gap-2"
        onClick={() => setExpanded(e => !e)}
      >
        <span
          className="shrink-0 mt-0.5 text-[9px] px-1.5 py-0.5 rounded"
          style={{ background: meta.bg, color: meta.color, border: `0.5px solid ${meta.border}` }}
        >
          {angle ?? "query"}
        </span>
        <span className="flex-1 text-[11px] text-left leading-relaxed" style={{ color: "#9a9ba4" }}>
          {question}
        </span>
        {isError
          ? <span className="text-[9px] text-amber-400 shrink-0">error</span>
          : <span className="text-[9px] shrink-0" style={{ color: "#3e3f4a" }}>
              {expanded ? "▲" : "▼"}
            </span>
        }
      </button>

      {/* Expanded: SQL + observation */}
      {expanded && (
        <div className="border-t px-3 pb-3 pt-2 space-y-2" style={{ borderColor: "#1e1f24" }}>
          {/* SQL */}
          <div>
            <p className="text-[9px] uppercase tracking-widest mb-1" style={{ color: "#3e3f4a" }}>SQL executed</p>
            <pre
              className="text-[10px] font-mono leading-relaxed overflow-x-auto rounded p-2"
              style={{ background: "#0d0e11", color: "#6e6f78", whiteSpace: "pre-wrap", wordBreak: "break-all" }}
            >
              {ep.sql}
            </pre>
          </div>
          {/* Observation */}
          <div>
            <p className="text-[9px] uppercase tracking-widest mb-1" style={{ color: "#3e3f4a" }}>Result</p>
            <pre
              className="text-[10px] font-mono leading-relaxed overflow-x-auto rounded p-2"
              style={{
                background: isError ? "#1a1010" : "#0d0e11",
                color: isError ? "#f87171" : "#6e6f78",
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
              }}
            >
              {obsPreview}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Insight card ──────────────────────────────────────────────────────────────

function InsightCard({ insight }: { insight: ExplorationInsight }) {
  const meta = domainMeta(insight.domain);
  return (
    <div
      className="rounded-md p-3 mb-2"
      style={{ background: "#13141a", border: `0.5px solid ${meta.border}` }}
    >
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <span
          className="text-[9px] px-1.5 py-0.5 rounded shrink-0"
          style={{ background: meta.bg, color: meta.color, border: `0.5px solid ${meta.border}` }}
        >
          {insight.angle || "general"}
        </span>
        <NoveltyBadge score={insight.novelty ?? 3} />
      </div>
      <p className="text-[11.5px] leading-relaxed" style={{ color: "#c8c7c3" }}>
        {insight.finding}
      </p>
    </div>
  );
}

// ── Per-domain section ────────────────────────────────────────────────────────

interface DomainSectionProps {
  domain: string;
  data: DomainInsights;
  episodes: ExplorationEpisode[];
  connectionId: string;
  onExtend: () => void;
}

type SubTab = "findings" | "trace";

function DomainSection({ domain, data, episodes, connectionId, onExtend }: DomainSectionProps) {
  const [extending, setExtending] = useState(false);
  const [subTab, setSubTab] = useState<SubTab>("findings");
  const meta = domainMeta(domain);

  const domainEps = episodes.filter(ep => {
    const parts = ep.think.split(" | ");
    const epDomain = parts[0]?.replace("Domain ", "");
    return epDomain === domain;
  });

  async function handleExtend() {
    setExtending(true);
    try {
      await extendDomainBudget(connectionId, domain);
      onExtend();
    } finally {
      setExtending(false);
    }
  }

  const budgetExhausted = data.queries_used >= data.budget_cap;

  return (
    <div
      className="rounded-lg mb-4 overflow-hidden"
      style={{ border: `0.5px solid ${meta.border}` }}
    >
      {/* Domain header */}
      <div
        className="flex items-center justify-between px-4 py-3"
        style={{ background: meta.bg }}
      >
        <div className="flex items-center gap-2.5">
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ background: meta.color }}
          />
          <span className="text-[13px] font-medium" style={{ color: meta.color }}>
            {domain}
          </span>
          <span className="text-[10px]" style={{ color: `${meta.color}99` }}>
            {data.insights.length} finding{data.insights.length !== 1 ? "s" : ""}
          </span>
        </div>
        <button
          onClick={handleExtend}
          disabled={extending}
          className="text-[10px] px-2.5 py-1 rounded transition-opacity disabled:opacity-40"
          style={{
            background: `${meta.color}15`,
            color: meta.color,
            border: `0.5px solid ${meta.border}`,
          }}
        >
          {extending ? "scheduling…" : budgetExhausted ? "Explore 5 more" : "+5 queries"}
        </button>
      </div>

      {/* Budget + angles */}
      <div className="px-4 pt-3">
        <BudgetBar used={data.queries_used} cap={data.budget_cap} domain={domain} />
        <AngleChips domain={domain} covered={data.angles_covered} />
      </div>

      {/* Sub-tabs */}
      <div
        className="flex border-b mx-4"
        style={{ borderColor: "#1e1f24" }}
      >
        {(["findings", "trace"] as SubTab[]).map(t => (
          <button
            key={t}
            onClick={() => setSubTab(t)}
            className="text-[10px] px-3 py-1.5 border-b-2 transition-colors capitalize"
            style={{
              borderColor: subTab === t ? meta.color : "transparent",
              color: subTab === t ? meta.color : "#4a4b57",
            }}
          >
            {t}
            {t === "trace" && domainEps.length > 0 && (
              <span className="ml-1 text-[9px]" style={{ color: "#3e3f4a" }}>
                {domainEps.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Sub-tab content */}
      <div className="px-4 py-3">
        {subTab === "findings" && (
          data.insights.length === 0
            ? <p className="text-[11px] italic" style={{ color: "#3e3f4a" }}>
                No findings yet — exploration is running or budget not started.
              </p>
            : data.insights.map(ins => <InsightCard key={ins.id} insight={ins} />)
        )}
        {subTab === "trace" && (
          domainEps.length === 0
            ? <p className="text-[11px] italic" style={{ color: "#3e3f4a" }}>
                No trace yet — queries appear here as they execute.
              </p>
            : [...domainEps].reverse().map(ep => (
                <EpisodeRow key={`${ep.episode_id}-${ep.ts}`} ep={ep} domain={domain} />
              ))
        )}
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

interface Props {
  connectionId: string;
  isActive: boolean;
}

export function DomainIntelPanel({ connectionId, isActive }: Props) {
  const [data, setData] = useState<Record<string, DomainInsights>>({});
  const [episodes, setEpisodes] = useState<ExplorationEpisode[]>([]);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!isActive) return;
    let cancelled = false;

    const load = async () => {
      try {
        const [d, eps] = await Promise.all([
          getDomainInsights(connectionId),
          getExplorationEpisodes(connectionId),
        ]);
        if (!cancelled) {
          setData(d);
          setEpisodes(eps);
          setLoading(false);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    const t = setInterval(load, 10_000);
    return () => { cancelled = true; clearInterval(t); };
  }, [connectionId, isActive, tick]);

  const domains = Object.keys(data);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40 text-sm" style={{ color: "#3e3f4a" }}>
        Loading domain intelligence…
      </div>
    );
  }

  if (domains.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 gap-3" style={{ color: "#3e3f4a" }}>
        <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
          <circle cx="16" cy="16" r="3" fill="#3e3f4a" />
          <circle cx="6" cy="8" r="2.5" stroke="#3e3f4a" strokeWidth="1.5" fill="none" />
          <circle cx="26" cy="8" r="2.5" stroke="#3e3f4a" strokeWidth="1.5" fill="none" />
          <circle cx="6" cy="24" r="2.5" stroke="#3e3f4a" strokeWidth="1.5" fill="none" />
          <line x1="8" y1="9.5" x2="13.5" y2="14.5" stroke="#3e3f4a" strokeWidth="1" />
          <line x1="24" y1="9.5" x2="18.5" y2="14.5" stroke="#3e3f4a" strokeWidth="1" />
          <line x1="8" y1="22.5" x2="13.5" y2="17.5" stroke="#3e3f4a" strokeWidth="1" />
        </svg>
        <p className="text-[12px]">Domain intelligence not yet available.</p>
        <p className="text-[11px]" style={{ color: "#2e2f3a" }}>
          Exploration must complete the ontology build + Phase 8 first.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {domains.map(domain => (
        <DomainSection
          key={domain}
          domain={domain}
          data={data[domain]}
          episodes={episodes}
          connectionId={connectionId}
          onExtend={() => setTick(t => t + 1)}
        />
      ))}
    </div>
  );
}
