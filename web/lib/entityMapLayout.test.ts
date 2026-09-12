/**
 * ON-3b — where the entity-type map STARTS each card. The map is a claim about the business: the busiest type is
 * in the middle, a card on ring N is N links from it by the shortest route, a type no link reaches sits in the
 * row underneath rather than being dropped, and no two cards overlap however many neighbours the middle has.
 * Everything after that first arrangement is the canvas's and the person dragging on it.
 */
import { describe, expect, it } from "vitest";

import { CARD, hubOf, layoutMap, litBy, ringsOf, unlinkedTypes } from "@/lib/entityMapLayout";
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

/** Two cards overlap unless they are a full width apart sideways or a full height apart upright. */
const overlap = (a: { x: number; y: number }, b: { x: number; y: number }) =>
  Math.abs(a.x - b.x) < CARD.w && Math.abs(a.y - b.y) < CARD.h;

describe("hubOf", () => {
  it("puts the type with the most links in the middle", () => {
    expect(hubOf(commerce)).toBe("order_item");
  });

  it("breaks a tie on the display name, so the middle does not move between two equal reads", () => {
    expect(hubOf(typeMap(link("b", "a")))).toBe("a");
  });

  it("has no middle for a map with no types", () => {
    expect(hubOf({ ...commerce, object_types: [] })).toBeNull();
  });
});

describe("ringsOf", () => {
  it("puts the focus in the middle and every other type on the ring of its shortest distance", () => {
    expect(Object.fromEntries(ringsOf(commerce, "order"))).toEqual({
      order: 0, customer: 1, order_item: 1, product: 2, shipment: 2,
    });
  });

  it("puts an island — linked types the focus cannot reach — on the ring outside them all", () => {
    const islands = { ...commerce, links: [...commerce.links, link("promo", "coupon")] };
    const rings = ringsOf({ ...islands, object_types: [...islands.object_types, row("promo"), row("coupon")] }, "order");
    expect([rings.get("promo"), rings.get("coupon")]).toEqual([3, 3]);
  });

  it("gives a type with no links at all no ring — it goes in the row under the map", () => {
    const map = withUnlinked(commerce, "country", "brand");
    expect(ringsOf(map, "order").has("country")).toBe(false);
    expect(unlinkedTypes(map, "order")).toEqual(["country", "brand"]);   // the rail's order, not re-sorted
  });

  it("keeps the middle out of that row, however few links it has", () => {
    expect(unlinkedTypes(withUnlinked(commerce, "country"), "country")).toEqual([]);
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
  it("starts every type somewhere — on a ring, or in the row underneath", () => {
    const layout = layoutMap(withUnlinked(commerce, "country", "brand"), "order");
    expect(layout.nodes.map((n) => n.objectType).sort())
      .toEqual(["brand", "country", "customer", "order", "order_item", "product", "shipment"]);
    const unlinked = layout.nodes.filter((n) => n.ring === -1);
    expect(unlinked.map((n) => n.objectType)).toEqual(["country", "brand"]);
    const ringed = layout.nodes.filter((n) => n.ring >= 0);
    expect(Math.min(...unlinked.map((n) => n.y))).toBeGreaterThan(Math.max(...ringed.map((n) => n.y)));
    expect(overlap(unlinked[0], unlinked[1])).toBe(false);
  });

  it.each([2, 7, 12, 40])("centres the focus and never overlaps two of %i neighbour cards", (n) => {
    const layout = layoutMap(star(n), "hub");
    const hub = layout.nodes.find((node) => node.objectType === "hub")!;
    expect(hub.x).toBe(layout.width / 2);
    const ring = layout.nodes.filter((node) => node.ring === 1);
    expect(ring).toHaveLength(n);
    for (let i = 0; i < ring.length; i += 1) {
      expect(overlap(ring[i], hub)).toBe(false);
      for (let j = i + 1; j < ring.length; j += 1) expect(overlap(ring[i], ring[j])).toBe(false);
    }
  });

  it("puts the second ring outside the first", () => {
    const layout = layoutMap(commerce, "order");
    const hub = layout.nodes.find((n) => n.objectType === "order")!;
    const distance = (t: string) => {
      const node = layout.nodes.find((n) => n.objectType === t)!;
      return Math.hypot(node.x - hub.x, node.y - hub.y);
    };
    const inner = Math.max(distance("customer"), distance("order_item"));
    expect(Math.min(distance("product"), distance("shipment"))).toBeGreaterThan(inner);
  });

  it("holds a map whose only type has no links at all", () => {
    const lonely = { ...commerce, links: [], object_types: [row("country")] };
    const layout = layoutMap(lonely, "country");
    expect(layout.nodes).toEqual([{ objectType: "country", ring: 0, x: layout.width / 2, y: expect.any(Number) }]);
    expect(layout.width).toBeGreaterThanOrEqual(CARD.w);
  });
});
