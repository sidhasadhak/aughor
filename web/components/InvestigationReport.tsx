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

interface ADARecommendation {
  action: string;
  expected_impact: string;
  owner: string;
  timeline: string;
}

export interface ADAReport {
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
  recommendations: ADARecommendation[];
  data_gaps: string[];
}

const CONF_TXT: Record<ADAReport["confidence"], string> = {
  HIGH:   "text-emerald-400",
  MEDIUM: "text-amber-400",
  LOW:    "text-red-400",
};

// ── Collapsible SQL block — quiet, per finding ─────────────────────────────────

function SqlToggle({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  if (!sql) return null;
  return (
    <div>
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-[11px] text-zinc-700 hover:text-zinc-500 transition-colors"
      >
        {open ? <ChevronDownIcon label="" size="small" /> : <ChevronRightIcon label="" size="small" />}
        SQL
      </button>
      {open && (
        <pre className="mt-1.5 text-[11px] text-zinc-400 rounded-md p-3 overflow-auto whitespace-pre-wrap leading-relaxed border border-zinc-800" style={{ background: "var(--code-bg)", maxHeight: 400 }}>
          {sql}
        </pre>
      )}
    </div>
  );
}

// ── Collapsible data table — quiet, only when a finding has no chart ───────────

function FindingTable({ columns, rows, label }: { columns: string[]; rows: (string | number | null)[][]; label: string }) {
  const [open, setOpen] = useState(false);
  if (!columns.length || !rows.length) return null;
  return (
    <div>
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-[11px] text-zinc-700 hover:text-zinc-500 transition-colors"
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

function EvidenceBlock({ finding }: { finding: InvestigationFinding }) {
  const hasData = finding.columns.length > 0 && finding.rows.length > 0;
  const hasChart = hasData && finding.chart_type !== "none" && finding.rows.length >= 2;

  return (
    <div className="flex flex-col gap-2.5">
      {/* Chart — the framed figure */}
      {hasChart && (
        <BriefFigure caption={finding.title}>
          <Chart columns={finding.columns} rows={finding.rows as unknown[][]} title={finding.title} />
        </BriefFigure>
      )}

      {/* Key numbers — inline metrics, no card */}
      {finding.key_numbers.length > 0 && <BriefMetrics metrics={finding.key_numbers} />}

      {/* Interpretation narrative */}
      {finding.interpretation && <BriefProse text={finding.interpretation} muted />}

      {/* Stat note — z-score etc */}
      {finding.stat_note && (
        <p className="aug-text-xs text-zinc-600 font-mono">{finding.stat_note}</p>
      )}

      {/* Error */}
      {finding.error && (
        <p className="aug-text-xs text-red-400 font-mono">{finding.error}</p>
      )}

      {/* Data table (collapsed) — only when no chart */}
      {hasData && !hasChart && (
        <FindingTable columns={finding.columns} rows={finding.rows} label="Data" />
      )}

      {/* SQL toggle */}
      <SqlToggle sql={finding.sql} />
    </div>
  );
}

// ── Phase — a flat narrative section (no accordion, no chevron, no indent) ─────

function PhaseSection({ phase }: { phase: InvestigationPhase }) {
  if (phase.status === "skipped") return null;
  const findings = phase.findings.filter(f => f.interpretation || f.columns.length > 0 || f.error);
  if (!phase.summary && findings.length === 0) return null;

  return (
    <BriefSection label={phase.phase_name}>
      {phase.summary && <BriefProse text={phase.summary} />}
      {findings.map(f => <EvidenceBlock key={f.finding_id} finding={f} />)}
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
                {tags && <span className="text-zinc-600"> · {tags}</span>}
              </span>
              <span className="flex items-center gap-3 shrink-0">
                <span className="text-zinc-600 font-mono">{entry.amount_label}</span>
                <span className={`font-mono w-10 text-right ${isNeg ? "text-red-400" : "text-emerald-400"}`}>
                  {entry.pct_of_total > 0 ? "+" : ""}{entry.pct_of_total.toFixed(0)}%
                </span>
              </span>
            </div>
            <div className="h-1 bg-zinc-800 rounded-full overflow-hidden">
              <div className={`h-full rounded-full ${isNeg ? "bg-red-500/60" : "bg-emerald-500/60"}`} style={{ width: `${barW}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Recommended actions — numbered, bold-lead, muted trailing meta ─────────────

function RecommendationsList({ recs }: { recs: ADARecommendation[] }) {
  if (!recs.length) return null;
  return (
    <ol className="flex flex-col gap-2.5">
      {recs.map((rec, i) => (
        <li key={i} className="flex gap-2.5">
          <span className="shrink-0 aug-text-sm font-mono text-zinc-600 mt-0.5">{i + 1}.</span>
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

function buildConfidenceFactors(report: ADAReport): { label: string; value: string; tone: ConfTone }[] {
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

function ConfidenceDetail({ report }: { report: ADAReport }) {
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
            <span className={`mt-1 w-1.5 h-1.5 rounded-full shrink-0 ${dotColor[f.tone]}`} />
            <span className="text-zinc-500 shrink-0 w-36">{f.label}</span>
            <span className="text-zinc-300">{f.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Investigation machinery — one quiet disclosure ─────────────────────────────

function InvestigationDetails({ report, intakePhase }: { report: ADAReport; intakePhase?: InvestigationPhase }) {
  const hasWaterfall = (report.attribution_waterfall?.length ?? 0) > 0;
  const hasGaps = (report.data_gaps?.length ?? 0) > 0;
  const intakeRows = intakePhase?.findings?.[0]?.rows ?? [];
  const hasIntake = intakeRows.length > 0;

  return (
    <BriefDetails>
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
                <span className="shrink-0 text-zinc-600">—</span>
                {gap}
              </li>
            ))}
          </ul>
        </BriefDetailBlock>
      )}

      {hasIntake && (
        <BriefDetailBlock label="Question intake">
          <div className="rounded-md border border-zinc-800/60 overflow-hidden" style={{ background: "var(--bg-0)" }}>
            <table className="w-full text-[11px]">
              <tbody>
                {intakeRows.map((row, i) => (
                  <tr key={i} className="border-b border-zinc-900/50 last:border-0">
                    <td className="py-1.5 px-3 text-zinc-500 whitespace-nowrap w-28">{String(row[0])}</td>
                    <td className="py-1.5 px-3 text-zinc-300 font-mono text-[11px] leading-relaxed">{String(row[1])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
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
  const findings = phase.findings.filter(f => f.columns.length > 0 || f.is_significant);

  return (
    <div className="space-y-2 pl-3 border-l border-zinc-800">
      <div className="flex items-center gap-2">
        <span className="text-base leading-none">{phase.phase_icon}</span>
        {isRunning && (
          <span className="text-sky-400 animate-spin inline-block">
            <RetryIcon label="Loading" size="small" />
          </span>
        )}
        <span className={`text-[11px] font-medium uppercase tracking-wide ${isSkipped ? "text-zinc-700" : "text-zinc-400"}`}>
          {phase.phase_name}
        </span>
        {isSkipped && <span className="text-[11px] text-zinc-600 italic">{phase.skipped_reason}</span>}
      </div>
      {phase.summary && !isSkipped && (
        <div className="text-[11px] text-zinc-500 leading-relaxed">{renderEmphasis(phase.summary)}</div>
      )}
      {findings.map(f => (
        <div key={f.finding_id} className="space-y-1.5 pl-2">
          {f.columns.length > 0 && f.rows.length >= 2 && f.chart_type !== "none" && (
            <div className="rounded-md border border-zinc-800/60 overflow-hidden p-2" style={{ background: "var(--bg-0)" }}>
              <Chart columns={f.columns} rows={f.rows as unknown[][]} title={f.title} chrome={false} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function InvestigationReportView({
  report,
  streamingPhases,
}: {
  report?: ADAReport;
  streamingPhases?: InvestigationPhase[];
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

      {analysisPhases.map(phase => <PhaseSection key={phase.phase_id} phase={phase} />)}

      {report.recommendations?.length > 0 && (
        <BriefSection label="Recommended actions">
          <RecommendationsList recs={report.recommendations} />
        </BriefSection>
      )}

      <InvestigationDetails report={report} intakePhase={intakePhase} />
    </Brief>
  );
}
