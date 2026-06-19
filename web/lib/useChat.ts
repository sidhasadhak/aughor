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
