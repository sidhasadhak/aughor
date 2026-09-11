/**
 * ON-3b — where each card sits on the entity-type map (ROADMAP §3.15, amended 2026-09-11).
 *
 * The map is centred on ONE type. The types one link away sit on the first ring; a person expands a neighbour to
 * open its links, and the types they reach sit on the ring outside it — breadth-first, so every type sits on the
 * ring of its shortest distance from the centre, and nothing beyond an opened type is drawn. A ring grows with its
 * cards so they never overlap, and each ring is ordered by where its types' nearest inner neighbours sit, so links
 * run outwards instead of across the map.
 *
 * Pure: the map component draws what this returns, and the tests pin it without a DOM.
 */
import type { TypeMap, TypeMapLink } from "@/lib/objectTypes";

export interface MapNode {
  objectType: string;
  ring: number;
  x: number;
  y: number;
}

export interface MapEdge {
  link: TypeMapLink;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface MapLayout {
  nodes: MapNode[];
  edges: MapEdge[];
  width: number;
  height: number;
}

/** The least distance between two rings. */
export const RING_GAP = 240;
/** The arc one card needs on a ring — a neighbour card's width plus air. */
export const CARD_ARC = 230;
/** Room beyond the outermost ring for a card's half-width and its label. */
export const MAP_PAD = 170;

function neighboursOf(map: TypeMap): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  const add = (a: string, b: string) => {
    const set = out.get(a) ?? new Set<string>();
    set.add(b);
    out.set(a, set);
  };
  for (const link of map.links) {
    if (link.from === link.to) continue;
    add(link.from, link.to);
    add(link.to, link.from);
  }
  return out;
}

/** type → ring for every type visible around `focus`: the focus, its neighbours, and the neighbours of each
 *  expanded type that is itself visible. */
export function visibleRings(map: TypeMap, focus: string, expanded: ReadonlySet<string>): Map<string, number> {
  const neighbours = neighboursOf(map);
  const rings = new Map<string, number>([[focus, 0]]);
  let frontier = [focus];
  for (let depth = 0; frontier.length > 0; depth += 1) {
    const next: string[] = [];
    for (const type of frontier) {
      if (type !== focus && !expanded.has(type)) continue;          // only an opened type shows its links
      for (const other of Array.from(neighbours.get(type) ?? []).sort()) {
        if (!rings.has(other)) {
          rings.set(other, depth + 1);
          next.push(other);
        }
      }
    }
    frontier = next;
  }
  return rings;
}

/** Whether a type has links to types the map is not yet showing — the expand affordance's condition. */
export function hasHiddenNeighbours(map: TypeMap, type: string, rings: ReadonlyMap<string, number>): boolean {
  return Array.from(neighboursOf(map).get(type) ?? []).some((other) => !rings.has(other));
}

export function layoutMap(map: TypeMap, focus: string, expanded: ReadonlySet<string>): MapLayout {
  const rings = visibleRings(map, focus, expanded);
  const neighbours = neighboursOf(map);
  const members = new Map<number, string[]>();
  rings.forEach((ring, type) => members.set(ring, [...(members.get(ring) ?? []), type]));
  const outer = Math.max(0, ...Array.from(rings.values()));

  const radius: number[] = [0];
  for (let ring = 1; ring <= outer; ring += 1) {
    const count = members.get(ring)?.length ?? 0;
    radius.push(Math.max(radius[ring - 1] + RING_GAP, (count * CARD_ARC) / (2 * Math.PI)));
  }
  const centre = radius[outer] + MAP_PAD;

  const angle = new Map<string, number>([[focus, 0]]);
  const position = new Map<string, { x: number; y: number }>([[focus, { x: centre, y: centre }]]);
  for (let ring = 1; ring <= outer; ring += 1) {
    const inner = (type: string) => {
      const placed = Array.from(neighbours.get(type) ?? [])
        .filter((other) => rings.get(other) === ring - 1)
        .map((other) => angle.get(other) ?? 0);
      return placed.length ? Math.min(...placed) : 0;
    };
    const ordered = [...(members.get(ring) ?? [])].sort((a, b) => inner(a) - inner(b) || a.localeCompare(b));
    ordered.forEach((type, i) => {
      const a = -Math.PI / 2 + (2 * Math.PI * i) / ordered.length;
      angle.set(type, a);
      position.set(type, { x: centre + Math.cos(a) * radius[ring], y: centre + Math.sin(a) * radius[ring] });
    });
  }

  const nodes = Array.from(rings.entries()).map(([objectType, ring]) => ({ objectType, ring, ...position.get(objectType)! }));
  const edges = map.links
    .filter((link) => link.from !== link.to && position.has(link.from) && position.has(link.to))
    .map((link) => {
      const a = position.get(link.from)!;
      const b = position.get(link.to)!;
      return { link, x1: a.x, y1: a.y, x2: b.x, y2: b.y };
    });
  return { nodes, edges, width: centre * 2, height: centre * 2 };
}
