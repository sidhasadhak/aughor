/**
 * `GET /api/chat/{id}/stream` — reattach to a conversation's in-flight run (FL-1b).
 *
 * The SDK half of resume: `useChat({ resume: true })` calls the transport's
 * `reconnectToStream`, and `DefaultChatTransport` GETs exactly this path with
 * the conversation id (our `session_id`). The backend half is
 * `GET /ask/stream/{session_id}` — the frame hub's snapshot-then-tail replay of
 * a K1 job-streamed deep run, in the run's own SSE dialect. This route is the
 * same translator the POST route is: Aughor frames in, UIMessage chunks out,
 * through the SAME adapter, so resume can never drift from first delivery.
 *
 * `204` (flag off · no run for this conversation · run already finished) maps
 * to a `204` here, which the SDK treats as "nothing to resume" and leaves the
 * conversation exactly as the persisted history rendered it.
 */

import { createUIMessageStream, createUIMessageStreamResponse } from "ai";

import { backendBase, backendHeaders } from "@/lib/chatProxy";
import { AughorToUIMessage } from "@/lib/uiMessageAdapter";
import { readFrames } from "@/lib/sseFrames";

export const dynamic = "force-dynamic";
// A resumed deep run tails until the run settles — same budget as the POST side.
export const maxDuration = 300;

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params; // Next 16 hands `params` as a PROMISE
  if (!id) return new Response(null, { status: 204 });

  const upstream = await fetch(
    `${backendBase()}/ask/stream/${encodeURIComponent(id)}`,
    { headers: backendHeaders(), signal: req.signal },
  ).catch(() => null);

  const ctype = upstream?.headers.get("content-type") ?? "";
  if (!upstream || !upstream.ok || upstream.status === 204 ||
      !ctype.includes("text/event-stream") || !upstream.body) {
    // Nothing to resume — includes a backend that cannot answer right now:
    // resume is opportunistic, so degrading to "no stream" beats an error turn.
    return new Response(null, { status: 204 });
  }

  const body = upstream.body;
  const stream = createUIMessageStream({
    execute: async ({ writer }) => {
      // Stable per-conversation id: a conversation runs one turn at a time, so
      // repeated reconnects (strict-mode double mounts, a second reload) update
      // one message rather than stacking duplicate turns.
      const adapter = new AughorToUIMessage({ messageId: `resume-${id}` });
      try {
        for await (const frame of readFrames(body, req.signal)) {
          const { chunks, terminal } = adapter.feed(frame);
          for (const c of chunks) writer.write(c);
          if (terminal) return; // nothing after a terminal frame (POST invariant 3)
        }
      } catch {
        // A dropped resume read is a drop, not a crash — settle below.
      }
      if (req.signal.aborted) {
        for (const c of adapter.abort("client disconnected")) writer.write(c);
        return;
      }
      // The replay ended without a terminal frame (a lagged consumer, or the
      // hub's TTL). The run itself is still supervised server-side; settle this
      // view honestly — a fresh reload resumes again or reads the history.
      for (const c of adapter.abort(
        "resume stream ended before the run settled — reload to reattach",
      )) writer.write(c);
    },
    onError: (e) => (e instanceof Error ? e.message : String(e)),
  });

  return createUIMessageStreamResponse({ stream });
}
