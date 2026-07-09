"use client";

/**
 * Deep Analysis report, rendered as a clean Brief.
 *
 * Same vocabulary as the Insight answer (headline → prose → framed figures →
 * one quiet details disclosure) — Deep Analysis is just the LONG version.
 * The old accordion-in-accordion, the confidence/total/controllable pills, and
 * the border-on-every-section are gone: phases are flat narrative sections, the
 * machinery (attribution, confidence factors, data gaps, intake, per-finding
 * SQL/data) folds into <BriefDetails>.
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
  BriefMetrics,
  BriefFigure,
  BriefDetails,
  BriefDetailBlock,
  renderEmphasis,
} from "@/components/brief/Brief";
import { SignificanceBadge } from "@/components/brief/StatBadge";
import { TrendStrip } from "@/components/brief/Sparkline";
import { useOpenInBuilder } from "@/lib/openInBuilder";

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
}

interface InvestigationPhase {
  phase_id: string;
  phase_name: string;
  phase_icon: string;
  status: "complete" | "partial" | "running" | "skipped" | "error";
  summary: string;
  findings: InvestigationFinding[];
  skipped_reason?: string;
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
}

const CONF_TXT: Record<AnswerReport["confidence"], string> = {
  HIGH:   "text-emerald-400",
  MEDIUM: "text-amber-400",
  LOW:    "text-red-400",
};

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

function EvidenceBlock({ finding, onShowSource }: { finding: InvestigationFinding; onShowSource?: ShowSource }) {
  const hasData = finding.columns.length > 0 && finding.rows.length > 0;
  const hasChart = hasData && finding.chart_type !== "none" && finding.rows.length >= 2;

  return (
    <div className="flex flex-col gap-2.5">
      {/* Chart — the framed figure */}
      {hasChart && (
        <BriefFigure caption={finding.title}>
          <Chart columns={finding.columns} rows={finding.rows as unknown[][]} title={finding.title} chartType={finding.chart_type} columnUnits={finding.column_units} showLabels />
        </BriefFigure>
      )}

      {/* Source data — opens the right-side data + SQL + Query Builder drawer (same as the quick answer) */}
      {hasData && onShowSource && (
        <button
          onClick={() => onShowSource({ columns: finding.columns, rows: finding.rows as unknown[][], sql: finding.sql || null, title: finding.title })}
          className="self-end flex items-center gap-1.5 aug-text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          <TableIcon label="Table" size="small" />
          Source data
        </button>
      )}

      {/* Trend strip — sparkline + period-over-period % (time-series findings only) */}
      <TrendStrip columns={finding.columns} rows={finding.rows} />

      {/* Key numbers — inline metrics, no card */}
      {finding.key_numbers.length > 0 && <BriefMetrics metrics={finding.key_numbers} />}

      {/* Interpretation narrative */}
      {finding.interpretation && <BriefProse text={finding.interpretation} muted />}

      {/* Significance verdict — "Significant" / "Within noise" + raw stat note */}
      {(finding.stat_note || finding.is_significant) && (
        <SignificanceBadge significant={finding.is_significant} note={finding.stat_note} />
      )}

      {/* Trust advisory — the result computed, but the trust battery distrusts it (impossible
          magnitude, fan-out artifact, vacuous CASE…). Surfaced, never suppressed. */}
      {finding.trust_caveat && (
        <div className="rounded-md border border-amber-700/40 bg-amber-900/15 px-2.5 py-1.5">
          <span className="aug-text-xs font-semibold uppercase tracking-wide text-amber-400">Trust advisory</span>
          <p className="aug-text-xs text-amber-200/90 mt-0.5">{finding.trust_caveat}</p>
        </div>
      )}

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

function PhaseSection({ phase, onShowSource }: { phase: InvestigationPhase; onShowSource?: ShowSource }) {
  if (phase.status === "skipped") return null;
  const findings = phase.findings.filter(f => f.interpretation || f.columns.length > 0 || f.error);
  if (!phase.summary && findings.length === 0) return null;

  return (
    <BriefSection label={phase.phase_name}>
      {phase.summary && <BriefProse text={phase.summary} />}
      {findings.map(f => <EvidenceBlock key={f.finding_id} finding={f} onShowSource={onShowSource} />)}
    </BriefSection>
  );
}

// ── Attribution waterfall — plain rows + bars (lives in details) ──────────────

function WaterfallSection({ entries }: { entries: WaterfallEntry[] }) {
  if (!entries.length) return null;
  const maxAbs = Math.max(...entries.map(e => Math.abs(e.pct_of_total)), 1);

  return (
    <div className="flex flex-col gap-2.5">
      {entries.map((entry, i) => {
        const isNeg = entry.pct_of_total < 0;
        const barW = Math.abs(entry.pct_of_total) / maxAbs * 100;
        const tags = [entry.controllable && "controllable", !entry.structural && "transient"]
          .filter(Boolean).join(" · ");
        return (
          <div key={i} className="flex flex-col gap-1">
            <div className="flex items-center justify-between aug-text-xs gap-2">
              <span className="text-zinc-400 truncate min-w-0">
                {entry.cause}
                {tags && <span className="text-zinc-500"> · {tags}</span>}
              </span>
              <span className="flex items-center gap-3 shrink-0">
                <span className="text-zinc-500 font-mono">{entry.amount_label}</span>
                <span className={`font-mono w-10 text-right ${isNeg ? "text-red-400" : "text-emerald-400"}`}>
                  {entry.pct_of_total > 0 ? "+" : ""}{entry.pct_of_total.toFixed(0)}%
                </span>
              </span>
            </div>
            <div className="h-1 bg-zinc-800 rounded-[var(--r-pill)] overflow-hidden">
              <div className={`h-full rounded-[var(--r-pill)] ${isNeg ? "bg-red-500/60" : "bg-emerald-500/60"}`} style={{ width: `${barW}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Recommended actions — numbered, bold-lead, muted trailing meta ─────────────

function RecommendationsList({ recs }: { recs: AnswerRecommendation[] }) {
  if (!recs.length) return null;
  return (
    <ol className="flex flex-col gap-2.5">
      {recs.map((rec, i) => (
        <li key={i} className="flex gap-2.5">
          <span className="shrink-0 aug-text-sm font-mono text-zinc-500 mt-0.5">{i + 1}.</span>
          <div className="flex flex-col gap-0.5 min-w-0">
            <span className="aug-text-ui text-zinc-200 leading-relaxed">{renderEmphasis(rec.action)}</span>
            {(rec.expected_impact || rec.owner || rec.timeline) && (
              <span className="aug-text-xs text-zinc-500 flex flex-wrap gap-x-3 gap-y-0.5">
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

// ── Confidence breakdown (lives in details) ────────────────────────────────────

type ConfTone = "good" | "warn" | "neutral";

function buildConfidenceFactors(report: AnswerReport): { label: string; value: string; tone: ConfTone }[] {
  const { phases, attribution_waterfall, data_gaps } = report;
  const completedPhases = phases.filter(p => p.status === "complete" || p.status === "partial");
  const skippedPhases   = phases.filter(p => p.status === "skipped");
  const allFindings     = phases.flatMap(p => p.findings);
  const queriesWithData = allFindings.filter(f => !f.error && f.columns.length > 0);
  const queriesErrored  = allFindings.filter(f => !!f.error);
  const sigFindings     = allFindings.filter(f => f.is_significant);
  const waterfallPct    = attribution_waterfall.reduce((s, e) => s + (e.pct_of_total ?? 0), 0);

  return [
    {
      label: "Phases run",
      value: skippedPhases.length > 0
        ? `${completedPhases.length} of ${phases.length} (${skippedPhases.length} skipped as unnecessary)`
        : `${completedPhases.length} of ${phases.length}`,
      tone: completedPhases.length >= phases.length * 0.6 ? "good" : "warn",
    },
    {
      label: "Queries with data",
      value: queriesErrored.length > 0
        ? `${queriesWithData.length} succeeded, ${queriesErrored.length} errored`
        : `${queriesWithData.length}`,
      tone: queriesErrored.length === 0 ? "good" : "warn",
    },
    ...(sigFindings.length > 0 ? [{
      label: "Significant findings",
      value: `${sigFindings.length} statistically significant`,
      tone: "good" as ConfTone,
    }] : []),
    ...(attribution_waterfall.length > 0 ? [{
      label: "Attribution explained",
      value: `${Math.round(waterfallPct)}% of change accounted for`,
      tone: (waterfallPct >= 80 ? "good" : "warn") as ConfTone,
    }] : []),
    ...(data_gaps.length > 0 ? [{
      label: "Data gaps",
      value: `${data_gaps.length} gap${data_gaps.length > 1 ? "s" : ""} noted`,
      tone: "warn" as ConfTone,
    }] : []),
  ];
}

function ConfidenceDetail({ report }: { report: AnswerReport }) {
  const dotColor: Record<ConfTone, string> = { good: "bg-emerald-400", warn: "bg-amber-400", neutral: "bg-zinc-500" };
  const factors = buildConfidenceFactors(report);
  return (
    <div className="flex flex-col gap-2.5 aug-text-xs">
      {report.confidence_justification && (
        <p className="text-zinc-400 leading-relaxed">{report.confidence_justification}</p>
      )}
      <div className="flex flex-col gap-1.5">
        {factors.map(f => (
          <div key={f.label} className="flex items-start gap-2">
            <span className={`mt-1 w-1.5 h-1.5 rounded-[var(--r-pill)] shrink-0 ${dotColor[f.tone]}`} />
            <span className="text-zinc-500 shrink-0 w-36">{f.label}</span>
            <span className="text-zinc-300">{f.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Cross-phase checks — the Orchestrator's declared plan + consistency verdict ──

function CrossPhaseSection({ report }: { report: AnswerReport }) {
  const plan = report.orchestration_plan;
  const contradictions = report.contradiction_report?.items ?? [];
  const rec = report.plan_reconciliation;
  return (
    <div className="flex flex-col gap-2.5">
      {contradictions.length > 0 && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2">
          <p className="aug-text-xs font-medium text-amber-300/90 mb-1">
            {contradictions.length} cross-phase tension{contradictions.length > 1 ? "s" : ""} flagged
          </p>
          <ul className="flex flex-col gap-1">
            {contradictions.map((c, i) => (
              <li key={i} className="aug-text-xs text-amber-200/80 flex items-start gap-2 leading-relaxed">
                <span className="shrink-0 text-amber-400/70">⚠</span>
                {c.detail}
              </li>
            ))}
          </ul>
        </div>
      )}
      {plan && (
        <div className="aug-text-sm text-zinc-400 leading-relaxed">
          <span className="text-zinc-500">Planned path: </span>
          {plan.steps.filter(s => s.disposition !== "gated_off").map(s => s.phase_id).join(" → ")}
          {rec && rec.skipped.length > 0 && (
            <span className="text-zinc-500"> · skipped {rec.skipped.join(", ")} (a gate stopped early)</span>
          )}
        </div>
      )}
    </div>
  );
}

// ── Investigation machinery — one quiet disclosure ─────────────────────────────

function InvestigationDetails({ report, intakePhase }: { report: AnswerReport; intakePhase?: InvestigationPhase }) {
  const hasWaterfall = (report.attribution_waterfall?.length ?? 0) > 0;
  const hasGaps = (report.data_gaps?.length ?? 0) > 0;
  const intakeRows = intakePhase?.findings?.[0]?.rows ?? [];
  const hasIntake = intakeRows.length > 0;
  const hasRecs = (report.recommendations?.length ?? 0) > 0;
  const openInBuilder = useOpenInBuilder();
  const queries = report.phases
    .flatMap(p => p.findings)
    .filter(f => f.sql && f.sql.trim())
    .map(f => ({ id: f.finding_id, title: f.title, sql: f.sql }));

  return (
    <BriefDetails>
      {hasRecs && (
        <BriefDetailBlock label="Recommended actions">
          <RecommendationsList recs={report.recommendations} />
        </BriefDetailBlock>
      )}

      <BriefDetailBlock label="Confidence">
        <ConfidenceDetail report={report} />
      </BriefDetailBlock>

      {hasWaterfall && (
        <BriefDetailBlock label="Attribution">
          <WaterfallSection entries={report.attribution_waterfall} />
        </BriefDetailBlock>
      )}

      {hasGaps && (
        <BriefDetailBlock label="Data gaps">
          <ul className="flex flex-col gap-1.5">
            {report.data_gaps.map((gap, i) => (
              <li key={i} className="aug-text-sm text-zinc-500 flex items-start gap-2 leading-relaxed">
                <span className="shrink-0 text-zinc-500">—</span>
                {gap}
              </li>
            ))}
          </ul>
        </BriefDetailBlock>
      )}

      {(report.orchestration_plan || (report.contradiction_report?.count ?? 0) > 0) && (
        <BriefDetailBlock label="Cross-phase checks">
          <CrossPhaseSection report={report} />
        </BriefDetailBlock>
      )}

      {hasIntake && (
        <BriefDetailBlock label="Question intake">
          <div className="rounded-md border border-zinc-800/60 overflow-hidden" style={{ background: "var(--bg-0)" }}>
            <table className="w-full aug-fs-xs">
              <tbody>
                {intakeRows.map((row, i) => (
                  <tr key={i} className="border-b border-zinc-900/50 last:border-0">
                    <td className="py-1.5 px-3 text-zinc-500 whitespace-nowrap w-28">{String(row[0])}</td>
                    <td className="py-1.5 px-3 text-zinc-300 font-mono aug-fs-xs leading-relaxed">{String(row[1])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </BriefDetailBlock>
      )}

      {queries.length > 0 && (
        <BriefDetailBlock label="Queries">
          <div className="flex flex-col gap-3">
            {queries.map(q => (
              <div key={q.id} className="flex flex-col gap-1.5">
                <div className="flex items-center gap-3">
                  <span className="aug-text-xs text-zinc-400 min-w-0 truncate">{q.title}</span>
                  {openInBuilder && (
                    <button
                      onClick={() => openInBuilder(q.sql)}
                      title="Open this query in the Query Builder"
                      className="shrink-0 aug-fs-xs text-blue-400 hover:text-blue-300 transition-colors"
                    >
                      Open in Query Builder →
                    </button>
                  )}
                </div>
                <pre className="w-full text-[11.5px] text-zinc-300 rounded-md p-2.5 overflow-auto whitespace-pre-wrap leading-relaxed border border-zinc-800" style={{ background: "var(--code-bg)", maxHeight: 320 }}>
                  {q.sql}
                </pre>
              </div>
            ))}
          </div>
        </BriefDetailBlock>
      )}
    </BriefDetails>
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
                <Chart columns={f.columns} rows={f.rows as unknown[][]} title={f.title} chrome={false} columnUnits={f.column_units} showLabels />
              </div>
            )}
            {f.key_numbers?.length > 0 && <BriefMetrics metrics={f.key_numbers} />}
            {f.interpretation && <BriefProse text={f.interpretation} muted />}
            {(f.stat_note || f.is_significant) && (
              <SignificanceBadge significant={f.is_significant} note={f.stat_note} />
            )}
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
  onShowSource,
}: {
  report?: AnswerReport;
  streamingPhases?: InvestigationPhase[];
  onShowSource?: ShowSource;
}) {
  // While streaming: progressive phase cards (the live state, unchanged)
  if (!report) {
    const phases = streamingPhases ?? [];
    if (!phases.length) return null;
    return (
      <div className="flex flex-col gap-4 pt-1">
        {phases.map(phase => <StreamingPhaseCard key={phase.phase_id} phase={phase} />)}
      </div>
    );
  }

  const intakePhase = report.phases.find(p => p.phase_id === "intake");
  const analysisPhases = report.phases.filter(p => p.phase_id !== "intake" && p.status !== "skipped");

  const periodStr = [
    report.observation_period,
    report.comparison_basis ? `vs ${report.comparison_basis}` : "",
  ].filter(Boolean).join(" ");

  return (
    <Brief>
      <BriefHeadline>{report.headline}</BriefHeadline>
      {report.executive_summary && <BriefProse text={report.executive_summary} />}

      <BriefMeta
        items={[
          report.total_change_label
            ? <span key="tc" className={`font-mono ${!/\d/.test(report.total_change_label) ? "text-zinc-400" : report.total_change_label.trim().startsWith("-") ? "text-red-400" : "text-emerald-400"}`}>{report.total_change_label}</span>
            : null,
          periodStr || null,
          report.confidence
            ? <span key="conf" className={CONF_TXT[report.confidence]}>{report.confidence.charAt(0) + report.confidence.slice(1).toLowerCase()} confidence</span>
            : null,
        ]}
      />

      {report.metric_definition && (
        <p className="aug-text-xs text-zinc-500 mt-1">
          <span className="text-zinc-400">How this was measured — </span>{report.metric_definition}
        </p>
      )}

      {analysisPhases.map(phase => <PhaseSection key={phase.phase_id} phase={phase} onShowSource={onShowSource} />)}

      <InvestigationDetails report={report} intakePhase={intakePhase} />
    </Brief>
  );
}
