"use client";

import { useState } from "react";
import type { ExplorationReport as ExplorationReportType, SubQuestion, SubQuestionAnswer } from "@/lib/types";
import { InvestigationChart } from "@/components/InvestigationChart";
import { SqlResultTable } from "@/components/AugTable";

interface Props {
  report: ExplorationReportType;
  subQuestions: SubQuestion[];
  subqAnswers: SubQuestionAnswer[];
  queryCount: number;
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
  return <p className="text-[11px] uppercase tracking-wide text-zinc-500">{children}</p>;
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
          <div className="h-8 w-8 rounded-full border border-zinc-700 bg-zinc-900 flex items-center justify-center text-[12px] font-mono text-zinc-400">
            {index + 1}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 space-y-2.5">
          {/* Question + purpose chip */}
          <div className="flex items-start gap-2 flex-wrap">
            <span className={`text-[11px] font-mono px-1.5 py-0.5 rounded border shrink-0 ${ps.chip}`}>
              {ps.icon} {ps.label}
            </span>
            <p className="text-[13px] text-zinc-300 leading-snug flex-1 min-w-0">{answer.question}</p>
          </div>

          {/* Answer takeaway */}
          {answer.answer && (
            <p className="text-[13px] text-zinc-100 leading-relaxed">{answer.answer}</p>
          )}

          {/* Evidence — chart + compact table, expanded by default */}
          {hasData && (
            <div className="space-y-2">
              <InvestigationChart columns={answer.columns} rows={answer.rows} />
              <SqlResultTable columns={answer.columns} rows={answer.rows} maxHeight={220} />
            </div>
          )}

          {answer.error && (
            <pre className="text-[12px] text-red-400/90 rounded border border-red-500/20 p-2.5 overflow-x-auto whitespace-pre-wrap font-code" style={{ background: "var(--bg-0)" }}>
              {answer.error}
            </pre>
          )}

          {/* Insight */}
          {answer.insight && answer.insight !== answer.answer && (
            <p className="text-[12px] text-zinc-400 leading-relaxed border-t border-zinc-800/60 pt-2">
              <span className="text-zinc-500 uppercase tracking-wide text-[11px] mr-1.5">Insight</span>
              {answer.insight}
            </p>
          )}

          {/* Refinement (what it led to next) */}
          {answer.refinement && (
            <p className="text-[12px] text-zinc-500 leading-relaxed">→ {answer.refinement}</p>
          )}

          {/* SQL — the only collapsed detail */}
          {(hasData || answer.error) && answer.sql && (
            <div>
              <button
                onClick={() => setSqlOpen(o => !o)}
                className="text-[11px] text-zinc-500 hover:text-zinc-400 transition flex items-center gap-1"
              >
                <span className="inline-block w-2">{sqlOpen ? "▼" : "▶"}</span> SQL
              </button>
              {sqlOpen && (
                <pre className="mt-1.5 text-[12px] text-zinc-400 rounded border border-zinc-800 p-2.5 overflow-x-auto whitespace-pre-wrap font-code leading-relaxed" style={{ background: "var(--bg-0)" }}>
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

export function ExplorationReportView({ report, subqAnswers, queryCount }: Props) {
  const dqNotes = report.data_quality_notes ?? [];
  const showNarrative = report.narrative && report.narrative.trim() !== (report.conclusion ?? "").trim();

  return (
    <div className="space-y-6 text-[13px] text-zinc-300">
      {/* Answer */}
      <div className="space-y-1.5">
        <SectionLabel>Answer</SectionLabel>
        <p className="text-[15px] font-medium text-zinc-100 leading-snug">{report.headline}</p>
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

      {/* Recommended actions */}
      {report.recommended_actions.length > 0 && (
        <div className="border-t border-zinc-800/60 pt-4 space-y-2.5">
          <SectionLabel>Recommended actions</SectionLabel>
          <ol className="space-y-2">
            {report.recommended_actions.map((action, i) => (
              <li key={i} className="flex items-start gap-2.5">
                <span className="shrink-0 mt-0.5 w-5 h-5 rounded-full border border-zinc-700 text-zinc-400 text-[11px] font-mono flex items-center justify-center">
                  {i + 1}
                </span>
                <p className="leading-relaxed">{action}</p>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* Data quality */}
      {dqNotes.length > 0 && (
        <div className="border-t border-zinc-800/60 pt-4 space-y-2">
          <SectionLabel>Data quality</SectionLabel>
          <ul className="space-y-1.5">
            {dqNotes.map((note, i) => (
              <li key={i} className="leading-relaxed flex items-start gap-2">
                <span className="shrink-0 mt-0.5 text-zinc-500">—</span>
                <span>
                  <code className="text-[12px] text-zinc-400">{note.column ? `${note.table}.${note.column}` : note.table}</code>
                  <span className="text-zinc-400"> {note.issue}</span>
                  {note.recommended_fix && <span className="text-zinc-500"> · Fix: {note.recommended_fix}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-[11px] text-zinc-500 pt-1">
        {queryCount} quer{queryCount === 1 ? "y" : "ies"} · {subqAnswers.length} step{subqAnswers.length !== 1 ? "s" : ""}
      </p>
    </div>
  );
}
