"use client";

import type { InvestigationState } from "@/lib/types";
import type { ChatTurn } from "@/lib/useChat";
import { localizeCurrency } from "@/lib/orgSettings";

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
  cross_section: "Scanning dimensions for where value is weakest",
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
      // The trace renders plain text (no markdown), so strip **bold** (else "**gift_sets**"
      // leaks literal asterisks) and honour the configured currency.
      const summary = localizeCurrency((p.summary || "").trim()).replace(/\*+/g, "");
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
        label: adaReport ? "Report ready" : "Analysing the data…",
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

function StepDot({ status, verdict }: { status: StepStatus; verdict?: Verdict }) {
  if (status === "running") {
    return (
      <span className="relative flex h-3.5 w-3.5 items-center justify-center shrink-0">
        <span className="absolute inline-flex h-full w-full rounded-[var(--r-pill)] bg-amber-400/50 animate-ping" />
        <span className="relative inline-flex rounded-[var(--r-pill)] h-3 w-3 bg-amber-400 aug-pulse-dot" />
      </span>
    );
  }
  if (status === "done") {
    const tone = verdict === "refuted" ? "text-red-400 border-red-500/40"
      : verdict === "inconclusive" ? "text-amber-400 border-amber-500/40"
      : "text-emerald-400 border-emerald-500/40";
    return (
      <span className={`flex h-3.5 w-3.5 items-center justify-center rounded-[var(--r-pill)] border bg-zinc-900 shrink-0 aug-check-pop ${tone}`}>
        <svg viewBox="0 0 24 24" className="h-2.5 w-2.5" fill="none" stroke="currentColor"
          strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 13l4 4L19 7" /></svg>
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="flex h-3.5 w-3.5 items-center justify-center rounded-[var(--r-pill)] border border-red-500/40 bg-zinc-900 text-red-400 shrink-0">
        <svg viewBox="0 0 24 24" className="h-2.5 w-2.5" fill="none" stroke="currentColor"
          strokeWidth="3.5" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </span>
    );
  }
  return <span className="h-3.5 w-3.5 rounded-[var(--r-pill)] border border-zinc-600/70 bg-zinc-800/50 shrink-0" />;
}

interface Props {
  state: InvestigationState;
}

export function ThinkingTrace({ state }: Props) {
  const steps = deriveSteps(state);
  const total = steps.length;
  const doneCount = steps.filter(s => s.status === "done").length;
  const hasRunning = steps.some(s => s.status === "running");
  const pct = total ? Math.round((doneCount / total) * 100) : 0;

  return (
    <div className="px-4 py-3">
      {/* Header — live position + animated progress bar */}
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs text-violet-400/70 uppercase tracking-wide font-mono">Analysis</p>
        <span className="aug-fs-xs text-zinc-500 font-mono tabular-nums">
          {hasRunning ? `step ${Math.min(doneCount + 1, total)} of ${total}` : `${doneCount} of ${total}`}
        </span>
      </div>
      <div className="h-1 rounded-[var(--r-pill)] bg-violet-500/10 overflow-hidden mb-3">
        <div className="h-full rounded-[var(--r-pill)] bg-gradient-to-r from-violet-500 to-emerald-400 transition-[width] duration-700 ease-out"
          style={{ width: `${pct}%` }} />
      </div>

      {/* Stepper rail */}
      <div>
        {steps.map((step, i) => {
          const isLast = i === steps.length - 1;
          return (
            <div key={`${step.id}-${i}`} className="flex items-stretch gap-3 aug-step-in"
              style={{ animationDelay: `${Math.min(i, 10) * 35}ms` }}>
              {/* Rail: dot + connector segment to the next step */}
              <div className="flex flex-col items-center w-3.5 shrink-0 pt-0.5">
                <StepDot status={step.status} verdict={step.verdict} />
                {!isLast && (
                  <span className={`flex-1 w-0.5 my-0.5 min-h-[16px] rounded-[var(--r-pill)] ${
                    step.status === "done" ? "bg-emerald-500/40"
                    : step.status === "running" ? "aug-flow-y"
                    : "bg-violet-500/15"
                  }`} />
                )}
              </div>
              {/* Content */}
              <div className="min-w-0 pb-3 flex-1">
                <p className={`text-xs leading-snug transition-colors duration-300 ${
                  step.status === "pending" ? "text-zinc-500"
                  : step.status === "running" ? "text-amber-200 font-medium"
                  : step.status === "error" ? "text-red-300"
                  : "text-zinc-300"
                }`}>
                  {step.label}
                </p>
                {step.sublabel && (
                  <p className={`aug-fs-xs mt-0.5 leading-snug aug-anim-fade ${
                    step.verdict ? VERDICT_COLOR[step.verdict] : "text-zinc-500"
                  }`}>
                    {step.sublabel}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
