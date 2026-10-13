// @vitest-environment jsdom

/**
 * The Org board draws its own links — an SVG path per relationship, not a React Flow edge — so what it hands the
 * renderer is each path's `d`. The rule (aughor-v2/CLARITY.md §3, the user 2026-10-10): a graph connector is straight
 * and bends only at 90° or 45°, never along a curve. Both of the board's layouts are drawn — a small schema as a ring
 * round its busiest entity, a larger one in columns — so a link at every angle a cluster can hold is checked.
 */
import { describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@/lib/testing";

import type { CatalogTree, OntologyEntity, OntologyGraph, OntologyRelationship } from "@/lib/api";

const entity = (id: string): OntologyEntity => ({
  id, display_name: id, description: "", source_tables: [id], identity_key: `${id}_id`, grain_verified: true,
  domain: null, entity_type: "business_object", has_lifecycle: false, lifecycle_column: null, lifecycle_states: [],
  terminal_states: [], active_filter: null, segments: {}, created_at_col: null, default_filters: [], exclude_when: [],
  properties: {}, computed_properties: [], exploration_insights: [], implements: [],
});

const rel = (from: string, to: string): OntologyRelationship => ({
  id: `${from}_${to}`, from_entity: from, to_entity: to, verb: "belongs_to", cardinality: "N:1", join_sql: "",
  from_table: from, from_col: `${to}_id`, to_table: to, to_col: `${to}_id`, join_confidence: "verified", nullable: false,
});

const graph = (schema: string, rels: [string, string][]): OntologyGraph => {
  const ids = Array.from(new Set(rels.flat()));
  return {
    connection_id: "c1", schema_name: schema, schema_fingerprint: "", generated_at: "", enriched: true,
    entities: Object.fromEntries(ids.map((id) => [id, entity(id)])),
    relationships: Object.fromEntries(rels.map(([a, b]) => [`${a}_${b}`, rel(a, b)])),
    metrics: {}, actions: {}, interfaces: {},
  };
};

// a ring: five entities round the busiest one (the board draws a cluster of 2–6 this way)
const ring = graph("shop", [["order", "customer"], ["order_item", "order"], ["payment", "order"],
  ["shipment", "order"], ["return", "order"], ["order_item", "product"]]);
// columns: nine entities several links deep, with links that run up, down and level between columns
const columns = graph("crm", [["event", "session"], ["session", "user"], ["order", "user"], ["order_item", "order"],
  ["order_item", "product"], ["product", "brand"], ["inventory", "product"], ["inventory", "warehouse"],
  ["order", "warehouse"], ["event", "product"]]);

const tree: CatalogTree = {
  sections: [{ id: "s", label: "Sources", entries: [{
    conn_id: "c1", name: "Shop", conn_type: "postgres", builtin: false,
    schemas: [{ name: "shop", tables: [] }, { name: "crm", tables: [] }],
  }] }],
};

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getCatalogTree: vi.fn(async () => tree),
  getOntology: vi.fn(async (_conn: string, schema?: string) => (schema === "shop" ? ring : columns)),
}));

import { OntologyOrgCanvas } from "@/components/OntologyOrgCanvas";

/** The points a path passes through, and whether it uses any curve command. */
function geometryOf(d: string): { points: [number, number][]; curves: boolean } {
  const tokens = d.match(/[A-Za-z]|-?\d*\.?\d+(?:e-?\d+)?/g) ?? [];
  const points: [number, number][] = [];
  let curves = false;
  for (let i = 0; i < tokens.length;) {
    const command = tokens[i++];
    if ("CcSsQqTtAa".includes(command)) curves = true;
    const numbers: number[] = [];
    while (i < tokens.length && !/^[A-Za-z]$/.test(tokens[i])) numbers.push(Number(tokens[i++]));
    for (let j = 0; j + 1 < numbers.length; j += 2) points.push([numbers[j], numbers[j + 1]]);
  }
  return { points, curves };
}

/** Every link path the board drew — the arrowheads inside `<marker>` are not links. */
const linkPaths = (root: HTMLElement) =>
  Array.from(new Set(Array.from(root.querySelectorAll("svg path"))
    .filter((p) => !p.closest("marker"))
    .map((p) => p.getAttribute("d") ?? "")));

describe("OntologyOrgCanvas — the Org board's links", () => {
  it("draws every link straight, bending only at 90° or 45° — never along a curve (the user, 2026-10-10)", async () => {
    const { container } = render(<OntologyOrgCanvas onOpenConnection={() => {}} />);
    const total = Object.keys(ring.relationships).length + Object.keys(columns.relationships).length;
    // one path per relationship, in both clusters — a board that drew none would pass every check below
    await waitFor(() => expect(linkPaths(container).length).toBe(total));
    for (const d of linkPaths(container)) {
      const { points, curves } = geometryOf(d);
      expect(curves, d).toBe(false);
      expect(points.length, d).toBeGreaterThan(1);
      for (let i = 1; i < points.length; i++) {
        const [dx, dy] = [Math.abs(points[i][0] - points[i - 1][0]), Math.abs(points[i][1] - points[i - 1][1])];
        expect(dx === 0 || dy === 0 || Math.abs(dx - dy) < 1e-6, d).toBe(true);   // level, upright, or 45°
      }
    }
  });
});
