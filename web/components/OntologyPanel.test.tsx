// @vitest-environment jsdom

/**
 * The Ontology tab's bar, laid out as its approved mockup lays it out (design-mockups/ontology-tab.html, 2026-10-10):
 * the scope, the figures the map holds — "8 entities · 12 links · 1 process · 1 rule" — the release everyone reads, what
 * waits on a person in amber, and every tool in one menu. No title: the rail and the tab already name the screen.
 *
 * The map is stubbed: what is pinned here is that the bar says what the map TELLS it, not a count of its own.
 */
import React from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/testing";

vi.mock("@/components/ontology/EntityTypeMap", () => ({
  EntityTypeMap: ({ onSummary, reviewDraft }: {
    onSummary?: (s: { entities: number; links: number; processes: number; rules: number; proposed: number }) => void;
    reviewDraft?: number;
  }) => {
    React.useEffect(() => { onSummary?.({ entities: 8, links: 12, processes: 1, rules: 1, proposed: 6 }); }, [onSummary]);
    return <div data-testid="map-stub">review:{reviewDraft ?? 0}</div>;
  },
}));
vi.mock("@/components/OntologyOrgCanvas", () => ({ OntologyOrgCanvas: () => <div data-testid="org-stub" /> }));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getOntology: vi.fn(async () => ({ entities: { order: {} }, relationships: {}, enriched: true, generated_at: "" })),
  getVisibility: vi.fn(async () => ({
    line: "Reads 5 of your 5 tables · all 9 links checked",
    tables: { band: "green", basis: "profiler", mapped: 5, in_scope: 5, unmapped: [], note: "" },
    definitions: [],
  })),
  getOntologyProposals: vi.fn(async () => []),
  getConnectionSettings: vi.fn(async () => ({ ontology_refresh_hours: null })),
  getSystemFlags: vi.fn(async () => ({})),
}));
vi.mock("@/lib/objectTypes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/objectTypes")>()),
  getRelease: vi.fn(async () => ({
    enabled: true, connection_id: "c1", schema_name: "thelook", releases: [], draft: [],
    published: { number: 6, id: "c1/thelook@6", at: "2026-10-10T02:15:26+00:00", by: "ana", note: "", elements: 21 },
  })),
  getEntitiesByReads: vi.fn(async () => ({
    path: "by_reads", connection_id: "c1", schema_name: "thelook", days: 30, source: "the platform's log of statements run",
    entities: [
      { entity: "Review", object_type: "review", display_name: "Review", tables: ["reviews"], part_of: "", days: 30,
        reads: 0, last_read: null, readers: 0, unattributed: 0 },
      { entity: "Order", object_type: "order", display_name: "Order", tables: ["orders"], part_of: "", days: 30,
        reads: 41, last_read: "2026-10-23T09:00:00Z", readers: 3, unattributed: 12,
        shared_said: "a statement naming orders counts for Order line too." },
      { entity: "Note", object_type: "note", display_name: "Note", tables: [], part_of: "", reads: null,
        said: "No table is bound to it, so nothing is counted." },
    ],
  })),
}));

import { OntologyPanel } from "@/components/OntologyPanel";

describe("OntologyPanel — the bar", () => {
  it("says the figures the map holds, the release, and what waits on a person — and no title", async () => {
    render(<OntologyPanel connectionId="c1" schema="thelook" />);
    const facts = await screen.findByTestId("ontology-facts");
    expect(facts.textContent).toBe("8 entities12 links1 process1 rule");
    expect(await screen.findByTestId("release-chip")).toHaveTextContent("Release 6 · 10 Oct");
    expect(screen.getByTestId("ontology-schema-scope")).toHaveTextContent("thelook");
    expect(await screen.findByTestId("visibility-line")).toHaveTextContent("Reads 5 of your 5 tables");
    expect(screen.queryByText("Business Ontology")).toBeNull();
    const approve = screen.getByTestId("ontology-to-approve");
    expect(approve).toHaveTextContent("6 to approve");
    fireEvent.click(approve);                                         // opens the explorer's proposals in the map's rail
    expect(screen.getByTestId("map-stub")).toHaveTextContent("review:1");
  });

  it("opens every tool from one menu, one beside the map at a time", async () => {
    render(<OntologyPanel connectionId="c1" schema="thelook" />);
    const tools = await screen.findByTestId("ontology-tools");
    fireEvent.keyDown(tools, { key: "Enter" });
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((i) => i.textContent)).toEqual(["Find duplicates", "Human edits", "Proposals", "Learned skills", "Settings"]);
    fireEvent.click(screen.getByRole("menuitem", { name: "Proposals" }));
    expect(await screen.findByTestId("ontology-proposals-drawer")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByTestId("ontology-tools"), { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Settings" }));
    expect(await screen.findByText("Ontology Settings")).toBeInTheDocument();
    expect(screen.queryByTestId("ontology-proposals-drawer")).toBeNull();
  });

  it("drops the map's figures on the organisation board, which draws no map", async () => {
    render(<OntologyPanel connectionId="c1" schema="thelook" />);
    await screen.findByTestId("ontology-facts");
    fireEvent.click(screen.getByRole("radio", { name: "Org" }));
    expect(await screen.findByTestId("org-stub")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId("ontology-facts")).toBeNull());
  });

  it("lists the entities by their reads, the least read first, only while what uses an entity is shown", async () => {
    const api = await import("@/lib/api");
    vi.mocked(api.getSystemFlags).mockResolvedValue({ "ontology.entity_usage": { value: true } } as never);
    render(<OntologyPanel connectionId="c1" schema="thelook" />);
    const tools = await screen.findByTestId("ontology-tools");
    await waitFor(() => expect(api.getSystemFlags).toHaveBeenCalled());
    fireEvent.keyDown(tools, { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Reads by entity" }));
    const rows = await screen.findAllByTestId("ontology-reads-row");
    expect(rows.map((r) => r.querySelector("[data-testid=ontology-reads-count]")?.textContent))
      .toEqual(["0 reads", "41 reads", "not counted"]);
    expect(rows[0]).toHaveTextContent("not read in 30 days");
    expect(rows[1]).toHaveTextContent("last read Fri 23 Oct · 3 readers · 12 with no reader recorded");
    expect(rows[1]).toHaveTextContent("Shared table: a statement naming orders counts for Order line too.");
    expect(rows[2]).toHaveTextContent("No table is bound to it, so nothing is counted.");
    vi.mocked(api.getSystemFlags).mockResolvedValue({});
  });
});
