"use client";

import { useReducer, useRef, useCallback } from "react";
import {
  chatReducer,
  consumeStream,
  MAX_LOG,
  type ChatTurn,
  type DebugEvent,
} from "./investigationStream";
import { API_BASE as BASE } from "./config";

export interface ThreadRunOpts {
  connectionId: string;
  /** Scope a non-canvas investigation to a specific schema (multi-schema connections). */
  schema?: string | null;
  canvasId?: string | null;
  /** The exact query the seed finding came from — anchors ADA on the real tables/window. */
  seedSql?: string | null;
  /** Free-text seed (e.g. the briefing claim being pulled on). */
  seedContext?: string;
  /** Bypass the similar-investigation cache so you observe live execution. */
  skipCache?: boolean;
}

/**
 * Drives ONE inline ADA investigation thread over the /investigate SSE stream.
 *
 * Unlike useChat (which keeps a list of turns and aborts any in-flight request
 * on each new ask), this owns a single turn and a single AbortController PER HOOK
 * INSTANCE, so many inline briefing threads can stream concurrently and each
 * cancels independently on unmount/stop. It reuses the exact same reducer and SSE
 * parser as useChat via the shared investigationStream module — the parser never
 * forks.
 */
export function useInvestigationThread() {
  const [state, dispatch] = useReducer(chatReducer, { turns: [], streaming: false });
  const abortRef = useRef<AbortController | null>(null);
  const eventLogRef = useRef<DebugEvent[]>([]);
  const logEvent = useCallback((e: DebugEvent) => {
    eventLogRef.current = [...eventLogRef.current.slice(-(MAX_LOG - 1)), e];
  }, []);

  const run = useCallback(async (question: string, opts: ThreadRunOpts) => {
    // Reset to a single fresh turn, then start streaming.
    dispatch({ type: "CLEAR" });
    const id = Math.random().toString(36).slice(2);
    dispatch({ type: "ASK", id, question, mode: "investigate" });

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    let res: Response;
    try {
      res = await fetch(`${BASE}/investigate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          connection_id: opts.connectionId,
          canvas_id: opts.canvasId ?? null,
          schema: opts.schema ?? null,
          seed_sql: opts.seedSql ?? null,
          seed_context: opts.seedContext ?? "",
          skip_cache: opts.skipCache ?? false,
        }),
        signal,
      });
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
  }, [logEvent]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    dispatch({ type: "DONE" });
  }, []);

  const turn: ChatTurn | null = state.turns.length ? state.turns[state.turns.length - 1] : null;
  return { turn, streaming: state.streaming, run, stop, eventLogRef };
}
