// @vitest-environment jsdom
/**
 * PENDING item 9 — the company-brain map: each store a box with a live count and its door, a
 * store that could not be read shown as a dash with its reason (never a zero), measured links
 * as sentences, and CB-1's changed facts with what they replaced. Shape: `aughor/hub/brain_map.py`.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BrainMap } from "@/lib/api";
import { boxFigure, edgeLines, recentFacts, vaultColumns } from "@/lib/brainMap";

const MAP: BrainMap = {
  connection_id: "c1",
  vaults: [{ id: "company", title: "What it knows" }, { id: "engagement", title: "What it did with people" },
           { id: "working_memory", title: "What people told it" }],
  boxes: [
    { id: "facts", vault: "company", title: "Dated facts", door: "GET /graph", count: 17, unit: "facts",
      line: "17 of 17 dated · 1 changed since first seen · 0 retired, kept",
      detail: { recent: [{ id: "metric:aov", kind: "metric", label: "aov", first_seen: "2026-09-23T10:00:00Z",
        last_changed: "2026-09-23T10:05:00Z", observed_at: "", observed_basis: "build",
        history: [{ replaced_at: "2026-09-23T10:05:00Z", reason: "corrected", facts: { formula_sql: "AVG(total_amount)" } }] }] } },
    { id: "visibility", vault: "company", title: "What the platform can see", door: "GET /visibility", count: null, unit: "",
      line: "the profiler has not seen this connection, so the denominator is unknown", detail: {} },
    { id: "findings", vault: "engagement", title: "Findings", door: "GET /exploration/{conn}/domains", count: 1250, unit: "findings",
      line: "1,250 across 9 domains", detail: {} },
    { id: "owners", vault: "working_memory", title: "Owners reachable", door: "GET /owners", count: 0, unit: "owners reachable",
      line: "0 of 7 named owners reachable", detail: {} },
  ],
  edges: [{ from: "findings", to: "facts", count: 3, label: "findings landed in the graph as facts" }],
};

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), getBrainMap: vi.fn(async () => MAP) }));

describe("brainMap", () => {
  it("groups boxes by vault and reads an unknown as a dash, never a zero", () => {
    expect(vaultColumns(MAP).map((v) => [v.id, v.boxes.map((b) => b.id)])).toEqual([
      ["company", ["facts", "visibility"]], ["engagement", ["findings"]], ["working_memory", ["owners"]]]);
    expect(boxFigure(MAP.boxes[1])).toBe("—");
    expect(boxFigure(MAP.boxes[2])).toBe("1,250");
    expect(boxFigure(MAP.boxes[3])).toBe("0");
  });

  it("writes each measured link with both ends' titles, and each changed fact with what it replaced", () => {
    expect(edgeLines(MAP)).toEqual(["Findings → Dated facts: 3 findings landed in the graph as facts"]);
    expect(recentFacts(MAP)).toEqual([{ id: "metric:aov", changed: "2026-09-23", replaced: "AVG(total_amount)", reason: "corrected" }]);
  });
});

describe("BrainMapPanel", () => {
  it("renders every box with its door and says why a box has no number", async () => {
    const { BrainMapPanel } = await import("@/components/BrainMapPanel");
    render(<BrainMapPanel connectionId="c1" />);
    await waitFor(() => expect(screen.getByTestId("brain-map")).toBeTruthy());
    expect(screen.getByTestId("brain-box-visibility").textContent).toContain("the denominator is unknown");
    // The door (a route) rides the box's tooltip since the ids-as-names movement (study §9.5);
    // the face carries the name and the count.
    expect(screen.getByTestId("brain-box-facts").getAttribute("title")).toBe("GET /graph");
    expect(screen.getByTestId("brain-box-facts").textContent).not.toContain("GET /graph");
    expect(screen.getByText(/it replaced/).textContent).toContain("AVG(total_amount)");
  });
});
