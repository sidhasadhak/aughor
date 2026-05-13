"use client";

import { useCallback, useReducer } from "react";
import type { InvestigationEvent, InvestigationState } from "./types";

const initial: InvestigationState = {
  status: "idle",
  question: "",
  hypotheses: [],
  queriesExecuted: 0,
  currentIteration: 0,
  log: [],
  report: null,
  error: null,
};

type Action = { type: "EVENT"; event: InvestigationEvent } | { type: "RESET" };

function reducer(state: InvestigationState, action: Action): InvestigationState {
  if (action.type === "RESET") return initial;

  const { event } = action;

  switch (event.type) {
    case "start":
      return { ...initial, status: "running", question: event.question, log: ["Decomposing question…"] };

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
      return {
        ...state,
        queriesExecuted: state.queriesExecuted + event.queries.length,
        currentIteration: event.iteration,
        log: [
          ...state.log,
          `H${event.hypothesis_idx + 1}: ran ${event.queries.length} quer${event.queries.length === 1 ? "y" : "ies"}`,
          ...correctionLogs,
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

    case "report":
      return {
        ...state,
        status: "done",
        hypotheses: event.hypotheses,
        queriesExecuted: event.query_count,
        report: event.report,
        log: [...state.log, "Investigation complete"],
      };

    case "error":
      return { ...state, status: "error", error: event.message, log: [...state.log, `Error: ${event.message}`] };

    case "done":
      return state.status === "running" ? { ...state, status: "done" } : state;

    default:
      return state;
  }
}

export function useInvestigation() {
  const [state, dispatch] = useReducer(reducer, initial);

  const investigate = useCallback(async (question: string, connectionId = "fixture") => {
    dispatch({ type: "RESET" });
    dispatch({ type: "EVENT", event: { type: "start", question } });

    const res = await fetch("http://localhost:8000/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, connection_id: connectionId }),
    });

    if (!res.ok || !res.body) {
      dispatch({ type: "EVENT", event: { type: "error", message: `Server error: ${res.status}` } });
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Parse SSE lines — each event is "data: {...}\n\n"
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";

      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        try {
          const event = JSON.parse(line.slice(5).trim()) as InvestigationEvent;
          dispatch({ type: "EVENT", event });
        } catch {
          // malformed chunk — ignore
        }
      }
    }
  }, []);

  return { state, investigate };
}
