"use client";

import { useEffect, useState } from "react";
import { Separator } from "@/components/ui/separator";
import { ReportView } from "@/components/ReportView";
import { InvestigationReportView } from "@/components/InvestigationReport";
import { ExplorationReportView } from "@/components/ExplorationReport";
import type { Hypothesis, QueryCitation, Report, ADAReport, ExplorationReport, SubQuestion, SubQuestionAnswer } from "@/lib/types";

interface FullInvestigation {
  id: string;
  question: string;
  connection_id: string;
  started_at: string;
  completed_at: string | null;
  hypotheses: Hypothesis[] | null;
  report: Report | null;
  query_history: QueryCitation[] | null;
}

interface Props {
  invId: string | null;
}

export function HistoryDetailPanel({ invId }: Props) {
  const [inv, setInv] = useState<FullInvestigation | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!invId) { setInv(null); return; }
    setLoading(true);
    fetch(`http://localhost:8000/investigations/${invId}`)
      .then(r => r.json())
      .then(setInv)
      .catch(() => setInv(null))
      .finally(() => setLoading(false));
  }, [invId]);

  if (!invId) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-8">
        <p className="text-2xl font-semibold text-zinc-500">Select an investigation</p>
        <p className="text-sm text-zinc-500 max-w-xs">
          Click any item on the left to view its full results.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex gap-1">
          {[0, 1, 2].map(i => (
            <span
              key={i}
              className="inline-block h-1.5 w-1.5 rounded-full bg-zinc-600 animate-bounce"
              style={{ animationDelay: `${i * 150}ms` }}
            />
          ))}
        </div>
      </div>
    );
  }

  if (!inv) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-zinc-500">
        Failed to load investigation.
      </div>
    );
  }

  const hypotheses = inv.hypotheses ?? [];
  const queryHistory = inv.query_history ?? [];

  // Detect report type via stored marker or field-sniffing
  const reportRaw = inv.report as (Record<string, unknown> & { _report_type?: string }) | null;
  const reportType: "investigate" | "explore" | "direct" | "legacy" = (() => {
    if (!reportRaw) return "legacy";
    if (reportRaw._report_type === "investigate" || reportRaw.executive_summary !== undefined) return "investigate";
    if (reportRaw._report_type === "explore" || reportRaw.narrative !== undefined) return "explore";
    if (hypotheses.length === 1 && (hypotheses[0] as Hypothesis & { id?: string })?.id === "direct") return "direct";
    return "legacy";
  })();

  return (
    <div className="flex-1 overflow-y-auto min-h-0">
      <div className="p-6 space-y-8 max-w-3xl mx-auto">
        {/* Question */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <p className="text-xs text-zinc-500 uppercase tracking-wide">Question</p>
            {reportType === "investigate" && (
              <span className="text-xs text-violet-400 border border-violet-500/30 bg-violet-500/10 rounded px-2 py-0.5 font-medium">ADA Investigate</span>
            )}
            {reportType === "explore" && (
              <span className="text-xs text-emerald-400 border border-emerald-500/30 bg-emerald-500/10 rounded px-2 py-0.5 font-medium">Explore</span>
            )}
            {reportType === "direct" && (
              <span className="text-xs text-sky-400 border border-sky-500/30 bg-sky-500/10 rounded px-2 py-0.5 font-medium">Direct Query</span>
            )}
          </div>
          <p className="text-base font-medium text-zinc-200">{inv.question}</p>
          <p className="mt-1 text-xs text-zinc-500 font-mono">{inv.connection_id}</p>
        </div>

        {/* Report */}
        {reportRaw && (
          <div className="space-y-3">
            <Separator className="bg-zinc-800" />

            {reportType === "investigate" && (
              <InvestigationReportView report={reportRaw as unknown as ADAReport} />
            )}

            {reportType === "explore" && (
              <ExplorationReportView
                report={reportRaw as unknown as ExplorationReport}
                subQuestions={(reportRaw.sub_questions ?? []) as SubQuestion[]}
                subqAnswers={(reportRaw.subq_answers ?? []) as SubQuestionAnswer[]}
                queryCount={queryHistory.length}
              />
            )}

            {(reportType === "direct" || reportType === "legacy") && (
              <>
                <p className="text-xs text-zinc-500 uppercase tracking-wide">
                  {reportType === "direct" ? "Query Report" : "Investigation Report"}
                </p>
                <ReportView
                  report={inv.report as Report}
                  queryCount={queryHistory.length}
                  queryHistory={queryHistory}
                  queryMode={reportType === "direct" ? "direct" : "investigate"}
                  hypotheses={hypotheses}
                  invId={inv.id}
                />
              </>
            )}
          </div>
        )}

        {!reportRaw && (
          <div className="rounded-lg border border-zinc-600 p-4 text-sm text-zinc-500">
            This investigation did not complete — no report available.
          </div>
        )}
      </div>
    </div>
  );
}
