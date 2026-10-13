/**
 * PENDING item 9 — the company-brain map, shaped for the screen. Pure: the panel renders what
 * these return, and the tests assert on them (jsdom measures nothing, so the picture's geometry is
 * computed here from fixed sizes — never read back from the DOM — and its truth lives here).
 */
import type { BrainBox, BrainEdge, BrainFact, BrainMap } from "@/lib/api";
import { formatCount, formatPercent } from "@/lib/format";

export interface VaultColumn { id: BrainBox["vault"]; title: string; boxes: BrainBox[] }

/** The boxes grouped into their vaults, in the order the server gives both. */
export function vaultColumns(map: BrainMap): VaultColumn[] {
  return map.vaults.map((v) => ({ ...v, boxes: map.boxes.filter((b) => b.vault === v.id) }));
}

/** A box's number as it reads: a share as a percent, a count with separators, and an em dash
 *  when the store could not be read — its `line` says why. */
export function boxFigure(box: BrainBox): string {
  if (box.count === null || box.count === undefined) return "—";
  if (box.id === "visibility") return formatPercent(box.count, 0);
  return formatCount(box.count);
}

/** Each measured arrow as one sentence, naming both ends by their titles. */
export function edgeLines(map: BrainMap): string[] {
  return map.edges.map((e) => edgeSentence(map, e));
}

function edgeSentence(map: BrainMap, e: BrainEdge): string {
  const title = (id: string) => map.boxes.find((b) => b.id === id)?.title ?? id;
  return `${title(e.from)} → ${title(e.to)}: ${formatCount(e.count)} ${e.label}`;
}

/** Words that end an edge's noun: "findings landed in the graph as facts" → "findings". */
const NOUN_ENDS = new Set(["landed", "in", "of", "as", "raised", "asked", "to", "from", "into", "at", "by", "for", "on", "that"]);

/** What an arrow carries, short enough to sit on it: the count and the label's noun — "77 findings",
 *  "0 Briefing citations". The whole sentence rides the arrow's hover. */
export function edgeShort(e: BrainEdge): string {
  const words = e.label.trim().split(/\s+/);
  const cut = words.findIndex((w, i) => i > 0 && NOUN_ENDS.has(w.toLowerCase()));
  return `${formatCount(e.count)} ${(cut > 0 ? words.slice(0, cut) : words).join(" ")}`.trim();
}

/** CB-1's owed screen: the facts that changed since first seen, each with what it replaced. */
export function recentFacts(map: BrainMap): {
  id: string; label: string; kind: string; changed: string; replaced: string; reason: string;
}[] {
  const facts = (map.boxes.find((b) => b.id === "facts")?.detail?.recent ?? []) as BrainFact[];
  return facts.map((f) => {
    const last = f.history[f.history.length - 1];
    const was = last?.facts
      ? Object.values(last.facts)
        .map((v) => (Array.isArray(v) ? v.join(", ") : v))
        .filter((v) => v !== null && v !== undefined && v !== "")
        .join(" · ")
      : "";
    return { id: f.id, label: f.label || f.id, kind: f.kind, changed: (f.last_changed || "").slice(0, 10),
             replaced: was || last?.summary || "", reason: last?.reason ?? "" };
  });
}

// ── The picture ────────────────────────────────────────────────────────────────────────────

/** Fixed sizes the picture is drawn at, in px — the layout never measures the DOM. */
export const MAP = { head: 26, nodeH: 92, gap: 34, gutterPct: 10, port: 28, portPct: 8 } as const;

/** One box's place: x as a percent of the picture's width, y in px. */
export interface MapNode { box: BrainBox; col: number; row: number; x0: number; x1: number; y0: number; y1: number }
/** One straight run of an arrow (x in percent, y in px). */
export interface MapSeg { x1: number; y1: number; x2: number; y2: number }
export interface MapRoute {
  key: string;
  edge: BrainEdge;
  segs: MapSeg[];
  /** Where the arrow's count sits: just above a horizontal arrow, or `beside` — to the right of — a vertical run, so the
   *  label never hides the line it names. */
  label: { x: number; y: number; beside: boolean };
  /** "Findings → Dated facts: 77 findings landed in the graph as facts" — the hover. */
  sentence: string;
}
export interface MapLayout {
  columns: { id: string; title: string; x0: number; x1: number }[];
  nodes: MapNode[];
  routes: MapRoute[];
  /** Arrows the picture cannot draw without crossing a box (two vaults apart, or an end it does not hold) — the
   *  panel says them in words instead, so none is lost. */
  unplaced: string[];
  height: number;
}

type Side = "left" | "right" | "top" | "bottom";

/**
 * The map as a picture: the vaults as columns, each store a box in its column, and every measured link an arrow whose
 * runs are straight and bend only at right angles (CLARITY §3). An arrow between neighbouring columns runs through the
 * gutter between them; one within a column joins two boxes stacked one above the other, or runs out to the side gutter
 * when they are not neighbours. Two arrows on one side of a box are spread apart, so neither hides the other.
 */
export function mapLayout(map: BrainMap): MapLayout {
  const cols = vaultColumns(map);
  const n = Math.max(1, cols.length);
  const colW = (100 - (n - 1) * MAP.gutterPct) / n;
  const columns = cols.map((c, i) => ({ id: c.id, title: c.title, x0: i * (colW + MAP.gutterPct), x1: i * (colW + MAP.gutterPct) + colW }));
  const nodes: MapNode[] = [];
  cols.forEach((c, ci) => c.boxes.forEach((box, ri) => {
    const y0 = MAP.head + ri * (MAP.nodeH + MAP.gap);
    nodes.push({ box, col: ci, row: ri, x0: columns[ci].x0, x1: columns[ci].x1, y0, y1: y0 + MAP.nodeH });
  }));
  const rows = Math.max(1, ...cols.map((c) => c.boxes.length));
  const height = MAP.head + rows * MAP.nodeH + (rows - 1) * MAP.gap + 4;
  const byId = new Map(nodes.map((nd) => [nd.box.id, nd]));

  // Which side of each end an arrow leaves and arrives at.
  type Plan = { i: number; edge: BrainEdge; s: MapNode; t: MapNode; ss: Side; ts: Side; gutter: number | null };
  const plans: Plan[] = [];
  const unplaced: string[] = [];
  map.edges.forEach((edge, i) => {
    const s = byId.get(edge.from);
    const t = byId.get(edge.to);
    if (!s || !t || s === t || Math.abs(t.col - s.col) > 1) { unplaced.push(edgeSentence(map, edge)); return; }
    if (t.col === s.col + 1) plans.push({ i, edge, s, t, ss: "right", ts: "left", gutter: s.col });
    else if (t.col === s.col - 1) plans.push({ i, edge, s, t, ss: "left", ts: "right", gutter: t.col });
    else if (Math.abs(t.row - s.row) === 1) {
      plans.push({ i, edge, s, t, ss: t.row < s.row ? "top" : "bottom", ts: t.row < s.row ? "bottom" : "top", gutter: null });
    } else {
      // Two boxes of one column with others between them: out to the side gutter and back.
      const right = s.col < n - 1;
      plans.push({ i, edge, s, t, ss: right ? "right" : "left", ts: right ? "right" : "left", gutter: right ? s.col : s.col - 1 });
    }
  });

  // Spread the arrows that share a side of a box, ordered by where their other end is so they do not cross.
  const ports = new Map<string, { plan: Plan; end: "s" | "t"; other: MapNode }[]>();
  const portKey = (nd: MapNode, side: Side) => `${nd.box.id}:${side}`;
  for (const p of plans) {
    for (const [end, nd, side, other] of [["s", p.s, p.ss, p.t], ["t", p.t, p.ts, p.s]] as const) {
      const k = portKey(nd, side);
      ports.set(k, [...(ports.get(k) ?? []), { plan: p, end, other }]);
    }
  }
  const offset = new Map<string, number>();     // `${planIndex}:${end}` → px from the side's middle
  for (const list of ports.values()) {
    list.sort((a, b) => (a.other.row - b.other.row) || (a.plan.i - b.plan.i));
    list.forEach((a, k) => offset.set(`${a.plan.i}:${a.end}`, (k - (list.length - 1) / 2) * MAP.port));
  }
  const count = (nd: MapNode, side: Side) => ports.get(portKey(nd, side))?.length ?? 1;
  // A straight arrow stays straight: where one end has the side to itself, it takes the other end's height.
  for (const p of plans) {
    if (p.s.row !== p.t.row || p.gutter === null || p.ss === p.ts) continue;
    if (count(p.s, p.ss) === 1) offset.set(`${p.i}:s`, offset.get(`${p.i}:t`) ?? 0);
    else if (count(p.t, p.ts) === 1) offset.set(`${p.i}:t`, offset.get(`${p.i}:s`) ?? 0);
  }

  // Lanes in each gutter for the arrows that must run up or down it.
  const yOf = (p: Plan, end: "s" | "t") => {
    const nd = end === "s" ? p.s : p.t;
    return (nd.y0 + nd.y1) / 2 + (offset.get(`${p.i}:${end}`) ?? 0);
  };
  const lanes = new Map<number, Plan[]>();
  for (const p of plans) {
    if (p.gutter === null || yOf(p, "s") === yOf(p, "t")) continue;
    lanes.set(p.gutter, [...(lanes.get(p.gutter) ?? []), p]);
  }
  const laneX = new Map<number, number>();
  for (const [g, list] of lanes) {
    const gl = columns[g].x1;
    list.forEach((p, k) => laneX.set(p.i, gl + ((k + 1) * MAP.gutterPct) / (list.length + 1)));
  }

  const routes: MapRoute[] = plans.map((p) => {
    const key = `${p.edge.from}->${p.edge.to}#${p.i}`;
    const sentence = edgeSentence(map, p.edge);
    if (p.gutter === null) {
      // Stacked neighbours in one column: a short vertical run between them.
      const xs = (p.s.x0 + p.s.x1) / 2 + ((offset.get(`${p.i}:s`) ?? 0) / MAP.port) * MAP.portPct;
      const y1 = p.ss === "top" ? p.s.y0 : p.s.y1;
      const y2 = p.ts === "top" ? p.t.y0 : p.t.y1;
      return { key, edge: p.edge, sentence, segs: [{ x1: xs, y1, x2: xs, y2 }], label: { x: xs, y: (y1 + y2) / 2, beside: true } };
    }
    const xs = p.ss === "right" ? p.s.x1 : p.s.x0;
    const xt = p.ts === "right" ? p.t.x1 : p.t.x0;
    const ys = yOf(p, "s");
    const yt = yOf(p, "t");
    if (ys === yt) {
      const mid = columns[p.gutter].x1 + MAP.gutterPct / 2;
      return { key, edge: p.edge, sentence, segs: [{ x1: xs, y1: ys, x2: xt, y2: yt }], label: { x: mid, y: ys, beside: false } };
    }
    const lx = laneX.get(p.i) ?? columns[p.gutter].x1 + MAP.gutterPct / 2;
    return {
      key, edge: p.edge, sentence,
      segs: [{ x1: xs, y1: ys, x2: lx, y2: ys }, { x1: lx, y1: ys, x2: lx, y2: yt }, { x1: lx, y1: yt, x2: xt, y2: yt }],
      label: { x: lx, y: (ys + yt) / 2, beside: true },
    };
  });

  return { columns, nodes, routes, unplaced, height };
}
