/**
 * The transport half of RC-1: one Aughor `/ask` turn, folded into an
 * `AsyncIterable<string>` that `thread.post` can stream into Slack.
 *
 * Deliberately thin. The question goes to the `/ask` door at `depth: "auto"` —
 * the same deterministic router the web chat's auto path uses, so a quick
 * question answers in seconds and a deep or wide one runs the full governed
 * path — and the Slack thread id rides as `session_id`, so the turn files under
 * a conversation (FL-6) exactly as a web turn does.
 *
 * Frame → text mapping is REPLACE-aware: Aughor's `*_delta` partials carry the
 * FULL text-so-far per frame (the resume hub's snapshot contract), while a
 * `thread.post` iterable APPENDS every yield. So this tracks what it already
 * yielded per channel and emits only suffixes — the one non-obvious piece of
 * the whole file.
 */

export interface AskOptions {
  sessionId: string;
  signal?: AbortSignal;
}

export type AskStream = (question: string, opts: AskOptions) => AsyncIterable<string>;

interface Env {
  AUGHOR_API_URL?: string;
  AUGHOR_API_KEY?: string;
  AUGHOR_CONNECTION_ID?: string;
  /**
   * RC-5 — the UserAgent this bot answers as. One process serves N bots that differ
   * ONLY in their connection and their agent: the transport is identical and the
   * platform decides how each one thinks. Per-BOT rather than per-call because that is
   * what it is — a property of the record, fixed for the life of the socket.
   */
  AUGHOR_AGENT_ID?: string;
}

const asText = (v: unknown): string => (typeof v === "string" ? v : "");

/** Yield only what `full` adds beyond `seen` (REPLACE partial → APPEND stream). */
function suffix(seen: string, full: string): string {
  if (!full || full.length <= seen.length) return "";
  return full.startsWith(seen) ? full.slice(seen.length) : "";
}

export function createAskStream(
  env: Env = process.env,
  fetchImpl: typeof fetch = fetch,
): AskStream {
  const base = (env.AUGHOR_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
  const connection = env.AUGHOR_CONNECTION_ID ?? "workspace";
  const agentId = env.AUGHOR_AGENT_ID ?? "";

  return async function* ask(question, { sessionId, signal }) {
    const res = await fetchImpl(`${base}/ask`, {
      method: "POST",
      signal,
      headers: {
        "content-type": "application/json",
        accept: "text/event-stream",
        ...(env.AUGHOR_API_KEY ? { "x-api-key": env.AUGHOR_API_KEY } : {}),
      },
      body: JSON.stringify({
        question,
        connection_id: connection,
        depth: "auto",
        session_id: sessionId,
        ...(agentId ? { agent_id: agentId } : {}),
      }),
    });
    if (!res.ok || !res.body) {
      yield `⚠️ Aughor did not answer (HTTP ${res.status}) — is the API running at ${base}?`;
      return;
    }

    let headline = "";
    let narrative = "";
    let sawText = false;
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE frames are `data: {json}` blocks separated by a blank line.
        for (;;) {
          const cut = buffer.indexOf("\n\n");
          if (cut < 0) break;
          const block = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          const line = block.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          let frame: Record<string, unknown>;
          try {
            frame = JSON.parse(line.slice(6));
          } catch {
            continue; // a malformed frame must not kill the whole answer
          }

          switch (frame.type) {
            case "headline_delta": {
              const add = suffix(headline, asText(frame.headline));
              if (add) {
                headline += add;
                sawText = true;
                yield add;
              }
              break;
            }
            case "narrative_delta": {
              const full = asText(frame.narrative);
              const add = suffix(narrative, full);
              if (add) {
                if (!narrative && sawText) yield "\n\n";
                narrative += add;
                sawText = true;
                yield add;
              }
              break;
            }
            case "headline":
            case "answer": {
              // Settled text wins over its stream — yield whatever the partial missed.
              const full = asText(frame.headline) || asText(frame.text) || asText(frame.answer);
              const add = suffix(headline, full);
              if (add) {
                headline = full;
                sawText = true;
                yield add;
              }
              break;
            }
            case "answer_report":
            case "report":
            case "explore_report": {
              // A deep or wide turn lands as a report. The full artifact lives in
              // Aughor; the thread gets the report's own words, never a summary
              // this transport invented.
              const rep = (frame.answer_report ?? frame.report ?? frame.explore_report ?? {}) as Record<string, unknown>;
              const head = asText(rep.headline) || asText(rep.answer) || asText(rep.summary);
              const body = asText(rep.summary) !== head ? asText(rep.summary) : "";
              const text = [head, body].filter(Boolean).join("\n\n")
                || "Deep analysis complete — open Aughor for the full report.";
              yield (sawText ? "\n\n" : "") + text;
              sawText = true;
              break;
            }
            case "error": {
              // The error frame carries R4's typed tail (reason/hint) AND the raw
              // provider text — which for a rate-limited chain is a wall of repeated
              // 429 JSON (seen live in a thread). A Slack surface gets ONE honest
              // sentence: the hint if the backend classified the error, else the
              // first attempt's text, bounded.
              const hint = asText(frame.hint);
              const first = (asText(frame.message) || asText(frame.error) || "the run failed")
                .split(" · ")[0]
                .trim();
              const short = first.length > 240 ? `${first.slice(0, 240)}…` : first;
              yield (sawText ? "\n\n" : "") + `⚠️ ${hint || short}`;
              return;
            }
            case "done":
              return;
            default:
              break; // progress/receipt frames are web-surface concerns, not Slack text
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  };
}
