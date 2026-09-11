/**
 * ON-3b — the entity-type map's layout. The map is a claim about the business: the busiest type is in the middle,
 * a card on ring N is N links from it by the shortest route, a type no link reaches is still drawn rather than
 * dropped, no two cards on a ring overlap however many neighbours the centre has, a link along a ring bows out
 * instead of crossing the cards inside it, and a link's label sits where no card hides it.
 */
import { describe, expect, it } from "vitest";

import {
  FOCUS_HALF, LABEL_ASIDE, NEIGHBOUR_HALF, hubOf, layoutMap, litBy, ringsOf, unlinkedTypes,
} from "@/lib/entityMapLayout";
import type { TypeMap, TypeMapLink, TypeMapRow } from "@/lib/objectTypes";

const link = (from: string, to: string): TypeMapLink => ({
  relationship: `${from}_${to}`, from, to, name: `${from}_to_${to}`, reverse_name: `${to}_to_${from}`,
  business_name: "", verb: "has", cardinality: "1:N", measured: true, traversable: true,
});

const row = (t: string): TypeMapRow => ({
  object_type: t, id: t, display_name: t, role: "business_object", domain: "", key: `${t}_id`,
  key_verified: true, rows: 1, table: t, display_property: `${t}_id`, display_is_key: true, properties: 1,
  bindings: 1, proposed_bindings: 0, links: 0, traversable_links: 0, actions: 0, metrics: 0,
});

const typeMap = (...links: TypeMapLink[]): TypeMap => {
  const types = Array.from(new Set(links.flatMap((l) => [l.from, l.to]))).sort();
  return { connection_id: "c1", schema_name: "s", generated_at: "", links, object_types: types.map(row) };
};

/** The same map with types nothing links to — Lux's Brand, Country, Date and Warehouse. */
const withUnlinked = (map: TypeMap, ...types: string[]): TypeMap =>
  ({ ...map, object_types: [...map.object_types, ...types.map(row)] });

// customer — order — order_item — product, and order_item — shipment
const commerce = typeMap(link("customer", "order"), link("order", "order_item"), link("order_item", "product"),
  link("order_item", "shipment"));

const star = (n: number) => typeMap(...Array.from({ length: n }, (_, i) => link("hub", `t${String(i).padStart(2, "0")}`)));

/** Two boxes overlap unless they are a full width apart sideways or a full height apart upright. */
const overlap = (a: { x: number; y: number }, b: { x: number; y: number }, half: { w: number; h: number }) =>
  Math.abs(a.x - b.x) < 2 * half.w && Math.abs(a.y - b.y) < 2 * half.h;

describe("hubOf", () => {
  it("centres the map on the type with the most links", () => {
    expect(hubOf(commerce)).toBe("order_item");
  });

  it("breaks a tie on the display name, so the centre does not move between two equal reads", () => {
    expect(hubOf(typeMap(link("b", "a")))).toBe("a");
  });

  it("has no centre for a map with no types", () => {
    expect(hubOf({ ...commerce, object_types: [] })).toBeNull();
  });
});

describe("ringsOf", () => {
  it("puts the focus at the centre and every other type on the ring of its shortest distance", () => {
    expect(Object.fromEntries(ringsOf(commerce, "order"))).toEqual({
      order: 0, customer: 1, order_item: 1, product: 2, shipment: 2,
    });
  });

  it("puts an island — linked types the focus cannot reach — on the ring outside them all", () => {
    const islands = { ...commerce, links: [...commerce.links, link("promo", "coupon")] };
    const rings = ringsOf({ ...islands, object_types: [...islands.object_types, row("promo"), row("coupon")] }, "order");
    expect(rings.get("promo")).toBe(3);
    expect(rings.get("coupon")).toBe(3);
  });

  it("gives a type with no links at all no ring — it is listed under the map instead", () => {
    const map = withUnlinked(commerce, "country", "brand");
    expect(ringsOf(map, "order").has("country")).toBe(false);
    expect(unlinkedTypes(map, "order")).toEqual(["country", "brand"]);   // the rail's order, not re-sorted
  });

  it("keeps the centred type off that list, however few links it has", () => {
    expect(unlinkedTypes(withUnlinked(commerce, "country"), "country")).toEqual([]);
  });

  it("places a type on the ring of its SHORTEST distance", () => {
    const triangle = typeMap(link("a", "b"), link("b", "c"), link("a", "c"));
    expect(Object.fromEntries(ringsOf(triangle, "a"))).toEqual({ a: 0, b: 1, c: 1 });
  });
});

describe("litBy", () => {
  it("lights a type, its links and the types on the other end of them", () => {
    const { nodes, links } = litBy(commerce, "order");
    expect([...nodes].sort()).toEqual(["customer", "order", "order_item"]);
    expect([...links].sort()).toEqual(["customer_order", "order_order_item"]);
  });

  it("lights nothing when nothing is picked, so the map reads whole", () => {
    expect(litBy(commerce, null)).toEqual({ nodes: new Set(), links: new Set() });
  });
});

describe("layoutMap", () => {
  it("draws every linked type, and hands the rest to the list under the map", () => {
    const layout = layoutMap(withUnlinked(commerce, "country"), "order");
    expect(layout.nodes.map((n) => n.objectType).sort())
      .toEqual(["customer", "order", "order_item", "product", "shipment"]);
    expect(layout.unlinked).toEqual(["country"]);
  });

  it("draws every link whose two types are both on the map, neighbour-to-neighbour included", () => {
    const triangle = typeMap(link("a", "b"), link("b", "c"), link("a", "c"));
    const layout = layoutMap(triangle, "a");
    expect(layout.edges.map((e) => e.link.relationship).sort()).toEqual(["a_b", "a_c", "b_c"]);
  });

  it.each([2, 7, 12, 40])("centres the focus and never overlaps two of %i neighbour cards", (n) => {
    const layout = layoutMap(star(n), "hub");
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

  it("holds the centred card even when the type has no links at all", () => {
    const layout = layoutMap(withUnlinked({ ...commerce, links: [], object_types: [] }, "country"), "country");
    expect(layout.width).toBeGreaterThan(2 * FOCUS_HALF.w);
    expect(layout.height).toBeGreaterThan(2 * FOCUS_HALF.h);
  });

  it("puts the second ring outside the first", () => {
    const layout = layoutMap(commerce, "order");
    const distance = (t: string) => {
      const node = layout.nodes.find((n) => n.objectType === t)!;
      return Math.hypot(node.x - layout.width / 2, node.y - layout.height / 2);
    };
    const inner = Math.max(distance("customer"), distance("order_item"));
    expect(Math.min(distance("product"), distance("shipment"))).toBeGreaterThan(inner);
  });

  it("bows a link between two cards on one ring outwards, away from the cards inside it", () => {
    const layout = layoutMap(typeMap(link("a", "b"), link("a", "c"), link("b", "c")), "a");
    const centre = { x: layout.width / 2, y: layout.height / 2 };
    const chord = layout.edges.find((e) => e.link.relationship === "b_c")!;
    expect(chord.bowed).toBe(true);
    expect(chord.path).toMatch(/^M [\d.-]+ [\d.-]+ Q /);
    const midpoint = { x: (chord.x1 + chord.x2) / 2, y: (chord.y1 + chord.y2) / 2 };
    expect(Math.hypot(chord.labelX - centre.x, chord.labelY - centre.y))
      .toBeGreaterThan(Math.hypot(midpoint.x - centre.x, midpoint.y - centre.y));
    const spoke = layout.edges.find((e) => e.link.relationship === "a_b")!;
    expect(spoke.bowed).toBe(false);
    expect(spoke.path).toMatch(/^M [\d.-]+ [\d.-]+ L [\d.-]+ [\d.-]+$/);
  });

  it("steps a label off the line when the two cards leave it no room", () => {
    const layout = layoutMap(star(2), "hub");
    const hub = layout.nodes.find((n) => n.objectType === "hub")!;
    const edge = layout.edges[0];
    const onTheLine = Math.abs((edge.labelX - hub.x) * (edge.y2 - edge.y1) - (edge.labelY - hub.y) * (edge.x2 - edge.x1))
      / Math.hypot(edge.x2 - edge.x1, edge.y2 - edge.y1);
    expect(onTheLine).toBeCloseTo(LABEL_ASIDE, 6);
  });

  it("sets every label on a spoke where neither card on its line hides it", () => {
    const layout = layoutMap(star(7), "hub");
    const hub = layout.nodes.find((n) => n.objectType === "hub")!;
    for (const edge of layout.edges) {
      const other = layout.nodes.find((n) => n.objectType === edge.link.to)!;
      const label = { x: edge.labelX, y: edge.labelY };
      expect(Math.abs(label.x - hub.x) >= FOCUS_HALF.w || Math.abs(label.y - hub.y) >= FOCUS_HALF.h).toBe(true);
      expect(Math.abs(label.x - other.x) >= NEIGHBOUR_HALF.w || Math.abs(label.y - other.y) >= NEIGHBOUR_HALF.h).toBe(true);
    }
  });
});
