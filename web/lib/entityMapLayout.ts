/**
 * ON-3b — where each entity type STARTS on the map (ROADMAP §3.15; re-laid 2026-09-12).
 *
 * The map draws the whole business at once and puts the type with the most links in the middle, so the first thing
 * a person reads off it is which entity everything else hangs from. Every other type sits on the ring of its
 * shortest distance from that centre — one link away on the first ring, two on the second — and the types no link
 * reaches at all sit in a row underneath, because a ring would claim a distance they do not have.
 *
 * This is a STARTING arrangement, not the arrangement: the canvas is `@xyflow/react`, so a person drags a card
 * where they want it and that position is what they see next time. What lives here is only what has to be
 * decided before anyone has dragged anything — which is why there is no edge geometry in this file any more. The
 * canvas routes its own edges and places its own labels; this returns positions, and how far a label steps aside
 * when it would land on another (`separateLabels`).
 *
 * Pure: the map component draws what this returns, and the tests pin it without a DOM.
 */
import type { TypeMap, TypeMapLink } from "@/lib/objectTypes";

export interface MapNode {
  objectType: string;
  /** 0 at the centre, N for a type N links away, and -1 for a type no link reaches. */
  ring: number;
  /** The CENTRE of the card. The canvas positions by a card's top-left corner and converts. */
  x: number;
  y: number;
}

export interface MapLayout {
  nodes: MapNode[];
  width: number;
  height: number;
}

/** Every card is the same size: the middle of the map is a position, not a bigger box. */
export const CARD = { w: 196, h: 58 };
/** The first ring's radii, and how much wider each ring outside it is. Ellipses, because cards are wide and
 *  short: a sideways link needs room for two card widths and a label, an upright one only for two card heights. */
export const RING = { rx: 330, ry: 215 };
export const RING_STEP = { rx: 250, ry: 165 };
/** The arc one card needs on a ring — a card's width plus air for the label beside it. */
export const CARD_ARC = 250;
/** Room around the outermost ring, and how far under it the unlinked row sits. */
export const MAP_PAD = { x: CARD.w, y: CARD.h + 40 };
export const UNLINKED_GAP = 96;
/** How far above its cards a sideways link's label sits. */
export const LABEL_LIFT = 14;

/** Where a link's label sits, as a y. A SIDEWAYS link leaves its card by the left or right side and crosses a gap
 *  narrower than any label, so a label at the middle of its path lies under both cards and they clip it: it is
 *  lifted clear above the higher of the two cards. An upright link keeps the middle, where the gap is a card's height.
 *  `sourceY` and `targetY` are the handle points React Flow hands an edge; a side handle sits at its card's middle. */
export function linkLabelY(side: string, sourceY: number, targetY: number, middleY: number): number {
  if (side !== "left" && side !== "right") return middleY;
  return Math.min(sourceY, targetY) - CARD.h / 2 - LABEL_LIFT;
}

/** A link's label as the map sizes it before anything is drawn: 11px text (`--aug-fs-xs`) inside the 6×3 padding the
 *  map hands React Flow. A character is counted a little wider than Inter draws one, so two labels the map keeps
 *  apart are apart on screen too. One step aside is a label's height and the air above it. */
export const LINK_LABEL = { charW: 6.4, padX: 6, padY: 3, h: 20, gap: 4 };

/** One named link's label, centred where React Flow would put it. */
export interface LabelSpot {
  id: string;
  x: number;
  y: number;
  text: string;
  /** A sideways link's label is lifted clear above its cards (`linkLabelY`), so it only ever steps further up. */
  sideways: boolean;
}

interface Box { x0: number; y0: number; x1: number; y1: number }

const labelBox = (spot: LabelSpot, dy: number): Box => {
  const w = spot.text.length * LINK_LABEL.charW + 2 * LINK_LABEL.padX;
  return { x0: spot.x - w / 2, y0: spot.y + dy - LINK_LABEL.h / 2, x1: spot.x + w / 2, y1: spot.y + dy + LINK_LABEL.h / 2 };
};
const meets = (a: Box, b: Box) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
/** How many steps a label may take before it settles for the nearest place clear of every other label. */
const MAX_STEPS = 12;

/** How far each named link's label moves, up or down, so that no two labels lie on top of each other. Measured on the
 *  live maps (2026-10-13): theLook's Order opened with 5 of its 6 labels in a pile — three links run between Order and
 *  User and two between Order and Product, and links between the same two cards share one path and so one label
 *  point — and Lux's Platform had 6 of its 18 on a neighbour's. A label stays where React Flow puts it when that is
 *  clear; otherwise it steps a label's height at a time to the nearest place that touches no label already placed
 *  and no card, so the labels of links sharing a path stack along it. A card may cover a label's padding, which
 *  hides no text — counting that as a collision sent a label six steps up a map for a corner it barely touched.
 *  Sideways labels are placed first and then upright ones, each in the order given, so the same map always settles
 *  the same way. `cards` are top-left corners. */
export function separateLabels(spots: LabelSpot[], cards: { x: number; y: number }[] = []): Map<string, number> {
  const step = LINK_LABEL.h + LINK_LABEL.gap;
  const { padX, padY } = LINK_LABEL;
  const blocks = cards.map((c) => ({ x0: c.x + padX, y0: c.y + padY, x1: c.x + CARD.w - padX, y1: c.y + CARD.h - padY }));
  const placed: Box[] = [];
  const shifts = new Map<string, number>();
  // The labels with the fewest places to go are placed first: a sideways link's only steps up, an upright link's
  // either way.
  for (const spot of [...spots.filter((s) => s.sideways), ...spots.filter((s) => !s.sideways)]) {
    const tries = [0];
    for (let n = 1; n <= MAX_STEPS; n += 1) tries.push(...(spot.sideways ? [-n] : [-n, n]));
    const clearOfLabels = (t: number) => !placed.some((box) => meets(box, labelBox(spot, t * step)));
    const clearOfCards = (t: number) => !blocks.some((box) => meets(box, labelBox(spot, t * step)));
    const t = tries.find((n) => clearOfLabels(n) && clearOfCards(n)) ?? tries.find(clearOfLabels) ?? 0;
    shifts.set(spot.id, t * step);
    placed.push(labelBox(spot, t * step));
  }
  return shifts;
}

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

/** The type with the MOST links — the map's middle, which is the claim "this is what the business runs on".
 *  Ties break on the display name so the middle never moves between two equal reads. */
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

/** The types no link touches at all, in the rail's order. They sit in a row under the map: a ring says how far a
 *  type is along the links, and a type with no links has no such distance. The centre is never one of them. */
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
 *  picked — the map is then read whole. */
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
  const unlinked = unlinkedTypes(map, focus);
  const cx = Math.max(radii[outer].rx + MAP_PAD.x, (unlinked.length * CARD_ARC) / 2 + MAP_PAD.x, CARD.w);
  const cy = radii[outer].ry + MAP_PAD.y;

  const angle = new Map<string, number>([[focus, 0]]);
  const nodes: MapNode[] = [{ objectType: focus, ring: 0, x: cx, y: cy }];
  for (let ring = 1; ring <= outer; ring += 1) {
    // a ring is ordered by where its types' nearest inner neighbours sit, so links run outwards
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
      nodes.push({ objectType: type, ring, x: cx + Math.cos(a) * radii[ring].rx, y: cy + Math.sin(a) * radii[ring].ry });
    });
  }

  const row = cy + radii[outer].ry + UNLINKED_GAP;
  unlinked.forEach((objectType, i) => {
    nodes.push({ objectType, ring: -1, x: cx + (i - (unlinked.length - 1) / 2) * CARD_ARC, y: row });
  });
  return { nodes, width: cx * 2, height: unlinked.length ? row + CARD.h : cy * 2 };
}


/** ON-7 — the map with every PART folded into its parent: a type absorbed into another is not a card, and each
 *  link that touches it is drawn from the type that stands for it (`shown_from` / `shown_to`, the server's answer
 *  to "which card"), named with the part it came through. A link that would then join a card to itself — a part's
 *  link to its own parent — is not drawn: it is the binding the part is read through, already on the parent's
 *  card. Pure; the tests pin it. */
export function collapseParts(map: TypeMap): TypeMap {
  const names = new Map(map.object_types.map((t) => [t.object_type, t.display_name]));
  const shown = new Set(map.object_types.filter((t) => !t.absorbed_into).map((t) => t.object_type));
  const stands = (link: TypeMapLink, end: "from" | "to"): string => {
    const card = end === "from" ? link.shown_from : link.shown_to;
    return card && shown.has(card) ? card : link[end];
  };
  return {
    ...map,
    object_types: map.object_types.filter((t) => !t.absorbed_into),
    links: map.links.flatMap((link) => {
      const [from, to] = [stands(link, "from"), stands(link, "to")];
      if (from === to || !shown.has(from) || !shown.has(to)) return [];
      const via = [link.from, link.to].filter((end) => end !== from && end !== to).map((end) => names.get(end) ?? end);
      return [{ ...link, from, to, ...(via.length ? { via: via.join(", ") } : {}) }];
    }),
  };
}
