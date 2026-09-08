// @vitest-environment jsdom

/**
 * jsdom reports every element as 0×0, so React Flow emits the edge container and
 * zero `.react-flow__edge` elements no matter what you pass it — a test asserting
 * on drawn edges cannot fail. So this stubs the canvas and asserts on **what the
 * component hands it**: the nodes, and the edges with their per-column handle ids.
 *
 * That is where the bug would live. An edge naming a handle the node never
 * rendered is dropped in silence, which looks identical to a schema with no joins.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { RichSchema } from "@/lib/api";

const handoff: { nodes: unknown[]; edges: unknown[] } = { nodes: [], edges: [] };

vi.mock("@xyflow/react", async importOriginal => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  return {
    ...actual,
    // Record the handoff, then render the nodes through their real component so
    // the handles they declare are observable in the DOM. `Handle` stays real,
    // which means it needs the real provider around it.
    ReactFlow: ({ nodes, edges, nodeTypes }: any) => {
      handoff.nodes = nodes;
      handoff.edges = edges;
      const Node = nodeTypes.erTable;
      return (
        <actual.ReactFlowProvider>
          <div data-testid="rf">
            {nodes.map((n: any) => <Node key={n.id} data={n.data} />)}
          </div>
        </actual.ReactFlowProvider>
      );
    },
    Background: () => null,
    Controls: () => null,
  };
});

vi.mock("@xyflow/react/dist/style.css", () => ({}));

import { ERDiagram } from "@/components/ERDiagram";

const schema: RichSchema = {
  tables: [
    // Hidden-column counts are deliberately distinct per table (3 / 2 / 1) so a
    // "Show N more" button names exactly one card.
    { name: "users", row_count: "100", columns: [
      { name: "id", type: "BIGINT", is_fk: false },
      { name: "email", type: "VARCHAR", is_fk: false },
      { name: "country", type: "VARCHAR", is_fk: false },
      { name: "age", type: "BIGINT", is_fk: false },
    ] },
    { name: "orders", row_count: "500", columns: [
      { name: "order_id", type: "BIGINT", is_fk: false },
      { name: "user_id", type: "BIGINT", is_fk: true },
      { name: "status", type: "VARCHAR", is_fk: false },
    ] },
    { name: "audit_log", row_count: "9", columns: [
      { name: "id", type: "BIGINT", is_fk: false },
      { name: "note", type: "VARCHAR", is_fk: false },
    ] },
  ],
  joins: [
    { t1: "orders", c1: "user_id", t2: "users", c2: "id", match: "exact" },
  ],
  isolated: ["audit_log"],
  warnings: [],
};

describe("ERDiagram", () => {
  it("anchors each edge to the columns it joins on, not to the card", () => {
    render(<ERDiagram schema={schema} />);

    expect(handoff.edges).toHaveLength(1);
    expect(handoff.edges[0]).toMatchObject({
      source: "users",  sourceHandle: "id__s",
      target: "orders", targetHandle: "user_id__t",
    });
  });

  it("renders a handle pair for every column an edge names", () => {
    const { container } = render(<ERDiagram schema={schema} />);

    for (const edge of handoff.edges as any[]) {
      expect(container.querySelector(`[data-handleid="${edge.sourceHandle}"]`)).not.toBeNull();
      expect(container.querySelector(`[data-handleid="${edge.targetHandle}"]`)).not.toBeNull();
    }
  });

  it("keeps join columns visible while collapsed, so no edge is silently dropped", () => {
    render(<ERDiagram schema={schema} />);

    // `status` is neither a key nor a join endpoint, so it hides; `user_id` is a
    // join endpoint and must not.
    expect(screen.getByText("user_id")).toBeInTheDocument();
    expect(screen.queryByText("status")).not.toBeInTheDocument();
  });

  it("reveals the remaining columns on expand", async () => {
    const user = userEvent.setup();
    render(<ERDiagram schema={schema} />);

    expect(screen.queryByText("status")).not.toBeInTheDocument();
    // 2 hidden columns is `orders` alone — order_id and status.
    await user.click(screen.getByRole("button", { name: /Show 2 more columns/ }));
    expect(screen.getByText("status")).toBeInTheDocument();
    expect(screen.getByText("order_id")).toBeInTheDocument();
  });

  it("hands React Flow one node per table, including a table with no joins", () => {
    render(<ERDiagram schema={schema} />);

    expect((handoff.nodes as any[]).map(n => n.id).sort())
      .toEqual(["audit_log", "orders", "users"]);
  });

  it("keeps a dimension left of the fact that references it", () => {
    render(<ERDiagram schema={schema} />);

    const x = (id: string) =>
      (handoff.nodes as any[]).find(n => n.id === id).position.x;

    // The rank hints exist for exactly this. Left to itself dagre's network
    // simplex shortens edges, which drags a pure dimension rightward into the
    // middle of the diagram — measured on theLook, `users` landed a full column
    // in from the left. A dimension must stay upstream of what references it.
    expect(x("users")).toBeLessThan(x("orders"));
  });

  it("says so plainly when there are no tables", () => {
    render(<ERDiagram schema={{ tables: [], joins: [], isolated: [], warnings: [] }} />);
    expect(screen.getByText("No tables found.")).toBeInTheDocument();
  });
});
