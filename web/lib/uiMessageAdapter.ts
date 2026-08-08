/**
 * C1 spike — the Aughor-SSE → AI SDK `UIMessage` adapter (Track C's one
 * load-bearing artifact, roadmap 2026-08-01 §C1).
 *
 * Track C's thesis: vercel/chatbot is a SHELL — the brain stays Python, a route
 * handler proxies `/ask`, and everything the shell renders arrives as AI SDK v7
 * `UIMessage` parts. This module is the seam that makes that true: a PURE
 * translator from Aughor's SSE frame vocabulary (see `investigationStream.ts`,
 * the authority on frame shapes) to UIMessage part deltas.
 *
 * THE TRAP THIS EXISTS TO SOLVE — replace vs append. Aughor's `*_delta` frames
 * carry the WHOLE partial so far (`narrative_delta` = the full narrative text
 * rewritten every frame; the terminal frame then replaces the partial outright).
 * The AI SDK's `text-delta` parts APPEND. Feeding replace-frames to an
 * append-consumer duplicates the prefix on every frame — the answer renders as
 * "TheThe reThe revenue…". `DeltaDiffer` converts: it remembers what it has
 * emitted for a channel and emits only the new SUFFIX; a partial that ever
 * REWRITES its prefix (a re-synthesis) resets the channel with a fresh part id,
 * which is the AI SDK's own idiom for "start a new text block".
 *
 * Ported invariants from `consumeStream` (WP-2), which the Track-C route handler
 * must keep even though this module doesn't do I/O:
 *   • content-type guard — a non-`text/event-stream` response is an ERROR part,
 *     never a silent empty stream;
 *   • drop-recovery — the early `start` frame's investigation id is surfaced so
 *     the caller can poll a dropped run's terminal state;
 *   • error-terminal — every terminal frame (`done`/`error`/report frames)
 *     closes the message; no frame after a terminal one is emitted.
 *
 * Report/figure frames ride as typed `data-*` parts (the AI SDK's escape hatch
 * for structured payloads), mirroring the AG-UI translator's whole-payload rule
 * (`routers/agui.py` `_REPORT_TOOLS` — render_ada/report/dossier/explore/
 * overview), so the chatbot shell routes on part type exactly like the AG-UI
 * frontend routes on tool name.
 */

// ── AI SDK v7 part shapes (the subset the shell consumes) ────────────────────
// Declared locally so the spike compiles without the `ai` package; PR-C2 swaps
// these for the real imports (they are structurally identical).

export type UIMessagePart =
  | { type: "text-start"; id: string }
  | { type: "text-delta"; id: string; delta: string }
  | { type: "text-end"; id: string }
  | { type: "reasoning-delta"; id: string; delta: string }
  | { type: `data-${string}`; id?: string; data: unknown }
  | { type: "error"; errorText: string };

export type AughorFrame = { event: string; data: Record<string, unknown> };

// ── the replace→append converter ─────────────────────────────────────────────

/** Per-channel partial-text state: what we've already emitted, under which part id. */
class Channel {
  emitted = "";
  partId: string;
  open = false;
  constructor(readonly key: string, private nextId: () => string) {
    this.partId = nextId();
  }

  /** Convert one REPLACE-style partial into APPEND parts. */
  take(full: string): UIMessagePart[] {
    const parts: UIMessagePart[] = [];
    if (!this.open) {
      parts.push({ type: "text-start", id: this.partId });
      this.open = true;
    }
    if (full.startsWith(this.emitted)) {
      const suffix = full.slice(this.emitted.length);
      if (suffix) parts.push({ type: "text-delta", id: this.partId, delta: suffix });
    } else {
      // The partial rewrote its own prefix (a re-synthesis) — close this block and
      // open a fresh one, the SDK idiom for "new text block", never a spliced edit.
      parts.push({ type: "text-end", id: this.partId });
      this.partId = this.nextId();
      parts.push({ type: "text-start", id: this.partId });
      if (full) parts.push({ type: "text-delta", id: this.partId, delta: full });
    }
    this.emitted = full;
    return parts;
  }

  close(): UIMessagePart[] {
    if (!this.open) return [];
    this.open = false;
    return [{ type: "text-end", id: this.partId }];
  }
}

/** Which frame types are partial channels, and where their text lives. */
const DELTA_CHANNELS: Record<string, string> = {
  narrative_delta: "narrative",
  insight_delta: "narrative",     // legacy spelling of the same channel
  headline_delta: "headline",
  report_delta: "executive_summary",
};

/** Terminal report frames → the `data-*` part the shell routes on (mirrors
 * `routers/agui.py::_REPORT_TOOLS` name-for-name). */
const REPORT_PARTS: Record<string, string> = {
  answer_report: "data-render_ada",
  report: "data-render_report",
  dossier_report: "data-render_dossier",
  explore_report: "data-render_explore",
  overview_report: "data-render_overview",
};

/** Advisory frames worth surfacing as typed data parts (not text). */
const DATA_PARTS = new Set([
  "route", "figure", "sql", "columns", "rows", "chart_type", "chart_config",
  "tables_used", "guard_receipt", "clarify_pending", "plan_pending",
  "context_receipt", "agent_badge", "status",
]);

export interface AdapterResult {
  parts: UIMessagePart[];
  /** Set once, from the early `start` frame — the WP-2 drop-recovery handle. */
  investigationId?: string;
  /** True after a terminal frame; the caller must stop feeding frames. */
  terminal: boolean;
}

/**
 * Stateful converter for ONE assistant turn. Feed frames in arrival order;
 * append the returned parts to the UIMessage. Pure state machine — no I/O.
 */
export class AughorToUIMessage {
  private channels = new Map<string, Channel>();
  private seq = 0;
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

  private closeAll(): UIMessagePart[] {
    const out: UIMessagePart[] = [];
    for (const ch of this.channels.values()) out.push(...ch.close());
    return out;
  }

  feed(frame: AughorFrame): AdapterResult {
    if (this.done) {
      // error-terminal invariant: nothing renders after a terminal frame.
      return { parts: [], investigationId: this.invId, terminal: true };
    }
    const { event, data } = frame;
    const parts: UIMessagePart[] = [];

    if (event === "start") {
      const id = data["investigation_id"];
      if (typeof id === "string" && id) this.invId = id;
      return { parts, investigationId: this.invId, terminal: false };
    }

    const channelField = DELTA_CHANNELS[event];
    if (channelField !== undefined) {
      const full = String(data[channelField] ?? "");
      parts.push(...this.channel(event === "headline_delta" ? "headline" : "narrative").take(full));
      return { parts, investigationId: this.invId, terminal: false };
    }

    const reportPart = REPORT_PARTS[event];
    if (reportPart !== undefined) {
      // Terminal narrative replaces the partial stream (delta frames are advisory) —
      // close every open text block, then hand the WHOLE payload over as data.
      parts.push(...this.closeAll());
      parts.push({ type: reportPart as `data-${string}`, id: this.nextId(), data });
      this.done = true;
      return { parts, investigationId: this.invId, terminal: true };
    }

    if (event === "error") {
      parts.push(...this.closeAll());
      parts.push({ type: "error", errorText: String(data["message"] ?? "stream error") });
      this.done = true;
      return { parts, investigationId: this.invId, terminal: true };
    }

    if (event === "done") {
      parts.push(...this.closeAll());
      this.done = true;
      return { parts, investigationId: this.invId, terminal: true };
    }

    if (DATA_PARTS.has(event)) {
      parts.push({ type: `data-${event}`, id: this.nextId(), data });
      return { parts, investigationId: this.invId, terminal: false };
    }

    // Unknown frame: forward as data rather than dropping — the shell may ignore it,
    // but a silently swallowed frame class is how features stop existing (the S2
    // lesson: both ends can exist while the middle drops the payload).
    parts.push({ type: `data-${event}`, id: this.nextId(), data });
    return { parts, investigationId: this.invId, terminal: false };
  }
}

/** Convenience for tests and the C2 route handler: run a whole frame list. */
export function adaptFrames(frames: AughorFrame[]): AdapterResult {
  const adapter = new AughorToUIMessage();
  const parts: UIMessagePart[] = [];
  let invId: string | undefined;
  let terminal = false;
  for (const f of frames) {
    const r = adapter.feed(f);
    parts.push(...r.parts);
    invId = r.investigationId ?? invId;
    terminal = r.terminal;
    if (terminal) break;
  }
  return { parts, investigationId: invId, terminal };
}
