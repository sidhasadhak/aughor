"use client";

/**
 * Deep Analysis report, rendered as a clean Brief.
 *
 * Same vocabulary as the Insight answer (headline → prose → framed figures) —
 * Deep Analysis is just the LONG version. The old accordion-in-accordion, the
 * confidence/total/controllable pills, and the border-on-every-section are gone:
 * phases are flat narrative sections. Clean-output policy (Genie report study):
 * the investigation machinery (confidence factors, attribution, data gaps,
 * question intake, the SQL Sources list) is NOT rendered here at all — a reader
 * gets conclusions, the per-exhibit Source-data icon + the Evidence tab carry the
 * data/SQL, and only the decision (Recommended actions) stays visible in the flow.
 */

import React, { useState } from "react";
import { Chart } from "@/components/Chart";
import { SqlResultTable } from "@/components/AugTable";
import ChevronDownIcon  from "@atlaskit/icon/core/chevron-down";
import ChevronRightIcon from "@atlaskit/icon/core/chevron-right";
import RetryIcon        from "@atlaskit/icon/core/retry";
import TableIcon        from "@atlaskit/icon/core/table";

/** Open the right-side Source-data drawer (data + SQL + Query Builder) for a finding. Typed inline
 *  (structurally = ChatMessage's SourcePanelData) to avoid a circular import with ChatMessage. */
type ShowSource = (data: { columns: string[]; rows: unknown[][]; sql: string | null; title: string }) => void;
import {
  Brief,
  BriefHeadline,
  BriefProse,
  BriefSection,
  BriefMeta,
  BriefFigure,
  renderEmphasis,
} from "@/components/brief/Brief";
import { TrendStrip } from "@/components/brief/Sparkline";

// ── Types ──────────────────────────────────────────────────────────────────────

interface PhaseKeyNumber {
  label: string;
  value: string;
  delta?: string;
  context?: string;
}

interface InvestigationFinding {
  finding_id: string;
  title: string;
  sql: string;
  columns: string[];
  rows: (string | number | null)[][];
  row_count: number;
  error?: string;
  interpretation: string;
  key_numbers: PhaseKeyNumber[];
  chart_type: string;
  stat_note?: string;
  is_significant: boolean;
  trust_caveat?: string | null;   // advisory from the trust battery — surfaced, never blocking
  column_units?: Record<string, string> | null;  // per-column display unit ({metric_total:"percent"})
  exhibit?: import("@/components/charts/exhibit").ExhibitSpec | null;  // chart-grammar semantics
}

interface InvestigationPhase {
  phase_id: string;
  phase_name: string;
  phase_icon: string;
  status: "complete" | "partial" | "running" | "skipped" | "error";
  summary: string;
  findings: InvestigationFinding[];
  skipped_reason?: string;
  _hidden?: boolean;   // pruned by the relevance pass (nothing that moves the reader) — don't render
}

interface WaterfallEntry {
  cause: string;
  amount_label: string;
  pct_of_total: number;
  controllable: boolean;
  structural: boolean;
}

interface AnswerRecommendation {
  action: string;
  expected_impact: string;
  owner: string;
  timeline: string;
}

export interface AnswerReport {
  headline: string;
  executive_summary: string;
  metric: string;
  observation_period: string;
  comparison_basis: string;
  total_change_label: string;
  phases: InvestigationPhase[];
  attribution_waterfall: WaterfallEntry[];
  confidence: "HIGH" | "MEDIUM" | "LOW";
  confidence_justification: string;
  recommendations: AnswerRecommendation[];
  data_gaps: string[];
  // Phase-2 structural trust artifacts (Orchestrator) — optional; older reports omit them.
  contradiction_report?: {
    severity: string; count: number;
    items: { kind: string; detail: string; phases: string[]; severity: string }[];
  } | null;
  orchestration_plan?: {
    question_kind: string; planned_ids: string[];
    steps: { phase_id: string; phase_name: string; icon: string; disposition: string; reason: string }[];
  } | null;
  plan_reconciliation?: { planned: string[]; actual: string[]; skipped: string[]; unplanned: string[] } | null;
  // T4-1 — plain-language receipt of how the metric was computed (formula + interpretation).
  metric_definition?: string | null;
  // A short closing "bottom line" that lands the answer at the end of the report (before
  // recommendations). Authored by synthesis; older reports omit it.
  closing_summary?: string | null;
}

// ── Collapsible data table — quiet, only when a finding has no chart ───────────

function FindingTable({ columns, rows, label }: { columns: string[]; rows: (string | number | null)[][]; label: string }) {
  const [open, setOpen] = useState(false);
  if (!columns.length || !rows.length) return null;
  return (
    <div>
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 aug-fs-xs text-zinc-500 hover:text-zinc-500 transition-colors"
      >
        {open ? <ChevronDownIcon label="" size="small" /> : <ChevronRightIcon label="" size="small" />}
        {label} · {rows.length} rows
      </button>
      {open && (
        <div className="mt-1.5">
          <SqlResultTable columns={columns} rows={rows as unknown[][]} maxHeight={280} />
        </div>
      )}
    </div>
  );
}

// ── Single finding — evidence block (flows inside a phase section) ─────────────

/* R16 P1 — numbers live in the sentence, not in tiles (the Genie report study:
   a claim reads "**long-haul load factor: 74.5%** (-2.7pt)", it doesn't stack
   stat cards under every chart). One quiet inline line per finding; the R15
   "Opportunity:" key number keeps its hedged context sentence — it IS the
   decision, so it earns the extra clause. Values arrive pre-formatted from the
   backend (no client-side number formatting). */
function KeyNumbersInline({ metrics }: { metrics: PhaseKeyNumber[] }) {
  const clean = (s?: string | null) => (s || "").replace(/\*/g, "");
  const opportunity = metrics.filter(m => clean(m.label).startsWith("Opportunity:"));
  const ordinary = metrics.filter(m => !clean(m.label).startsWith("Opportunity:"));
  if (!metrics.length) return null;
  return (
    <div className="flex flex-col gap-1">
      {ordinary.length > 0 && (
        <p className="aug-fs-ui leading-relaxed text-zinc-300">
          {ordinary.map((m, i) => (
            <span key={i}>
              {i > 0 && <span className="text-zinc-600"> · </span>}
              <strong className="font-semibold">{clean(m.label)}: {clean(m.value)}</strong>
              {m.delta && <span className="text-zinc-500"> ({clean(m.delta)})</span>}
            </span>
          ))}
        </p>
      )}
      {opportunity.map((m, i) => (
        <p key={`opp-${i}`} className="aug-fs-ui leading-relaxed text-zinc-300">
          <strong className="font-semibold">{clean(m.label)}: {clean(m.value)}</strong>
          {m.delta && <span className="text-zinc-500"> ({clean(m.delta)})</span>}
          {m.context && <span className="text-zinc-500">. {clean(m.context)}</span>}
        </p>
      ))}
    </div>
  );
}

/** A brief, human name for a finding's underlying data — labels the source-data icon
 *  (Genie's descriptive "…for viz" footer) instead of an opaque "Source N". The finding
 *  title already says what the exhibit shows; trim it so the chip stays one short line. */
function sourceLabel(title: string): string {
  const t = (title || "").replace(/\*/g, "").trim();
  if (!t) return "Source data";
  return t.length > 46 ? t.slice(0, 46).trimEnd() + "…" : t;
}

function EvidenceBlock({ finding, onShowSource }: { finding: InvestigationFinding; onShowSource?: ShowSource }) {
  const hasData = finding.columns.length > 0 && finding.rows.length > 0;
  const hasChart = hasData && finding.chart_type !== "none" && finding.rows.length >= 2;

  return (
    <div className="flex flex-col gap-2.5">
      {/* Chart — the framed figure */}
      {hasChart && (
        <BriefFigure caption={finding.title}>
          <Chart columns={finding.columns} rows={finding.rows as unknown[][]} title={finding.title} chartType={finding.chart_type} columnUnits={finding.column_units} exhibit={finding.exhibit} showLabels />
        </BriefFigure>
      )}

      {/* Source data — opens the right-side data + SQL + Query Builder drawer (same as the quick answer) */}
      {hasData && onShowSource && (
        <button
          onClick={() => onShowSource({ columns: finding.columns, rows: finding.rows as unknown[][], sql: finding.sql || null, title: finding.title })}
          className="self-end flex items-center gap-1.5 aug-text-xs text-zinc-500 hover:text-zinc-300 transition-colors max-w-full"
          title={`Data + SQL behind “${finding.title}”`}
        >
          <TableIcon label="Table" size="small" />
          {/* Name the source by WHAT it shows (Genie's "…for viz" footer), not an opaque "Source N". */}
          <span className="truncate">{sourceLabel(finding.title)}</span>
        </button>
      )}

      {/* Trend strip — sparkline + period-over-period % (time-series findings only) */}
      <TrendStrip columns={finding.columns} rows={finding.rows} />

      {/* Key numbers — one inline prose line, not a tile row (R16 P1) */}
      {finding.key_numbers.length > 0 && <KeyNumbersInline metrics={finding.key_numbers} />}

      {/* Interpretation narrative */}
      {finding.interpretation && <BriefProse text={finding.interpretation} muted />}

      {/* Significance verdict — "Significant" / "Within noise" + raw stat note */}
      {/* Clean-output policy: the significance verdict + stat note are VERIFICATION
          machinery — they live in the Trust Receipt / Details, never in the body.
          A reader gets conclusions; "Within noise · Only 2 rows returned" is the
          machine talking to itself. */}

      {/* The Trust advisory box is gone from the body — it restated the finding's own
          interpretation (a suppressed finding is now dropped entirely; a repaired one says
          "recomputed against 2.8%" in its interpretation already). It added space, not
          value. The trust caveat still rides the finding for the Details / trust receipt. */}

      {/* Error */}
      {finding.error && (
        <p className="aug-text-xs text-red-400 font-mono">{finding.error}</p>
      )}

      {/* Data table (collapsed) — only when no chart */}
      {hasData && !hasChart && (
        <FindingTable columns={finding.columns} rows={finding.rows} label="Data" />
      )}
      {/* The per-finding SQL + "Open in Query Builder" used to live here; for a swifter
          conversation it now sits in the one Details disclosure (the Queries block). */}
    </div>
  );
}

// ── Phase — a flat narrative section (no accordion, no chevron, no indent) ─────

function PhaseSection({ phase, onShowSource, execSummary }: { phase: InvestigationPhase; onShowSource?: ShowSource; execSummary?: string }) {
  if (phase.status === "skipped") return null;
  const findings = phase.findings.filter(f => f.interpretation || f.columns.length > 0 || f.error);
  if (!phase.summary && findings.length === 0) return null;
  // The deterministic synthesis fallback STITCHES the phase summaries into the executive
  // summary — re-printing this phase's summary below it reads the same paragraph twice
  // (three times counting the headline). Skip a summary the head already carries.
  const _norm = (s: string) => s.replace(/\*+/g, "").replace(/\s+/g, " ").trim();
  const summaryRedundant = !!phase.summary && !!execSummary && _norm(execSummary).includes(_norm(phase.summary));

  return (
    // Clean-output policy (Genie-style): no phase-machinery header ("CROSS-SECTIONAL
    // SCAN", "TEMPORAL TREND — WHEN") — the reader gets a continuous, confident
    // narrative; which internal phase produced a finding is process, not insight.
    <BriefSection>
      {phase.summary && !summaryRedundant && <BriefProse text={phase.summary} />}
      {findings.map(f => <EvidenceBlock key={f.finding_id} finding={f} onShowSource={onShowSource} />)}
    </BriefSection>
  );
}

// ── Recommended actions — numbered, bold-lead, muted trailing meta ─────────────

function RecommendationsList({ recs }: { recs: AnswerRecommendation[] }) {
  if (!recs.length) return null;
  return (
    <ol className="flex flex-col gap-2.5">
      {recs.map((rec, i) => (
        <li key={i} className="flex gap-2.5">
          <span className="shrink-0 aug-fs-ui text-zinc-500 mt-0.5">{i + 1}.</span>
          <div className="flex flex-col gap-0.5 min-w-0">
            <span className="aug-text-ui text-zinc-200 leading-relaxed">{renderEmphasis(rec.action)}</span>
            {(rec.expected_impact || rec.owner || rec.timeline) && (
              <span className="aug-fs-ui text-zinc-500 flex flex-wrap gap-x-3 gap-y-0.5">
                {rec.expected_impact && <span>Impact: {rec.expected_impact}</span>}
                {rec.owner && <span>Owner: {rec.owner}</span>}
                {rec.timeline && <span>Timeline: {rec.timeline}</span>}
              </span>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

// ── Streaming phase card (live, while the investigation runs) ──────────────────

function StreamingPhaseCard({ phase }: { phase: InvestigationPhase }) {
  const isRunning = phase.status === "running";
  const isSkipped = phase.status === "skipped";
  // Include any finding that carries narrative too — so the interpretation streams WITH its chart
  // as the phase lands, instead of being withheld until the final report swap (which made the
  // text, numbers and synthesis all appear at once "to fill the gap").
  const findings = phase.findings.filter(f => f.columns.length > 0 || f.is_significant || f.interpretation);

  return (
    <div className="space-y-2 pl-3 border-l border-zinc-800">
      <div className="flex items-center gap-2">
        <span className="text-base leading-none">{phase.phase_icon}</span>
        {isRunning && (
          <span className="text-sky-400 animate-spin inline-block">
            <RetryIcon label="Loading" size="small" />
          </span>
        )}
        <span className={`aug-fs-xs font-medium uppercase tracking-wide ${isSkipped ? "text-zinc-500" : "text-zinc-400"}`}>
          {phase.phase_name}
        </span>
        {isSkipped && <span className="aug-fs-xs text-zinc-500 italic">{phase.skipped_reason}</span>}
      </div>
      {phase.summary && !isSkipped && (
        <div className="aug-fs-xs text-zinc-500 leading-relaxed">{renderEmphasis(phase.summary)}</div>
      )}
      {/* A running phase with nothing rendered yet — name the wait so the gap reads as progress,
          not a frozen chart (the per-phase interpret is a slow LLM round-trip). */}
      {isRunning && findings.length === 0 && (
        <div className="aug-fs-xs text-zinc-500 italic pl-2 animate-pulse">Reading the results…</div>
      )}
      {findings.map(f => {
        const hasChart = f.columns.length > 0 && f.rows.length >= 2 && f.chart_type !== "none";
        return (
          <div key={f.finding_id} className="space-y-1.5 pl-2">
            {hasChart && (
              <div className="rounded-md border border-zinc-800/60 overflow-hidden p-2" style={{ background: "var(--bg-0)" }}>
                <Chart columns={f.columns} rows={f.rows as unknown[][]} title={f.title} chrome={false} columnUnits={f.column_units} exhibit={f.exhibit} showLabels />
              </div>
            )}
            {f.key_numbers?.length > 0 && <KeyNumbersInline metrics={f.key_numbers} />}
            {f.interpretation && <BriefProse text={f.interpretation} muted />}
          </div>
        );
      })}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function InvestigationReportView({
  report,
  streamingPhases,
  streamingReport,
  onShowSource,
}: {
  report?: AnswerReport;
  streamingPhases?: InvestigationPhase[];
  streamingReport?: string;
  onShowSource?: ShowSource;
}) {
  // While streaming: progressive phase cards + the report prose as the narrator writes
  // it (R6), so the synthesis phase isn't silent. The terminal report replaces both.
  if (!report) {
    // Intake is setup, not thinking — users don't value the "QUESTION INTAKE" dump of the
    // run's raw framing (it streamed a wall of join-path reasoning). The final report already
    // pulls intake out of the analysis phases; mirror that while streaming.
    const phases = (streamingPhases ?? []).filter(p => p.phase_id !== "intake" && !p._hidden);
    if (!phases.length && !streamingReport) return null;
    return (
      <div className="flex flex-col gap-4 pt-1">
        {streamingReport && <BriefProse text={streamingReport} />}
        {phases.map(phase => <StreamingPhaseCard key={phase.phase_id} phase={phase} />)}
      </div>
    );
  }

  const analysisPhases = report.phases.filter(p => p.phase_id !== "intake" && p.status !== "skipped" && !p._hidden);

  const periodStr = [
    report.observation_period,
    report.comparison_basis ? `vs ${report.comparison_basis}` : "",
  ].filter(Boolean).join(" ");

  return (
    <Brief>
      <BriefHeadline>{report.headline}</BriefHeadline>
      {/* Skip a summary that only restates the headline (the fallback path can emit both
          from the same sentence) — one text, rendered once. */}
      {report.executive_summary && report.executive_summary.trim() !== report.headline?.trim()
        && <BriefProse text={report.executive_summary} />}

      <BriefMeta
        items={[
          report.total_change_label
            ? <span key="tc" className={`tabular-nums font-medium ${!/\d/.test(report.total_change_label) ? "text-zinc-400" : report.total_change_label.trim().startsWith("-") ? "text-red-400" : "text-emerald-400"}`}>{report.total_change_label}</span>
            : null,
          periodStr || null,
          // Clean-output policy: the confidence verdict + justification are gone from the
          // report body entirely (the Details disclosure they lived in is removed) — the
          // body states findings, not a hedge banner across the top of every answer.
        ]}
      />

      {analysisPhases.map(phase => (
        <PhaseSection key={phase.phase_id} phase={phase} onShowSource={onShowSource} execSummary={report.executive_summary} />
      ))}

      {/* Bottom line — a short closing summary that lands the answer at the END of the
          report, before the actions (the exec summary opens it; this closes it). Backend-
          authored (`closing_summary`); older reports without the field simply omit it. */}
      {report.closing_summary && report.closing_summary.trim() && (
        <BriefSection label="Bottom line" className="border-t border-zinc-800/60 pt-4">
          <BriefProse text={report.closing_summary} />
        </BriefSection>
      )}

      {/* Clean-output policy: the Methodology & details disclosure (confidence factors,
          attribution, data gaps, question intake, the SQL Sources list) is gone — a
          reader gets conclusions, and the per-exhibit Source-data icon + the Evidence tab
          carry the data/SQL one click away. Only the decision — Recommended actions —
          stays in the flow, visible (uncollapsed), not behind a disclosure. */}
      {report.recommendations && report.recommendations.length > 0 && (
        <BriefSection label="Recommended actions" className="border-t border-zinc-800/60 pt-4">
          <RecommendationsList recs={report.recommendations} />
        </BriefSection>
      )}
    </Brief>
  );
}
