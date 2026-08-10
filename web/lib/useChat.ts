"use client";

import { useReducer, useRef, useCallback } from "react";
import {
  chatReducer,
  consumeStream,
  newSessionId,
  MAX_LOG,
  type ChatAction,
  type ChatTurn,
  type DebugEvent,
} from "./investigationStream";

import { getApiBase, AUGHOR_AGUI } from "./config";
import { runAskViaAgui } from "./aguiTransport";

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
  const headline = t.deepReport?.headline || (t.report?.headline as string | undefined) || t.headline || "";
  let rep: { sql: string; columns: string[]; rows: (string | number | null)[][] } | undefined;
  for (const p of t.deepReport?.phases ?? []) {
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
  // Stable session ID for the lifetime of this chat tab mount — unless a resumed
  // conversation adopts its own (see `adoptSession`).
  const sessionIdRef = useRef(newSessionId());
  // Debug event log — ring buffer, never triggers re-render; callers read on demand
  const eventLogRef = useRef<DebugEvent[]>([]);
  const logEvent = useCallback((e: DebugEvent) => {
    eventLogRef.current = [...eventLogRef.current.slice(-(MAX_LOG - 1)), e];
  }, []);

  // ── Two streams can now overlap ─────────────────────────────────────────────
  // Until P5 the composer refused to send while a turn was streaming, so exactly one
  // request was ever in flight and every "the last turn is my turn" assumption below
  // held for free. An interrupt breaks that: between the abort and the superseded
  // stream noticing it, two calls are alive at once. Every reducer action targets
  // turns[length-1], so without these two seams the OLD stream writes the NEW turn.

  // Drop a superseded stream's actions. Once its controller is aborted the call has
  // lost its claim on the conversation: its terminal DONE would settle the turn that
  // replaced it (born "done" milliseconds after ASK, while its own answer is still
  // streaming in), and any frame already parsed in the chunk that was in flight would
  // write the old turn's body into the new one.
  const untilAborted = (signal: AbortSignal) => (a: ChatAction) => { if (!signal.aborted) dispatch(a); };

  // Release the shared abort handle ONLY if it still points at this call's controller.
  // A superseded call returns AFTER its replacement has installed a new controller, so
  // an unconditional `abortRef.current = null` throws away the LIVE stream's handle —
  // leaving stop() and the next interrupt with nothing to abort.
  const releaseController = (c: AbortController) => { if (abortRef.current === c) abortRef.current = null; };

  async function ask(question: string, connectionId: string, mode: "auto" | "ask" | "investigate" = "auto", opts: { skipCache?: boolean; canvasId?: string; schema?: string | null; insightId?: string; seedSql?: string | null; seedContext?: string; deep?: boolean; depth?: "quick" | "deep"; skipClarify?: boolean; clarifyReading?: string; clarifySubject?: string; clarifySource?: string; agentId?: string; requestMode?: "investigate" | "explore"; purpose?: string } = {}) {
    const id = Math.random().toString(36).slice(2);
    // The turn's initial mode is corrected by the `route` event for auto turns
    // (deep → investigate, else ask); start auto as "ask" so the loading state is
    // the lightweight one until the router's verdict lands (it arrives first).
    // A starter's requestMode always routes deep, so start those as "investigate".
    const initialMode: "ask" | "investigate" = mode === "investigate" || opts.requestMode ? "investigate" : "ask";

    // An interrupt — the user sent this while a turn was still streaming. Settle the
    // OUTGOING turn now, while it is still turns[length-1] and therefore still the turn
    // every action addresses. Once ASK appends the new turn nothing can reach the old
    // one again, and it would spin forever. This mirrors stop(), which likewise ends a
    // turn the user walked away from as "done" rather than inventing a failure.
    if (stateRef.current.streaming) dispatch({ type: "DONE" });

    dispatch({ type: "ASK", id, question, mode: initialMode });

    // Cancel any in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;
    // Everything this call reports goes through `emit`, so the moment it is superseded
    // it stops being able to write to a conversation that has moved on without it.
    const emit = untilAborted(signal);

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
        res = await fetch(`${getApiBase()}/investigate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          // history: a follow-up in a canvas composes on the previous query (parity
          // with the quick /chat + /ask paths), not just the auto route.
          // seed_sql / seed_context: a drill seeded from a result (overview "explore this
          // fact", or any raw-seed deeper) anchors the deep analysis on the originating query/observation
          // even without an insight_id — the backend's _build_origin_finding raw-seed fallback.
          body: JSON.stringify({ question, connection_id: connectionId, canvas_id: opts.canvasId ?? null, skip_cache: opts.skipCache ?? false, insight_id: opts.insightId ?? null, seed_sql: opts.seedSql ?? null, seed_context: opts.seedContext ?? "", deep: opts.deep ?? false, history: chatHistory() }),
          signal,
        });
      } else if (mode === "auto") {
        // Unified door: the router picks quick vs deep and emits a `route` receipt.
        if (AUGHOR_AGUI) {
          // CK-1: drive the SAME turn through the AG-UI protocol seam (POST /agui/run). The
          // adapter re-frames AG-UI events into the SAME reducer dispatches (identical turn) and
          // owns its own consumeStream call (with WP-2 drop-recovery), so this path returns here.
          await runAskViaAgui({
            question, connectionId, canvasId: opts.canvasId ?? null,
            schema: opts.schema ?? null,
            sessionId: sessionIdRef.current, history: chatHistory(),
            depth: opts.depth ?? "auto", agentId: opts.agentId,
            skipClarify: opts.skipClarify, clarifyReading: opts.clarifyReading,
            clarifySubject: opts.clarifySubject, clarifySource: opts.clarifySource,
            insightId: opts.insightId, deep: opts.deep,
            requestMode: opts.requestMode, purpose: opts.purpose,   // R13 starter route parity
          }, emit, signal, logEvent);
          releaseController(controller);
          return;
        }
        res = await fetch(`${getApiBase()}/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question,
            connection_id: connectionId,
            canvas_id: opts.canvasId ?? null,
            // Scope a non-canvas answer to the selected schema. The backend forwards this
            // to resolve_execution_scope on BOTH branches now; without it a quick answer
            // could resolve `FROM orders` against a sibling schema's same-named table.
            schema: opts.schema ?? null,
            history: chatHistory(),
            session_id: sessionIdRef.current,
            depth: opts.depth ?? "auto",
            // Answer AS a user-defined agent.
            agent_id: opts.agentId ?? null,
            skip_clarify: opts.skipClarify ?? false,
            // I4 — when this turn answers a clarify, carry the chosen reading so the backend
            // crystallizes it into the Ambiguity Ledger (source=user) for this connection.
            clarify_reading: opts.clarifyReading ?? "",
            clarify_subject: opts.clarifySubject ?? "",
            clarify_source: opts.clarifySource ?? "",
            insight_id: opts.insightId ?? null,
            deep: opts.deep ?? false,
            // R13 — a named starter's declared route (investigate | explore) + its
            // purpose tag; the router honors mode deterministically (no classifier).
            mode: opts.requestMode ?? null,
            purpose: opts.purpose ?? "",
          }),
          signal,
        });
      } else {
        res = await fetch(`${getApiBase()}/chat`, {
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
        // Superseded (or stopped) before the response arrived. The turn this call owned
        // was already settled — by the interrupt above, or by stop() — so this DONE has
        // no turn left to end; `emit` drops it rather than ending the next one.
        emit({ type: "DONE" });
      } else {
        emit({ type: "ERROR", message: "Network error — is the server running?" });
      }
      return;
    }

    await consumeStream(res, emit, signal, logEvent);
    releaseController(controller);
  }

  // P3 editable plan gate: approve the paused sub-question plan (keeping the chosen
  // indices) and stream the resumed run back into the SAME turn.
  async function resumePlan(invId: string, keepSubquestions: number[]) {
    const { resumeInvestigationPlan } = await import("./api");
    dispatch({ type: "PLAN_RESUME" });
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const emit = untilAborted(controller.signal);
    let res: Response;
    try {
      res = await resumeInvestigationPlan(invId, keepSubquestions);
    } catch {
      emit({ type: "ERROR", message: "Failed to resume the investigation." });
      return;
    }
    await consumeStream(res, emit, controller.signal, logEvent);
    releaseController(controller);
  }

  // Reject the pending plan — cancel the paused investigation.
  async function rejectPlan(invId: string) {
    const { cancelInvestigation } = await import("./api");
    try { await cancelInvestigation(invId); } catch { /* best-effort */ }
    dispatch({ type: "DONE" });
  }

  // Resume a clarify_pending pause with the metric reading the user chose (P4).
  async function resumeClarify(invId: string, choice: string) {
    const { resumeInvestigationClarify } = await import("./api");
    dispatch({ type: "CLARIFY_RESUME" });
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const emit = untilAborted(controller.signal);
    let res: Response;
    try {
      res = await resumeInvestigationClarify(invId, choice);
    } catch {
      emit({ type: "ERROR", message: "Failed to resume the investigation." });
      return;
    }
    await consumeStream(res, emit, controller.signal, logEvent);
    releaseController(controller);
  }

  function restore(turns: ChatTurn[], sessionId?: string) {
    // Adopt the restored conversation's own id, which this comment has always claimed
    // happened and which nothing actually did: without it a follow-up asked after a
    // restore is filed under a FRESH session, so the conversation the user is looking at
    // and the conversation being written to are two different rows. Reading a session
    // back and then continuing it are the same act; they have to share an id.
    if (sessionId) sessionIdRef.current = sessionId;
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

  return { state, ask, stop, clear, restore, resumePlan, rejectPlan, resumeClarify, sessionId: sessionIdRef.current, eventLogRef };
}
