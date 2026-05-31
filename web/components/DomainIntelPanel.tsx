"use client";

import { useEffect, useState } from "react";
import {
  getDomainInsights,
  extendDomainBudget,
  getExplorationEpisodes,
  getCanvasDomainInsights,
  extendCanvasDomainBudget,
  getCanvasExplorationEpisodes,
  promoteCanvasInsight,
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

// ── Novelty metadata ──────────────────────────────────────────────────────────

const NOVELTY: Record<number, { label: string; color: string; bg: string; border: string }> = {
  1: { label: "trivial",      color: "#4a4b57", bg: "#111115", border: "#1e1f24" },
  2: { label: "expected",     color: "#6e6f78", bg: "#16171c", border: "#222228" },
  3: { label: "interesting",  color: "#7ba8f7", bg: "#1a1e2e", border: "#2a3050" },
  4: { label: "notable",      color: "#60a5fa", bg: "#1a2030", border: "#2a3a50" },
  5: { label: "breakthrough", color: "#34d399", bg: "#1a2820", border: "#2a4030" },
};

function noveltyMeta(score: number) {
  return NOVELTY[score] ?? NOVELTY[2];
}

function confidenceLabel(c: number): string {
  if (c >= 0.85) return "high";
  if (c >= 0.65) return "medium";
  return "low";
}

// ── Episode query row (trace view) ────────────────────────────────────────────

function EpisodeRow({ ep, domain }: { ep: ExplorationEpisode; domain: string }) {
  const [expanded, setExpanded] = useState(false);
  const meta = domainMeta(domain);

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
      <button
        className="w-full text-left px-3 py-2.5 flex items-start gap-2"
        onClick={() => setExpanded(e => !e)}
      >
        <span
          className="shrink-0 mt-0.5 text-[11px] px-1.5 py-0.5 rounded"
          style={{ background: meta.bg, color: meta.color, border: `0.5px solid ${meta.border}` }}
        >
          {angle ?? "query"}
        </span>
        <span className="flex-1 text-[11px] text-left leading-relaxed" style={{ color: "#9a9ba4" }}>
          {question}
        </span>
        {isError
          ? <span className="text-[11px] text-amber-400 shrink-0">error</span>
          : <span className="text-[11px] shrink-0" style={{ color: "#3e3f4a" }}>{expanded ? "▲" : "▼"}</span>
        }
      </button>
      {expanded && (
        <div className="border-t px-3 pb-3 pt-2 space-y-2" style={{ borderColor: "#1e1f24" }}>
          <div>
            <p className="text-[11px] uppercase tracking-widest mb-1" style={{ color: "#3e3f4a" }}>SQL</p>
            <pre className="text-[11px] font-mono leading-relaxed overflow-x-auto rounded p-2"
              style={{ background: "#11171d", color: "#6e6f78", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
              {ep.sql}
            </pre>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-widest mb-1" style={{ color: "#3e3f4a" }}>Result</p>
            <pre className="text-[11px] font-mono leading-relaxed overflow-x-auto rounded p-2"
              style={{ background: isError ? "#1a1010" : "#0d0e11", color: isError ? "#f87171" : "#6e6f78", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
              {obsPreview}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Finding card ──────────────────────────────────────────────────────────────

function FindingCard({ insight, canvasId }: { insight: ExplorationInsight; canvasId?: string }) {
  const [sqlOpen, setSqlOpen] = useState(false);
  const [promoted, setPromoted] = useState(insight.promoted_to_org ?? false);
  const [promoting, setPromoting] = useState(false);
  const nv = noveltyMeta(insight.novelty);
  const dm = domainMeta(insight.domain);

  const handlePromote = async () => {
    if (!canvasId || promoting || promoted) return;
    setPromoting(true);
    try {
      await promoteCanvasInsight(canvasId, insight.id);
      setPromoted(true);
    } catch { /* ignore */ }
    finally { setPromoting(false); }
  };

  return (
    <div style={{
      background: "#0f1014",
      border: "0.5px solid #1e1f24",
      borderRadius: 8,
      padding: "12px 14px",
      marginBottom: 8,
    }}>
      {/* Novelty + angle */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 9, flexWrap: "wrap" }}>
        <span style={{
          fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 500,
          background: nv.bg, color: nv.color, border: `0.5px solid ${nv.border}`,
        }}>
          {nv.label}
        </span>
        {insight.angle && (
          <span style={{
            fontSize: 10, padding: "2px 8px", borderRadius: 4,
            background: dm.bg, color: `${dm.color}cc`, border: `0.5px solid ${dm.border}`,
          }}>
            {insight.angle.replace(/_/g, " ")}
          </span>
        )}
      </div>

      {/* Finding text */}
      <p style={{ fontSize: 12, color: "#c0bfbc", lineHeight: 1.65, margin: 0 }}>
        {insight.finding}
      </p>

      {/* Footer */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 10, gap: 8 }}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, color: "#3e3f4a" }}>
            confidence{" "}
            <span style={{ color: confidenceLabel(insight.confidence) === "high" ? "#34d399" : confidenceLabel(insight.confidence) === "medium" ? "#7ba8f7" : "#f87171" }}>
              {confidenceLabel(insight.confidence)}
            </span>
          </span>
          {insight.entities_involved.length > 0 && (
            <span style={{ fontSize: 10, color: "#3e3f4a" }}>
              {insight.entities_involved.slice(0, 3).join(" · ")}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          {canvasId && (
            promoted ? (
              <span style={{ fontSize: 10, color: "#34d399" }}>Promoted ✓</span>
            ) : (
              <button
                onClick={handlePromote}
                disabled={promoting}
                style={{
                  fontSize: 10, padding: "2px 8px", borderRadius: 4,
                  background: "#1a2820", color: "#34d399",
                  border: "0.5px solid #2a4030",
                  cursor: promoting ? "wait" : "pointer",
                  opacity: promoting ? 0.5 : 1,
                }}
              >
                {promoting ? "…" : "Promote to Org →"}
              </button>
            )
          )}
          {insight.sql && (
            <button
              onClick={() => setSqlOpen(o => !o)}
              style={{ fontSize: 10, color: "#3e3f4a", background: "none", border: "none", cursor: "pointer", padding: 0 }}
            >
              {sqlOpen ? "SQL ▲" : "SQL ▼"}
            </button>
          )}
        </div>
      </div>

      {/* SQL */}
      {sqlOpen && insight.sql && (
        <pre style={{
          marginTop: 8, fontSize: 10, fontFamily: "var(--font-mono)",
          color: "#5a5b62", background: "#11171d", borderRadius: 4,
          padding: "8px 10px", overflowX: "auto",
          whiteSpace: "pre-wrap", wordBreak: "break-all",
          border: "0.5px solid #1a1b20",
        }}>
          {insight.sql}
        </pre>
      )}
    </div>
  );
}

// ── Domain overview card ──────────────────────────────────────────────────────

interface OverviewCardProps {
  domain: string;
  data: DomainInsights;
  onSelect: (d: string) => void;
  connectionId: string;
  canvasId?: string;
  onExtend: () => void;
}

function DomainOverviewCard({ domain, data, onSelect, connectionId, canvasId, onExtend }: OverviewCardProps) {
  const [extending, setExtending] = useState(false);
  const meta = domainMeta(domain);

  // Breakdown: counts per novelty score (highest first, skip zeros)
  const breakdown = [5, 4, 3, 2, 1]
    .map(n => ({ ...noveltyMeta(n), count: data.insights.filter(i => i.novelty === n).length }))
    .filter(b => b.count > 0);

  // Top finding preview (highest novelty)
  const top = [...data.insights].sort((a, b) => b.novelty - a.novelty)[0];

  async function handleExtend(e: React.MouseEvent) {
    e.stopPropagation();
    setExtending(true);
    try {
      if (canvasId) await extendCanvasDomainBudget(canvasId, domain);
      else await extendDomainBudget(connectionId, domain);
      onExtend();
    }
    finally { setExtending(false); }
  }

  return (
    <div
      onClick={() => onSelect(domain)}
      style={{
        cursor: "pointer",
        borderRadius: 10,
        border: `0.5px solid ${meta.border}`,
        overflow: "hidden",
        transition: "border-color .12s",
      }}
      onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = meta.color + "66"}
      onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = meta.border}
    >
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "10px 14px", background: meta.bg,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: meta.color, display: "inline-block", flexShrink: 0 }} />
          <span style={{ fontSize: 13, fontWeight: 500, color: meta.color }}>{domain}</span>
          <span style={{ fontSize: 10, color: `${meta.color}88` }}>
            {data.insights.length} finding{data.insights.length !== 1 ? "s" : ""}
          </span>
        </div>
        <button
          onClick={handleExtend}
          disabled={extending}
          style={{
            fontSize: 10, padding: "3px 9px", borderRadius: 4,
            background: `${meta.color}15`, color: meta.color,
            border: `0.5px solid ${meta.border}`,
            cursor: extending ? "wait" : "pointer",
            opacity: extending ? 0.5 : 1,
          }}
        >
          {extending ? "scheduling…" : data.queries_used >= data.budget_cap ? "Explore 5 more" : "+5 queries"}
        </button>
      </div>

      {/* Body */}
      <div style={{ padding: "10px 14px 12px", background: "#11171d" }}>
        {/* Novelty breakdown */}
        {breakdown.length > 0 ? (
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 10 }}>
            {breakdown.map(b => (
              <span key={b.label} style={{
                fontSize: 10, padding: "2px 8px", borderRadius: 4,
                background: b.bg, color: b.color, border: `0.5px solid ${b.border}`,
              }}>
                {b.count} {b.label}
              </span>
            ))}
          </div>
        ) : (
          <p style={{ fontSize: 11, color: "#3e3f4a", fontStyle: "italic", marginBottom: 10 }}>No findings yet</p>
        )}

        {/* Top finding preview */}
        {top && (
          <p style={{
            fontSize: 11, color: "#5a5b62", lineHeight: 1.55,
            borderTop: "0.5px solid #1a1b20", paddingTop: 8,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}>
            {top.finding}
          </p>
        )}

        {/* Footer */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10 }}>
          <span style={{ fontSize: 10, color: "#2e2f37" }}>
            {data.angles_covered.length} angle{data.angles_covered.length !== 1 ? "s" : ""} covered
          </span>
          <span style={{ fontSize: 10, color: meta.color }}>View findings →</span>
        </div>
      </div>
    </div>
  );
}

// ── Domain detail view ────────────────────────────────────────────────────────

interface DetailProps {
  domain: string;
  data: DomainInsights;
  episodes: ExplorationEpisode[];
  connectionId: string;
  canvasId?: string;
  onBack: () => void;
  onExtend: () => void;
}

function DomainDetailView({ domain, data, episodes, connectionId, canvasId, onBack, onExtend }: DetailProps) {
  const [filterNovelty, setFilterNovelty] = useState<number | null>(null);
  const [filterAngle, setFilterAngle]     = useState<string | null>(null);
  const [search, setSearch]               = useState("");
  const [showTrace, setShowTrace]         = useState(false);
  const [extending, setExtending]         = useState(false);
  const meta = domainMeta(domain);

  const angles = Array.from(new Set(data.insights.map(i => i.angle).filter(Boolean)));

  const filtered = data.insights
    .filter(i => {
      if (filterNovelty !== null && i.novelty !== filterNovelty) return false;
      if (filterAngle   !== null && i.angle !== filterAngle)     return false;
      if (search && !i.finding.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    })
    .sort((a, b) => b.novelty - a.novelty);

  const domainEps = episodes.filter(ep => {
    const d = ep.think.split(" | ")[0]?.replace("Domain ", "");
    return d === domain;
  });

  const hasFilters = filterNovelty !== null || filterAngle !== null || !!search;

  async function handleExtend() {
    setExtending(true);
    try {
      if (canvasId) await extendCanvasDomainBudget(canvasId, domain);
      else await extendDomainBudget(connectionId, domain);
      onExtend();
    }
    finally { setExtending(false); }
  }

  return (
    <div>
      {/* Back + header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
        <button
          onClick={onBack}
          style={{ fontSize: 11, color: "#4a4b57", background: "none", border: "none", cursor: "pointer", padding: 0 }}
        >
          ← All domains
        </button>
        <span style={{ color: "#2e2f37", fontSize: 12 }}>|</span>
        <span style={{ fontSize: 13, fontWeight: 500, color: meta.color }}>{domain}</span>
        <span style={{ fontSize: 10, color: `${meta.color}88` }}>
          {data.insights.length} finding{data.insights.length !== 1 ? "s" : ""}
        </span>
        <div style={{ flex: 1 }} />
        <button
          onClick={handleExtend}
          disabled={extending}
          style={{
            fontSize: 10, padding: "3px 9px", borderRadius: 4,
            background: `${meta.color}15`, color: meta.color,
            border: `0.5px solid ${meta.border}`,
            cursor: extending ? "wait" : "pointer",
            opacity: extending ? 0.5 : 1,
          }}
        >
          {extending ? "scheduling…" : data.queries_used >= data.budget_cap ? "Explore 5 more" : "+5 queries"}
        </button>
      </div>

      {/* Filter bar */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8, alignItems: "center" }}>
        {/* Novelty dropdown */}
        <select
          value={filterNovelty ?? ""}
          onChange={e => setFilterNovelty(e.target.value !== "" ? Number(e.target.value) : null)}
          style={{
            fontSize: 10, padding: "4px 8px", borderRadius: 4,
            background: "#111115",
            color: filterNovelty !== null ? noveltyMeta(filterNovelty).color : "#4a4b57",
            border: "0.5px solid #1e1f24", cursor: "pointer",
          }}
        >
          <option value="">All levels</option>
          {[5, 4, 3, 2, 1].map(n => (
            <option key={n} value={n}>{NOVELTY[n].label}</option>
          ))}
        </select>

        {/* Angle dropdown */}
        {angles.length > 1 && (
          <select
            value={filterAngle ?? ""}
            onChange={e => setFilterAngle(e.target.value || null)}
            style={{
              fontSize: 10, padding: "4px 8px", borderRadius: 4,
              background: "#111115",
              color: filterAngle ? meta.color : "#4a4b57",
              border: "0.5px solid #1e1f24", cursor: "pointer",
            }}
          >
            <option value="">All angles</option>
            {angles.map(a => (
              <option key={a} value={a}>{a.replace(/_/g, " ")}</option>
            ))}
          </select>
        )}

        {/* Search */}
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search findings…"
          style={{
            flex: 1, minWidth: 100, fontSize: 11, padding: "4px 9px",
            borderRadius: 4, background: "#111115",
            color: "#9a9ba4", border: "0.5px solid #1e1f24",
            outline: "none",
          }}
        />

        {/* Clear */}
        {hasFilters && (
          <button
            onClick={() => { setFilterNovelty(null); setFilterAngle(null); setSearch(""); }}
            style={{ fontSize: 10, color: "#4a4b57", background: "none", border: "none", cursor: "pointer", padding: 0 }}
          >
            Clear ×
          </button>
        )}

        {/* Queries toggle */}
        <button
          onClick={() => setShowTrace(v => !v)}
          style={{
            fontSize: 10, padding: "4px 10px", borderRadius: 4,
            background: showTrace ? "#1a1e2e" : "#111115",
            color: showTrace ? "#7ba8f7" : "#3e3f4a",
            border: `0.5px solid ${showTrace ? "#2a3050" : "#1e1f24"}`,
            cursor: "pointer",
          }}
        >
          Queries{domainEps.length > 0 ? ` ${domainEps.length}` : ""}
        </button>
      </div>

      {/* Active filter chips */}
      {hasFilters && (
        <div style={{ display: "flex", gap: 5, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
          {filterNovelty !== null && (() => {
            const nv = noveltyMeta(filterNovelty);
            return (
              <span style={{
                fontSize: 10, padding: "2px 8px", borderRadius: 4,
                background: nv.bg, color: nv.color, border: `0.5px solid ${nv.border}`,
                display: "inline-flex", alignItems: "center", gap: 4,
              }}>
                {nv.label}
                <button onClick={() => setFilterNovelty(null)} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", padding: 0, lineHeight: 1 }}>×</button>
              </span>
            );
          })()}
          {filterAngle !== null && (
            <span style={{
              fontSize: 10, padding: "2px 8px", borderRadius: 4,
              background: meta.bg, color: meta.color, border: `0.5px solid ${meta.border}`,
              display: "inline-flex", alignItems: "center", gap: 4,
            }}>
              {filterAngle.replace(/_/g, " ")}
              <button onClick={() => setFilterAngle(null)} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", padding: 0, lineHeight: 1 }}>×</button>
            </span>
          )}
          {search && (
            <span style={{
              fontSize: 10, padding: "2px 8px", borderRadius: 4,
              background: "#111115", color: "#6e6f78", border: "0.5px solid #1e1f24",
              display: "inline-flex", alignItems: "center", gap: 4,
            }}>
              &quot;{search.length > 20 ? search.slice(0, 20) + "…" : search}&quot;
              <button onClick={() => setSearch("")} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", padding: 0, lineHeight: 1 }}>×</button>
            </span>
          )}
          <span style={{ fontSize: 10, color: "#3e3f4a" }}>
            {filtered.length} result{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>
      )}

      {/* Content */}
      {showTrace ? (
        domainEps.length === 0
          ? <p style={{ fontSize: 11, color: "#3e3f4a", fontStyle: "italic" }}>No queries yet.</p>
          : [...domainEps].reverse().map(ep => (
              <EpisodeRow key={`${ep.episode_id}-${ep.ts}`} ep={ep} domain={domain} />
            ))
      ) : (
        filtered.length === 0
          ? <p style={{ fontSize: 11, color: "#3e3f4a", fontStyle: "italic" }}>
              {hasFilters ? "No findings match these filters." : "No findings yet — exploration is running or budget not started."}
            </p>
          : filtered.map(ins => <FindingCard key={ins.id} insight={ins} canvasId={canvasId} />)
      )}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

interface Props {
  connectionId: string;
  isActive: boolean;
  canvasId?: string;
}

export function DomainIntelPanel({ connectionId, isActive, canvasId }: Props) {
  const [data, setData]         = useState<Record<string, DomainInsights>>({});
  const [episodes, setEpisodes] = useState<ExplorationEpisode[]>([]);
  const [tick, setTick]         = useState(0);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!isActive) return;
    let cancelled = false;

    const load = async () => {
      try {
        const [d, eps] = canvasId
          ? await Promise.all([getCanvasDomainInsights(canvasId), getCanvasExplorationEpisodes(canvasId)])
          : await Promise.all([getDomainInsights(connectionId), getExplorationEpisodes(connectionId)]);
        if (!cancelled) { setData(d); setEpisodes(eps); }
      } catch { /* silently ignore — stale data stays, next poll retries */ }
    };

    load();
    const t = setInterval(load, 10_000);
    return () => { cancelled = true; clearInterval(t); };
  }, [connectionId, canvasId, isActive, tick]);

  const domains = Object.keys(data);

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
    <div>
      {selected && data[selected] ? (
        /* ── Detail view ── */
        <DomainDetailView
          domain={selected}
          data={data[selected]}
          episodes={episodes}
          connectionId={connectionId}
          canvasId={canvasId}
          onBack={() => setSelected(null)}
          onExtend={() => setTick(t => t + 1)}
        />
      ) : (
        /* ── Overview dashboard ── */
        <div>
          {/* Summary header */}
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 14 }}>
            <span style={{ fontSize: 11, color: "#3e3f4a" }}>
              {domains.length} domain{domains.length !== 1 ? "s" : ""}
              {" · "}
              {domains.reduce((n, d) => n + (data[d]?.insights.length ?? 0), 0)} total findings
            </span>
          </div>

          {/* Domain cards grid */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
            {domains.map(domain => (
              <DomainOverviewCard
                key={domain}
                domain={domain}
                data={data[domain]}
                onSelect={setSelected}
                connectionId={connectionId}
                canvasId={canvasId}
                onExtend={() => setTick(t => t + 1)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
