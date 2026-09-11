/**
 * ON-3b — the entity-type map's layout. The map is a claim about distance: a card on ring N is N links from the
 * centre by the shortest route, a type beyond an unopened neighbour is not drawn, no two cards on a ring overlap
 * however many neighbours the centre has, and a link's label sits where no card hides it.
 */
import { describe, expect, it } from "vitest";

import { FOCUS_HALF, NEIGHBOUR_HALF, hasHiddenNeighbours, layoutMap, visibleRings } from "@/lib/entityMapLayout";
import type { TypeMap, TypeMapLink } from "@/lib/objectTypes";

const link = (from: string, to: string): TypeMapLink => ({
  relationship: `${from}_${to}`, from, to, name: `${from}_to_${to}`, reverse_name: `${to}_to_${from}`,
  business_name: "", verb: "has", cardinality: "1:N", measured: true, traversable: true,
});

const typeMap = (...links: TypeMapLink[]): TypeMap => {
  const types = Array.from(new Set(links.flatMap((l) => [l.from, l.to]))).sort();
  return {
    connection_id: "c1", schema_name: "s", generated_at: "", links,
    object_types: types.map((t) => ({
      object_type: t, id: t, display_name: t, role: "business_object", domain: "", key: `${t}_id`,
      key_verified: true, rows: 1, table: t, display_property: `${t}_id`, display_is_key: true, properties: 1,
      bindings: 1, links: 0, traversable_links: 0, actions: 0, metrics: 0,
    })),
  };
};

// customer — order — order_item — product, and order_item — shipment
const commerce = typeMap(link("customer", "order"), link("order", "order_item"), link("order_item", "product"),
  link("order_item", "shipment"));

const star = (n: number) => typeMap(...Array.from({ length: n }, (_, i) => link("hub", `t${String(i).padStart(2, "0")}`)));

/** Two boxes overlap unless they are a full width apart sideways or a full height apart upright. */
const overlap = (a: { x: number; y: number }, b: { x: number; y: number }, half: { w: number; h: number }) =>
  Math.abs(a.x - b.x) < 2 * half.w && Math.abs(a.y - b.y) < 2 * half.h;

describe("visibleRings", () => {
  it("puts the focus at the centre and its neighbours on the first ring, and nothing further", () => {
    expect(Object.fromEntries(visibleRings(commerce, "order", new Set()))).toEqual({ order: 0, customer: 1, order_item: 1 });
  });

  it("opens an expanded neighbour's links onto the next ring", () => {
    const rings = visibleRings(commerce, "order", new Set(["order_item"]));
    expect(Object.fromEntries(rings)).toEqual({ order: 0, customer: 1, order_item: 1, product: 2, shipment: 2 });
  });

  it("ignores an expanded type the map is not showing", () => {
    expect(visibleRings(commerce, "customer", new Set(["order_item"])).has("product")).toBe(false);
  });

  it("places a type on the ring of its SHORTEST distance", () => {
    const triangle = typeMap(link("a", "b"), link("b", "c"), link("a", "c"));
    expect(Object.fromEntries(visibleRings(triangle, "a", new Set(["b"])))).toEqual({ a: 0, b: 1, c: 1 });
  });
});

describe("layoutMap", () => {
  it("draws only the links whose two types are both on the map, neighbour-to-neighbour included", () => {
    const triangle = typeMap(link("a", "b"), link("b", "c"), link("a", "c"), link("c", "d"));
    const layout = layoutMap(triangle, "a", new Set());
    expect(layout.edges.map((e) => e.link.relationship).sort()).toEqual(["a_b", "a_c", "b_c"]);
  });

  it.each([2, 7, 12, 40])("centres the focus and never overlaps two of %i neighbour cards", (n) => {
    const layout = layoutMap(star(n), "hub", new Set());
    const hub = layout.nodes.find((node) => node.objectType === "hub")!;
    expect([hub.x, hub.y]).toEqual([layout.width / 2, layout.height / 2]);
    const ring = layout.nodes.filter((node) => node.ring === 1);
    expect(ring).toHaveLength(n);
    for (let i = 0; i < ring.length; i += 1) {
      expect(overlap(ring[i], hub, { w: (FOCUS_HALF.w + NEIGHBOUR_HALF.w) / 2, h: (FOCUS_HALF.h + NEIGHBOUR_HALF.h) / 2 }))
        .toBe(false);
      for (let j = i + 1; j < ring.length; j += 1) expect(overlap(ring[i], ring[j], NEIGHBOUR_HALF)).toBe(false);
    }
  });

  it("puts the second ring outside the first", () => {
    const layout = layoutMap(commerce, "order", new Set(["order_item"]));
    const distance = (t: string) => {
      const node = layout.nodes.find((n) => n.objectType === t)!;
      return Math.hypot(node.x - layout.width / 2, node.y - layout.height / 2);
    };
    const inner = Math.max(distance("customer"), distance("order_item"));
    expect(Math.min(distance("product"), distance("shipment"))).toBeGreaterThan(inner);
  });

  it("sets every label where neither card on its line hides it", () => {
    const layout = layoutMap(star(7), "hub", new Set());
    const hub = layout.nodes.find((n) => n.objectType === "hub")!;
    for (const edge of layout.edges) {
      const other = layout.nodes.find((n) => n.objectType === edge.link.to)!;
      const label = { x: edge.labelX, y: edge.labelY };
      expect(Math.abs(label.x - hub.x) >= FOCUS_HALF.w || Math.abs(label.y - hub.y) >= FOCUS_HALF.h).toBe(true);
      expect(Math.abs(label.x - other.x) >= NEIGHBOUR_HALF.w || Math.abs(label.y - other.y) >= NEIGHBOUR_HALF.h).toBe(true);
    }
  });

  it("says which cards still hide links", () => {
    const rings = visibleRings(commerce, "order", new Set());
    expect(hasHiddenNeighbours(commerce, "order_item", rings)).toBe(true);
    expect(hasHiddenNeighbours(commerce, "customer", rings)).toBe(false);
  });
});
