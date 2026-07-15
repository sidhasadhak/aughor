"use client";
/**
 * AG-UI transport adapter (CK-1.2 of the CopilotKit/AG-UI adoption plan).
 *
 * Routes a unified `/ask` turn through the AG-UI protocol seam (POST /agui/run) instead of the
 * native `/ask` SSE — WITHOUT touching the reducer, the ChatTurn shape, or any renderer.
 *
 * Design: a pure stream TRANSFORM. It re-frames the backend's AG-UI event stream BACK into the
 * Aughor SSE frames that the existing `consumeStream` already understands, wraps that in a
 * synthetic Response, and hands it to `consumeStream` VERBATIM. So every WP-2 robustness
 * invariant (content-type guard, mid-run drop-recovery via GET /investigations/{id}, abort→DONE,
 * error-is-terminal, invId capture) applies unchanged across transports — guardrail #5, for free.
 *
 * The AG-UI→Aughor mapping is the exact inverse of the backend translator (aughor/routers/agui.py
 * §6): Custom{aughor.<type>}→the raw Aughor event, TextMessage(<run>-headline/-insight)→
 * headline/insight_delta, ToolCall(render_answer)→figure frames, ToolCall(render_*)→the report
 * event, RunError→error, RunFinished{result}→done (carrying the receipt).
 */
import { consumeStream, type ChatAction, type DebugEvent } from "./investigationStream";
import { API_BASE as BASE } from "./config";

/** The logical inputs of a unified `/ask` turn — mapped into an AG-UI RunAgentInput below. */
export interface AguiAskInput {
  question: string;
  connectionId: string;
  canvasId?: string | null;
  sessionId: string;
  history?: unknown[];
  depth?: string;
  agentId?: string | null;
  skipClarify?: boolean;
  clarifyReading?: string;
  clarifySubject?: string;
  clarifySource?: string;
  insightId?: string | null;
  deep?: boolean;
  seedSql?: string | null;
  seedContext?: string;
}

type AughorEvent = { type: string } & Record<string, unknown>;

/**
 * Stateful mapper: one AG-UI event → zero-or-more Aughor events (the inverse of the backend §6
 * map). Tracks TextMessage roles (by messageId suffix) and ToolCall names/args across frames.
 */
function makeAguiMapper() {
  const msgRole: Record<string, "headline" | "insight" | "other"> = {};
  const msgAcc: Record<string, string> = {};
  const toolName: Record<string, string> = {};
  const toolArgs: Record<string, string> = {};

  return (ag: Record<string, unknown>): AughorEvent[] => {
    switch (ag.type as string) {
      case "TEXT_MESSAGE_START": {
        const id = ag.messageId as string;
        msgRole[id] = id?.endsWith("-headline") ? "headline" : id?.endsWith("-insight") ? "insight" : "other";
        msgAcc[id] = "";
        return [];
      }
      case "TEXT_MESSAGE_CONTENT": {
        const id = ag.messageId as string;
        const delta = (ag.delta as string) ?? "";
        msgAcc[id] = (msgAcc[id] ?? "") + delta;
        // insight streams as deltas; headline is emitted whole on END.
        if (msgRole[id] === "insight" && delta) return [{ type: "insight_delta", narrative: delta }];
        return [];
      }
      case "TEXT_MESSAGE_END": {
        const id = ag.messageId as string;
        if (msgRole[id] === "headline" && msgAcc[id]) return [{ type: "headline", headline: msgAcc[id] }];
        return [];
      }
      case "TOOL_CALL_START": {
        toolName[ag.toolCallId as string] = ag.toolCallName as string;
        toolArgs[ag.toolCallId as string] = "";
        return [];
      }
      case "TOOL_CALL_ARGS": {
        const id = ag.toolCallId as string;
        toolArgs[id] = (toolArgs[id] ?? "") + ((ag.delta as string) ?? "");
        return [];
      }
      case "TOOL_CALL_END": {
        const id = ag.toolCallId as string;
        const name = toolName[id];
        let parsed: Record<string, unknown>;
        try { parsed = JSON.parse(toolArgs[id] || "{}"); } catch { return []; }
        if (name === "render_answer") {
          // figure object → one Aughor figure frame per present field
          const out: AughorEvent[] = [];
          if ("sql" in parsed) out.push({ type: "sql", sql: parsed.sql });
          if ("columns" in parsed) out.push({ type: "columns", columns: parsed.columns });
          if ("rows" in parsed) out.push({ type: "rows", rows: parsed.rows });
          if ("chart_type" in parsed) out.push({ type: "chart_type", chart_type: parsed.chart_type });
          if ("chart_config" in parsed) out.push({ type: "chart_config", chart_config: parsed.chart_config });
          if ("tables_used" in parsed) out.push({ type: "tables_used", tables: parsed.tables_used });
          return out;
        }
        // render_ada / render_report / render_dossier / render_explore / render_overview:
        // the parsed args ARE the full Aughor event (it carries its own `type`).
        return parsed && parsed.type ? [parsed as AughorEvent] : [];
      }
      case "CUSTOM": {
        const name = ag.name as string;
        if (name?.startsWith("aughor.") && ag.value && typeof ag.value === "object") {
          return [ag.value as AughorEvent];
        }
        return [];
      }
      case "RUN_ERROR":
        return [{ type: "error", message: (ag.message as string) ?? "error" }];
      case "RUN_FINISHED": {
        // An INTERRUPT outcome is a mid-run PAUSE, not a finish — the clarify/plan gate already
        // arrived via Custom (→ CLARIFY_PENDING/PLAN_PENDING). Emit no `done` so the turn stays
        // paused (parity with the native path, which ends the stream without a `done` at a gate).
        const outcome = ag.outcome as { type?: string } | undefined;
        if (outcome?.type === "interrupt") return [];
        // otherwise the backend rode the aughor `done` payload (has_receipt/inv_id) in `result`.
        return [{ type: "done", ...((ag.result as Record<string, unknown>) ?? {}) }];
      }
      case "RUN_STARTED":
      default:
        return [];
    }
  };
}

/** Wrap the AG-UI SSE byte stream in a ReadableStream of re-framed Aughor SSE bytes. */
function aguiToAughorStream(src: ReadableStream<Uint8Array>): ReadableStream<Uint8Array> {
  const reader = src.getReader();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  const map = makeAguiMapper();
  let buffer = "";
  const frame = (ev: AughorEvent) => encoder.encode(`data: ${JSON.stringify(ev)}\n\n`);

  const emit = (controller: ReadableStreamDefaultController<Uint8Array>, chunk: string) => {
    if (!chunk.startsWith("data: ")) return;
    let ag: Record<string, unknown>;
    try { ag = JSON.parse(chunk.slice(6)); } catch { return; }
    for (const aughorEv of map(ag)) controller.enqueue(frame(aughorEv));
  };

  // A `start` PUMP (not `pull`): drive the source reads in one loop and enqueue as we go.
  // A `pull`-based transform DEADLOCKS here — a pull whose source read maps to ZERO Aughor
  // frames (RUN_STARTED, TextMessage Start/Content, ToolCall Start/Args all map to nothing)
  // is not reliably re-driven, so the reframed stream stalls before the first frame and the
  // turn hangs on "Thinking…" forever (found via browser dogfooding). The pump owns its
  // cadence; enqueue still respects backpressure, and a drop/abort still surfaces to
  // consumeStream's reader (the SAME WP-2 recovery / abort→DONE as the native path).
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) {
            if (buffer.startsWith("data: ")) emit(controller, buffer);   // flush a final unterminated frame
            controller.close();
            return;
          }
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split("\n\n");
          buffer = chunks.pop()!;
          for (const chunk of chunks) emit(controller, chunk);
        }
      } catch (err) {
        controller.error(err);
      }
    },
    cancel(reason) { try { reader.cancel(reason); } catch { /* already closed */ } },
  });
}

/**
 * Drive a unified `/ask` turn over the AG-UI seam. Mirrors the native path's contract exactly:
 * the same reducer dispatches, the same abort + drop-recovery, the same terminal DONE/ERROR.
 */
export async function runAskViaAgui(
  input: AguiAskInput,
  dispatch: (a: ChatAction) => void,
  signal: AbortSignal,
  logEvent: (e: DebugEvent) => void,
) {
  const runInput = {
    threadId: input.sessionId || "",
    runId: Math.random().toString(36).slice(2),
    state: {},
    messages: [{ id: Math.random().toString(36).slice(2), role: "user", content: input.question }],
    tools: [],
    context: [],
    forwardedProps: {
      connection_id: input.connectionId,
      canvas_id: input.canvasId ?? null,
      depth: input.depth ?? "auto",
      agent_id: input.agentId ?? null,
      skip_clarify: input.skipClarify ?? false,
      clarify_reading: input.clarifyReading ?? "",
      clarify_subject: input.clarifySubject ?? "",
      clarify_source: input.clarifySource ?? "",
      insight_id: input.insightId ?? null,
      deep: input.deep ?? false,
      seed_sql: input.seedSql ?? null,
      seed_context: input.seedContext ?? "",
      history: input.history ?? [],
    },
  };

  let res: Response;
  try {
    res = await fetch(`${BASE}/agui/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(runInput),
      signal,
    });
  } catch (err) {
    if ((err as Error)?.name === "AbortError") dispatch({ type: "DONE" });
    else dispatch({ type: "ERROR", message: "Network error — is the server running?" });
    return;
  }

  // On a non-stream / error response (e.g. 404 when the backend flag is off), let consumeStream's
  // own guard surface the HTTP error verbatim — no transform needed.
  const ctype = res.headers.get("content-type") || "";
  if (!res.ok || !ctype.includes("text/event-stream")) {
    await consumeStream(res, dispatch, signal, logEvent);
    return;
  }

  // Re-frame AG-UI → Aughor SSE, then reuse consumeStream unchanged (WP-2 robustness verbatim).
  const synthetic = new Response(aguiToAughorStream(res.body!), {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
  await consumeStream(synthetic, dispatch, signal, logEvent);
}
