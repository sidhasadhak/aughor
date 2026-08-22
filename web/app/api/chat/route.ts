/**
 * `/api/chat` — the chat surface's one stream — CI-1d, promoted in CA-1.
 *
 * Track C's thesis in one file: the brain stays Python, this handler proxies its
 * SSE, and everything the shell renders arrives as AI SDK chunks. Since CA-1 this
 * is not a proving route but THE chat transport: the workspace panel, the
 * full-page `/chat` and the briefing surfaces all send through here, and the
 * reducer path they used to share is gone.
 *
 * WHY A SERVER ROUTE AND NOT A BROWSER FETCH. The SDK's `useChat` speaks its own
 * SSE dialect (`data: {chunk}\n\n` under the UI-message-stream protocol), while
 * Aughor's backend speaks its own (`data: {json}` frames). Something has to
 * translate, and doing it here rather than in the browser means the backend URL
 * and its key never reach the client, and the shell has one wire format to
 * understand.
 *
 * WHAT ONE TURN'S BODY MAY CARRY (all optional beyond the SDK's `messages`):
 *   • `mode` — the reducer path's three doors, preserved exactly: "investigate"
 *     posts `/investigate`, "ask" (forced Quick) posts `/chat`, anything else
 *     posts the unified `/ask`. Same endpoints, same bodies, same backend
 *     behaviour — that is what transcript parity means.
 *   • per-turn options — depth, schema, canvas_id, agent_id, clarify carryover,
 *     insight_id, seeds, skip_cache, request mode + purpose (R13 starters).
 *   • `resume` — a P3 plan approval or P4 clarify choice. Still a side POST
 *     keyed by investigation id (the roadmap's rule), just spelled through the
 *     one transport so the resumed run streams like any other turn.
 *
 * HISTORY IS DERIVED, NOT TRUSTED SEPARATELY. The reducer client kept a parallel
 * `history` array; the SDK client sends its `messages`, which carry the same
 * data parts the answers streamed in as. `historyFrom` projects the compact
 * shape (`question · sql · columns · headline · key_rows`) the backend's
 * `build_history_section` reads — one memory, one source. The server still
 * reconstructs from its own store when this comes up empty (CI-1).
 *
 * THE THREE INVARIANTS PORTED FROM `consumeStream` (WP-2) stay:
 *   1. CONTENT-TYPE GUARD — anything that is not a live SSE body becomes an
 *      `error` chunk carrying the upstream's own words (the demo's 501 refusal
 *      is a product surface, not a "Request failed").
 *   2. DROP-RECOVERY — a deep run survives its stream: if the upstream drops
 *      without a terminal frame, this handler polls the investigation's
 *      persisted state (bounded) and emits the recovered report, so the turn
 *      resolves to the truth rather than an "interrupted" guess.
 *   3. ERROR-TERMINAL — nothing is emitted after a terminal frame.
 */

import { createUIMessageStream, createUIMessageStreamResponse } from "ai";

import { projectTurn, UNCERTAIN_RESULT, type AughorUIMessage, type ChatTurn } from "@/lib/chatTurn";
import { AughorToUIMessage, type AughorChunk } from "@/lib/uiMessageAdapter";
import { readFrames } from "@/lib/sseFrames";

export const dynamic = "force-dynamic";
// A deep run's drop-recovery may hold the stream open while it polls; the
// default serverless budget would kill it mid-poll.
export const maxDuration = 300;

/** The Python API. Server-side only — never shipped to the client bundle. */
function backendBase(): string {
  return (
    process.env.AUGHOR_API_BASE ||
    process.env.NEXT_PUBLIC_API_BASE ||
    "http://127.0.0.1:8000"
  ).replace(/\/+$/, "");
}

function backendHeaders(): Record<string, string> {
  return {
    "content-type": "application/json",
    accept: "text/event-stream",
    ...(process.env.AUGHOR_SECRET_KEY
      ? { "x-aughor-key": process.env.AUGHOR_SECRET_KEY }
      : {}),
  };
}

interface ChatBody {
  question?: string;
  messages?: AughorUIMessage[];
  connection_id?: string;
  session_id?: string;
  /** The reducer path's three doors: investigate | ask (forced Quick) | auto. */
  mode?: "auto" | "ask" | "investigate";
  depth?: string;
  schema?: string | null;
  canvas_id?: string | null;
  agent_id?: string | null;
  skip_clarify?: boolean;
  clarify_reading?: string;
  clarify_subject?: string;
  clarify_source?: string;
  insight_id?: string | null;
  deep?: boolean;
  seed_sql?: string | null;
  seed_context?: string;
  skip_cache?: boolean;
  /** R13 — a named starter's declared route + purpose tag. */
  request_mode?: "investigate" | "explore" | null;
  purpose?: string;
  /** P3/P4 gate approvals — a side POST keyed by investigation id. */
  resume?: {
    kind: "plan" | "clarify";
    investigation_id: string;
    keep_subquestions?: number[];
    choice?: string;
  };
  /** Direct callers may still send the compact history; the SDK client never does. */
  history?: unknown[];
}

/**
 * The question this turn is asking.
 *
 * The SDK posts `messages` — a UIMessage list whose text lives in `parts` — and
 * NEVER a `question` field. Reading `body.question` alone therefore sent the
 * backend an empty string on every browser-driven turn, and an empty question is
 * not an error there: the backend answered from whatever context it had, so the
 * UI showed a fluent, confident answer to a question nobody asked. Curl tests
 * passed throughout because curl sends `question` directly — the one shape the
 * real client never uses.
 *
 * `question` is still honoured, so a direct caller (and every test written
 * against it) keeps working.
 */
function questionFrom(body: ChatBody): string {
  if (body.question?.trim()) return body.question;
  const lastUser = [...(body.messages ?? [])].reverse().find((m) => m.role === "user");
  return (lastUser?.parts ?? [])
    .filter((p): p is { type: "text"; text: string } => p.type === "text")
    .map((p) => p.text ?? "")
    .join("")
    .trim();
}

interface ChatHistoryTurn {
  question: string;
  sql: string;
  columns: string[];
  headline: string;
  key_rows: unknown[][];
}

/** Carry a deep turn into the context: its headline for continuity + the first
 *  finding-with-SQL as a representative base a follow-up can compose on. */
function deepHistoryEntry(t: ChatTurn): ChatHistoryTurn | null {
  const headline =
    t.deepReport?.headline || (t.report?.headline as string | undefined) || t.headline || "";
  let rep: { sql: string; columns: string[]; rows: (string | number | null)[][] } | undefined;
  for (const p of t.deepReport?.phases ?? []) {
    rep = p.findings?.find((f) => f.sql && f.sql.trim());
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

/**
 * The compact conversation history, projected from the SDK's own messages —
 * every COMPLETED prior turn, in the exact shape the reducer client used to
 * keep in parallel. The turn being asked (the trailing user message) is not
 * history. Slightly deeper than the server's verbatim window on purpose (CI-1):
 * the server windows it itself.
 */
function historyFrom(messages: AughorUIMessage[]): ChatHistoryTurn[] {
  const out: ChatHistoryTurn[] = [];
  let question = "";
  for (const m of messages) {
    if (m.role === "user") {
      question = m.parts
        .filter((p): p is { type: "text"; text: string } => p.type === "text")
        .map((p) => p.text)
        .join("")
        .trim();
      continue;
    }
    if (m.role !== "assistant" || !question) continue;
    const t = projectTurn(question, m);
    question = "";
    if (t.status !== "done") continue; // an errored turn is not context to compose on
    if (t.mode === "investigate" || t.deepReport) {
      const e = deepHistoryEntry(t);
      if (e) out.push(e);
    } else if (t.sql) {
      out.push({
        question: t.question,
        sql: t.sql,
        columns: t.columns,
        headline: t.headline ?? "",
        key_rows: (t.rows ?? []).slice(0, 3),
      });
    }
  }
  return out.slice(-8);
}

/** Pick the upstream endpoint + body for this turn — the reducer's three doors,
 *  plus the gate-resume side POSTs, verbatim. */
function upstreamRequest(body: ChatBody): { url: string; payload: Record<string, unknown> } {
  const base = backendBase();
  const question = questionFrom(body);
  const history = body.history ?? historyFrom(body.messages ?? []);

  if (body.resume) {
    const r = body.resume;
    return {
      url: `${base}/investigations/${encodeURIComponent(r.investigation_id)}/feedback`,
      payload:
        r.kind === "plan"
          ? { feedback: "plan approved", keep_subquestions: r.keep_subquestions ?? [] }
          : { feedback: "clarify answered", clarify_choice: r.choice ?? "" },
    };
  }

  if (body.mode === "investigate") {
    return {
      url: `${base}/investigate`,
      payload: {
        question,
        connection_id: body.connection_id ?? "",
        canvas_id: body.canvas_id ?? null,
        schema: body.schema ?? null,
        skip_cache: body.skip_cache ?? false,
        insight_id: body.insight_id ?? null,
        seed_sql: body.seed_sql ?? null,
        seed_context: body.seed_context ?? "",
        deep: body.deep ?? false,
        history,
        session_id: body.session_id ?? "",
      },
    };
  }

  if (body.mode === "ask") {
    // Forced Quick — the reducer path's `/chat` door.
    return {
      url: `${base}/chat`,
      payload: {
        question,
        connection_id: body.connection_id ?? "",
        canvas_id: body.canvas_id ?? null,
        history,
        session_id: body.session_id ?? "",
      },
    };
  }

  // The unified door: the router picks quick vs deep and emits a `route` receipt.
  return {
    url: `${base}/ask`,
    payload: {
      question,
      connection_id: body.connection_id ?? "",
      canvas_id: body.canvas_id ?? null,
      schema: body.schema ?? null,
      history,
      session_id: body.session_id ?? "",
      depth: body.depth ?? "auto",
      agent_id: body.agent_id ?? null,
      skip_clarify: body.skip_clarify ?? false,
      clarify_reading: body.clarify_reading ?? "",
      clarify_subject: body.clarify_subject ?? "",
      clarify_source: body.clarify_source ?? "",
      insight_id: body.insight_id ?? null,
      deep: body.deep ?? false,
      mode: body.request_mode ?? null,
      purpose: body.purpose ?? "",
    },
  };
}

/**
 * WP-2 drop-recovery, moved to the seam: a deep `/ask` run executes as a
 * kernel-decoupled job that survives a dropped stream and writes its terminal
 * row. Poll for that outcome instead of asserting a bare "interrupted" — always
 * ends in exactly one recovered report, error, or honest-uncertainty abort.
 */
async function recoverAfterDrop(
  invId: string,
  adapter: AughorToUIMessage,
  write: (c: AughorChunk) => void,
  signal: AbortSignal,
): Promise<void> {
  const deadline = Date.now() + 4 * 60 * 1000; // bounded well inside maxDuration
  while (Date.now() < deadline && !signal.aborted) {
    await new Promise((r) => setTimeout(r, 4000));
    let d: { status?: string; report?: unknown } | null = null;
    try {
      const r = await fetch(`${backendBase()}/investigations/${encodeURIComponent(invId)}`, {
        headers: backendHeaders(),
        signal,
      });
      if (!r.ok) continue;
      d = (await r.json()) as { status?: string; report?: unknown };
    } catch {
      if (signal.aborted) break;
      continue; // transient — keep polling
    }
    const status = d?.status;
    if (status === "complete") {
      const rep = d?.report as { phases?: unknown[]; headline?: string } | undefined;
      if (rep && Array.isArray(rep.phases) && rep.headline) {
        for (const c of adapter.feed({
          event: "answer_report",
          data: { answer_report: rep, query_mode: "investigate", investigation_id: invId },
        }).chunks) write(c);
      } else {
        for (const c of adapter.feed({ event: "done", data: {} }).chunks) write(c);
      }
      return;
    }
    if (status === "failed" || status === "timed_out") {
      for (const c of adapter.feed({
        event: "error",
        data: {
          message:
            status === "timed_out"
              ? "The investigation timed out after the connection dropped."
              : "The investigation failed after the connection dropped.",
        },
      }).chunks) write(c);
      return;
    }
    // running / paused → keep polling until it settles or the deadline passes
  }
  for (const c of adapter.abort(
    `Connection dropped and the run did not settle in time — ${UNCERTAIN_RESULT}.`,
  )) write(c);
}

export async function POST(req: Request): Promise<Response> {
  const body = (await req.json()) as ChatBody;
  const { url, payload } = upstreamRequest(body);

  const upstream = await fetch(url, {
    method: "POST",
    headers: backendHeaders(),
    body: JSON.stringify(payload),
    signal: req.signal,
  }).catch((e: unknown) => e as Error);

  const stream = createUIMessageStream({
    execute: async ({ writer }) => {
      const adapter = new AughorToUIMessage();

      // INVARIANT 1 — anything that is not a live SSE body becomes an error
      // chunk carrying the upstream's own words.
      if (upstream instanceof Error) {
        writer.write({ type: "start" });
        writer.write({ type: "error", errorText: `backend unreachable: ${upstream.message}` });
        writer.write({ type: "finish" });
        return;
      }
      const ctype = upstream.headers.get("content-type") ?? "";
      if (!upstream.ok || !ctype.includes("text/event-stream") || !upstream.body) {
        let detail = "";
        try {
          detail = (await upstream.text()).slice(0, 400).trim();
        } catch {
          /* body unreadable — the status is all we have */
        }
        // The demo's refusal is a PRODUCT surface: unwrap it and show the
        // sentence on its own rather than burying it under "Request failed".
        let demoRefusal = "";
        try {
          const parsed = JSON.parse(detail) as { detail?: string; demo?: boolean };
          if (parsed?.demo && typeof parsed.detail === "string") demoRefusal = parsed.detail;
        } catch {
          /* not JSON — fall through to the generic message */
        }
        writer.write({ type: "start" });
        writer.write({
          type: "error",
          errorText: demoRefusal || detail || `backend returned HTTP ${upstream.status}`,
        });
        writer.write({ type: "finish" });
        return;
      }

      let sawTerminal = false;
      let invId: string | undefined;
      try {
        for await (const frame of readFrames(upstream.body, req.signal)) {
          const { chunks, terminal, investigationId } = adapter.feed(frame);
          invId = investigationId ?? invId;
          for (const c of chunks) writer.write(c);
          if (terminal) {
            sawTerminal = true;
            break; // INVARIANT 3 — nothing after a terminal frame.
          }
        }
      } catch {
        // A rejected read (client abort, upstream reset) is a drop, not a crash
        // — the recovery below decides what it means.
      }

      if (sawTerminal) return;

      // The upstream ended without saying so. The client walking away is not a
      // failure; a dropped DEEP run gets INVARIANT 2's recovery poll; anything
      // else closes honestly.
      if (req.signal.aborted) {
        for (const c of adapter.abort("client disconnected")) writer.write(c);
      } else if (invId) {
        await recoverAfterDrop(invId, adapter, (c) => writer.write(c), req.signal);
      } else {
        for (const c of adapter.abort("upstream ended without a terminal frame")) {
          writer.write(c);
        }
      }
    },
    // Default masks the reason as "An error occurred."; the shell can show more.
    onError: (e) => (e instanceof Error ? e.message : String(e)),
  });

  return createUIMessageStreamResponse({ stream });
}
