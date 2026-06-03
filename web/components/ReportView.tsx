"use client";

import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { SqlResultTable } from "@/components/AugTable";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { DataQualityNote, Finding, Hypothesis, QueryCitation, Report, StatResult, Verdict } from "@/lib/types";
import { logOutcome, getInvestigationOutcomes, type RecOutcome, type RecStatus } from "@/lib/api";
import { InvestigationChart } from "@/components/InvestigationChart";
import { SHARE_COL_PATTERN, buildColumnFormatter } from "@/lib/formatCell";

interface Props {
  report: Report;
  queryCount: number;
  queryHistory?: QueryCitation[];
  queryMode?: "direct" | "investigate" | null;
  hypotheses?: Hypothesis[];
  invId?: string | null;
}

// ── Palette definitions ──────────────────────────────────────────────────────

const H_PALETTES = [
  { ring: "border-violet-500/40", dimBg: "bg-violet-500/5",  badge: "bg-violet-500/20 text-violet-300 border-violet-500/30",  divider: "divide-violet-500/10"  },
  { ring: "border-blue-500/40",   dimBg: "bg-blue-500/5",    badge: "bg-blue-500/20 text-blue-300 border-blue-500/30",        divider: "divide-blue-500/10"    },
  { ring: "border-emerald-500/40",dimBg: "bg-emerald-500/5", badge: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",divider: "divide-emerald-500/10" },
  { ring: "border-amber-500/40",  dimBg: "bg-amber-500/5",   badge: "bg-amber-500/20 text-amber-300 border-amber-500/30",     divider: "divide-amber-500/10"   },
  { ring: "border-rose-500/40",   dimBg: "bg-rose-500/5",    badge: "bg-rose-500/20 text-rose-300 border-rose-500/30",        divider: "divide-rose-500/10"    },
];

const VERDICT_STYLE: Record<Verdict, { label: string; chip: string; bar: string }> = {
  confirmed:    { label: "Confirmed",    chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400", bar: "bg-emerald-500" },
  refuted:      { label: "Refuted",      chip: "border-red-500/30 bg-red-500/10 text-red-400",             bar: "bg-red-500"     },
  inconclusive: { label: "Inconclusive", chip: "border-amber-500/30 bg-amber-500/10 text-amber-400",       bar: "bg-amber-500"   },
  untested:     { label: "Untested",     chip: "border-zinc-600 bg-zinc-800/50 text-zinc-500",              bar: "bg-zinc-700"    },
};

const STAT_STYLE: Record<StatResult["type"], { icon: string; chip: string }> = {
  anomaly:      { icon: "⚡", chip: "border-amber-500/20 bg-amber-500/5 text-amber-300"   },
  trend:        { icon: "↗",  chip: "border-blue-500/20 bg-blue-500/5 text-blue-300"      },
  comparison:   { icon: "⟺", chip: "border-violet-500/20 bg-violet-500/5 text-violet-300" },
  distribution: { icon: "≈",  chip: "border-zinc-600 bg-zinc-800/50 text-zinc-400"         },
};

// ── Collapsible section (used in bottom report sections) ─────────────────────

function CollapsibleSection({
  title,
  badge,
  titleClass = "text-zinc-300",
  children,
}: {
  title: string;
  badge?: React.ReactNode;
  titleClass?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 w-full text-left group py-1"
      >
        <h3 className={`text-sm font-semibold uppercase tracking-wide ${titleClass}`}>{title}</h3>
        {badge}
        <span className="ml-auto text-zinc-500 group-hover:text-zinc-400 text-xs transition">
          {open ? "▲" : "▼"}
        </span>
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  );
}

// ── Statistical signal callout ────────────────────────────────────────────────

function StatCallout({ stat }: { stat: StatResult }) {
  const s = STAT_STYLE[stat.type];
  return (
    <div className={`rounded border p-2.5 flex items-start gap-2.5 ${s.chip}`}>
      <span className="text-xs shrink-0 mt-0.5 font-mono">{s.icon}</span>
      <div className="min-w-0 space-y-0.5">
        <p className="text-xs leading-snug">{stat.interpretation}</p>
        {stat.sigma != null && (
          <p className="text-[11px] text-zinc-500 font-mono">
            {stat.sigma.toFixed(1)}σ{stat.p_value != null ? ` · p=${stat.p_value.toFixed(3)}` : ""}
          </p>
        )}
      </div>
    </div>
  );
}

// ── Query result mini-table ───────────────────────────────────────────────────

function QueryMiniTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  return <SqlResultTable columns={columns} rows={rows} maxHeight={280} />;
}

// ── Single query evidence block ───────────────────────────────────────────────

function QueryEvidence({
  query,
  index,
  total,
}: {
  query: QueryCitation;
  index: number;
  total: number;
}) {
  const [sqlOpen, setSqlOpen] = useState(false);
  const hasData = !query.error && (query.columns?.length ?? 0) > 0 && (query.rows?.length ?? 0) > 0;
  const significantStats = (query.stats ?? []).filter(s => s.is_significant);

  return (
    <div className="p-4 space-y-3">
      {/* Query header */}
      <div className="flex items-center gap-2.5">
        <span className="text-[11px] text-zinc-500 font-mono uppercase tracking-wide">
          Query {index + 1}/{total}
        </span>
        {query.error
          ? <span className="text-xs text-red-400 border border-red-500/20 bg-red-500/5 rounded px-1.5 py-0.5">✕ failed</span>
          : <span className="text-[11px] text-zinc-500 font-mono">{query.row_count} row{query.row_count !== 1 ? "s" : ""}</span>
        }
      </div>

      {/* Chart — InvestigationChart returns null when data isn't chartable */}
      {hasData && (
        <InvestigationChart columns={query.columns!} rows={query.rows!} />
      )}

      {/* Table — always show when data fits; complements the chart */}
      {hasData && (
        <QueryMiniTable columns={query.columns!} rows={query.rows!} />
      )}

      {/* Error detail */}
      {query.error && (
        <pre className="text-xs text-red-400 bg-red-500/5 rounded border border-red-500/20 p-2.5 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
          {query.error}
        </pre>
      )}

      {/* Statistical signals */}
      {significantStats.length > 0 && (
        <div className="space-y-1.5">
          {significantStats.map((s, i) => <StatCallout key={i} stat={s} />)}
        </div>
      )}

      {/* SQL toggle */}
      <div>
        <button
          onClick={() => setSqlOpen(o => !o)}
          className="flex items-center gap-1.5 text-[11px] text-zinc-500 hover:text-zinc-400 transition font-mono uppercase tracking-wide"
        >
          <span className="text-[8px]">{sqlOpen ? "▼" : "▶"}</span> SQL
        </button>
        {sqlOpen && (
          <pre className="mt-1.5 text-xs text-zinc-400 bg-zinc-800 rounded border border-zinc-600/60 p-2.5 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
            {query.sql}
          </pre>
        )}
      </div>
    </div>
  );
}

// ── Hypothesis accordion row ──────────────────────────────────────────────────

function HypothesisAccordion({
  index,
  hypothesis,
  queries,
  linkedFinding,
}: {
  index: number;
  hypothesis: Hypothesis;
  queries: QueryCitation[];
  linkedFinding: Finding | null;
}) {
  const [open, setOpen] = useState(false);
  const palette = H_PALETTES[index % H_PALETTES.length];
  const vc = VERDICT_STYLE[hypothesis.verdict];

  return (
    <div className={`rounded-lg border ${palette.ring} overflow-hidden`}>
      {/* ── Header ── */}
      <button
        onClick={() => setOpen(o => !o)}
        className={`w-full text-left px-4 py-3 transition group ${open ? palette.dimBg : "hover:bg-zinc-700/40"}`}
      >
        <div className="flex items-start gap-3">
          {/* H-label badge */}
          <span className={`mt-0.5 shrink-0 text-xs font-mono font-semibold px-1.5 py-0.5 rounded border ${palette.badge}`}>
            H{index + 1}
          </span>

          {/* Description */}
          <p className="text-sm text-zinc-200 flex-1 leading-snug text-left">
            {hypothesis.description}
          </p>

          {/* Verdict + confidence + toggle */}
          <div className="flex items-center gap-2 shrink-0 ml-2">
            <span className={`text-[11px] font-medium px-1.5 py-0.5 rounded border ${vc.chip}`}>
              {vc.label}
            </span>
            <span className="text-[11px] font-mono text-zinc-500 w-8 text-right">
              {Math.round(hypothesis.confidence * 100)}%
            </span>
            <span className="text-zinc-500 text-[11px] group-hover:text-zinc-400 transition">
              {open ? "▲" : "▼"}
            </span>
          </div>
        </div>

        {/* Confidence bar */}
        <div className="mt-2.5 ml-10 h-[3px] rounded-full bg-zinc-800 overflow-hidden">
          <div
            className={`h-full rounded-full ${vc.bar} transition-all duration-300`}
            style={{ width: `${hypothesis.confidence * 100}%` }}
          />
        </div>
      </button>

      {/* ── Expanded detail ── */}
      {open && (
        <div className={`border-t ${palette.ring} divide-y divide-zinc-600/50`}>

          {/* 1. Key finding */}
          <div className="px-4 py-3 space-y-1.5">
            <p className="text-[11px] text-zinc-500 uppercase tracking-widest font-mono">Key Finding</p>
            <p className="text-sm text-zinc-200 leading-relaxed">
              {hypothesis.key_finding || "No finding recorded for this hypothesis."}
            </p>
          </div>

          {/* 2. Queries — each with chart + table + stats + SQL */}
          {queries.length === 0 ? (
            <div className="px-4 py-3">
              <p className="text-xs text-zinc-500 italic">No queries were executed for this hypothesis.</p>
            </div>
          ) : (
            <div className={`divide-y divide-zinc-600/50`}>
              {queries.map((q, i) => (
                <QueryEvidence key={i} query={q} index={i} total={queries.length} />
              ))}
            </div>
          )}

          {/* 3. Synthesis link — if the final report references this hypothesis */}
          {linkedFinding && (
            <div className="px-4 py-3 space-y-2">
              <p className="text-[11px] text-zinc-500 uppercase tracking-widest font-mono">Report Synthesis</p>
              <blockquote className="border-l-2 border-emerald-500/40 pl-3 space-y-1">
                <p className="text-sm text-zinc-200 leading-relaxed italic">&quot;{linkedFinding.claim}&quot;</p>
                {linkedFinding.evidence && (
                  <p className="text-xs text-zinc-500 leading-relaxed">{linkedFinding.evidence}</p>
                )}
              </blockquote>
              <Badge
                variant="outline"
                className={linkedFinding.confidence >= 0.7
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-400"
                }
              >
                {Math.round(linkedFinding.confidence * 100)}% confidence
              </Badge>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Hypothesis panel ──────────────────────────────────────────────────────────

function HypothesisPanel({
  hypotheses,
  queryHistory,
  reportFindings,
}: {
  hypotheses: Hypothesis[];
  queryHistory: QueryCitation[];
  reportFindings: Finding[];
}) {
  const tested = hypotheses.filter(h => h.verdict !== "untested");
  const confirmed = tested.filter(h => h.verdict === "confirmed").length;
  const refuted = tested.filter(h => h.verdict === "refuted").length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wide">
          Hypotheses Tested
        </h3>
        <div className="flex items-center gap-2 text-[11px] font-mono">
          {confirmed > 0 && <span className="text-emerald-400">{confirmed} confirmed</span>}
          {confirmed > 0 && refuted > 0 && <span className="text-zinc-500">·</span>}
          {refuted > 0 && <span className="text-red-400">{refuted} refuted</span>}
          {(confirmed > 0 || refuted > 0) && tested.length - confirmed - refuted > 0 && <span className="text-zinc-500">·</span>}
          {tested.length - confirmed - refuted > 0 && <span className="text-amber-400">{tested.length - confirmed - refuted} inconclusive</span>}
        </div>
      </div>

      <div className="space-y-2">
        {hypotheses.map((h, i) => (
          <HypothesisAccordion
            key={h.id}
            index={i}
            hypothesis={h}
            queries={queryHistory.filter(
              q => q.hypothesis_id?.toUpperCase() === h.id?.toUpperCase()
            )}
            linkedFinding={
              reportFindings.find(
                f => f.hypothesis_id?.toUpperCase() === h.id?.toUpperCase()
              ) ?? null
            }
          />
        ))}
      </div>
    </div>
  );
}

// ── Key Finding card ─────────────────────────────────────────────────────────

function KeyFindingCard({
  finding,
  index,
  hypotheses,
}: {
  finding: Finding;
  index: number;
  hypotheses: Hypothesis[];
}) {
  const [open, setOpen] = useState(false);
  const linkedHypothesis = finding.hypothesis_id
    ? hypotheses.find(h => h.id.toUpperCase() === finding.hypothesis_id!.toUpperCase())
    : null;
  const hypothesisIndex = linkedHypothesis
    ? hypotheses.indexOf(linkedHypothesis)
    : -1;
  const palette = hypothesisIndex >= 0 ? H_PALETTES[hypothesisIndex % H_PALETTES.length] : null;

  const confidenceLabel =
    finding.confidence >= 0.8 ? { text: "High confidence", color: "text-emerald-400", dot: "bg-emerald-400" } :
    finding.confidence >= 0.5 ? { text: "Moderate confidence", color: "text-amber-400", dot: "bg-amber-400" } :
                                 { text: "Low confidence", color: "text-red-400", dot: "bg-red-400" };

  return (
    <div className="rounded-lg border border-zinc-600 bg-zinc-800/50 overflow-hidden">
      {/* Header row */}
      <div className="flex items-start gap-3 p-4">
        {/* Index circle */}
        <span className="shrink-0 flex h-6 w-6 items-center justify-center rounded-full bg-zinc-800 border border-zinc-600 text-xs font-mono text-zinc-400 mt-0.5">
          {index + 1}
        </span>

        <div className="flex-1 min-w-0 space-y-2">
          {/* Claim */}
          <p className="text-sm font-medium text-zinc-100 leading-snug">{finding.claim}</p>

          {/* Meta row: confidence + hypothesis link */}
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-1.5">
              <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${confidenceLabel.dot}`} />
              <span className={`text-xs ${confidenceLabel.color}`}>{confidenceLabel.text}</span>
            </div>
            {/* Confidence bar */}
            <div className="flex items-center gap-1.5">
              <div className="w-20 h-1 rounded-full bg-zinc-800 overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    finding.confidence >= 0.8 ? "bg-emerald-500" :
                    finding.confidence >= 0.5 ? "bg-amber-500" : "bg-red-500"
                  }`}
                  style={{ width: `${finding.confidence * 100}%` }}
                />
              </div>
              <span className="text-[11px] font-mono text-zinc-500">
                {Math.round(finding.confidence * 100)}%
              </span>
            </div>
            {/* Hypothesis chip */}
            {palette && hypothesisIndex >= 0 && (
              <span className={`text-[11px] font-mono px-1.5 py-0.5 rounded border ${palette.badge}`}>
                H{hypothesisIndex + 1}
              </span>
            )}
          </div>
        </div>

        {/* Expand toggle for evidence */}
        {finding.evidence && (
          <button
            onClick={() => setOpen(o => !o)}
            className="shrink-0 text-[11px] text-zinc-500 hover:text-zinc-400 border border-zinc-600 hover:border-zinc-600 rounded px-2 py-1 transition mt-0.5"
          >
            {open ? "Less" : "Evidence"}
          </button>
        )}
      </div>

      {/* Expandable evidence */}
      {open && finding.evidence && (
        <div className="px-4 pb-4 pt-0">
          <div className="rounded border border-zinc-600/60 bg-zinc-800/50 p-3 space-y-1.5">
            <p className="text-[11px] text-zinc-500 uppercase tracking-widest font-mono">Supporting Evidence</p>
            <p className="text-sm text-zinc-300 leading-relaxed">{finding.evidence}</p>
            {linkedHypothesis && (
              <p className="text-xs text-zinc-500 mt-1 pt-1.5 border-t border-zinc-600">
                From hypothesis: <span className="text-zinc-400 italic">&quot;{linkedHypothesis.description}&quot;</span>
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Outcome status styles ─────────────────────────────────────────────────────

const STATUS_STYLE: Record<RecStatus, { label: string; chip: string }> = {
  accepted:    { label: "Accepted",    chip: "border-blue-500/30 bg-blue-500/10 text-blue-400"       },
  implemented: { label: "Implemented", chip: "border-violet-500/30 bg-violet-500/10 text-violet-400" },
  verified:    { label: "Verified",    chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" },
  rejected:    { label: "Rejected",    chip: "border-red-500/30 bg-red-500/10 text-red-400"          },
  dismissed:   { label: "Dismissed",   chip: "border-zinc-600 bg-zinc-800/50 text-zinc-500"          },
};

function RecommendationCard({
  action,
  index,
  invId,
  existingOutcome,
}: {
  action: string;
  index: number;
  invId: string;
  existingOutcome: RecOutcome | undefined;
}) {
  const [outcome, setOutcome] = useState<RecOutcome | undefined>(existingOutcome);
  const [saving, setSaving] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const mark = useCallback(async (status: RecStatus) => {
    setSaving(true);
    setMenuOpen(false);
    try {
      const result = await logOutcome(invId, index, action, status);
      setOutcome(result);
    } catch {
      /* silent */
    } finally {
      setSaving(false);
    }
  }, [invId, index, action]);

  const current = outcome ? STATUS_STYLE[outcome.status] : null;

  return (
    <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-3 flex items-start gap-3">
      <span className="shrink-0 flex h-5 w-5 items-center justify-center rounded-full bg-violet-500/20 border border-violet-500/30 text-xs font-mono text-violet-300 mt-0.5">
        {index + 1}
      </span>
      <p className="text-sm text-zinc-300 leading-relaxed flex-1">{action}</p>
      <div className="shrink-0 relative">
        {current ? (
          <div className="flex items-center gap-1.5">
            <span className={`text-[11px] font-medium px-1.5 py-0.5 rounded border ${current.chip}`}>
              {current.label}
            </span>
            <button
              onClick={() => setMenuOpen(o => !o)}
              className="text-[11px] text-zinc-500 hover:text-zinc-400 transition px-1"
              title="Change status"
            >
              ▾
            </button>
          </div>
        ) : (
          <button
            onClick={() => setMenuOpen(o => !o)}
            disabled={saving}
            className="text-[11px] text-zinc-500 hover:text-zinc-300 border border-zinc-600 hover:border-zinc-500 rounded px-2 py-1 transition whitespace-nowrap"
          >
            {saving ? "…" : "Mark"}
          </button>
        )}
        {menuOpen && (
          <div className="absolute right-0 top-full mt-1 z-20 w-36 rounded-lg border border-zinc-600 bg-zinc-900 shadow-xl overflow-hidden">
            {(["accepted", "implemented", "verified", "rejected", "dismissed"] as RecStatus[]).map(s => (
              <button
                key={s}
                onClick={() => mark(s)}
                className="w-full text-left px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800 transition capitalize"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main ReportView ───────────────────────────────────────────────────────────

export function ReportView({ report, queryCount, queryHistory = [], queryMode, hypotheses = [], invId }: Props) {
  const dqNotes = report.data_quality_notes ?? [];
  const isDirect = queryMode === "direct";

  const [outcomes, setOutcomes] = useState<RecOutcome[]>([]);
  useEffect(() => {
    if (!invId) return;
    getInvestigationOutcomes(invId).then(setOutcomes).catch(() => {});
  }, [invId]);
  const isQueryFailure = isDirect && !report.verdict && report.headline === "Query execution failed";

  const directTable = isDirect
    ? queryHistory.find(q => !q.error && q.columns?.length && q.rows?.length)
    : undefined;

  return (
    <div className="space-y-6">
      {/* 1. Verdict / Headline */}
      <div className={`rounded-lg border p-5 ${isQueryFailure ? "border-red-500/30 bg-red-500/5" : "border-emerald-500/30 bg-emerald-500/5"}`}>
        <p className={`text-xs font-medium uppercase tracking-widest mb-2 ${isQueryFailure ? "text-red-400" : "text-emerald-400"}`}>
          {isQueryFailure ? "Query Failed" : isDirect ? "Top Insight" : "Verdict"}
        </p>
        <p className="text-lg font-semibold text-white leading-snug">{report.headline}</p>
      </div>

      {/* 2. Diagnosis / Executive Summary */}
      {!isQueryFailure && (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wide">
            {isDirect ? "Executive Summary" : "Diagnosis"}
          </h3>
          <p className="text-sm text-zinc-300 leading-relaxed">{report.verdict}</p>

          {/* Key findings — rich cards for both modes */}
          {(report.key_findings ?? []).length > 0 && (
            <div className="space-y-2 pt-1">
              <p className="text-xs text-zinc-500 uppercase tracking-widest font-mono">Key Findings</p>
              {(report.key_findings ?? []).map((f, i) => (
                <KeyFindingCard key={i} finding={f} index={i} hypotheses={hypotheses} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* 3. Hypothesis accordion — investigate mode (before separator) */}
      {!isDirect && hypotheses.length > 0 && (
        <HypothesisPanel
          hypotheses={hypotheses}
          queryHistory={queryHistory}
          reportFindings={report.key_findings}
        />
      )}

      {/* 4. Chart — direct mode */}
      {isDirect && !isQueryFailure && directTable?.columns && directTable?.rows && (
        <InvestigationChart columns={directTable.columns} rows={directTable.rows} />
      )}

      {/* 5. KPI highlight — single-row scalar */}
      {isDirect && !isQueryFailure && directTable && <KPIHighlight table={directTable} />}

      {/* 6. Query results table — direct mode */}
      {isDirect && !isQueryFailure && directTable && (
        <DirectResultTable table={directTable} />
      )}

      <Separator className="bg-zinc-800" />

      {/* 7. Data Quality Issues */}
      {dqNotes.length > 0 && (
        <CollapsibleSection
          title={isQueryFailure ? "Execution Error" : "Data Quality Issues"}
          titleClass="text-orange-400"
          badge={
            <Badge variant="outline" className="border-orange-500/30 bg-orange-500/10 text-orange-400 text-xs">
              {isQueryFailure ? "query failed" : `${dqNotes.length} found`}
            </Badge>
          }
        >
          <p className="text-xs text-zinc-500 mb-3">
            {isQueryFailure
              ? "The query was automatically corrected and retried but still could not execute successfully."
              : "These structural issues were detected during the investigation and may affect analysis accuracy."}
          </p>
          <div className="space-y-3">
            {dqNotes.map((note, i) => <DataQualityCard key={i} note={note} />)}
          </div>
        </CollapsibleSection>
      )}

      {/* 8. Risks */}
      {(report.risks ?? []).length > 0 && (
        <CollapsibleSection title="Risks & Considerations">
          <div className="space-y-2">
            {(report.risks ?? []).map((risk, i) => (
              <div key={i} className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 flex items-start gap-3 border-l-2 border-l-amber-500/50">
                <span className="shrink-0 mt-0.5 text-amber-400 text-xs">⚠</span>
                <p className="text-sm text-zinc-300 leading-relaxed">{risk}</p>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {/* 9. Recommended Actions */}
      {(report.recommended_actions ?? []).length > 0 && (
        <CollapsibleSection title="Recommended Actions">
          <div className="space-y-2">
            {(report.recommended_actions ?? []).map((action, i) => (
              invId ? (
                <RecommendationCard
                  key={i}
                  action={action}
                  index={i}
                  invId={invId}
                  existingOutcome={outcomes.find(o => o.rec_index === i)}
                />
              ) : (
                <div key={i} className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-3 flex items-start gap-3">
                  <span className="shrink-0 flex h-5 w-5 items-center justify-center rounded-full bg-violet-500/20 border border-violet-500/30 text-xs font-mono text-violet-300 mt-0.5">
                    {i + 1}
                  </span>
                  <p className="text-sm text-zinc-300 leading-relaxed">{action}</p>
                </div>
              )
            ))}
          </div>
        </CollapsibleSection>
      )}

      {/* 10. Excluded Causes */}
      {(report.what_is_not_the_cause ?? []).length > 0 && (
        <CollapsibleSection title="Excluded Causes" titleClass="text-zinc-500">
          <ul className="space-y-1">
            {(report.what_is_not_the_cause ?? []).map((item, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-zinc-500 leading-relaxed">
                <span className="mt-0.5 text-red-500/60 shrink-0">✕</span>
                {item}
              </li>
            ))}
          </ul>
        </CollapsibleSection>
      )}

      <p className="text-xs text-zinc-500 text-center font-mono">
        {queryCount} SQL quer{queryCount === 1 ? "y" : "ies"} executed
      </p>
    </div>
  );
}

// ── Direct mode helpers ───────────────────────────────────────────────────────

function KPIHighlight({ table }: { table: QueryCitation }) {
  const columns = table.columns ?? [];
  const rows = table.rows ?? [];
  if (rows.length !== 1 || columns.length === 0) return null;

  const row = rows[0] as unknown[];
  const metrics = columns
    .map((col, i) => ({ col, val: row[i] }))
    .filter(({ val }) => val !== null && !isNaN(Number(val)) && Number(val) !== 0);

  if (!metrics.length) return null;

  const fmt = (col: string, v: unknown) => {
    const n = Number(v);
    if (SHARE_COL_PATTERN.test(col) && n >= 0 && n <= 1) return `${(n * 100).toFixed(2)}%`;
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    if (n % 1 !== 0) return n.toFixed(2);
    return n.toLocaleString();
  };

  return (
    <div className={`grid gap-3 ${metrics.length > 2 ? "grid-cols-3" : metrics.length === 2 ? "grid-cols-2" : "grid-cols-1"}`}>
      {metrics.slice(0, 3).map(({ col, val }) => (
        <div key={col} className="rounded-lg border border-zinc-600 bg-zinc-800/60 p-4 text-center space-y-1">
          <p className="text-2xl font-mono font-semibold text-emerald-400 tracking-tight">{fmt(col, val)}</p>
          <p className="text-xs text-zinc-500 uppercase tracking-wide">{col.replace(/_/g, " ")}</p>
        </div>
      ))}
    </div>
  );
}

function DirectResultTable({ table }: { table: QueryCitation }) {
  const columns = table.columns ?? [];
  const rows = table.rows ?? [];
  const fmt = buildColumnFormatter(columns, rows as unknown[][]);
  const VISIBLE_ROWS = 20;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wide">Query Results</h3>
        <span className="text-xs text-zinc-500 font-mono">
          {table.row_count} row{table.row_count !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="rounded-lg border border-zinc-600 overflow-hidden">
        <div className="overflow-x-auto overflow-y-auto max-h-[400px]">
          <Table>
            <TableHeader>
              <TableRow className="border-zinc-600 hover:bg-transparent">
                {columns.map(col => (
                  <TableHead key={col} className="text-xs text-zinc-500 font-mono whitespace-nowrap bg-zinc-800/80 h-8">
                    {col}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, ri) => (
                <TableRow key={ri} className="border-zinc-600/50 hover:bg-zinc-700/30">
                  {(row as unknown[]).map((cell, ci) => (
                    <TableCell key={ci} className="text-xs text-zinc-300 font-mono py-1.5 whitespace-nowrap">
                      {cell === null || cell === undefined ? (
                        <span className="text-zinc-500 italic">null</span>
                      ) : (
                        fmt(ci, cell)
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
      <details className="group">
        <summary className="text-xs text-zinc-500 cursor-pointer hover:text-zinc-400 transition list-none flex items-center gap-1">
          <span className="group-open:hidden">▶</span>
          <span className="hidden group-open:inline">▼</span>
          SQL
        </summary>
        <pre className="mt-1 text-xs text-zinc-400 bg-zinc-800 rounded p-3 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
          {table.sql}
        </pre>
      </details>
    </div>
  );
}

function DataQualityCard({ note }: { note: DataQualityNote }) {
  const target = note.column ? `${note.table}.${note.column}` : note.table;
  return (
    <div className="rounded-lg border border-orange-500/20 bg-orange-500/5 p-4 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <code className="text-xs font-mono text-orange-300 bg-orange-500/10 px-2 py-0.5 rounded">
          {target}
        </code>
      </div>
      <p className="text-sm text-zinc-300 whitespace-pre-wrap font-mono text-xs leading-relaxed">{note.issue}</p>
      <p className="text-xs text-zinc-500">
        <span className="text-zinc-400 font-medium">Impact: </span>{note.impact}
      </p>
      <div className="border-t border-orange-500/10 pt-2">
        <p className="text-xs text-zinc-500">
          <span className="text-orange-400 font-medium">Fix: </span>{note.recommended_fix}
        </p>
      </div>
    </div>
  );
}
