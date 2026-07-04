"use client";

import { useState } from "react";
import type { ExplorationReport as ExplorationReportType, SubQuestion, SubQuestionAnswer } from "@/lib/types";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { BriefDetails, BriefDetailBlock } from "@/components/brief/Brief";
import { recordVerdict } from "@/lib/api";

interface Props {
  report: ExplorationReportType;
  subQuestions: SubQuestion[];
  subqAnswers: SubQuestionAnswer[];
  queryCount: number;
  connectionId?: string;
  investigationId?: string;
}

// ── Purpose chip (the one allowed accent) ─────────────────────────────────────

const PURPOSE_STYLE: Record<string, { label: string; chip: string; icon: string }> = {
  landscape:    { label: "Landscape",    icon: "◎", chip: "border-blue-500/30 text-blue-400"     },
  relationship: { label: "Relationship", icon: "⟺", chip: "border-violet-500/30 text-violet-400" },
  threshold:    { label: "Threshold",    icon: "↯", chip: "border-amber-500/30 text-amber-400"    },
  drill_down:   { label: "Drill-down",   icon: "⇣", chip: "border-rose-500/30 text-rose-400"      },
  confounder:   { label: "Confounder",   icon: "⊕", chip: "border-emerald-500/30 text-emerald-400"},
  synthesis:    { label: "Synthesis",    icon: "✦", chip: "border-zinc-500/30 text-zinc-400"      },
};

// One small uppercase section label, used everywhere for a consistent rhythm.
function SectionLabel({ children }: { children: React.ReactNode }) {
  return <p className="aug-fs-xs uppercase tracking-wide text-zinc-500">{children}</p>;
}

// ── Sub-question step — chart + table shown upfront, only SQL collapsed ────────

function SubQuestionCard({
  answer,
  index,
  last,
}: {
  answer: SubQuestionAnswer;
  index: number;
  last: boolean;
}) {
  const [sqlOpen, setSqlOpen] = useState(false);
  const ps = PURPOSE_STYLE[answer.purpose] ?? PURPOSE_STYLE.landscape;
  const hasData = !answer.error && answer.columns.length > 0 && answer.rows.length > 0;

  return (
    <div className="relative">
      {/* Connector rail */}
      {!last && <div className="absolute left-[15px] top-9 bottom-0 w-px bg-zinc-800/80 pointer-events-none" />}

      <div className="flex gap-3 pb-6">
        {/* Step number */}
        <div className="shrink-0 z-10">
          <div className="h-8 w-8 rounded-[var(--r-pill)] border border-zinc-700 bg-zinc-900 flex items-center justify-center aug-fs-sm font-mono text-zinc-400">
            {index + 1}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 space-y-2.5">
          {/* Question + purpose chip */}
          <div className="flex items-start gap-2 flex-wrap">
            <span className={`aug-fs-xs font-mono px-1.5 py-0.5 rounded border shrink-0 ${ps.chip}`}>
              {ps.icon} {ps.label}
            </span>
            <p className="aug-fs-ui text-zinc-300 leading-snug flex-1 min-w-0">{answer.question}</p>
          </div>

          {/* Answer takeaway */}
          {answer.answer && (
            <p className="aug-fs-ui text-zinc-100 leading-relaxed">{answer.answer}</p>
          )}

          {/* Evidence — chart with grain-aware controls + chart⇄table toggle */}
          {hasData && (
            <ResultChartCard columns={answer.columns} rows={answer.rows} />
          )}

          {answer.error && (
            <pre className="aug-fs-sm text-red-400/90 rounded border border-red-500/20 p-2.5 overflow-x-auto whitespace-pre-wrap font-code" style={{ background: "var(--bg-0)" }}>
              {answer.error}
            </pre>
          )}

          {/* Insight */}
          {answer.insight && answer.insight !== answer.answer && (
            <p className="aug-fs-sm text-zinc-400 leading-relaxed border-t border-zinc-800/60 pt-2">
              <span className="text-zinc-500 uppercase tracking-wide aug-fs-xs mr-1.5">Insight</span>
              {answer.insight}
            </p>
          )}

          {/* Refinement (what it led to next) */}
          {answer.refinement && (
            <p className="aug-fs-sm text-zinc-500 leading-relaxed">→ {answer.refinement}</p>
          )}

          {/* SQL — the only collapsed detail */}
          {(hasData || answer.error) && answer.sql && (
            <div>
              <button
                onClick={() => setSqlOpen(o => !o)}
                className="aug-fs-xs text-zinc-500 hover:text-zinc-400 transition flex items-center gap-1"
              >
                <span className="inline-block w-2">{sqlOpen ? "▼" : "▶"}</span> SQL
              </button>
              {sqlOpen && (
                <pre className="mt-1.5 aug-fs-sm text-zinc-400 rounded border border-zinc-800 p-2.5 overflow-x-auto whitespace-pre-wrap font-code leading-relaxed" style={{ background: "var(--bg-0)" }}>
                  {answer.sql}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

const BAND_STYLE: Record<string, string> = {
  high:   "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  medium: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  low:    "border-rose-500/40 bg-rose-500/10 text-rose-300",
};

function ConfidenceChip({ band, earned }: { band: string; earned: number }) {
  return (
    <span className={`shrink-0 aug-fs-xs font-mono uppercase tracking-wide px-2 py-0.5 rounded border ${BAND_STYLE[band] ?? BAND_STYLE.low}`}
      title="Computed from guard coverage × chain completeness × data trust — not asserted by the model.">
      {band} confidence · {Math.round(earned * 100)}%
    </span>
  );
}

const CHECK_MARK: Record<string, { sym: string; cls: string }> = {
  ran:     { sym: "✓", cls: "text-emerald-400" },
  not_run: { sym: "⊘", cls: "text-rose-400" },
  "n/a":   { sym: "–", cls: "text-zinc-600" },
};

function VerificationPanel({ v }: { v: NonNullable<ExplorationReportType["verification"]> }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-x-5 gap-y-1 aug-fs-xs text-zinc-400 font-mono">
        <span>earned confidence <span className="text-zinc-200">{Math.round(v.earned_confidence * 100)}%</span></span>
        <span>data trust <span className="text-zinc-200">{Math.round(v.data_trust * 100)}%</span></span>
        <span>guard coverage <span className="text-zinc-200">{Math.round(v.coverage * 100)}%</span></span>
      </div>
      <ul className="space-y-1">
        {v.checks.map((c) => {
          const m = CHECK_MARK[c.status] ?? CHECK_MARK["n/a"];
          return (
            <li key={c.name} className="flex items-start gap-2 leading-relaxed">
              <span className={`shrink-0 mt-0.5 w-3 text-center ${m.cls}`}>{m.sym}</span>
              <span>
                <span className={c.status === "not_run" ? "text-rose-300" : "text-zinc-300"}>{c.label}</span>
                {c.status === "not_run" && <span className="text-rose-400/80"> — did not run</span>}
                {c.detail && <span className="text-zinc-500"> · {c.detail}</span>}
              </span>
            </li>
          );
        })}
      </ul>
      {v.signals.length > 0 && (
        <ul className="space-y-1 pt-1">
          {v.signals.map((s, i) => (
            <li key={i} className="aug-fs-xs text-zinc-500 flex items-start gap-2">
              <span className="shrink-0 mt-0.5">·</span><span>{s}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FindingVerdict({ headline, connectionId, investigationId }: {
  headline: string; connectionId?: string; investigationId?: string;
}) {
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const send = async (verdict: "accept" | "correct" | "reject") => {
    if (busy) return;
    setBusy(true);
    try {
      await recordVerdict({ verdict, connectionId, investigationId, headline });
      setDone(verdict);
    } catch {
      setDone(null);
    } finally {
      setBusy(false);
    }
  };
  if (done) {
    return (
      <div className="border-t border-zinc-800/60 pt-4 aug-fs-xs text-zinc-500">
        Thanks — recorded as <span className="text-zinc-300">{done}</span>. This calibrates future confidence.
      </div>
    );
  }
  const btn = "aug-fs-xs px-2.5 py-1 rounded border transition-colors disabled:opacity-50";
  return (
    <div className="border-t border-zinc-800/60 pt-4 flex items-center gap-2 flex-wrap">
      <span className="aug-fs-xs text-zinc-500 mr-1">Was this finding right?</span>
      <button disabled={busy} onClick={() => send("accept")}
        className={`${btn} border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10`}>Accept</button>
      <button disabled={busy} onClick={() => send("correct")}
        className={`${btn} border-amber-500/40 text-amber-300 hover:bg-amber-500/10`}>Partly</button>
      <button disabled={busy} onClick={() => send("reject")}
        className={`${btn} border-rose-500/40 text-rose-300 hover:bg-rose-500/10`}>Reject</button>
    </div>
  );
}

export function ExplorationReportView({ report, subqAnswers, queryCount, connectionId, investigationId }: Props) {
  const dqNotes = report.data_quality_notes ?? [];
  const showNarrative = report.narrative && report.narrative.trim() !== (report.conclusion ?? "").trim();

  return (
    <div className="space-y-6 aug-fs-ui text-zinc-300">
      {/* Answer */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-3">
          <SectionLabel>Answer</SectionLabel>
          {report.verification && (
            <ConfidenceChip band={report.verification.confidence_band} earned={report.verification.earned_confidence} />
          )}
        </div>
        <p className="aug-fs-h2 font-medium text-zinc-100 leading-snug">{report.headline}</p>
      </div>

      {/* Summary — conclusion + narrative merged into one block */}
      {(report.conclusion || showNarrative) && (
        <div className="border-t border-zinc-800/60 pt-4 space-y-2">
          <SectionLabel>Summary</SectionLabel>
          {report.conclusion && <p className="leading-relaxed">{report.conclusion}</p>}
          {showNarrative && <p className="leading-relaxed text-zinc-400">{report.narrative}</p>}
        </div>
      )}

      {/* Investigative chain */}
      {subqAnswers.length > 0 && (
        <div className="border-t border-zinc-800/60 pt-4 space-y-3">
          <SectionLabel>Investigative chain · {subqAnswers.length} step{subqAnswers.length !== 1 ? "s" : ""}</SectionLabel>
          <div>
            {subqAnswers.map((a, i) => (
              <SubQuestionCard key={a.subq_id} answer={a} index={i} last={i === subqAnswers.length - 1} />
            ))}
          </div>
        </div>
      )}

      {/* Machinery — recommended actions, data quality, and verification fold into one
          quiet Details toggle so the explore answer reads as a conversation, not a report
          (Option A, consistent with the quick + deep answers). */}
      {(report.recommended_actions.length > 0 || dqNotes.length > 0 || report.verification) && (
        <BriefDetails summary="Details">
          {report.recommended_actions.length > 0 && (
            <BriefDetailBlock label="Recommended actions">
              <ol className="space-y-2">
                {report.recommended_actions.map((action, i) => (
                  <li key={i} className="flex items-start gap-2.5">
                    <span className="shrink-0 mt-0.5 w-5 h-5 rounded-[var(--r-pill)] border border-zinc-700 text-zinc-400 aug-fs-xs font-mono flex items-center justify-center">
                      {i + 1}
                    </span>
                    <p className="leading-relaxed">{action}</p>
                  </li>
                ))}
              </ol>
            </BriefDetailBlock>
          )}

          {dqNotes.length > 0 && (
            <BriefDetailBlock label="Data quality">
              <ul className="space-y-1.5">
                {dqNotes.map((note, i) => (
                  <li key={i} className="leading-relaxed flex items-start gap-2">
                    <span className="shrink-0 mt-0.5 text-zinc-500">—</span>
                    <span>
                      <code className="aug-fs-sm text-zinc-400">{note.column ? `${note.table}.${note.column}` : note.table}</code>
                      <span className="text-zinc-400"> {note.issue}</span>
                      {note.recommended_fix && <span className="text-zinc-500"> · Fix: {note.recommended_fix}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </BriefDetailBlock>
          )}

          {report.verification && (
            <BriefDetailBlock label="Verification">
              <VerificationPanel v={report.verification} />
            </BriefDetailBlock>
          )}
        </BriefDetails>
      )}

      {/* Human ground-truth capture (Bet 0, 0-V) — the non-circular calibration anchor */}
      {investigationId && (
        <FindingVerdict headline={report.headline} connectionId={connectionId} investigationId={investigationId} />
      )}

      <p className="aug-fs-xs text-zinc-500 pt-1">
        {queryCount} quer{queryCount === 1 ? "y" : "ies"} · {subqAnswers.length} step{subqAnswers.length !== 1 ? "s" : ""}
      </p>
    </div>
  );
}
