"use client";

import type { InvestigationState } from "@/lib/types";

type StepStatus = "pending" | "running" | "done" | "error";
type Verdict = "confirmed" | "refuted" | "inconclusive" | "untested";

interface Step {
  id: string;
  label: string;
  sublabel?: string;
  status: StepStatus;
  verdict?: Verdict;
}

const VERDICT_COLOR: Record<Verdict, string> = {
  confirmed: "text-emerald-400",
  refuted: "text-red-400",
  inconclusive: "text-amber-400",
  untested: "text-zinc-500",
};

function deriveSteps(state: InvestigationState): Step[] {
  const { queryMode, hypotheses, status, queriesExecuted } = state;
  const isRunning = status === "running";
  const isDone = status === "done" || status === "paused";
  const steps: Step[] = [];

  // Route
  const routeDone = queryMode !== null;
  steps.push({
    id: "route",
    label: routeDone
      ? queryMode === "direct" ? "Direct Query" : "Investigation"
      : "Classifying question…",
    sublabel: routeDone
      ? queryMode === "direct" ? "Single-pass answer" : "Multi-hypothesis analysis"
      : undefined,
    status: routeDone ? "done" : "running",
  });

  if (!routeDone) return steps;

  if (queryMode === "direct") {
    steps.push({
      id: "query",
      label: queriesExecuted > 0
        ? `${queriesExecuted} quer${queriesExecuted === 1 ? "y" : "ies"} executed`
        : "Running query…",
      status: queriesExecuted > 0 ? "done" : "running",
    });
    steps.push({
      id: "summarize",
      label: "Summarizing results",
      status: isDone ? "done" : isRunning && queriesExecuted > 0 ? "running" : "pending",
    });
    return steps;
  }

  // Investigate mode
  const hasHypotheses = hypotheses.length > 0;
  steps.push({
    id: "decompose",
    label: hasHypotheses
      ? `${hypotheses.length} hypotheses formed`
      : "Decomposing question…",
    status: hasHypotheses ? "done" : "running",
  });

  if (!hasHypotheses) return steps;

  const firstUntested = hypotheses.findIndex(h => h.verdict === "untested");

  for (let i = 0; i < hypotheses.length; i++) {
    const h = hypotheses[i];
    const tested = h.verdict !== "untested";
    const isCurrent = isRunning && i === firstUntested;
    steps.push({
      id: `h-${i}`,
      label: `H${i + 1} · ${h.description.length > 48 ? h.description.slice(0, 48) + "…" : h.description}`,
      sublabel: tested
        ? `${h.verdict} · ${Math.round(h.confidence * 100)}%`
        : isCurrent ? "testing…" : undefined,
      status: tested ? "done" : isCurrent ? "running" : "pending",
      verdict: tested ? h.verdict : undefined,
    });
  }

  const allTested = firstUntested === -1;
  steps.push({
    id: "synthesize",
    label: "Synthesizing report",
    status: isDone ? "done" : isRunning && allTested ? "running" : "pending",
  });

  return steps;
}

function Dot({ status, verdict }: { status: StepStatus; verdict?: Verdict }) {
  if (status === "running") {
    return (
      <span className="relative flex h-2.5 w-2.5 shrink-0 mt-0.5">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-60" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-400" />
      </span>
    );
  }
  if (status === "done") {
    const color = verdict ? {
      confirmed: "bg-emerald-500",
      refuted: "bg-red-500",
      inconclusive: "bg-amber-500",
      untested: "bg-emerald-500",
    }[verdict] : "bg-emerald-500";
    return <span className={`h-2.5 w-2.5 rounded-full shrink-0 mt-0.5 ${color}`} />;
  }
  return <span className="h-2.5 w-2.5 rounded-full shrink-0 mt-0.5 border border-zinc-700 bg-zinc-900" />;
}

interface Props {
  state: InvestigationState;
}

export function ThinkingTrace({ state }: Props) {
  const steps = deriveSteps(state);

  return (
    <div className="px-4 py-3 space-y-0.5">
      <p className="text-xs text-zinc-600 uppercase tracking-wide mb-3">Progress</p>
      <div className="relative">
        {/* Vertical connecting line */}
        <div className="absolute left-[4px] top-3 bottom-3 w-px bg-zinc-800" />

        <div className="space-y-3">
          {steps.map(step => (
            <div key={step.id} className="flex items-start gap-3 relative">
              <Dot status={step.status} verdict={step.verdict} />
              <div className="min-w-0">
                <p className={`text-xs leading-snug ${
                  step.status === "pending" ? "text-zinc-600" :
                  step.status === "running" ? "text-amber-300" :
                  "text-zinc-300"
                }`}>
                  {step.label}
                </p>
                {step.sublabel && (
                  <p className={`text-xs mt-0.5 ${
                    step.verdict ? VERDICT_COLOR[step.verdict] : "text-zinc-500"
                  }`}>
                    {step.sublabel}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
