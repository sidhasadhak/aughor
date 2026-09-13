"use client";
import { ErrorState } from "@/components/ui/states";
import { CiteRef, GuardChip } from "@/components/ui/trust";

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
import { countNoun, formatTimestamp, formatMetricValue, normalizeNumberPrecision } from "@/lib/format";
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
import { Pending, SkeletonRows } from "@/components/ui/motion";
import { MovedNumbers } from "@/components/brief/MovedNumbers";
import { useNorthStarMoves } from "@/components/brief/useNorthStarMoves";
import { periodWord } from "@/components/brief/metricFormat";
import { BriefSchedule } from "@/components/brief/BriefSchedule";
import { extractKeyFigure } from "@/components/brief/keyFigure";
import { PinnedCards } from "@/components/brief/PinnedCards";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import type { VizConfig } from "@/components/charts/vizConfig";
import { useVizConfigs } from "@/lib/useVizConfigs";
import { toast } from "@/components/ui/toast";
import { useRegisterCommands, type Command } from "@/lib/commandRegistry";
import { InlineInvestigationThread } from "@/components/brief/InlineInvestigationThread";
import { GroundedNumber, withGroundedNumbers } from "@/components/brief/GroundedNumber";
import { BriefAskPanel } from "@/components/brief/BriefAskPanel";
import { NewCardComposer } from "@/components/brief/NewCardComposer";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";

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
  /** Queries the explorer spent on these domains, as the store counts them. */
  queriesUsed:   number;
  synthesizedAt: string;
  /** insight_id → {insight, domain} so a narrative citation can resolve to the full
   *  finding and offer the same actions a finding card has. */
  insightById:   Map<string, SynthesisSignal>;
}

// ── Inline citation renderer ───────────────────────────────────────────────────
// Parses narrative text for [N] markers; each becomes a superscript into the apparatus.

function NarrativeText({
  text,
  citations,
  onCitationClick,
  connectionId,
  schema,
}: {
  text: string;
  citations: BriefingCitation[];
  onCitationClick: (citation: BriefingCitation, anchor: DOMRect) => void;
  /** Connection + schema scope so each magnitude number can be grounded ("show the receipt"). */
  connectionId: string;
  schema?: string;
}) {
  const citationMap = Object.fromEntries(citations.map(c => [c.ref, c]));
  // Every cited insight — a synthesized number may have come from any of them, so we
  // ground against all (primary = nearest) rather than only the nearest citation.
  const allInsightIds = Array.from(new Set(citations.map(c => c.insight_id).filter(Boolean)));
  // Render-boundary backstop for float noise. Upstream (aughor/util/format.py) now rounds on
  // the way into the prompt AND at emit, so this is a no-op on fresh briefs — it exists to
  // correct prose synthesized before that landed, including anything still in the 2h cache.
  // Rounding only shortens a decimal run, so the GroundedNumber receipt still matches its cell.
  const parts = normalizeNumberPrecision(text).split(/(\[\d+\])/g);
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
          const c = citationMap[match[1]];
          return (
            <CiteRef key={i} refNo={match[1]}
              title={c ? `${c.domain}${c.angle ? ` · ${c.angle}` : ""} — ${c.finding}` : undefined}
              onOpen={c ? anchor => onCitationClick(c, anchor) : undefined} />
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

// ── Citation actions ─────────────────────────────────────────────────────────────

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
          boxShadow: "var(--shadow-lg)", padding: 12,
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

// ── Helpers ────────────────────────────────────────────────────────────────────

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
  let queriesUsed = 0;

  // Index every insight by id (including degenerate ones) so a citation referencing
  // any finding can resolve to the full object for its action menu.
  const insightById = new Map<string, SynthesisSignal>();

  // Never surface a degenerate "no data" finding — it must not win the headline or a
  // signal slot (the backend now drops these at the source; this also hides any that
  // were stored before that fix). Such findings stay visible only in the full Hub ledger.
  for (const [domain, data] of Object.entries(domainData)) {
    queriesUsed += data.queries_used ?? 0;
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
    queriesUsed,
    synthesizedAt: new Date().toISOString(),
    insightById,
  };
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
        borderRadius: "var(--r-chip)", gap: 6, height: 26,
        background: active ? "color-mix(in srgb, var(--blue4) 12%, var(--bg-2))" : "var(--bg-2)",
        border: `1px solid ${active ? "var(--blue4)" : "var(--b1)"}`,
        color: active ? "var(--blue4)" : "var(--t2)",
        fontWeight: active ? 500 : 400,
      }}
    >
      {dot && <span style={{ width: 7, height: 7, borderRadius: "var(--r-pill)", background: dot, flexShrink: 0 }} />}
      {label}
      <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: active ? "var(--blue4)" : "var(--t3)", opacity: 0.85 }}>{count}</span>
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

/** How the explorer's phase should READ to a person, given whether work survived it.
 *
 * The stored phase is untouched — `failed` stays `failed` in the record, because
 * `canvas_needs_resume`, `is_unfinished` and the boot recovery all key on it. This decides
 * only the WORD and the colour on screen.
 *
 * **Why "failed" was the wrong word here.** A run that ends without completing is recorded
 * as `failed` whatever the cause, and the engine's own most common reason is *"cancelled
 * (budget exceeded or stopped) — progress saved"*. Rendering that in red as FAILED
 * overstates what the engine actually recorded, and it did real damage: a deployment with
 * 54 findings and a grounded briefing read as broken, and the reasonable response was to
 * throw the lot away and start again.
 *
 * **What is NOT softened.** A run that ended with nothing behind it still reads `failed`,
 * in red, because there is nothing to keep and it genuinely wants attention. The split is
 * the one already in the data — did this connection end up with work or not — so no
 * judgement is being invented to make a number look better.
 */
export function explorerPhaseLabel(
  phase: string | undefined, hasWork: boolean,
): { text: string; tone: "good" | "warn" | "bad" | "busy" } {
  if (phase === "complete") return { text: "complete", tone: "good" };
  if (phase !== "failed") return { text: phase ?? "unknown", tone: "busy" };
  return hasWork
    // Accurate and not alarming: the run stopped short, the work stands.
    ? { text: "incomplete", tone: "warn" }
    : { text: "failed", tone: "bad" };
}


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
      {status === "busy" && <Pending />}
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
      <span style={{ fontSize: 11, color: "var(--t3)", fontStyle: "italic" as const }}>
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
            <div style={{ position: "absolute", top: "calc(100% + 4px)", right: 0, zIndex: 30, background: "var(--bg-1)", border: "1px solid var(--b2)", borderRadius: "var(--r2)", boxShadow: "var(--shadow-lg)", minWidth: 150, padding: 4, display: "flex", flexDirection: "column" as const, gap: 2 }}>
              <Button variant="ghost" size="xs" className="w-full justify-start h-auto" disabled={degenerate}
                onClick={() => { setMoreOpen(false); handlePromote(); }}
                style={{ padding: "7px 10px", fontSize: 12, color: degenerate ? "var(--t3)" : "var(--t2)" }}>
                {promStatus === "done" ? "Promoted ✓" : "Promote"}
              </Button>
              <div style={{ position: "relative" }}>
                <Button variant="ghost" size="xs" className="w-full justify-start h-auto" disabled={degenerate}
                  onClick={() => { if (triggers.length === 0) { setMoreOpen(false); onTriggersHint(); } else { setShareOpen(v => !v); } }}
                  style={{ padding: "7px 10px", fontSize: 12, color: degenerate ? "var(--t3)" : "var(--t2)" }}>
                  Share
                </Button>
                {shareOpen && triggers.length > 0 && (
                  <div style={{ position: "absolute", top: 0, right: "calc(100% + 4px)", zIndex: 40, background: "var(--bg-1)", border: "1px solid var(--b2)", borderRadius: "var(--r2)", boxShadow: "var(--shadow-lg)", minWidth: 160, overflow: "hidden" }}>
                    {triggers.map(t => (
                      <Button key={t.id} variant="ghost" size="xs" className="w-full justify-start h-auto"
                        onClick={() => { handleShareTo(t); setMoreOpen(false); }}
                        style={{ padding: "7px 10px", fontSize: 12, color: t.enabled ? "var(--t2)" : "var(--t3)" }}>
                        <span className="aug-fs-xs" style={{ fontFamily: "var(--font-mono)", color: "var(--t3)", marginRight: 6 }}>{t.type}</span>{t.name}{!t.enabled && " (disabled)"}
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
          <span title={noData} className="aug-label" style={{ padding: "2px 6px", borderRadius: "var(--r1)", color: "var(--t3)", background: "var(--bg-3)", border: "1px solid var(--b1)" }}>no data</span>
        )}
        {shareMsg && (
          <span className="aug-fs-xs" style={{ color: shareMsg.includes("✓") ? "var(--grn4)" : "var(--t3)" }}>{shareMsg}</span>
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
            boxShadow: "var(--shadow-lg)", minWidth: 160, overflow: "hidden",
          }}>
            <div className="aug-label" style={{ padding: "6px 10px", borderBottom: "1px solid var(--b1)" }}>
              Send to channel
            </div>
            {triggers.map(t => (
              <button key={t.id} onClick={() => handleShareTo(t)}
                style={{
                  display: "block", width: "100%", textAlign: "left" as const,
                  padding: "7px 10px", fontSize: 12, background: "transparent", border: "none",
                  color: t.enabled ? "var(--t2)" : "var(--t3)", cursor: "pointer",
                }}
                onMouseEnter={e => { e.currentTarget.style.background = "var(--bg-3)"; }}
                onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}>
                <span className="aug-fs-xs" style={{ fontFamily: "var(--font-mono)", color: "var(--t3)", marginRight: 6 }}>{t.type}</span>
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
          padding: "2px 6px", borderRadius: "var(--r1)", color: "var(--t3)",
          background: "var(--bg-3)", border: "1px solid var(--b1)",
        }}>no data</span>
      )}
      {shareMsg && (
        <span className="aug-fs-xs" style={{ color: shareMsg.includes("✓") ? "var(--grn4)" : "var(--t3)" }}>{shareMsg}</span>
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
            <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--t3)", wordBreak: "break-word" as const, lineHeight: 1.5 }}>
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
          style={{ padding: "5px 11px", borderRadius: "var(--r1)", background: "var(--bg-3)", border: "1px solid var(--b2)", color: "var(--t1)", fontSize: 12, fontWeight: 500, cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1 }}
        >{busy ? "Re-validating…" : "Re-validate"}</button>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>as of {asOfText}</span>
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
      position: "fixed", inset: 0, zIndex: 60, background: "var(--scrim)",
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
          <div style={{ fontSize: 15, color: "var(--t1)", lineHeight: 1.6, fontWeight: 500 }}>{insight.finding}</div>

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
              fontSize: 12, fontFamily: "var(--font-code)", color: "var(--t2)",
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

/**
 * The expanded body of a finding — its grounded result as a chart (or a big scalar, or an
 * honest "no chartable result"), plus Evidence / Investigate.
 *
 * Opened from its row in the findings ledger. Display edits persist through
 * `vizConfig`/`onVizConfigChange`, keyed by the finding's id.
 */
function FindingDetail({
  insight, domain, connectionId, chartHeight, onInvestigate, onEvidence,
  vizConfig, onVizConfigChange,
}: {
  insight:       ExplorationInsight;
  domain:        string;
  connectionId:  string;
  chartHeight:   number;
  onInvestigate: (q: string, insightId?: string) => void;
  onEvidence:    (ins: ExplorationInsight, domain: string) => void;
  vizConfig?:      VizConfig | null;
  onVizConfigChange?: (c: VizConfig) => void;
}) {
  // The finding's own grounded result — fetched LAZILY on first mount of the detail
  // (server-cached, same query the explorer ran). A single scalar shows as the big figure;
  // anything richer renders through the chart card; error/empty → text only.
  const [run, setRun]     = useState<{ columns: string[]; rows: unknown[][] } | null>(null);
  const [phase, setPhase] = useState<"idle" | "loading" | "chart" | "text">("idle");
  // `phase` is deliberately NOT a dependency: including it makes the effect re-run the instant
  // it flips to "loading", and that re-run's cleanup sets alive=false on the fetch just kicked
  // off — so it never reaches "chart" and the body sticks on the shimmer. Guard on `run` so a
  // re-render doesn't refetch; StrictMode's remount simply starts a fresh (server-cached) call.
  useEffect(() => {
    if (run) return;
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
  }, [run, connectionId, insight.sql]);

  const scalar = run && run.rows.length === 1 && run.columns.length === 1 && !isNaN(Number(run.rows[0][0]))
    ? Number(run.rows[0][0]) : null;

  return (
    <div style={{ background: "var(--bg-1)", border: "1px solid var(--b0)", borderRadius: "var(--r2)", padding: 12 }}>
      {phase === "loading" && <div className="aug-skeleton" style={{ height: chartHeight, borderRadius: "var(--r2)" }} />}
      {phase === "text" && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "8px 2px" }}>
          No chartable result for this finding — the statement above is the finding.
        </div>
      )}
      {phase === "chart" && run && (scalar != null ? (
        <div className="aug-fs-display" style={{ color: "var(--t1)", fontWeight: 700, fontFamily: "var(--font-mono)", lineHeight: 1, padding: "18px 2px" }}>
          {/* Rendered as a HEADLINE, not a grid cell, so it takes the prose precision policy —
              otherwise it reads "45.4865" directly beneath a statement saying "45.49%".
              `formatMetricValue` still owns the K/M/B abbreviation. */}
          {normalizeNumberPrecision(formatMetricValue(scalar))}
        </div>
      ) : (
        <div style={{ minHeight: chartHeight }}>
          <ResultChartCard columns={run.columns} rows={run.rows} fillHeight={chartHeight}
            config={vizConfig} onConfigChange={onVizConfigChange} />
        </div>
      ))}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 10 }}>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{insight.angle || "The finding's grounded query"}</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 12 }}>
          <Button variant="ghost" size="xs" onClick={() => onEvidence(insight, domain)}
            title="See the query + provenance behind this finding"
            style={{ fontSize: 11, color: "var(--vio4)", padding: "2px 6px" }}>Evidence</Button>
          <Button variant="ghost" size="xs" onClick={() => onInvestigate(`Investigate: ${insight.finding}`, insight.id)}
            style={{ fontSize: 11, fontWeight: 600, color: "var(--blue4)", padding: "2px 6px" }}>Investigate →</Button>
        </span>
      </div>
    </div>
  );
}

function LedgerRow({ signal, connectionId, expanded, onToggle, onInvestigate, onEvidence, rowRef, vizConfig, onVizConfigChange }: {
  signal:        SynthesisSignal;
  connectionId:  string;
  expanded:      boolean;
  onToggle:      () => void;
  onInvestigate: (q: string, insightId?: string) => void;
  onEvidence:    (ins: ExplorationInsight, domain: string) => void;
  rowRef:        (el: HTMLDivElement | null) => void;
  vizConfig?:      VizConfig | null;
  onVizConfigChange?: (c: VizConfig) => void;
}) {
  const { insight, domain } = signal;
  const fig = extractKeyFigure(insight.finding);
  const hot = insight.novelty >= 5;      // Notable/High → amber novelty dot; else quiet --b3
  const [hover, setHover] = useState(false);

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
              {fig.value}{fig.secondary && <span style={{ color: "var(--t3)", fontSize: 12 }}>{fig.secondary}</span>}
            </div>
            {fig.sublabel && <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--t3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{fig.sublabel}</div>}
          </>)}
        </div>
        {/* chevron */}
        <span aria-hidden style={{ color: "var(--t3)", fontSize: 12, textAlign: "center" }}>{expanded ? "▴" : "▾"}</span>
      </div>

      {expanded && (
        <div style={{ padding: "0 18px 16px" }}>
          <FindingDetail insight={insight} domain={domain} connectionId={connectionId}
            chartHeight={LEDGER_CHART_H} onInvestigate={onInvestigate} onEvidence={onEvidence}
            vizConfig={vizConfig} onVizConfigChange={onVizConfigChange} />
        </div>
      )}
    </div>
  );
}

function FindingsLedger({ signals, connectionId, onInvestigate, onEvidence, scrollRef, vizConfigFor, onVizConfigChange }: {
  signals:        SynthesisSignal[];
  connectionId:   string;
  onInvestigate:  (q: string, insightId?: string) => void;
  onEvidence:     (ins: ExplorationInsight, domain: string) => void;
  /** The ledger's own scroll container — so the jump menu scrolls the panel, not the app shell. */
  scrollRef?:     { current: HTMLDivElement | null };
  /** Saved chart display per insight — so an edit survives collapsing the row (or opening
   *  another, since the ledger is single-open and used to destroy the first row's edits). */
  vizConfigFor?:      (insightId: string) => VizConfig | null;
  onVizConfigChange?: (insightId: string, c: VizConfig) => void;
}) {
  const [shown, setShown]           = useState(LEDGER_DEFAULT);
  const [expandedId, setExpandedId] = useState<string | null>(null);   // one row open at a time
  const [jumpOpen, setJumpOpen]     = useState(false);
  const [pending, setPending]       = useState<{ ident: string; expand: boolean } | null>(null);
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const scrollToRow = useCallback((el: HTMLElement) => {
    const reduce = typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const c = scrollRef?.current;
    if (!c) { el.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" }); return; }
    // Container-relative scroll — never a scrollIntoView that yanks the app shell.
    const top = el.getBoundingClientRect().top - c.getBoundingClientRect().top + c.scrollTop - 72;
    c.scrollTo({ top, behavior: reduce ? "auto" : "smooth" });
  }, [scrollRef]);

  // Resolve a jump request: grow the list to include the row (if past the visible count),
  // expand it (unless it's a plain jump), then scroll it into view.
  useEffect(() => {
    if (!pending) return;
    const idx = signals.findIndex(s => signalIdentity(s.insight) === pending.ident);
    if (idx < 0) { setPending(null); return; }
    if (idx >= shown) { setShown(Math.min(signals.length, Math.ceil((idx + 1) / LEDGER_STEP) * LEDGER_STEP)); return; }
    if (pending.expand) setExpandedId(pending.ident);
    const el = rowRefs.current.get(pending.ident);
    if (el) requestAnimationFrame(() => scrollToRow(el));
    setPending(null);
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
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", overflow: "hidden" }}>
        {top.map(sig => {
          const ident = signalIdentity(sig.insight);
          return (
            <LedgerRow key={ident} signal={sig} connectionId={connectionId}
              expanded={expandedId === ident}
              onToggle={() => setExpandedId(id => (id === ident ? null : ident))}
              onInvestigate={onInvestigate} onEvidence={onEvidence}
              rowRef={el => { if (el) rowRefs.current.set(ident, el); else rowRefs.current.delete(ident); }}
              vizConfig={vizConfigFor?.(sig.insight.id) ?? null}
              onVizConfigChange={onVizConfigChange ? c => onVizConfigChange(sig.insight.id, c) : undefined} />
          );
        })}
        {/* footer — Show next N · count · jump to domain (replaces the removed sticky nav rail) */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "11px 18px", background: "var(--bg-1)", fontSize: 12, color: "var(--t3)" }}>
          {remaining > 0 ? (
            <Button variant="ghost" size="xs" onClick={() => setShown(s => s + LEDGER_STEP)}
              style={{ color: "var(--t2)", fontWeight: 500, fontSize: 12, padding: "2px 6px" }}>
              Show next {Math.min(LEDGER_STEP, remaining)}
            </Button>
          ) : <span style={{ color: "var(--t3)" }}>All findings shown</span>}
          <span style={{ color: "var(--t3)" }}>· {Math.min(shown, signals.length)} of {signals.length}</span>
          <div style={{ marginLeft: "auto", position: "relative" }}>
            <Button variant="ghost" size="xs" onClick={() => setJumpOpen(o => !o)}
              style={{ color: "var(--t3)", fontSize: 12, padding: "2px 6px" }}>
              jump to domain ▾
            </Button>
            {jumpOpen && (
              <div style={{ position: "absolute", bottom: "calc(100% + 6px)", right: 0, zIndex: 20, background: "var(--bg-1)", border: "1px solid var(--b2)", borderRadius: "var(--r2)", boxShadow: "var(--shadow-lg)", minWidth: 170, overflow: "hidden", maxHeight: 260, overflowY: "auto" }}>
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
  // "pending" is not "never": a queued or boot-resumed run reads pending for its
  // first seconds while prior findings still exist, and rendering "No exploration
  // has run yet" over real data was a visible flicker. Pending with ANY recorded
  // work shows as a run in flight; only a truly blank status means never.
  if (
    status &&
    phase === "pending" &&
    (status.insights_found > 0 || status.facts_discovered > 0 || status.queries_executed > 0)
  ) {
    return {
      kind: "running",
      queries: status.queries_executed,
      insights: status.insights_found,
      phase,
    };
  }
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
  synthesis:         "composing cross-domain findings",
};

// The birth rite's steps, which run BEFORE the first exploration phase exists. Measured
// on a 38-table schema: intelligence 7.6s, popularity 8.9s — so this names ~16.5s that
// otherwise reads as a stalled Start button. Same voice as PHASE_LABELS: what it is
// doing, not what it is called internally.
const BIRTH_STEP_LABELS: Record<string, string> = {
  intelligence: "Building intelligence…",
  popularity:   "Reading query history…",
  exploration:  "Starting exploration…",
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
          <Pending label="Generating the briefing" className="aug-fs-h1" style={{ color: "var(--t3)" }} />
        ) : (
          <span style={{ color: "var(--t3)", display: "inline-flex" }}><Icon name="brief" size={22} /></span>
        )}
      </div>
      <div style={{ textAlign: "center" as const, maxWidth: 400 }}>
        <div style={{ fontSize: 15, fontWeight: 500, color: "var(--t2)", marginBottom: 6 }}>
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
              <Pending />
              Working…
            </>
          ) : (
            <>
              <Icon name="spark" size={12} />
              {cta.label}
            </>
          )}
        </button>
      )}
    </div>
  );
}

// ── The brief as an artefact (Aughor Intelligence · 01 Briefing) ────────────────────────────
// A 700px measure, numbered sections in a 44px gutter, superscripts into a margin apparatus and a
// signature block. The other Intelligence layers are instrument-dense and get none of it.

/** What the shell's header shows for this layer (IntelligenceWorkspace draws it). */
export interface BriefHead {
  /** When the brief on screen was written — the server's stamp, not when this page loaded. */
  generatedAt: string | null;
  /** `writing`: a brief asked for with Regenerate; `opening`: the cached brief being read. */
  pending: "writing" | "opening" | null;
  hasNarrative: boolean;
  /** No findings in scope, so there is nothing to write a brief from. */
  empty: boolean;
  regenerate: () => void;
  investigate: { label: string; run: () => void } | null;
}

/** The cockpit's suggested pin — a key figure quoted from a finding. */
interface SuggestedPin { insightId: string; value: string; label: string }

type NarrativeProps = {
  citations: BriefingCitation[];
  onCitationClick: (citation: BriefingCitation, anchor: DOMRect) => void;
  connectionId: string;
  schema?: string;
};

/** The narrator writes a 2–3 sentence lede, then 2–4 paragraphs of depth, blank-line separated
 *  (knowledge/briefing.py). The lede stands under the verdict; the depth is §2. */
export function splitLede(narrative: string): { lede: string; depth: string[] } {
  const paras = narrative.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
  return { lede: paras[0] ?? "", depth: paras.slice(1) };
}

/** How many figures in the prose can be matched to a live cell — the same rule that makes a
 *  figure clickable, so the signature counts exactly what a reader can open. */
function countReceiptFigures(text: string): number {
  let n = 0;
  withGroundedNumbers(normalizeNumberPrecision(text), () => { n++; return null; }, "count");
  return n;
}

function BriefSection({ mark, children }: { mark: string; children: ReactNode }) {
  return (
    <section className="aug-brief-sec">
      <div className="aug-brief-gutter" aria-hidden>{mark}</div>
      <div className="aug-brief-body">{children}</div>
    </section>
  );
}

function SectionHead({ title, meta }: { title: string; meta?: ReactNode }) {
  return (
    <div className="aug-brief-head">
      <h2 className="aug-brief-title">{title}</h2>
      {meta != null && meta !== "" && <span className="aug-brief-meta">{meta}</span>}
    </div>
  );
}

/**
 * The margin the superscripts point into, and the brief's signature.
 *
 * Every note is a finding the prose cites, opening the same actions its superscript does. The
 * signature says only what the screen can stand behind: how many figures a reader can check
 * against a live cell, and how the trust gate read the cited findings. No confidence is printed
 * — none is computed for a brief — and nothing animates toward one.
 */
function ApparatusRail({ citations, pending, hasNarrative, narrativeText, insightById, activeRef, onOpen }: {
  citations:     BriefingCitation[];
  pending:       BriefHead["pending"];
  hasNarrative:  boolean;
  narrativeText: string;
  insightById:   Map<string, SynthesisSignal>;
  activeRef:     string | null;
  onOpen:        (citation: BriefingCitation, anchor: DOMRect) => void;
}) {
  const signed = hasNarrative && !pending;
  const figures = signed ? countReceiptFigures(narrativeText) : 0;
  // The trust gate's reading of the findings the prose leans on, as /domains stamped it. A
  // metric move is a measured trend, not a gated finding, so it is not counted either way.
  let passed = 0, confound = 0, unread = 0, gone = 0;
  const seen = new Set<string>();
  for (const c of citations) {
    if (seen.has(c.insight_id) || c.insight_id.startsWith("metric-move::")) continue;
    seen.add(c.insight_id);
    const sig = insightById.get(c.insight_id);
    const p = sig?.insight.plausibility;
    if (!sig) gone++;
    else if (p === undefined) unread++;
    else if (p === null) passed++;
    else if (p === "confound") confound++;
  }
  const sigText = [
    figures > 0
      ? `${countNoun(figures, "figure")} in the prose can be checked against a live cell — open one to see the match.`
      : "The prose states no figure large enough to check against a cell.",
    gone > 0
      ? `${countNoun(gone, "cited finding")} ${gone === 1 ? "is" : "are"} no longer in the findings, so the trust gate has no reading of ${gone === 1 ? "it" : "them"}.`
      : "",
    unread > 0 ? `${countNoun(unread, "cited finding")} ${unread === 1 ? "carries" : "carry"} no trust-gate reading.` : "",
  ].filter(Boolean).join(" ");
  // Notes read in their own order, whatever order the narrator happened to cite them in.
  const notes = [...citations].sort((a, b) => Number(a.ref) - Number(b.ref));

  return (
    <aside className="aug-apparatus" aria-label="Apparatus">
      <div className="aug-apparatus-head">
        <span className="aug-brief-eyebrow">Apparatus</span>
        <span className={`aug-brief-meta${pending ? " aug-brief-writing" : ""}`}>
          {pending === "writing" ? "being written" : pending === "opening" ? "opening" : countNoun(citations.length, "note")}
        </span>
      </div>

      {pending ? (
        <div className="aug-apparatus-notes" aria-busy="true">
          {["92%", "74%", "84%"].map((w, i) => (
            <div key={i} className="aug-apparatus-note" style={{ cursor: "default" }}>
              <span className="aug-apparatus-n">{i + 1}</span>
              <span className="aug-apparatus-body aug-brief-skel" style={{ flex: 1 }}>
                <span className="aug-skeleton" style={{ width: w }} />
                <span className="aug-skeleton" style={{ width: "48%" }} />
              </span>
            </div>
          ))}
        </div>
      ) : citations.length === 0 ? (
        <div className="aug-apparatus-notes">
          <p className="aug-apparatus-empty">
            {hasNarrative ? "This brief cites no findings." : "Notes appear when the brief is written — each one is a finding its prose cites."}
          </p>
        </div>
      ) : (
        <ol className="aug-apparatus-notes">
          {notes.map(c => {
            const missing = !insightById.has(c.insight_id) && !c.insight_id.startsWith("metric-move::");
            // An angle can be a whole question; the meta keeps one line and the title keeps the rest.
            const meta = [c.domain, missing ? "no longer in the findings" : c.angle].filter(Boolean).join(" · ");
            const open = (el: HTMLElement) => onOpen(c, el.getBoundingClientRect());
            return (
              <li key={c.ref}>
                <div role="button" tabIndex={0}
                  className={`aug-apparatus-note${activeRef === c.ref ? " aug-apparatus-note-on" : ""}`}
                  onClick={e => open(e.currentTarget)}
                  onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(e.currentTarget); } }}>
                  <span className="aug-apparatus-n">{c.ref}</span>
                  <span className="aug-apparatus-body">
                    <span className="aug-apparatus-text">{normalizeNumberPrecision(c.finding)}</span>
                    <span className="aug-apparatus-meta" title={[c.domain, c.angle].filter(Boolean).join(" · ")}>{meta}</span>
                  </span>
                </div>
              </li>
            );
          })}
        </ol>
      )}

      <div className="aug-apparatus-sig">
        <span className="aug-brief-eyebrow">{signed ? "Signature" : "Signature · not signed"}</span>
        {signed ? (
          <>
            <p className="aug-apparatus-sig-text">{sigText}</p>
            {(passed > 0 || confound > 0) && (
              <div className="aug-apparatus-guards">
                {passed > 0 && (
                  <GuardChip verdict="passed" title="Cited findings the trust gate did not flag">plausible {passed}</GuardChip>
                )}
                {confound > 0 && (
                  <GuardChip verdict="warned" title="Cited findings the trust gate flagged as a possible confound">confound {confound}</GuardChip>
                )}
              </div>
            )}
          </>
        ) : (
          <p className="aug-apparatus-sig-text">Nothing is signed until the brief is written.</p>
        )}
      </div>
    </aside>
  );
}

// ── Loading state — the brief's own shape, waiting on real data ─────────────────────────────
/** First load: the verdict, the moved numbers, the prose and the apparatus in shape, so nothing
 *  jumps when the findings land. No spinner. */
function BriefingLoading() {
  return (
    <div className="aug-brief-scroll" aria-busy="true" aria-label="Reading the findings">
      <div className="aug-brief">
        <div className="aug-brief-cols">
          <div className="aug-brief-main">
            <BriefSection mark="01">
              <div className="aug-brief-measure aug-brief-skel">
                <div className="aug-skeleton" style={{ width: 120 }} />
                <div className="aug-skeleton aug-brief-skel-h1" style={{ width: "72%" }} />
                <div className="aug-skeleton" style={{ width: "94%" }} />
                <div className="aug-skeleton" style={{ width: "57%" }} />
              </div>
            </BriefSection>
            <BriefSection mark="§1"><SkeletonRows rows={4} /></BriefSection>
            <BriefSection mark="§2">
              <div className="aug-brief-measure aug-brief-skel">
                {["98%", "95%", "99%", "62%"].map((w, i) => <div key={i} className="aug-skeleton" style={{ width: w }} />)}
              </div>
            </BriefSection>
          </div>
          <aside className="aug-apparatus" aria-hidden>
            <div className="aug-apparatus-head"><span className="aug-brief-eyebrow">Apparatus</span></div>
            <div className="aug-apparatus-notes aug-brief-skel">
              {["88%", "70%", "80%"].map((w, i) => <div key={i} className="aug-skeleton" style={{ width: w }} />)}
            </div>
          </aside>
        </div>
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
  onHead,
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
  /** The shell draws this layer's header: when the brief was written, and its actions. */
  onHead?: (head: BriefHead | null) => void;
}) {
  const [briefing, setBriefing]             = useState<BriefingData | null>(null);
  const [pinnedRefresh, setPinnedRefresh]   = useState(0);
  // The ask side panel. Closed by default — the brief is the page; asking is a mode
  // you enter, and an always-mounted panel would cost every reader ~420px of width.
  const [askOpen, setAskOpen]               = useState(false);
  // Scope chips: narrow the narrative layer (supporting signals + top patterns) to one
  // domain; null = all. The standing cockpit layer is intentionally left unscoped — it's
  // the user's arranged surface, not a per-cycle finding view.
  const [scope, setScope]                   = useState<string | null>(null);
  const [loading, setLoading]               = useState(false);
  const [error, setError]                   = useState<string | null>(null);
  const [narrative, setNarrative]           = useState<BriefingNarrativeResponse | null>(null);
  const [narrativeLoading, setNarrativeLoading] = useState(false);
  const [narrativeError, setNarrativeError] = useState<string | null>(null);
  // Whether the brief in flight was asked for (Regenerate) or is the cached one being opened —
  // the screen says "being written" only when it is.
  const [narrativeForced, setNarrativeForced] = useState(false);
  // One open citation at a time, wherever it was opened from — a superscript in the prose or its
  // note in the apparatus — and the inline investigation a citation can pull.
  const [activeCitation, setActiveCitation] = useState<{ citation: BriefingCitation; x: number; y: number } | null>(null);
  const [thread, setThread] = useState<{ question: string; seedSql: string | null; seedContext: string; key: string } | null>(null);
  const openCitation = useCallback((citation: BriefingCitation, anchor: DOMRect) =>
    setActiveCitation({ citation, x: anchor.left, y: anchor.bottom }), []);
  // The scope this panel is currently rendering. Mirrors the server's `scope_key` EXACTLY
  // (`canvas:<id>` | `<conn>:<schema>` | `<conn>`) so a returned brief can be checked
  // against it — see the scope guard in `generateNarrative`.
  const narrativeScope = canvasId ? `canvas:${canvasId}` : (schema ? `${connectionId}:${schema}` : connectionId);
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
  // The label of the action dispatched but not yet VISIBLE in the status ("Starting…").
  // Measured: the POST behind Start answers in 42ms, so a spinner tied to the request
  // lasts 42ms — below perception — while the phase it triggers takes seconds to appear.
  // For ~17s the panel then showed the pre-click state with an enabled Start button, so
  // the only feedback a click produced was none, and clicking again was invited.
  const [explorerPending, setExplorerPending] = useState<string | null>(null);
  // The birth-rite step currently running, from the `birth.step` events the backend
  // already emits. Names the wait instead of leaving it blank.
  const [birthStep, setBirthStep] = useState<string | null>(null);
  // Locked while a request is in flight, while a dispatched action has not yet become
  // visible, AND while a birth rite is running — including one this user did not start
  // (a connection auto-explores on boot). Offering "Start" during a run in progress was
  // itself part of what made the controls feel unreliable.
  const controlsLocked = explorerBusy || !!explorerPending || !!birthStep;
  const [triggers, setTriggers]               = useState<ActionTrigger[]>([]);
  const [evidenceInsight, setEvidenceInsight] = useState<ExplorationInsight | null>(null);
  const [evidenceDomain, setEvidenceDomain]   = useState<string>("");
  // The ledger's jump menu expands + scrolls to a finding, and it scrolls THIS container
  // (never a shell-yanking scrollIntoView).
  const scrollRef = useRef<HTMLDivElement | null>(null);

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
    toast.info("No delivery channel yet", { description: "Add a Slack/webhook trigger in Notifications to share findings." });
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
    const forScope = narrativeScope;
    setNarrativeLoading(true);
    setNarrativeError(null);
    setNarrativeForced(forceRefresh);
    // Drop the OUTGOING brief up front. It belongs to whatever scope was current when it
    // was fetched; from here on the only correct thing to paint is this call's result or
    // an error. Leaving it up is how a previous schema's synthesis ended up rendered under
    // a new schema's verdict (the two are separate state; only the hero re-derived).
    setNarrative(null);
    setActiveCitation(null);
    setThread(null);
    try {
      const result = canvasId
        ? await generateCanvasBriefingNarrative(canvasId, forceRefresh, workspaceId)
        : await generateBriefingNarrative(connectionId, forceRefresh, schema, workspaceId);
      if (myReq !== reqSeq.current) return;   // superseded → don't paint a stale brief (the flip guard)
      // Scope guard: the server stamps the scope it generated FOR. A brief that doesn't
      // claim THIS scope is never painted — that makes a cross-scope leak structurally
      // impossible rather than merely unlikely. (Briefs cached before `scope_key` existed
      // carry none; those are refused too and simply regenerate.)
      if (result.available && result.scope_key && result.scope_key !== forScope) {
        setNarrativeError("This briefing was generated for a different scope — regenerating.");
        return;
      }
      if (result.available) setNarrative(result);
      else setNarrativeError("No domain intelligence available — run an exploration first.");
    } catch (e) {
      if (myReq === reqSeq.current) setNarrativeError(e instanceof Error ? e.message : "Failed to generate narrative");
    } finally {
      if (myReq === reqSeq.current) setNarrativeLoading(false);
    }
  }, [connectionId, canvasId, schema, workspaceId, narrativeScope]);

  // Shared explorer actions — used by both the control bar and the empty-state CTA.
  // In canvas mode (canvasId set) every action drives the *canvas* explorer, scoped to
  // the canvas's curated tables (#7) — not the underlying connection.
  //
  // Two failure modes these must NOT swallow (both made the buttons read as dead):
  //  1. The backend refuses politely with HTTP 200 + {ok:false, reason} ("already
  //     running", "phases 3-7 not complete", "connection not ready") — only thrown
  //     errors ever reached the catch, so a refusal changed nothing on screen.
  //  2. Nothing re-polled status after a click — the 60s fallback interval was the
  //     only guarantee of visible change when kernel events are quiet.
  // `pollRef` is filled by the status-poll effect below; actions call it on completion.
  const pollRef = useRef<() => Promise<ExplorerStatus | null>>(async () => null);

  // Wait for a dispatched action to become VISIBLE, holding the pending label meanwhile.
  //
  // The old sequence polled once, immediately, and that poll almost always lost: the POST
  // returns as soon as the job is accepted, before the phase moves, so the refresh spent
  // on the click re-read the state the click was meant to change. Nothing polled again
  // until a kernel event or the 60s fallback — measured at 17 seconds of a screen
  // identical to the one before the click.
  //
  // So poll on a backoff until the phase differs from what it was, then hand back to the
  // event path. The cap matters: an action whose phase never moves must not pin the
  // controls forever, so after it the buttons return to the live status even if that
  // status is unchanged. `seq` guards against a second click racing the first.
  const confirmSeq = useRef(0);
  const confirmAction = useCallback(async (label: string, phaseBefore: string | null) => {
    const seq = ++confirmSeq.current;
    setExplorerPending(label);
    const backoff = [300, 500, 800, 1200, 1800, 2500, 3000, 3000, 3000, 3000, 3000, 3000];
    for (const wait of backoff) {
      await new Promise(r => setTimeout(r, wait));
      if (confirmSeq.current !== seq) return;      // superseded by a newer action
      const s = await pollRef.current();
      if (confirmSeq.current !== seq) return;
      if ((s?.phase ?? null) !== phaseBefore) break;
    }
    if (confirmSeq.current === seq) setExplorerPending(null);
  }, []);

  /** Surface a 200-level refusal — strictly `ok === false`, because the canvas
   *  endpoints answer {status:"started"} with no `ok` at all (and fail by throwing).
   *  Trigger-intel fans out per schema and reports {results:[{schema, ok, reason}]} —
   *  show the first failing schema's reason. */
  /** Shows the refusal, and REPORTS it: a refused action started nothing, so its caller
   *  must not then wait for a phase change that is never coming. */
  const surfaceRefusal = useCallback(
    (res: { ok?: boolean; status?: string; reason?: string; results?: { schema?: string | null; ok: boolean; reason?: string }[] }, fallback: string): boolean => {
      if (res.ok !== false) return false;
      const failed = res.results?.find(r => !r.ok);
      const reason = res.reason ?? failed?.reason;
      const scope = failed?.schema ? `[${failed.schema}] ` : "";
      setExplorerError(reason ? `${scope}${reason}` : fallback);
      return true;
    }, []);

  const runExplorer = useCallback(async () => {
    if (!canvasId && !connectionId) { setExplorerError("No connection selected"); return; }
    const before = explorerStatus?.phase ?? null;
    setExplorerBusy(true);
    setExplorerError(null);
    try {
      const res = canvasId ? await resumeCanvasExploration(canvasId)
                           : await startExplorer(connectionId, schema);
      if (surfaceRefusal(res, "The explorer did not start")) { setExplorerBusy(false); return; }
    } catch (e) {
      setExplorerError(e instanceof Error ? e.message : "Could not start the explorer");
      setExplorerBusy(false);
      return;                          // nothing started, so nothing to wait to become visible
    }
    setExplorerBusy(false);
    confirmAction("Starting…", before);
  }, [connectionId, canvasId, schema, surfaceRefusal, explorerStatus?.phase, confirmAction]);

  /** Does this connection already hold findings? — the discriminator the explorer control
   *  bar keys on, replacing `phase === "complete"`.
   *
   *  A phase is the verdict of the LAST run; findings are the accumulated result of every
   *  run. Those come apart exactly when it matters: a run that fails after (or on top of)
   *  a successful one leaves a full briefing behind a phase that says failed, and keying
   *  the controls on the phase then hides the only two actions that make sense.
   *
   *  `facts_discovered` rather than the findings count: it is the superset (findings plus
   *  mapped lifecycles), so a run that verified structure without landing a finding still
   *  has a body of work worth extending — and "is there anything here at all" is the
   *  question these controls actually turn on. */
  const hasFindings = (explorerStatus?.facts_discovered ?? 0) > 0;

  const runTriggerIntel = useCallback(async () => {
    if (!canvasId && !connectionId) { setExplorerError("No connection selected"); return; }
    const before = explorerStatus?.phase ?? null;
    setExplorerBusy(true);
    setExplorerError(null);
    try {
      const res = canvasId ? await triggerCanvasDomainIntelligence(canvasId)
                           : await triggerDomainIntelligence(connectionId);
      if (surfaceRefusal(res, "Intelligence did not trigger")) { setExplorerBusy(false); return; }
    } catch (e) {
      setExplorerError(e instanceof Error ? e.message : "Could not trigger intelligence");
      setExplorerBusy(false);
      return;
    }
    setExplorerBusy(false);
    confirmAction("Triggering…", before);
  }, [connectionId, canvasId, surfaceRefusal, explorerStatus?.phase, confirmAction]);

  // One-click refresh: clears stale findings and re-runs the full pipeline under the
  // current (corrected) explorer — drops "no data" / cross-dataset findings, re-anchors
  // the temporal window. The honest way to make a stale headline reliable + up to date.
  const runRefresh = useCallback(async () => {
    if (!canvasId && !connectionId) { setExplorerError("No connection selected"); return; }
    const before = explorerStatus?.phase ?? null;
    setExplorerBusy(true);
    setExplorerError(null);
    try {
      const res = canvasId ? await restartCanvasExploration(canvasId)
                           : await restartExplorer(connectionId);
      if (surfaceRefusal(res, "The refresh did not start")) { setExplorerBusy(false); return; }
    } catch (e) {
      setExplorerError(e instanceof Error ? e.message : "Refresh failed");
      setExplorerBusy(false);
      return;
    }
    setExplorerBusy(false);
    confirmAction("Refreshing…", before);
  }, [connectionId, canvasId, surfaceRefusal, explorerStatus?.phase, confirmAction]);

  const runStop = useCallback(async () => {
    if (!canvasId && !connectionId) { setExplorerError("No connection selected"); return; }
    const before = explorerStatus?.phase ?? null;
    setExplorerBusy(true);
    setExplorerError(null);
    try {
      const res = canvasId ? await stopCanvasExploration(canvasId)
                           : await stopExplorer(connectionId);
      if (surfaceRefusal(res, "The explorer did not stop")) { setExplorerBusy(false); return; }
    } catch (e) {
      setExplorerError(e instanceof Error ? e.message : "Stop failed");
      setExplorerBusy(false);
      return;
    }
    setExplorerBusy(false);
    confirmAction("Stopping…", before);
  }, [connectionId, canvasId, surfaceRefusal, explorerStatus?.phase, confirmAction]);

  useEffect(() => { load(); }, [load]);

  // Auto-fetch the cached narrative on mount and whenever the scope (connection or
  // shared schema) changes. Guard on the scope we last fetched — not on `narrative
  // !== null` — so a schema switch actually re-fetches instead of keeping the old one.
  useEffect(() => {
    if (!canvasId && !connectionId) return;
    // WP-5 — wait for the shared schema selector to settle before the first connection-scoped
    // fetch, so we never issue an unscoped briefing request that then races the scoped one.
    if (!canvasId && !schemaReady) return;
    if (narrativeScope === fetchedScope.current) return;
    fetchedScope.current = narrativeScope;
    generateNarrative(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionId, canvasId, schema, schemaReady, narrativeScope]);

  // Poll explorer status — canvas-scoped when a canvasId is set (#7), so the control
  // bar + empty-state reflect the *canvas* explorer's phase, not the connection's.
  useEffect(() => {
    const scopeId = canvasId || connectionId;
    if (!scopeId) return;
    let mounted = true;
    // Returns what it read, so an action can wait for its OWN effect to become visible
    // instead of firing one poll that races the backend and loses.
    const poll = () => {
      const req = canvasId ? getCanvasExplorationStatus(canvasId) : getExplorerStatus(connectionId, schema);
      return req
        .then(s => { if (mounted) setExplorerStatus(s); return s; })
        .catch(() => { if (mounted) setExplorerStatus(null); return null; });
    };
    pollRef.current = poll;   // let the action handlers refresh status immediately
    poll();
    // The subscription fires the callback ONCE PER EVENT, and events arrive in bursts —
    // a single kernel tick was measured issuing NINE identical status requests in the
    // same millisecond. Coalesce them: a burst schedules one refresh, not one each.
    let burst: ReturnType<typeof setTimeout> | null = null;
    const coalescedPoll = () => {
      if (burst !== null) return;
      burst = setTimeout(() => { burst = null; poll(); }, 120);
    };
    // K2: phase-change events drive this; the interval is only a slow fallback
    // (was a 3s poll — the worst offender of the seven).
    const iv = setInterval(poll, 60_000);
    // `birth.` is subscribed because the backend ALREADY narrates this wait and nobody
    // was listening. A Start hands off to the birth rite, which runs two preparatory
    // steps before exploration begins — measured at 7.6s (intelligence) and 8.9s
    // (popularity, 4,785 queries over 38 tables). Only after both does the first
    // `exploration.phase` arrive, which is the ONLY thing this panel used to react to.
    // So ~16.5s of real, named work looked like a hang. The events carry `step` and a
    // started/done status; showing them costs nothing and changes the wait from
    // "nothing is happening" to "this is what is happening".
    const unsub = subscribeKernelEvents(ev => {
      if (ev.kind === "birth.step" || ev.kind === "birth.done") {
        const p = (ev.payload ?? {}) as { step?: string; status?: string; schema?: string | null };
        // Events for a sibling schema must not narrate THIS panel's wait.
        const sameScope = !schema || !p.schema || p.schema === schema;
        if (sameScope) {
          if (ev.kind === "birth.done") setBirthStep(null);
          else if (p.status === "started" && p.step) setBirthStep(p.step);
        }
      }
      coalescedPoll();
    }, {
      kinds: ["exploration.", "job.state", "birth."],
      ...(canvasId ? { canvasId } : { connId: connectionId }),
    });
    return () => {
      mounted = false;
      clearInterval(iv);
      if (burst !== null) clearTimeout(burst);
      unsub();
    };
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
    { id: "brief-regen",   label: "Regenerate briefing", sublabel: "Re-synthesize the intelligence briefing",        icon: "spark",   accent: "var(--blue3)", keywords: "regenerate refresh brief narrative synthesis",  run: () => regenRefCmd.current(true) },
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

  // The cockpit's suggested pins: the top findings (headline excluded) that yield a key figure, in
  // impact order. Every figure is quoted from a grounded finding statement — never invented.
  const movers = useMemo<SuggestedPin[]>(() => {
    if (!briefing) return [];
    const headlineId = briefing.headline ? signalIdentity(briefing.headline.insight) : null;
    const ranked = dedupeSignals([...briefing.signals, ...briefing.allSignals])
      .filter(s => signalIdentity(s.insight) !== headlineId);
    const out: SuggestedPin[] = [];
    for (const s of ranked) {
      const fig = extractKeyFigure(s.insight.finding);
      if (!fig) continue;
      out.push({ insightId: s.insight.id, value: fig.value, label: fig.sublabel || s.domain });
      if (out.length >= 3) break;
    }
    return out;
  }, [briefing]);

  // The ledger holds every finding in scope. The one exception is the top finding while no brief
  // is written: it IS the verdict's title then, and printing it twice helps no one.
  const hasNarrative   = !!narrative?.narrative;
  const scopedSignals  = !briefing
    ? []
    : dedupeSignals(
        scopeDomain
          ? briefing.allSignals.filter(s => s.domain === scopeDomain)
          : [...briefing.signals, ...briefing.allSignals],
      ).filter(s => hasNarrative || signalIdentity(s.insight) !== headlineIdent);
  const scopedPatterns = !briefing
    ? []
    : scopeDomain
      ? briefing.patterns.filter(p => p.domains?.includes(scopeDomain))
      : briefing.patterns;

  const hasPatterns    = scopedPatterns.length > 0;
  const isEmpty        = !briefing || briefing.totalInsights === 0;

  // Saved chart display per finding, for every card-less chart in the brief (the ledger's rows).
  // Scoped exactly like the narrative, so one schema's edits never show up under another's.
  // Pinned cards persist their own display in `card.render` instead.
  const { configFor: vizConfigFor, save: saveVizConfigFor } = useVizConfigs(narrativeScope);

  // PX-6 — the scheduled-delivery card, toggled from the control bar.
  const [showSchedule, setShowSchedule] = useState(false);

  // §1 — the north-star metrics, each read for its latest move (the KPI tiles' queries, moved up).
  const moves = useNorthStarMoves(connectionId, schema);

  // The header the shell draws for this layer. The actions go through a ref so the effect re-runs
  // only when what the header SHOWS changes, not on every render's fresh closures.
  const headActions = useRef({ regenerate: () => {}, investigate: () => {} });
  useEffect(() => {
    headActions.current.regenerate = () => { void generateNarrative(!!narrative?.narrative); };
    headActions.current.investigate = () => {
      const h = briefing?.headline;
      if (h) onInvestigate(`Investigate: ${h.insight.finding}`, h.insight.id);
    };
  });
  const headlineFinding = briefing?.headline?.insight.finding ?? null;
  const headPending: BriefHead["pending"] = narrativeLoading ? (narrativeForced ? "writing" : "opening") : null;
  useEffect(() => {
    onHead?.({
      generatedAt: narrative?.generated_at ?? null,
      pending: headPending,
      hasNarrative,
      empty: !loading && isEmpty,
      regenerate: () => headActions.current.regenerate(),
      investigate: headlineFinding
        ? { label: normalizeNumberPrecision(headlineFinding), run: () => headActions.current.investigate() }
        : null,
    });
  }, [onHead, narrative?.generated_at, headPending, hasNarrative, loading, isEmpty, headlineFinding]);
  useEffect(() => () => onHead?.(null), [onHead]);

  if (loading) return <BriefingLoading />;

  if (error) {
    return (
      <div className="aug-brief-pad" style={{ flex: 1 }}>
        <ErrorState kind="Briefing failed" what={error}
          means="The findings for this scope could not be read, so there is no brief to show."
          doors={[{ label: "Reload", onClick: () => { void load(); }, primary: true }]} />
      </div>
    );
  }

  // What the brief says, split for its sections.
  const { lede, depth } = splitLede(hasNarrative ? narrative?.narrative ?? "" : "");
  const theme        = normalizeNumberPrecision(narrative?.headline_theme?.trim());
  const topFinding   = normalizeNumberPrecision(briefing?.headline?.insight.finding?.trim());
  const verdictTitle = (hasNarrative && theme) || topFinding || "Intelligence briefing";
  const citations    = hasNarrative && narrative ? narrative.citations : [];
  const pendingWord  = narrativeForced ? "being written" : "opening";
  const verdictMeta  = briefing
    ? [
        countNoun(briefing.domainCount, "domain"),
        countNoun(briefing.totalInsights, "finding"),
        briefing.queriesUsed > 0 ? countNoun(briefing.queriesUsed, "query", "queries") : "",
      ].filter(Boolean).join(" · ")
    : "";
  const movePeriods = [...new Set(moves.rows.map(r => r.period).filter((x): x is string => !!x))];
  const movesMeta = moves.status === "ready"
    ? [moves.industry, movePeriods.length === 1 ? `latest against ${periodWord(movePeriods[0])}` : "latest period against the one before"]
        .filter(Boolean).join(" · ")
    : undefined;
  const showWhy      = narrativeLoading || depth.length > 0;
  const showFindings = scopedSignals.length > 0 || (briefing?.domains.length ?? 0) > 1;
  let sectionNo = 0;
  const mark = () => `§${++sectionNo}`;
  const narrativeProps: NarrativeProps = { citations, onCitationClick: openCitation, connectionId, schema };
  const citationCtx: CitationActionContext | null = briefing
    ? {
        insightById: briefing.insightById, connectionId, canvasId, schema, triggers,
        onEvidence: openEvidence, onTriggersHint: showTriggersHint, onDismissed: load, onInvestigate,
      }
    : null;
  const threadEl = thread ? (
    <InlineInvestigationThread
      key={thread.key}
      question={thread.question}
      opts={{
        connectionId, schema: schema ?? null, canvasId: canvasId ?? null,
        seedSql: thread.seedSql, seedContext: thread.seedContext,
        insightId: thread.key,  // the citation's insight id — seeds the rich dossier when present
      }}
      onClose={() => setThread(null)}
      onOpenInAsk={onInvestigate}
    />
  ) : null;

  return (
    // Row, not a column: the ask panel is a fixed-width SIBLING that pushes the brief left
    // rather than overlaying it — the whole point is reading an answer against the brief it
    // is about. (Same shape as ChatPanel's source drawer.) The brief keeps its own scroller.
    <div style={{ flex: 1, display: "flex", minHeight: 0, minWidth: 0 }}>
    <div ref={scrollRef} className="aug-brief-scroll">

      {/* Evidence drill-through drawer (finding actions, #4). Transient hints/side-effect
          feedback now go through the shared <Toaster/> (toast.*), mounted in the root layout. */}
      <EvidenceDrawer insight={evidenceInsight} domain={evidenceDomain} connectionId={connectionId} onClose={() => setEvidenceInsight(null)} />

      {activeCitation && citationCtx && (
        <CitationActionsPopover
          citation={activeCitation.citation} x={activeCitation.x} y={activeCitation.y} ctx={citationCtx}
          onPull={(t) => { setThread(t); setActiveCitation(null); }}
          onClose={() => setActiveCitation(null)}
        />
      )}

      {/* ── Explorer control bar ── demoted to a thin machinery strip: it explains where the
          brief comes from, but it isn't content. Single hairline row, mono --t4. */}
      <div className="aug-brief-strip">
        <span style={{ fontSize: 11, color: "var(--t3)", fontFamily: "var(--font-mono)", letterSpacing: ".08em", textTransform: "uppercase" }}>
          Explorer
        </span>
        {explorerStatus ? (
          <>
            <span className="aug-fs-xs" style={{
              color: explorerStatus.paused ? "var(--amb4)" : {
                good: "var(--grn4)", warn: "var(--amb4)",
                bad: "var(--red4)", busy: "var(--blue4)",
              }[explorerPhaseLabel(explorerStatus.phase, hasFindings).tone],
              fontWeight: 500,
            }}>
              {explorerPhaseLabel(explorerStatus.phase, hasFindings).text}
              {explorerStatus.paused && " (paused)"}
            </span>
            {/* A terminal phase with work behind it must say BOTH. "failed" alone is what
                sent a reader to "I may have to start afresh" while 54 findings and a
                grounded briefing sat on the same screen — the phase is the verdict of the
                LAST run, not of the body of work, and those come apart exactly when a run
                fails on top of a successful one.

                No count: the scope bar above already carries it, and the status's own
                figure counts something slightly different, so a second number here would
                invite the reader to reconcile two things that were never the same. */}
            {explorerStatus.phase === "failed" && hasFindings && (
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                · the last run stopped short; earlier findings are kept
              </span>
            )}
            {/* No run counters here: queries_executed is the CURRENT run's number while
                insights_found is lifetime, so "1q · 22 findings" read as broken history —
                and either way it is machinery, not business content. */}
          </>
        ) : (
          <span style={{ fontSize: 11, color: "var(--t3)" }}>unknown</span>
        )}
        {explorerError && (
          <GuardChip verdict="refused" title={explorerError}>
            {explorerError.length > 60 ? explorerError.slice(0, 60) + "…" : explorerError}
          </GuardChip>
        )}
        {/* A dispatched action, named, until the status shows it. Without this the only
            feedback a click produced was a 42ms disabled flicker followed by seconds of
            an unchanged screen — indistinguishable from a dead button. */}
        {(explorerPending || birthStep) && (
          <span style={{ fontSize: 11, color: "var(--blue4)", fontWeight: 500 }}>
            {birthStep ? (BIRTH_STEP_LABELS[birthStep] ?? `${birthStep}…`) : explorerPending}
          </span>
        )}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {(!explorerStatus || explorerStatus.phase === "complete" || explorerStatus.phase === "pending" || explorerStatus.phase === "failed") ? (
            <>
              {/* "Start" only when starting is the honest verb — nothing has run yet.
                  A completed run already has findings on screen behind these controls,
                  and offering to start one implies none exists; the two things you can
                  actually do to it are add intelligence or redo it, which is what
                  Trigger Intel and Refresh are. `runRefresh` IS the restart
                  (`restartExplorer`), so Start alongside it was also a duplicate.
                  This is the taxonomy `BriefingEmpty` already uses one level down —
                  "Start exploration" for never, "Restart exploration" for failed —
                  which the control bar was contradicting. */}
              {/* 🔴 These keyed on `phase === "complete"`, which contradicted the very
                  taxonomy described above. A run that FAILED after producing findings —
                  or, as seen live, a later run that failed on top of an earlier
                  successful one — kept 54 findings and a grounded briefing on screen
                  while the control bar offered only "Start". Trigger Intel and Refresh,
                  the two things the comment says you can actually do to a body of
                  findings, were both hidden precisely when someone would reach for them.

                  The honest discriminator is not the phase, it is whether there ARE
                  findings: "offering to start one implies none exists" is exactly as
                  true for a failed run with 54 of them. So `hasFindings` decides, and
                  the phase decides only the VERB — Start when nothing has ever run,
                  Restart when something ran and did not finish. */}
              {!hasFindings && (
                <Button
                  variant="secondary" size="xs"
                  disabled={controlsLocked} onClick={runExplorer}
                >{explorerPending === "Starting…" ? "Starting…"
                  : explorerStatus?.phase === "failed" ? "Restart" : "Start"}</Button>
              )}
              {hasFindings && (
                <Button
                  variant="secondary" size="xs"
                  disabled={controlsLocked} onClick={runTriggerIntel}
                >{explorerPending === "Triggering…" ? "Triggering…" : "Trigger Intel"}</Button>
              )}
              {hasFindings && (
                <Button
                  variant="secondary" size="xs"
                  disabled={controlsLocked} onClick={runRefresh}
                  title="Clear stale findings and re-run intelligence from scratch (drops 'no data' findings, re-anchors the window)"
                >{explorerPending === "Refreshing…" ? "Refreshing…" : "↻ Refresh"}</Button>
              )}
            </>
          ) : (
            <>
              <Button
                variant="secondary" size="xs"
                disabled={controlsLocked} onClick={runStop}
              >{explorerPending === "Stopping…" ? "Stopping…" : "Stop"}</Button>
              <Button
                variant="secondary" size="xs"
                disabled={controlsLocked} onClick={runRefresh}
              >{explorerPending === "Refreshing…" ? "Refreshing…" : "Restart"}</Button>
            </>
          )}
          {/* PX-6 — the scheduled-delivery door (five wrappers, zero callers until now). */}
          <Button variant={showSchedule ? "secondary" : "ghost"} size="xs"
            onClick={() => setShowSchedule(s => !s)}>Schedule</Button>
        </div>
      </div>

      {showSchedule && <div className="aug-brief-pad"><BriefSchedule connId={connectionId} /></div>}

      {isEmpty || !briefing ? (
        <div className="aug-brief-pad">
          <BriefingEmpty
            status={explorerStatus}
            // Its CTA already renders a spinner + "Working…" on `busy`; the bug was that
            // `explorerBusy` tracked only the 42ms request, so that state was never seen.
            // Holding it through the pending window is the whole fix for this surface.
            busy={controlsLocked}
            onStart={runExplorer}
            onTrigger={runTriggerIntel}
            canvasId={canvasId}
          />
        </div>
      ) : (
        <div className="aug-brief">
          <div className="aug-brief-cols">
            <div className="aug-brief-main">

              {/* 01 — the verdict. The title is the narrator's theme and the lede its opening
                  paragraph, superscripts and all. Without a written brief the top finding leads,
                  and the eyebrow says that is what it is. */}
              <BriefSection mark="01">
                <div className="aug-brief-measure">
                  <div className="aug-brief-eyebrow-row">
                    {narrativeLoading && <span className="aug-dot aug-dot-analysing" aria-hidden />}
                    <span className={`aug-brief-eyebrow${narrativeLoading ? " aug-brief-writing" : ""}`}>
                      {narrativeLoading ? `Verdict · ${pendingWord}` : hasNarrative ? "Verdict" : "Top finding"}
                    </span>
                    <span className="aug-brief-meta">{verdictMeta}</span>
                  </div>
                  {narrativeLoading ? (
                    <div className="aug-brief-skel" aria-busy="true" aria-label={`The verdict is ${pendingWord}`}>
                      <div className="aug-skeleton aug-brief-skel-h1" style={{ width: "74%" }} />
                      <div className="aug-skeleton" style={{ width: "96%" }} />
                      <div className="aug-skeleton" style={{ width: "61%" }} />
                    </div>
                  ) : (
                    <>
                      <h1 className="aug-brief-verdict">{verdictTitle}</h1>
                      {hasNarrative && lede && (
                        <p className="aug-brief-lede"><NarrativeText text={lede} {...narrativeProps} /></p>
                      )}
                    </>
                  )}
                  {!narrativeLoading && narrativeError && (
                    <div className="aug-brief-doors">
                      <ErrorState kind="Synthesis failed" what={narrativeError}
                        means="The findings below are unaffected; only the written verdict is missing." />
                    </div>
                  )}
                  <div className="aug-brief-doors">
                    {!askOpen && (
                      <Button variant="secondary" size="xs" onClick={() => setAskOpen(true)}
                        title="Quick answers, scoped to this brief and its schema">
                        Ask this briefing
                      </Button>
                    )}
                    {briefing.headline && (
                      <>
                        {(hasNarrative || narrativeLoading) && <span className="aug-brief-meta">top finding</span>}
                        <FindingActions
                          insight={briefing.headline.insight} domain={briefing.headline.domain}
                          connectionId={connectionId} canvasId={canvasId} schema={schema} triggers={triggers}
                          overflow
                          onEvidence={(ins) => openEvidence(ins, briefing.headline!.domain)}
                          onTriggersHint={showTriggersHint} onDismissed={() => load()}
                          onPinned={() => setPinnedRefresh(n => n + 1)} />
                      </>
                    )}
                  </div>
                  {!showWhy && threadEl}
                </div>
              </BriefSection>

              {/* §1 — the numbers that moved (MovedNumbers says what it leaves out, and why). */}
              <BriefSection mark={mark()}>
                <SectionHead title="The numbers that moved" meta={movesMeta} />
                {moves.status === "none" ? (
                  <p className="aug-brief-note">
                    No north-star metrics are defined for this connection, so nothing is watched for movement.
                    They are set in the connection&apos;s business profile.
                  </p>
                ) : moves.status === "loading" ? (
                  <SkeletonRows rows={3} />
                ) : (
                  <MovedNumbers rows={moves.rows} scopeKey={narrativeScope} />
                )}
              </BriefSection>

              {/* §2 — why: the narrator's paragraphs of depth. No prose is drawn until there is
                  prose; the skeleton only holds its place. */}
              {showWhy && (
                <BriefSection mark={mark()}>
                  <SectionHead title="Why" meta={narrativeLoading
                    ? <span className="aug-brief-writing">{narrativeForced ? "the narrator is writing — no prose until it is done" : "opening the brief"}</span>
                    : `${countNoun(citations.length, "note")} in the apparatus`} />
                  {narrativeLoading ? (
                    <div className="aug-brief-measure aug-brief-skel" aria-busy="true">
                      {["97%", "99%", "93%", "58%"].map((w, i) => <div key={i} className="aug-skeleton" style={{ width: w }} />)}
                    </div>
                  ) : (
                    <div className="aug-brief-measure aug-brief-prose">
                      {depth.map((para, i) => <p key={i}><NarrativeText text={para} {...narrativeProps} /></p>)}
                    </div>
                  )}
                  {threadEl}
                </BriefSection>
              )}

              {/* §3 — findings: every finding in scope, one row each, its chart on expand. */}
              {showFindings && (
                <BriefSection mark={mark()}>
                  <SectionHead title="Findings"
                    meta={`${countNoun(scopedSignals.length, "finding")}${scopeDomain ? ` in ${scopeDomain}` : ""} · ranked by impact`} />
                  <ScopeChips domains={briefing.domains} total={briefing.totalInsights} active={scopeDomain} onChange={setScope} />
                  <FindingsLedger key={scopeDomain ?? "all"} signals={scopedSignals} connectionId={connectionId}
                    onInvestigate={onInvestigate} onEvidence={openEvidence} scrollRef={scrollRef}
                    vizConfigFor={vizConfigFor} onVizConfigChange={saveVizConfigFor} />
                </BriefSection>
              )}

              {/* §4 — the cockpit: the user's own cards, which outlive any one brief. */}
              <BriefSection mark={mark()}>
                <SectionHead title="Your cockpit" meta="cards you pinned — they stay when the brief changes" />
                <NewCardComposer connectionId={connectionId} schema={schema}
                  onCreated={() => setPinnedRefresh(n => n + 1)} />
                <PinnedCards connectionId={connectionId} schema={schema} refreshKey={pinnedRefresh}
                  suggestions={movers}
                  onPinned={() => setPinnedRefresh(n => n + 1)}
                  onOpenSource={(iid) => onInvestigate("Investigate this finding", iid)}
                  onEvidence={(iid) => { const sig = briefing.insightById.get(iid); if (sig) openEvidence(sig.insight, sig.domain); }} />
              </BriefSection>

              {/* §5 — patterns across domains. */}
              {hasPatterns && (
                <BriefSection mark={mark()}>
                  <SectionHead title="Patterns" meta={`${countNoun(scopedPatterns.length, "pattern")} across domains`} />
                  <div style={{ display: "flex", flexDirection: "column" as const, gap: 6 }}>
                    {scopedPatterns.map(pt => (
                      <PatternRow key={pt.id} pattern={pt} onInvestigate={onInvestigate} />
                    ))}
                  </div>
                </BriefSection>
              )}
            </div>

            {/* The apparatus gives way to the ask panel: reading an answer against the brief needs
                the width more than the notes do, and every note stays one superscript away. */}
            {!askOpen && (
              <ApparatusRail
                citations={citations}
                pending={headPending}
                hasNarrative={hasNarrative}
                narrativeText={narrative?.narrative ?? ""}
                insightById={briefing.insightById}
                activeRef={activeCitation?.citation.ref ?? null}
                onOpen={openCitation}
              />
            )}
          </div>
        </div>
      )}
    </div>

      {askOpen && (
        <BriefAskPanel
          connectionId={connectionId}
          schema={schema}
          canvasId={canvasId}
          onClose={() => setAskOpen(false)}
          onOpenInAsk={onInvestigate}
        />
      )}
    </div>
  );
}
