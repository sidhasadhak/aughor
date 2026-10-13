// @vitest-environment jsdom
/**
 * PENDING item 9 — the company-brain map: each store a box with a live count and its door, a
 * store that could not be read shown as a dash with its reason (never a zero), measured links
 * drawn as arrows between the boxes (their sentences on hover), and CB-1's changed facts with
 * what they replaced. Shape: `aughor/hub/brain_map.py`.
 */
import { fireEvent, render, screen, waitFor } from "@/lib/testing";
import { describe, expect, it, vi } from "vitest";

import { getBrainMap, type BrainMap } from "@/lib/api";
import { boxFigure, edgeLines, edgeShort, mapLayout, recentFacts, vaultColumns } from "@/lib/brainMap";

const MAP: BrainMap = {
  connection_id: "c1",
  vaults: [{ id: "company", title: "What it knows" }, { id: "engagement", title: "What it did with people" },
           { id: "working_memory", title: "What people told it" }],
  boxes: [
    { id: "facts", vault: "company", title: "Dated facts", door: "GET /graph", count: 17, unit: "facts",
      line: "17 of 17 dated · 1 changed since first seen · 0 retired, kept",
      detail: { with_history: 1, recent: [{ id: "metric:aov", kind: "metric", label: "aov", first_seen: "2026-09-23T10:00:00Z",
        last_changed: "2026-09-23T10:05:00Z", observed_at: "", observed_basis: "build",
        history: [{ replaced_at: "2026-09-23T10:05:00Z", reason: "corrected", facts: { formula_sql: "AVG(total_amount)", tables: ["orders", "items"] } }] }] } },
    { id: "visibility", vault: "company", title: "What the platform can see", door: "GET /visibility", count: null, unit: "",
      line: "Reads 4 tables — how many this connection holds is not known yet", detail: {} },
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
    expect(recentFacts(MAP)).toEqual([{ id: "metric:aov", label: "aov", kind: "metric", changed: "2026-09-23",
      replaced: "AVG(total_amount) · orders, items", reason: "corrected" }]);
  });

  it("puts an arrow's count and its noun on the arrow, the sentence for its hover", () => {
    expect(edgeShort(MAP.edges[0])).toBe("3 findings");
    expect(edgeShort({ from: "a", to: "b", count: 0, label: "Briefing citations of findings" })).toBe("0 Briefing citations");
    expect(edgeShort({ from: "a", to: "b", count: 1204, label: "contradicted claims raised as a question" }))
      .toBe("1,204 contradicted claims");
  });

  it("draws each arrow in straight runs between the boxes it joins, and says in words one it cannot draw", () => {
    const map: BrainMap = { ...MAP, edges: [
      ...MAP.edges,
      { from: "facts", to: "findings", count: 0, label: "Briefing citations of findings" },
      { from: "visibility", to: "facts", count: 2, label: "tables in the graph" },
      { from: "facts", to: "owners", count: 1, label: "owners named by facts" },
    ] };
    const out = mapLayout(map);
    expect(out.nodes.map((n) => [n.box.id, n.col, n.row])).toEqual([
      ["facts", 0, 0], ["visibility", 0, 1], ["findings", 1, 0], ["owners", 2, 0]]);
    const byKey = Object.fromEntries(out.routes.map((r) => [`${r.edge.from}>${r.edge.to}`, r]));
    // Two arrows between one pair run side by side, each straight, from one box's edge to the other's.
    const there = byKey["findings>facts"];
    const back = byKey["facts>findings"];
    for (const r of [there, back]) {
      expect(r.segs).toHaveLength(1);
      expect(r.segs[0].y1).toBe(r.segs[0].y2);
    }
    expect(there.segs[0].y1).not.toBe(back.segs[0].y1);
    const facts = out.nodes[0];
    const findings = out.nodes[2];
    expect(there.segs[0]).toMatchObject({ x1: findings.x0, x2: facts.x1 });
    // Stacked neighbours in one column: one vertical run from the lower box's top to the upper box's bottom.
    const mid = (facts.x0 + facts.x1) / 2;
    expect(byKey["visibility>facts"].segs).toEqual([{ x1: mid, y1: out.nodes[1].y0, x2: mid, y2: facts.y1 }]);
    // Two vaults apart, the arrow would cross a box: it is said, not drawn.
    expect(byKey["facts>owners"]).toBeUndefined();
    expect(out.unplaced).toEqual(["Dated facts → Owners reachable: 1 owners named by facts"]);
    // Every run is horizontal or vertical — never a diagonal.
    for (const r of out.routes) for (const s of r.segs) expect(s.x1 === s.x2 || s.y1 === s.y2).toBe(true);
  });
});

describe("BrainMapPanel", () => {
  it("renders every box with its door and says why a box has no number", async () => {
    const { BrainMapPanel } = await import("@/components/BrainMapPanel");
    render(<BrainMapPanel connectionId="c1" />);
    await waitFor(() => expect(screen.getByTestId("brain-map")).toBeTruthy());
    expect(screen.getByTestId("brain-box-visibility").textContent).toContain("how many this connection holds is not known yet");
    expect(screen.getByTestId("brain-box-visibility").textContent).toContain("—");
    // The door (a route) rides the box's tooltip since the ids-as-names movement (study §9.5);
    // the face carries the name and the count.
    expect(screen.getByTestId("brain-box-facts").getAttribute("title")).toBe("GET /graph");
    expect(screen.getByTestId("brain-box-facts").textContent).not.toContain("GET /graph");
    // The link is an arrow on the picture: its count on the face, its sentence for a reader who cannot see it.
    const edge = screen.getByTestId("brain-edge-findings-facts");
    expect(edge.textContent).toBe("3 findings");
    expect(edge.getAttribute("aria-label")).toBe("Findings → Dated facts: 3 findings landed in the graph as facts");
    // A changed fact names what it replaced.
    expect(screen.getByTestId("brain-fact-metric:aov").textContent).toContain("was AVG(total_amount)");
  });

  it("says a failed read and reads again on Retry — never an empty map", async () => {
    vi.mocked(getBrainMap).mockRejectedValueOnce(new Error("Failed to load the brain map"));
    const { BrainMapPanel } = await import("@/components/BrainMapPanel");
    render(<BrainMapPanel connectionId="c1" />);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Could not read the brain map"));
    expect(screen.queryByTestId("brain-map")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByTestId("brain-map")).toBeTruthy());
  });

  it("says the fact history was not read when the facts store could not be read, rather than that nothing changed", async () => {
    vi.mocked(getBrainMap).mockResolvedValueOnce({ ...MAP, boxes: MAP.boxes.map((b) => (b.id === "facts"
      ? { ...b, count: null, detail: {}, line: "could not be read (OSError)" } : b)) });
    const { BrainMapPanel } = await import("@/components/BrainMapPanel");
    render(<BrainMapPanel connectionId="c1" />);
    await waitFor(() => expect(screen.getByTestId("brain-facts").textContent).toContain("Fact history not read — could not be read (OSError)"));
    expect(screen.getByTestId("brain-facts").textContent).not.toContain("No fact has changed");
  });
});
