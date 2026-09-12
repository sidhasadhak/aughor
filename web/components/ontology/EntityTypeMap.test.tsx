// @vitest-environment jsdom

/**
 * ON-3b — the entity-type map's canvas is `@xyflow/react`, and jsdom reports every element as 0×0, so React Flow
 * emits the edge container and ZERO edges however many you pass it: a test asserting on drawn edges cannot fail.
 * So this stubs the canvas and asserts on what the component HANDS it — which is where these bugs live.
 *
 * What is pinned here: every type reaches the canvas as a card and every link as an edge; a link leaves by the
 * side the type it reaches actually lies on (an edge naming a handle its node never rendered is dropped in
 * silence, and that looks exactly like an ontology with no links); only the picked type's links are named; and a
 * card a person drags is remembered, so the next visit opens on their arrangement and not the layout's.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { TypeMap } from "@/lib/objectTypes";

const handoff: { nodes: any[]; edges: any[]; onNodeDragStop?: (e: unknown, n: unknown) => void } =
  { nodes: [], edges: [] };

vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  return {
    ...actual,
    ReactFlow: ({ nodes, edges, nodeTypes, onNodeDragStop, onNodeClick, children }: any) => {
      handoff.nodes = nodes;
      handoff.edges = edges;
      handoff.onNodeDragStop = onNodeDragStop;
      const Card = nodeTypes.entity;
      return (
        <actual.ReactFlowProvider>
          <div data-testid="rf">
            {nodes.map((n: any) => (
              <button key={n.id} data-testid={`rf-node-${n.id}`} onClick={(e) => onNodeClick?.(e, n)}>
                <Card data={n.data} />
              </button>
            ))}
            {children}
          </div>
        </actual.ReactFlowProvider>
      );
    },
    Controls: () => null,
  };
});
vi.mock("@xyflow/react/dist/style.css", () => ({}));

vi.mock("@/components/ontology/EntityTypePanel", () => ({
  EntityTypePanel: ({ objectType }: { objectType: string }) => <div data-testid="panel">{objectType}</div>,
}));

const map: TypeMap = {
  connection_id: "c1", schema_name: "s", generated_at: "",
  links: [
    { relationship: "oi_order", from: "order_item", to: "order", name: "order_item_to_order",
      reverse_name: "order_to_order_item", business_name: "", verb: "belongs to", cardinality: "N:1",
      measured: true, traversable: true },
    { relationship: "oi_product", from: "order_item", to: "product", name: "order_item_to_product",
      reverse_name: "product_to_order_item", business_name: "", verb: "contains", cardinality: "1:N",
      measured: true, traversable: false, why_not: "N:N by measurement" },
  ],
  object_types: ["order_item", "order", "product", "country"].map((t) => ({
    object_type: t, id: t, display_name: t, role: "business_object", domain: "", key: `${t}_id`,
    key_verified: true, rows: 3, table: t, display_property: `${t}_id`, display_is_key: true, properties: 1,
    bindings: 1, proposed_bindings: 0, links: 0, traversable_links: 0, actions: 0, metrics: 0,
  })),
};

vi.mock("@/lib/objectTypes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/objectTypes")>()),
  getTypeMap: vi.fn(async () => map),
}));

import { EntityTypeMap } from "@/components/ontology/EntityTypeMap";

const LAYOUT_KEY = "ont-map-layout:c1:s";

describe("EntityTypeMap", () => {
  beforeEach(() => {
    window.localStorage.clear();
    handoff.nodes = [];
    handoff.edges = [];
  });

  it("hands the canvas every type — the unlinked one too — and every link", async () => {
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.edges.length).toBe(2));
    expect(handoff.nodes.map((n) => n.id).sort()).toEqual(["country", "order", "order_item", "product"]);
    expect(handoff.edges.map((e) => e.id).sort()).toEqual(["oi_order", "oi_product"]);
    expect(handoff.nodes.every((n) => n.draggable && n.type === "entity")).toBe(true);
  });

  it("sends each link out of the side the type it reaches actually lies on", async () => {
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.edges.length).toBe(2));
    const at = new Map(handoff.nodes.map((n) => [n.id, n.position]));
    for (const edge of handoff.edges) {
      const [a, b] = [at.get(edge.source)!, at.get(edge.target)!];
      const [dx, dy] = [b.x - a.x, b.y - a.y];
      const expected = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "r" : "l") : (dy > 0 ? "b" : "t");
      expect(edge.sourceHandle).toBe(expected);
      expect(edge.targetHandle).toBe(`${expected === "r" ? "l" : expected === "l" ? "r" : expected === "b" ? "t" : "b"}-in`);
    }
  });

  it("names only the picked type's links, and says which the compiler refuses", async () => {
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    // the busiest type is picked to begin with, so both of its links are named
    await waitFor(() => expect(screen.getByTestId("panel")).toHaveTextContent("order_item"));
    await waitFor(() =>
      expect(handoff.edges.map((e) => e.label).sort()).toEqual(["belongs to · N:1", "contains · 1:N"]));
    const refused = handoff.edges.find((e) => e.id === "oi_product")!;
    expect(refused.style.strokeDasharray).toBe("5 4");          // a link the compiler will not follow

    await userEvent.click(screen.getAllByTestId("entity-rail-row").find((b) => b.textContent?.startsWith("country"))!);
    await waitFor(() => expect(screen.getByTestId("panel")).toHaveTextContent("country"));
    await waitFor(() => expect(handoff.edges.every((e) => e.label === undefined)).toBe(true));
  });

  it("remembers where a person drags a card, and opens there next time", async () => {
    const { unmount } = render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.nodes.length).toBe(4));
    const before = handoff.nodes.find((n) => n.id === "order")!.position;
    handoff.onNodeDragStop!({}, { id: "order", position: { x: 42, y: 7 } });
    await waitFor(() =>
      expect(JSON.parse(window.localStorage.getItem(LAYOUT_KEY)!)).toEqual({ order: { x: 42, y: 7 } }));
    expect(before).not.toEqual({ x: 42, y: 7 });

    unmount();
    handoff.nodes = [];
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.nodes.length).toBe(4));
    expect(handoff.nodes.find((n) => n.id === "order")!.position).toEqual({ x: 42, y: 7 });
    // …and only that one: the rest still start where the layout put them
    expect(handoff.nodes.find((n) => n.id === "product")!.position).not.toEqual({ x: 42, y: 7 });
  });

  it("offers to put the arrangement back only once something has been moved", async () => {
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.nodes.length).toBe(4));
    expect(screen.queryByText(/Reset arrangement/)).toBeNull();

    handoff.onNodeDragStop!({}, { id: "order", position: { x: 42, y: 7 } });
    const reset = await screen.findByText(/Reset arrangement/);
    await userEvent.click(reset);
    await waitFor(() => expect(window.localStorage.getItem(LAYOUT_KEY)).toBe("{}"));
    expect(handoff.nodes.find((n) => n.id === "order")!.position).not.toEqual({ x: 42, y: 7 });
  });
});
