/**
 * PENDING item 15 — with `chat.buttons_reach_agent` off, a button's turn is sent exactly as before
 * (Quick → `/chat`, Agent → the deep-analysis door); on, both go through the unified `/ask` door,
 * where the conversation agent holds the ontology's tools.
 */
import { describe, expect, it } from "vitest";

import type { ChatMode } from "@/components/ChatPanel";
import { doorFor } from "@/lib/chatDoors";

/** The Agent button's wire value — the backend spelling, named once. */
const AGENT: ChatMode = "investigate";

describe("doorFor", () => {
  it("changes nothing while the flag is off", () => {
    expect(doorFor("ask", "auto", false)).toEqual({ mode: "ask", depth: "auto" });
    expect(doorFor(AGENT, "auto", false)).toEqual({ mode: AGENT, depth: "auto" });
    expect(doorFor("auto", "deep", false)).toEqual({ mode: "auto", depth: "deep" });
  });

  it("sends Quick to /ask at quick depth and Agent to /ask at deep depth when on", () => {
    expect(doorFor("ask", "auto", true)).toEqual({ mode: "auto", depth: "quick" });
    expect(doorFor(AGENT, "auto", true)).toEqual({ mode: "auto", depth: "deep" });
  });

  it("keeps a depth the person chose, and leaves turns already on /ask alone", () => {
    expect(doorFor(AGENT, "quick", true)).toEqual({ mode: "auto", depth: "quick" });
    expect(doorFor("auto", "auto", true)).toEqual({ mode: "auto", depth: "auto" });
  });
});
