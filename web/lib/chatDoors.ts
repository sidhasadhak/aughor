/**
 * PENDING item 15 — which backend door a chat button's turn goes through.
 *
 * Measured 2026-09-23: Quick posted `/chat` and the default Agent button the deep-analysis door;
 * only Edit, starters, clarify answers and re-runs reached the unified `/ask`, where the
 * conversation agent holds the ontology's tools (look up an object, describe a type). Now both
 * buttons go through `/ask` — Quick at quick depth, Agent at deep depth — the user's call of
 * 2026-09-24, taken knowing a conversation turn costs ~20k tokens (ROADMAP §3.22); part of the
 * platform since 2026-10-28 (it was the flag `chat.buttons_reach_agent`, ROADMAP §3.65).
 */
import type { ChatMode } from "@/components/ChatPanel";

export type ButtonMode = ChatMode | "auto";
type Depth = "auto" | "quick" | "deep";

/**
 * ``plain`` is false for a send that carries more than a question — seed SQL, a cache skip, a
 * finding id, a starter's mode: `/ask` does not forward those fields, so such a send keeps its own
 * door (found by the branch review, 2026-09-24: "Run fresh" was quietly served from cache and
 * "Explore this fact" lost its seed).
 */
export function doorFor(mode: ButtonMode, depth: Depth, plain = true): { mode: ButtonMode; depth: Depth } {
  if (!plain || mode === "auto") return { mode, depth };
  const own: Depth = mode === "ask" ? "quick" : "deep";     // Quick → quick; the Agent button → deep
  return { mode: "auto", depth: depth === "auto" ? own : depth };
}

/** The only per-turn options a plain question carries; anything else set means the send carries
 *  more than a question, and keeps its own door. */
const PLAIN_KEYS = new Set(["depth", "schema"]);

export function isPlainSend(opts: object): boolean {
  return Object.entries(opts).every(([k, v]) => PLAIN_KEYS.has(k) || !v);
}
