"use client";

// Editable plan gate (P3) — the AI FDE "generate a plan for review" idea. When a
// deep investigation pauses after decomposition, the user sees the sub-question
// plan and its estimated cost BEFORE the expensive fan-out runs, and can drop
// off-target sub-questions (a mis-scoped plan is corrected for ~$0) or reject it.

import { useState } from "react";
import { formatCount } from "@/lib/format";
import type { PlanPending } from "@/lib/investigationStream";

const PURPOSE_LABEL: Record<string, string> = {
  landscape: "landscape",
  relationship: "relationship",
  threshold: "threshold",
  drill_down: "drill-down",
  confounder: "confounder",
  synthesis: "synthesis",
};

export function PlanGateCard({
  plan,
  onApprove,
  onReject,
}: {
  plan: PlanPending;
  onApprove: (keepIndices: number[]) => void;
  onReject: () => void;
}) {
  const [kept, setKept] = useState<Set<number>>(() => new Set(plan.subQuestions.map((_, i) => i)));
  const toggle = (i: number) =>
    setKept((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i); else next.add(i);
      return next;
    });

  const keptIdx = [...kept].sort((a, b) => a - b);
  const perQ = plan.chainLength ? plan.estimatedTokens / plan.chainLength : 0;
  const estKept = Math.round(perQ * keptIdx.length);

  return (
    <div
      className="flex flex-col gap-2 rounded-md p-3 my-1"
      style={{ border: "1px solid var(--border, #2a3742)", background: "var(--panel, #101a24)" }}
    >
      <div className="flex items-center justify-between">
        <span className="aug-text-xs uppercase tracking-wide" style={{ color: "var(--t3)" }}>
          Review plan before running
        </span>
        <span className="aug-text-xs font-mono" style={{ color: "var(--t4)" }}>
          {keptIdx.length}/{plan.subQuestions.length} steps · ~{formatCount(estKept)} tok
        </span>
      </div>

      <ul className="flex flex-col gap-1">
        {plan.subQuestions.map((sq, i) => {
          const on = kept.has(i);
          return (
            <li key={sq.id ?? i}>
              <button
                onClick={() => toggle(i)}
                className="w-full text-left flex items-start gap-2 rounded px-2 py-1.5 transition-colors"
                style={{ background: on ? "var(--panel2, #16212c)" : "transparent", opacity: on ? 1 : 0.45 }}
              >
                <span className="mt-0.5 aug-text-xs" style={{ color: on ? "#4ade80" : "var(--t4)" }}>
                  {on ? "✓" : "○"}
                </span>
                <span className="flex flex-col gap-0.5 min-w-0">
                  <span className="aug-text-sm" style={{ color: "var(--t1)" }}>
                    <span className="font-mono" style={{ color: "var(--t4)" }}>{sq.id} </span>
                    {sq.question}
                  </span>
                  <span className="aug-text-xs" style={{ color: "var(--t4)" }}>
                    {PURPOSE_LABEL[sq.purpose] ?? sq.purpose}
                    {sq.expected_output ? ` — ${sq.expected_output}` : ""}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <div className="flex items-center gap-2 pt-1">
        <button
          disabled={keptIdx.length === 0}
          onClick={() => onApprove(keptIdx)}
          className="rounded px-2.5 py-1 aug-text-sm font-medium transition-colors disabled:opacity-40"
          style={{ background: "#166534", color: "#dcfce7" }}
        >
          Run {keptIdx.length} step{keptIdx.length === 1 ? "" : "s"} →
        </button>
        <button
          onClick={onReject}
          className="rounded px-2.5 py-1 aug-text-sm transition-colors"
          style={{ color: "var(--t3)" }}
        >
          Reject
        </button>
      </div>
    </div>
  );
}
