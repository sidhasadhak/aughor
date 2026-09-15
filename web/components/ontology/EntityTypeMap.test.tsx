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
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { OntologyDraft, TypeMap } from "@/lib/objectTypes";

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

/** The per-user preference store the arrangement lives in — the map reads it on mount and writes it on a drop;
 *  `localStorage` is only this device's paint-before-fetch cache. */
const stored: { value: unknown } = { value: undefined };
const putPreference = vi.fn(async (_key: string, value: unknown) => { stored.value = value; });

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getMyPreferences: vi.fn(async () => ({ user: "local", preferences: { ontology_map_layout: stored.value } })),
  putMyPreference: (key: string, value: unknown) => putPreference(key, value),
  getConnections: vi.fn(async () => [{ id: "shop1", name: "Shop" }, { id: "crm1", name: "CRM" }]),
}));

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

const served: { map: TypeMap } = { map };
/** The door answers with the type, and the map's re-read then carries it — as the server does. */
const declareEntity = vi.fn(async (..._args: unknown[]) => {
  const made = { ...map.object_types[0], object_type: "purchase_order", id: "PurchaseOrder", display_name: "Purchase order" };
  served.map = { ...served.map, object_types: [...served.map.object_types, made] };
  return { object_type: "purchase_order" };
});

/** ON-7b — the explorer's draft: what the rail reads, and the two doors it calls. */
const emptyDraft: OntologyDraft = {
  connection_id: "c1", schema_name: "s", runs: [], proposals: [], grouping: {},
  counts: { proposed: 0, confirmed: 0, released: 0, withdrawn: 0, refused: 0 },
};
const drafted: OntologyDraft = {
  ...emptyDraft,
  runs: [{ id: "r1", at: "2026-09-13T00:00:00Z", backend: "gemini", model: "m", fallback: false, version: 1,
           provenance: "model:m@1", catalogue_chars: 100, said: { entities: 0, parts: 2, links: 1 },
           written: 2, refused: 1, already: 0, withdrawn: 0 }],
  proposals: [
    { key: "part:order:order_item", kind: "part", tier: "proposed", sentence: "order_item is a part of order, read as lines (detail)",
      note: "many rows per order", reason: "an order has lines", provenance: "model:m@1",
      target: { entity: "order", binding: "lines", table: "order_item", part: "order_item" }, object_type: "order" },
    { key: "link:country.country=order.country", kind: "link", tier: "proposed", sentence: "order ships_to country on country = country",
      note: "measured N:1", reason: "orders ship to a country", provenance: "model:m@1",
      target: { relationship: "order_ships_to_country" }, object_type: "order" },
    { key: "link:country.country=product.product_id", kind: "link", tier: "refused",
      sentence: "product made_in country on product_id = country", note: "the keys never meet", reason: "a guess",
      provenance: "model:m@1", target: {}, object_type: "" },
  ],
  counts: { proposed: 2, confirmed: 0, released: 0, withdrawn: 0, refused: 1 },
};
const draftState: { value: OntologyDraft } = { value: emptyDraft };
const getOntologyDraft = vi.fn(async (..._args: unknown[]) => draftState.value);
const exploreOntology = vi.fn(async (..._args: unknown[]) => { draftState.value = drafted; return drafted; });
const confirmProposals = vi.fn(async (..._args: unknown[]) => ({ ...draftState.value, confirmed: [], refused: [] }));

vi.mock("@/lib/objectTypes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/objectTypes")>()),
  getTypeMap: vi.fn(async () => served.map),
  declareEntity: (...a: unknown[]) => declareEntity(...a),
  getOntologyDraft: (...a: unknown[]) => getOntologyDraft(...a),
  exploreOntology: (...a: unknown[]) => exploreOntology(...a),
  confirmProposals: (...a: unknown[]) => confirmProposals(...a),
}));

import { EntityTypeMap } from "@/components/ontology/EntityTypeMap";

const CACHE_KEY = "ont-map-layout";
const SCOPE = "c1:s";

describe("EntityTypeMap", () => {
  beforeEach(() => {
    window.localStorage.clear();
    stored.value = undefined;
    putPreference.mockClear();
    declareEntity.mockClear();
    served.map = map;
    handoff.nodes = [];
    handoff.edges = [];
  });

  it("hands the canvas every type — the unlinked one too — and every link", async () => {
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.edges.length).toBe(2));
    expect(handoff.nodes.map((n) => n.id).sort()).toEqual(["country", "order", "order_item", "product"]);
    expect(handoff.edges.map((e) => e.id).sort()).toEqual(["oi_order", "oi_product"]);
    // drawn by the map's own edge, which lifts a sideways link's label clear of the cards it would lie under
    expect(handoff.edges.every((e) => e.type === "link")).toBe(true);
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

  it("lists each declared rule with what it admits and the metrics it scopes", async () => {
    served.map = { ...map, processes: [], rules: [
      { id: "fulfilled_orders", display_name: "Fulfilled orders", entity: "order", kind: "condition", origin: "human",
        verified: true, admitted: 3900, objects: 5000, flags: 0, scopes: ["revenue", "aov"] },
      { id: "dach", display_name: "DACH", entity: "country", kind: "value_set", origin: "human",
        verified: true, admitted: 2, objects: 3, flags: 1 },
    ] };
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    const [scoping, grouping] = await screen.findAllByTestId("entity-rail-rule");
    expect(scoping.textContent).toContain("scopes revenue, aov");
    expect(grouping.textContent).toContain("1 flagged");
    expect(grouping.textContent).not.toContain("scopes");
  });

  it("keeps where a person drags a card in the preference store, and opens there next time", async () => {
    const { unmount } = render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.nodes.length).toBe(4));
    const before = handoff.nodes.find((n) => n.id === "order")!.position;
    handoff.onNodeDragStop!({}, { id: "order", position: { x: 42, y: 7 } });

    const arranged = { [SCOPE]: { order: { x: 42, y: 7 } } };
    await waitFor(() => expect(putPreference).toHaveBeenCalledWith("ontology_map_layout", arranged));
    expect(JSON.parse(window.localStorage.getItem(CACHE_KEY)!)).toEqual(arranged);   // and the paint cache
    expect(before).not.toEqual({ x: 42, y: 7 });

    unmount();
    handoff.nodes = [];
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.nodes.length).toBe(4));
    expect(handoff.nodes.find((n) => n.id === "order")!.position).toEqual({ x: 42, y: 7 });
    // …and only that one: the rest still start where the layout put them
    expect(handoff.nodes.find((n) => n.id === "product")!.position).not.toEqual({ x: 42, y: 7 });
  });

  it("opens on the store's arrangement even when this browser has never seen it", async () => {
    stored.value = { [SCOPE]: { product: { x: -8, y: 300 } } };      // arranged on another machine
    expect(window.localStorage.getItem(CACHE_KEY)).toBeNull();
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() =>
      expect(handoff.nodes.find((n) => n.id === "product")!.position).toEqual({ x: -8, y: 300 }));
    expect(JSON.parse(window.localStorage.getItem(CACHE_KEY)!)).toEqual(stored.value);   // cached for next time
  });

  it("leaves another map's arrangement alone when it writes this one's", async () => {
    stored.value = { "other:map": { order: { x: 5, y: 5 } } };
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.nodes.length).toBe(4));
    handoff.onNodeDragStop!({}, { id: "order", position: { x: 42, y: 7 } });
    await waitFor(() => expect(putPreference).toHaveBeenCalledWith("ontology_map_layout", {
      "other:map": { order: { x: 5, y: 5 } },
      [SCOPE]: { order: { x: 42, y: 7 } },
    }));
  });

  it("offers to put the arrangement back only once something has been moved", async () => {
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.nodes.length).toBe(4));
    expect(screen.queryByText(/Reset arrangement/)).toBeNull();

    handoff.onNodeDragStop!({}, { id: "order", position: { x: 42, y: 7 } });
    const reset = await screen.findByText(/Reset arrangement/);
    await userEvent.click(reset);
    await waitFor(() => expect(putPreference).toHaveBeenLastCalledWith("ontology_map_layout", { [SCOPE]: {} }));
    expect(handoff.nodes.find((n) => n.id === "order")!.position).not.toEqual({ x: 42, y: 7 });
  });
});

describe("EntityTypeMap — ON-7: parts fold into their parent, and a person declares an entity", () => {
  beforeEach(() => {
    window.localStorage.clear();
    stored.value = undefined;
    declareEntity.mockClear();
    served.map = map;
    handoff.nodes = [];
    handoff.edges = [];
  });

  it("draws no card for a part, and draws its links from the parent's card, named through the part", async () => {
    served.map = {
      ...map,
      object_types: map.object_types.map((t) =>
        t.object_type === "order_item" ? { ...t, absorbed_into: "order" }
          : t.object_type === "order" ? { ...t, parts: [{ object_type: "order_item", display_name: "order_item", binding: "lines", kind: "detail" }] }
            : t),
      links: map.links.map((l) => ({ ...l, shown_from: "order", shown_to: l.to })),
    };
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.nodes.length).toBe(3));
    expect(handoff.nodes.map((n) => n.id).sort()).toEqual(["country", "order", "product"]);
    // the part's link to its own parent is the binding it is read through — not an edge; its link to Product is
    // drawn from Order's card and says it came through the part
    // edges are drawn from the cards' live positions, one effect after the cards land — wait for them, never race them
    await waitFor(() => expect(handoff.edges.map((e) => e.id)).toEqual(["oi_product"]));
    expect(handoff.edges[0].source).toBe("order");
    await waitFor(() => expect(handoff.edges[0].label).toBe("contains · 1:N · via order_item"));
    // the rail lists the part under the cards, and the card says it has one
    expect(screen.getAllByTestId("entity-rail-part").map((b) => b.textContent)).toEqual(["order_itempart of order"]);
    expect(screen.getByTestId("rf-node-order")).toHaveTextContent("1 part");
  });

  it("declares an entity from the rail and opens it", async () => {
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.nodes.length).toBe(4));
    await userEvent.click(screen.getByTestId("entity-declare-open"));
    await userEvent.type(screen.getByLabelText("Entity id"), "PurchaseOrder");
    await userEvent.type(screen.getByLabelText("Entity display name"), "Purchase order");
    await userEvent.type(screen.getByLabelText("Entity table"), "purchase_orders");
    expect(screen.getByRole("button", { name: "Declare" })).toBeDisabled();       // no key yet
    await userEvent.type(screen.getByLabelText("Entity key column"), "po_id");
    await userEvent.click(screen.getByRole("button", { name: "Declare" }));
    await waitFor(() => expect(declareEntity).toHaveBeenCalledWith("c1", {
      id: "PurchaseOrder", display_name: "Purchase order", backing: { primary_key: "po_id", table: "purchase_orders" },
    }, "s"));
    await waitFor(() => expect(screen.getByTestId("panel")).toHaveTextContent("purchase_order"));
  });
});

describe("EntityTypeMap — ON-7b: the explorer's draft", () => {
  beforeEach(() => {
    window.localStorage.clear();
    stored.value = undefined;
    served.map = map;
    draftState.value = emptyDraft;
    exploreOntology.mockClear();
    confirmProposals.mockClear();
    handoff.nodes = [];
    handoff.edges = [];
  });

  it("offers a first draft and says what it costs, then shows what was proposed and what the data refused", async () => {
    const user = userEvent.setup();
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    const run = await screen.findByTestId("explorer-draft-run");
    expect(run).toHaveTextContent("Draft the business");
    expect(screen.getByTestId("explorer-draft")).toHaveTextContent("One model call");
    await user.click(run);
    await waitFor(() => expect(exploreOntology).toHaveBeenCalledWith("c1", "s"));
    await waitFor(() =>
      expect(screen.getByTestId("explorer-draft-counts")).toHaveTextContent("2 proposed · 0 confirmed · 1 refused"));
    expect(screen.getByTestId("explorer-draft-run")).toHaveTextContent("Draft again");
    await user.click(screen.getByRole("button", { name: "Review" }));
    const rows = screen.getAllByTestId("explorer-proposal");
    expect(rows).toHaveLength(3);
    // a refusal says what the data said, never the model's own reason for proposing it
    expect(rows[2]).toHaveTextContent("refused");
    expect(rows[2]).toHaveTextContent("the keys never meet");
    expect(rows[2]).not.toHaveTextContent("a guess");
    expect(within(rows[2]).queryByRole("button", { name: "Confirm" })).toBeNull();
  });

  it("confirms every proposal in one click, and one at a time by the declaration it was written as", async () => {
    const user = userEvent.setup();
    draftState.value = drafted;
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await user.click(await screen.findByTestId("explorer-draft-confirm-all"));
    await waitFor(() => expect(confirmProposals).toHaveBeenCalledWith("c1", { all: true }, "s"));
    await user.click(screen.getByRole("button", { name: "Review" }));
    const [part, link] = screen.getAllByTestId("explorer-proposal");
    await user.click(within(part).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(confirmProposals).toHaveBeenLastCalledWith(
      "c1", { targets: [{ kind: "binding", entity: "order", binding: "lines" }] }, "s"));
    await user.click(within(link).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(confirmProposals).toHaveBeenLastCalledWith(
      "c1", { targets: [{ kind: "link", relationship: "order_ships_to_country" }] }, "s"));
  });

  it("confirms a proposed process and a proposed rule by the declaration each was written as", async () => {
    const user = userEvent.setup();
    draftState.value = {
      ...emptyDraft,
      runs: drafted.runs,
      proposals: [
        { key: "process:Order:order_date>shipped_at", kind: "process", tier: "proposed",
          sentence: "Order goes through placed → shipped", note: "5,000 Order objects; 2 of 2 stages reached",
          reason: "orders ship", provenance: "model:m@2", target: { process: "order_fulfilment", entity: "Order" },
          object_type: "order" },
        { key: "rule:Order:status not_in", kind: "rule", tier: "proposed",
          sentence: "fulfilled_orders on Order: status not_in cancelled, refunded", note: "admits 3,900 of 5,000",
          reason: "what finance counts", provenance: "model:m@2", target: { rule: "fulfilled_orders", entity: "Order" },
          object_type: "order" },
      ],
      counts: { proposed: 2, confirmed: 0, released: 0, withdrawn: 0, refused: 0 },
    };
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await user.click(await screen.findByRole("button", { name: "Review" }));
    const [process, rule] = screen.getAllByTestId("explorer-proposal");
    await user.click(within(process).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(confirmProposals).toHaveBeenLastCalledWith(
      "c1", { targets: [{ kind: "process", process: "order_fulfilment" }] }, "s"));
    await user.click(within(rule).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(confirmProposals).toHaveBeenLastCalledWith(
      "c1", { targets: [{ kind: "rule", rule: "fulfilled_orders" }] }, "s"));
  });

  it("marks what an explorer proposed on its card and on its link", async () => {
    served.map = {
      ...map,
      object_types: map.object_types.map((t) => (t.object_type === "order"
        ? { ...t, origin: "model" as const, unconfirmed: 1, provenance: "model:m@1" } : t)),
      links: map.links.map((l) => (l.relationship === "oi_order" ? { ...l, origin: "model" as const } : l)),
    };
    render(<EntityTypeMap connectionId="c1" schema="s" />);
    await waitFor(() => expect(handoff.edges.length).toBe(2));
    expect(within(screen.getByTestId("rf-node-order")).getByTestId("entity-map-card-proposed")).toHaveTextContent("proposed");
    expect(screen.getByTestId("rf-node-product")).not.toHaveTextContent("proposed");
    expect(handoff.edges.find((e) => e.id === "oi_order")!.style.stroke).toBe("var(--vio4)");
    expect(handoff.edges.find((e) => e.id === "oi_product")!.style.stroke).toBe("var(--amb4)");   // refused stays refused
    await waitFor(() =>
      expect(handoff.edges.find((e) => e.id === "oi_order")!.label).toBe("belongs to · N:1 · proposed"));
  });
});

/** ON-8 — the organisation's ontology: one map over the connections its types are declared on. */
describe("EntityTypeMap — an organisation's ontology", () => {
  const domainMap: TypeMap = {
    connection_id: "org=default", schema_name: "default", generated_at: "", domain: "default/default",
    links: [
      { relationship: "Order_placed_by_Customer", from: "order", to: "customer", name: "placed_by",
        reverse_name: "customer_to_order", business_name: "placed_by", verb: "placed by", cardinality: "N:1",
        measured: true, traversable: true, traversal: "cross-source" },
    ],
    object_types: [["order", "shop1"], ["customer", "crm1"]].map(([t, conn]) => ({
      object_type: t, id: t, display_name: t, role: "business_object", domain: "", key: `${t}_id`,
      key_verified: true, rows: 3, table: `ecommerce.${t}s`, display_property: `${t}_id`, display_is_key: true,
      properties: 1, bindings: 1, proposed_bindings: 0, links: 1, traversable_links: 1, actions: 0, metrics: 0,
      connection_id: conn,
    })),
  };

  beforeEach(() => {
    window.localStorage.clear();
    served.map = domainMap;
    handoff.nodes = [];
    handoff.edges = [];
    getOntologyDraft.mockClear();
    declareEntity.mockClear();
  });

  it("names each type's connection, draws a cross-source link dotted and says so, and reads no explorer draft", async () => {
    render(<EntityTypeMap connectionId="domain:default" />);
    await waitFor(() => expect(handoff.nodes.find((n) => n.id === "customer")?.data.source).toBe("CRM"));
    expect(screen.getByTestId("rf-node-order")).toHaveTextContent("on Shop");
    expect(screen.getAllByTestId("entity-rail-connection").map((n) => n.textContent).sort()).toEqual(["on CRM", "on Shop"]);
    await waitFor(() => expect(handoff.edges).toHaveLength(1));
    const [edge] = handoff.edges;
    expect(edge.style.strokeDasharray).toBe("1 4");
    await waitFor(() => expect(handoff.edges[0].label).toBe("placed by · N:1 · cross-source"));
    expect(screen.queryByTestId("explorer-draft")).toBeNull();
    expect(getOntologyDraft).not.toHaveBeenCalled();
  });

  it("declares a type on the connection a person picks, with the schema that qualifies its table", async () => {
    const user = userEvent.setup();
    render(<EntityTypeMap connectionId="domain:default" />);
    await waitFor(() => expect(handoff.nodes).toHaveLength(2));
    await user.click(screen.getByTestId("entity-declare-open"));
    const form = screen.getByTestId("entity-declare");
    await waitFor(() => expect(within(form).getByRole("option", { name: "CRM" })).toBeInTheDocument());
    await user.selectOptions(within(form).getByTestId("entity-declare-connection"), "crm1");
    await user.type(within(form).getByLabelText("Entity id"), "Ticket");
    await user.type(within(form).getByLabelText("Entity display name"), "Ticket");
    await user.type(within(form).getByLabelText("Entity table"), "tickets");
    await user.type(within(form).getByLabelText("Entity schema"), "support");
    await user.type(within(form).getByLabelText("Entity key column"), "ticket_id");
    await user.click(within(form).getByRole("button", { name: "Declare" }));
    await waitFor(() => expect(declareEntity).toHaveBeenCalledTimes(1));
    expect(declareEntity.mock.calls[0][0]).toBe("domain:default");
    expect(declareEntity.mock.calls[0][1]).toMatchObject({
      id: "Ticket", backing: { table: "tickets", schema_name: "support", primary_key: "ticket_id", connection_id: "crm1" } });
  });

  it("opens an empty organisation's ontology on the door that declares its first type", async () => {
    served.map = { ...domainMap, object_types: [], links: [] };
    render(<EntityTypeMap connectionId="domain:default" />);
    await waitFor(() => expect(screen.getByTestId("entity-declare-open")).toBeInTheDocument());
    expect(screen.getByText(/Nothing is declared in the organisation's ontology yet/)).toBeInTheDocument();
  });
});
