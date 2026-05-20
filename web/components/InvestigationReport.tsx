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
          <tr className="border-b border-zinc-800">
            {columns.map((col, i) => (
              <th key={i} className="text-left py-1.5 px-2 text-zinc-500 font-medium whitespace-nowrap">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 15).map((row, ri) => (
            <tr key={ri} className="border-b border-zinc-900 hover:bg-zinc-900/50">
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
    <div className="flex gap-4 flex-wrap">
      {numbers.map((n, i) => (
        <div key={i} className="flex flex-col">
          <span className="text-xs text-zinc-500">{n.label}</span>
          <div className="flex items-baseline gap-1.5">
            <span className="text-lg font-semibold text-white">{n.value}</span>
            {n.delta && (
              <span className={`text-xs font-medium ${n.delta.startsWith("-") ? "text-red-400" : "text-emerald-400"}`}>
                {n.delta}
              </span>
            )}
          </div>
          {n.context && <span className="text-[10px] text-zinc-600">{n.context}</span>}
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
    <div className="border border-zinc-800 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-3 py-2.5 bg-zinc-900/40 hover:bg-zinc-900/70 transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          {open ? (
            <ChevronDown className="h-3 w-3 text-zinc-500 flex-shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 text-zinc-500 flex-shrink-0" />
          )}
          <span className="text-sm text-zinc-200">{finding.title}</span>
          {finding.is_significant && (
            <span className="text-[10px] bg-orange-900/50 text-orange-300 px-1.5 py-0.5 rounded">significant</span>
          )}
          {finding.error && (
            <span className="text-[10px] bg-red-900/40 text-red-400 px-1.5 py-0.5 rounded">error</span>
          )}
        </div>
        <span className="text-xs text-zinc-600">{finding.row_count > 0 ? `${finding.row_count} rows` : ""}</span>
      </button>

      {open && (
        <div className="px-4 py-3 space-y-3">
          {/* Interpretation */}
          <p className="text-sm text-zinc-300 leading-relaxed">{finding.interpretation}</p>

          {/* Key numbers */}
          {finding.key_numbers.length > 0 && (
            <KeyNumbers numbers={finding.key_numbers} />
          )}

          {/* Stat note */}
          {finding.stat_note && (
            <div className="text-xs text-zinc-500 bg-zinc-900/50 px-3 py-1.5 rounded font-mono">
              {finding.stat_note}
            </div>
          )}

          {/* Chart */}
          {hasChart && (
            <FindingChart columns={finding.columns} rows={finding.rows} chartType={finding.chart_type} />
          )}

          {/* Table */}
          {hasData && (
            <div className="bg-zinc-950/50 rounded-lg p-2">
              <FindingTable columns={finding.columns} rows={finding.rows} />
            </div>
          )}

          {/* SQL toggle */}
          {finding.sql && (
            <div>
              <button
                onClick={() => setSqlOpen(v => !v)}
                className="flex items-center gap-1 text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors"
              >
                {sqlOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                SQL
              </button>
              {sqlOpen && (
                <pre className="mt-1 text-[11px] text-zinc-400 bg-zinc-950 border border-zinc-800 rounded p-3 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                  {finding.sql}
                </pre>
              )}
            </div>
          )}

          {/* Error */}
          {finding.error && (
            <div className="text-xs text-red-400 bg-red-950/30 px-3 py-2 rounded font-mono">
              {finding.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Phase section ──────────────────────────────────────────────────────────────

function PhaseSection({ phase, phaseIndex }: { phase: InvestigationPhase; phaseIndex: number }) {
  const [expanded, setExpanded] = useState(true);

  const statusIcon = {
    complete: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
    partial:  <CheckCircle2 className="h-4 w-4 text-amber-500" />,
    running:  <Loader2 className="h-4 w-4 text-sky-400 animate-spin" />,
    skipped:  <SkipForward className="h-4 w-4 text-zinc-600" />,
    error:    <AlertCircle className="h-4 w-4 text-red-500" />,
  }[phase.status] ?? <Loader2 className="h-4 w-4 text-zinc-500 animate-spin" />;

  const nonTrivialFindings = phase.findings.filter(f => f.chart_type !== "none" || f.columns.length > 0);

  return (
    <div className="space-y-3">
      {/* Phase header */}
      <div className="flex items-start gap-3">
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-base">{phase.phase_icon}</span>
          {statusIcon}
        </div>
        <div className="flex-1 min-w-0">
          <button
            onClick={() => setExpanded(v => !v)}
            className="flex items-center gap-2 text-left w-full group"
          >
            <span className="text-sm font-semibold text-zinc-200 group-hover:text-white">
              {phase.phase_name}
            </span>
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5 text-zinc-600" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 text-zinc-600" />
            )}
          </button>
          {/* Phase summary — always visible */}
          <p className="text-sm text-zinc-400 mt-0.5 leading-snug">{phase.summary}</p>
          {phase.skipped_reason && (
            <p className="text-xs text-zinc-600 italic mt-0.5">{phase.skipped_reason}</p>
          )}
        </div>
      </div>

      {/* Phase findings (expandable) */}
      {expanded && nonTrivialFindings.length > 0 && (
        <div className="ml-9 space-y-2">
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
        <div key={i} className="bg-zinc-900/40 border border-zinc-800 rounded-lg px-4 py-3 space-y-1">
          <p className="text-sm text-zinc-200 font-medium">{rec.action}</p>
          <div className="flex gap-3 flex-wrap text-xs text-zinc-500">
            {rec.expected_impact && <span>Impact: <span className="text-zinc-300">{rec.expected_impact}</span></span>}
            {rec.owner && <span>Owner: <span className="text-zinc-300">{rec.owner}</span></span>}
            {rec.timeline && <span>Timeline: <span className="text-zinc-300">{rec.timeline}</span></span>}
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
            <p className="text-xs text-zinc-600 uppercase tracking-wide">Attribution Waterfall</p>
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
            <p className="text-xs text-zinc-600 uppercase tracking-wide">Recommended Actions</p>
            <Recommendations recs={report.recommendations} />
          </div>
        </>
      )}

      {/* ── Data gaps ── */}
      {report && (report.data_gaps?.length ?? 0) > 0 && (
        <>
          <Separator className="bg-zinc-800" />
          <div className="space-y-2">
            <p className="text-xs text-zinc-600 uppercase tracking-wide">Data Gaps</p>
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
