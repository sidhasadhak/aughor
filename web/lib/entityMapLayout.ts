/**
 * ON-3b — where each card sits on the entity-type map (ROADMAP §3.15, amended 2026-09-11; re-laid 2026-09-12).
 *
 * The map draws the WHOLE business at once and puts the type with the most links at the centre, so the first thing
 * a person reads off it is which entity everything else hangs from. Every other type sits on the ring of its
 * shortest distance from that centre — one link away on the first ring, two on the second — and a type no link
 * reaches sits on the ring outside them all rather than being left off. Nothing is hidden behind an expander:
 * what is dimmed, not what is drawn, is how the map answers "and what does THIS one touch?" (`litBy`).
 *
 * Rings are ellipses, because cards are wide and short: a sideways link needs room for two card widths and its
 * label, an upright one only for two card heights. A ring grows with its cards so they never overlap, each ring is
 * ordered by where its types' nearest inner neighbours sit so links run outwards, a link between two cards on the
 * SAME ring bows outward instead of cutting through the middle, and a link's label sits in the stretch of its line
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

/** A link's line, the path it is drawn along, and where its label sits. */
export interface MapEdge {
  link: TypeMapLink;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  /** The SVG path the component draws: a line between rings, a bowed curve along one. */
  path: string;
  /** True when the two cards sit on the same ring and the link bows around it. */
  bowed: boolean;
  labelX: number;
  labelY: number;
}

export interface MapLayout {
  nodes: MapNode[];
  edges: MapEdge[];
  /** Types no link touches — listed under the map, not drawn on a ring (`unlinkedTypes`). */
  unlinked: string[];
  width: number;
  height: number;
}

/** Half the centred card and half a neighbour card — the stretch of a link's line each one hides. */
export const FOCUS_HALF = { w: 118, h: 96 };
export const NEIGHBOUR_HALF = { w: 90, h: 30 };
/** The first ring's radii, and how much wider each ring outside it is. */
export const RING = { rx: 270, ry: 186 };
export const RING_STEP = { rx: 170, ry: 124 };
/** The arc one card needs on a ring — a neighbour card's width plus air. */
export const CARD_ARC = 210;
/** How much clear line a label needs, and how far it steps aside when the line does not have it. */
export const LABEL_ROOM = 96;
export const LABEL_ASIDE = 36;
/** Room beyond the outermost ring for a card, and the smallest map that still holds the centred card. */
export const MAP_PAD = { x: NEIGHBOUR_HALF.w + 24, y: NEIGHBOUR_HALF.h + 56 };
export const MIN_HALF = { x: FOCUS_HALF.w + 60, y: FOCUS_HALF.h + 60 };

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

/** How many links each type has — the map centres on the busiest, which is the claim "this is what the business
 *  runs on". Ties break on the display name so the centre never moves between two equal reads. */
export function hubOf(map: TypeMap): string | null {
  const degree = new Map<string, number>();
  for (const link of map.links) {
    if (link.from === link.to) continue;
    degree.set(link.from, (degree.get(link.from) ?? 0) + 1);
    degree.set(link.to, (degree.get(link.to) ?? 0) + 1);
  }
  const ranked = [...map.object_types].sort((a, b) =>
    (degree.get(b.object_type) ?? 0) - (degree.get(a.object_type) ?? 0) ||
    a.display_name.localeCompare(b.display_name));
  return ranked[0]?.object_type ?? null;
}

/** The types no link touches at all, in the rail's order. A ring says how far a type is along the links; a type
 *  with no links has no such distance, so it is listed under the map rather than parked on a far ring that would
 *  double the map's size to say nothing. The centred type is never in this list — it is on the map. */
export function unlinkedTypes(map: TypeMap, focus: string): string[] {
  const linked = neighboursOf(map);
  return map.object_types
    .filter((t) => t.object_type !== focus && (linked.get(t.object_type)?.size ?? 0) === 0)
    .map((t) => t.object_type);
}

/** type → ring for every LINKED type: the centre at 0, a type N links from it on ring N, and a type its links
 *  never reach from here — a separate island of the graph — on the ring outside them all. */
export function ringsOf(map: TypeMap, focus: string): Map<string, number> {
  const neighbours = neighboursOf(map);
  const rings = new Map<string, number>([[focus, 0]]);
  let frontier = [focus];
  while (frontier.length > 0) {
    const next: string[] = [];
    for (const type of frontier) {
      const depth = rings.get(type) ?? 0;
      for (const other of Array.from(neighbours.get(type) ?? []).sort()) {
        if (rings.has(other)) continue;
        rings.set(other, depth + 1);
        next.push(other);
      }
    }
    frontier = next;
  }
  const island = Math.max(0, ...Array.from(rings.values())) + 1;
  for (const type of map.object_types) {
    if (rings.has(type.object_type) || (neighbours.get(type.object_type)?.size ?? 0) === 0) continue;
    rings.set(type.object_type, island);
  }
  return rings;
}

/** What one type lights up: itself, the types it links to, and those links. Nothing is lit when nothing is
 *  selected — the map is then read whole. */
export function litBy(map: TypeMap, type: string | null): { nodes: Set<string>; links: Set<string> } {
  const nodes = new Set<string>();
  const links = new Set<string>();
  if (!type) return { nodes, links };
  nodes.add(type);
  for (const link of map.links) {
    if (link.from !== type && link.to !== type) continue;
    links.add(link.relationship);
    nodes.add(link.from);
    nodes.add(link.to);
  }
  return { nodes, links };
}

/** How far along a line in direction (dx, dy) a box of half-size `half` reaches from its centre. */
function reach(half: { w: number; h: number }, dx: number, dy: number): number {
  const length = Math.hypot(dx, dy) || 1;
  const cos = Math.abs(dx) / length;
  const sin = Math.abs(dy) / length;
  return Math.min(cos > 1e-9 ? half.w / cos : Infinity, sin > 1e-9 ? half.h / sin : Infinity);
}

export function layoutMap(map: TypeMap, focus: string): MapLayout {
  const rings = ringsOf(map, focus);
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
  const cx = Math.max(radii[outer].rx + MAP_PAD.x, MIN_HALF.x);
  const cy = Math.max(radii[outer].ry + MAP_PAD.y, MIN_HALF.y);

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
  const nodes = Array.from(rings.entries())
    .filter(([objectType]) => position.has(objectType))
    .map(([objectType, ring]) => ({ objectType, ring, ...position.get(objectType)! }));
  const edges = map.links
    .filter((link) => link.from !== link.to && position.has(link.from) && position.has(link.to))
    .map((link) => {
      const a = position.get(link.from)!;
      const b = position.get(link.to)!;
      const [dx, dy] = [b.x - a.x, b.y - a.y];
      const length = Math.hypot(dx, dy) || 1;
      const bowed = rings.get(link.from) === rings.get(link.to) && (rings.get(link.from) ?? 0) > 0;
      if (bowed) {
        // A link along one ring bows AWAY from the centre rather than cutting across the cards inside it. The bow is
        // PERPENDICULAR to the chord — pushing along the chord would only slide the line, not bend it — and its sign
        // is whichever side points outwards. A chord straight through the middle has no outward side: it bends the
        // one way perpendicular allows, deterministically.
        const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        const perp = { x: -dy / length, y: dx / length };
        const outward = perp.x * (mid.x - cx) + perp.y * (mid.y - cy);
        const sign = outward < 0 ? -1 : 1;
        const bulge = Math.min(180, length * 0.3);
        const control = { x: mid.x + perp.x * sign * bulge, y: mid.y + perp.y * sign * bulge };
        return {
          link, x1: a.x, y1: a.y, x2: b.x, y2: b.y, bowed: true,
          path: `M ${a.x} ${a.y} Q ${control.x} ${control.y} ${b.x} ${b.y}`,
          labelX: (a.x + 2 * control.x + b.x) / 4,   // the curve at its halfway point
          labelY: (a.y + 2 * control.y + b.y) / 4,
        };
      }
      const [ca, cb] = [reach(half(link.from), dx, dy), reach(half(link.to), dx, dy)];
      // The middle of the stretch neither card covers. When that stretch is too short to hold a label — two cards
      // almost touching, which the rings allow on a diagonal — the label steps aside off the line rather than
      // being laid over a card.
      const clear = length - ca - cb;
      const t = clear > 0 ? (ca + clear / 2) / length : 0.5;
      const aside = clear < LABEL_ROOM ? LABEL_ASIDE : 0;
      return {
        link, x1: a.x, y1: a.y, x2: b.x, y2: b.y, bowed: false,
        path: `M ${a.x} ${a.y} L ${b.x} ${b.y}`,
        labelX: a.x + dx * t - (dy / length) * aside,
        labelY: a.y + dy * t + (dx / length) * aside,
      };
    });
  return { nodes, edges, unlinked: unlinkedTypes(map, focus), width: cx * 2, height: cy * 2 };
}
