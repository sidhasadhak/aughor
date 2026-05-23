"use client";

import React, { useState } from "react";
import { InvestigationChart } from "@/components/InvestigationChart";
import { Loader2, ChevronDown, ChevronRight } from "lucide-react";

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

// ── Number-coloured rich text — no bold, just tint ───────────────────────────
// Positive deltas (+X, +X%) → emerald · Negative (−X, −X%) → red
// Neutral big numbers / dollar amounts → zinc-200 · **marked** → zinc-200

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
        className="flex items-center gap-1 text-[11px] text-zinc-600 hover:text-zinc-400 transition-colors"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
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

// ── Data table (collapsed by default) ─────────────────────────────────────────

function DataTable({ columns, rows, label }: { columns: string[]; rows: (string | number | null)[][]; label: string }) {
  const [open, setOpen] = useState(false);
  if (!columns.length || !rows.length) return null;
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-[11px] text-zinc-600 hover:text-zinc-400 transition-colors"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
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

// ── Finding section — narrative block with chart + source citation ─────────────

function FindingSection({
  finding,
  phaseLabel,
  index,
}: {
  finding: InvestigationFinding;
  phaseLabel: string;
  index: number;
}) {
  const hasData = finding.columns.length > 0 && finding.rows.length > 0;
  const hasChart = hasData && finding.chart_type !== "none" && finding.rows.length >= 2;

  return (
    <div className="space-y-2">
      {/* Phase label — subtle, no caps */}
      <p className="text-[11px] text-zinc-500">{phaseLabel}</p>

      {/* Finding title — same size as body, medium weight */}
      <h3 className="text-[12px] font-medium text-zinc-300 leading-snug">{finding.title}</h3>

      {/* Interpretation */}
      {finding.interpretation && (
        <p className="text-[12px] text-zinc-300 leading-relaxed">
          <RichText text={finding.interpretation} />
        </p>
      )}

      {/* Key numbers — inline pills */}
      {finding.key_numbers.length > 0 && (
        <div className="flex flex-wrap gap-3 pt-1">
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
              {n.context && <p className="text-[11px] text-zinc-500">{n.context}</p>}
            </div>
          ))}
        </div>
      )}

      {/* Stat note */}
      {finding.stat_note && (
        <p className="text-[11px] text-zinc-600 font-mono bg-zinc-900/60 px-2 py-1 rounded">{finding.stat_note}</p>
      )}

      {/* Chart */}
      {hasChart && (
        <div className="mt-2 rounded-xl border border-zinc-800/60 overflow-hidden p-3" style={{ background: "#0f1923" }}>
          <InvestigationChart columns={finding.columns} rows={finding.rows as unknown[][]} />
          <p className="text-[11px] text-zinc-600 mt-2 text-right">Source: {finding.title}</p>
        </div>
      )}

      {/* Error */}
      {finding.error && (
        <p className="text-[11px] text-red-400 font-mono bg-red-950/20 border border-red-500/20 px-2 py-1.5 rounded">{finding.error}</p>
      )}

      {/* Data table + SQL toggles */}
      {hasData && !hasChart && (
        <DataTable columns={finding.columns} rows={finding.rows} label="Data" />
      )}
      <SqlToggle sql={finding.sql} />
    </div>
  );
}

// ── Summary table ─────────────────────────────────────────────────────────────
// Mirrors the "Key Problem Areas Summary" table in Databricks Genie.

function SummaryTable({
  phases,
  recommendations,
}: {
  phases: InvestigationPhase[];
  recommendations: ADARecommendation[];
}) {
  // Gather significant findings across all phases
  const rows: { category: string; finding: string; details: string; action: string }[] = [];
  let recIdx = 0;

  for (const phase of phases) {
    for (const f of phase.findings) {
      if (!f.interpretation || f.chart_type === "none" && !f.key_numbers.length && !f.is_significant) continue;
      const firstSentence = f.interpretation.split(/(?<=[.!?])\s/)[0] ?? f.interpretation;
      const details = f.key_numbers.slice(0, 2).map(n => `${n.label}: ${n.value}`).join("  ·  ");
      const action = recommendations[recIdx]?.action ?? "—";
      if (f.is_significant) recIdx++;
      rows.push({ category: f.title, finding: firstSentence, details, action });
    }
  }

  if (!rows.length) return null;

  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-800" style={{ background: "#0f1923" }}>
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-zinc-800">
            {["Issue Category", "Finding", "Details", "Recommended Action"].map(h => (
              <th key={h} className="text-left px-3 py-2 text-zinc-500 font-medium whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-zinc-800/50 last:border-0 hover:bg-white/[0.02]">
              <td className="px-3 py-2 text-zinc-300 font-medium whitespace-nowrap max-w-[140px] truncate">{row.category}</td>
              <td className="px-3 py-2 text-zinc-400 max-w-[240px]">
                <RichText text={row.finding} />
              </td>
              <td className="px-3 py-2 text-zinc-500 whitespace-nowrap font-mono">{row.details || "—"}</td>
              <td className="px-3 py-2 text-zinc-400 max-w-[200px]">{row.action}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Attribution waterfall ──────────────────────────────────────────────────────

function WaterfallSection({ entries, totalLabel }: { entries: WaterfallEntry[]; totalLabel: string }) {
  if (!entries.length) return null;
  const maxAbs = Math.max(...entries.map(e => Math.abs(e.pct_of_total)), 1);

  return (
    <div className="space-y-3">
      <p className="text-[11px] text-zinc-500">Attribution</p>
      <div className="flex items-center gap-3 mb-1">
        <span className="text-[12px] font-mono text-red-400">{totalLabel}</span>
      </div>
      <div className="space-y-2.5">
        {entries.map((entry, i) => {
          const isNeg = entry.pct_of_total > 0;
          const barW = Math.abs(entry.pct_of_total) / maxAbs * 100;
          return (
            <div key={i} className="space-y-1">
              <div className="flex items-center justify-between text-[11px]">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-zinc-300 truncate max-w-[200px]">{entry.cause}</span>
                  {entry.controllable && <span className="text-[9px] bg-amber-900/40 text-amber-400 border border-amber-800/40 px-1.5 py-0.5 rounded-full shrink-0">controllable</span>}
                  {!entry.structural && <span className="text-[9px] bg-sky-900/40 text-sky-400 border border-sky-800/40 px-1.5 py-0.5 rounded-full shrink-0">transient</span>}
                </div>
                <div className="flex items-center gap-3 shrink-0 ml-2">
                  <span className="text-zinc-500 font-mono">{entry.amount_label}</span>
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

// ── Recommendations table ──────────────────────────────────────────────────────

function RecommendationsTable({ recs }: { recs: ADARecommendation[] }) {
  if (!recs.length) return null;
  return (
    <div className="space-y-3">
      <p className="text-[11px] text-zinc-500">Recommended Actions</p>
      <div className="space-y-3">
        {recs.map((rec, i) => (
          <div key={i} className="flex items-start gap-3">
            <span className="shrink-0 mt-0.5 w-5 h-5 rounded-full border border-emerald-700/50 bg-emerald-900/20 flex items-center justify-center text-[10px] text-emerald-400 font-mono">{i + 1}</span>
            <div className="space-y-0.5 min-w-0">
              <p className="text-[12px] text-zinc-300 font-medium leading-snug">{rec.action}</p>
              <div className="flex flex-wrap gap-3 text-[11px] text-zinc-600">
                {rec.expected_impact && <span>Impact: <span className="text-zinc-500">{rec.expected_impact}</span></span>}
                {rec.owner && <span>Owner: <span className="text-zinc-500">{rec.owner}</span></span>}
                {rec.timeline && <span>Timeline: <span className="text-zinc-500">{rec.timeline}</span></span>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Streaming phase card (shown while investigation is running) ────────────────

function StreamingPhaseCard({ phase }: { phase: InvestigationPhase }) {
  const isRunning = phase.status === "running";
  const isSkipped = phase.status === "skipped";
  const findings = phase.findings.filter(f => f.columns.length > 0 || f.is_significant);

  return (
    <div className="space-y-3 pl-3 border-l border-zinc-800">
      <div className="flex items-center gap-2">
        <span className="text-base leading-none">{phase.phase_icon}</span>
        {isRunning && <Loader2 className="h-3.5 w-3.5 text-sky-400 animate-spin" />}
        <span className={`text-[12px] font-medium ${isSkipped ? "text-zinc-600" : "text-zinc-300"}`}>
          {phase.phase_name}
        </span>
        {isSkipped && <span className="text-[10px] text-zinc-600 italic">{phase.skipped_reason}</span>}
      </div>
      {phase.summary && !isSkipped && (
        <p className="text-[11px] text-zinc-500 leading-relaxed"><RichText text={phase.summary} /></p>
      )}
      {findings.map(f => (
        <div key={f.finding_id} className="space-y-1.5 pl-2">
          <p className="text-[11px] font-medium text-zinc-400">{f.title}</p>
          {f.columns.length > 0 && f.rows.length >= 2 && (
            <div className="rounded-lg border border-zinc-800/60 overflow-hidden p-2" style={{ background: "#0f1923" }}>
              <InvestigationChart columns={f.columns} rows={f.rows as unknown[][]} />
            </div>
          )}
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
      <div className="space-y-5 pt-1">
        {phases.map(phase => (
          <StreamingPhaseCard key={phase.phase_id} phase={phase} />
        ))}
      </div>
    );
  }

  // Complete report: narrative document layout
  const allFindings: { finding: InvestigationFinding; phaseLabel: string }[] = report.phases.flatMap(phase =>
    phase.findings
      .filter(f => f.chart_type !== "none" || f.interpretation || f.is_significant)
      .map(finding => ({
        finding,
        phaseLabel: phase.phase_name.toUpperCase(),
      }))
  );

  const hasWaterfall = (report.attribution_waterfall?.length ?? 0) > 0;
  const hasRecs = (report.recommendations?.length ?? 0) > 0;
  const hasGaps = (report.data_gaps?.length ?? 0) > 0;

  return (
    <div className="space-y-8 text-sm">

      {/* ── Headline + summary ── */}
      <div className="space-y-2">
        <h2 className="text-[14px] font-medium text-zinc-200 leading-snug">{report.headline}</h2>
        <p className="text-[12px] text-zinc-300 leading-relaxed">
          <RichText text={report.executive_summary} />
        </p>

        {/* Stat strip */}
        <div className="flex items-center flex-wrap gap-2 pt-1">
          <ConfidencePill confidence={report.confidence} />
          {report.total_change_label && (
            <span className="text-[12px] font-mono text-red-400 bg-red-950/20 border border-red-900/30 px-2.5 py-1 rounded-full">
              {report.total_change_label}
            </span>
          )}
          {report.comparison_basis && (
            <span className="text-[11px] text-zinc-500">vs {report.comparison_basis}</span>
          )}
        </div>
        {report.confidence_justification && (
          <p className="text-[11px] text-zinc-500 leading-relaxed">{report.confidence_justification}</p>
        )}
      </div>

      {/* ── Key Problem Areas Summary table ── */}
      {report.phases.length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] text-zinc-500">Key Problem Areas</p>
          <SummaryTable phases={report.phases} recommendations={report.recommendations ?? []} />
        </div>
      )}

      {/* ── Finding sections — flat narrative ── */}
      {allFindings.length > 0 && (
        <div className="space-y-8">
          {allFindings.map(({ finding, phaseLabel }, i) => (
            <React.Fragment key={finding.finding_id}>
              {i > 0 && <div className="border-t border-zinc-800/60" />}
              <FindingSection finding={finding} phaseLabel={phaseLabel} index={i} />
            </React.Fragment>
          ))}
        </div>
      )}

      {/* ── Attribution waterfall ── */}
      {hasWaterfall && (
        <>
          <div className="border-t border-zinc-800/60" />
          <WaterfallSection entries={report.attribution_waterfall} totalLabel={report.total_change_label} />
        </>
      )}

      {/* ── Recommended actions ── */}
      {hasRecs && (
        <>
          <div className="border-t border-zinc-800/60" />
          <RecommendationsTable recs={report.recommendations} />
        </>
      )}

      {/* ── Data gaps ── */}
      {hasGaps && (
        <>
          <div className="border-t border-zinc-800/60" />
          <div className="space-y-2">
            <p className="text-[11px] text-zinc-500">Data Gaps</p>
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
