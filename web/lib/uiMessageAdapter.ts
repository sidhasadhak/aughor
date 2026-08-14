/**
 * The Aughor-SSE → AI SDK stream adapter — CI-1d (was the C1 spike, 2026-08-01).
 *
 * Track C's thesis: vercel/chatbot is a SHELL — the brain stays Python, a route
 * handler proxies `/ask`, and everything the shell renders arrives as AI SDK
 * chunks. This module is the seam that makes that true: a PURE translator from
 * Aughor's SSE frame vocabulary (see `investigationStream.ts`, the authority on
 * frame shapes) to the SDK's stream protocol. No I/O.
 *
 * ── What changed when the spike met the real package ────────────────────────
 *
 * The spike declared its own part types locally and said they were
 * "structurally identical" to the SDK's, to be swapped for real imports later.
 * Checked against `ai@7`, that was wrong in three ways, and each one is a bug
 * the shell would have hit:
 *
 *   1. IT WAS THE WRONG TYPE. `text-start` / `text-delta` / `text-end` are
 *      `UIMessageChunk` — the STREAMING form. `UIMessagePart`, the name the
 *      spike used, is the PERSISTED form (`TextUIPart`, `DataUIPart`, …) that a
 *      chunk stream accumulates INTO. Emitting parts where chunks are expected
 *      does not type-check and does not stream.
 *
 *   2. IT NEVER OPENED OR CLOSED THE MESSAGE. The protocol brackets a turn with
 *      `start` and `finish` chunks. The spike emitted neither, so a consumer
 *      would never see the message begin or end.
 *
 *   3. `data-${string}` DOES NOT SATISFY THE DATA ARM. That arm is
 *      `DataUIMessageChunk<DATA_TYPES>`, a mapped type over a declared
 *      `UIDataTypes` map — so the part NAMES have to be a closed set. They now
 *      are, in `aughorUIDataTypes.ts`, extracted from the reducer's own wire
 *      vocabulary rather than hand-listed (the spike's set covered 14 of ~35).
 *
 * ── The trap this module exists to solve: REPLACE vs APPEND ─────────────────
 *
 * Aughor's `*_delta` frames carry the WHOLE partial so far (`narrative_delta` =
 * the full narrative rewritten every frame; the terminal frame then replaces the
 * partial outright). The SDK's `text-delta` chunks APPEND. Feeding
 * replace-frames to an append-consumer duplicates the prefix on every frame —
 * the answer renders as "TheThe reThe revenue…".
 *
 * `Channel` converts: it remembers what it has emitted and emits only the new
 * SUFFIX. A partial that ever REWRITES its prefix (a re-synthesis) closes its
 * block and opens a fresh one with a new id — the SDK's own idiom for "start a
 * new text block", never a spliced edit.
 *
 * ── Invariants ported from `consumeStream` (WP-2) ───────────────────────────
 * The route handler that does the I/O must keep these even though this module
 * doesn't:
 *   • content-type guard — a non-`text/event-stream` response is an `error`
 *     chunk, never a silent empty stream;
 *   • drop-recovery — the early `start` frame's investigation id is surfaced so
 *     the caller can poll a dropped run's terminal state;
 *   • error-terminal — every terminal frame closes the message, and no frame
 *     after a terminal one is emitted.
 */

import type { UIMessageChunk } from "ai";

import {
  DECLARED_DATA_PARTS,
  REPORT_FRAMES,
  UNRENDERED_FRAMES,
  type AughorUIDataTypes,
} from "./aughorUIDataTypes";

/** The chunk type this adapter emits, bound to Aughor's data-part vocabulary. */
export type AughorChunk = UIMessageChunk<unknown, AughorUIDataTypes>;

export type AughorFrame = { event: string; data: Record<string, unknown> };

// ── the replace→append converter ─────────────────────────────────────────────

/** Per-channel partial-text state: what we've already emitted, under which id. */
class Channel {
  emitted = "";
  partId: string;
  open = false;

  constructor(
    readonly key: string,
    private nextId: () => string,
  ) {
    this.partId = nextId();
  }

  /** Convert one REPLACE-style partial into APPEND chunks. */
  take(full: string): AughorChunk[] {
    const chunks: AughorChunk[] = [];
    // An empty partial opens nothing. Frames legitimately carry "" — a channel
    // that has not produced text yet, or a field this turn never fills — and
    // opening a block for one yields an EMPTY text part, which renders as a
    // blank paragraph the reader cannot account for. A live run produced three
    // blocks for two pieces of text this way.
    if (!this.open && !full) return chunks;
    if (!this.open) {
      chunks.push({ type: "text-start", id: this.partId });
      this.open = true;
    }
    if (full.startsWith(this.emitted)) {
      const suffix = full.slice(this.emitted.length);
      if (suffix) chunks.push({ type: "text-delta", id: this.partId, delta: suffix });
    } else {
      // The partial rewrote its own prefix (a re-synthesis) — close this block
      // and open a fresh one, never a spliced edit.
      chunks.push({ type: "text-end", id: this.partId });
      this.partId = this.nextId();
      chunks.push({ type: "text-start", id: this.partId });
      if (full) chunks.push({ type: "text-delta", id: this.partId, delta: full });
    }
    this.emitted = full;
    return chunks;
  }

  close(): AughorChunk[] {
    if (!this.open) return [];
    this.open = false;
    return [{ type: "text-end", id: this.partId }];
  }
}

/**
 * Which frame types carry the answer's TEXT, and which field holds it.
 *
 * Both the partial (`*_delta`) and the SETTLED frame route here, to the same
 * channel. That is not symmetry for its own sake — a live turn exposed the bug:
 * with only the deltas mapped, a turn that streams settled `headline` frames
 * (`mode: {query_mode: "final_text"}`) rendered its entire answer — prose, a
 * markdown table, the actual numbers — as a JSON blob in a `<pre>`, because it
 * fell through to the data path. The answer was present and unreadable.
 *
 * Routing both is safe because `Channel.take()` is REPLACE-semantic: a settled
 * frame carrying the whole text either extends what was already emitted (the
 * common case, when deltas preceded it) or rewrites the prefix and opens a fresh
 * block. Either way the reader sees prose, and no text is emitted twice.
 */
const TEXT_CHANNELS: Record<string, { field: string; channel: string }> = {
  // partials — the whole text so far, re-sent each frame
  narrative_delta: { field: "narrative", channel: "narrative" },
  insight_delta: { field: "narrative", channel: "narrative" }, // legacy spelling
  headline_delta: { field: "headline", channel: "headline" },
  report_delta: { field: "executive_summary", channel: "narrative" },
  // settled — the final text for that channel
  narrative: { field: "narrative", channel: "narrative" },
  insight: { field: "insight", channel: "narrative" },
  headline: { field: "headline", channel: "headline" },
  answer: { field: "answer", channel: "narrative" },
};

export interface AdapterResult {
  chunks: AughorChunk[];
  /** Set once, from the early `start` frame — the WP-2 drop-recovery handle. */
  investigationId?: string;
  /** True after a terminal frame; the caller must stop feeding frames. */
  terminal: boolean;
}

/**
 * Stateful converter for ONE assistant turn. Feed frames in arrival order and
 * forward the returned chunks. Pure state machine — no I/O.
 */
export class AughorToUIMessage {
  private channels = new Map<string, Channel>();
  private seq = 0;
  private started = false;
  private done = false;
  private invId: string | undefined;

  private nextId = () => `aug_${++this.seq}`;

  private channel(key: string): Channel {
    let ch = this.channels.get(key);
    if (!ch) {
      ch = new Channel(key, this.nextId);
      this.channels.set(key, ch);
    }
    return ch;
  }

  private closeAll(): AughorChunk[] {
    const out: AughorChunk[] = [];
    for (const ch of this.channels.values()) out.push(...ch.close());
    return out;
  }

  /** The protocol's message-open chunk, emitted lazily before the first content. */
  private open(): AughorChunk[] {
    if (this.started) return [];
    this.started = true;
    return [{ type: "start" }];
  }

  /** Close every open text block, then the message. Idempotent via `done`. */
  private finish(): AughorChunk[] {
    const out = [...this.closeAll()];
    out.push({ type: "finish" });
    this.done = true;
    return out;
  }

  /**
   * A DECLARED frame becomes its own typed data part; an undeclared one rides
   * the escape hatch carrying its event name.
   *
   * The cast is confined to the declared branch, where `DECLARED_DATA_PARTS`
   * has just proved the name is a key of the map — the one place the runtime
   * set meets the SDK's mapped type. The undeclared branch needs no cast at
   * all, which is the point: `data-${anything}` does not type-check against a
   * closed map, and TypeScript rejects it at the CONSUME site even when an
   * `as` silences the emit site.
   */
  private data(name: string, payload: Record<string, unknown>): AughorChunk {
    if (DECLARED_DATA_PARTS.has(name)) {
      return { type: `data-${name}`, id: this.nextId(), data: payload } as AughorChunk;
    }
    return {
      type: "data-unknown_frame",
      id: this.nextId(),
      data: { event: name, payload },
    };
  }

  feed(frame: AughorFrame): AdapterResult {
    if (this.done) {
      // error-terminal invariant: nothing renders after a terminal frame.
      return { chunks: [], investigationId: this.invId, terminal: true };
    }
    const { event, data } = frame;
    const chunks: AughorChunk[] = [];

    if (event === "start") {
      const id = data["investigation_id"];
      if (typeof id === "string" && id) this.invId = id;
      // The wire's `start` carries the run handle; the protocol's `start` opens
      // the message. Same word, different jobs — emit ours here.
      chunks.push(...this.open());
      return { chunks, investigationId: this.invId, terminal: false };
    }

    chunks.push(...this.open());

    const ch = TEXT_CHANNELS[event];
    if (ch !== undefined) {
      chunks.push(...this.channel(ch.channel).take(String(data[ch.field] ?? "")));
      return { chunks, investigationId: this.invId, terminal: false };
    }

    if (REPORT_FRAMES.has(event as never)) {
      // A terminal report REPLACES the partial stream (delta frames are
      // advisory) — close every open text block, hand the whole payload over as
      // data, then close the message.
      chunks.push(...this.closeAll());
      chunks.push(this.data(event, data));
      chunks.push(...this.finish());
      return { chunks, investigationId: this.invId, terminal: true };
    }

    if (event === "error") {
      chunks.push(...this.closeAll());
      chunks.push({ type: "error", errorText: String(data["message"] ?? "stream error") });
      chunks.push(...this.finish());
      return { chunks, investigationId: this.invId, terminal: true };
    }

    if (event === "done") {
      chunks.push(...this.finish());
      return { chunks, investigationId: this.invId, terminal: true };
    }

    // A frame the reducer deliberately renders nothing for is skipped rather
    // than surfaced. Not a swallow — a written-down decision: once a
    // deliberately-silent frame renders as "unrecognised: <name>", it is
    // indistinguishable from a genuine gap, which is the ambiguity the
    // reducer's own list exists to end.
    if (UNRENDERED_FRAMES.has(event)) {
      return { chunks, investigationId: this.invId, terminal: false };
    }

    // A declared advisory frame rides as its typed data part; a frame in
    // NEITHER list rides the escape hatch rather than being dropped. A silently
    // swallowed frame class is how features stop existing — and this is the
    // property the reducer's closed switch could not offer, since a `default:`
    // there can only warn, never render. Here an unknown frame reaches the
    // shell, which may ignore it, but cannot be unaware of it.
    chunks.push(this.data(event, data));
    return { chunks, investigationId: this.invId, terminal: false };
  }

  /**
   * Close a turn the backend never terminated — a dropped connection. Returns
   * the chunks needed to leave the message well-formed; empty if already done.
   */
  abort(reason?: string): AughorChunk[] {
    if (this.done) return [];
    const out = [...this.open(), ...this.closeAll()];
    out.push({ type: "abort", reason });
    this.done = true;
    return out;
  }
}

/** Whether a frame name has a declared data part (vs riding the unknown path). */
export function isDeclaredDataPart(event: string): boolean {
  return DECLARED_DATA_PARTS.has(event);
}

/** Convenience for tests and the route handler: run a whole frame list. */
export function adaptFrames(frames: AughorFrame[]): AdapterResult {
  const adapter = new AughorToUIMessage();
  const chunks: AughorChunk[] = [];
  let invId: string | undefined;
  let terminal = false;
  for (const f of frames) {
    const r = adapter.feed(f);
    chunks.push(...r.chunks);
    invId = r.investigationId ?? invId;
    terminal = r.terminal;
    if (terminal) break;
  }
  return { chunks, investigationId: invId, terminal };
}
