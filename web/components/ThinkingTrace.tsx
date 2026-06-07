"use client";

import type { InvestigationState } from "@/lib/types";
import type { ChatTurn } from "@/lib/useChat";

// Map a ChatTurn → InvestigationState so the trace can be rendered both inline
// (ChatMessage) and, historically, in a side panel. `running` reflects whether
// this turn is still streaming.
export function turnToTraceState(turn: ChatTurn, running: boolean): InvestigationState {
  return {
    status: running ? "running" : turn.status === "error" ? "error" : "done",
    question: turn.question,
    investigationId: turn.investigationId,
    hypotheses: turn.hypotheses,
    queriesExecuted: turn.queriesExecuted.length,
    currentIteration: 0,
    log: [],
    report: null,
    queryHistory: [],
    error: turn.error,
    statsPerHypothesis: {},
    fromCache: turn.fromCache,
    cachedQuestion: turn.cachedQuestion,
    humanFeedback: null,
    queryMode: turn.queryMode as InvestigationState["queryMode"],
    routeReasoning: null,
    routeConfidence: null,
    subQuestions: turn.subQuestions,
    subqAnswers: turn.subqAnswers,
    exploreReport: turn.exploreReport,
    investigationPhases: turn.phases,
    adaReport: turn.adaReport,
  };
}

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

const PURPOSE_ICON: Record<string, string> = {
  landscape:    "◎",
  relationship: "⟺",
  threshold:    "↯",
  drill_down:   "⇣",
  confounder:   "⊕",
  synthesis:    "✦",
};

// Present-tense, plain-language labels for the ADA investigation phases — what the
// agent is doing right now, not internal phase jargon. Falls back to phase_name.
const PHASE_ACTION: Record<string, string> = {
  intake:      "Understanding the question",
  baseline:    "Establishing the baseline & scanning for anomalies",
  decompose:   "Breaking the metric into its drivers",
  dimensional: "Comparing across regions, products & segments",
  behavioral:  "Checking customer & operational behavior",
  synthesis:   "Writing the report",
  synthesize:  "Writing the report",
};

function deriveSteps(state: InvestigationState): Step[] {
  const { queryMode, hypotheses, status, queriesExecuted, routeReasoning, routeConfidence, subQuestions, subqAnswers, exploreReport, investigationPhases, adaReport } = state;
  const isRunning = status === "running";
  const isDone = status === "done" || status === "paused";
  const steps: Step[] = [];

  // Route
  const routeDone = queryMode !== null;
  const confidenceLabel = routeConfidence != null ? ` · ${Math.round(routeConfidence * 100)}% confidence` : "";
  steps.push({
    id: "route",
    label: routeDone
      ? queryMode === "direct" ? "Direct Query" : queryMode === "explore" ? "Exploration" : "Investigation"
      : "Classifying question…",
    sublabel: routeDone
      ? (routeReasoning ?? (
          queryMode === "direct" ? "Single-pass answer" :
          queryMode === "explore" ? "Characterisation / open-ended analysis" :
          "Multi-hypothesis analysis"
        )) + confidenceLabel
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

  if (queryMode === "explore") {
    const hasSubqs = subQuestions.length > 0;
    steps.push({
      id: "explore-plan",
      label: hasSubqs
        ? `${subQuestions.length} sub-question${subQuestions.length !== 1 ? "s" : ""} planned`
        : "Designing investigative chain…",
      status: hasSubqs ? "done" : "running",
    });

    if (!hasSubqs) return steps;

    const answeredIds = new Set(subqAnswers.map(a => a.subq_id));

    for (let i = 0; i < subQuestions.length; i++) {
      const sq = subQuestions[i];
      const answered = sq.done || answeredIds.has(sq.id);
      const icon = PURPOSE_ICON[sq.purpose] ?? "·";
      const label = `${icon} ${sq.question.length > 44 ? sq.question.slice(0, 44) + "…" : sq.question}`;
      const answer = subqAnswers.find(a => a.subq_id === sq.id);
      // Current = running and this is the first unanswered
      const isCurrentlyRunning = isRunning && !answered && subQuestions.slice(0, i).every(s => s.done || answeredIds.has(s.id));
      steps.push({
        id: `sq-${sq.id}`,
        label,
        sublabel: answered && answer
          ? answer.answer.length > 56 ? answer.answer.slice(0, 56) + "…" : answer.answer
          : isCurrentlyRunning ? "running…" : undefined,
        status: answered ? "done" : isCurrentlyRunning ? "running" : "pending",
      });
    }

    steps.push({
      id: "synthesize-explore",
      label: "Synthesizing exploration",
      status: exploreReport ? "done" : isRunning && subQuestions.every(sq => sq.done || answeredIds.has(sq.id)) ? "running" : "pending",
    });

    return steps;
  }

  // ── Investigate mode (ADA) — render the streamed phases as the live trace. ──
  // The ADA flow populates investigationPhases (and finally adaReport), NOT the
  // legacy `hypotheses` list, so derive the trace from the phases as they stream.
  const phases = (adaReport?.phases ?? investigationPhases ?? []);
  if (phases.length > 0) {
    for (const p of phases) {
      const skipped = p.status === "skipped";
      const errored = p.status === "error";
      const done = p.status === "complete" || p.status === "partial" || skipped;
      const running = p.status === "running";
      const summary = (p.summary || "").trim();
      steps.push({
        id: `ph-${p.phase_id}`,
        label: PHASE_ACTION[p.phase_id] ?? p.phase_name,
        sublabel: skipped
          ? "skipped — not needed"
          : done
            ? (summary ? (summary.length > 64 ? summary.slice(0, 64) + "…" : summary) : undefined)
            : running ? "working…" : undefined,
        status: errored ? "error" : done ? "done" : running ? "running" : "pending",
      });
    }
    // Trailing report step — the synthesis node isn't streamed as a phase, so show
    // it explicitly: running until the final report materialises.
    const hasSynthPhase = phases.some(p => /synth/.test(p.phase_id));
    if (!hasSynthPhase) {
      steps.push({
        id: "synthesize",
        label: "Writing the report",
        status: adaReport ? "done" : isRunning ? "running" : "pending",
      });
    }
    return steps;
  }

  // Fallback: legacy hypothesis-based investigate trace (pre-ADA flows).
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
  return <span className="h-2.5 w-2.5 rounded-full shrink-0 mt-0.5 border border-zinc-600 bg-zinc-800" />;
}

interface Props {
  state: InvestigationState;
}

export function ThinkingTrace({ state }: Props) {
  const steps = deriveSteps(state);

  return (
    <div className="px-4 py-3 space-y-0.5">
      <p className="text-xs text-violet-400/60 uppercase tracking-wide mb-3 font-mono">Progress</p>
      <div className="relative">
        <div className="absolute left-[4px] top-3 bottom-3 w-px bg-violet-500/20" />

        <div className="space-y-3">
          {steps.map(step => (
            <div key={step.id} className="flex items-start gap-3 relative">
              <Dot status={step.status} verdict={step.verdict} />
              <div className="min-w-0">
                <p className={`text-xs leading-snug ${
                  step.status === "pending" ? "text-zinc-500" :
                  step.status === "running" ? "text-amber-300 bg-amber-500/10 rounded px-1 -mx-1" :
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
