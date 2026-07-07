"use client";

import { useReducer, useRef, useCallback } from "react";
import {
  chatReducer,
  consumeStream,
  newSessionId,
  MAX_LOG,
  type ChatTurn,
  type DebugEvent,
} from "./investigationStream";

import { API_BASE as BASE } from "./config";

// Re-export so existing imports from useChat keep working
export type { ChatTurn, DebugEvent } from "./investigationStream";
export type { InvPhase } from "./investigationStream";

interface ChatHistoryTurn {
  question: string;
  sql: string;
  columns: string[];
  headline: string;
  key_rows: unknown[][];
}

// Carry a deep/investigate turn into the conversation context (Phase 4b): its headline
// for continuity + the first finding-with-SQL as a representative base a follow-up can
// compose on. Returns null when there's nothing worth carrying.
function deepHistoryEntry(t: ChatTurn): ChatHistoryTurn | null {
  const headline = t.adaReport?.headline || (t.report?.headline as string | undefined) || t.headline || "";
  let rep: { sql: string; columns: string[]; rows: (string | number | null)[][] } | undefined;
  for (const p of t.adaReport?.phases ?? []) {
    rep = p.findings?.find(f => f.sql && f.sql.trim());
    if (rep) break;
  }
  if (!rep && !headline) return null;
  return {
    question: t.question,
    sql: rep?.sql ?? "",
    columns: rep?.columns ?? [],
    headline,
    key_rows: (rep?.rows ?? []).slice(0, 3),
  };
}

// ── Hook ──────────────────────────────────────────────────────────────────────

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

  async function ask(question: string, connectionId: string, mode: "auto" | "ask" | "investigate" = "auto", opts: { skipCache?: boolean; canvasId?: string; insightId?: string; deep?: boolean; depth?: "quick" | "deep"; skipClarify?: boolean; clarifyReading?: string; clarifySubject?: string; clarifySource?: string } = {}) {
    const id = Math.random().toString(36).slice(2);
    // The turn's initial mode is corrected by the `route` event for auto turns
    // (deep → investigate, else ask); start auto as "ask" so the loading state is
    // the lightweight one until the router's verdict lands (it arrives first).
    const initialMode: "ask" | "investigate" = mode === "investigate" ? "investigate" : "ask";
    dispatch({ type: "ASK", id, question, mode: initialMode });

    // Cancel any in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    // History of the last 3 completed quick (ask) turns — fed to /chat and /ask.
    const chatHistory = (): ChatHistoryTurn[] => {
      const out: ChatHistoryTurn[] = [];
      for (const t of stateRef.current.turns) {
        if (t.status !== "done") continue;
        if (t.mode === "ask" && t.sql) {
          out.push({ question: t.question, sql: t.sql, columns: t.columns, headline: t.headline ?? "", key_rows: (t.rows ?? []).slice(0, 3) });
        } else if (t.mode === "investigate") {
          const e = deepHistoryEntry(t);
          if (e) out.push(e);
        }
      }
      return out.slice(-3);
    };

    let res: Response;
    try {
      if (mode === "investigate") {
        res = await fetch(`${BASE}/investigate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          // history: a follow-up in a canvas composes on the previous query (parity
          // with the quick /chat + /ask paths), not just the auto route.
          body: JSON.stringify({ question, connection_id: connectionId, canvas_id: opts.canvasId ?? null, skip_cache: opts.skipCache ?? false, insight_id: opts.insightId ?? null, deep: opts.deep ?? false, history: chatHistory() }),
          signal,
        });
      } else if (mode === "auto") {
        // Unified door: the router picks quick vs deep and emits a `route` receipt.
        res = await fetch(`${BASE}/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question,
            connection_id: connectionId,
            canvas_id: opts.canvasId ?? null,
            history: chatHistory(),
            session_id: sessionIdRef.current,
            depth: opts.depth ?? "auto",
            skip_clarify: opts.skipClarify ?? false,
            // I4 — when this turn answers a clarify, carry the chosen reading so the backend
            // crystallizes it into the Ambiguity Ledger (source=user) for this connection.
            clarify_reading: opts.clarifyReading ?? "",
            clarify_subject: opts.clarifySubject ?? "",
            clarify_source: opts.clarifySource ?? "",
            insight_id: opts.insightId ?? null,
            deep: opts.deep ?? false,
          }),
          signal,
        });
      } else {
        res = await fetch(`${BASE}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question,
            connection_id: connectionId,
            canvas_id: opts.canvasId ?? null,
            history: chatHistory(),
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

  // P3 editable plan gate: approve the paused sub-question plan (keeping the chosen
  // indices) and stream the resumed run back into the SAME turn.
  async function resumePlan(invId: string, keepSubquestions: number[]) {
    const { resumeInvestigationPlan } = await import("./api");
    dispatch({ type: "PLAN_RESUME" });
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    let res: Response;
    try {
      res = await resumeInvestigationPlan(invId, keepSubquestions);
    } catch {
      dispatch({ type: "ERROR", message: "Failed to resume the investigation." });
      return;
    }
    await consumeStream(res, dispatch, controller.signal, logEvent);
    abortRef.current = null;
  }

  // Reject the pending plan — cancel the paused investigation.
  async function rejectPlan(invId: string) {
    const { cancelInvestigation } = await import("./api");
    try { await cancelInvestigation(invId); } catch { /* best-effort */ }
    dispatch({ type: "DONE" });
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

  return { state, ask, stop, clear, restore, resumePlan, rejectPlan, sessionId: sessionIdRef.current, eventLogRef };
}
