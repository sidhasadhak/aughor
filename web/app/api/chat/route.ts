/**
 * `/api/chat` — the adapter's first consumer, and the shell's stream — CI-1d.
 *
 * Track C's thesis in one file: the brain stays Python, this handler proxies its
 * SSE, and everything the shell renders arrives as AI SDK chunks. It exists
 * because `uiMessageAdapter.ts` had NO consumer — both ends of the seam were
 * written and the middle was never built, which is how a feature can be fully
 * present and entirely absent at the same time.
 *
 * WHY A SERVER ROUTE AND NOT A BROWSER FETCH. The SDK's `useChat` speaks its own
 * SSE dialect (`data: {chunk}\n\n` under the UI-message-stream protocol), while
 * Aughor's backend speaks its own (`event: <name>` + `data: {json}`). Something
 * has to translate, and doing it here rather than in the browser means the
 * backend URL and its key never reach the client, and the shell has one wire
 * format to understand.
 *
 * THE THREE INVARIANTS PORTED FROM `consumeStream` (WP-2). The adapter is pure,
 * so these are this file's job, and each one is a bug someone already hit:
 *
 *   1. CONTENT-TYPE GUARD. A non-2xx or non-`text/event-stream` body (an HTML
 *      dev overlay, a proxy error page, the demo backend's 501 refusal) fed to
 *      an SSE reader finds no frames, ends cleanly, and emits neither error nor
 *      done — the turn spins forever. Anything that is not a stream becomes an
 *      `error` chunk carrying the body's own text, because the demo's refusal is
 *      a PRODUCT surface and burying it under "Request failed" hides the one
 *      instruction the reader needs.
 *   2. DROP-RECOVERY. The early `start` frame's investigation id is surfaced as
 *      message metadata so a dropped run can be polled for its terminal state.
 *   3. ERROR-TERMINAL. Nothing is emitted after a terminal frame — enforced by
 *      the adapter, and the loop stops reading when it says so.
 *
 * A dropped upstream is NOT silence: if the body ends without a terminal frame,
 * `abort()` closes the message. The SDK throws `UIMessageStreamError` on a delta
 * without its start or an end without its start, so a half-open message is a
 * runtime error in the client, not a cosmetic problem.
 */

import { createUIMessageStream, createUIMessageStreamResponse } from "ai";

import { AughorToUIMessage } from "@/lib/uiMessageAdapter";
import { readFrames } from "@/lib/sseFrames";

export const dynamic = "force-dynamic";

/** The Python API. Server-side only — never shipped to the client bundle. */
function backendBase(): string {
  return (
    process.env.AUGHOR_API_BASE ||
    process.env.NEXT_PUBLIC_API_BASE ||
    "http://127.0.0.1:8000"
  ).replace(/\/+$/, "");
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
function questionFrom(body: {
  question?: string;
  messages?: Array<{ role?: string; parts?: Array<{ type?: string; text?: string }> }>;
}): string {
  if (body.question?.trim()) return body.question;
  const lastUser = [...(body.messages ?? [])].reverse().find((m) => m.role === "user");
  return (lastUser?.parts ?? [])
    .filter((p) => p.type === "text")
    .map((p) => p.text ?? "")
    .join("")
    .trim();
}

export async function POST(req: Request): Promise<Response> {
  const body = (await req.json()) as {
    question?: string;
    messages?: Array<{ role?: string; parts?: Array<{ type?: string; text?: string }> }>;
    connection_id?: string;
    session_id?: string;
    history?: unknown[];
  };

  const upstream = await fetch(`${backendBase()}/ask`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "text/event-stream",
      ...(process.env.AUGHOR_SECRET_KEY
        ? { "x-aughor-key": process.env.AUGHOR_SECRET_KEY }
        : {}),
    },
    body: JSON.stringify({
      question: questionFrom(body),
      connection_id: body.connection_id ?? "",
      session_id: body.session_id ?? "",
      history: body.history ?? [],
    }),
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
        writer.write({ type: "start" });
        writer.write({
          type: "error",
          errorText: detail || `backend returned HTTP ${upstream.status}`,
        });
        writer.write({ type: "finish" });
        return;
      }

      let sawTerminal = false;
      for await (const frame of readFrames(upstream.body, req.signal)) {
        const { chunks, terminal } = adapter.feed(frame);
        for (const c of chunks) writer.write(c);
        if (terminal) {
          sawTerminal = true;
          break; // INVARIANT 3 — nothing after a terminal frame.
        }
      }

      // The upstream ended without saying so — a dropped connection. Close the
      // message rather than leaving text blocks open, which the SDK rejects.
      if (!sawTerminal) {
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
