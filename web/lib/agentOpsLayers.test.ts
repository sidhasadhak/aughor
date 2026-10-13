/**
 * Agent Ops' layers by the id a link names them with. The Activity tab folded into the Overview (2026-10-13); a link
 * that still says `layer=activity` — a bookmark, a link someone was sent, the UI study's list of screens — lands on the
 * Overview, never on nothing.
 */
import { describe, expect, it } from "vitest";

import { AGENT_OPS_LAYERS, OVERVIEW_LAYER, agentOpsLayerOf } from "@/lib/agentOpsLayers";

describe("an Agent Ops layer named by a link", () => {
  it("lands a folded layer on the one that holds it: layer=activity is the Overview", () => {
    expect(OVERVIEW_LAYER).toBe("fleet"); // the Overview's frozen id — every link names it so
    expect(agentOpsLayerOf("activity")).toBe(OVERVIEW_LAYER);
  });

  it("takes every live layer as it is", () => {
    for (const id of AGENT_OPS_LAYERS) expect(agentOpsLayerOf(id)).toBe(id);
    expect(AGENT_OPS_LAYERS).not.toContain("activity");
  });

  it("names nothing for an id it does not know — an inherited key included", () => {
    for (const id of ["", null, undefined, "nope", "constructor", "toString", "Activity"]) {
      expect(agentOpsLayerOf(id)).toBeNull();
    }
  });
});
