"use client";

import { useReducer, useRef } from "react";

const BASE = "http://localhost:8000";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface InvPhase {
  phase_id: string;
  summary?: string;
  findings?: { is_significant: boolean; description: string; metric?: string }[];
}

export interface ChatTurn {
  id: string;
  question: string;
  mode: "ask" | "investigate";
  status: "loading" | "done" | "error";

  // Ask mode
  sql: string | null;
  columns: string[];
  rows: unknown[][];
  headline: string | null;
  chartType: string | null;

  // Investigate mode
  statusText: string | null;      // "Analyzing baseline…" live phase indicator
  phases: InvPhase[];
  adaReport: Record<string, unknown> | null;
  report: Record<string, unknown> | null;
  queryMode: string | null;

  // Shared
  tablesUsed: string[];
  followups: string[];
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

// ── Actions ───────────────────────────────────────────────────────────────────

type ChatAction =
  | { type: "ASK";        id: string; question: string; mode: "ask" | "investigate" }
  | { type: "SQL";        sql: string }
  | { type: "COLUMNS";    columns: string[] }
  | { type: "ROWS";       rows: unknown[][] }
  | { type: "HEADLINE";   headline: string }
  | { type: "CHART_TYPE"; chartType: string }
  | { type: "STATUS_TEXT";text: string }
  | { type: "PHASE";      phase: InvPhase }
  | { type: "ADA_REPORT"; report: Record<string, unknown>; queryMode: string }
  | { type: "REPORT";     report: Record<string, unknown>; queryMode: string }
  | { type: "QUERY_MODE"; queryMode: string }
  | { type: "TABLES_USED";tables: string[] }
  | { type: "FOLLOWUPS";  questions: string[] }
  | { type: "ERROR";      message: string }
  | { type: "DONE" }
  | { type: "CLEAR" }
  | { type: "RESTORE";    turns: ChatTurn[] };

// ── Reducer ───────────────────────────────────────────────────────────────────

function updateLast(state: ChatState, fn: (t: ChatTurn) => ChatTurn): ChatState {
  const turns = [...state.turns];
  if (turns.length > 0) turns[turns.length - 1] = fn(turns[turns.length - 1]);
  return { ...state, turns };
}

const EMPTY_TURN: Omit<ChatTurn, "id" | "question" | "mode"> = {
  status: "loading",
  sql: null, columns: [], rows: [], headline: null, chartType: null,
  statusText: null, phases: [], adaReport: null, report: null, queryMode: null,
  tablesUsed: [], followups: [], error: null,
};

function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "ASK":
      return {
        ...state, streaming: true,
        turns: [...state.turns, { ...EMPTY_TURN, id: action.id, question: action.question, mode: action.mode }],
      };
    case "SQL":        return updateLast(state, t => ({ ...t, sql: action.sql }));
    case "COLUMNS":    return updateLast(state, t => ({ ...t, columns: action.columns }));
    case "ROWS":       return updateLast(state, t => ({ ...t, rows: action.rows }));
    case "HEADLINE":   return updateLast(state, t => ({ ...t, headline: action.headline }));
    case "CHART_TYPE": return updateLast(state, t => ({ ...t, chartType: action.chartType }));
    case "STATUS_TEXT":return updateLast(state, t => ({ ...t, statusText: action.text }));
    case "TABLES_USED":return updateLast(state, t => ({ ...t, tablesUsed: action.tables }));
    case "FOLLOWUPS":  return updateLast(state, t => ({ ...t, followups: action.questions }));
    case "QUERY_MODE": return updateLast(state, t => ({ ...t, queryMode: action.queryMode }));
    case "PHASE":
      return updateLast(state, t => ({ ...t, phases: [...t.phases, action.phase], statusText: `Analyzing ${action.phase.phase_id}…` }));
    case "ADA_REPORT":
      return updateLast(state, t => ({ ...t, adaReport: action.report, queryMode: action.queryMode, statusText: null }));
    case "REPORT":
      return updateLast(state, t => ({ ...t, report: action.report, queryMode: action.queryMode, statusText: null }));
    case "ERROR":
      return { ...updateLast(state, t => ({ ...t, status: "error", error: action.message })), streaming: false };
    case "DONE":
      return { ...updateLast(state, t => ({ ...t, status: "done" })), streaming: false };
    case "CLEAR":
      return { turns: [], streaming: false };
    case "RESTORE":
      return { turns: action.turns, streaming: false };
  }
}

// ── SSE stream consumer ───────────────────────────────────────────────────────

async function consumeStream(
  res: Response,
  dispatch: (a: ChatAction) => void,
  signal: AbortSignal,
) {
  if (!res.body) { dispatch({ type: "ERROR", message: "No response body" }); return; }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (signal.aborted) { reader.cancel(); break; }
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop()!;

      for (const chunk of chunks) {
        if (!chunk.startsWith("data: ")) continue;
        try {
          const p = JSON.parse(chunk.slice(6)) as { type: string } & Record<string, unknown>;
          switch (p.type) {
            case "sql":          dispatch({ type: "SQL",        sql:       p.sql as string }); break;
            case "columns":      dispatch({ type: "COLUMNS",    columns:   p.columns as string[] }); break;
            case "rows":         dispatch({ type: "ROWS",       rows:      p.rows as unknown[][] }); break;
            case "headline":     dispatch({ type: "HEADLINE",   headline:  p.headline as string }); break;
            case "chart_type":   dispatch({ type: "CHART_TYPE", chartType: p.chart_type as string }); break;
            case "tables_used":  dispatch({ type: "TABLES_USED",tables:    p.tables as string[] }); break;
            case "followups":    dispatch({ type: "FOLLOWUPS",  questions: p.questions as string[] }); break;
            case "mode":         dispatch({ type: "QUERY_MODE", queryMode: p.query_mode as string }); break;
            case "phase_complete":
              dispatch({ type: "PHASE", phase: (p.phase as InvPhase) });
              break;
            case "ada_report":
              dispatch({ type: "ADA_REPORT", report: p.ada_report as Record<string, unknown>, queryMode: p.query_mode as string ?? "investigate" });
              break;
            case "report":
              dispatch({ type: "REPORT", report: p.report as Record<string, unknown>, queryMode: p.query_mode as string ?? "investigate" });
              break;
            case "explore_report":
              // Explore-mode investigation result — map to the same REPORT slot so ChatMessage can render it
              dispatch({ type: "REPORT", report: p.explore_report as Record<string, unknown>, queryMode: "explore" });
              break;
            case "error":        dispatch({ type: "ERROR", message: p.message as string }); break;
            case "done":         dispatch({ type: "DONE" }); break;
          }
        } catch { /* malformed chunk — skip */ }
      }
    }
  } catch (err) {
    if ((err as Error)?.name === "AbortError" || signal.aborted) {
      // User stopped — treat as done rather than error
      dispatch({ type: "DONE" });
    } else {
      dispatch({ type: "ERROR", message: "Stream interrupted" });
    }
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────────

// Tiny session ID generator — no external deps
function newSessionId() {
  return Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
}

export function useChat() {
  const [state, dispatch] = useReducer(chatReducer, { turns: [], streaming: false });
  const stateRef = useRef(state);
  stateRef.current = state;
  const abortRef = useRef<AbortController | null>(null);
  // Stable session ID for the lifetime of this chat tab mount
  const sessionIdRef = useRef(newSessionId());

  async function ask(question: string, connectionId: string, mode: "ask" | "investigate" = "ask") {
    const id = Math.random().toString(36).slice(2);
    dispatch({ type: "ASK", id, question, mode });

    // Cancel any in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    let res: Response;
    try {
      if (mode === "investigate") {
        res = await fetch(`${BASE}/investigate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, connection_id: connectionId }),
          signal,
        });
      } else {
        // Build history from last 3 completed ask-mode turns
        const history: ChatHistoryTurn[] = stateRef.current.turns
          .filter(t => t.status === "done" && t.sql && t.mode === "ask")
          .slice(-3)
          .map(t => ({ question: t.question, sql: t.sql!, columns: t.columns, headline: t.headline ?? "" }));

        res = await fetch(`${BASE}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question,
            connection_id: connectionId,
            history,
            session_id: sessionIdRef.current,
          }),
          signal,
        });
      }
    } catch (err) {
      if ((err as Error)?.name === "AbortError") {
        dispatch({ type: "DONE" });
      } else {
        dispatch({ type: "ERROR", message: "Network error — is the server running?" });
      }
      return;
    }

    await consumeStream(res, dispatch, signal);
    abortRef.current = null;
  }

  function restore(turns: ChatTurn[]) {
    // Assign a stable session ID that matches the restored session
    dispatch({ type: "RESTORE", turns });
  }

  function stop() {
    abortRef.current?.abort();
    abortRef.current = null;
    dispatch({ type: "DONE" });
  }

  function clear() {
    sessionIdRef.current = newSessionId(); // new session on clear
    dispatch({ type: "CLEAR" });
  }

  return { state, ask, stop, clear, restore, sessionId: sessionIdRef.current };
}
