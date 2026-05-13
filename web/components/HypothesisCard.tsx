"use client";

import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import type { Hypothesis } from "@/lib/types";
import { cn } from "@/lib/utils";

const VERDICT_STYLES: Record<string, { badge: string; bar: string }> = {
  confirmed:   { badge: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30", bar: "bg-emerald-500" },
  refuted:     { badge: "bg-red-500/15 text-red-400 border-red-500/30",             bar: "bg-red-500" },
  inconclusive:{ badge: "bg-amber-500/15 text-amber-400 border-amber-500/30",       bar: "bg-amber-500" },
  untested:    { badge: "bg-zinc-700/50 text-zinc-400 border-zinc-600",             bar: "bg-zinc-600" },
};

interface Props {
  hypothesis: Hypothesis;
  index: number;
}

export function HypothesisCard({ hypothesis, index }: Props) {
  const styles = VERDICT_STYLES[hypothesis.verdict] ?? VERDICT_STYLES.untested;
  const pct = Math.round(hypothesis.confidence * 100);

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4 space-y-3 transition-all duration-500">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2 min-w-0">
          <span className="mt-0.5 shrink-0 text-xs font-mono text-zinc-500">H{index + 1}</span>
          <p className="text-sm text-zinc-200 leading-snug">{hypothesis.description}</p>
        </div>
        <Badge
          variant="outline"
          className={cn("shrink-0 text-xs font-medium uppercase tracking-wide", styles.badge)}
        >
          {hypothesis.verdict}
        </Badge>
      </div>

      {hypothesis.verdict !== "untested" && (
        <>
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-zinc-500">
              <span>Confidence</span>
              <span className="font-mono">{pct}%</span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-zinc-800 overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all duration-700", styles.bar)}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
          {hypothesis.key_finding && (
            <p className="text-xs text-zinc-400 leading-relaxed border-l-2 border-zinc-700 pl-3">
              {hypothesis.key_finding}
            </p>
          )}
        </>
      )}
    </div>
  );
}
