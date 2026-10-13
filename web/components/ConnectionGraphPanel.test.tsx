// @vitest-environment jsdom
/**
 * The Graph tab, rendered (redone to CLARITY 2026-10-13).
 *
 * jsdom reports every element as 0×0, so React Flow draws no edge whatever it is handed (web/AGENTS.md). The canvas is
 * therefore stubbed and the assertions sit on the HANDOFF — the links the panel computes and passes down — and on what
 * the reader sees around the picture: one line of what the graph holds, the side panel at rest and with a node chosen,
 * and the `?table=` deep link opening straight onto a table's page.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CGEdge, CGNode, ConnectionGraph, GraphAudit, GraphReview, GraphReviewItem, TrustSidecar } from "@/lib/api";

type RFLike = Record<string, unknown>;
const handoff: { nodes: RFLike[]; edges: RFLike[] } = { nodes: [], edges: [] };

vi.mock("@xyflow/react", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    // Record the handoff; give each node a button that selects it the way React Flow reports a click.
    ReactFlow: ({ nodes, edges, onNodesChange, children }: {
      nodes: RFLike[]; edges: RFLike[]; children?: React.ReactNode;
      onNodesChange: (changes: { type: "select"; id: string; selected: boolean }[]) => void;
    }) => {
      handoff.nodes = nodes;
      handoff.edges = edges;
      return (
        <div data-testid="rf">
          {nodes.map(n => (
            <span key={String(n.id)} role="button" tabIndex={0} data-testid={`node:${String(n.id)}`}
              onClick={() => onNodesChange([{ type: "select", id: String(n.id), selected: true }])}>
              {String((n.data as { label: string }).label)}
            </span>
          ))}
          {children}
        </div>
      );
    },
    Panel: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
    Background: () => null,
    Controls: () => null,
  };
});
vi.mock("@xyflow/react/dist/style.css", () => ({}));

const prov = { source: "ontology.entity", measured: null, note: "" };
const table = (id: string, label: string, extra: Record<string, unknown> = {}): CGNode => ({
  id, kind: "table", label, summary: "", tags: [], provenance: prov,
  data: { domain: "Commerce", columns: ["order_id", "status"], source_tables: ["orders"], ...extra },
  warrant: { warrant: "declared", detail: "from the warehouse schema", label: "Declared" },
});
const join = (from: string, to: string, measured: number | null): CGEdge => ({
  id: `${from}--joins_on-->${to}`, kind: "joins_on", from_id: from, to_id: to,
  provenance: { source: "join_guard", measured, note: "" }, label: "",
  warrant: measured === null
    ? { warrant: "declared", detail: "declared foreign key — not yet probed", label: "Declared" }
    : { warrant: "measured", detail: `${Math.round(measured * 100)}% of key values overlap`, label: "Measured" },
});
const GRAPH: ConnectionGraph = {
  org_id: "default", connection_id: "c1", schema_name: "s", structural_fingerprint: "", version: 3,
  nodes: {
    "table:Order": table("table:Order", "Customer Order"),
    "table:User": table("table:User", "Customer", { domain: "Customer", source_tables: ["users"], columns: ["id"] }),
    "table:Item": table("table:Item", "Order Line", { source_tables: ["order_items"], columns: ["id"] }),
    "metric:aov": { id: "metric:aov", kind: "metric", label: "average_order_value", summary: "", tags: [], provenance: prov,
      data: {}, warrant: { warrant: "declared", detail: "", label: "Declared" } },
    "glossary_term:orders.status": { id: "glossary_term:orders.status", kind: "glossary_term", label: "status",
      summary: "Current status of the order", tags: [], provenance: prov, data: { table: "orders", column: "status" } },
  },
  edges: Object.fromEntries([
    join("table:Order", "table:User", 1),
    join("table:Item", "table:Order", null),
    { id: "metric:aov--derived_from-->table:Item", kind: "derived_from", from_id: "metric:aov", to_id: "table:Item",
      provenance: prov, label: "" } as CGEdge,
  ].map(e => [e.id, e])),
  counts: { table: 3, metric: 1, finding: 0, glossary_term: 1, edges: 3 },
  domains: [{ label: "Commerce", tables: ["table:Order", "table:Item"], table_count: 2 },
    { label: "Customer", tables: ["table:User"], table_count: 1 }],
  domain_edges: [{ from: "Commerce", to: "Customer", count: 1 }],
  staleness: "fresh",
};
const AUDIT = {
  connection_id: "c1", schema_name: "s", graph_version: 3, order: ["measured", "human", "declared", "derived", "inferred"],
  labels: { measured: "Measured", human: "Human", declared: "Declared", derived: "Derived", inferred: "Inferred" },
  meanings: { measured: "m", human: "h", declared: "d", derived: "dv", inferred: "i" },
  nodes: { measured: 0, human: 0, declared: 4, derived: 0, inferred: 1 },
  edges: { measured: 1, human: 0, declared: 2, derived: 0, inferred: 0 },
  edges_by_kind: {}, totals: { nodes: 5, edges: 3, joins: 2 }, joins_measured_share: 0.5, edge_grounded_share: 0.33,
  staleness: "fresh",
  drift: { drifted: true, reason: "a rebuild would add 4 finding", missing: { finding: 4 } },
} as unknown as GraphAudit;
const reviewItem = (type: GraphReviewItem["type"], subject: string, check: GraphReviewItem["check"], why: string): GraphReviewItem => ({
  id: `${type}:${subject}`, type, question: `Check ${subject}?`, why, subject_id: subject, subject_label: subject,
  check, depends: 2, detail: {},
});
const REVIEW: GraphReview = {
  connection_id: "c1", schema_name: "s", graph_version: 3,
  items: [
    reviewItem("graph_behind", "", "rebuild", "a rebuild would add 4 finding"),
    reviewItem("unprobed_join", "table:Item--joins_on-->table:Order", "probe_join", "declared, not measured"),
    reviewItem("unprobed_join", "table:X--joins_on-->table:Y", "probe_join", "declared, not measured"),
    reviewItem("isolated_table", "table:User", "ask", "nothing joins it"),
  ],
  total: 4, total_found: 4, truncated: false, by_type: {},
};
const TRUST = { connection_id: "c1", nodes: {}, meanings: {}, by_standing: {}, scored_nodes: 0, verdicts_seen: 0,
  human_signal: false } as unknown as TrustSidecar;

const api = vi.hoisted(() => ({
  getConnectionGraph: vi.fn(),
  getGraphAudit: vi.fn(),
  getGraphReview: vi.fn(),
  getGraphTrust: vi.fn(),
  getConnectionTour: vi.fn(),
  getGraphLineage: vi.fn(),
  listGovernedTags: vi.fn(),
}));
vi.mock("@/lib/api", async importOriginal => ({ ...(await importOriginal<Record<string, unknown>>()), ...api }));

import { ConnectionGraphPanel } from "@/components/ConnectionGraphPanel";

/** The panel with the workspace's Ask seam wired, under the prop name the workspace has always passed. */
const renderWithAsk = (ask: (q: string) => void) => render(<ConnectionGraphPanel connectionId="c1" onInvestigate={ask} />);

beforeEach(() => {
  api.getConnectionGraph.mockReset().mockResolvedValue(GRAPH);
  api.getGraphAudit.mockReset().mockResolvedValue(AUDIT);
  api.getGraphReview.mockReset().mockResolvedValue(REVIEW);
  api.getGraphTrust.mockReset().mockResolvedValue(TRUST);
  api.getConnectionTour.mockReset();
  api.getGraphLineage.mockReset().mockResolvedValue({ connection_id: "c1", node_id: "table:Order", label: "", root: "",
    truncated: false, counts_by_kind: {}, summary: "", dependents: [] });
  api.listGovernedTags.mockReset().mockResolvedValue([]);
  window.history.replaceState(null, "", "/");
});

describe("the Graph tab", () => {
  it("hands the renderer square links — step edges, coloured through tokens — never curves", async () => {
    render(<ConnectionGraphPanel connectionId="c1" />);
    await screen.findByTestId("rf");
    await waitFor(() => expect(handoff.edges.length).toBe(3));
    for (const e of handoff.edges) {
      expect(e.type).toBe("step");
      expect(String((e.style as { stroke: string }).stroke)).toMatch(/^var\(--/);
    }
    // A measured join carries its overlap; an unprobed one says it is weaker rather than nothing.
    const label = (id: string) => handoff.edges.find(e => e.id === id)?.label;
    expect(label("table:Order--joins_on-->table:User")).toBe("100%");
    expect(label("table:Item--joins_on-->table:Order")).toBe("declared");
    // The metric's key reaches the map as words.
    expect(handoff.nodes.map(n => (n.data as { label: string }).label)).toContain("Average order value");
  });

  it("opens on the picture with one line of what the graph holds above it — no figure cards", async () => {
    render(<ConnectionGraphPanel connectionId="c1" />);
    const holds = await screen.findByTestId("graph-holds");
    expect(holds).toHaveTextContent("3 tables");
    expect(holds).toHaveTextContent("2 joins");
    expect(holds).toHaveTextContent("1 metric");
    expect(screen.getByText("1 of 2 measured")).toBeInTheDocument();
    // The content axis wins over a schema-only "Fresh".
    expect(screen.getByTestId("graph-freshness")).toHaveTextContent("Rebuild owed");
    expect(document.querySelector("[data-slot=figure-value]")).toBeNull();
  });

  it("beside the map: what needs a person, folded by kind, with its check on the row — the rebuild said once", async () => {
    const ask = vi.fn();
    renderWithAsk(ask);
    const needs = await screen.findByTestId("graph-needs");
    await waitFor(() => expect(needs).toHaveAttribute("data-waiting", "true"));
    // Two unprobed joins are one row with a count, not two rows saying the same thing.
    expect(within(needs).getByText((_, el) => el?.textContent === "2 unprobed joins")).toBeInTheDocument();
    // The chip above the picture says "Rebuild owed"; the side panel does not say it again.
    expect(within(needs).queryByText(/Graph is behind/i)).toBeNull();
    // A single item keeps its check on its row.
    fireEvent.click(within(needs).getByRole("button", { name: "Ask about it" }));
    expect(ask).toHaveBeenCalledWith("Check table:User?");
    expect(screen.getByTestId("warrant-mix")).toBeInTheDocument();
  });

  it("a failed review read is said, never shown as nothing to check", async () => {
    api.getGraphReview.mockReset().mockRejectedValue(new Error("Graph review not available"));
    render(<ConnectionGraphPanel connectionId="c1" />);
    const needs = await screen.findByTestId("graph-needs");
    await waitFor(() => expect(within(needs).getByRole("alert")).toHaveTextContent("Could not read what needs checking"));
    expect(within(needs).queryByText(/Nothing to check/)).toBeNull();
  });

  it("choosing a node turns the side panel into its essentials, and its question goes to Ask", async () => {
    const ask = vi.fn();
    renderWithAsk(ask);
    fireEvent.click(await screen.findByTestId("node:table:Order"));
    const chosen = await screen.findByTestId("graph-chosen");
    expect(within(chosen).getByText("Customer Order")).toBeInTheDocument();
    expect(within(chosen).getByText(/orders · 2 columns/)).toBeInTheDocument();
    // Its joins, each with how it is known.
    expect(within(chosen).getByText("→ Customer")).toBeInTheDocument();
    expect(within(chosen).getAllByText(/Measured · 100% of key values overlap/).length).toBeGreaterThan(0);
    fireEvent.click(within(chosen).getByRole("button", { name: "Ask about this table" }));
    expect(ask).toHaveBeenCalledWith(expect.stringContaining("overview of the Customer Order table"));
    // Open goes to the table's page.
    fireEvent.click(within(chosen).getByRole("button", { name: "Open" }));
    expect(await screen.findByTestId("graph-table-page")).toBeInTheDocument();
    expect(window.location.search).toContain("table=table%3AOrder");
  });

  it("the ?table= deep link opens straight onto that table's page, a column beside its definition", async () => {
    render(<ConnectionGraphPanel connectionId="c1" initialTableId="table:Order" />);
    const page = await screen.findByTestId("graph-table-page");
    expect(within(page).getByText("Customer Order")).toBeInTheDocument();
    expect(within(page).getByText("status")).toBeInTheDocument();
    expect(within(page).getByText("Current status of the order")).toBeInTheDocument();
    // Nothing rests on it: said once, not as an empty section.
    expect(within(page).getByText("No findings.")).toBeInTheDocument();
    expect(window.location.search).toContain("table=table%3AOrder");
    // Back to the map drops the param.
    await act(async () => { fireEvent.click(screen.getByRole("radio", { name: "Map" })); });
    expect(window.location.search).not.toContain("table=");
  });

  it("an unknown deep-linked table degrades to the map, never an error", async () => {
    render(<ConnectionGraphPanel connectionId="c1" initialTableId="table:Nope" />);
    expect(await screen.findByTestId("rf")).toBeInTheDocument();
    expect(screen.queryByTestId("graph-table-page")).toBeNull();
  });
});
