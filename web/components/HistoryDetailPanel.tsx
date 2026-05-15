"use client";

import { useEffect, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { HypothesisCard } from "@/components/HypothesisCard";
import { ReportView } from "@/components/ReportView";
import type { Hypothesis, QueryCitation, Report } from "@/lib/types";

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
        <p className="text-2xl font-semibold text-zinc-700">Select an investigation</p>
        <p className="text-sm text-zinc-600 max-w-xs">
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
      <div className="flex-1 flex items-center justify-center text-sm text-zinc-600">
        Failed to load investigation.
      </div>
    );
  }

  const hypotheses = inv.hypotheses ?? [];
  const queryHistory = inv.query_history ?? [];
  const isDirect = hypotheses.length === 1 && hypotheses[0]?.id === "direct";
  const queryMode = isDirect ? "direct" : "investigate";

  return (
    <ScrollArea className="flex-1">
      <div className="p-6 space-y-8 max-w-3xl mx-auto">
        {/* Question */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <p className="text-xs text-zinc-600 uppercase tracking-wide">Question</p>
            {isDirect && (
              <span className="text-xs text-sky-400 border border-sky-500/30 bg-sky-500/10 rounded px-2 py-0.5 font-medium">
                Direct Query
              </span>
            )}
          </div>
          <p className="text-base font-medium text-zinc-200">{inv.question}</p>
          <p className="mt-1 text-xs text-zinc-600 font-mono">{inv.connection_id}</p>
        </div>

        {/* Hypotheses — hidden for direct mode */}
        {!isDirect && hypotheses.length > 0 && (
          <div className="space-y-3">
            <p className="text-xs text-zinc-600 uppercase tracking-wide">
              Hypotheses — {hypotheses.filter(h => h.verdict !== "untested").length} of {hypotheses.length} tested
            </p>
            {hypotheses.map((h, i) => (
              <HypothesisCard key={h.id} hypothesis={h} index={i} />
            ))}
          </div>
        )}

        {/* Report */}
        {inv.report && (
          <div className="space-y-3">
            <Separator className="bg-zinc-800" />
            <p className="text-xs text-zinc-600 uppercase tracking-wide">
              {isDirect ? "Query Report" : "Investigation Report"}
            </p>
            <ReportView
              report={inv.report}
              queryCount={queryHistory.length}
              queryHistory={queryHistory}
              queryMode={queryMode}
            />
          </div>
        )}

        {!inv.report && (
          <div className="rounded-lg border border-zinc-800 p-4 text-sm text-zinc-600">
            This investigation did not complete — no report available.
          </div>
        )}
      </div>
    </ScrollArea>
  );
}
