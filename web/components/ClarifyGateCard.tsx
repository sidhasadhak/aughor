"use client";

// Interactive metric-ambiguity clarify (P4) — a sibling of PlanGateCard. When a deep
// investigation finds that a metric's governed reading and the parsed reading both run but
// give materially different numbers (the count-vs-value "refund rate" class), the run PAUSES
// and asks which reading the user meant, showing each reading's probed value. The choice binds
// the metric for the run and is remembered per connection (the Ambiguity Ledger), so the same
// question never re-asks.

import { Button } from "@/components/ui/button";
import type { ClarifyPending } from "@/lib/investigationStream";

export function ClarifyGateCard({
  clarify,
  onChoose,
}: {
  clarify: ClarifyPending;
  onChoose: (option: string) => void;
}) {
  return (
    <div
      className="flex flex-col gap-2 rounded-md p-3 my-1"
      style={{ border: "1px solid var(--b1)", background: "var(--bg-2)" }}
    >
      <div className="flex items-center justify-between">
        <span className="aug-text-xs uppercase tracking-wide" style={{ color: "var(--t3)" }}>
          Which reading did you mean?
        </span>
        {clarify.metricLabel && (
          <span className="aug-text-xs font-mono" style={{ color: "var(--t4)" }}>
            {clarify.metricLabel}
          </span>
        )}
      </div>

      {clarify.question && (
        <p className="aug-text-sm" style={{ color: "var(--t2)" }}>{clarify.question}</p>
      )}

      <ul className="flex flex-col gap-1">
        {clarify.options.map((opt, i) => (
          <li key={i}>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => onChoose(opt)}
              className="w-full h-auto justify-between gap-2 px-2 py-1.5 text-left whitespace-normal"
            >
              <span className="aug-text-sm" style={{ color: "var(--t1)" }}>{opt}</span>
              {clarify.previews[i] && (
                <span className="aug-text-xs font-mono shrink-0" style={{ color: "var(--grn4)" }}>
                  {clarify.previews[i]}
                </span>
              )}
            </Button>
          </li>
        ))}
      </ul>

      <span className="aug-text-xs" style={{ color: "var(--t4)" }}>
        Your choice is remembered for this connection — you won&apos;t be asked again.
      </span>
    </div>
  );
}
