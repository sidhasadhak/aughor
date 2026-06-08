"use client";

/**
 * BriefingPanel — M24a + M24b Synthesis Layer
 *
 * Distils cross-domain intelligence into a coherent Monday morning brief.
 *
 * M24a: deterministic front-end synthesis (headline + signals + patterns)
 * M24b: LLM-authored narrative with inline citation markers [1][2][3]
 *
 * Data sources:
 *   • getDomainInsights()         — all domain findings, sorted by novelty
 *   • getPatterns()               — cross-domain structural patterns
 *   • getOrgIntelligence()        — promoted org-level signals
 *   • generateBriefingNarrative() — LLM prose with citation links (M24b)
 */

import { useEffect, useState, useCallback, useRef } from "react";
import {
  getDomainInsights,
  getCanvasDomainInsights,
  getPatterns,
  getOrgIntelligence,
  generateBriefingNarrative,
  generateCanvasBriefingNarrative,
  getCatalogTree,
  getExplorerStatus,
  startExplorer,
  stopExplorer,
  restartExplorer,
  triggerDomainIntelligence,
  type DomainInsights,
  type ExplorationInsight,
  type Pattern,
  type OrgInsight,
  type BriefingCitation,
  type BriefingNarrativeResponse,
  type ExplorerStatus,
} from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────────

interface SynthesisSignal {
  insight: ExplorationInsight;
  domain: string;
}

interface DomainStat {
  name:       string;
  count:      number;
  avgNovelty: number;
  maxNovelty: number;
}

interface BriefingData {
  headline:      SynthesisSignal | null;
  signals:       SynthesisSignal[];
  patterns:      Pattern[];
  orgInsights:   OrgInsight[];
  domains:       DomainStat[];
  domainCount:   number;
  totalInsights: number;
  synthesizedAt: string;
}

// ── Inline citation renderer ───────────────────────────────────────────────────
// Parses narrative text for [N] markers and renders them as interactive chips.

function CitationChip({
  ref: refNum,
  citation,
  onInvestigate,
}: {
  ref: string;
  citation: BriefingCitation | undefined;
  onInvestigate: (q: string) => void;
}) {
  const [tooltip, setTooltip] = useState(false);

  return (
    <span style={{ position: "relative", display: "inline" }}>
      <span
        onMouseEnter={() => setTooltip(true)}
        onMouseLeave={() => setTooltip(false)}
        onClick={() => citation && onInvestigate(`Investigate: ${citation.finding}`)}
        style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 18, height: 18, borderRadius: "50%",
          fontSize: 9, fontWeight: 700, fontFamily: "var(--font-mono)",
          background: "var(--blue3)", color: "var(--bg-0)",
          cursor: citation ? "pointer" : "default",
          verticalAlign: "middle", marginLeft: 2, flexShrink: 0,
          transition: "background .1s",
          userSelect: "none" as const,
        }}
        onMouseDown={e => { (e.currentTarget as HTMLElement).style.background = "var(--blue4)"; }}
        onMouseUp={e => { (e.currentTarget as HTMLElement).style.background = "var(--blue3)"; }}
      >
        {refNum}
      </span>
      {tooltip && citation && (
        <span style={{
          position: "absolute", bottom: "calc(100% + 6px)", left: "50%",
          transform: "translateX(-50%)",
          width: 240, padding: "8px 10px",
          background: "var(--bg-3)", border: "1px solid var(--b2)",
          borderRadius: "var(--r2)", boxShadow: "0 4px 16px rgba(0,0,0,.4)",
          zIndex: 50, pointerEvents: "none" as const,
        }}>
          <div style={{ fontSize: 9, fontWeight: 600, color: "var(--t4)", textTransform: "uppercase" as const, letterSpacing: ".07em", marginBottom: 4 }}>
            {citation.domain}{citation.angle ? ` · ${citation.angle}` : ""}
          </div>
          <div style={{ fontSize: 11, color: "var(--t2)", lineHeight: 1.5 }}>
            {citation.finding.length > 120 ? citation.finding.slice(0, 120) + "…" : citation.finding}
          </div>
        </span>
      )}
    </span>
  );
}

function NarrativeText({
  text,
  citations,
  onInvestigate,
}: {
  text: string;
  citations: BriefingCitation[];
  onInvestigate: (q: string) => void;
}) {
  const citationMap = Object.fromEntries(citations.map(c => [c.ref, c]));
  // Split on [N] markers
  const parts = text.split(/(\[\d+\])/g);

  return (
    <span>
      {parts.map((part, i) => {
        const match = part.match(/^\[(\d+)\]$/);
        if (match) {
          return (
            <CitationChip
              key={i}
              ref={match[1]}
              citation={citationMap[match[1]]}
              onInvestigate={onInvestigate}
            />
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </span>
  );
}

// ── Narrative card ─────────────────────────────────────────────────────────────

function NarrativeCard({
  narrative,
  onInvestigate,
}: {
  narrative: BriefingNarrativeResponse;
  onInvestigate: (q: string) => void;
}) {
  return (
    <div style={{
      background: "linear-gradient(135deg, color-mix(in srgb, var(--blue4) 8%, var(--bg-2)), var(--bg-2))",
      border: "1px solid color-mix(in srgb, var(--blue4) 22%, var(--b1))",
      borderRadius: "var(--r3)", padding: "18px 22px",
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span style={{
          fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: "var(--r1)",
          background: "color-mix(in srgb, var(--blue4) 16%, transparent)",
          border: "1px solid color-mix(in srgb, var(--blue4) 30%, transparent)",
          color: "var(--blue4)", textTransform: "uppercase" as const, letterSpacing: ".09em",
        }}>
          AI Synthesis
        </span>
        {narrative.headline_theme && (
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)", letterSpacing: ".01em" }}>
            {narrative.headline_theme}
          </span>
        )}
        {narrative.generated_at && (
          <span style={{ fontSize: 10, color: "var(--t4)", marginLeft: "auto" }}>
            {timeAgo(narrative.generated_at)}
          </span>
        )}
      </div>

      {/* Narrative prose with inline citations */}
      <div style={{
        fontSize: 13, color: "var(--t1)", lineHeight: 1.75, fontWeight: 400,
        letterSpacing: ".01em",
      }}>
        <NarrativeText
          text={narrative.narrative}
          citations={narrative.citations}
          onInvestigate={onInvestigate}
        />
      </div>

      {/* Citation legend */}
      {narrative.citations.length > 0 && (
        <div style={{ marginTop: 14, display: "flex", flexDirection: "column" as const, gap: 4 }}>
          {narrative.citations.map(c => (
            <div
              key={c.ref}
              onClick={() => onInvestigate(`Investigate: ${c.finding}`)}
              style={{
                display: "flex", gap: 8, alignItems: "flex-start",
                cursor: "pointer", borderRadius: "var(--r2)", padding: "4px 6px",
                transition: "background .1s",
              }}
              onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = "var(--bg-3)"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}
            >
              <span style={{
                width: 16, height: 16, borderRadius: "50%", flexShrink: 0, marginTop: 1,
                fontSize: 8, fontWeight: 700, fontFamily: "var(--font-mono)",
                background: "var(--blue3)", color: "var(--bg-0)",
                display: "inline-flex", alignItems: "center", justifyContent: "center",
              }}>
                {c.ref}
              </span>
              <span style={{ fontSize: 10, color: "var(--t3)", lineHeight: 1.5 }}>
                <span style={{ color: "var(--t2)", fontWeight: 500 }}>{c.domain}</span>
                {c.angle ? ` · ${c.angle}` : ""} —{" "}
                {c.finding.length > 100 ? c.finding.slice(0, 100) + "…" : c.finding}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Narrative generate button ──────────────────────────────────────────────────

function GenerateBriefButton({
  loading,
  hasNarrative,
  onClick,
}: {
  loading: boolean;
  hasNarrative: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      style={{
        display: "inline-flex", alignItems: "center", gap: 7,
        padding: "8px 16px", borderRadius: "var(--r2)", fontSize: 12, fontWeight: 500,
        background: loading
          ? "var(--bg-2)"
          : "color-mix(in srgb, var(--blue4) 14%, var(--bg-2))",
        border: `1px solid ${loading ? "var(--b1)" : "color-mix(in srgb, var(--blue4) 32%, var(--b1))"}`,
        color: loading ? "var(--t3)" : "var(--blue4)",
        cursor: loading ? "not-allowed" : "pointer",
        transition: "all .15s",
      }}
      onMouseEnter={e => { if (!loading) e.currentTarget.style.background = "color-mix(in srgb, var(--blue4) 22%, var(--bg-2))"; }}
      onMouseLeave={e => { if (!loading) e.currentTarget.style.background = "color-mix(in srgb, var(--blue4) 14%, var(--bg-2))"; }}
    >
      {loading ? (
        <>
          <span style={{
            width: 12, height: 12, border: "2px solid var(--b2)",
            borderTop: "2px solid var(--blue4)", borderRadius: "50%",
            animation: "spin 1s linear infinite", flexShrink: 0,
          }} />
          Generating…
        </>
      ) : (
        <>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z" />
          </svg>
          {hasNarrative ? "Regenerate Brief" : "Generate AI Brief"}
        </>
      )}
    </button>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function noveltyColor(n: number): string {
  if (n >= 7) return "var(--grn3)";
  if (n >= 5) return "var(--blue4)";
  if (n >= 3) return "var(--amb3)";
  return "var(--t4)";
}

function noveltyLabel(n: number): string {
  if (n >= 7) return "High";
  if (n >= 5) return "Notable";
  if (n >= 3) return "Mid";
  return "Low";
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

const PATTERN_TYPE_COLORS: Record<string, string> = {
  angle:       "var(--blue4)",
  entity:      "var(--vio3)",
  convergence: "var(--grn3)",
};

const PATTERN_TYPE_ICONS: Record<string, string> = {
  angle:       "↻",
  entity:      "⊕",
  convergence: "◎",
};

// ── Synthesis engine ───────────────────────────────────────────────────────────

function synthesize(
  domainData:  Record<string, DomainInsights>,
  patterns:    Pattern[],
  orgInsights: OrgInsight[],
): BriefingData {
  const allSignals: SynthesisSignal[] = [];
  let totalInsights = 0;

  for (const [domain, data] of Object.entries(domainData)) {
    for (const ins of data.insights) {
      allSignals.push({ insight: ins, domain });
      totalInsights++;
    }
  }

  // Sort by novelty desc
  allSignals.sort((a, b) => b.insight.novelty - a.insight.novelty);

  const headline = allSignals[0] ?? null;

  // Build supporting signals: breadth first (one per domain), then fill to 6
  const seenIds    = new Set<string>(headline ? [headline.insight.id] : []);
  const seenDomains = new Set<string>();
  const signals: SynthesisSignal[] = [];

  // Pass 1 — breadth
  for (const s of allSignals) {
    if (signals.length >= 6) break;
    if (seenIds.has(s.insight.id)) continue;
    if (seenDomains.has(s.domain)) continue;
    seenIds.add(s.insight.id);
    seenDomains.add(s.domain);
    signals.push(s);
  }

  // Pass 2 — fill with highest-novelty remainder
  for (const s of allSignals) {
    if (signals.length >= 6) break;
    if (seenIds.has(s.insight.id)) continue;
    seenIds.add(s.insight.id);
    signals.push(s);
  }

  // Per-domain stats for the coverage chart (where the intelligence concentrates).
  const domains: DomainStat[] = Object.entries(domainData)
    .map(([name, data]) => {
      const ns = data.insights.map(i => i.novelty);
      return {
        name,
        count: ns.length,
        avgNovelty: ns.length ? ns.reduce((a, b) => a + b, 0) / ns.length : 0,
        maxNovelty: ns.length ? Math.max(...ns) : 0,
      };
    })
    .filter(d => d.count > 0)
    .sort((a, b) => b.count - a.count || b.maxNovelty - a.maxNovelty);

  return {
    headline,
    signals,
    patterns:      patterns.slice(0, 5),
    orgInsights:   orgInsights.slice(0, 3),
    domains,
    domainCount:   domains.length,
    totalInsights,
    synthesizedAt: new Date().toISOString(),
  };
}

// ── Visual primitives ────────────────────────────────────────────────────────

/** A compact bar showing a finding's novelty/signal strength (0–10). */
function NoveltyMeter({ novelty, width = 56, showValue = true }: { novelty: number; width?: number; showValue?: boolean }) {
  const pct = Math.max(4, Math.min(100, (novelty / 10) * 100));
  const color = noveltyColor(novelty);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }} title={`Novelty ${novelty.toFixed(1)} / 10`}>
      <span style={{ width, height: 5, borderRadius: 3, background: "var(--bg-3)", display: "inline-block", overflow: "hidden", flexShrink: 0 }}>
        <span style={{ display: "block", height: "100%", width: `${pct}%`, background: color, borderRadius: 3, transition: "width .5s ease" }} />
      </span>
      {showValue && <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color, fontWeight: 600 }}>{novelty.toFixed(1)}</span>}
    </span>
  );
}

/** Horizontal bar chart of findings per domain — shows the *shape* of the intelligence
 *  (which domains dominate) at a glance, with novelty driving bar opacity. */
function DomainCoverageChart({ domains }: { domains: DomainStat[] }) {
  const max = Math.max(1, ...domains.map(d => d.count));
  return (
    <div style={{ display: "flex", flexDirection: "column" as const, gap: 9 }}>
      {domains.slice(0, 8).map(d => {
        const color = domainColor(d.name);
        const pct = Math.max(5, (d.count / max) * 100);
        return (
          <div key={d.name} style={{ display: "flex", flexDirection: "column" as const, gap: 3 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
              <span style={{ fontSize: 11, color: "var(--t2)", textTransform: "capitalize" as const, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const }}>{d.name}</span>
              <span style={{ fontSize: 10, color: "var(--t4)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>{d.count}</span>
            </div>
            <div style={{ height: 6, borderRadius: 3, background: "var(--bg-3)", overflow: "hidden" }}>
              <div style={{
                height: "100%", width: `${pct}%`, background: color, borderRadius: 3,
                opacity: 0.45 + Math.min(0.55, d.maxNovelty / 13), transition: "width .5s ease",
              }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Domain tag ─────────────────────────────────────────────────────────────────

const DOMAIN_COLORS = [
  "var(--blue4)", "var(--vio3)", "var(--grn3)",
  "var(--amb3)",  "var(--chart-4)", "var(--chart-5)",
];

function domainColor(domain: string): string {
  let h = 0;
  for (const c of domain) h = (h * 31 + c.charCodeAt(0)) & 0xffff;
  return DOMAIN_COLORS[h % DOMAIN_COLORS.length];
}

function DomainTag({ domain }: { domain: string }) {
  const color = domainColor(domain);
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "2px 8px", borderRadius: "var(--r2)", fontSize: 10,
      background:  `color-mix(in srgb, ${color} 12%, transparent)`,
      border:      `1px solid color-mix(in srgb, ${color} 28%, transparent)`,
      color, fontWeight: 500, textTransform: "capitalize" as const,
      letterSpacing: ".02em", flexShrink: 0,
    }}>
      {domain}
    </span>
  );
}

// ── Headline card ──────────────────────────────────────────────────────────────

function HeadlineCard({ signal, onInvestigate }: {
  signal:       SynthesisSignal;
  onInvestigate: (q: string) => void;
}) {
  const { insight, domain } = signal;
  const nColor = noveltyColor(insight.novelty);

  return (
    <div style={{
      background:  "var(--bg-2)",
      border:      `1px solid color-mix(in srgb, ${nColor} 28%, var(--b1))`,
      borderLeft:  `3px solid ${nColor}`,
      borderRadius: "var(--r3)", padding: "20px 24px",
    }}>
      {/* Badge row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" as const }}>
        <span style={{
          padding: "3px 8px", borderRadius: "var(--r2)", fontSize: 10, fontWeight: 600,
          background: `color-mix(in srgb, ${nColor} 14%, transparent)`,
          border:     `1px solid color-mix(in srgb, ${nColor} 28%, transparent)`,
          color: nColor, textTransform: "uppercase" as const, letterSpacing: ".07em",
        }}>
          {noveltyLabel(insight.novelty)}
        </span>
        <DomainTag domain={domain} />
        {insight.angle && (
          <span style={{ fontSize: 10, color: "var(--t4)" }}>{insight.angle}</span>
        )}
        <span style={{ marginLeft: "auto" }}><NoveltyMeter novelty={insight.novelty} width={64} /></span>
      </div>

      {/* Finding */}
      <div style={{ fontSize: 14, fontWeight: 500, color: "var(--t1)", lineHeight: 1.65, marginBottom: 16 }}>
        {insight.finding}
      </div>

      {/* Footer */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" as const }}>
        {insight.entities_involved.length > 0 && (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" as const }}>
            {insight.entities_involved.slice(0, 4).map(e => (
              <span key={e} style={{
                padding: "1px 6px", borderRadius: "var(--r1)", fontSize: 10,
                background: "var(--bg-3)", border: "1px solid var(--b1)",
                color: "var(--t3)", fontFamily: "var(--font-mono)",
              }}>{e.replace(/_/g, " ")}</span>
            ))}
          </div>
        )}
        <button
          onClick={() => onInvestigate(`Investigate: ${insight.finding}`)}
          style={{
            marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 6,
            padding: "6px 14px", borderRadius: "var(--r2)", fontSize: 12, fontWeight: 500,
            background: "var(--bg-sel)", border: "1px solid var(--blue2)",
            color: "var(--blue4)", cursor: "pointer", transition: "all .12s",
          }}
          onMouseEnter={e => { e.currentTarget.style.background = "color-mix(in srgb, var(--blue4) 16%, transparent)"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "var(--bg-sel)"; }}
        >
          Investigate →
        </button>
      </div>
    </div>
  );
}

// ── Signal card ────────────────────────────────────────────────────────────────

function SignalCard({ signal, onInvestigate }: {
  signal:       SynthesisSignal;
  onInvestigate: (q: string) => void;
}) {
  const { insight, domain } = signal;
  const nColor = noveltyColor(insight.novelty);

  return (
    <div style={{
      background: "var(--bg-2)", border: "1px solid var(--b1)",
      borderTop:  `2px solid ${nColor}`,
      borderRadius: "var(--r3)", padding: "14px 16px",
      display: "flex", flexDirection: "column" as const, gap: 10,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" as const }}>
        <DomainTag domain={domain} />
        {insight.angle && (
          <span style={{ fontSize: 10, color: "var(--t4)" }}>{insight.angle}</span>
        )}
        <span style={{ marginLeft: "auto" }}><NoveltyMeter novelty={insight.novelty} width={40} /></span>
      </div>
      <div style={{ fontSize: 12, color: "var(--t2)", lineHeight: 1.55, flex: 1 }}>
        {insight.finding.length > 160 ? insight.finding.slice(0, 160) + "…" : insight.finding}
      </div>
      <button
        onClick={() => onInvestigate(`Investigate: ${insight.finding}`)}
        style={{
          alignSelf: "flex-start" as const,
          padding: "4px 10px", borderRadius: "var(--r2)", fontSize: 11, fontWeight: 500,
          background: "transparent", border: "1px solid var(--b2)",
          color: "var(--t3)", cursor: "pointer", transition: "all .12s",
        }}
        onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--blue3)"; e.currentTarget.style.color = "var(--blue4)"; }}
        onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b2)"; e.currentTarget.style.color = "var(--t3)"; }}
      >
        Investigate →
      </button>
    </div>
  );
}

// ── Pattern row (sidebar) ──────────────────────────────────────────────────────

function PatternRow({ pattern, onInvestigate }: {
  pattern:      Pattern;
  onInvestigate: (q: string) => void;
}) {
  const color = PATTERN_TYPE_COLORS[pattern.type] ?? "var(--t3)";
  const icon  = PATTERN_TYPE_ICONS[pattern.type]  ?? "·";

  return (
    <div
      onClick={() => onInvestigate(`Investigate the pattern: ${pattern.title}`)}
      style={{
        display: "flex", alignItems: "flex-start", gap: 10,
        padding: "10px 12px", borderRadius: "var(--r2)",
        background: "var(--bg-2)", border: "1px solid var(--b1)",
        cursor: "pointer", transition: "background .1s",
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = "var(--bg-3)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = "var(--bg-2)"; }}
    >
      <span style={{ fontSize: 13, color, flexShrink: 0, lineHeight: 1.4 }}>{icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 11, fontWeight: 500, color: "var(--t1)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const,
        }}>
          {pattern.title}
        </div>
        <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 2 }}>
          {pattern.domains.length} domain{pattern.domains.length !== 1 ? "s" : ""} · {pattern.evidence_count} findings
        </div>
      </div>
      <span style={{
        fontSize: 9, padding: "2px 6px", borderRadius: "var(--r1)", flexShrink: 0,
        background: `color-mix(in srgb, ${color} 12%, transparent)`,
        border:     `1px solid color-mix(in srgb, ${color} 25%, transparent)`,
        color, textTransform: "uppercase" as const, letterSpacing: ".06em", fontWeight: 600,
      }}>
        {pattern.type}
      </span>
    </div>
  );
}

// ── Org signal row (sidebar) ───────────────────────────────────────────────────

function OrgSignalRow({ insight }: { insight: OrgInsight }) {
  const nColor = noveltyColor(insight.novelty);
  return (
    <div style={{
      padding: "10px 12px", borderRadius: "var(--r2)",
      background: "var(--bg-2)", border: "1px solid var(--b1)",
      borderLeft: `2px solid ${nColor}`,
    }}>
      <div style={{ display: "flex", gap: 6, marginBottom: 6, alignItems: "center", flexWrap: "wrap" as const }}>
        <DomainTag domain={insight.domain} />
        {insight.angle && (
          <span style={{ fontSize: 10, color: "var(--t4)", marginLeft: "auto" }}>{insight.angle}</span>
        )}
      </div>
      <div style={{ fontSize: 11, color: "var(--t2)", lineHeight: 1.5 }}>
        {insight.text.length > 120 ? insight.text.slice(0, 120) + "…" : insight.text}
      </div>
    </div>
  );
}

// ── Empty state ────────────────────────────────────────────────────────────────
//
// "Empty" is never silent: we diagnose *why* the briefing has no domain
// intelligence from the explorer status and offer the matching next action.
// The four causes map 1:1 to the explorer lifecycle:
//   never        → no exploration has run (phase pending / no status)   → Start
//   running      → explorer mid-flight (phases 3-8 in progress)         → wait
//   failed       → the run errored out                                  → Restart
//   completeEmpty→ run finished but Phase-8 domain intel is empty        → Trigger
//                  (ontology gate skipped it, or the schema is too sparse)

type EmptyReason =
  | { kind: "never" }
  | { kind: "running"; queries: number; insights: number; phase: string }
  | { kind: "failed"; error: string | null }
  | { kind: "ontologyFailed"; note: string | null }
  | { kind: "completeEmpty"; insights: number };

function emptyReason(status: ExplorerStatus | null): EmptyReason {
  const phase = status?.phase;
  if (!status || !phase || phase === "pending") return { kind: "never" };
  if (phase === "failed")   return { kind: "failed", error: status.error };
  if (phase === "complete") {
    // Phase-8 ran the gate but its prerequisite ontology couldn't be built — a
    // specific, retryable failure, not just "nothing generated yet".
    if (status.domain_intel_skipped) return { kind: "ontologyFailed", note: status.domain_intel_note ?? null };
    return { kind: "completeEmpty", insights: status.insights_found };
  }
  return { kind: "running", queries: status.queries_executed, insights: status.insights_found, phase };
}

const PHASE_LABELS: Record<string, string> = {
  null_meaning:      "resolving null meanings",
  join_verification: "verifying joins",
  lifecycle_mapping: "mapping lifecycles",
  distribution:      "profiling distributions",
  cross_table:       "finding cross-table patterns",
  domain_intel:      "synthesising domain intelligence",
};

function BriefingEmpty({
  status,
  busy,
  onStart,
  onTrigger,
  canvasId,
}: {
  status: ExplorerStatus | null;
  busy: boolean;
  onStart: () => void;
  onTrigger: () => void;
  canvasId?: string;
}) {
  const reason = emptyReason(status);
  const scope = canvasId ? "this canvas's tables" : "this connection";

  let title: string;
  let body: string;
  let cta: { label: string; onClick: () => void } | null = null;
  let spinning = false;

  switch (reason.kind) {
    case "never":
      title = "No exploration has run yet";
      body  = `Briefings synthesise the domain intelligence discovered by the autonomous explorer. Run an exploration on ${scope} to surface findings — they'll appear here automatically.`;
      cta   = { label: "Start exploration", onClick: onStart };
      break;
    case "running":
      spinning = true;
      title = "Exploration in progress";
      body  = `The explorer is ${PHASE_LABELS[reason.phase] ?? reason.phase} — ${reason.queries} ${reason.queries === 1 ? "query" : "queries"} run, ${reason.insights} raw finding${reason.insights === 1 ? "" : "s"} so far. Domain intelligence appears here once the run completes.`;
      break;
    case "failed":
      title = "Exploration failed";
      body  = reason.error
        ? `The last run stopped: ${reason.error}. Restart to try discovering domain intelligence again.`
        : "The last exploration run did not complete. Restart to try again.";
      cta   = { label: "Restart exploration", onClick: onStart };
      break;
    case "ontologyFailed":
      title = "Intelligence couldn't be built";
      body  = `${reason.note || "Domain intelligence is derived from an ontology (object model) of your schema, and that build didn't succeed — usually the schema is too sparse to model."} Rebuild to try again, or query ${scope} directly via Ask or Investigate.`;
      cta   = { label: "Rebuild & retry", onClick: onTrigger };
      break;
    case "completeEmpty":
      title = "No domain intelligence yet";
      body  = `Exploration completed${reason.insights > 0 ? ` with ${reason.insights} raw finding${reason.insights === 1 ? "" : "s"}` : ""}, but no domain intelligence has been synthesised for ${scope} — that's the layer briefings are built from. Generate it now; if it stays empty, the schema may be too sparse to build an ontology (you can still Ask or Investigate the data directly).`;
      cta   = { label: "Generate domain intelligence", onClick: onTrigger };
      break;
  }

  return (
    <div style={{
      flex: 1, display: "flex", flexDirection: "column" as const,
      alignItems: "center", justifyContent: "center", gap: 16, padding: 48,
    }}>
      <div style={{
        width: 56, height: 56, borderRadius: "var(--r3)",
        background: "var(--bg-2)", border: "1px solid var(--b1)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        {spinning ? (
          <div style={{
            width: 22, height: 22, border: "2px solid var(--b2)",
            borderTop: "2px solid var(--blue4)", borderRadius: "50%",
            animation: "spin 1s linear infinite",
          }} />
        ) : (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
            stroke="var(--t4)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 5h18M3 9h18M3 13h12M3 17h8" />
          </svg>
        )}
      </div>
      <div style={{ textAlign: "center" as const, maxWidth: 400 }}>
        <div style={{ fontSize: 14, fontWeight: 500, color: "var(--t2)", marginBottom: 6 }}>
          {title}
        </div>
        <div style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.6 }}>
          {body}
        </div>
      </div>
      {cta && (
        <button
          onClick={cta.onClick}
          disabled={busy}
          style={{
            display: "inline-flex", alignItems: "center", gap: 7,
            padding: "8px 18px", borderRadius: "var(--r2)", fontSize: 12, fontWeight: 500,
            background: busy ? "var(--bg-2)" : "color-mix(in srgb, var(--blue4) 14%, var(--bg-2))",
            border: `1px solid ${busy ? "var(--b1)" : "color-mix(in srgb, var(--blue4) 32%, var(--b1))"}`,
            color: busy ? "var(--t3)" : "var(--blue4)",
            cursor: busy ? "not-allowed" : "pointer", transition: "all .15s",
          }}
          onMouseEnter={e => { if (!busy) e.currentTarget.style.background = "color-mix(in srgb, var(--blue4) 22%, var(--bg-2))"; }}
          onMouseLeave={e => { if (!busy) e.currentTarget.style.background = "color-mix(in srgb, var(--blue4) 14%, var(--bg-2))"; }}
        >
          {busy ? (
            <>
              <span style={{ width: 12, height: 12, border: "2px solid var(--b2)", borderTop: "2px solid var(--blue4)", borderRadius: "50%", animation: "spin 1s linear infinite", flexShrink: 0 }} />
              Working…
            </>
          ) : (
            <>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z" />
              </svg>
              {cta.label}
            </>
          )}
        </button>
      )}
    </div>
  );
}

// ── Loading state ──────────────────────────────────────────────────────────────

function BriefingLoading() {
  return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{
        display: "flex", flexDirection: "column" as const, alignItems: "center", gap: 12,
      }}>
        <div style={{
          width: 32, height: 32,
          border: "2px solid var(--b1)",
          borderTop: "2px solid var(--blue4)",
          borderRadius: "50%",
          animation: "spin 1s linear infinite",
        }} />
        <div style={{ fontSize: 12, color: "var(--t3)" }}>Synthesizing intelligence…</div>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function BriefingPanel({
  connectionId,
  onInvestigate,
  canvasId,
}: {
  connectionId: string;
  onInvestigate: (q: string) => void;
  /** When set, the briefing is scoped to this Canvas's curated tables (not the whole
   *  connection) — keeps Briefing consistent with the already-canvas-scoped Domains. */
  canvasId?: string;
}) {
  const [briefing, setBriefing]             = useState<BriefingData | null>(null);
  const [loading, setLoading]               = useState(false);
  const [error, setError]                   = useState<string | null>(null);
  const [narrative, setNarrative]           = useState<BriefingNarrativeResponse | null>(null);
  const [narrativeLoading, setNarrativeLoading] = useState(false);
  const [narrativeError, setNarrativeError] = useState<string | null>(null);
  const [schemas, setSchemas]                 = useState<string[]>([]);
  const [selectedSchema, setSelectedSchema]   = useState<string | null>(null);
  const [explorerStatus, setExplorerStatus]   = useState<ExplorerStatus | null>(null);
  const [explorerBusy, setExplorerBusy]       = useState(false);

  const load = useCallback(async () => {
    if (!canvasId && !connectionId) return;
    setLoading(true);
    setError(null);
    try {
      const schema = selectedSchema ?? undefined;
      // Canvas scope: use the canvas's domain insights; patterns aren't computed per-canvas
      // (the canvas briefing endpoint derives them internally for the narrative).
      const [domainRaw, patternsRes, orgInsights] = await Promise.all([
        canvasId ? getCanvasDomainInsights(canvasId) : getDomainInsights(connectionId, schema),
        canvasId
          ? Promise.resolve({ patterns: [] as Pattern[], count: 0 })
          : getPatterns(connectionId, false, schema).catch(() => ({ patterns: [] as Pattern[], count: 0 })),
        getOrgIntelligence().catch(() => [] as OrgInsight[]),
      ]);
      setBriefing(synthesize(domainRaw, patternsRes.patterns, orgInsights));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load briefing");
    } finally {
      setLoading(false);
    }
  }, [connectionId, canvasId, selectedSchema]);

  const generateNarrative = useCallback(async (forceRefresh = false) => {
    if (!canvasId && !connectionId) return;
    setNarrativeLoading(true);
    setNarrativeError(null);
    try {
      const result = canvasId
        ? await generateCanvasBriefingNarrative(canvasId, forceRefresh)
        : await generateBriefingNarrative(connectionId, forceRefresh, selectedSchema ?? undefined);
      if (result.available) setNarrative(result);
      else setNarrativeError("No domain intelligence available — run an exploration first.");
    } catch (e) {
      setNarrativeError(e instanceof Error ? e.message : "Failed to generate narrative");
    } finally {
      setNarrativeLoading(false);
    }
  }, [connectionId, canvasId, selectedSchema]);

  // Shared explorer actions — used by both the control bar and the empty-state CTA.
  const runExplorer = useCallback(async () => {
    if (!connectionId) return;
    setExplorerBusy(true);
    try { await startExplorer(connectionId); } catch {}
    setExplorerBusy(false);
  }, [connectionId]);

  const runTriggerIntel = useCallback(async () => {
    if (!connectionId) return;
    setExplorerBusy(true);
    try { await triggerDomainIntelligence(connectionId); } catch {}
    setExplorerBusy(false);
  }, [connectionId]);

  useEffect(() => { load(); }, [load]);

  // Fetch available schemas for this connection (N/A for a canvas — already scoped)
  useEffect(() => {
    if (canvasId || !connectionId) { setSchemas([]); setSelectedSchema(null); return; }
    getCatalogTree()
      .then(tree => {
        const entry = tree.sections.flatMap(s => s.entries).find(e => e.conn_id === connectionId);
        const names = entry?.schemas.map(s => s.name) ?? [];
        setSchemas(names);
        // If only one schema, auto-select it; otherwise keep previous or null
        if (names.length === 1) setSelectedSchema(names[0]);
      })
      .catch(() => setSchemas([]));
  }, [connectionId, canvasId]);

  // Auto-fetch cached narrative (no force-refresh) on mount / scope change
  useEffect(() => {
    if ((!canvasId && !connectionId) || narrative !== null) return;
    generateNarrative(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionId, canvasId, selectedSchema]);

  // Poll explorer status every 3 seconds
  useEffect(() => {
    if (!connectionId) return;
    let mounted = true;
    const poll = () => {
      getExplorerStatus(connectionId)
        .then(s => { if (mounted) setExplorerStatus(s); })
        .catch(() => { if (mounted) setExplorerStatus(null); });
    };
    poll();
    const iv = setInterval(poll, 3000);
    return () => { mounted = false; clearInterval(iv); };
  }, [connectionId]);

  // Auto-refresh the briefing the moment an exploration run reaches "complete" —
  // newly-synthesised domain intelligence would otherwise stay hidden until a manual Reload.
  const prevPhaseRef = useRef<string | null>(null);
  useEffect(() => {
    const phase = explorerStatus?.phase ?? null;
    if (prevPhaseRef.current && prevPhaseRef.current !== "complete" && phase === "complete") {
      load();
      setNarrative(null); // let the cached-narrative auto-fetch pick up fresh intel
    }
    prevPhaseRef.current = phase;
  }, [explorerStatus?.phase, load]);

  if (loading)  return <BriefingLoading />;

  if (error) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ fontSize: 12, color: "var(--red4)" }}>{error}</div>
      </div>
    );
  }

  const hasPatterns    = (briefing?.patterns?.length ?? 0) > 0;
  const hasOrgInsights = (briefing?.orgInsights?.length ?? 0) > 0;
  const hasSidebar     = hasPatterns || hasOrgInsights || ((briefing?.domainCount ?? 0) > 0);
  const hasNarrative   = !!narrative?.narrative;
  const isEmpty        = !briefing || briefing.totalInsights === 0;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "20px 28px" }}>

      {/* ── Explorer control bar ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, padding: "8px 12px", borderRadius: "var(--r2)", background: "var(--bg-2)", border: "1px solid var(--b1)" }}>
        <span style={{ fontSize: 11, color: "var(--t3)", fontFamily: "var(--font-mono)", textTransform: "uppercase" }}>
          Explorer
        </span>
        {explorerStatus ? (
          <>
            <span style={{
              fontSize: 11,
              color: explorerStatus.phase === "complete" ? "var(--grn4)" :
                     explorerStatus.phase === "failed" ? "var(--red4)" :
                     explorerStatus.paused ? "var(--amb4)" : "var(--blue4)",
              fontWeight: 500,
            }}>
              {explorerStatus.phase}
              {explorerStatus.paused && " (paused)"}
            </span>
            {explorerStatus.queries_executed > 0 && (
              <span style={{ fontSize: 11, color: "var(--t4)" }}>
                {explorerStatus.queries_executed}q &middot; {explorerStatus.insights_found} insights
              </span>
            )}
          </>
        ) : (
          <span style={{ fontSize: 11, color: "var(--t4)" }}>unknown</span>
        )}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {(!explorerStatus || explorerStatus.phase === "complete" || explorerStatus.phase === "pending" || explorerStatus.phase === "failed") ? (
            <>
              <button
                disabled={explorerBusy}
                onClick={runExplorer}
                style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: "var(--grn2)", color: "var(--grn5)", border: "1px solid var(--grn3)", cursor: explorerBusy ? "default" : "pointer", opacity: explorerBusy ? 0.6 : 1 }}
              >Start</button>
              {explorerStatus?.phase === "complete" && (
                <button
                  disabled={explorerBusy}
                  onClick={runTriggerIntel}
                  style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: "var(--blue2)", color: "var(--blue5)", border: "1px solid var(--blue3)", cursor: explorerBusy ? "default" : "pointer", opacity: explorerBusy ? 0.6 : 1 }}
                >Trigger Intel</button>
              )}
            </>
          ) : (
            <>
              <button
                disabled={explorerBusy}
                onClick={async () => {
                  setExplorerBusy(true);
                  try { await stopExplorer(connectionId); } catch {}
                  setExplorerBusy(false);
                }}
                style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: "var(--red2)", color: "var(--red5)", border: "1px solid var(--red3)", cursor: explorerBusy ? "default" : "pointer", opacity: explorerBusy ? 0.6 : 1 }}
              >Stop</button>
              <button
                disabled={explorerBusy}
                onClick={async () => {
                  setExplorerBusy(true);
                  try { await restartExplorer(connectionId); } catch {}
                  setExplorerBusy(false);
                }}
                style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: "var(--bg-3)", color: "var(--t3)", border: "1px solid var(--b2)", cursor: explorerBusy ? "default" : "pointer", opacity: explorerBusy ? 0.6 : 1 }}
              >Restart</button>
            </>
          )}
        </div>
      </div>

      {isEmpty ? (
        <BriefingEmpty
          status={explorerStatus}
          busy={explorerBusy}
          onStart={runExplorer}
          onTrigger={runTriggerIntel}
          canvasId={canvasId}
        />
      ) : (
        <>

      {/* ── Meta strip ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
        {schemas.length > 1 && (
          <select
            value={selectedSchema ?? ""}
            onChange={e => setSelectedSchema(e.target.value || null)}
            style={{
              fontSize: 11, color: "var(--t1)", background: "var(--bg-1)",
              border: "1px solid var(--b1)", borderRadius: 4, padding: "3px 8px", cursor: "pointer",
            }}
          >
            <option value="">All schemas</option>
            {schemas.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        )}
        <span style={{ fontSize: 11, color: "var(--t3)" }}>
          Synthesized from{" "}
          <span style={{ color: "var(--t2)", fontWeight: 500 }}>{briefing.domainCount} domains</span>
          {" "}·{" "}
          <span style={{ color: "var(--t2)", fontWeight: 500 }}>{briefing.totalInsights} findings</span>
          <span style={{ color: "var(--t4)", marginLeft: 6 }}>· {timeAgo(briefing.synthesizedAt)}</span>
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <GenerateBriefButton
            loading={narrativeLoading}
            hasNarrative={hasNarrative}
            onClick={() => generateNarrative(hasNarrative)}
          />
          <button
            onClick={load}
            style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              padding: "4px 10px", borderRadius: "var(--r2)", fontSize: 11,
              background: "var(--bg-2)", border: "1px solid var(--b1)",
              color: "var(--t3)", cursor: "pointer", transition: "all .1s",
            }}
            onMouseEnter={e => { e.currentTarget.style.color = "var(--t1)"; e.currentTarget.style.borderColor = "var(--b2)"; }}
            onMouseLeave={e => { e.currentTarget.style.color = "var(--t3)"; e.currentTarget.style.borderColor = "var(--b1)"; }}
          >
            ↻ Reload
          </button>
        </div>
      </div>

      {/* ── Two-column layout ── */}
      <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>

        {/* ── Main column ── */}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" as const, gap: 24 }}>

          {/* AI Narrative (M24b) */}
          {(hasNarrative || narrativeLoading || narrativeError) && (
            <div>
              <div className="aug-label" style={{ marginBottom: 10 }}>AI Synthesis</div>
              {narrativeLoading && (
                <div style={{
                  background: "color-mix(in srgb, var(--blue4) 6%, var(--bg-2))",
                  border: "1px solid color-mix(in srgb, var(--blue4) 18%, var(--b1))",
                  borderRadius: "var(--r3)", padding: "18px 22px",
                  display: "flex", alignItems: "center", gap: 10,
                }}>
                  <span style={{
                    width: 14, height: 14, border: "2px solid var(--b2)",
                    borderTop: "2px solid var(--blue4)", borderRadius: "50%",
                    animation: "spin 1s linear infinite", flexShrink: 0,
                  }} />
                  <span style={{ fontSize: 12, color: "var(--t3)" }}>
                    Writing intelligence brief…
                  </span>
                </div>
              )}
              {!narrativeLoading && narrativeError && (
                <div style={{
                  padding: "10px 14px", borderRadius: "var(--r2)",
                  background: "var(--red1)", border: "1px solid var(--red2)",
                  fontSize: 11, color: "var(--red4)",
                }}>
                  {narrativeError}
                </div>
              )}
              {!narrativeLoading && hasNarrative && narrative && (
                <NarrativeCard narrative={narrative} onInvestigate={onInvestigate} />
              )}
            </div>
          )}

          {/* Headline finding */}
          {briefing.headline && (
            <div>
              <div className="aug-label" style={{ marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
                <span>Headline Finding</span>
                <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: "var(--r1)", background: "var(--bg-3)", border: "1px solid var(--b1)", color: "var(--t4)", textTransform: "uppercase" as const, letterSpacing: ".06em", fontWeight: 600 }}>
                  Top signal
                </span>
              </div>
              <HeadlineCard signal={briefing.headline} onInvestigate={onInvestigate} />
            </div>
          )}

          {/* Supporting signals */}
          {briefing.signals.length > 0 && (
            <div>
              <div className="aug-label" style={{ marginBottom: 10 }}>
                Supporting Signals
                <span style={{ marginLeft: 6, fontWeight: 400, color: "var(--t4)" }}>
                  — cross-domain findings by novelty
                </span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12 }}>
                {briefing.signals.map(s => (
                  <SignalCard key={s.insight.id} signal={s} onInvestigate={onInvestigate} />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Sidebar ── */}
        {hasSidebar && (
          <div style={{ width: 272, flexShrink: 0, display: "flex", flexDirection: "column" as const, gap: 20 }}>

            {/* Domain coverage — a bar chart of findings per domain (where intelligence concentrates) */}
            <div>
              <div className="aug-label" style={{ marginBottom: 10, display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
                <span>Domain Coverage</span>
                <span style={{ fontSize: 10, fontWeight: 400, color: "var(--t4)", fontFamily: "var(--font-mono)" }}>
                  {briefing.domainCount} · {briefing.totalInsights} findings
                </span>
              </div>
              <div style={{
                background: "var(--bg-2)", border: "1px solid var(--b1)",
                borderRadius: "var(--r3)", padding: "14px 16px",
              }}>
                <DomainCoverageChart domains={briefing.domains} />
              </div>
            </div>

            {/* Top patterns */}
            {hasPatterns && (
              <div>
                <div className="aug-label" style={{ marginBottom: 10 }}>Top Patterns</div>
                <div style={{ display: "flex", flexDirection: "column" as const, gap: 6 }}>
                  {briefing.patterns.map(p => (
                    <PatternRow key={p.id} pattern={p} onInvestigate={onInvestigate} />
                  ))}
                </div>
              </div>
            )}

            {/* Org intel */}
            {hasOrgInsights && (
              <div>
                <div className="aug-label" style={{ marginBottom: 10 }}>Org Intelligence</div>
                <div style={{ display: "flex", flexDirection: "column" as const, gap: 6 }}>
                  {briefing.orgInsights.map(o => (
                    <OrgSignalRow key={o.id} insight={o} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )}

      {/* Spinner keyframe */}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
