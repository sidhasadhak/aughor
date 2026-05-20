"use client";

import React, { useState } from "react";
import { InvestigationChart } from "@/components/InvestigationChart";
import { ChevronDown, ChevronRight, CheckCircle2, Loader2, AlertCircle, SkipForward } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

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

// ── Waterfall chart ────────────────────────────────────────────────────────────

function AttributionWaterfall({ entries, totalLabel }: { entries: WaterfallEntry[]; totalLabel: string }) {
  if (!entries.length) return null;

  const maxAbs = Math.max(...entries.map(e => Math.abs(e.pct_of_total)));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-zinc-500 uppercase tracking-wide">Attribution</span>
        <span className="text-sm font-semibold text-red-400">{totalLabel}</span>
      </div>
      <div className="space-y-2">
        {entries.map((entry, i) => {
          const isNegative = entry.pct_of_total > 0; // contributor to decline = positive pct
          const barWidth = Math.abs(entry.pct_of_total) / Math.max(maxAbs, 1) * 100;
          const barColor = isNegative
            ? "bg-red-500/70"
            : "bg-emerald-500/70";

          return (
            <div key={i} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-zinc-300 truncate max-w-[200px]">{entry.cause}</span>
                  <div className="flex gap-1 flex-shrink-0">
                    {entry.controllable && (
                      <span className="text-[10px] bg-amber-900/40 text-amber-300 px-1 rounded">controllable</span>
                    )}
                    {!entry.structural && (
                      <span className="text-[10px] bg-sky-900/40 text-sky-300 px-1 rounded">transient</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                  <span className="text-zinc-400">{entry.amount_label}</span>
                  <span className={`font-mono font-semibold ${isNegative ? "text-red-400" : "text-emerald-400"}`}>
                    {entry.pct_of_total > 0 ? "+" : ""}{entry.pct_of_total.toFixed(0)}%
                  </span>
                </div>
              </div>
              <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${barColor}`}
                  style={{ width: `${barWidth}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Data table ─────────────────────────────────────────────────────────────────

function FindingTable({ columns, rows }: { columns: string[]; rows: (string | number | null)[][] }) {
  if (!columns.length || !rows.length) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-zinc-600">
            {columns.map((col, i) => (
              <th key={i} className="text-left py-1.5 px-2 text-zinc-500 font-medium whitespace-nowrap">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 15).map((row, ri) => (
            <tr key={ri} className="border-b border-zinc-900 hover:bg-zinc-700/70/50">
              {row.map((cell, ci) => {
                const str = cell === null ? "NULL" : String(cell);
                // Colour negative/positive values
                const isNumeric = typeof cell === "number" || (typeof cell === "string" && /^-?\d+\.?\d*%?$/.test(str));
                const isNeg = isNumeric && (parseFloat(str) < 0 || str.startsWith("-"));
                const isPos = isNumeric && !isNeg && parseFloat(str) > 0;
                return (
                  <td
                    key={ci}
                    className={`py-1.5 px-2 font-mono whitespace-nowrap ${
                      isNeg ? "text-red-400" : isPos && ci > 0 ? "text-emerald-400" : "text-zinc-300"
                    }`}
                  >
                    {str}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 15 && (
        <p className="text-xs text-zinc-600 mt-1 px-2">… {rows.length - 15} more rows</p>
      )}
    </div>
  );
}

// ── Mini chart (delegates to existing Observable Plot component) ───────────────

function FindingChart({ columns, rows, chartType }: { columns: string[]; rows: (string | number | null)[][]; chartType: string }) {
  if (chartType === "none" || !columns.length || rows.length < 2) return null;
  return (
    <div className="mt-2">
      <InvestigationChart columns={columns} rows={rows as unknown[][]} />
    </div>
  );
}

// ── Key numbers strip ──────────────────────────────────────────────────────────

function KeyNumbers({ numbers }: { numbers: PhaseKeyNumber[] }) {
  if (!numbers.length) return null;
  return (
    <div className="flex gap-3 flex-wrap">
      {numbers.map((n, i) => (
        <div key={i} className="flex flex-col gap-0.5 rounded-xl border border-zinc-600 bg-zinc-800/60 px-4 py-3 min-w-[100px]">
          <span className="text-[10px] uppercase tracking-wide text-zinc-500">{n.label}</span>
          <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-semibold tabular-nums text-white">{n.value}</span>
            {n.delta && (
              <span className={`text-xs font-medium ${n.delta.startsWith("-") ? "text-red-400" : "text-emerald-400"}`}>
                {n.delta}
              </span>
            )}
          </div>
          {n.context && <span className="text-[10px] text-zinc-600 leading-tight">{n.context}</span>}
        </div>
      ))}
    </div>
  );
}

// ── Single finding ─────────────────────────────────────────────────────────────

function FindingCard({ finding, defaultOpen }: { finding: InvestigationFinding; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const [sqlOpen, setSqlOpen] = useState(false);
  const hasData = finding.columns.length > 0 && finding.rows.length > 0;
  const hasChart = hasData && finding.chart_type !== "none";

  return (
    <div className={`rounded-xl border overflow-hidden transition-colors ${
      finding.is_significant
        ? "border-orange-500/30 bg-orange-500/5"
        : "border-zinc-600 bg-zinc-800/40"
    }`}>
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-zinc-700/30 transition-colors text-left"
      >
        <div className="flex items-center gap-2.5">
          {open
            ? <ChevronDown className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
            : <ChevronRight className="h-3.5 w-3.5 text-zinc-500 shrink-0" />}
          <span className="text-sm font-medium text-zinc-200">{finding.title}</span>
          {finding.is_significant && (
            <span className="text-[10px] bg-orange-500/15 text-orange-300 border border-orange-500/20 px-1.5 py-0.5 rounded-full">significant</span>
          )}
          {finding.error && (
            <span className="text-[10px] bg-red-500/10 text-red-400 border border-red-500/20 px-1.5 py-0.5 rounded-full">error</span>
          )}
        </div>
        {finding.row_count > 0 && (
          <span className="text-[11px] text-zinc-600 shrink-0 ml-2">{finding.row_count} rows</span>
        )}
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-4 border-t border-zinc-600/50">
          <div className="pt-3">
            <p className="text-sm text-zinc-300 leading-relaxed">{finding.interpretation}</p>
          </div>

          {finding.key_numbers.length > 0 && (
            <KeyNumbers numbers={finding.key_numbers} />
          )}

          {finding.stat_note && (
            <div className="text-xs text-zinc-500 bg-zinc-800/60 border border-zinc-600 px-3 py-2 rounded-lg font-mono">
              {finding.stat_note}
            </div>
          )}

          {hasChart && (
            <FindingChart columns={finding.columns} rows={finding.rows} chartType={finding.chart_type} />
          )}

          {hasData && (
            <div className="rounded-lg border border-zinc-600 overflow-hidden">
              <FindingTable columns={finding.columns} rows={finding.rows} />
            </div>
          )}

          {finding.sql && (
            <div>
              <button
                onClick={() => setSqlOpen(v => !v)}
                className="flex items-center gap-1.5 text-[11px] text-zinc-600 hover:text-zinc-400 transition-colors"
              >
                {sqlOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                SQL
              </button>
              {sqlOpen && (
                <pre className="mt-1.5 text-[11px] text-zinc-400 bg-zinc-800 border border-zinc-600 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                  {finding.sql}
                </pre>
              )}
            </div>
          )}

          {finding.error && (
            <div className="text-xs text-red-400 bg-red-950/20 border border-red-500/20 px-3 py-2 rounded-lg font-mono">
              {finding.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Phase color palette (left-border accent by phase index) ───────────────────

const PHASE_ACCENT = [
  "border-l-violet-500",
  "border-l-sky-500",
  "border-l-teal-500",
  "border-l-amber-500",
  "border-l-emerald-500",
];

// ── Phase section ──────────────────────────────────────────────────────────────

function PhaseSection({ phase, phaseIndex }: { phase: InvestigationPhase; phaseIndex: number }) {
  const [expanded, setExpanded] = useState(true);
  const accent = PHASE_ACCENT[phaseIndex % PHASE_ACCENT.length];

  const statusIcon = {
    complete: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
    partial:  <CheckCircle2 className="h-4 w-4 text-amber-500" />,
    running:  <Loader2 className="h-4 w-4 text-sky-400 animate-spin" />,
    skipped:  <SkipForward className="h-4 w-4 text-zinc-600" />,
    error:    <AlertCircle className="h-4 w-4 text-red-500" />,
  }[phase.status] ?? <Loader2 className="h-4 w-4 text-zinc-500 animate-spin" />;

  const nonTrivialFindings = phase.findings.filter(f => f.chart_type !== "none" || f.columns.length > 0);

  return (
    <div className={`pl-4 border-l-2 ${accent} space-y-3`}>
      {/* Phase header */}
      <div className="flex items-start gap-3">
        <div className="flex items-center gap-1.5 mt-0.5 shrink-0">
          <span className="text-base leading-none">{phase.phase_icon}</span>
          {statusIcon}
        </div>
        <div className="flex-1 min-w-0">
          <button
            onClick={() => setExpanded(v => !v)}
            className="flex items-center gap-2 text-left w-full group"
          >
            <span className="text-sm font-semibold text-zinc-200 group-hover:text-white transition-colors">
              {phase.phase_name}
            </span>
            {expanded
              ? <ChevronDown className="h-3.5 w-3.5 text-zinc-600" />
              : <ChevronRight className="h-3.5 w-3.5 text-zinc-600" />}
          </button>
          <p className="text-sm text-zinc-400 mt-0.5 leading-snug">{phase.summary}</p>
          {phase.skipped_reason && (
            <p className="text-xs text-zinc-600 italic mt-0.5">{phase.skipped_reason}</p>
          )}
        </div>
      </div>

      {expanded && nonTrivialFindings.length > 0 && (
        <div className="space-y-2.5">
          {nonTrivialFindings.map((finding, i) => (
            <FindingCard
              key={finding.finding_id}
              finding={finding}
              defaultOpen={i === 0 && phase.status !== "skipped"}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Confidence badge ───────────────────────────────────────────────────────────

function ConfidenceBadge({ confidence }: { confidence: "HIGH" | "MEDIUM" | "LOW" }) {
  const styles = {
    HIGH:   "bg-emerald-900/40 text-emerald-300 border-emerald-800/50",
    MEDIUM: "bg-amber-900/40 text-amber-300 border-amber-800/50",
    LOW:    "bg-red-900/40 text-red-400 border-red-800/50",
  };
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${styles[confidence]}`}>
      {confidence} CONFIDENCE
    </span>
  );
}

// ── Recommendations ────────────────────────────────────────────────────────────

function Recommendations({ recs }: { recs: ADARecommendation[] }) {
  if (!recs.length) return null;
  return (
    <div className="space-y-2">
      {recs.map((rec, i) => (
        <div key={i} className="rounded-xl border border-zinc-600 bg-zinc-800/50 px-4 py-3 space-y-1.5">
          <div className="flex items-start gap-2">
            <span className="text-emerald-500 text-xs mt-0.5 shrink-0">→</span>
            <p className="text-sm text-zinc-200 font-medium leading-snug">{rec.action}</p>
          </div>
          <div className="flex gap-4 flex-wrap text-xs text-zinc-600 pl-4">
            {rec.expected_impact && (
              <span>Impact: <span className="text-zinc-400">{rec.expected_impact}</span></span>
            )}
            {rec.owner && (
              <span>Owner: <span className="text-zinc-400">{rec.owner}</span></span>
            )}
            {rec.timeline && (
              <span>Timeline: <span className="text-zinc-400">{rec.timeline}</span></span>
            )}
          </div>
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
  // Use report.phases if complete, otherwise use streaming phases for progressive reveal
  const phases = report?.phases ?? streamingPhases ?? [];

  return (
    <div className="space-y-6">
      {/* ── Headline ── */}
      {report && (
        <div className="space-y-2">
          <h2 className="text-xl font-bold text-white leading-tight">{report.headline}</h2>
          <p className="text-sm text-zinc-400 leading-relaxed">{report.executive_summary}</p>

          <div className="flex items-center gap-3 flex-wrap">
            <ConfidenceBadge confidence={report.confidence} />
            {report.total_change_label && (
              <span className="text-sm font-mono font-semibold text-red-400">{report.total_change_label}</span>
            )}
            {report.comparison_basis && (
              <span className="text-xs text-zinc-600">vs {report.comparison_basis}</span>
            )}
          </div>

          {report.confidence_justification && (
            <p className="text-xs text-zinc-600 italic">{report.confidence_justification}</p>
          )}
        </div>
      )}

      {/* ── Phases (progressive) ── */}
      {phases.length > 0 && (
        <div className="space-y-5">
          {phases.map((phase, i) => (
            <React.Fragment key={phase.phase_id}>
              {i > 0 && <Separator className="bg-zinc-800/50" />}
              <PhaseSection phase={phase} phaseIndex={i} />
            </React.Fragment>
          ))}
        </div>
      )}

      {/* ── Attribution Waterfall ── */}
      {report && (report.attribution_waterfall?.length ?? 0) > 0 && (
        <>
          <Separator className="bg-zinc-800" />
          <div className="space-y-3">
            <p className="text-[10px] text-zinc-500 uppercase tracking-widest font-medium">Attribution Waterfall</p>
            <AttributionWaterfall
              entries={report.attribution_waterfall}
              totalLabel={report.total_change_label}
            />
          </div>
        </>
      )}

      {/* ── Recommendations ── */}
      {report && (report.recommendations?.length ?? 0) > 0 && (
        <>
          <Separator className="bg-zinc-800" />
          <div className="space-y-3">
            <p className="text-[10px] text-zinc-500 uppercase tracking-widest font-medium">Recommended Actions</p>
            <Recommendations recs={report.recommendations} />
          </div>
        </>
      )}

      {/* ── Data gaps ── */}
      {report && (report.data_gaps?.length ?? 0) > 0 && (
        <>
          <Separator className="bg-zinc-800" />
          <div className="space-y-2">
            <p className="text-[10px] text-zinc-500 uppercase tracking-widest font-medium">Data Gaps</p>
            <ul className="space-y-1">
              {report.data_gaps.map((gap, i) => (
                <li key={i} className="text-xs text-zinc-500 flex items-start gap-2">
                  <span className="text-zinc-700 mt-0.5">—</span>
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
