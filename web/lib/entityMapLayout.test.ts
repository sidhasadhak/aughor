/**
 * ON-3b — the entity-type map's layout. The map is a claim about distance: a card on ring N is N links from the
 * centre by the shortest route, a type beyond an unopened neighbour is not drawn, and no two cards on a ring
 * overlap however many neighbours the centre has.
 */
import { describe, expect, it } from "vitest";

import { CARD_ARC, hasHiddenNeighbours, layoutMap, visibleRings } from "@/lib/entityMapLayout";
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

  it("centres the focus and keeps every ring's cards at least a card apart", () => {
    const star = typeMap(...Array.from({ length: 12 }, (_, i) => link("hub", `t${String(i).padStart(2, "0")}`)));
    const layout = layoutMap(star, "hub", new Set());
    const hub = layout.nodes.find((n) => n.objectType === "hub")!;
    expect([hub.x, hub.y]).toEqual([layout.width / 2, layout.height / 2]);
    const ring = layout.nodes.filter((n) => n.ring === 1);
    expect(ring).toHaveLength(12);
    for (let i = 0; i < ring.length; i += 1) {
      for (let j = i + 1; j < ring.length; j += 1) {
        const gap = Math.hypot(ring[i].x - ring[j].x, ring[i].y - ring[j].y);
        expect(gap).toBeGreaterThanOrEqual((CARD_ARC * 0.9) - 1);   // a chord, a little shorter than its arc
      }
    }
  });

  it("puts the second ring outside the first", () => {
    const layout = layoutMap(commerce, "order", new Set(["order_item"]));
    const distance = (t: string) => {
      const n = layout.nodes.find((node) => node.objectType === t)!;
      return Math.hypot(n.x - layout.width / 2, n.y - layout.height / 2);
    };
    expect(distance("product")).toBeGreaterThan(distance("order_item"));
    expect(distance("shipment")).toBeGreaterThan(distance("customer"));
  });

  it("says which cards still hide links", () => {
    const rings = visibleRings(commerce, "order", new Set());
    expect(hasHiddenNeighbours(commerce, "order_item", rings)).toBe(true);
    expect(hasHiddenNeighbours(commerce, "customer", rings)).toBe(false);
  });
});
