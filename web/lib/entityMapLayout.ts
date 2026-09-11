/**
 * ON-3b — where each card sits on the entity-type map (ROADMAP §3.15, amended 2026-09-11).
 *
 * The map is centred on ONE type. The types one link away sit on the first ring; a person expands a neighbour to
 * open its links, and the types they reach sit on the ring outside it — breadth-first, so every type sits on the
 * ring of its shortest distance from the centre, and nothing beyond an unopened type is drawn. Rings are ellipses,
 * because cards are wide and short: a sideways link needs room for two card widths and its label, an upright one
 * only for two card heights. A ring grows with its cards so they never overlap, each ring is ordered by where its
 * types' nearest inner neighbours sit so links run outwards, and a link's label sits in the stretch of its line
 * that neither card covers.
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

/** A link's line, centre to centre, and where its label sits. */
export interface MapEdge {
  link: TypeMapLink;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  labelX: number;
  labelY: number;
}

export interface MapLayout {
  nodes: MapNode[];
  edges: MapEdge[];
  width: number;
  height: number;
}

/** Half the centred card and half a neighbour card — the stretch of a link's line each one hides. */
export const FOCUS_HALF = { w: 118, h: 96 };
export const NEIGHBOUR_HALF = { w: 90, h: 30 };
/** The first ring's radii, and how much wider each ring outside it is. */
export const RING = { rx: 310, ry: 200 };
export const RING_STEP = { rx: 290, ry: 180 };
/** The arc one card needs on a ring — a neighbour card's width plus air. */
export const CARD_ARC = 210;
/** Room beyond the outermost ring for a card. */
export const MAP_PAD = { x: NEIGHBOUR_HALF.w + 10, y: NEIGHBOUR_HALF.h + 40 };

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

/** How far along a line in direction (dx, dy) a box of half-size `half` reaches from its centre. */
function reach(half: { w: number; h: number }, dx: number, dy: number): number {
  const length = Math.hypot(dx, dy) || 1;
  const cos = Math.abs(dx) / length;
  const sin = Math.abs(dy) / length;
  return Math.min(cos > 1e-9 ? half.w / cos : Infinity, sin > 1e-9 ? half.h / sin : Infinity);
}

export function layoutMap(map: TypeMap, focus: string, expanded: ReadonlySet<string>): MapLayout {
  const rings = visibleRings(map, focus, expanded);
  const neighbours = neighboursOf(map);
  const members = new Map<number, string[]>();
  rings.forEach((ring, type) => members.set(ring, [...(members.get(ring) ?? []), type]));
  const outer = Math.max(0, ...Array.from(rings.values()));

  const radii = [{ rx: 0, ry: 0 }];
  for (let ring = 1; ring <= outer; ring += 1) {
    const rx = ring === 1 ? RING.rx : radii[ring - 1].rx + RING_STEP.rx;
    const ry = ring === 1 ? RING.ry : radii[ring - 1].ry + RING_STEP.ry;
    const perimeter = 2 * Math.PI * Math.sqrt((rx * rx + ry * ry) / 2);
    const grow = Math.max(1, ((members.get(ring)?.length ?? 0) * CARD_ARC) / perimeter);
    radii.push({ rx: rx * grow, ry: ry * grow });
  }
  const cx = radii[outer].rx + MAP_PAD.x;
  const cy = radii[outer].ry + MAP_PAD.y;

  const angle = new Map<string, number>([[focus, 0]]);
  const position = new Map<string, { x: number; y: number }>([[focus, { x: cx, y: cy }]]);
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
      position.set(type, { x: cx + Math.cos(a) * radii[ring].rx, y: cy + Math.sin(a) * radii[ring].ry });
    });
  }

  const half = (type: string) => (type === focus ? FOCUS_HALF : NEIGHBOUR_HALF);
  const nodes = Array.from(rings.entries()).map(([objectType, ring]) => ({ objectType, ring, ...position.get(objectType)! }));
  const edges = map.links
    .filter((link) => link.from !== link.to && position.has(link.from) && position.has(link.to))
    .map((link) => {
      const a = position.get(link.from)!;
      const b = position.get(link.to)!;
      const [dx, dy] = [b.x - a.x, b.y - a.y];
      const length = Math.hypot(dx, dy) || 1;
      const [ca, cb] = [reach(half(link.from), dx, dy), reach(half(link.to), dx, dy)];
      // the middle of the stretch neither card covers — the plain midpoint when the cards nearly touch
      const t = length > ca + cb ? (ca + (length - ca - cb) / 2) / length : 0.5;
      return { link, x1: a.x, y1: a.y, x2: b.x, y2: b.y, labelX: a.x + dx * t, labelY: a.y + dy * t };
    });
  return { nodes, edges, width: cx * 2, height: cy * 2 };
}
