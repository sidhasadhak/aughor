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

import { useEffect, useState, useCallback, useRef, type ReactNode } from "react";
import {
  getDomainInsights,
  getCanvasDomainInsights,
  getPatterns,
  getOrgIntelligence,
  generateBriefingNarrative,
  generateCanvasBriefingNarrative,
  getExplorerStatus,
  startExplorer,
  stopExplorer,
  restartExplorer,
  triggerDomainIntelligence,
  getCanvasExplorationStatus,
  resumeCanvasExploration,
  stopCanvasExploration,
  restartCanvasExploration,
  triggerCanvasDomainIntelligence,
  promoteCanvasInsight,
  promoteConnectionInsight,
  dismissCanvasInsight,
  dismissConnectionInsight,
  createMonitor,
  getActionTriggers,
  sendFindingToTrigger,
  type DomainInsights,
  type ExplorationInsight,
  type Pattern,
  type OrgInsight,
  type BriefingCitation,
  type BriefingNarrativeResponse,
  type ExplorerStatus,
  type ActionTrigger,
  getInsightReceipt,
  type InsightReceipt,
} from "@/lib/api";
import { subscribeKernelEvents } from "@/lib/events";
import { Spinner } from "@/components/ui/motion";
import { BriefingDashboard } from "@/components/brief/BriefingDashboard";
import { IndustryKpiStrip } from "@/components/brief/IndustryKpiStrip";

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
  /** insight_id → {insight, domain} so a narrative citation can resolve to the full
   *  finding and offer the same actions a finding card has. */
  insightById:   Map<string, SynthesisSignal>;
}

// ── Inline citation renderer ───────────────────────────────────────────────────
// Parses narrative text for [N] markers and renders them as interactive chips.

function CitationChip({
  ref: refNum,
  citation,
  onCitationClick,
}: {
  ref: string;
  citation: BriefingCitation | undefined;
  onCitationClick: (citation: BriefingCitation, e: { clientX: number; clientY: number }) => void;
}) {
  const [tooltip, setTooltip] = useState(false);

  return (
    <span style={{ position: "relative", display: "inline" }}>
      <span
        onMouseEnter={() => setTooltip(true)}
        onMouseLeave={() => setTooltip(false)}
        onClick={e => { if (citation) { setTooltip(false); onCitationClick(citation, e); } }}
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
  onCitationClick,
}: {
  text: string;
  citations: BriefingCitation[];
  onCitationClick: (citation: BriefingCitation, e: { clientX: number; clientY: number }) => void;
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
              onCitationClick={onCitationClick}
            />
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </span>
  );
}

// ── Narrative card ─────────────────────────────────────────────────────────────

/** Shared context a narrative citation needs to open the same action menu a finding
 *  card has (resolve the cited insight, then Monitor/Promote/Share/Evidence/Dismiss). */
interface CitationActionContext {
  insightById:    Map<string, SynthesisSignal>;
  connectionId:   string;
  canvasId?:      string;
  triggers:       ActionTrigger[];
  onEvidence:     (insight: ExplorationInsight, domain: string) => void;
  onTriggersHint: () => void;
  onDismissed:    () => void;
  onInvestigate:  (q: string) => void;
}

function NarrativeCard({
  narrative,
  ctx,
}: {
  narrative: BriefingNarrativeResponse;
  ctx: CitationActionContext;
}) {
  const [active, setActive] = useState<{ citation: BriefingCitation; x: number; y: number } | null>(null);
  const onCitationClick = (citation: BriefingCitation, e: { clientX: number; clientY: number }) =>
    setActive({ citation, x: e.clientX, y: e.clientY });

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
          onCitationClick={onCitationClick}
        />
      </div>

      {/* Citation legend removed — the inline [n] chips in the prose are the pointers;
          the repeated list below was redundant. */}

      {active && (
        <CitationActionsPopover
          citation={active.citation}
          x={active.x}
          y={active.y}
          ctx={ctx}
          onClose={() => setActive(null)}
        />
      )}
    </div>
  );
}

/** Anchored action menu for a narrative citation — resolves the cited insight (or a
 *  minimal stand-in if it was filtered out) and offers the same actions as a finding
 *  card: Monitor / Promote / Share / Evidence / Dismiss, plus Investigate. */
function CitationActionsPopover({
  citation,
  x,
  y,
  ctx,
  onClose,
}: {
  citation: BriefingCitation;
  x: number;
  y: number;
  ctx: CitationActionContext;
  onClose: () => void;
}) {
  const resolved = ctx.insightById.get(citation.insight_id);
  const insight: ExplorationInsight = resolved?.insight ?? {
    id: citation.insight_id, domain: citation.domain, angle: citation.angle,
    entities_involved: [], dimensions: [], measures: [],
    finding: citation.finding, sql: "", confidence: 0, novelty: 0, generated_at: "",
  };
  const domain = resolved?.domain ?? citation.domain;
  const left = Math.max(12, Math.min(x, (typeof window !== "undefined" ? window.innerWidth : 1280) - 332));
  const top  = Math.min(y + 10, (typeof window !== "undefined" ? window.innerHeight : 800) - 180);

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 99 }} />
      <div
        onClick={e => e.stopPropagation()}
        style={{
          position: "fixed", left, top, zIndex: 100, width: 320,
          background: "var(--bg-2)", border: "1px solid var(--b2)", borderRadius: "var(--r3)",
          boxShadow: "0 8px 28px rgba(0,0,0,.45)", padding: 12,
          display: "flex", flexDirection: "column", gap: 10,
        }}
      >
        <div style={{ fontSize: 9, fontWeight: 600, color: "var(--t4)", textTransform: "uppercase" as const, letterSpacing: ".07em" }}>
          {domain}{citation.angle ? ` · ${citation.angle}` : ""}
        </div>
        <div style={{ fontSize: 11, color: "var(--t2)", lineHeight: 1.5 }}>
          {citation.finding.length > 180 ? citation.finding.slice(0, 180) + "…" : citation.finding}
        </div>
        <FindingActions
          insight={insight}
          domain={domain}
          connectionId={ctx.connectionId}
          canvasId={ctx.canvasId}
          triggers={ctx.triggers}
          onEvidence={ins => { ctx.onEvidence(ins, domain); onClose(); }}
          onTriggersHint={ctx.onTriggersHint}
          onDismissed={() => { ctx.onDismissed(); onClose(); }}
        />
        <button
          onClick={() => { ctx.onInvestigate(`Investigate: ${citation.finding}`); onClose(); }}
          className="aug-btn"
          style={{
            alignSelf: "flex-start", fontSize: 11, color: "var(--blue5)",
            background: "var(--bg-sel)", border: "1px solid var(--b1)",
            borderRadius: "var(--r2)", padding: "4px 10px", cursor: "pointer",
          }}
        >
          Investigate →
        </button>
      </div>
    </>
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
            animation: "aug-spin var(--dur-breath) linear infinite", flexShrink: 0,
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

  // Index every insight by id (including degenerate ones) so a citation referencing
  // any finding can resolve to the full object for its action menu.
  const insightById = new Map<string, SynthesisSignal>();

  // Never surface a degenerate "no data" finding — it must not win the headline or a
  // signal slot (the backend now drops these at the source; this also hides any that
  // were stored before that fix). Such findings stay visible only in the full Hub ledger.
  for (const [domain, data] of Object.entries(domainData)) {
    for (const ins of data.insights) {
      insightById.set(ins.id, { insight: ins, domain });
      if (isDegenerateFinding(ins)) continue;
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
      const ns = data.insights.filter(i => !isDegenerateFinding(i)).map(i => i.novelty);
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
    insightById,
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

// ── Finding-level actions ────────────────────────────────────────────────────
// Create Monitor · Promote to Org · Share · Evidence — makes each finding
// actionable so intelligence REACHES the user (backlog #4).

// A "no data" finding (empty/all-NULL result) must not be actionable: monitoring,
// promoting, or sharing it just propagates noise — and a monitor built from its SQL
// fires "No condition met" forever. The explorer now drops these at the source; this
// guards any that already exist or slip through. Investigate/Evidence stay enabled so
// the user can still inspect *why* there's no data.
const _NO_DATA_RE = /(returned no data|no data (found|available|to report|for)|0 \w+ (were |was )?found|null values for all|no rows (returned|found|matched)|query (failed|errored)|no matching (rows|records|data)|empty result set)/i;

export function isDegenerateFinding(insight: ExplorationInsight): boolean {
  const f = (insight.finding || "").trim();
  if (!f) return true;
  return _NO_DATA_RE.test(f);
}

type ActStatus = "idle" | "busy" | "done" | "error";

function ActionButton({ label, title, status, color, onClick, disabled }: {
  label: string; title: string; status: ActStatus;
  color?: string; onClick: () => void; disabled?: boolean;
}) {
  const c = color || "var(--t3)";
  const txt = status === "done" ? "✓" : status === "error" ? "!" : label;
  return (
    <button
      title={title}
      onClick={onClick}
      disabled={disabled || status === "busy" || status === "done"}
      style={{
        padding: "3px 9px", borderRadius: "var(--r2)", fontSize: 11, fontWeight: 500,
        background: "transparent",
        border: `1px solid ${status === "done" ? "var(--grn3)" : "var(--b2)"}`,
        color: status === "done" ? "var(--grn4)" : status === "error" ? "var(--red4)" : c,
        display: "inline-flex", alignItems: "center", gap: 5,
        cursor: disabled || status === "busy" || status === "done" ? "default" : "pointer",
        opacity: disabled ? 0.45 : 1, transition: "all .12s", whiteSpace: "nowrap" as const,
      }}
      onMouseEnter={e => { if (!disabled && status === "idle") { e.currentTarget.style.borderColor = c; } }}
      onMouseLeave={e => { if (status === "idle") { e.currentTarget.style.borderColor = "var(--b2)"; } }}
    >
      {status === "busy" && <Spinner size={10} color="currentColor" />}
      {status === "done" ? `${label} ${txt}` : label}
    </button>
  );
}

export function FindingActions({ insight, domain, connectionId, canvasId, triggers, onEvidence, onTriggersHint, onDismissed }: {
  insight:       ExplorationInsight;
  domain:        string;
  connectionId:  string;
  canvasId?:     string;
  triggers:      ActionTrigger[];
  onEvidence:    (insight: ExplorationInsight) => void;
  onTriggersHint: () => void;
  onDismissed?:  (insightId: string) => void;
}) {
  const [monStatus, setMonStatus]   = useState<ActStatus>("idle");
  const [promStatus, setPromStatus] = useState<ActStatus>(insight.promoted_to_org ? "done" : "idle");
  const [shareOpen, setShareOpen]   = useState(false);
  const [shareMsg, setShareMsg]     = useState<string | null>(null);
  const [dismissed, setDismissed]   = useState(false);

  const handleDismiss = useCallback(async () => {
    // Capture a reason — it feeds the guard/eval backlog (finding_dismissals.jsonl),
    // turning a one-off correction into systematic signal.
    const reason = (window.prompt("Dismiss this finding. Why is it wrong or stale? (optional)") ?? "").trim();
    try {
      if (canvasId) await dismissCanvasInsight(canvasId, insight.id, reason);
      else await dismissConnectionInsight(connectionId, insight.id, reason);
      setDismissed(true);
      onDismissed?.(insight.id);
    } catch { /* non-fatal */ }
  }, [insight.id, canvasId, connectionId, onDismissed]);

  const handleMonitor = useCallback(async () => {
    if (!insight.sql) return;
    setMonStatus("busy");
    try {
      await createMonitor({
        conn_id: connectionId,
        name: `${domain}: ${insight.finding.slice(0, 48)}${insight.finding.length > 48 ? "…" : ""}`,
        custom_sql: insight.sql,
        alert_on: "anomaly",
        // Re-anchor the finding's frozen date window to the live data edge at run time,
        // so the monitor tracks a trailing window instead of going stale.
        reanchor_window: true,
      });
      setMonStatus("done");
    } catch { setMonStatus("error"); }
  }, [insight, domain, connectionId]);

  const handlePromote = useCallback(async () => {
    setPromStatus("busy");
    try {
      if (canvasId) await promoteCanvasInsight(canvasId, insight.id);
      else await promoteConnectionInsight(connectionId, insight.id);
      setPromStatus("done");
    } catch { setPromStatus("error"); }
  }, [insight.id, canvasId, connectionId]);

  const handleShareTo = useCallback(async (trigger: ActionTrigger) => {
    setShareOpen(false);
    setShareMsg("Sending…");
    try {
      const r = await sendFindingToTrigger(trigger.id, {
        text: insight.finding,
        metric_name: (insight.measures || []).join(", ") || undefined,
        headline: `${domain}${insight.angle ? " · " + insight.angle : ""}`,
        source_id: insight.id,
      });
      setShareMsg(r.status === "ok" ? `Sent to ${trigger.name} ✓` : `Failed: ${r.error || r.status}`);
    } catch { setShareMsg("Share failed"); }
    setTimeout(() => setShareMsg(null), 4000);
  }, [insight, domain]);

  const btnColor = "var(--t3)";
  // A "no data" finding isn't actionable — disable Monitor/Promote/Share (a monitor
  // built from its query would fire "No condition met" forever). Investigate + Evidence
  // stay enabled so the user can inspect why there's no data.
  const degenerate = isDegenerateFinding(insight);
  const noData = "This finding has no data — nothing to act on";

  if (dismissed) {
    return (
      <span style={{ fontSize: 11, color: "var(--t4)", fontStyle: "italic" as const }}>
        Dismissed ✓ — hidden from intelligence (kept for review)
      </span>
    );
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" as const, position: "relative" }}>
      <ActionButton label="Monitor"
        title={degenerate ? noData : (insight.sql ? "Create an anomaly monitor from this finding's query" : "No query available to monitor")}
        status={monStatus} color={btnColor} onClick={handleMonitor} disabled={!insight.sql || degenerate} />
      <ActionButton label="Promote"
        title={degenerate ? noData : (promStatus === "done" ? "Promoted to org intelligence" : "Promote this finding to org-wide intelligence")}
        status={promStatus} color={btnColor} onClick={handlePromote} disabled={degenerate} />
      <div style={{ position: "relative" }}>
        <ActionButton label="Share" title={degenerate ? noData : "Share this finding to a delivery channel"} status="idle" color={btnColor}
          disabled={degenerate}
          onClick={() => { if (triggers.length === 0) { onTriggersHint(); } else { setShareOpen(v => !v); } }} />
        {shareOpen && triggers.length > 0 && (
          <div style={{
            position: "absolute", top: "calc(100% + 4px)", left: 0, zIndex: 20,
            background: "var(--bg-1)", border: "1px solid var(--b2)", borderRadius: "var(--r2)",
            boxShadow: "0 6px 20px rgba(0,0,0,.18)", minWidth: 160, overflow: "hidden",
          }}>
            <div style={{ padding: "6px 10px", fontSize: 9, color: "var(--t4)", textTransform: "uppercase" as const, letterSpacing: ".06em", borderBottom: "1px solid var(--b1)" }}>
              Send to channel
            </div>
            {triggers.map(t => (
              <button key={t.id} onClick={() => handleShareTo(t)}
                style={{
                  display: "block", width: "100%", textAlign: "left" as const,
                  padding: "7px 10px", fontSize: 12, background: "transparent", border: "none",
                  color: t.enabled ? "var(--t2)" : "var(--t4)", cursor: "pointer",
                }}
                onMouseEnter={e => { e.currentTarget.style.background = "var(--bg-3)"; }}
                onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--t4)", marginRight: 6 }}>{t.type}</span>
                {t.name}{!t.enabled && " (disabled)"}
              </button>
            ))}
          </div>
        )}
      </div>
      <ActionButton label="Evidence" title="Show the query + provenance behind this finding" status="idle"
        color={btnColor} onClick={() => onEvidence(insight)} />
      <ActionButton label="Dismiss"
        title="Hide this finding if it's wrong or stale — captures a reason for the guard backlog; reversible"
        status="idle" color={btnColor} onClick={handleDismiss} />
      {degenerate && (
        <span title={noData} style={{
          fontSize: 9, fontWeight: 600, letterSpacing: ".05em", textTransform: "uppercase" as const,
          padding: "2px 6px", borderRadius: "var(--r1)", color: "var(--t4)",
          background: "var(--bg-3)", border: "1px solid var(--b1)",
        }}>no data</span>
      )}
      {shareMsg && (
        <span style={{ fontSize: 10, color: shareMsg.includes("✓") ? "var(--green4, #2e8c63)" : "var(--t4)" }}>{shareMsg}</span>
      )}
    </div>
  );
}

// ── Evidence drawer ──────────────────────────────────────────────────────────
// Drill-through: the exact SQL + confidence/novelty/freshness behind a finding.

export function EvidenceDrawer({ insight, domain, onClose, connectionId }: {
  insight: ExplorationInsight | null;
  domain:  string;
  onClose: () => void;
  connectionId?: string;
}) {
  // K3 Trust Receipt — provenance from the kernel ledger (job + lineage edges).
  const [receipt, setReceipt] = useState<InsightReceipt | null>(null);
  useEffect(() => {
    setReceipt(null);
    if (!insight || !connectionId) return;
    getInsightReceipt(connectionId, insight.id).then(r => setReceipt(r)).catch(() => {});
  }, [insight, connectionId]);
  if (!insight) return null;
  const fresh = insight.generated_at ? new Date(insight.generated_at).toLocaleString() : "—";
  const Stat = ({ label, value }: { label: string; value: string }) => (
    <div style={{ display: "flex", flexDirection: "column" as const, gap: 2 }}>
      <span style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase" as const, letterSpacing: ".06em" }}>{label}</span>
      <span style={{ fontSize: 13, color: "var(--t1)", fontWeight: 500 }}>{value}</span>
    </div>
  );
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 60, background: "rgba(0,0,0,.32)",
      display: "flex", justifyContent: "flex-end",
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: "min(520px, 92vw)", height: "100%", background: "var(--bg-1)",
        borderLeft: "1px solid var(--b2)", boxShadow: "-8px 0 28px rgba(0,0,0,.22)",
        display: "flex", flexDirection: "column" as const, overflow: "hidden",
      }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--b1)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="aug-label">Evidence</span>
            <DomainTag domain={domain} />
          </div>
          <button onClick={onClose} style={{ background: "transparent", border: "none", color: "var(--t3)", fontSize: 18, cursor: "pointer", lineHeight: 1 }}>×</button>
        </div>
        <div style={{ padding: "18px 20px", overflowY: "auto" as const, display: "flex", flexDirection: "column" as const, gap: 18 }}>
          <div style={{ fontSize: 14, color: "var(--t1)", lineHeight: 1.6, fontWeight: 500 }}>{insight.finding}</div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
            <Stat label="Confidence" value={`${Math.round((insight.confidence ?? 0) * 100)}%`} />
            <Stat label="Novelty" value={`${insight.novelty}/10`} />
            <Stat label="Freshness" value={fresh} />
          </div>

          {(insight.entities_involved?.length > 0 || insight.measures?.length > 0) && (
            <div style={{ display: "flex", flexDirection: "column" as const, gap: 10 }}>
              {insight.entities_involved?.length > 0 && (
                <div>
                  <div style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase" as const, letterSpacing: ".06em", marginBottom: 5 }}>Entities</div>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" as const }}>
                    {insight.entities_involved.map(e => (
                      <span key={e} style={{ padding: "2px 7px", borderRadius: "var(--r1)", fontSize: 10, background: "var(--bg-3)", border: "1px solid var(--b1)", color: "var(--t3)", fontFamily: "var(--font-mono)" }}>{e.replace(/_/g, " ")}</span>
                    ))}
                  </div>
                </div>
              )}
              {insight.measures?.length > 0 && (
                <div>
                  <div style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase" as const, letterSpacing: ".06em", marginBottom: 5 }}>Measures</div>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" as const }}>
                    {insight.measures.map(m => (
                      <span key={m} style={{ padding: "2px 7px", borderRadius: "var(--r1)", fontSize: 10, background: "var(--bg-3)", border: "1px solid var(--b1)", color: "var(--t3)", fontFamily: "var(--font-mono)" }}>{m}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div>
            <div style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase" as const, letterSpacing: ".06em", marginBottom: 6 }}>Source query — the data behind this claim</div>
            <pre style={{
              margin: 0, padding: "12px 14px", borderRadius: "var(--r2)",
              background: "var(--bg-2)", border: "1px solid var(--b1)",
              fontSize: 11.5, fontFamily: "var(--font-code)", color: "var(--t2)",
              whiteSpace: "pre-wrap" as const, wordBreak: "break-word" as const, lineHeight: 1.55,
            }}>{insight.sql || "— no query recorded —"}</pre>
          </div>

          {receipt && (
            <div>
              <div style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase" as const, letterSpacing: ".06em", marginBottom: 6 }}>
                Trust receipt — how this finding was produced
              </div>
              <div style={{ display: "flex", flexDirection: "column" as const, gap: 6, padding: "10px 12px", borderRadius: "var(--r2)", background: "var(--bg-2)", border: "1px solid var(--b1)" }}>
                {receipt.job && (
                  <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--t2)" }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: receipt.job.state === "SUCCEEDED" ? "var(--grn4)" : "var(--amb4)", flexShrink: 0 }} />
                    Computed by {receipt.job.kind} job <span style={{ color: "var(--t1)", fontWeight: 500 }}>{receipt.job.id}</span>
                    {receipt.job.finished_at ? ` · finished ${new Date(receipt.job.finished_at).toLocaleString()}` : ""}
                  </div>
                )}
                <div style={{ fontSize: 11, color: "var(--t2)" }}>
                  Version {receipt.artifact.version}{receipt.artifact.version > 1 ? " (earlier versions preserved)" : ""} · recorded {new Date(receipt.artifact.created_at).toLocaleString()}
                </div>
                {receipt.lineage.filter(l => l.relation === "input").length > 0 && (
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" as const, alignItems: "center" }}>
                    <span style={{ fontSize: 10, color: "var(--t3)" }}>Inputs:</span>
                    {receipt.lineage.filter(l => l.relation === "input").map(l => (
                      <span key={l.ref} style={{ padding: "1px 6px", borderRadius: "var(--r1)", fontSize: 10, background: "var(--bg-3)", border: "1px solid var(--b1)", color: "var(--t3)" }}>{l.ref.replace("table:", "")}</span>
                    ))}
                  </div>
                )}
                {receipt.lineage.filter(l => l.relation === "validated_by").map(l => (
                  <div key={l.ref} style={{ fontSize: 11, color: "var(--grn4)" }}>
                    ✓ {l.ref.replace("guard:", "").replace(/_/g, " ")}{l.detail ? ` — ${l.detail}` : ""}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function HeadlineCard({ signal, onInvestigate, actions }: {
  signal:       SynthesisSignal;
  onInvestigate: (q: string) => void;
  actions?:      ReactNode;
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
      {actions && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--b1)" }}>{actions}</div>
      )}
    </div>
  );
}

// ── Signal card ────────────────────────────────────────────────────────────────

function SignalCard({ signal, onInvestigate, actions }: {
  signal:       SynthesisSignal;
  onInvestigate: (q: string) => void;
  actions?:      ReactNode;
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
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" as const }}>
        <button
          onClick={() => onInvestigate(`Investigate: ${insight.finding}`)}
          style={{
            padding: "4px 10px", borderRadius: "var(--r2)", fontSize: 11, fontWeight: 500,
            background: "transparent", border: "1px solid var(--b2)",
            color: "var(--t3)", cursor: "pointer", transition: "all .12s",
          }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--blue3)"; e.currentTarget.style.color = "var(--blue4)"; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b2)"; e.currentTarget.style.color = "var(--t3)"; }}
        >
          Investigate →
        </button>
        {actions}
      </div>
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
            animation: "aug-spin var(--dur-breath) linear infinite",
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
              <span style={{ width: 12, height: 12, border: "2px solid var(--b2)", borderTop: "2px solid var(--blue4)", borderRadius: "50%", animation: "aug-spin var(--dur-breath) linear infinite", flexShrink: 0 }} />
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
          animation: "aug-spin var(--dur-breath) linear infinite",
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
  schema,
}: {
  connectionId: string;
  onInvestigate: (q: string) => void;
  /** When set, the briefing is scoped to this Canvas's curated tables (not the whole
   *  connection) — keeps Briefing consistent with the already-canvas-scoped Domains. */
  canvasId?: string;
  /** Shared schema scope from the workspace header (filters findings + narrative).
   *  Undefined = all schemas. N/A for a canvas (already table-scoped). */
  schema?: string;
}) {
  const [briefing, setBriefing]             = useState<BriefingData | null>(null);
  const [loading, setLoading]               = useState(false);
  const [error, setError]                   = useState<string | null>(null);
  const [narrative, setNarrative]           = useState<BriefingNarrativeResponse | null>(null);
  const [narrativeLoading, setNarrativeLoading] = useState(false);
  const [narrativeError, setNarrativeError] = useState<string | null>(null);
  // Scope the narrative auto-fetch by connection+schema so the AI Synthesis card
  // re-fetches when the shared schema selector changes (it previously short-circuited
  // on `narrative !== null`, leaving the synthesis stale while every other card updated).
  const fetchedScope = useRef<string | null>(null);
  const [explorerStatus, setExplorerStatus]   = useState<ExplorerStatus | null>(null);
  const [explorerBusy, setExplorerBusy]       = useState(false);
  const [triggers, setTriggers]               = useState<ActionTrigger[]>([]);
  const [evidenceInsight, setEvidenceInsight] = useState<ExplorationInsight | null>(null);
  const [evidenceDomain, setEvidenceDomain]   = useState<string>("");
  const [hint, setHint]                       = useState<string | null>(null);

  // Available delivery channels for the Share action (Action Hub triggers).
  useEffect(() => {
    let alive = true;
    getActionTriggers().then(t => { if (alive) setTriggers(t); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  const openEvidence = useCallback((ins: ExplorationInsight, domain: string) => {
    setEvidenceDomain(domain);
    setEvidenceInsight(ins);
  }, []);

  const showTriggersHint = useCallback(() => {
    setHint("No delivery channel yet — add a Slack/webhook trigger in Action Hub to share findings.");
    setTimeout(() => setHint(null), 5000);
  }, []);

  const load = useCallback(async () => {
    if (!canvasId && !connectionId) return;
    setLoading(true);
    setError(null);
    try {
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
  }, [connectionId, canvasId, schema]);

  const generateNarrative = useCallback(async (forceRefresh = false) => {
    if (!canvasId && !connectionId) return;
    setNarrativeLoading(true);
    setNarrativeError(null);
    try {
      const result = canvasId
        ? await generateCanvasBriefingNarrative(canvasId, forceRefresh)
        : await generateBriefingNarrative(connectionId, forceRefresh, schema);
      if (result.available) setNarrative(result);
      else setNarrativeError("No domain intelligence available — run an exploration first.");
    } catch (e) {
      setNarrativeError(e instanceof Error ? e.message : "Failed to generate narrative");
    } finally {
      setNarrativeLoading(false);
    }
  }, [connectionId, canvasId, schema]);

  // Shared explorer actions — used by both the control bar and the empty-state CTA.
  // In canvas mode (canvasId set) every action drives the *canvas* explorer, scoped to
  // the canvas's curated tables (#7) — not the underlying connection.
  const runExplorer = useCallback(async () => {
    if (!canvasId && !connectionId) return;
    setExplorerBusy(true);
    try {
      if (canvasId) await resumeCanvasExploration(canvasId);
      else          await startExplorer(connectionId);
    } catch {}
    setExplorerBusy(false);
  }, [connectionId, canvasId]);

  const runTriggerIntel = useCallback(async () => {
    if (!canvasId && !connectionId) return;
    setExplorerBusy(true);
    try {
      if (canvasId) await triggerCanvasDomainIntelligence(canvasId);
      else          await triggerDomainIntelligence(connectionId);
    } catch {}
    setExplorerBusy(false);
  }, [connectionId, canvasId]);

  // One-click refresh: clears stale findings and re-runs the full pipeline under the
  // current (corrected) explorer — drops "no data" / cross-dataset findings, re-anchors
  // the temporal window. The honest way to make a stale headline reliable + up to date.
  const runRefresh = useCallback(async () => {
    if (!canvasId && !connectionId) return;
    setExplorerBusy(true);
    try {
      if (canvasId) await restartCanvasExploration(canvasId);
      else          await restartExplorer(connectionId);
    } catch {}
    setExplorerBusy(false);
  }, [connectionId, canvasId]);

  const runStop = useCallback(async () => {
    if (!canvasId && !connectionId) return;
    setExplorerBusy(true);
    try {
      if (canvasId) await stopCanvasExploration(canvasId);
      else          await stopExplorer(connectionId);
    } catch {}
    setExplorerBusy(false);
  }, [connectionId, canvasId]);

  useEffect(() => { load(); }, [load]);

  // Auto-fetch the cached narrative on mount and whenever the scope (connection or
  // shared schema) changes. Guard on the scope we last fetched — not on `narrative
  // !== null` — so a schema switch actually re-fetches instead of keeping the old one.
  useEffect(() => {
    if (!canvasId && !connectionId) return;
    const scope = canvasId ?? `${connectionId}:${schema ?? ""}`;
    if (scope === fetchedScope.current) return;
    fetchedScope.current = scope;
    generateNarrative(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionId, canvasId, schema]);

  // Poll explorer status — canvas-scoped when a canvasId is set (#7), so the control
  // bar + empty-state reflect the *canvas* explorer's phase, not the connection's.
  useEffect(() => {
    const scopeId = canvasId || connectionId;
    if (!scopeId) return;
    let mounted = true;
    const poll = () => {
      const req = canvasId ? getCanvasExplorationStatus(canvasId) : getExplorerStatus(connectionId);
      req
        .then(s => { if (mounted) setExplorerStatus(s); })
        .catch(() => { if (mounted) setExplorerStatus(null); });
    };
    poll();
    // K2: phase-change events drive this; the interval is only a slow fallback
    // (was a 3s poll — the worst offender of the seven).
    const iv = setInterval(poll, 60_000);
    const unsub = subscribeKernelEvents(() => poll(), {
      kinds: ["exploration.", "job.state"],
      ...(canvasId ? { canvasId } : { connId: connectionId }),
    });
    return () => { mounted = false; clearInterval(iv); unsub(); };
  }, [connectionId, canvasId]);

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

      {/* Evidence drill-through drawer + transient hint toast (finding actions, #4) */}
      <EvidenceDrawer insight={evidenceInsight} domain={evidenceDomain} connectionId={connectionId} onClose={() => setEvidenceInsight(null)} />
      {hint && (
        <div style={{
          position: "fixed", bottom: 20, left: "50%", transform: "translateX(-50%)", zIndex: 70,
          padding: "10px 16px", borderRadius: "var(--r2)", fontSize: 12,
          background: "var(--bg-1)", border: "1px solid var(--b2)", color: "var(--t2)",
          boxShadow: "0 6px 20px rgba(0,0,0,.18)", maxWidth: 420,
        }}>{hint}</div>
      )}

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
              {explorerStatus?.phase === "complete" && (
                <button
                  disabled={explorerBusy}
                  onClick={runRefresh}
                  title="Clear stale findings and re-run intelligence from scratch (drops 'no data' findings, re-anchors the window)"
                  style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: "var(--bg-3)", color: "var(--t2)", border: "1px solid var(--b2)", cursor: explorerBusy ? "default" : "pointer", opacity: explorerBusy ? 0.6 : 1 }}
                >↻ Refresh</button>
              )}
            </>
          ) : (
            <>
              <button
                disabled={explorerBusy}
                onClick={runStop}
                style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: "var(--red2)", color: "var(--red5)", border: "1px solid var(--red3)", cursor: explorerBusy ? "default" : "pointer", opacity: explorerBusy ? 0.6 : 1 }}
              >Stop</button>
              <button
                disabled={explorerBusy}
                onClick={runRefresh}
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

      {/* ── Meta strip ── (schema selection now lives in the shared workspace header) */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
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

      {/* ── AI Synthesis ── always at the very top of the briefing */}
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
                animation: "aug-spin var(--dur-breath) linear infinite", flexShrink: 0,
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
            <NarrativeCard
              narrative={narrative}
              ctx={{
                insightById:    briefing.insightById,
                connectionId,
                canvasId,
                triggers,
                onEvidence:     openEvidence,
                onTriggersHint: showTriggersHint,
                onDismissed:    load,
                onInvestigate,
              }}
            />
          )}
        </div>
      )}

      {/* ── Industry key metrics ── the vertical's north-star KPIs, computed live */}
      <IndustryKpiStrip connectionId={connectionId} />

      {/* ── Live dashboard ── top-3 key-metric explainer charts + finding text cards (#3) */}
      <BriefingDashboard
        findings={[briefing.headline, ...briefing.signals].filter(Boolean) as { insight: ExplorationInsight; domain: string }[]}
        connectionId={connectionId}
        onInvestigate={onInvestigate}
        renderActions={(insight, domain) => (
          <FindingActions insight={insight} domain={domain}
            connectionId={connectionId} canvasId={canvasId} triggers={triggers}
            onEvidence={(ins) => openEvidence(ins, domain)} onTriggersHint={showTriggersHint}
            onDismissed={() => load()} />
        )}
      />

      {/* ── Domain coverage · patterns · org intelligence ── a full-width row below the
          mixed dashboard (the prior two-column main was emptied by the layout change, so
          these were orphaned in a right rail). */}
      {hasSidebar && (
        <div style={{ display: "flex", gap: 24, alignItems: "flex-start", flexWrap: "wrap" }}>

          {/* Domain coverage — findings per domain (where intelligence concentrates) */}
          <div style={{ flex: "1 1 280px", minWidth: 240 }}>
            <div className="aug-label" style={{ marginBottom: 10, display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
              <span>Domain Coverage</span>
              <span style={{ fontSize: 10, fontWeight: 400, color: "var(--t4)", fontFamily: "var(--font-mono)" }}>
                {briefing.domainCount} · {briefing.totalInsights} findings
              </span>
            </div>
            <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "14px 16px" }}>
              <DomainCoverageChart domains={briefing.domains} />
            </div>
          </div>

          {/* Top patterns */}
          {hasPatterns && (
            <div style={{ flex: "1 1 280px", minWidth: 240 }}>
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
            <div style={{ flex: "1 1 280px", minWidth: 240 }}>
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
    </>
  )}

      {/* Spinner keyframe */}
          </div>
  );
}
