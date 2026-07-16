"use client";

import type { ReactNode } from "react";
import CompassIcon   from "@atlaskit/icon/core/compass";
import DataFlowIcon  from "@atlaskit/icon/core/data-flow";
import ScalesIcon    from "@atlaskit/icon/core/scales";
import ZoomInIcon    from "@atlaskit/icon/core/zoom-in";
import FlaskIcon     from "@atlaskit/icon/core/flask";
import LightbulbIcon from "@atlaskit/icon/core/lightbulb";
import MinusIcon     from "@atlaskit/icon/core/minus";
import DatabaseIcon  from "@atlaskit/icon/core/database";
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
  /** Leading icon rendered before the label (explore sub-question purposes). */
  icon?: ReactNode;
  sublabel?: string;
  status: StepStatus;
  verdict?: Verdict;
  /** Named query steps nested under this beat (Genie-style): the human titles of
   *  the queries this phase ran — "Bottom 20 franchises by revenue", never SQL. */
  substeps?: string[];
}

const VERDICT_COLOR: Record<Verdict, string> = {
  confirmed: "text-emerald-400",
  refuted: "text-red-400",
  inconclusive: "text-amber-400",
  untested: "text-zinc-500",
};

// Sub-question purpose → leading icon (atlaskit core, 12px "small", colour
// inherited from the step label). Real icons replace the old unicode glyphs.
const PURPOSE_ICON: Record<string, ReactNode> = {
  landscape:    <CompassIcon label="" size="small" />,
  relationship: <DataFlowIcon label="" size="small" />,
  threshold:    <ScalesIcon label="" size="small" />,
  drill_down:   <ZoomInIcon label="" size="small" />,
  confounder:   <FlaskIcon label="" size="small" />,
  synthesis:    <LightbulbIcon label="" size="small" />,
};
// Neutral fallback for purposes the map doesn't know (was "·").
const PURPOSE_FALLBACK_ICON: ReactNode = <MinusIcon label="" size="small" />;

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
      const label = sq.question.length > 44 ? sq.question.slice(0, 44) + "…" : sq.question;
      const answer = subqAnswers.find(a => a.subq_id === sq.id);
      // Current = running and this is the first unanswered
      const isCurrentlyRunning = isRunning && !answered && subQuestions.slice(0, i).every(s => s.done || answeredIds.has(s.id));
      steps.push({
        id: `sq-${sq.id}`,
        label,
        icon: PURPOSE_ICON[sq.purpose] ?? PURPOSE_FALLBACK_ICON,
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
      // Nested named query steps (Genie-style): each finding's human title is one
      // sub-row under the phase beat — the reader sees WHAT was asked of the data,
      // never SQL. Errored/blank titles are dropped; capped for readability.
      const substeps = (p.findings ?? [])
        .filter(f => !f.error && (f.title || "").trim())
        .map(f => localizeCurrency(f.title).replace(/\*+/g, ""))
        .slice(0, 8);
      steps.push({
        id: `ph-${p.phase_id}`,
        label: PHASE_ACTION[p.phase_id] ?? p.phase_name,
        sublabel: skipped
          ? "skipped — not needed"
          : done
            ? (summary ? (summary.length > 64 ? summary.slice(0, 64) + "…" : summary) : undefined)
            : running ? "working…" : undefined,
        status: errored ? "error" : done ? "done" : running ? "running" : "pending",
        substeps: substeps.length ? substeps : undefined,
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

// R16 P3 — the Genie-trace study: a thinking trace is a quiet, structured text
// tree, not a status dashboard. Monochrome markers (no colored pills, no check
// pop): running = a soft pulsing dot, done = a filled dot, error keeps the one
// muted red × (failure must stay visible). Verdict nuance lives in the sublabel
// text, not the marker.
function StepDot({ status }: { status: StepStatus; verdict?: Verdict }) {
  if (status === "running") {
    return (
      <span className="relative flex h-3.5 w-3.5 items-center justify-center shrink-0">
        <span className="relative inline-flex rounded-[var(--r-pill)] h-2 w-2 bg-zinc-400 aug-pulse-dot" />
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="flex h-3.5 w-3.5 items-center justify-center text-red-400/80 shrink-0">
        <svg viewBox="0 0 24 24" className="h-2.5 w-2.5" fill="none" stroke="currentColor"
          strokeWidth="3.5" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </span>
    );
  }
  if (status === "done") {
    return (
      <span className="flex h-3.5 w-3.5 items-center justify-center shrink-0">
        <span className="inline-flex rounded-[var(--r-pill)] h-1.5 w-1.5 bg-zinc-500" />
      </span>
    );
  }
  return (
    <span className="flex h-3.5 w-3.5 items-center justify-center shrink-0">
      <span className="inline-flex rounded-[var(--r-pill)] h-1.5 w-1.5 border border-zinc-600/70" />
    </span>
  );
}

interface Props {
  state: InvestigationState;
}

export function ThinkingTrace({ state }: Props) {
  const steps = deriveSteps(state);

  return (
    <div className="px-4 py-3">
      {/* R16 P3 — no dashboard chrome: the tree itself is the progress display.
          (The wrapper's label carries running/complete; a step counter and a
          gradient bar read as status theater, not thinking.) */}
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
                  <span className="flex-1 w-px my-0.5 min-h-[16px] bg-zinc-700/60" />
                )}
              </div>
              {/* Content */}
              <div className="min-w-0 pb-3 flex-1">
                <p className={`text-xs leading-snug transition-colors duration-300 flex items-start gap-1.5 ${
                  step.status === "pending" ? "text-zinc-500"
                  : step.status === "running" ? "text-zinc-100 font-medium"
                  : step.status === "error" ? "text-red-300"
                  : "text-zinc-300"
                }`}>
                  {/* Icon inherits the label's colour so pending/running/done tones carry through. */}
                  {step.icon && <span className="shrink-0 mt-px" aria-hidden>{step.icon}</span>}
                  <span className="min-w-0">{step.label}</span>
                </p>
                {step.sublabel && (
                  <p className={`aug-fs-xs mt-0.5 leading-snug aug-anim-fade ${
                    step.verdict ? VERDICT_COLOR[step.verdict] : "text-zinc-500"
                  }`}>
                    {step.sublabel}
                  </p>
                )}
                {/* Nested named query steps — indented rail of what was asked of the data.
                    Wrapped in .aug-disclose so the region grows smoothly when the first
                    finding streams in mid-run; restored turns mount already-open (no
                    transition fires on initial render), so history doesn't animate. */}
                <div className="aug-disclose" data-open={!!step.substeps}>
                  <div>
                    {step.substeps && (
                      <div className="mt-1.5 ml-0.5 border-l border-zinc-700/60 pl-2.5 space-y-1">
                        {step.substeps.map((s, j) => (
                          <p key={j} className="aug-fs-xs leading-snug text-zinc-400 flex items-start gap-1.5 aug-anim-fade">
                            <span className="text-zinc-500 shrink-0 mt-px" aria-hidden><DatabaseIcon label="" size="small" /></span>
                            <span className="min-w-0">{s.length > 76 ? s.slice(0, 76) + "…" : s}</span>
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
