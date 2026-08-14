/**
 * SSE byte stream → Aughor frames — CI-1d.
 *
 * Lives outside the route handler for two reasons: Next validates a
 * `route.ts`'s exports, so a helper exported for testing is a build risk there;
 * and this is the part most likely to be subtly wrong, so it needs tests.
 *
 * TWO RULES THAT LOOK LIKE DETAILS AND ARE NOT:
 *
 *   • SPLIT ON THE BLANK LINE, NOT ON NEWLINES. A `data:` payload is JSON and
 *     may contain them — an answer with a newline in its narrative is ordinary.
 *     Splitting per line tears one frame into several unparseable ones.
 *   • CARRY THE REMAINDER BETWEEN READS. A network chunk boundary lands
 *     mid-record far more often than a fixture suggests, and a parser that
 *     assumes each read is whole records drops the straddling frame — silently,
 *     because the next read starts mid-JSON and simply fails to parse.
 */

export type AughorFrame = { event: string; data: Record<string, unknown> };

/**
 * Parse one SSE record (the text between blank lines) into a frame.
 *
 * THE FRAME NAME LIVES IN THE PAYLOAD, NOT IN AN `event:` LINE. Aughor's
 * backend emits bare `data: {"type":"route",…}` records — it does not use the
 * SSE event field at all, and `investigationStream.ts:587` has always read
 * `p.type` from the parsed JSON for exactly this reason.
 *
 * Written the other way round — trusting an `event:` line with a `"message"`
 * default — every frame parses "successfully" as `message` and falls through to
 * the unknown path. Nothing throws, nothing is empty, and the stream carries a
 * full complement of frames that mean nothing. That is precisely what a live
 * run produced: 14 frames, all unrecognised, no text, no terminal.
 *
 * The `event:` line is still honoured as a FALLBACK, so a future endpoint that
 * does use it is not broken by this — but the payload's own `type` wins, being
 * the field the backend actually sets.
 */
export function parseRecord(record: string): AughorFrame | null {
  let sseEvent = "";
  const data: string[] = [];
  for (const line of record.split("\n")) {
    if (line.startsWith("event:")) sseEvent = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  if (!data.length) return null;
  try {
    const payload = JSON.parse(data.join("\n")) as Record<string, unknown>;
    const inPayload = typeof payload.type === "string" ? payload.type : "";
    return { event: inPayload || sseEvent || "message", data: payload };
  } catch {
    // A frame whose JSON does not parse is a backend bug, not a reason to kill
    // the turn — surface it rather than dropping it.
    return { event: "error", data: { message: `unparseable ${sseEvent || "data"} frame` } };
  }
}

/**
 * Incremental SSE splitter. Feed decoded text; get back whole frames and keep
 * the partial tail for the next call.
 */
export class FrameBuffer {
  private buffer = "";

  push(text: string): AughorFrame[] {
    this.buffer += text;
    const out: AughorFrame[] = [];
    let sep: number;
    while ((sep = this.buffer.indexOf("\n\n")) !== -1) {
      const record = this.buffer.slice(0, sep);
      this.buffer = this.buffer.slice(sep + 2);
      const frame = parseRecord(record);
      if (frame) out.push(frame);
    }
    return out;
  }

  /** Whatever never terminated with a blank line. Non-empty means a truncated stream. */
  get pending(): string {
    return this.buffer;
  }
}

/** Read an SSE body to completion, yielding frames as they complete. */
export async function* readFrames(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<AughorFrame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const frames = new FrameBuffer();
  try {
    for (;;) {
      if (signal?.aborted) break;
      const { done, value } = await reader.read();
      if (done) break;
      for (const f of frames.push(decoder.decode(value, { stream: true }))) yield f;
    }
  } finally {
    reader.releaseLock();
  }
}
