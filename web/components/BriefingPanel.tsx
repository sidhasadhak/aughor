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

import { useEffect, useState, useCallback, useRef, useMemo, type ReactNode } from "react";
import { formatTimestamp, formatMetricValue } from "@/lib/format";
import {
  runDirectQuery,
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
import { IndustryKpiStrip } from "@/components/brief/IndustryKpiStrip";
import { StatTile } from "@/components/brief/StatTile";
import { extractKeyFigure } from "@/components/brief/keyFigure";
import { PinnedCards } from "@/components/brief/PinnedCards";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { toast } from "@/components/ui/toast";
import { useRegisterCommands, type Command } from "@/lib/commandRegistry";
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
  /** The full ranked, non-degenerate finding list (before the breadth-first dedup that
   *  caps `signals` at one-per-domain) — the scope chips filter by domain and so need the
   *  complete set, not the deduped six. */
  allSignals:    SynthesisSignal[];
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
        className="aug-fs-xs"
        style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 18, height: 18, borderRadius: "50%",
          fontWeight: 700, fontFamily: "var(--font-mono)",
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
          <div className="aug-label" style={{ marginBottom: 4 }}>
            {citation.domain}{citation.angle ? ` · ${citation.angle}` : ""}
          </div>
          <div className="aug-fs-xs" style={{ color: "var(--t2)", lineHeight: 1.5 }}>
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
      <div className="aug-label" style={{ marginBottom: 6 }}>
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
  collapsible = false,
}: {
  narrative: BriefingNarrativeResponse;
  ctx: CitationActionContext;
  /** When the VerdictHero already leads with the conclusion, suppress this card's
   *  header so the headline_theme / "AI Synthesis" tag aren't shown twice. */
  hideHeadline?: boolean;
  /** Direction B: render only the lede (clamped + bottom fade) with a "Read full
   *  synthesis" toggle, so the synthesis reads as the argument's close, not a second wall. */
  collapsible?: boolean;
}) {
  const [active, setActive] = useState<{ citation: BriefingCitation; x: number; y: number } | null>(null);
  const [expanded, setExpanded] = useState(false);
  const clamped = collapsible && !expanded;
  const onCitationClick = (citation: BriefingCitation, e: { clientX: number; clientY: number }) =>
    setActive({ citation, x: e.clientX, y: e.clientY });
  // Capability A — an inline investigation pulled from a citation, streamed below the prose.
  const [thread, setThread] = useState<{ question: string; seedSql: string | null; seedContext: string; key: string } | null>(null);

  return (
    // Flat panel in the shared card language (was a blue-gradient card). The section's .aug-label
    // header outside already frames it; the prose carries the analysis.
    <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "18px 22px" }}>
      {/* Header */}
      {!hideHeadline && (
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span className="aug-label">AI Synthesis</span>
        {narrative.headline_theme && (
          <span className="aug-fs-sm" style={{ fontWeight: 600, color: "var(--t1)" }}>
            {narrative.headline_theme}
          </span>
        )}
        {narrative.generated_at && (
          <span className="aug-fs-xs" style={{ color: "var(--t4)", marginLeft: "auto" }}>
            {timeAgo(narrative.generated_at)}
          </span>
        )}
      </div>
      )}

      {/* Narrative prose with inline citations. When collapsible, only the lede shows —
          clamped with a bottom fade to the card surface — until "Read full synthesis". */}
      <div style={{ position: "relative" }}>
        <div className="aug-fs-ui" style={{
          color: "var(--t1)", lineHeight: 1.7, fontWeight: 400, maxWidth: "72ch",
          ...(clamped ? { maxHeight: 150, overflow: "hidden" as const } : {}),
        }}>
          <NarrativeText
            text={narrative.narrative}
            citations={narrative.citations}
            onCitationClick={onCitationClick}
            connectionId={ctx.connectionId}
            schema={ctx.schema}
          />
        </div>
        {clamped && (
          <div aria-hidden style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 54, background: "linear-gradient(180deg, rgba(0,0,0,0), var(--bg-2))", pointerEvents: "none" }} />
        )}
      </div>
      {collapsible && (
        <div style={{ marginTop: 8 }}>
          <Button variant="ghost" size="xs" onClick={() => setExpanded(e => !e)}
            style={{ color: "var(--blue4)", fontSize: 12.5, fontWeight: 500, padding: "2px 8px" }}>
            {expanded ? "Show less ▴" : "Read full synthesis ▾"}
          </Button>
        </div>
      )}

      {/* Citation legend removed — the inline [n] chips in the prose are the pointers;
          the repeated list below was redundant. */}

      {/* Trust-gate audit trail — the signals we suppressed/demoted, and why. Hidden while
          the synthesis is collapsed so the lede stays a clean close. */}
      {(!collapsible || expanded) && <HeldBackStrip items={narrative.held_back ?? []} />}

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
        <div className="aug-label">
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
          <Button
            variant="ghost"
            onClick={() => onPull({
              question: `Why is this happening? ${citation.finding}`,
              seedSql: insight.sql || null,
              seedContext: `SEED FINDING (the briefing claim being investigated): ${citation.finding}`,
              key: citation.insight_id,
            })}
            style={{
              alignSelf: "flex-start", fontSize: 11, color: "var(--bg-0)",
              background: "var(--blue5)", border: "1px solid var(--blue5)",
              borderRadius: "var(--r2)", padding: "4px 10px", cursor: "pointer", fontWeight: 600,
            }}
            title="Investigate this citation in place"
          >
            Pull the thread →
          </Button>
          <Button
            variant="ghost"
            onClick={() => { ctx.onInvestigate(`Investigate: ${citation.finding}`, citation.insight_id); onClose(); }}
            style={{
              alignSelf: "flex-start", fontSize: 11, color: "var(--blue5)",
              background: "var(--bg-sel)", border: "1px solid var(--b1)",
              borderRadius: "var(--r2)", padding: "4px 10px", cursor: "pointer",
            }}
            title="Open in the Ask workspace"
          >
            Open in Ask ↗
          </Button>
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

/** Stable identity for a finding, robust to the meta-domains ("Key Questions",
 *  "Synthesis") that repeat the same finding and reuse non-unique ids: `insightKey`
 *  alone collides there (bare `pinned__N` / `synth__…` ids, no source_schema), so we
 *  fold the finding TEXT in. Used to dedup a scoped slice, count distinct per domain,
 *  and key the cards. */
const signalIdentity = (ins: ExplorationInsight): string => `${insightKey(ins)}|${ins.finding}`;

/** Drop repeated findings from a list (first occurrence wins), by `signalIdentity`. */
function dedupeSignals(list: SynthesisSignal[]): SynthesisSignal[] {
  const seen = new Set<string>();
  return list.filter(s => {
    const k = signalIdentity(s.insight);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

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
  // Count DISTINCT findings (by signalIdentity) so a meta-domain that repeats the same
  // finding many times isn't inflated — and its chip count matches the deduped scoped view.
  const domains: DomainStat[] = Object.entries(domainData)
    .map(([name, data]) => {
      const valid = data.insights.filter(i => !isDegenerateFinding(i) && i.plausibility !== "implausible");
      const seen = new Set<string>();
      const ns = valid.filter(i => { const k = signalIdentity(i); if (seen.has(k)) return false; seen.add(k); return true; }).map(i => i.novelty);
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
    allSignals,
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
      {showValue && <span className="aug-fs-xs" style={{ fontFamily: "var(--font-mono)", color, fontWeight: 600 }}>{novelty.toFixed(1)}</span>}
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
              <span className="aug-fs-xs" style={{ color: "var(--t4)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>{d.count}</span>
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
    <span className="aug-fs-xs" style={{
      display: "inline-flex", alignItems: "center",
      padding: "2px 8px", borderRadius: "var(--r2)",
      background:  `color-mix(in srgb, ${color} 12%, transparent)`,
      border:      `1px solid color-mix(in srgb, ${color} 28%, transparent)`,
      color, fontWeight: 500, textTransform: "capitalize" as const,
      letterSpacing: ".02em", flexShrink: 0,
    }}>
      {domain}
    </span>
  );
}

// ── Scope chips ─────────────────────────────────────────────────────────────────
/** A filter row that scopes the brief's narrative layer to one domain. "All" clears the
 *  scope; each domain chip carries its finding count + colour dot. The schema/connection
 *  scope is handled upstream by the workspace header — these chips scope *within* the
 *  brief, by domain, so the reader can focus the supporting signals + patterns on one area.
 *  Built on <Button> (the canonical system) styled as the app's FilterChip pill. */
function ScopeChip({ label, dot, count, active, onClick }: {
  label: string; dot?: string; count: number; active: boolean; onClick: () => void;
}) {
  return (
    <Button
      variant="ghost" size="xs" onClick={onClick} className="px-3"
      aria-pressed={active}
      style={{
        borderRadius: "var(--r-pill)", gap: 6, height: 26,
        background: active ? "color-mix(in srgb, var(--blue4) 12%, var(--bg-2))" : "var(--bg-2)",
        border: `1px solid ${active ? "var(--blue4)" : "var(--b1)"}`,
        color: active ? "var(--blue4)" : "var(--t2)",
        fontWeight: active ? 500 : 400,
      }}
    >
      {dot && <span style={{ width: 7, height: 7, borderRadius: "var(--r-pill)", background: dot, flexShrink: 0 }} />}
      {label}
      <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: active ? "var(--blue4)" : "var(--t4)", opacity: 0.85 }}>{count}</span>
    </Button>
  );
}

function ScopeChips({ domains, total, active, onChange }: {
  domains:  DomainStat[];
  total:    number;
  active:   string | null;
  onChange: (domain: string | null) => void;
}) {
  // Nothing to scope when the brief spans a single domain.
  if (domains.length < 2) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 8, alignItems: "center", marginTop: 6, marginBottom: 14 }}>
      <span className="aug-label" style={{ marginRight: 2 }}>Scope</span>
      <ScopeChip label="All" count={total} active={active == null} onClick={() => onChange(null)} />
      {domains.map(d => (
        <ScopeChip
          key={d.name}
          label={d.name.replace(/_/g, " ")}
          dot={domainColor(d.name)}
          count={d.count}
          active={active === d.name}
          onClick={() => onChange(active === d.name ? null : d.name)}
        />
      ))}
    </div>
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

export function FindingActions({ insight, domain, connectionId, canvasId, schema, triggers, onEvidence, onTriggersHint, onDismissed, onPinned, overflow }: {
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
  /** Hero de-clutter (Direction B): show Monitor + Pin, fold Promote/Share/Evidence/Dismiss
   *  into a ⋯ overflow menu. */
  overflow?:     boolean;
}) {
  const [monStatus, setMonStatus]   = useState<ActStatus>("idle");
  const [promStatus, setPromStatus] = useState<ActStatus>(insight.promoted_to_org ? "done" : "idle");
  const [pinStatus, setPinStatus]   = useState<ActStatus>("idle");
  const [shareOpen, setShareOpen]   = useState(false);
  const [shareMsg, setShareMsg]     = useState<string | null>(null);
  const [dismissed, setDismissed]   = useState(false);
  const [moreOpen, setMoreOpen]     = useState(false);   // ⋯ overflow menu (hero de-clutter)

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
      toast.success("Pinned to your cockpit");
    } catch {
      setPinStatus("error");
      toast.error("Couldn't pin finding", { description: "The finding's query didn't pass the trust guards." });
    }
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

  // Overflow layout — Monitor + Pin stay inline; the rest fold into a ⋯ menu.
  if (overflow) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6, position: "relative", flexWrap: "wrap" as const }}>
        <ActionButton label="Monitor"
          title={degenerate ? noData : (insight.sql ? "Create an anomaly monitor from this finding's query" : "No query available to monitor")}
          status={monStatus} color={btnColor} onClick={handleMonitor} disabled={!insight.sql || degenerate} />
        <ActionButton label="Pin"
          title={degenerate ? noData : (insight.sql ? "Pin this finding as a guard-checked card on your dashboard" : "No query available to pin")}
          status={pinStatus} color={btnColor} onClick={handlePin} disabled={!insight.sql || degenerate} />
        <div style={{ position: "relative" }}>
          <ActionButton label="⋯" title="More actions" status="idle" color={btnColor} onClick={() => setMoreOpen(v => !v)} />
          {moreOpen && (
            <div style={{ position: "absolute", top: "calc(100% + 4px)", right: 0, zIndex: 30, background: "var(--bg-1)", border: "1px solid var(--b2)", borderRadius: "var(--r2)", boxShadow: "0 6px 20px rgba(0,0,0,.28)", minWidth: 150, padding: 4, display: "flex", flexDirection: "column" as const, gap: 2 }}>
              <Button variant="ghost" size="xs" className="w-full justify-start h-auto" disabled={degenerate}
                onClick={() => { setMoreOpen(false); handlePromote(); }}
                style={{ padding: "7px 10px", fontSize: 12, color: degenerate ? "var(--t4)" : "var(--t2)" }}>
                {promStatus === "done" ? "Promoted ✓" : "Promote"}
              </Button>
              <div style={{ position: "relative" }}>
                <Button variant="ghost" size="xs" className="w-full justify-start h-auto" disabled={degenerate}
                  onClick={() => { if (triggers.length === 0) { setMoreOpen(false); onTriggersHint(); } else { setShareOpen(v => !v); } }}
                  style={{ padding: "7px 10px", fontSize: 12, color: degenerate ? "var(--t4)" : "var(--t2)" }}>
                  Share
                </Button>
                {shareOpen && triggers.length > 0 && (
                  <div style={{ position: "absolute", top: 0, right: "calc(100% + 4px)", zIndex: 40, background: "var(--bg-1)", border: "1px solid var(--b2)", borderRadius: "var(--r2)", boxShadow: "0 6px 20px rgba(0,0,0,.28)", minWidth: 160, overflow: "hidden" }}>
                    {triggers.map(t => (
                      <Button key={t.id} variant="ghost" size="xs" className="w-full justify-start h-auto"
                        onClick={() => { handleShareTo(t); setMoreOpen(false); }}
                        style={{ padding: "7px 10px", fontSize: 12, color: t.enabled ? "var(--t2)" : "var(--t4)" }}>
                        <span className="aug-fs-xs" style={{ fontFamily: "var(--font-mono)", color: "var(--t4)", marginRight: 6 }}>{t.type}</span>{t.name}{!t.enabled && " (disabled)"}
                      </Button>
                    ))}
                  </div>
                )}
              </div>
              <Button variant="ghost" size="xs" className="w-full justify-start h-auto"
                onClick={() => { setMoreOpen(false); onEvidence(insight); }}
                style={{ padding: "7px 10px", fontSize: 12, color: "var(--t2)" }}>
                Evidence
              </Button>
              <Button variant="ghost" size="xs" className="w-full justify-start h-auto"
                onClick={() => { setMoreOpen(false); handleDismiss(); }}
                style={{ padding: "7px 10px", fontSize: 12, color: "var(--t2)" }}>
                Dismiss
              </Button>
            </div>
          )}
        </div>
        {degenerate && (
          <span title={noData} className="aug-label" style={{ padding: "2px 6px", borderRadius: "var(--r1)", color: "var(--t4)", background: "var(--bg-3)", border: "1px solid var(--b1)" }}>no data</span>
        )}
        {shareMsg && (
          <span className="aug-fs-xs" style={{ color: shareMsg.includes("✓") ? "var(--grn4)" : "var(--t4)" }}>{shareMsg}</span>
        )}
      </div>
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
            <div className="aug-label" style={{ padding: "6px 10px", borderBottom: "1px solid var(--b1)" }}>
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
                <span className="aug-fs-xs" style={{ fontFamily: "var(--font-mono)", color: "var(--t4)", marginRight: 6 }}>{t.type}</span>
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
        <span title={noData} className="aug-label" style={{
          padding: "2px 6px", borderRadius: "var(--r1)", color: "var(--t4)",
          background: "var(--bg-3)", border: "1px solid var(--b1)",
        }}>no data</span>
      )}
      {shareMsg && (
        <span className="aug-fs-xs" style={{ color: shareMsg.includes("✓") ? "var(--grn4)" : "var(--t4)" }}>{shareMsg}</span>
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
    <div className="aug-label" style={{ marginBottom: 6 }}>{children}</div>
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
        <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>as of {asOfText}</span>
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
      <span className="aug-label">{label}</span>
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
                  <div className="aug-label" style={{ marginBottom: 5 }}>Entities</div>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" as const }}>
                    {insight.entities_involved.map(e => (
                      <span key={e} className="aug-fs-xs" style={{ padding: "2px 7px", borderRadius: "var(--r1)", background: "var(--bg-3)", border: "1px solid var(--b1)", color: "var(--t3)", fontFamily: "var(--font-mono)" }}>{e.replace(/_/g, " ")}</span>
                    ))}
                  </div>
                </div>
              )}
              {insight.measures?.length > 0 && (
                <div>
                  <div className="aug-label" style={{ marginBottom: 5 }}>Measures</div>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" as const }}>
                    {insight.measures.map(m => (
                      <span key={m} className="aug-fs-xs" style={{ padding: "2px 7px", borderRadius: "var(--r1)", background: "var(--bg-3)", border: "1px solid var(--b1)", color: "var(--t3)", fontFamily: "var(--font-mono)" }}>{m}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {dossier && <DossierTrace dossier={dossier} />}
          {dossier && <RevalidateRow dossier={dossier} connectionId={connectionId} insightId={insight.id} />}

          <div>
            <div className="aug-label" style={{ marginBottom: 6 }}>Source query — the data behind this claim</div>
            <pre style={{
              margin: 0, padding: "12px 14px", borderRadius: "var(--r2)",
              background: "var(--bg-2)", border: "1px solid var(--b1)",
              fontSize: 11.5, fontFamily: "var(--font-code)", color: "var(--t2)",
              whiteSpace: "pre-wrap" as const, wordBreak: "break-word" as const, lineHeight: 1.55,
            }}>{insight.sql || "— no query recorded —"}</pre>
          </div>

          {receipt && (
            <div>
              <div className="aug-label" style={{ marginBottom: 6 }}>
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
                    <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>Inputs:</span>
                    {receipt.lineage.filter(l => l.relation === "input").map(l => (
                      <span key={l.ref} className="aug-fs-xs" style={{ padding: "1px 6px", borderRadius: "var(--r1)", background: "var(--bg-3)", border: "1px solid var(--b1)", color: "var(--t3)" }}>{l.ref.replace("table:", "")}</span>
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

  return (
    // Flat card — the novelty is carried by the label + meter, not a colour-coded border.
    <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "20px 24px" }}>
      {/* Badge row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" as const }}>
        <span className="aug-label">{noveltyLabel(insight.novelty)}</span>
        <DomainTag domain={domain} />
        {insight.angle && (
          <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>{insight.angle}</span>
        )}
        <span style={{ marginLeft: "auto" }}><NoveltyMeter novelty={insight.novelty} width={64} /></span>
      </div>

      {/* Finding */}
      <div className="aug-fs-ui" style={{ fontWeight: 500, color: "var(--t1)", lineHeight: 1.65, marginBottom: 16 }}>
        {insight.finding}
      </div>

      {/* Footer */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" as const }}>
        {insight.entities_involved.length > 0 && (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" as const }}>
            {insight.entities_involved.slice(0, 4).map(e => (
              <span key={e} className="aug-fs-xs" style={{
                padding: "1px 6px", borderRadius: "var(--r1)",
                background: "var(--bg-3)", border: "1px solid var(--b1)",
                color: "var(--t3)", fontFamily: "var(--font-mono)",
              }}>{e.replace(/_/g, " ")}</span>
            ))}
          </div>
        )}
        <Button
          variant="minimal" size="sm"
          onClick={() => onInvestigate(`Investigate: ${insight.finding}`, insight.id)}
          style={{ marginLeft: "auto" }}
        >
          Investigate →
        </Button>
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
    <span className="aug-fs-xs" style={{ display: "inline-flex", alignItems: "baseline", gap: 5 }}>
      <span style={{ fontWeight: 600, color: "var(--t2)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" as const }}>{value}</span>
      <span style={{ color: "var(--t4)" }}>{label}</span>
    </span>
  );
}
function HeroDivider() {
  return <span style={{ width: 1, height: 11, background: "var(--b2)" }} />;
}

/** One "Numbers that moved" tile — a key figure extracted from a finding this cycle,
 *  carrying the identity to deep-link back to its ledger row. */
interface DigestTile {
  ident:      string;   // signalIdentity — the ledger row to scroll/expand
  insightId:  string;   // the finding id — used to pin from the cockpit empty state
  value:      string;
  secondary?: string;
  label:      string;   // the finding statement (clamped to 2 lines in the tile)
  sublabel?:  string;   // a short descriptor (for the cockpit's suggested-pin chips)
  domain:     string;
  accent:     string;   // domain colour (honest — not a fabricated favorability judgement)
}

function VerdictHero({
  narrative, headline, domainCount, totalInsights, synthesizedAt,
  onInvestigate, controls, actions, scope, digest, onFinding,
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
  /** "Numbers that moved" digest — figures extracted from this cycle's findings; each tile
   *  deep-links to its finding. Empty/absent → the row is omitted. */
  digest?:       DigestTile[];
  onFinding?:    (ident: string) => void;
}) {
  const theme   = narrative?.headline_theme?.trim();
  const finding = headline?.insight.finding?.trim();
  const title   = theme || finding || "Intelligence briefing";
  // When the AI theme is the headline, the top finding becomes the supporting lead.
  const lead    = theme ? finding : undefined;
  const isVerdict = !!narrative;

  return (
    // Flat panel in the shared card language (was a gradient + glow + shadow hero). Prominence now
    // comes from position, the display-size verdict, and the primary action — not chrome.
    <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)" }}>
      <div style={{ padding: "18px 26px 17px" }}>
        {/* eyebrow (context) + controls */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 13, flexWrap: "wrap" as const }}>
          <span className="aug-label">
            Intelligence briefing{scope ? <span style={{ color: "var(--t4)" }}>{"  ·  "}{scope}</span> : null}
          </span>
          {controls && <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>{controls}</span>}
        </div>

        {/* verdict badge — dot + label (dots, not boxes, like the report surfaces) */}
        <div style={{ display: "inline-flex", alignItems: "center", gap: 7, marginBottom: 11 }}>
          <span style={{ width: 6, height: 6, borderRadius: "var(--r-pill)", background: "var(--blue4)" }} />
          <span className="aug-label" style={{ color: "var(--blue4)" }}>{isVerdict ? "Verdict" : "Top finding"}</span>
        </div>

        {/* the ONE verdict — 24px (the digest row below now shares the hero's weight) */}
        <div style={{
          fontSize: 24, fontWeight: 600, lineHeight: 1.2, color: "var(--t1)",
          letterSpacing: "-.02em", maxWidth: "32ch", textWrap: "balance" as const,
          marginBottom: lead ? 10 : 0,
        }}>{title}</div>

        {/* one-line proof */}
        {lead && (
          <p className="aug-fs-ui" style={{
            color: "var(--t2)", lineHeight: 1.6, maxWidth: 740, margin: 0,
            display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" as const, overflow: "hidden",
          }}>{lead}</p>
        )}

        {/* actions (left) + trust & provenance (right) on one confident strip */}
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 18, flexWrap: "wrap" as const }}>
          {(headline || actions) && (
            <div style={{ display: "flex", gap: 9, alignItems: "center", flexWrap: "wrap" as const }}>
              {headline && (
                <Button
                  variant="default" size="sm"
                  onClick={() => onInvestigate(`Investigate: ${headline.insight.finding}`, headline.insight.id)}
                >Investigate →</Button>
              )}
              {actions}
            </div>
          )}

          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" as const }}>
            {/* Aughor's differentiator, made explicit: every number is evidence-backed. */}
            <span title="Every number is grounded in the data and cleared the trust guards"
              className="aug-tag aug-tag-green">
              ✓ Grounded &amp; guarded
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
              <HeroStatPill value={domainCount} label={domainCount === 1 ? "domain" : "domains"} />
              <HeroDivider />
              <HeroStatPill value={totalInsights} label={totalInsights === 1 ? "finding" : "findings"} />
              <HeroDivider />
              <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>{timeAgo(synthesizedAt)}</span>
            </span>
          </div>
        </div>

        {/* "Numbers that moved" — a 4-up digest of key figures pulled from this cycle's
            findings; each tile is one click from its ledger row (the "every number one click
            from its why" guarantee). Not north-star KPIs — cycle-specific movers. */}
        {digest && digest.length > 0 && (
          <div style={{ marginTop: 18 }}>
            <div className="aug-label" style={{ marginBottom: 8, color: "var(--t3)" }}>Numbers that moved</div>
            <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(4, digest.length)}, minmax(0, 1fr))`, gap: 12 }}>
              {digest.slice(0, 4).map(d => (
                <StatTile
                  key={d.ident}
                  accent={d.accent}
                  accentBar
                  labelLines={2}
                  label={d.label}
                  value={<span>{d.value}{d.secondary && <span style={{ color: "var(--t4)", fontSize: 15 }}>{d.secondary}</span>}</span>}
                  footer={
                    <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontFamily: "var(--font-mono)", color: "var(--t3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.domain}</span>
                      <a onClick={e => { e.stopPropagation(); onFinding?.(d.ident); }}
                        style={{ marginLeft: "auto", cursor: "pointer", color: "var(--blue4)", whiteSpace: "nowrap" }}>finding →</a>
                    </div>
                  }
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Findings — the bulletin ledger (Direction B) ────────────────────────────────
/** The narrative layer's reading surface: every finding is ONE scannable row — novelty
 *  + domain, the statement with its figures inline, and the extracted key figure right-
 *  aligned. The eye scans a single left edge instead of a card mosaic; a row's grounded
 *  chart is fetched lazily only when it's expanded, so collapsed rows cost zero chart
 *  requests. Replaces the uniform exhibit-card grid. */
const LEDGER_DEFAULT = 7;     // first paint: seven rows ≈ the height of one row of old cards
const LEDGER_STEP    = 12;    // each "Show next" click
const LEDGER_CHART_H = 190;   // expanded-row chart height
const LEDGER_COLS    = "128px 1fr 150px 20px";   // [domain | statement | key figure | chevron]

/** Wrap the numeric tokens in a finding statement in bold mono, so figures read as figures
 *  without the backend having to mark them up. Pure formatting of already-grounded text. */
function renderFigures(text: string): ReactNode[] {
  const re = /[$€£¥₹]?\d[\d,]*(?:\.\d+)?\s?[%×BMK]?/g;
  const out: ReactNode[] = [];
  let last = 0, m: RegExpExecArray | null, k = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(<span key={k++}>{text.slice(last, m.index)}</span>);
    out.push(<b key={k++} style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--t1)" }}>{m[0]}</b>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(<span key={k++}>{text.slice(last)}</span>);
  return out;
}

function LedgerRow({ signal, connectionId, expanded, onToggle, onInvestigate, onEvidence, rowRef }: {
  signal:        SynthesisSignal;
  connectionId:  string;
  expanded:      boolean;
  onToggle:      () => void;
  onInvestigate: (q: string, insightId?: string) => void;
  onEvidence:    (ins: ExplorationInsight, domain: string) => void;
  rowRef:        (el: HTMLDivElement | null) => void;
}) {
  const { insight, domain } = signal;
  const fig = extractKeyFigure(insight.finding);
  const hot = insight.novelty >= 5;      // Notable/High → amber novelty dot; else quiet --b3
  const [hover, setHover] = useState(false);

  // The finding's own grounded result — fetched LAZILY on first expand (server-cached, same
  // query the explorer ran), then kept. Collapsed rows never fetch. A single scalar shows as
  // the big figure; anything richer renders through the chart card; error/empty → text only.
  const [run, setRun]     = useState<{ columns: string[]; rows: unknown[][] } | null>(null);
  const [phase, setPhase] = useState<"idle" | "loading" | "chart" | "text">("idle");
  // Lazy chart fetch on first expand. `phase` is deliberately NOT a dependency: including it
  // makes the effect re-run the instant it flips to "loading", and that re-run's cleanup sets
  // alive=false on the fetch just kicked off — so it never reaches "chart" and the row sticks on
  // the shimmer. Guard on `run` so a collapse→re-expand doesn't refetch; StrictMode's remount
  // simply starts a fresh (server-cached) call.
  useEffect(() => {
    if (!expanded || run) return;
    const sql = (insight.sql || "").trim();
    if (!sql || !connectionId) { setPhase("text"); return; }
    setPhase("loading");
    let alive = true;
    runDirectQuery(connectionId, sql, 200, { useCache: true })
      .then(r => {
        if (!alive) return;
        if (r.error || !r.columns?.length || !r.rows?.length) { setPhase("text"); return; }
        setRun({ columns: r.columns, rows: r.rows as unknown[][] });
        setPhase("chart");
      })
      .catch(() => { if (alive) setPhase("text"); });
    return () => { alive = false; };
  }, [expanded, run, connectionId, insight.sql]);

  const scalar = run && run.rows.length === 1 && run.columns.length === 1 && !isNaN(Number(run.rows[0][0]))
    ? Number(run.rows[0][0]) : null;

  return (
    <div ref={rowRef} data-finding={signalIdentity(insight)}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ borderBottom: "1px solid var(--b0)", background: expanded || hover ? "var(--bg-3)" : "transparent", transition: "background var(--dur-fast)" }}>
      <div role="button" tabIndex={0} onClick={onToggle}
        onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}
        style={{ display: "grid", gridTemplateColumns: LEDGER_COLS, gap: 14, alignItems: "center", padding: "13px 18px", cursor: "pointer" }}>
        {/* domain — novelty dot + domain-colour dot + name */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span title={`Novelty ${insight.novelty.toFixed(1)} / 10`} style={{ width: 6, height: 6, borderRadius: "var(--r-pill)", background: hot ? "var(--amb4)" : "var(--b3)", flex: "none" }} />
          <span style={{ width: 6, height: 6, borderRadius: "var(--r-pill)", background: domainColor(domain), flex: "none" }} />
          <span style={{ fontSize: 12, fontWeight: 500, color: "var(--t2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{domain}</span>
        </div>
        {/* statement — figures bold mono inline; trust caveat inline amber */}
        <div style={{ fontSize: 13, lineHeight: 1.45, color: "var(--t1)", minWidth: 0,
          display: "-webkit-box", WebkitLineClamp: expanded ? 99 : 2, WebkitBoxOrient: "vertical" as const, overflow: "hidden" }}>
          {renderFigures(insight.finding)}
          {insight.plausibility && (
            <span className="aug-fs-xs" style={{ marginLeft: 6, color: "var(--amb4)", whiteSpace: "nowrap" }}>⚠ {insight.plausibility}</span>
          )}
        </div>
        {/* key figure — extracted scalar, right-aligned, over a mono sub-label */}
        <div style={{ textAlign: "right", minWidth: 0 }}>
          {fig && (<>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 15, fontWeight: 600, color: "var(--t1)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {fig.value}{fig.secondary && <span style={{ color: "var(--t4)", fontSize: 12 }}>{fig.secondary}</span>}
            </div>
            {fig.sublabel && <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--t4)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{fig.sublabel}</div>}
          </>)}
        </div>
        {/* chevron */}
        <span aria-hidden style={{ color: "var(--t4)", fontSize: 12, textAlign: "center" }}>{expanded ? "▴" : "▾"}</span>
      </div>

      {expanded && (
        <div style={{ padding: "0 18px 16px" }}>
          <div style={{ background: "var(--bg-1)", border: "1px solid var(--b0)", borderRadius: "var(--r2)", padding: 12 }}>
            {phase === "loading" && <Shimmer h={LEDGER_CHART_H} r="var(--r2)" />}
            {phase === "text" && (
              <div className="aug-fs-xs" style={{ color: "var(--t4)", padding: "8px 2px" }}>
                No chartable result for this finding — the statement above is the finding.
              </div>
            )}
            {phase === "chart" && run && (scalar != null ? (
              <div className="aug-fs-display" style={{ color: "var(--t1)", fontWeight: 700, fontFamily: "var(--font-mono)", lineHeight: 1, padding: "18px 2px" }}>
                {formatMetricValue(scalar)}
              </div>
            ) : (
              <div style={{ minHeight: LEDGER_CHART_H }}>
                <ResultChartCard columns={run.columns} rows={run.rows} fillHeight={LEDGER_CHART_H} />
              </div>
            ))}
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 10 }}>
              <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>{insight.angle || "The finding's grounded query"}</span>
              <span style={{ marginLeft: "auto", display: "flex", gap: 12 }}>
                <Button variant="ghost" size="xs" onClick={() => onEvidence(insight, domain)}
                  title="See the query + provenance behind this finding"
                  style={{ fontSize: 11, color: "var(--vio4)", padding: "2px 6px" }}>Evidence</Button>
                <Button variant="ghost" size="xs" onClick={() => onInvestigate(`Investigate: ${insight.finding}`, insight.id)}
                  style={{ fontSize: 11, fontWeight: 600, color: "var(--blue4)", padding: "2px 6px" }}>Investigate →</Button>
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function FindingsLedger({ signals, connectionId, onInvestigate, onEvidence, focus, onFocusHandled, scrollRef }: {
  signals:        SynthesisSignal[];
  connectionId:   string;
  onInvestigate:  (q: string, insightId?: string) => void;
  onEvidence:     (ins: ExplorationInsight, domain: string) => void;
  /** A deep-link request (from a digest tile / jump menu): expand + scroll to this row. */
  focus?:         { ident: string; expand: boolean } | null;
  onFocusHandled?: () => void;
  /** The Briefing's own scroll container — so a deep-link scrolls the panel, not the app shell. */
  scrollRef?:     { current: HTMLDivElement | null };
}) {
  const [shown, setShown]           = useState(LEDGER_DEFAULT);
  const [expandedId, setExpandedId] = useState<string | null>(null);   // one row open at a time
  const [jumpOpen, setJumpOpen]     = useState(false);
  const [pending, setPending]       = useState<{ ident: string; expand: boolean } | null>(null);
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  useEffect(() => { if (focus) setPending(focus); }, [focus]);

  const scrollToRow = useCallback((el: HTMLElement) => {
    const reduce = typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const c = scrollRef?.current;
    if (!c) { el.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" }); return; }
    // Container-relative scroll — never a scrollIntoView that yanks the app shell.
    const top = el.getBoundingClientRect().top - c.getBoundingClientRect().top + c.scrollTop - 72;
    c.scrollTo({ top, behavior: reduce ? "auto" : "smooth" });
  }, [scrollRef]);

  // Resolve a focus request: grow the list to include the row (if past the visible count),
  // expand it (unless it's a plain jump), then scroll it into view.
  useEffect(() => {
    if (!pending) return;
    const idx = signals.findIndex(s => signalIdentity(s.insight) === pending.ident);
    if (idx < 0) { setPending(null); onFocusHandled?.(); return; }
    if (idx >= shown) { setShown(Math.min(signals.length, Math.ceil((idx + 1) / LEDGER_STEP) * LEDGER_STEP)); return; }
    if (pending.expand) setExpandedId(pending.ident);
    const el = rowRefs.current.get(pending.ident);
    if (el) requestAnimationFrame(() => scrollToRow(el));
    setPending(null);
    onFocusHandled?.();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, shown]);

  if (signals.length === 0) return null;
  const top = signals.slice(0, shown);
  const remaining = signals.length - top.length;
  const domainsInList = [...new Set(signals.map(s => s.domain))];

  const jumpTo = (d: string) => {
    setJumpOpen(false);
    const s = signals.find(x => x.domain === d);
    if (s) setPending({ ident: signalIdentity(s.insight), expand: false });
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 10 }}>
        <span className="aug-label" style={{ color: "var(--t2)" }}>Findings</span>
        <span className="aug-fs-xs" style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", color: "var(--t4)" }}>
          {Math.min(shown, signals.length)} of {signals.length} shown · ranked by novelty
        </span>
      </div>
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", overflow: "hidden" }}>
        {top.map(sig => {
          const ident = signalIdentity(sig.insight);
          return (
            <LedgerRow key={ident} signal={sig} connectionId={connectionId}
              expanded={expandedId === ident}
              onToggle={() => setExpandedId(id => (id === ident ? null : ident))}
              onInvestigate={onInvestigate} onEvidence={onEvidence}
              rowRef={el => { if (el) rowRefs.current.set(ident, el); else rowRefs.current.delete(ident); }} />
          );
        })}
        {/* footer — Show next N · count · jump to domain (replaces the removed sticky nav rail) */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "11px 18px", background: "var(--bg-1)", fontSize: 12, color: "var(--t3)" }}>
          {remaining > 0 ? (
            <Button variant="ghost" size="xs" onClick={() => setShown(s => s + LEDGER_STEP)}
              style={{ color: "var(--t2)", fontWeight: 500, fontSize: 12, padding: "2px 6px" }}>
              Show next {Math.min(LEDGER_STEP, remaining)}
            </Button>
          ) : <span style={{ color: "var(--t4)" }}>All findings shown</span>}
          <span style={{ color: "var(--t4)" }}>· {Math.min(shown, signals.length)} of {signals.length}</span>
          <div style={{ marginLeft: "auto", position: "relative" }}>
            <Button variant="ghost" size="xs" onClick={() => setJumpOpen(o => !o)}
              style={{ color: "var(--t3)", fontSize: 12, padding: "2px 6px" }}>
              jump to domain ▾
            </Button>
            {jumpOpen && (
              <div style={{ position: "absolute", bottom: "calc(100% + 6px)", right: 0, zIndex: 20, background: "var(--bg-1)", border: "1px solid var(--b2)", borderRadius: "var(--r2)", boxShadow: "0 6px 20px rgba(0,0,0,.28)", minWidth: 170, overflow: "hidden", maxHeight: 260, overflowY: "auto" }}>
                {domainsInList.map(d => (
                  <Button key={d} variant="ghost" size="xs" onClick={() => jumpTo(d)}
                    className="w-full justify-start h-auto"
                    style={{ gap: 8, padding: "7px 11px", fontSize: 12, color: "var(--t2)" }}>
                    <span style={{ width: 6, height: 6, borderRadius: "var(--r-pill)", background: domainColor(d), flex: "none" }} />{d}
                  </Button>
                ))}
              </div>
            )}
          </div>
        </div>
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

  return (
    <div style={{
      background: "var(--bg-2)", border: "1px solid var(--b1)",
      borderRadius: "var(--r3)", padding: "14px 16px",
      display: "flex", flexDirection: "column" as const, gap: 10,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" as const }}>
        <DomainTag domain={domain} />
        {insight.angle && (
          <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>{insight.angle}</span>
        )}
        <span style={{ marginLeft: "auto" }}><NoveltyMeter novelty={insight.novelty} width={40} /></span>
      </div>
      <div className="aug-fs-sm" style={{ color: "var(--t2)", lineHeight: 1.55, flex: 1 }}>
        {insight.finding.length > 160 ? insight.finding.slice(0, 160) + "…" : insight.finding}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" as const }}>
        <Button
          variant="minimal" size="xs"
          onClick={() => onInvestigate(`Investigate: ${insight.finding}`, insight.id)}
        >
          Investigate →
        </Button>
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
      className="group"
      style={{
        display: "flex", alignItems: "flex-start", gap: 10,
        padding: "10px 12px", borderRadius: "var(--r2)",
        background: "var(--bg-2)", border: "1px solid var(--b1)",
        cursor: "pointer", transition: "background .1s",
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = "var(--bg-3)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = "var(--bg-2)"; }}
    >
      <span className="aug-fs-ui" style={{ color, flexShrink: 0, lineHeight: 1.4 }}>{icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="aug-fs-xs" style={{
          fontWeight: 500, color: "var(--t1)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const,
        }}>
          {pattern.title}
        </div>
        <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>
          {pattern.domains.length} domain{pattern.domains.length !== 1 ? "s" : ""} · {pattern.evidence_count} findings
        </div>
      </div>
      <span className="aug-label" style={{ flexShrink: 0 }}>{pattern.type}</span>
      {/* Hover-row affordance: a quiet chevron that confirms the row navigates, revealed on
          hover in a fixed 12px slot so it never nudges the layout. */}
      <span aria-hidden className="opacity-0 group-hover:opacity-100 transition-opacity"
        style={{ flexShrink: 0, width: 12, textAlign: "right" as const, color: "var(--blue4)", fontWeight: 700, lineHeight: 1.4 }}>→</span>
    </div>
  );
}

// ── Org signal row (sidebar) ───────────────────────────────────────────────────

function OrgSignalRow({ insight }: { insight: OrgInsight }) {
  return (
    <div style={{
      padding: "10px 12px", borderRadius: "var(--r2)",
      background: "var(--bg-2)", border: "1px solid var(--b1)",
    }}>
      <div style={{ display: "flex", gap: 6, marginBottom: 6, alignItems: "center", flexWrap: "wrap" as const }}>
        <DomainTag domain={insight.domain} />
        {insight.angle && (
          <span className="aug-fs-xs" style={{ color: "var(--t4)", marginLeft: "auto" }}>{insight.angle}</span>
        )}
      </div>
      <div className="aug-fs-xs" style={{ color: "var(--t2)", lineHeight: 1.5 }}>
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

// ── Loading state — content-shaped skeletons ────────────────────────────────────
// Not a bare spinner: the briefing's OWN shape shimmers in place, so the layout doesn't
// jump when the real content lands (the old spinner grew the section and shoved
// everything below it down). Uses the app's standard skeleton idiom (animate-pulse on a
// muted fill) and the same flat card language as the reskinned briefing.

/** One shimmer bar. */
function Shimmer({ w = "100%", h = 12, r = "var(--r1)", mt = 0 }: { w?: number | string; h?: number; r?: string; mt?: number }) {
  return <div className="animate-pulse" style={{ width: w, height: h, marginTop: mt, borderRadius: r, background: "var(--bg-3)" }} />;
}

const skelCard: React.CSSProperties = { background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)" };

/** The full-synthesis prose block while the narrative streams — mirrors NarrativeCard's shape. */
function SynthesisSkeleton() {
  return (
    <div style={{ ...skelCard, padding: "18px 22px", display: "flex", flexDirection: "column", gap: 9 }}
      aria-busy="true" aria-label="Writing intelligence brief">
      {["100%", "97%", "99%", "94%", "98%", "62%"].map((w, i) => <Shimmer key={i} w={w} h={12} />)}
    </div>
  );
}

/** Whole-briefing first load — verdict hero + 3 supporting signals + synthesis, in shape. */
function BriefingLoading() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }} aria-busy="true" aria-label="Synthesizing intelligence">
      {/* Verdict hero */}
      <div style={{ ...skelCard, padding: "18px 26px 20px" }}>
        <Shimmer w={130} h={10} />
        <Shimmer w={70} h={10} mt={16} />
        <Shimmer w="68%" h={22} mt={14} />
        <Shimmer w="46%" h={22} mt={8} />
        <Shimmer w="88%" h={13} mt={16} />
        <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
          <Shimmer w={120} h={30} />
          <Shimmer w={180} h={30} />
        </div>
      </div>
      {/* Supporting signals — 3-up */}
      <div>
        <Shimmer w={120} h={11} />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14, marginTop: 10 }}>
          {[0, 1, 2].map(i => (
            <div key={i} style={{ ...skelCard, padding: "16px 18px", display: "flex", flexDirection: "column", gap: 10 }}>
              <Shimmer w={80} h={20} r="var(--r-pill)" />
              <Shimmer w="100%" h={12} mt={4} />
              <Shimmer w="92%" h={12} />
              <Shimmer w="70%" h={12} />
            </div>
          ))}
        </div>
      </div>
      {/* Full synthesis */}
      <div>
        <Shimmer w={110} h={11} />
        <div style={{ marginTop: 10 }}><SynthesisSkeleton /></div>
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
  // Scope chips: narrow the narrative layer (supporting signals + top patterns) to one
  // domain; null = all. The standing cockpit layer is intentionally left unscoped — it's
  // the user's arranged surface, not a per-cycle finding view.
  const [scope, setScope]                   = useState<string | null>(null);
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
  // Deep-linking within the brief: a digest tile / jump menu asks the ledger to expand +
  // scroll to a finding, and it scrolls THIS container (never a shell-yanking scrollIntoView).
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [ledgerFocus, setLedgerFocus] = useState<{ ident: string; expand: boolean } | null>(null);

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
    toast.info("No delivery channel yet", { description: "Add a Slack/webhook trigger in Action Hub to share findings." });
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

  // ── ⌘K contextual commands (present only while the Briefing is mounted) ──
  const regenRefCmd = useRef(generateNarrative);
  const startRefCmd = useRef(runExplorer);
  useEffect(() => { regenRefCmd.current = generateNarrative; startRefCmd.current = runExplorer; });
  const briefCommands = useMemo<Command[]>(() => [
    { id: "brief-regen",   label: "Regenerate brief",  sublabel: "Re-synthesize the intelligence briefing",          icon: "spark",   accent: "var(--blue3)", keywords: "regenerate refresh brief narrative synthesis",  run: () => regenRefCmd.current(true) },
    { id: "brief-explore", label: "Start exploration", sublabel: "Run the autonomous explorer on this connection",   icon: "process", accent: "var(--cyn3)",  keywords: "explore exploration run analyze discover signals", run: () => startRefCmd.current() },
  ], []);
  useRegisterCommands("briefing", briefCommands);

  // Scope-chip derivations — filter the narrative-layer findings + patterns to the active
  // domain. Guard the scope against a stale value (a reload can drop the domain), and drop
  // the headline (it already leads the verdict hero) by IDENTITY — not id, which collides
  // across the meta-domains. Unscoped, the strip starts breadth-first (the deduped one-per-
  // domain signals) and extends into the full impact-ranked list behind "Show more".
  const scopeDomain    = scope && briefing?.domains.some(d => d.name === scope) ? scope : null;
  const headlineIdent  = briefing?.headline ? signalIdentity(briefing.headline.insight) : null;
  const scopedSignals  = !briefing
    ? []
    : dedupeSignals(
        scopeDomain
          ? briefing.allSignals.filter(s => s.domain === scopeDomain)
          : [...briefing.signals, ...briefing.allSignals],
      ).filter(s => signalIdentity(s.insight) !== headlineIdent);
  const scopedPatterns = !briefing
    ? []
    : scopeDomain
      ? briefing.patterns.filter(p => p.domains?.includes(scopeDomain))
      : briefing.patterns;

  const hasPatterns    = scopedPatterns.length > 0;
  const hasNarrative   = !!narrative?.narrative;
  const isEmpty        = !briefing || briefing.totalInsights === 0;

  // "Numbers that moved" (hero digest) + the cockpit's suggested pins share ONE extraction:
  // the top findings (unscoped, headline excluded) that yield a key figure, in impact order.
  // Every figure is quoted from a grounded finding statement — never invented.
  const movers = useMemo<DigestTile[]>(() => {
    if (!briefing) return [];
    const headlineId = briefing.headline ? signalIdentity(briefing.headline.insight) : null;
    const ranked = dedupeSignals([...briefing.signals, ...briefing.allSignals])
      .filter(s => signalIdentity(s.insight) !== headlineId);
    const out: DigestTile[] = [];
    for (const s of ranked) {
      const fig = extractKeyFigure(s.insight.finding);
      if (!fig) continue;
      out.push({
        ident: signalIdentity(s.insight), insightId: s.insight.id,
        value: fig.value, secondary: fig.secondary, sublabel: fig.sublabel,
        label: s.insight.finding, domain: s.domain, accent: domainColor(s.domain),
      });
      if (out.length >= 6) break;
    }
    return out;
  }, [briefing]);

  if (loading)  return <BriefingLoading />;

  if (error) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ fontSize: 12, color: "var(--red4)" }}>{error}</div>
      </div>
    );
  }

  return (
    <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "20px 28px" }}>

      {/* Evidence drill-through drawer (finding actions, #4). Transient hints/side-effect
          feedback now go through the shared <Toaster/> (toast.*), mounted in the root layout. */}
      <EvidenceDrawer insight={evidenceInsight} domain={evidenceDomain} connectionId={connectionId} onClose={() => setEvidenceInsight(null)} />

      {/* ── Explorer control bar ── demoted to a thin machinery strip: it explains where the
          brief comes from, but it isn't content. Single hairline row, mono --t4. */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, padding: "9px 2px", borderBottom: "1px solid var(--b0)" }}>
        <span style={{ fontSize: 11, color: "var(--t4)", fontFamily: "var(--font-mono)", letterSpacing: ".08em", textTransform: "uppercase" }}>
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
              <Button
                variant="secondary" size="xs"
                disabled={explorerBusy} onClick={runExplorer}
              >Start</Button>
              {explorerStatus?.phase === "complete" && (
                <Button
                  variant="secondary" size="xs"
                  disabled={explorerBusy} onClick={runTriggerIntel}
                >Trigger Intel</Button>
              )}
              {explorerStatus?.phase === "complete" && (
                <Button
                  variant="secondary" size="xs"
                  disabled={explorerBusy} onClick={runRefresh}
                  title="Clear stale findings and re-run intelligence from scratch (drops 'no data' findings, re-anchors the window)"
                >↻ Refresh</Button>
              )}
            </>
          ) : (
            <>
              <Button
                variant="secondary" size="xs"
                disabled={explorerBusy} onClick={runStop}
              >Stop</Button>
              <Button
                variant="secondary" size="xs"
                disabled={explorerBusy} onClick={runRefresh}
              >Restart</Button>
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
        digest={movers}
        onFinding={(ident) => setLedgerFocus({ ident, expand: true })}
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
            overflow
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
      {/* ── Scope chips ── focus the narrative layer (signals + patterns) on one domain. */}
      <ScopeChips domains={briefing.domains} total={briefing.totalInsights} active={scopeDomain} onChange={setScope} />

      {/* ── Findings ── the bulletin ledger: one scannable row per finding, chart on expand,
          impact-ordered and scoped by the chips; keyed by scope so it resets on a scope change. */}
      <FindingsLedger key={scopeDomain ?? "all"} signals={scopedSignals} connectionId={connectionId}
        onInvestigate={onInvestigate} onEvidence={openEvidence}
        focus={ledgerFocus} onFocusHandled={() => setLedgerFocus(null)} scrollRef={scrollRef} />

      {/* ── Full synthesis ── the multi-paragraph narrative + interactive citations.
          The hero above already carries the conclusion, so this card hides its header. */}
      {(hasNarrative || narrativeLoading || narrativeError) && (
        <div>
          <div className="aug-label" style={{ marginBottom: 10 }}>Full synthesis</div>
          {narrativeLoading && <SynthesisSkeleton />}
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
              collapsible
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

      {/* ── Standing layer ── the cockpit + KPIs, marked off from this cycle's narrative by a
            single violet rule (violet = user/pinned, already the system's semantic). The layer
            is ALWAYS present now — even with no pins — so the cockpit teaches itself (empty
            state) instead of vanishing. The cycle's findings read above in the ledger; the
            cockpit is the surface the user curates, not a dump of the brief. */}
      <div style={{ marginTop: 34, paddingTop: 20, borderTop: "1px solid var(--vio2)" }}>
        <div className="aug-label" style={{ color: "var(--vio4)", marginBottom: 12 }}>Your cockpit</div>
        {/* Door 3 (inline authoring) sits at the top so the first card can be composed even when empty. */}
        <NewCardComposer connectionId={connectionId} schema={schema}
          onCreated={() => setPinnedRefresh(n => n + 1)} />
        <PinnedCards connectionId={connectionId} schema={schema} refreshKey={pinnedRefresh}
          suggestions={movers.slice(0, 3).map(m => ({ insightId: m.insightId, value: m.value, label: m.sublabel || m.domain }))}
          onPinned={() => setPinnedRefresh(n => n + 1)}
          onOpenSource={(iid) => onInvestigate("Investigate this finding", iid)}
          onEvidence={(iid) => { const sig = briefing.insightById.get(iid); if (sig) openEvidence(sig.insight, sig.domain); }} />

        {/* ── Industry key metrics ── the vertical's north-star KPIs, computed live; click a
              card to expand its trend. Renders a define-CTA (not nothing) when none are set. */}
        <IndustryKpiStrip connectionId={connectionId} schema={schema} />
      </div>

      {lens === "linear" && (<>
      {/* ── The findings now render as chart/table cards in the cockpit above (PinnedCards),
          replacing the old text "Dashboard" section — one unified, arrangeable card surface. ── */}

      {/* ── Top patterns ── a full-width row below the cockpit. */}
      {hasPatterns && (
        <div style={{ display: "flex", gap: 24, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 280px", minWidth: 240 }}>
            <div className="aug-label" style={{ marginBottom: 10 }}>Top Patterns</div>
            <div style={{ display: "flex", flexDirection: "column" as const, gap: 6 }}>
              {scopedPatterns.map(p => (
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
