/**
 * PENDING item 15 — both buttons go through the unified `/ask` door, where the conversation agent
 * holds the ontology's tools: Quick at quick depth, Agent at deep. A send carrying more than a
 * question keeps its own door (Quick → `/chat`, Agent → the deep-analysis door).
 */
import { describe, expect, it } from "vitest";

import type { ChatMode } from "@/components/ChatPanel";
import { doorFor, isPlainSend } from "@/lib/chatDoors";

/** The Agent button's wire value — the backend spelling, named once. */
const AGENT: ChatMode = "investigate";

describe("doorFor", () => {
  it("sends Quick to /ask at quick depth and Agent to /ask at deep depth", () => {
    expect(doorFor("ask", "auto")).toEqual({ mode: "auto", depth: "quick" });
    expect(doorFor(AGENT, "auto")).toEqual({ mode: "auto", depth: "deep" });
  });

  it("keeps a depth the person chose, and leaves turns already on /ask alone", () => {
    expect(doorFor(AGENT, "quick")).toEqual({ mode: "auto", depth: "quick" });
    expect(doorFor("auto", "auto")).toEqual({ mode: "auto", depth: "auto" });
    expect(doorFor("auto", "deep")).toEqual({ mode: "auto", depth: "deep" });
  });

  it("leaves a send that carries more than a question on its own door", () => {
    expect(doorFor(AGENT, "auto", false)).toEqual({ mode: AGENT, depth: "auto" });
    expect(doorFor("ask", "auto", false)).toEqual({ mode: "ask", depth: "auto" });
  });

  it("reads a send as plain only when it carries nothing but a depth or a schema", () => {
    expect(isPlainSend({})).toBe(true);
    expect(isPlainSend({ depth: "quick", schema: "shop", skipCache: false })).toBe(true);
    expect(isPlainSend({ skipCache: true })).toBe(false);
    expect(isPlainSend({ seedSql: "SELECT 1" })).toBe(false);
  });
});
