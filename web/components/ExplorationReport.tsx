"use client";

import { useState } from "react";
import type { ExplorationReport as ExplorationReportType, SubQuestion, SubQuestionAnswer, DataQualityNote } from "@/lib/types";
import { InvestigationChart } from "@/components/InvestigationChart";
import { SqlResultTable } from "@/components/AugTable";

interface Props {
  report: ExplorationReportType;
  subQuestions: SubQuestion[];
  subqAnswers: SubQuestionAnswer[];
  queryCount: number;
}

// ── Purpose badge ─────────────────────────────────────────────────────────────

const PURPOSE_STYLE: Record<string, { label: string; chip: string; icon: string }> = {
  landscape:    { label: "Landscape",    icon: "◎", chip: "border-blue-500/30 bg-blue-500/10 text-blue-400"        },
  relationship: { label: "Relationship", icon: "⟺", chip: "border-violet-500/30 bg-violet-500/10 text-violet-400"  },
  threshold:    { label: "Threshold",    icon: "↯", chip: "border-amber-500/30 bg-amber-500/10 text-amber-400"      },
  drill_down:   { label: "Drill-down",   icon: "⇣", chip: "border-rose-500/30 bg-rose-500/10 text-rose-400"        },
  confounder:   { label: "Confounder",   icon: "⊕", chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"},
  synthesis:    { label: "Synthesis",    icon: "✦", chip: "border-zinc-500/30 bg-zinc-500/10 text-zinc-400"         },
};

// ── Sub-question answer card ──────────────────────────────────────────────────

function SubQuestionCard({
  answer,
  index,
}: {
  answer: SubQuestionAnswer;
  index: number;
}) {
  const [open, setOpen] = useState(false);
  const [sqlOpen, setSqlOpen] = useState(false);
  const ps = PURPOSE_STYLE[answer.purpose] ?? PURPOSE_STYLE.landscape;
  const hasData = !answer.error && answer.columns.length > 0 && answer.rows.length > 0;

  return (
    <div className="relative">
      {/* Connector line */}
      <div className="absolute left-[18px] top-10 bottom-0 w-px bg-zinc-800/80 pointer-events-none" />

      <div className="flex gap-3">
        {/* Step indicator */}
        <div className="shrink-0 flex flex-col items-center z-10">
          <div className="h-9 w-9 rounded-full border border-zinc-600 bg-zinc-800 flex items-center justify-center text-xs font-mono text-zinc-400">
            {index + 1}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 pb-6 min-w-0">
          {/* Header */}
          <div className="flex items-start gap-2 flex-wrap mb-2">
            <span className={`text-[11px] font-mono px-1.5 py-0.5 rounded border shrink-0 ${ps.chip}`}>
              {ps.icon} {ps.label}
            </span>
            <p className="text-sm text-zinc-300 leading-snug flex-1 min-w-0">{answer.question}</p>
          </div>

          {/* Answer bubble */}
          <div className="rounded-md border border-zinc-600 bg-zinc-800/60 p-3 space-y-2">
            <p className="text-sm text-zinc-100 leading-relaxed font-medium">{answer.answer}</p>
            {answer.insight && answer.insight !== answer.answer && (
              <p className="text-xs text-zinc-400 leading-relaxed border-t border-zinc-600/60 pt-2">
                <span className="text-zinc-500 uppercase tracking-widest font-mono text-[11px]">Insight </span>
                {answer.insight}
              </p>
            )}
            {answer.refinement && (
              <p className="text-[11px] text-violet-400/70 border-t border-zinc-600/60 pt-2 leading-relaxed italic">
                → {answer.refinement}
              </p>
            )}
          </div>

          {/* Evidence toggle */}
          {(hasData || answer.error) && (
            <div className="mt-2">
              <button
                onClick={() => setOpen(o => !o)}
                className="text-[11px] text-zinc-500 hover:text-zinc-400 transition font-mono uppercase tracking-wide flex items-center gap-1"
              >
                <span>{open ? "▼" : "▶"}</span> Data
              </button>

              {open && (
                <div className="mt-2 space-y-2">
                  {answer.error ? (
                    <pre className="text-xs text-red-400 bg-red-500/5 rounded border border-red-500/20 p-2.5 overflow-x-auto whitespace-pre-wrap font-mono">
                      {answer.error}
                    </pre>
                  ) : (
                    <>
                      {hasData && <InvestigationChart columns={answer.columns} rows={answer.rows} />}
                      {hasData && (
                        <SubqMiniTable columns={answer.columns} rows={answer.rows} rowCount={answer.row_count} />
                      )}
                    </>
                  )}
                  <button
                    onClick={() => setSqlOpen(o => !o)}
                    className="text-[11px] text-zinc-500 hover:text-zinc-400 transition font-mono uppercase tracking-wide flex items-center gap-1"
                  >
                    <span>{sqlOpen ? "▼" : "▶"}</span> SQL
                  </button>
                  {sqlOpen && (
                    <pre className="text-xs text-zinc-400 bg-zinc-800 rounded border border-zinc-600/60 p-2.5 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
                      {answer.sql}
                    </pre>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SubqMiniTable({ columns, rows }: { columns: string[]; rows: unknown[][]; rowCount: number }) {
  return <SqlResultTable columns={columns} rows={rows} maxHeight={220} />;
}

// ── Main component ────────────────────────────────────────────────────────────

export function ExplorationReportView({ report, subQuestions, subqAnswers, queryCount }: Props) {
  const dqNotes = report.data_quality_notes ?? [];

  return (
    <div className="space-y-6">
      {/* 1. Headline answer */}
      <div className="rounded-md border border-violet-500/30 bg-violet-500/5 p-5">
        <p className="text-xs font-medium uppercase tracking-widest mb-2 text-violet-400">Answer</p>
        <p className="text-lg font-semibold text-white leading-snug">{report.headline}</p>
      </div>

      {/* 2. Conclusion */}
      <div className="space-y-1.5">
        <p className="text-xs text-zinc-500 uppercase tracking-widest font-mono">Conclusion</p>
        <p className="text-sm text-zinc-200 leading-relaxed">{report.conclusion}</p>
      </div>

      {/* 3. Narrative */}
      <div className="rounded-md border border-zinc-600 bg-zinc-800/40 p-4 space-y-1.5">
        <p className="text-xs text-zinc-500 uppercase tracking-widest font-mono">How we got here</p>
        <p className="text-sm text-zinc-300 leading-relaxed italic">{report.narrative}</p>
      </div>

      {/* 4. Investigative chain */}
      {subqAnswers.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-zinc-500 uppercase tracking-widest font-mono">
            Investigative chain · {subqAnswers.length} sub-question{subqAnswers.length !== 1 ? "s" : ""}
          </p>
          <div className="mt-3">
            {subqAnswers.map((a, i) => (
              <SubQuestionCard key={a.subq_id} answer={a} index={i} />
            ))}
          </div>
        </div>
      )}

      {/* 5. Recommended actions */}
      {report.recommended_actions.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-zinc-500 uppercase tracking-widest font-mono">Recommended Actions</p>
          <div className="space-y-2">
            {report.recommended_actions.map((action, i) => (
              <div key={i} className="rounded-md border border-violet-500/20 bg-violet-500/5 p-3 flex items-start gap-3">
                <span className="shrink-0 flex h-5 w-5 items-center justify-center rounded-full bg-violet-500/20 border border-violet-500/30 text-xs font-mono text-violet-300 mt-0.5">
                  {i + 1}
                </span>
                <p className="text-sm text-zinc-300 leading-relaxed">{action}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 6. Data quality notes */}
      {dqNotes.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-orange-400 uppercase tracking-widest font-mono">Data Quality Issues</p>
          <div className="space-y-3">
            {dqNotes.map((note, i) => (
              <div key={i} className="rounded-md border border-orange-500/20 bg-orange-500/5 p-3 space-y-1.5">
                <code className="text-xs font-mono text-orange-300">{note.column ? `${note.table}.${note.column}` : note.table}</code>
                <p className="text-xs text-zinc-300">{note.issue}</p>
                <p className="text-xs text-zinc-500"><span className="text-orange-400">Fix:</span> {note.recommended_fix}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-xs text-zinc-500 text-center font-mono">
        {queryCount} SQL quer{queryCount === 1 ? "y" : "ies"} · {subqAnswers.length} sub-question{subqAnswers.length !== 1 ? "s" : ""} explored
      </p>
    </div>
  );
}
