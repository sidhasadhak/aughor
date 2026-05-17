"use client";

import { useReducer, useRef } from "react";

const BASE = "http://localhost:8000";

export interface ChatTurn {
  id: string;
  question: string;
  status: "loading" | "done" | "error";
  sql: string | null;
  columns: string[];
  rows: unknown[][];
  headline: string | null;
  chartType: string | null;
  error: string | null;
}

interface ChatHistoryTurn {
  question: string;
  sql: string;
  columns: string[];
  headline: string;
}

interface ChatState {
  turns: ChatTurn[];
  streaming: boolean;
}

type ChatAction =
  | { type: "ASK"; id: string; question: string }
  | { type: "SQL"; sql: string }
  | { type: "COLUMNS"; columns: string[] }
  | { type: "ROWS"; rows: unknown[][] }
  | { type: "HEADLINE"; headline: string }
  | { type: "CHART_TYPE"; chartType: string }
  | { type: "ERROR"; message: string }
  | { type: "DONE" }
  | { type: "CLEAR" };

function updateLast(state: ChatState, fn: (t: ChatTurn) => ChatTurn): ChatState {
  const turns = [...state.turns];
  if (turns.length > 0) turns[turns.length - 1] = fn(turns[turns.length - 1]);
  return { ...state, turns };
}

function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "ASK":
      return {
        ...state,
        streaming: true,
        turns: [
          ...state.turns,
          { id: action.id, question: action.question, status: "loading", sql: null, columns: [], rows: [], headline: null, chartType: null, error: null },
        ],
      };
    case "SQL":
      return updateLast(state, (t) => ({ ...t, sql: action.sql }));
    case "COLUMNS":
      return updateLast(state, (t) => ({ ...t, columns: action.columns }));
    case "ROWS":
      return updateLast(state, (t) => ({ ...t, rows: action.rows }));
    case "HEADLINE":
      return updateLast(state, (t) => ({ ...t, headline: action.headline }));
    case "CHART_TYPE":
      return updateLast(state, (t) => ({ ...t, chartType: action.chartType }));
    case "ERROR":
      return { ...updateLast(state, (t) => ({ ...t, status: "error", error: action.message })), streaming: false };
    case "DONE":
      return { ...updateLast(state, (t) => ({ ...t, status: "done" })), streaming: false };
    case "CLEAR":
      return { turns: [], streaming: false };
  }
}

export function useChat() {
  const [state, dispatch] = useReducer(chatReducer, { turns: [], streaming: false });
  const stateRef = useRef(state);
  stateRef.current = state;

  async function ask(question: string, connectionId: string) {
    const id = Math.random().toString(36).slice(2);
    dispatch({ type: "ASK", id, question });

    // Build history from the last 3 completed turns
    const history: ChatHistoryTurn[] = stateRef.current.turns
      .filter((t) => t.status === "done" && t.sql)
      .slice(-3)
      .map((t) => ({
        question: t.question,
        sql: t.sql!,
        columns: t.columns,
        headline: t.headline ?? "",
      }));

    let res: Response;
    try {
      res = await fetch(`${BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, connection_id: connectionId, history }),
      });
    } catch (e) {
      dispatch({ type: "ERROR", message: "Network error — is the server running?" });
      return;
    }

    if (!res.body) {
      dispatch({ type: "ERROR", message: "No response body" });
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop()!;
      for (const chunk of chunks) {
        if (!chunk.startsWith("data: ")) continue;
        try {
          const payload = JSON.parse(chunk.slice(6)) as { type: string } & Record<string, unknown>;
          if (payload.type === "sql")        dispatch({ type: "SQL",        sql:       payload.sql as string });
          if (payload.type === "columns")    dispatch({ type: "COLUMNS",    columns:   payload.columns as string[] });
          if (payload.type === "rows")       dispatch({ type: "ROWS",       rows:      payload.rows as unknown[][] });
          if (payload.type === "headline")   dispatch({ type: "HEADLINE",   headline:  payload.headline as string });
          if (payload.type === "chart_type") dispatch({ type: "CHART_TYPE", chartType: payload.chart_type as string });
          if (payload.type === "error")      dispatch({ type: "ERROR",      message:   payload.message as string });
          if (payload.type === "done")       dispatch({ type: "DONE" });
        } catch {
          // malformed chunk — skip
        }
      }
    }
  }

  function clear() {
    dispatch({ type: "CLEAR" });
  }

  return { state, ask, clear };
}
