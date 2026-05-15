"use client";

import { useCallback, useReducer } from "react";
import type { InvestigationEvent, InvestigationState } from "./types";

const initial: InvestigationState = {
  status: "idle",
  question: "",
  investigationId: null,
  hypotheses: [],
  queriesExecuted: 0,
  currentIteration: 0,
  log: [],
  report: null,
  queryHistory: [],
  error: null,
  statsPerHypothesis: {},
  fromCache: false,
  cachedQuestion: null,
  humanFeedback: null,
  queryMode: null,
};

type HistoricalInvestigation = {
  id: string;
  question: string;
  query_count: number;
  report: import("./types").Report;
  hypotheses: import("./types").Hypothesis[];
  query_history: import("./types").QueryCitation[];
};

type Action =
  | { type: "EVENT"; event: InvestigationEvent }
  | { type: "RESET" }
  | { type: "RESUME"; feedback: string }
  | { type: "LOAD_HISTORICAL"; inv: HistoricalInvestigation };

function reducer(state: InvestigationState, action: Action): InvestigationState {
  if (action.type === "RESET") return initial;

  if (action.type === "RESUME") {
    // Preserve all evidence gathered so far — only flip status and record feedback
    return {
      ...state,
      status: "running",
      humanFeedback: action.feedback || null,
      log: [...state.log, action.feedback ? `Feedback submitted — generating report…` : "Generating report…"],
    };
  }

  if (action.type === "LOAD_HISTORICAL") {
    const { inv } = action;
    const hasManyHypotheses = (inv.hypotheses?.length ?? 0) > 1;
    return {
      ...initial,
      status: "done",
      investigationId: inv.id,
      question: inv.question,
      hypotheses: inv.hypotheses ?? [],
      queriesExecuted: inv.query_count ?? 0,
      report: inv.report,
      queryHistory: inv.query_history ?? [],
      queryMode: hasManyHypotheses ? "investigate" : "direct",
      log: ["Loaded from history"],
    };
  }

  const { event } = action;

  switch (event.type) {
    case "start":
      return { ...initial, status: "running", question: event.question, investigationId: event.investigation_id ?? null, log: ["Decomposing question…"] };

    case "mode":
      return {
        ...state,
        queryMode: event.query_mode,
        log: [...state.log, event.query_mode === "direct" ? "Direct query — fetching data…" : "Investigating — decomposing into hypotheses…"],
      };

    case "hypotheses":
      return {
        ...state,
        hypotheses: event.hypotheses,
        log: [...state.log, `Formed ${event.hypotheses.length} hypotheses`],
      };

    case "queries_executed": {
      const correctionLogs = (event.corrections ?? []).map(
        c => `↺ Auto-corrected: ${c.fix_explanation}${c.data_quality_issue ? ` · DQ: ${c.data_quality_issue}` : ""}`
      );
      const significantStats = (event.stats ?? []).filter(s => s.is_significant);
      const statsLogs = significantStats.map(
        s => `📊 ${s.sigma != null ? `${s.sigma}σ` : "sig."} — ${s.interpretation}`
      );
      const prevStats = state.statsPerHypothesis[event.hypothesis_idx] ?? [];
      return {
        ...state,
        queriesExecuted: state.queriesExecuted + event.queries.length,
        currentIteration: event.iteration,
        statsPerHypothesis: {
          ...state.statsPerHypothesis,
          [event.hypothesis_idx]: [...prevStats, ...(event.stats ?? [])],
        },
        log: [
          ...state.log,
          `H${event.hypothesis_idx + 1}: ran ${event.queries.length} quer${event.queries.length === 1 ? "y" : "ies"}`,
          ...correctionLogs,
          ...statsLogs,
        ],
      };
    }

    case "score":
      return {
        ...state,
        hypotheses: event.hypotheses,
        currentIteration: event.iteration,
        log: [
          ...state.log,
          `${event.score.hypothesis_id}: ${event.score.verdict} (${Math.round(event.score.confidence * 100)}%) — ${event.score.key_finding}`,
        ],
      };

    case "paused":
      return {
        ...state,
        status: "paused",
        hypotheses: event.hypotheses,
        investigationId: event.investigation_id,
        log: [...state.log, "Awaiting your review before generating the final report…"],
      };

    case "report":
      return {
        ...state,
        status: "done",
        hypotheses: event.hypotheses?.length ? event.hypotheses : state.hypotheses,
        queriesExecuted: event.query_count,
        report: event.report,
        queryHistory: event.query_history ?? [],
        investigationId: event.investigation_id ?? state.investigationId,
        fromCache: event.from_cache ?? false,
        cachedQuestion: event.cached_question ?? null,
        queryMode: event.query_mode ?? state.queryMode,
        log: [...state.log, event.from_cache ? "Matched prior investigation — returning cached result" : "Investigation complete"],
      };

    case "error":
      return { ...state, status: "error", error: event.message, log: [...state.log, `Error: ${event.message}`] };

    case "done":
      return state.status === "running" ? { ...state, status: "done" } : state;

    default:
      return state;
  }
}

async function consumeSSE(
  res: Response,
  onEvent: (event: InvestigationEvent) => void,
) {
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()) as InvestigationEvent);
      } catch {
        // malformed chunk — ignore
      }
    }
  }
}

export function useInvestigation() {
  const [state, dispatch] = useReducer(reducer, initial);

  const investigate = useCallback(async (question: string, connectionId = "fixture", hitl = false) => {
    dispatch({ type: "RESET" });
    dispatch({ type: "EVENT", event: { type: "start", question } });

    const res = await fetch("http://localhost:8000/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, connection_id: connectionId, hitl }),
    });

    if (!res.ok || !res.body) {
      dispatch({ type: "EVENT", event: { type: "error", message: `Server error: ${res.status}` } });
      return;
    }

    await consumeSSE(res, event => dispatch({ type: "EVENT", event }));
  }, []);

  const submitFeedback = useCallback(async (invId: string, feedback: string) => {
    const res = await fetch(`http://localhost:8000/investigations/${invId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feedback }),
    });

    if (!res.ok || !res.body) {
      dispatch({ type: "EVENT", event: { type: "error", message: `Feedback error: ${res.status}` } });
      return;
    }

    // Resume without resetting state — preserve hypotheses and evidence
    dispatch({ type: "RESUME", feedback });
    await consumeSSE(res, event => dispatch({ type: "EVENT", event }));
  }, [state.question]);

  const loadHistorical = useCallback((inv: HistoricalInvestigation) => {
    dispatch({ type: "LOAD_HISTORICAL", inv });
  }, []);

  return { state, investigate, submitFeedback, loadHistorical };
}
