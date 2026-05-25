"use client";

import React, { useState } from "react";
import { InvestigationChart } from "@/components/InvestigationChart";
import ChevronDownIcon  from "@atlaskit/icon/core/chevron-down";
import ChevronRightIcon from "@atlaskit/icon/core/chevron-right";
import RetryIcon        from "@atlaskit/icon/core/retry";

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

// ── Number-coloured rich text ─────────────────────────────────────────────────

function RichText({ text, className = "" }: { text: string; className?: string }) {
  const parts = text.split(
    /(\*\*[^*]+\*\*|[+]\$?[\d,]+(?:\.\d+)?[KMBk]?%?|-\$?[\d,]+(?:\.\d+)?[KMBk]?%?|\$[\d,]+(?:\.\d+)?[KMBk]?|\d+(?:\.\d+)?%|\b\d{4,}(?:,\d{3})*\b)/g
  );
  return (
    <span className={className}>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**"))
          return <span key={i} className="text-zinc-200">{part.slice(2, -2)}</span>;
        if (/^[+]/.test(part))
          return <span key={i} className="font-mono text-emerald-400">{part}</span>;
        if (/^-/.test(part) && /\d/.test(part))
          return <span key={i} className="font-mono text-red-400">{part}</span>;
        if (/\$[\d,]+|\d+%|\b\d{4,}/.test(part))
          return <span key={i} className="font-mono text-zinc-200">{part}</span>;
        return part;
      })}
    </span>
  );
}

// ── Collapsible SQL block ──────────────────────────────────────────────────────

function SqlToggle({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  if (!sql) return null;
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-[11px] text-zinc-700 hover:text-zinc-500 transition-colors"
      >
        {open ? <ChevronDownIcon label="" size="small" /> : <ChevronRightIcon label="" size="small" />}
        SQL
      </button>
      {open && (
        <pre className="mt-1.5 text-[11px] text-zinc-400 bg-[#0d131a] rounded-lg p-3 overflow-x-auto whitespace-pre-wrap leading-relaxed border border-zinc-800">
          {sql}
        </pre>
      )}
    </div>
  );
}

// ── Data table ─────────────────────────────────────────────────────────────────

function DataTable({ columns, rows, label }: { columns: string[]; rows: (string | number | null)[][]; label: string }) {
  const [open, setOpen] = useState(false);
  if (!columns.length || !rows.length) return null;
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-[11px] text-zinc-700 hover:text-zinc-500 transition-colors"
      >
        {open ? <ChevronDownIcon label="" size="small" /> : <ChevronRightIcon label="" size="small" />}
        {label} · {rows.length} rows
      </button>
      {open && (
        <div className="mt-1.5 overflow-x-auto rounded-lg border border-zinc-800" style={{ background: "#0d131a" }}>
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-zinc-800">
                {columns.map((col, i) => (
                  <th key={i} className="text-left py-1.5 px-3 text-zinc-500 font-medium whitespace-nowrap">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 20).map((row, ri) => (
                <tr key={ri} className="border-b border-zinc-900/50 hover:bg-white/[0.02]">
                  {row.map((cell, ci) => {
                    const str = cell === null ? "—" : String(cell);
                    const n = parseFloat(str);
                    const isNeg = !isNaN(n) && n < 0;
                    const isPos = !isNaN(n) && n > 0 && ci > 0;
                    return (
                      <td key={ci} className={`py-1.5 px-3 font-mono whitespace-nowrap ${isNeg ? "text-red-400" : isPos ? "text-emerald-400" : "text-zinc-300"}`}>
                        {str}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > 20 && <p className="text-[11px] text-zinc-600 px-3 py-1.5">…{rows.length - 20} more rows</p>}
        </div>
      )}
    </div>
  );
}

// ── Single finding — evidence block (no title, flows inside phase) ─────────────

function EvidenceBlock({ finding }: { finding: InvestigationFinding }) {
  const hasData = finding.columns.length > 0 && finding.rows.length > 0;
  const hasChart = hasData && finding.chart_type !== "none" && finding.rows.length >= 2;

  return (
    <div className="space-y-2.5">
      {/* Chart — first, most prominent */}
      {hasChart && (
        <div className="rounded-xl border border-zinc-800/60 overflow-hidden p-3" style={{ background: "#0f1923" }}>
          <p className="text-[11px] text-zinc-500 mb-2">{finding.title}</p>
          <InvestigationChart columns={finding.columns} rows={finding.rows as unknown[][]} />
        </div>
      )}

      {/* Key numbers — inline stats */}
      {finding.key_numbers.length > 0 && (
        <div className="flex flex-wrap gap-x-5 gap-y-2 pt-0.5">
          {finding.key_numbers.map((n, i) => (
            <div key={i} className="space-y-0.5">
              <p className="text-[11px] text-zinc-500">{n.label}</p>
              <p className="text-[13px] font-mono tabular-nums text-zinc-200">
                {n.value}
                {n.delta && (
                  <span className={`text-[11px] ml-1.5 ${n.delta.startsWith("-") ? "text-red-400" : "text-emerald-400"}`}>
                    {n.delta}
                  </span>
                )}
              </p>
              {n.context && <p className="text-[11px] text-zinc-600">{n.context}</p>}
            </div>
          ))}
        </div>
      )}

      {/* Interpretation narrative */}
      {finding.interpretation && (
        <p className="text-[12px] text-zinc-400 leading-relaxed">
          <RichText text={finding.interpretation} />
        </p>
      )}

      {/* Stat note — z-score etc */}
      {finding.stat_note && (
        <p className="text-[11px] text-zinc-600 font-mono bg-zinc-900/50 px-2 py-1 rounded inline-block">{finding.stat_note}</p>
      )}

      {/* Error */}
      {finding.error && (
        <p className="text-[11px] text-red-400 font-mono bg-red-950/20 border border-red-500/20 px-2 py-1.5 rounded">{finding.error}</p>
      )}

      {/* Data table (collapsed) — only when no chart */}
      {hasData && !hasChart && (
        <DataTable columns={finding.columns} rows={finding.rows} label="Data" />
      )}

      {/* SQL toggle */}
      <SqlToggle sql={finding.sql} />
    </div>
  );
}

// ── Phase section — collapsible, groups all findings under one header ───────────

function PhaseSection({
  phase,
  defaultOpen = true,
}: {
  phase: InvestigationPhase;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const isSkipped = phase.status === "skipped";
  const isError   = phase.status === "error";

  // Filter out intake spec rows — shown in the phase but in a simpler way
  const isIntake = phase.phase_id === "intake";

  // Only show findings that have actual content
  const findings = phase.findings.filter(f =>
    f.interpretation || f.columns.length > 0 || f.error
  );

  const statusColor = isSkipped ? "text-zinc-700" : isError ? "text-red-500/70" : "text-zinc-400";

  return (
    <div className="space-y-0">
      {/* Phase header row */}
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-start gap-2.5 py-2 group"
      >
        <span className="mt-0.5 shrink-0">
          {open
            ? <ChevronDownIcon label="" size="small" />
            : <ChevronRightIcon label="" size="small" />}
        </span>
        <div className="flex-1 text-left space-y-0.5">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-zinc-300 uppercase tracking-wide">
              {phase.phase_name}
            </span>
            {isSkipped && (
              <span className="text-[10px] text-zinc-600 border border-zinc-800 px-1.5 py-0.5 rounded-full">skipped</span>
            )}
          </div>
          {/* Phase summary — the one-sentence takeaway */}
          {phase.summary && !isSkipped && (
            <p className={`text-[12px] leading-relaxed ${statusColor}`}>
              <RichText text={phase.summary} />
            </p>
          )}
          {isSkipped && phase.skipped_reason && (
            <p className="text-[11px] text-zinc-700 leading-relaxed">{phase.skipped_reason}</p>
          )}
        </div>
      </button>

      {/* Findings body */}
      {open && !isSkipped && findings.length > 0 && (
        <div className={`ml-6 mt-1 space-y-5 pb-2 ${isIntake ? "opacity-70" : ""}`}>
          {isIntake ? (
            // Intake: render as a compact key-value block
            <div className="rounded-lg border border-zinc-800/50 overflow-hidden" style={{ background: "#0d131a" }}>
              <table className="w-full text-[11px]">
                <tbody>
                  {findings[0]?.rows?.map((row, i) => (
                    <tr key={i} className="border-b border-zinc-900/50 last:border-0">
                      <td className="py-1.5 px-3 text-zinc-500 whitespace-nowrap w-28">{String(row[0])}</td>
                      <td className="py-1.5 px-3 text-zinc-300 font-mono text-[11px] leading-relaxed">{String(row[1])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {findings[0]?.interpretation && (
                <p className="text-[11px] text-zinc-500 px-3 py-2 border-t border-zinc-900/50 leading-relaxed">
                  {findings[0].interpretation}
                </p>
              )}
            </div>
          ) : (
            // Analysis phases: render findings as sequential evidence blocks
            findings.map((finding, i) => (
              <React.Fragment key={finding.finding_id}>
                {i > 0 && <div className="border-t border-zinc-800/40" />}
                <EvidenceBlock finding={finding} />
              </React.Fragment>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ── Attribution waterfall ──────────────────────────────────────────────────────

function WaterfallSection({ entries, totalLabel }: { entries: WaterfallEntry[]; totalLabel: string }) {
  if (!entries.length) return null;
  const maxAbs = Math.max(...entries.map(e => Math.abs(e.pct_of_total)), 1);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {totalLabel && (
          <span className="text-[12px] font-mono text-red-400 bg-red-950/20 border border-red-900/30 px-2 py-0.5 rounded-full">
            {totalLabel}
          </span>
        )}
      </div>
      <div className="space-y-2.5">
        {entries.map((entry, i) => {
          const isNeg = entry.pct_of_total > 0;
          const barW = Math.abs(entry.pct_of_total) / maxAbs * 100;
          return (
            <div key={i} className="space-y-1">
              <div className="flex items-center justify-between text-[11px]">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-zinc-300 truncate max-w-[220px]">{entry.cause}</span>
                  {entry.controllable && (
                    <span className="text-[9px] bg-amber-900/40 text-amber-400 border border-amber-800/40 px-1.5 py-0.5 rounded-full shrink-0">controllable</span>
                  )}
                  {!entry.structural && (
                    <span className="text-[9px] bg-sky-900/40 text-sky-400 border border-sky-800/40 px-1.5 py-0.5 rounded-full shrink-0">transient</span>
                  )}
                </div>
                <div className="flex items-center gap-3 shrink-0 ml-2">
                  <span className="text-zinc-600 font-mono">{entry.amount_label}</span>
                  <span className={`font-mono w-10 text-right ${isNeg ? "text-red-400" : "text-emerald-400"}`}>
                    {entry.pct_of_total > 0 ? "+" : ""}{entry.pct_of_total.toFixed(0)}%
                  </span>
                </div>
              </div>
              <div className="h-1 bg-zinc-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${isNeg ? "bg-red-500/60" : "bg-emerald-500/60"}`}
                  style={{ width: `${barW}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Recommendations ────────────────────────────────────────────────────────────

function RecommendationsSection({ recs }: { recs: ADARecommendation[] }) {
  if (!recs.length) return null;
  return (
    <div className="space-y-3">
      {recs.map((rec, i) => (
        <div key={i} className="flex items-start gap-3">
          <span className="shrink-0 mt-0.5 w-5 h-5 rounded-full border border-emerald-700/50 bg-emerald-900/20 flex items-center justify-center text-[10px] text-emerald-400 font-mono">{i + 1}</span>
          <div className="space-y-0.5 min-w-0">
            <p className="text-[12px] text-zinc-300 leading-snug">{rec.action}</p>
            <div className="flex flex-wrap gap-3 text-[11px] text-zinc-600">
              {rec.expected_impact && <span>Impact: <span className="text-zinc-500">{rec.expected_impact}</span></span>}
              {rec.owner && <span>Owner: <span className="text-zinc-500">{rec.owner}</span></span>}
              {rec.timeline && <span>Timeline: <span className="text-zinc-500">{rec.timeline}</span></span>}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Confidence badge ───────────────────────────────────────────────────────────

function ConfidencePill({ confidence }: { confidence: "HIGH" | "MEDIUM" | "LOW" }) {
  const styles = {
    HIGH:   "bg-emerald-900/30 text-emerald-400 border-emerald-800/40",
    MEDIUM: "bg-amber-900/30 text-amber-400 border-amber-800/40",
    LOW:    "bg-red-900/30 text-red-400 border-red-800/40",
  };
  return (
    <span className={`text-[11px] font-medium px-2.5 py-1 rounded-full border ${styles[confidence]}`}>
      {confidence} CONFIDENCE
    </span>
  );
}

// ── Streaming phase card (shown while investigation is running) ────────────────

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
        {isSkipped && <span className="text-[10px] text-zinc-600 italic">{phase.skipped_reason}</span>}
      </div>
      {phase.summary && !isSkipped && (
        <p className="text-[11px] text-zinc-500 leading-relaxed"><RichText text={phase.summary} /></p>
      )}
      {findings.map(f => (
        <div key={f.finding_id} className="space-y-1.5 pl-2">
          {f.columns.length > 0 && f.rows.length >= 2 && f.chart_type !== "none" && (
            <div className="rounded-lg border border-zinc-800/60 overflow-hidden p-2" style={{ background: "#0f1923" }}>
              <InvestigationChart columns={f.columns} rows={f.rows as unknown[][]} />
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
  // While streaming: show progressive phase cards
  if (!report) {
    const phases = streamingPhases ?? [];
    if (!phases.length) return null;
    return (
      <div className="space-y-4 pt-1">
        {phases.map(phase => (
          <StreamingPhaseCard key={phase.phase_id} phase={phase} />
        ))}
      </div>
    );
  }

  const hasWaterfall = (report.attribution_waterfall?.length ?? 0) > 0;
  const hasRecs = (report.recommendations?.length ?? 0) > 0;
  const hasGaps = (report.data_gaps?.length ?? 0) > 0;

  // Separate intake from analysis phases
  const intakePhase = report.phases.find(p => p.phase_id === "intake");
  const analysisPhases = report.phases.filter(p => p.phase_id !== "intake");

  return (
    <div className="space-y-6 text-sm">

      {/* ── Headline ── */}
      <div className="space-y-2">
        <h2 className="text-[14px] font-medium text-zinc-200 leading-snug">{report.headline}</h2>
        <p className="text-[12px] text-zinc-400 leading-relaxed">
          <RichText text={report.executive_summary} />
        </p>
        <div className="flex items-center flex-wrap gap-2 pt-1">
          <ConfidencePill confidence={report.confidence} />
          {report.total_change_label && (
            <span className="text-[12px] font-mono text-red-400 bg-red-950/20 border border-red-900/30 px-2.5 py-1 rounded-full">
              {report.total_change_label}
            </span>
          )}
          {report.comparison_basis && (
            <span className="text-[11px] text-zinc-600">vs {report.comparison_basis}</span>
          )}
        </div>
        {report.confidence_justification && (
          <p className="text-[11px] text-zinc-600 leading-relaxed">{report.confidence_justification}</p>
        )}
      </div>

      {/* ── Investigation phases — chronological narrative ── */}
      {(intakePhase || analysisPhases.length > 0) && (
        <div className="border-t border-zinc-800/60 pt-4 space-y-1">
          {/* Intake collapsed by default (it's metadata) */}
          {intakePhase && (
            <PhaseSection phase={intakePhase} defaultOpen={false} />
          )}
          {/* Analysis phases open by default */}
          {analysisPhases.map(phase => (
            <React.Fragment key={phase.phase_id}>
              <div className="border-t border-zinc-800/30" />
              <PhaseSection phase={phase} defaultOpen={true} />
            </React.Fragment>
          ))}
        </div>
      )}

      {/* ── Attribution waterfall ── */}
      {hasWaterfall && (
        <>
          <div className="border-t border-zinc-800/60" />
          <div className="space-y-2">
            <p className="text-[11px] text-zinc-500 uppercase tracking-wide">Attribution</p>
            <WaterfallSection entries={report.attribution_waterfall} totalLabel={report.total_change_label} />
          </div>
        </>
      )}

      {/* ── Recommended actions ── */}
      {hasRecs && (
        <>
          <div className="border-t border-zinc-800/60" />
          <div className="space-y-3">
            <p className="text-[11px] text-zinc-500 uppercase tracking-wide">Recommended Actions</p>
            <RecommendationsSection recs={report.recommendations} />
          </div>
        </>
      )}

      {/* ── Data gaps ── */}
      {hasGaps && (
        <>
          <div className="border-t border-zinc-800/60" />
          <div className="space-y-2">
            <p className="text-[11px] text-zinc-500 uppercase tracking-wide">Data Gaps</p>
            <ul className="space-y-1.5">
              {report.data_gaps.map((gap, i) => (
                <li key={i} className="text-[11px] text-zinc-600 flex items-start gap-2 leading-relaxed">
                  <span className="shrink-0 mt-0.5">—</span>
                  {gap}
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
