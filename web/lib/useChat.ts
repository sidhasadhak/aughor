"use client";

import { useReducer, useRef, useCallback } from "react";
import type { ADAReport, ExplorationReport, Hypothesis, InvestigationPhase, SubQuestion, SubQuestionAnswer } from "@/lib/types";

// ── Debug event log — ring buffer of raw SSE events ───────────────────────────
export interface DebugEvent {
  ts: number;            // Date.now()
  type: string;          // SSE event type
  summary: string;       // brief human-readable summary
  payload: unknown;      // full payload (shown on expand)
}
const MAX_LOG = 300;

import { API_BASE as BASE } from "./config";

// ── Types ─────────────────────────────────────────────────────────────────────

// Re-export so existing imports from useChat still work
export type { InvestigationPhase as InvPhase };

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

  // Investigate mode — ADA phases stream in progressively
  statusText: string | null;
  phases: InvestigationPhase[];
  adaReport: ADAReport | null;
  report: Record<string, unknown> | null;
  queryMode: string | null;

  // Explore mode — captured from the final explore_report SSE event
  subQuestions: SubQuestion[];
  subqAnswers: SubQuestionAnswer[];
  exploreReport: ExplorationReport | null;

  // Real-time investigation progress
  queriesExecuted: { sql: string; row_count: number; error: string | null }[];
  latestScore: Record<string, unknown> | null;
  hypotheses: Hypothesis[];
  investigationId: string | null;

  // Shared
  tablesUsed: string[];
  followups: string[];
  analysis: { intent: string; steps: string[] } | null;
  error: string | null;

  // Timing — wall clock for the whole turn (all modes incl. Quick/ask)
  startedAt: number;          // Date.now() when the turn began streaming
  elapsedMs: number | null;   // frozen once the turn reaches a terminal state

  // Cache metadata
  fromCache: boolean;
  cachedQuestion: string | null;

  // Semantic inspect — set when the post-execution LLM validator finds issues
  inspectWarning: { issues: string[]; suggestedFix: string } | null;
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
  | { type: "ASK";          id: string; question: string; mode: "ask" | "investigate" }
  | { type: "SQL";          sql: string }
  | { type: "COLUMNS";      columns: string[] }
  | { type: "ROWS";         rows: unknown[][] }
  | { type: "HEADLINE";     headline: string }
  | { type: "CHART_TYPE";   chartType: string }
  | { type: "STATUS_TEXT";  text: string }
  | { type: "PHASE";        phase: InvestigationPhase }
  | { type: "ADA_REPORT";   report: ADAReport; queryMode: string; investigationId: string | null }
  | { type: "EXPLORE_REPORT"; report: ExplorationReport; subQuestions: SubQuestion[]; subqAnswers: SubQuestionAnswer[]; investigationId: string | null }
  | { type: "REPORT";       report: Record<string, unknown>; queryMode: string; investigationId: string | null }
  | { type: "QUERY_MODE";   queryMode: string }
  | { type: "TABLES_USED";  tables: string[] }
  | { type: "FOLLOWUPS";    questions: string[] }
  | { type: "ANALYSIS";     intent: string; steps: string[] }
  | { type: "CACHE_META";   fromCache: boolean; cachedQuestion: string | null }
  | { type: "QUERIES_EXEC"; queries: { sql: string; row_count: number; error: string | null }[]; hypIdx: number }
  | { type: "HYPOTHESES";       hypotheses: Hypothesis[] }
  | { type: "SCORE";            score: Record<string, unknown> }
  | { type: "INSPECT_WARNING";  issues: string[]; suggestedFix: string }
  | { type: "ERROR";            message: string }
  | { type: "DONE" }
  | { type: "CLEAR" }
  | { type: "RESTORE";          turns: ChatTurn[] };

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
  subQuestions: [], subqAnswers: [], exploreReport: null,
  queriesExecuted: [], latestScore: null,
  hypotheses: [], investigationId: null,
  tablesUsed: [], followups: [], analysis: null, error: null,
  startedAt: 0, elapsedMs: null,
  fromCache: false, cachedQuestion: null,
  inspectWarning: null,
};

// Freeze the elapsed wall-time the first time a turn reaches a terminal state.
function finish(t: ChatTurn): ChatTurn {
  return { ...t, elapsedMs: t.elapsedMs ?? (t.startedAt ? Date.now() - t.startedAt : null) };
}

function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "ASK":
      return {
        ...state, streaming: true,
        turns: [...state.turns, { ...EMPTY_TURN, id: action.id, question: action.question, mode: action.mode, startedAt: Date.now() }],
      };
    case "SQL":        return updateLast(state, t => ({ ...t, sql: action.sql }));
    case "COLUMNS":    return updateLast(state, t => ({ ...t, columns: action.columns }));
    case "ROWS":       return updateLast(state, t => ({ ...t, rows: action.rows }));
    case "HEADLINE":   return updateLast(state, t => ({ ...t, headline: action.headline }));
    case "CHART_TYPE": return updateLast(state, t => ({ ...t, chartType: action.chartType }));
    case "STATUS_TEXT":return updateLast(state, t => ({ ...t, statusText: action.text }));
    case "TABLES_USED":return updateLast(state, t => ({ ...t, tablesUsed: action.tables }));
    case "FOLLOWUPS":  return updateLast(state, t => ({ ...t, followups: action.questions }));
    case "ANALYSIS":   return updateLast(state, t => ({ ...t, analysis: { intent: action.intent, steps: action.steps } }));
    case "QUERY_MODE": return updateLast(state, t => ({ ...t, queryMode: action.queryMode }));
    case "CACHE_META":
      return updateLast(state, t => ({ ...t, fromCache: action.fromCache, cachedQuestion: action.cachedQuestion }));
    case "QUERIES_EXEC": {
      const ok = action.queries.filter(q => !q.error).length;
      const fail = action.queries.length - ok;
      const text = `Ran ${action.queries.length} quer${action.queries.length === 1 ? "y" : "ies"}${fail ? ` (${fail} failed)` : ""}…`;
      return updateLast(state, t => ({ ...t, queriesExecuted: [...t.queriesExecuted, ...action.queries], statusText: text }));
    }
    case "HYPOTHESES":
      return updateLast(state, t => ({ ...t, hypotheses: action.hypotheses }));
    case "SCORE":
      // score events carry the full updated hypotheses[] — use them to refresh state
      return updateLast(state, t => ({
        ...t,
        latestScore: action.score,
        hypotheses: (action.score.hypotheses as Hypothesis[] | undefined) ?? t.hypotheses,
      }));
    case "INSPECT_WARNING":
      return updateLast(state, t => ({
        ...t,
        inspectWarning: { issues: action.issues, suggestedFix: action.suggestedFix },
      }));
    case "PHASE":
      return updateLast(state, t => ({ ...t, phases: [...t.phases, action.phase], statusText: `Analyzing ${action.phase.phase_id}…` }));
    case "ADA_REPORT":
      return { ...updateLast(state, t => finish({ ...t, status: "done", adaReport: action.report, queryMode: action.queryMode, statusText: null, investigationId: action.investigationId ?? t.investigationId })), streaming: false };
    case "EXPLORE_REPORT":
      return { ...updateLast(state, t => finish({ ...t, status: "done", exploreReport: action.report, subQuestions: action.subQuestions, subqAnswers: action.subqAnswers, queryMode: "explore", statusText: null, investigationId: action.investigationId ?? t.investigationId })), streaming: false };
    case "REPORT":
      return updateLast(state, t => ({ ...t, report: action.report, queryMode: action.queryMode, statusText: null, investigationId: action.investigationId ?? t.investigationId }));
    case "ERROR":
      return { ...updateLast(state, t => finish({ ...t, status: "error", error: action.message })), streaming: false };
    case "DONE":
      // The backend always emits `done` in its finally block — even right after an
      // `error`. Only promote a still-running turn; never overwrite a terminal
      // `error` status (otherwise the failure message is set but never shown and
      // the investigation looks like it silently "gave up").
      return { ...updateLast(state, t => finish({ ...t, status: t.status === "loading" ? "done" : t.status })), streaming: false };
    case "CLEAR":
      return { turns: [], streaming: false };
    case "RESTORE":
      return { turns: action.turns, streaming: false };
  }
}

// ── SSE stream consumer ───────────────────────────────────────────────────────

function summarisePayload(type: string, p: Record<string, unknown>): string {
  switch (type) {
    case "phase_complete": return `phase: ${(p.phase as { phase_id?: string })?.phase_id ?? "?"}`;
    case "ada_report":     return `headline: ${String((p.ada_report as { headline?: string })?.headline ?? "").slice(0, 60)}`;
    case "explore_report": return `narrative: ${String((p.explore_report as { narrative?: string })?.narrative ?? "").slice(0, 60)}`;
    case "report":         return `mode: ${p.query_mode ?? "?"}`;
    case "error":          return `message: ${p.message}`;
    case "start":          return `inv: ${p.investigation_id ?? "new"}`;
    default:               return Object.keys(p).slice(0, 3).join(", ");
  }
}

async function consumeStream(
  res: Response,
  dispatch: (a: ChatAction) => void,
  signal: AbortSignal,
  logEvent: (e: DebugEvent) => void,
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
          logEvent({ ts: Date.now(), type: p.type, summary: summarisePayload(p.type, p), payload: p });
          switch (p.type) {
            case "sql":          dispatch({ type: "SQL",        sql:       p.sql as string }); break;
            case "columns":      dispatch({ type: "COLUMNS",    columns:   p.columns as string[] }); break;
            case "rows":         dispatch({ type: "ROWS",       rows:      p.rows as unknown[][] }); break;
            case "headline":     dispatch({ type: "HEADLINE",   headline:  p.headline as string }); break;
            case "chart_type":   dispatch({ type: "CHART_TYPE", chartType: p.chart_type as string }); break;
            case "tables_used":  dispatch({ type: "TABLES_USED",tables:    p.tables as string[] }); break;
            case "followups":    dispatch({ type: "FOLLOWUPS",  questions: p.questions as string[] }); break;
            case "analysis":     dispatch({ type: "ANALYSIS",   intent:    p.intent as string, steps: p.steps as string[] }); break;
            case "mode":         dispatch({ type: "QUERY_MODE", queryMode: p.query_mode as string }); break;
            case "phase_complete":
              dispatch({ type: "PHASE", phase: p.phase as InvestigationPhase });
              break;
            case "hypotheses":
              dispatch({ type: "HYPOTHESES", hypotheses: (p.hypotheses as Hypothesis[]) ?? [] });
              break;
            case "ada_report":
              if (p.from_cache) dispatch({ type: "CACHE_META", fromCache: true, cachedQuestion: (p.cached_question as string) ?? null });
              dispatch({ type: "ADA_REPORT", report: p.ada_report as ADAReport, queryMode: (p.query_mode as string) ?? "investigate", investigationId: (p.investigation_id as string) ?? null });
              break;
            case "report": {
              const qMode = (p.query_mode as string) ?? "investigate";
              if (p.from_cache) dispatch({ type: "CACHE_META", fromCache: true, cachedQuestion: (p.cached_question as string) ?? null });
              dispatch({ type: "REPORT", report: p.report as Record<string, unknown>, queryMode: qMode, investigationId: (p.investigation_id as string) ?? null });
              // For direct-routed agentic queries, surface the first query's SQL + results
              // so the turn renders like Quick mode (chart/table + SQL) rather than just a headline
              if (qMode === "direct" && Array.isArray(p.query_history) && (p.query_history as unknown[]).length > 0) {
                const q = (p.query_history as { sql: string; columns: string[]; rows: unknown[][] }[])[0];
                if (q.sql)                dispatch({ type: "SQL",     sql:     q.sql });
                if (q.columns?.length)    dispatch({ type: "COLUMNS", columns: q.columns });
                if (q.rows?.length)       dispatch({ type: "ROWS",    rows:    q.rows });
              }
              break;
            }
            case "explore_report":
              if (p.from_cache) dispatch({ type: "CACHE_META", fromCache: true, cachedQuestion: (p.cached_question as string) ?? null });
              dispatch({
                type: "EXPLORE_REPORT",
                report: p.explore_report as ExplorationReport,
                subQuestions: (p.sub_questions ?? []) as SubQuestion[],
                subqAnswers: (p.subq_answers ?? []) as SubQuestionAnswer[],
                investigationId: (p.investigation_id as string) ?? null,
              });
              break;
            case "queries_executed":
              dispatch({
                type: "QUERIES_EXEC",
                queries: (p.queries as { sql: string; row_count: number; error: string | null }[]) ?? [],
                hypIdx: (p.hypothesis_idx as number) ?? 0,
              });
              break;
            case "score":
              dispatch({ type: "SCORE", score: (p.score as Record<string, unknown>) ?? {} });
              break;
            case "inspect_warning":
              dispatch({
                type: "INSPECT_WARNING",
                issues:      (p.issues as string[]) ?? [],
                suggestedFix: (p.suggested_fix as string) ?? "",
              });
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
  // Debug event log — ring buffer, never triggers re-render; callers read on demand
  const eventLogRef = useRef<DebugEvent[]>([]);
  const logEvent = useCallback((e: DebugEvent) => {
    eventLogRef.current = [...eventLogRef.current.slice(-(MAX_LOG - 1)), e];
  }, []);

  async function ask(question: string, connectionId: string, mode: "ask" | "investigate" = "ask", opts: { skipCache?: boolean; canvasId?: string } = {}) {
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
          body: JSON.stringify({ question, connection_id: connectionId, canvas_id: opts.canvasId ?? null, skip_cache: opts.skipCache ?? false }),
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
            canvas_id: opts.canvasId ?? null,
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

    await consumeStream(res, dispatch, signal, logEvent);
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

  return { state, ask, stop, clear, restore, sessionId: sessionIdRef.current, eventLogRef };
}
