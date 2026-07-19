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
import { formatTimestamp } from "@/lib/format";
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
  pinInsightToDashboard,
  type DomainInsights,
  type ExplorationInsight,
  type Pattern,
  type OrgInsight,
  type BriefingCitation,
  type BriefingNarrativeResponse,
  type HeldBackSignal,
  type ExplorerStatus,
  type ActionTrigger,
  getInsightReceipt,
  revalidateInsight,
  type InsightReceipt,
  groundBriefingNumber,
  insightKey,
  type FindingDossier,
  type RevalidateResult,
} from "@/lib/api";
import { subscribeKernelEvents } from "@/lib/events";
import { Spinner } from "@/components/ui/motion";
import { BriefingDashboard } from "@/components/brief/BriefingDashboard";
import { IndustryKpiStrip } from "@/components/brief/IndustryKpiStrip";
import { PinnedCards } from "@/components/brief/PinnedCards";
import { InlineInvestigationThread } from "@/components/brief/InlineInvestigationThread";
import { GroundedNumber, withGroundedNumbers } from "@/components/brief/GroundedNumber";
import { BriefAskBox } from "@/components/brief/BriefAskBox";
import { NewCardComposer } from "@/components/brief/NewCardComposer";
import { Button } from "@/components/ui/button";
import dynamic from "next/dynamic";

// React Flow measures the DOM — load the argument-graph lens client-only (the repo's pattern for
// heavy client libs, e.g. ECharts), so it never renders during SSR.
const ArgumentGraph = dynamic(() => import("@/components/brief/ArgumentGraph"), { ssr: false });

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
  connectionId,
  schema,
}: {
  text: string;
  citations: BriefingCitation[];
  onCitationClick: (citation: BriefingCitation, e: { clientX: number; clientY: number }) => void;
  /** Connection + schema scope so each magnitude number can be grounded ("show the receipt"). */
  connectionId: string;
  schema?: string;
}) {
  const citationMap = Object.fromEntries(citations.map(c => [c.ref, c]));
  // Every cited insight — a synthesized number may have come from any of them, so we
  // ground against all (primary = nearest) rather than only the nearest citation.
  const allInsightIds = Array.from(new Set(citations.map(c => c.insight_id).filter(Boolean)));
  // Split on [N] markers
  const parts = text.split(/(\[\d+\])/g);
  // The insight a number is grounded against = the NEAREST citation marker (claims usually
  // precede their [N], so prefer the following marker, falling back to the preceding one).
  const markerRefAt = (i: number): string | null => {
    for (let d = 0; d < parts.length; d++) {
      const after = parts[i + d]?.match(/^\[(\d+)\]$/);
      if (after) return after[1];
      const before = parts[i - d]?.match(/^\[(\d+)\]$/);
      if (before) return before[1];
    }
    return null;
  };

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
        const ref = markerRefAt(i);
        const insightId = ref ? citationMap[ref]?.insight_id : undefined;
        if (!insightId) return <span key={i}>{part}</span>;
        return (
          <span key={i}>
            {withGroundedNumbers(part, (tok, key) => (
              <GroundedNumber
                key={key}
                token={tok}
                resolve={async () => {
                  const r = await groundBriefingNumber(connectionId, insightId, { text: tok, schema, insightIds: allInsightIds });
                  if (r.error) return { sql: r.sql, grounded: null, matchedCell: null, error: r.error };
                  const rec = r.numerals[0];
                  return {
                    sql: r.sql,
                    grounded: rec ? (rec.enforce ? rec.grounded : null) : null,
                    matchedCell: rec?.matched_cell ?? null,
                  };
                }}
              />
            ), `p${i}`)}
          </span>
        );
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
  /** Shared schema scope — threaded into a citation's inline investigation. */
  schema?:        string;
  triggers:       ActionTrigger[];
  onEvidence:     (insight: ExplorationInsight, domain: string) => void;
  onTriggersHint: () => void;
  onDismissed:    () => void;
  onInvestigate:  (q: string, insightId?: string) => void;
}

/** The trust-gate audit trail: signals the brief deliberately withheld. An impossible
 *  number (turnover 3,600×) is SUPPRESSED; an anti-causal correlation (stockouts fall as
 *  lead time rises) is DEMOTED. Showing why we held them back is what earns trust. */
function HeldBackStrip({ items }: { items: HeldBackSignal[] }) {
  if (!items?.length) return null;
  return (
    <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--b1)" }}>
      <div style={{
        fontSize: 9, fontWeight: 700, textTransform: "uppercase" as const, letterSpacing: ".08em",
        color: "var(--t4)", marginBottom: 6,
      }}>
        {items.length} signal{items.length > 1 ? "s" : ""} held back by the trust gate
      </div>
      {items.map((h, i) => {
        const danger = h.severity === "implausible";
        return (
          <div key={i} style={{ fontSize: 11.5, color: "var(--t3)", lineHeight: 1.6, marginBottom: 3 }}>
            <span style={{ color: danger ? "var(--red4)" : "var(--amb4)", fontWeight: 600 }}>
              {danger ? "Implausible" : "Confound"}
            </span>
            <span style={{ color: "var(--t4)" }}> — </span>
            {h.reason}
          </div>
        );
      })}
    </div>
  );
}

function NarrativeCard({
  narrative,
  ctx,
  hideHeadline = false,
}: {
  narrative: BriefingNarrativeResponse;
  ctx: CitationActionContext;
  /** When the VerdictHero already leads with the conclusion, suppress this card's
   *  header so the headline_theme / "AI Synthesis" tag aren't shown twice. */
  hideHeadline?: boolean;
}) {
  const [active, setActive] = useState<{ citation: BriefingCitation; x: number; y: number } | null>(null);
  const onCitationClick = (citation: BriefingCitation, e: { clientX: number; clientY: number }) =>
    setActive({ citation, x: e.clientX, y: e.clientY });
  // Capability A — an inline investigation pulled from a citation, streamed below the prose.
  const [thread, setThread] = useState<{ question: string; seedSql: string | null; seedContext: string; key: string } | null>(null);

  return (
    <div style={{
      background: "linear-gradient(135deg, color-mix(in srgb, var(--blue4) 8%, var(--bg-2)), var(--bg-2))",
      border: "1px solid color-mix(in srgb, var(--blue4) 22%, var(--b1))",
      borderRadius: "var(--r3)", padding: "18px 22px",
    }}>
      {/* Header */}
      {!hideHeadline && (
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
      )}

      {/* Narrative prose with inline citations */}
      <div style={{
        fontSize: 13, color: "var(--t1)", lineHeight: 1.75, fontWeight: 400,
        letterSpacing: ".01em",
      }}>
        <NarrativeText
          text={narrative.narrative}
          citations={narrative.citations}
          onCitationClick={onCitationClick}
          connectionId={ctx.connectionId}
          schema={ctx.schema}
        />
      </div>

      {/* Citation legend removed — the inline [n] chips in the prose are the pointers;
          the repeated list below was redundant. */}

      {/* Trust-gate audit trail — the signals we suppressed/demoted, and why. */}
      <HeldBackStrip items={narrative.held_back ?? []} />

      {active && (
        <CitationActionsPopover
          citation={active.citation}
          x={active.x}
          y={active.y}
          ctx={ctx}
          onPull={(t) => { setThread(t); setActive(null); }}
          onClose={() => setActive(null)}
        />
      )}

      {/* Inline investigation pulled from a citation — seeded with the cited finding's SQL. */}
      {thread && (
        <InlineInvestigationThread
          key={thread.key}
          question={thread.question}
          opts={{
            connectionId: ctx.connectionId,
            schema: ctx.schema ?? null,
            canvasId: ctx.canvasId ?? null,
            seedSql: thread.seedSql,
            seedContext: thread.seedContext,
            insightId: thread.key,  // the citation's insight id — seeds the rich dossier when present
          }}
          onClose={() => setThread(null)}
          onOpenInAsk={ctx.onInvestigate}
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
  onPull,
  onClose,
}: {
  citation: BriefingCitation;
  x: number;
  y: number;
  ctx: CitationActionContext;
  onPull: (t: { question: string; seedSql: string | null; seedContext: string; key: string }) => void;
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
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => onPull({
              question: `Why is this happening? ${citation.finding}`,
              seedSql: insight.sql || null,
              seedContext: `SEED FINDING (the briefing claim being investigated): ${citation.finding}`,
              key: citation.insight_id,
            })}
            className="aug-btn"
            style={{
              alignSelf: "flex-start", fontSize: 11, color: "var(--bg-0)",
              background: "var(--blue5)", border: "1px solid var(--blue5)",
              borderRadius: "var(--r2)", padding: "4px 10px", cursor: "pointer", fontWeight: 600,
            }}
            title="Investigate this citation in place"
          >
            Pull the thread →
          </button>
          <button
            onClick={() => { ctx.onInvestigate(`Investigate: ${citation.finding}`, citation.insight_id); onClose(); }}
            className="aug-btn"
            style={{
              alignSelf: "flex-start", fontSize: 11, color: "var(--blue5)",
              background: "var(--bg-sel)", border: "1px solid var(--b1)",
              borderRadius: "var(--r2)", padding: "4px 10px", cursor: "pointer",
            }}
            title="Open in the Ask workspace"
          >
            Open in Ask ↗
          </button>
        </div>
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
      // Drop the impossible (e.g. inventory turnover 96,295×) from EVERY signal surface —
      // the headline, supporting signals AND the key-questions grid — using the same trust
      // gate as the AI synthesis. Confounds and everything else stay (ranked by impact below).
      if (isDegenerateFinding(ins) || ins.plausibility === "implausible") continue;
      allSignals.push({ insight: ins, domain });
      totalInsights++;
    }
  }

  // Rank by impact (the briefing-triage score stamped by /domains) — the same authority as
  // the AI synthesis and the dashboard cards — falling back to novelty when unannotated.
  const rankImpact = (i: ExplorationInsight) => i.impact ?? (i.novelty ?? 0);
  allSignals.sort((a, b) => rankImpact(b.insight) - rankImpact(a.insight));

  const headline = allSignals[0] ?? null;

  // Build supporting signals: breadth first (one per domain), then fill to 6.
  // Dedup by composite identity — bare ids collide across schemas in the aggregate.
  const seenIds    = new Set<string>(headline ? [insightKey(headline.insight)] : []);
  const seenDomains = new Set<string>();
  const signals: SynthesisSignal[] = [];

  // Pass 1 — breadth
  for (const s of allSignals) {
    if (signals.length >= 6) break;
    if (seenIds.has(insightKey(s.insight))) continue;
    if (seenDomains.has(s.domain)) continue;
    seenIds.add(insightKey(s.insight));
    seenDomains.add(s.domain);
    signals.push(s);
  }

  // Pass 2 — fill with highest-novelty remainder
  for (const s of allSignals) {
    if (signals.length >= 6) break;
    if (seenIds.has(insightKey(s.insight))) continue;
    seenIds.add(insightKey(s.insight));
    signals.push(s);
  }

  // Per-domain stats for the coverage chart (where the intelligence concentrates).
  const domains: DomainStat[] = Object.entries(domainData)
    .map(([name, data]) => {
      const ns = data.insights.filter(i => !isDegenerateFinding(i) && i.plausibility !== "implausible").map(i => i.novelty);
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

export function FindingActions({ insight, domain, connectionId, canvasId, schema, triggers, onEvidence, onTriggersHint, onDismissed, onPinned }: {
  insight:       ExplorationInsight;
  domain:        string;
  connectionId:  string;
  canvasId?:     string;
  schema?:       string;
  triggers:      ActionTrigger[];
  onEvidence:    (insight: ExplorationInsight) => void;
  onTriggersHint: () => void;
  onDismissed?:  (insightId: string) => void;
  onPinned?:     () => void;
}) {
  const [monStatus, setMonStatus]   = useState<ActStatus>("idle");
  const [promStatus, setPromStatus] = useState<ActStatus>(insight.promoted_to_org ? "done" : "idle");
  const [pinStatus, setPinStatus]   = useState<ActStatus>("idle");
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

  const handlePin = useCallback(async () => {
    if (!insight.sql) return;
    setPinStatus("busy");
    try {
      await pinInsightToDashboard(connectionId, insight.id, {
        scope: "connection", scopeRef: connectionId, schema,
      });
      setPinStatus("done");
      onPinned?.();
    } catch { setPinStatus("error"); }
  }, [insight.id, insight.sql, connectionId, schema, onPinned]);

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
      <ActionButton label="Pin"
        title={degenerate ? noData : (insight.sql ? "Pin this finding as a guard-checked card on your dashboard" : "No query available to pin")}
        status={pinStatus} color={btnColor} onClick={handlePin} disabled={!insight.sql || degenerate} />
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
        <span style={{ fontSize: 10, color: shareMsg.includes("✓") ? "var(--grn4)" : "var(--t4)" }}>{shareMsg}</span>
      )}
    </div>
  );
}

// ── Evidence drawer ──────────────────────────────────────────────────────────
// The Finding Dossier — the explorer's OWN derivation, captured at emit time and
// carried in the finding artifact's payload. Rendering it here means "how was this
// derived?" is answered by a read of work already done, not a second deep analysis.
// Exported so the Investigate (Tier-0) chat path renders the identical trace.
export function DossierTrace({ dossier }: { dossier: FindingDossier }) {
  const sc = dossier.structural_ctx || ({} as FindingDossier["structural_ctx"]);
  const joins = sc.joins || [];
  const dists = Object.entries(sc.distributions || {});
  const lifecycles = Object.entries(sc.lifecycles || {});
  const nulls = Object.entries(sc.null_meanings || {});
  const hasStructural = joins.length > 0 || dists.length > 0 || lifecycles.length > 0 || nulls.length > 0;
  const g = dossier.grounding;

  const Label = ({ children }: { children: React.ReactNode }) => (
    <div style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase" as const, letterSpacing: ".06em", marginBottom: 6 }}>{children}</div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column" as const, gap: 16 }}>
      {dossier.question && (
        <div>
          <Label>Question the explorer asked</Label>
          <div style={{ fontSize: 13, color: "var(--t2)", lineHeight: 1.55, fontStyle: "italic" as const }}>“{dossier.question}”</div>
        </div>
      )}

      {dossier.rationale && (
        <div>
          <Label>Why this holds — the mechanism</Label>
          <div style={{ fontSize: 13, color: "var(--t2)", lineHeight: 1.55 }}>{dossier.rationale}</div>
        </div>
      )}

      {dossier.narrative && (
        <div>
          <Label>Why it matters — in the broader picture</Label>
          <div style={{ fontSize: 13, color: "var(--t2)", lineHeight: 1.55 }}>{dossier.narrative}</div>
        </div>
      )}

      {dossier.result_cells && (
        <div>
          <Label>
            {g
              ? (g.checked === 0
                  ? "Result values — no magnitude claims to verify"
                  : g.grounded
                    ? `Grounded figures — ${g.checked} verified against the data`
                    : `Grounded figures — ${g.ungrounded.length} unverified`)
              : "Grounded figures"}
          </Label>
          <div style={{
            display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", borderRadius: "var(--r2)",
            background: "var(--bg-2)", border: "1px solid var(--b1)",
          }}>
            {g && (
              <span style={{ flexShrink: 0, fontSize: 12, color: g.grounded ? "var(--grn4)" : "var(--amb4)" }}>
                {g.grounded ? "✓" : "⚠"}
              </span>
            )}
            <span style={{ fontSize: 11.5, fontFamily: "var(--font-mono)", color: "var(--t3)", wordBreak: "break-word" as const, lineHeight: 1.5 }}>
              {dossier.result_cells}
            </span>
          </div>
        </div>
      )}

      {hasStructural && (
        <div>
          <Label>Structural ground — facts this claim stands on</Label>
          <div style={{ display: "flex", flexDirection: "column" as const, gap: 5, padding: "10px 12px", borderRadius: "var(--r2)", background: "var(--bg-2)", border: "1px solid var(--b1)" }}>
            {joins.map((j, i) => (
              <div key={`j${i}`} style={{ fontSize: 11, color: j.verified ? "var(--grn4)" : "var(--amb4)" }}>
                {j.verified ? "✓" : "⚠"} {j.from_table} → {j.to_table} ({j.cardinality}
                {j.verified ? ", 0 orphans" : `, ${j.orphan_count} orphans`})
              </div>
            ))}
            {dists.map(([k, d]) => (
              <div key={`d${k}`} style={{ fontSize: 11, color: "var(--t3)" }}>
                <span style={{ fontFamily: "var(--font-mono)" }}>{k.replace(":", ".")}</span> — {d.shape || "—"}
                {typeof d.p50 === "number" ? ` (median ${d.p50}` : ""}{typeof d.pct_zero === "number" ? `, ${Math.round(d.pct_zero * 100)}% zero)` : (typeof d.p50 === "number" ? ")" : "")}
              </div>
            ))}
            {lifecycles.map(([t, lm]) => (
              <div key={`l${t}`} style={{ fontSize: 11, color: "var(--t3)" }}>
                <span style={{ fontFamily: "var(--font-mono)" }}>{t}.{lm.status_column || "status"}</span>: {(lm.states || []).join(" → ")}
                {(lm.terminal_states || []).length > 0 ? ` · terminal: ${(lm.terminal_states || []).join(", ")}` : ""}
              </div>
            ))}
            {nulls.map(([k, nm]) => (
              <div key={`n${k}`} style={{ fontSize: 11, color: "var(--t3)" }}>
                <span style={{ fontFamily: "var(--font-mono)" }}>{k.replace(":", ".")}</span> — {nm.meaning || "—"}
                {nm.business_rule ? ` (${nm.business_rule})` : ""}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Living dossier: re-run the finding's SQL against current data and re-ground the
// claim. "as of" reflects the last check; the badge says whether it still holds.
function RevalidateRow({ dossier, connectionId, insightId }: {
  dossier: FindingDossier; connectionId?: string; insightId: string;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RevalidateResult | null>(null);
  const asOf = (result?.revalidated_at ?? (dossier as { revalidated_at?: string }).revalidated_at ?? dossier.generated_at);
  const asOfText = asOf ? formatTimestamp(asOf) : "—";
  const badge =
    result?.status === "confirmed" ? { c: "var(--grn4)", t: "Confirmed — still holds against current data" } :
    result?.status === "drifted"   ? { c: "var(--amb4)", t: `Drifted — ${(result.ungrounded ?? []).join(", ") || "a value moved"}` } :
    result?.status === "error"     ? { c: "var(--red4, #d66)", t: `Could not re-run — ${result.error ?? "query failed"}` } : null;

  return (
    <div style={{ display: "flex", flexDirection: "column" as const, gap: 8, paddingTop: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button
          disabled={busy || !connectionId}
          onClick={async () => {
            if (!connectionId) return;
            setBusy(true);
            try { setResult(await revalidateInsight(connectionId, insightId)); }
            finally { setBusy(false); }
          }}
          style={{ padding: "5px 11px", borderRadius: "var(--r1)", background: "var(--bg-3)", border: "1px solid var(--b2)", color: "var(--t1)", fontSize: 11.5, fontWeight: 500, cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1 }}
        >{busy ? "Re-validating…" : "Re-validate"}</button>
        <span style={{ fontSize: 10.5, color: "var(--t4)" }}>as of {asOfText}</span>
      </div>
      {badge && (
        <div style={{ fontSize: 11, color: badge.c, lineHeight: 1.5 }}>
          {result?.status === "confirmed" ? "✓ " : result?.status === "drifted" ? "⚠ " : "✕ "}{badge.t}
        </div>
      )}
    </div>
  );
}

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
  const fresh = insight.generated_at ? formatTimestamp(insight.generated_at) : "—";
  // The explorer's captured derivation, if this finding postdates dossier tracking.
  const dossier = receipt?.artifact?.payload?.dossier;
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

          {dossier && <DossierTrace dossier={dossier} />}
          {dossier && <RevalidateRow dossier={dossier} connectionId={connectionId} insightId={insight.id} />}

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
                    {receipt.job.finished_at ? ` · finished ${formatTimestamp(receipt.job.finished_at)}` : ""}
                  </div>
                )}
                <div style={{ fontSize: 11, color: "var(--t2)" }}>
                  Version {receipt.artifact.version}{receipt.artifact.version > 1 ? " (earlier versions preserved)" : ""} · recorded {formatTimestamp(receipt.artifact.created_at)}
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
  onInvestigate: (q: string, insightId?: string) => void;
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
          onClick={() => onInvestigate(`Investigate: ${insight.finding}`, insight.id)}
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

// ── Verdict hero ────────────────────────────────────────────────────────────────
/** Conclusion-first briefing lede: ONE bold verdict, a one-line proof, and the
 *  primary action — up front. The scope/provenance ("synthesized from N domains…")
 *  is demoted to a quiet footer so the lede isn't cluttered with background process.
 *  Falls back to the deterministic top finding when no AI narrative exists.
 *  Confidence % is deliberately NOT shown — it carried no call to action. */
// Small provenance chips for the verdict hero's meta strip (module-level so they aren't
// re-created on every VerdictHero render).
function HeroStatPill({ value, label }: { value: number; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: 5, fontSize: 11 }}>
      <span style={{ fontWeight: 650, color: "var(--t2)", fontVariantNumeric: "tabular-nums" as const }}>{value}</span>
      <span style={{ color: "var(--t4)" }}>{label}</span>
    </span>
  );
}
function HeroDivider() {
  return <span style={{ width: 1, height: 11, background: "var(--b2)" }} />;
}

function VerdictHero({
  narrative, headline, domainCount, totalInsights, synthesizedAt,
  onInvestigate, controls, actions, scope,
}: {
  narrative:     BriefingNarrativeResponse | null;
  headline:      SynthesisSignal | null;
  domainCount:   number;
  totalInsights: number;
  synthesizedAt: string;
  /** WP-5 — the schema this briefing is for; shown in the footer so two scopes can't be
   *  confused (the flip used to swap a scoped verdict for an unscoped one with no signal). */
  scope?:        string;
  onInvestigate: (q: string, insightId?: string) => void;
  controls?:     ReactNode;   // Generate / Reload buttons (top-right)
  actions?:      ReactNode;   // FindingActions menu for the headline finding
}) {
  const theme   = narrative?.headline_theme?.trim();
  const finding = headline?.insight.finding?.trim();
  const title   = theme || finding || "Intelligence briefing";
  // When the AI theme is the headline, the top finding becomes the supporting lead.
  const lead    = theme ? finding : undefined;
  const isVerdict = !!narrative;

  return (
    <div style={{
      position: "relative", overflow: "hidden",
      background: "linear-gradient(135deg, color-mix(in srgb, var(--blue4) 10%, var(--bg-2)) 0%, var(--bg-2) 58%)",
      border: "1px solid color-mix(in srgb, var(--blue4) 24%, var(--b1))",
      borderRadius: "var(--r3)", boxShadow: "var(--shadow-md)",
    }}>
      {/* left accent + a soft top-right glow for depth */}
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 3, background: "linear-gradient(var(--blue4), color-mix(in srgb, var(--blue4) 25%, transparent))" }} />
      <div style={{ position: "absolute", right: 0, top: 0, width: 380, height: 210, background: "radial-gradient(circle at 100% 0%, color-mix(in srgb, var(--blue4) 13%, transparent), transparent 62%)", pointerEvents: "none" }} />

      <div style={{ position: "relative", padding: "18px 26px 17px 30px" }}>
        {/* eyebrow (context) + controls */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 13, flexWrap: "wrap" as const }}>
          <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".13em", textTransform: "uppercase" as const, color: "var(--t4)" }}>
            Intelligence briefing{scope ? <span style={{ color: "var(--t3)" }}>{"  ·  "}{scope}</span> : null}
          </span>
          {controls && <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>{controls}</span>}
        </div>

        {/* verdict badge — a live pulse dot reads as a fresh, standing conclusion */}
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 11,
          padding: "3px 10px 3px 8px", borderRadius: "var(--r-pill)",
          background: "color-mix(in srgb, var(--blue4) 14%, transparent)",
          border: "1px solid color-mix(in srgb, var(--blue4) 32%, transparent)",
        }}>
          <span style={{ width: 6, height: 6, borderRadius: "var(--r-pill)", background: "var(--blue4)", boxShadow: "0 0 6px color-mix(in srgb, var(--blue4) 70%, transparent)" }} />
          <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".1em", textTransform: "uppercase" as const, color: "var(--blue4)" }}>
            {isVerdict ? "Verdict" : "Top finding"}
          </span>
        </div>

        {/* the ONE bold verdict — larger, tighter, premium */}
        <div style={{
          fontSize: 24, fontWeight: 680, lineHeight: 1.28, color: "var(--t1)",
          letterSpacing: "-.015em", maxWidth: 780, textWrap: "balance" as const,
          marginBottom: lead ? 10 : 0,
        }}>{title}</div>

        {/* one-line proof */}
        {lead && (
          <p style={{
            fontSize: 13.5, color: "var(--t2)", lineHeight: 1.6, maxWidth: 740, margin: 0,
            display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" as const, overflow: "hidden",
          }}>{lead}</p>
        )}

        {/* actions (left) + trust & provenance (right) on one confident strip */}
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 18, flexWrap: "wrap" as const }}>
          {(headline || actions) && (
            <div style={{ display: "flex", gap: 9, alignItems: "center", flexWrap: "wrap" as const }}>
              {headline && (
                <button
                  onClick={() => onInvestigate(`Investigate: ${headline.insight.finding}`, headline.insight.id)}
                  className="aug-btn aug-btn-primary"
                  style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "8px 16px", fontSize: 12.5, fontWeight: 600, borderRadius: "var(--r2)", cursor: "pointer" }}
                >Investigate →</button>
              )}
              {actions}
            </div>
          )}

          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" as const }}>
            {/* Aughor's differentiator, made explicit: every number is evidence-backed. */}
            <span title="Every number is grounded in the data and cleared the trust guards"
              style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10, fontWeight: 600, padding: "3px 8px", borderRadius: "var(--r-pill)", color: "var(--grn4)", background: "var(--grn1)", border: "1px solid var(--grn2)" }}>
              <span style={{ fontSize: 9 }}>✓</span> Grounded &amp; guarded
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
              <HeroStatPill value={domainCount} label={domainCount === 1 ? "domain" : "domains"} />
              <HeroDivider />
              <HeroStatPill value={totalInsights} label={totalInsights === 1 ? "finding" : "findings"} />
              <HeroDivider />
              <span style={{ fontSize: 11, color: "var(--t4)" }}>{timeAgo(synthesizedAt)}</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Supporting signals ──────────────────────────────────────────────────────────
/** A 3-up row of the strongest supporting findings under the verdict (v2 mockup's
 *  hypothesis-card row). Driven by real briefing signals — every card is a live
 *  finding tagged by novelty. Confidence % is intentionally omitted (no call to
 *  action); novelty + the Investigate affordance carry the card. */
function SupportingSignals({ signals, onInvestigate }: {
  signals:       SynthesisSignal[];
  onInvestigate: (q: string, insightId?: string) => void;
}) {
  const top = signals.slice(0, 3);
  if (top.length === 0) return null;
  return (
    <div>
      <div className="aug-label" style={{ marginBottom: 10 }}>Supporting signals</div>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${top.length}, 1fr)`, gap: 14 }}>
        {top.map(({ insight, domain }) => {
          const nColor    = noveltyColor(insight.novelty);
          return (
            <div key={insightKey(insight)} style={{
              background: "var(--bg-2)", border: "1px solid var(--b1)",
              borderLeft: `3px solid ${nColor}`, borderRadius: "var(--r3)",
              padding: "16px 18px", display: "flex", flexDirection: "column" as const, gap: 10,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <DomainTag domain={domain} />
                {insight.angle && <span style={{ fontSize: 10, color: "var(--t4)" }}>{insight.angle}</span>}
                <span style={{ marginLeft: "auto", fontSize: 9.5, fontWeight: 700, color: nColor, textTransform: "uppercase" as const, letterSpacing: ".06em" }}>
                  {noveltyLabel(insight.novelty)}
                </span>
              </div>
              <div style={{
                fontSize: 13, fontWeight: 500, color: "var(--t1)", lineHeight: 1.5,
                textWrap: "pretty" as const, display: "-webkit-box",
                WebkitLineClamp: 4, WebkitBoxOrient: "vertical" as const, overflow: "hidden",
              }}>{insight.finding}</div>
              <button
                onClick={() => onInvestigate(`Investigate: ${insight.finding}`, insight.id)}
                style={{ alignSelf: "flex-start", marginTop: "auto", fontSize: 11, color: "var(--blue4)", background: "none", border: "none", padding: 0, cursor: "pointer" }}
              >Investigate →</button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Signal card ────────────────────────────────────────────────────────────────

function SignalCard({ signal, onInvestigate, actions }: {
  signal:       SynthesisSignal;
  onInvestigate: (q: string, insightId?: string) => void;
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
          onClick={() => onInvestigate(`Investigate: ${insight.finding}`, insight.id)}
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
  onInvestigate: (q: string, insightId?: string) => void;
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
  synthesis:         "composing cross-finding insights",
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
  workspaceId,
  schemaReady = true,
}: {
  connectionId: string;
  onInvestigate: (q: string, insightId?: string) => void;
  /** When set, the briefing is scoped to this Canvas's curated tables (not the whole
   *  connection) — keeps Briefing consistent with the already-canvas-scoped Domains. */
  canvasId?: string;
  /** Shared schema scope from the workspace header (filters findings + narrative).
   *  Undefined = all schemas. N/A for a canvas (already table-scoped). */
  schema?: string;
  /** Active workspace — lets a workspace-scoped currency/industry override win in the
   *  backend briefing (override-wins over the app default). Undefined = app default. */
  workspaceId?: string;
  /** WP-5 — whether the parent's schema selector has settled. The narrative auto-fetch
   *  waits for this so it never fires an unscoped request before the schema resolves.
   *  Defaults true for callers without a schema selector (e.g. a canvas mount). */
  schemaReady?: boolean;
}) {
  const [briefing, setBriefing]             = useState<BriefingData | null>(null);
  const [pinnedRefresh, setPinnedRefresh]   = useState(0);
  // Argument-graph lens (Slice 3): swap the linear narrative body for the node+edge graph.
  const [lens, setLens]                     = useState<"linear" | "graph">("linear");
  const [loading, setLoading]               = useState(false);
  const [error, setError]                   = useState<string | null>(null);
  const [narrative, setNarrative]           = useState<BriefingNarrativeResponse | null>(null);
  const [narrativeLoading, setNarrativeLoading] = useState(false);
  const [narrativeError, setNarrativeError] = useState<string | null>(null);
  // Scope the narrative auto-fetch by connection+schema so the AI Synthesis card
  // re-fetches when the shared schema selector changes (it previously short-circuited
  // on `narrative !== null`, leaving the synthesis stale while every other card updated).
  const fetchedScope = useRef<string | null>(null);
  // WP-5 — monotonically increasing request id: only the LATEST narrative fetch may apply
  // its result. Kills the headline-flip when two briefings (e.g. an unscoped one that raced
  // ahead, or a StrictMode double-invoke) resolve out of order — the stale one is discarded.
  const reqSeq = useRef(0);
  const [explorerStatus, setExplorerStatus]   = useState<ExplorerStatus | null>(null);
  const [explorerBusy, setExplorerBusy]       = useState(false);
  const [explorerError, setExplorerError]     = useState<string | null>(null);
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
    const myReq = ++reqSeq.current;   // WP-5 — this call is now the latest
    setNarrativeLoading(true);
    setNarrativeError(null);
    try {
      const result = canvasId
        ? await generateCanvasBriefingNarrative(canvasId, forceRefresh, workspaceId)
        : await generateBriefingNarrative(connectionId, forceRefresh, schema, workspaceId);
      if (myReq !== reqSeq.current) return;   // superseded → don't paint a stale brief (the flip guard)
      if (result.available) setNarrative(result);
      else setNarrativeError("No domain intelligence available — run an exploration first.");
    } catch (e) {
      if (myReq === reqSeq.current) setNarrativeError(e instanceof Error ? e.message : "Failed to generate narrative");
    } finally {
      if (myReq === reqSeq.current) setNarrativeLoading(false);
    }
  }, [connectionId, canvasId, schema, workspaceId]);

  // Shared explorer actions — used by both the control bar and the empty-state CTA.
  // In canvas mode (canvasId set) every action drives the *canvas* explorer, scoped to
  // the canvas's curated tables (#7) — not the underlying connection.
  const runExplorer = useCallback(async () => {
    if (!canvasId && !connectionId) return;
    setExplorerBusy(true);
    setExplorerError(null);
    try {
      if (canvasId) await resumeCanvasExploration(canvasId);
      else          await startExplorer(connectionId, schema);
    } catch (e) { setExplorerError(e instanceof Error ? e.message : "Could not start the explorer"); }
    setExplorerBusy(false);
  }, [connectionId, canvasId, schema]);

  const runTriggerIntel = useCallback(async () => {
    if (!canvasId && !connectionId) return;
    setExplorerBusy(true);
    setExplorerError(null);
    try {
      if (canvasId) await triggerCanvasDomainIntelligence(canvasId);
      else          await triggerDomainIntelligence(connectionId);
    } catch (e) { setExplorerError(e instanceof Error ? e.message : "Could not trigger intelligence"); }
    setExplorerBusy(false);
  }, [connectionId, canvasId]);

  // One-click refresh: clears stale findings and re-runs the full pipeline under the
  // current (corrected) explorer — drops "no data" / cross-dataset findings, re-anchors
  // the temporal window. The honest way to make a stale headline reliable + up to date.
  const runRefresh = useCallback(async () => {
    if (!canvasId && !connectionId) return;
    setExplorerBusy(true);
    setExplorerError(null);
    try {
      if (canvasId) await restartCanvasExploration(canvasId);
      else          await restartExplorer(connectionId);
    } catch (e) { setExplorerError(e instanceof Error ? e.message : "Refresh failed"); }
    setExplorerBusy(false);
  }, [connectionId, canvasId]);

  const runStop = useCallback(async () => {
    if (!canvasId && !connectionId) return;
    setExplorerBusy(true);
    setExplorerError(null);
    try {
      if (canvasId) await stopCanvasExploration(canvasId);
      else          await stopExplorer(connectionId);
    } catch (e) { setExplorerError(e instanceof Error ? e.message : "Stop failed"); }
    setExplorerBusy(false);
  }, [connectionId, canvasId]);

  useEffect(() => { load(); }, [load]);

  // Auto-fetch the cached narrative on mount and whenever the scope (connection or
  // shared schema) changes. Guard on the scope we last fetched — not on `narrative
  // !== null` — so a schema switch actually re-fetches instead of keeping the old one.
  useEffect(() => {
    if (!canvasId && !connectionId) return;
    // WP-5 — wait for the shared schema selector to settle before the first connection-scoped
    // fetch, so we never issue an unscoped briefing request that then races the scoped one.
    if (!canvasId && !schemaReady) return;
    const scope = canvasId ?? `${connectionId}:${schema ?? ""}`;
    if (scope === fetchedScope.current) return;
    fetchedScope.current = scope;
    generateNarrative(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionId, canvasId, schema, schemaReady]);

  // Poll explorer status — canvas-scoped when a canvasId is set (#7), so the control
  // bar + empty-state reflect the *canvas* explorer's phase, not the connection's.
  useEffect(() => {
    const scopeId = canvasId || connectionId;
    if (!scopeId) return;
    let mounted = true;
    const poll = () => {
      const req = canvasId ? getCanvasExplorationStatus(canvasId) : getExplorerStatus(connectionId, schema);
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
  }, [connectionId, canvasId, schema]);

  // Auto-refresh the briefing the moment an exploration run reaches "complete" —
  // newly-synthesised domain intelligence would otherwise stay hidden until a manual Reload.
  const prevPhaseRef = useRef<string | null>(null);
  useEffect(() => {
    const phase = explorerStatus?.phase ?? null;
    if (prevPhaseRef.current && prevPhaseRef.current !== "complete" && phase === "complete") {
      load();
      fetchedScope.current = null; // WP-5 — clear the scope guard so the auto-fetch refires
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
        {explorerError && (
          <span style={{ fontSize: 11, color: "var(--red5, #f87171)" }} title={explorerError}>
            ✗ {explorerError.length > 60 ? explorerError.slice(0, 60) + "…" : explorerError}
          </span>
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

      {/* ── Verdict hero ── conclusion-first lede: the synthesized verdict + the top
          finding + proof stats + the primary action, ahead of the full prose. */}
      <VerdictHero
        narrative={hasNarrative ? narrative : null}
        headline={briefing.headline}
        domainCount={briefing.domainCount}
        totalInsights={briefing.totalInsights}
        synthesizedAt={briefing.synthesizedAt}
        scope={schema}
        onInvestigate={onInvestigate}
        controls={
          <>
            {narrative?.graph && narrative.graph.nodes.length > 1 && (
              <div style={{ display: "inline-flex", borderRadius: "var(--r2)", border: "1px solid var(--b1)", overflow: "hidden" }}>
                {(["linear", "graph"] as const).map(m => (
                  <Button key={m} variant="ghost" size="xs" onClick={() => setLens(m)}
                    title={m === "graph" ? "See the verdict, its drivers and their evidence as an argument graph" : "The linear brief"}
                    style={{
                      padding: "4px 10px", fontSize: 11, height: "auto", borderRadius: 0, cursor: "pointer",
                      background: lens === m ? "var(--bg-1)" : "transparent",
                      color: lens === m ? "var(--blue4)" : "var(--t3)",
                      fontWeight: lens === m ? 600 : 400,
                    }}>
                    {m === "linear" ? "Linear" : "Graph"}
                  </Button>
                ))}
              </div>
            )}
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
          </>
        }
        actions={briefing.headline && (
          <FindingActions
            insight={briefing.headline.insight} domain={briefing.headline.domain}
            connectionId={connectionId} canvasId={canvasId} schema={schema} triggers={triggers}
            onEvidence={(ins) => openEvidence(ins, briefing.headline!.domain)}
            onTriggersHint={showTriggersHint} onDismissed={() => load()}
            onPinned={() => setPinnedRefresh(n => n + 1)} />
        )}
      />

      {/* ── Living brief ── ask anything anchored to this briefing's context; answers
          stream inline as a stack of investigations (capability E). */}
      <BriefAskBox
        connectionId={connectionId}
        schema={schema}
        canvasId={canvasId}
        briefContext={[
          narrative?.headline_theme ? `BRIEFING THEME: ${narrative.headline_theme}` : "",
          briefing.headline ? `HEADLINE FINDING: ${briefing.headline.insight.finding}` : "",
          ...briefing.signals.slice(0, 3).map(s => `- ${s.insight.finding}`),
        ].filter(Boolean).join("\n")}
        onOpenInAsk={onInvestigate}
      />

      {lens === "graph" && narrative?.graph ? (
        /* ── Argument graph ── the verdict, its drivers, and their typed evidence edges,
           a lens over the same brief (Slice 3). Linear stays the default. */
        <ArgumentGraph
          graph={narrative.graph}
          connectionId={connectionId}
          schema={schema}
          onOpenFinding={(iid) => onInvestigate("Investigate this finding", iid)}
        />
      ) : (
      <>
      {/* ── Supporting signals ── 3-up confidence-meter cards of the strongest findings. */}
      <SupportingSignals signals={briefing.signals} onInvestigate={onInvestigate} />

      {/* ── Full synthesis ── the multi-paragraph narrative + interactive citations.
          The hero above already carries the conclusion, so this card hides its header. */}
      {(hasNarrative || narrativeLoading || narrativeError) && (
        <div>
          <div className="aug-label" style={{ marginBottom: 10 }}>Full synthesis</div>
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
              hideHeadline
              ctx={{
                insightById:    briefing.insightById,
                connectionId,
                canvasId,
                schema,
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
      </>
      )}

      {/* ── Your pinned cards ── the standing cockpit layer: user-authored, guard-checked
            KPI cards. Door 3 (inline authoring from a metric) sits above the pinned grid so
            the first card can be composed even when the cockpit is empty. */}
      <NewCardComposer connectionId={connectionId} schema={schema}
        onCreated={() => setPinnedRefresh(n => n + 1)} />
      <PinnedCards connectionId={connectionId} refreshKey={pinnedRefresh}
        onOpenSource={(iid) => onInvestigate("Investigate this finding", iid)}
        onEvidence={(iid) => { const sig = briefing.insightById.get(iid); if (sig) openEvidence(sig.insight, sig.domain); }} />

      {/* ── Industry key metrics ── the vertical's north-star KPIs, computed live;
            click a card to expand it into its trend chart (replaces the old chart grid). */}
      <IndustryKpiStrip connectionId={connectionId} schema={schema} />

      {lens === "linear" && (<>
      {/* ── Live dashboard ── finding text cards (#3); metric trends now expand from the KPI strip above */}
      <BriefingDashboard
        findings={[briefing.headline, ...briefing.signals].filter(Boolean) as { insight: ExplorationInsight; domain: string }[]}
        connectionId={connectionId}
        schema={schema}
        canvasId={canvasId}
        onInvestigate={onInvestigate}
        renderActions={(insight, domain) => (
          <FindingActions insight={insight} domain={domain}
            connectionId={connectionId} canvasId={canvasId} schema={schema} triggers={triggers}
            onEvidence={(ins) => openEvidence(ins, domain)} onTriggersHint={showTriggersHint}
            onDismissed={() => load()} onPinned={() => setPinnedRefresh(n => n + 1)} />
        )}
      />

      {/* ── Top patterns ── a full-width row below the dashboard. (Domain Coverage and
          Org Intelligence were removed by request — the dashboard's metric charts +
          finding cards carry the briefing.) */}
      {hasPatterns && (
        <div style={{ display: "flex", gap: 24, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 280px", minWidth: 240 }}>
            <div className="aug-label" style={{ marginBottom: 10 }}>Top Patterns</div>
            <div style={{ display: "flex", flexDirection: "column" as const, gap: 6 }}>
              {briefing.patterns.map(p => (
                <PatternRow key={p.id} pattern={p} onInvestigate={onInvestigate} />
              ))}
            </div>
          </div>
        </div>
      )}
      </>)}
    </>
  )}

      {/* Spinner keyframe */}
          </div>
  );
}
