/**
 * gridLayout — a small, pure grid-packing core for the cockpit canvas.
 *
 * The cockpit is a SNAP-TO-GRID board on which cards never overlap and never leave a gap they could
 * fill. Every card occupies an integer cell rectangle {gx,gy,gw,gh} on a uniform `GRID`-px lattice,
 * and the board is TOP-LEFT PACKED: each card, in priority order, drops into the top-most / then
 * left-most free position it fits (`packTopLeft`) — so cards gravitate up AND left, the left gutter
 * never sits empty, and a small card slots into a hole a taller neighbour left behind. When one card
 * is dragged or resized it is PINNED at the reader's chosen cell and every OTHER card repacks around
 * it; on release the whole board repacks so priority order and geometry settle with no gaps.
 *
 * Everything here is pure and framework-free so the packing is trivial to reason about (and to reuse
 * from the React-Flow wiring in PinnedCardsCanvas without dragging React into the maths).
 */

/** Pixels per grid cell. Also the canvas background-dot gap, so the dots mark exactly where a card
 *  edge can land. */
export const GRID = 20;

export type Box = { x: number; y: number; w: number; h: number };
export type Cell = { gx: number; gy: number; gw: number; gh: number };
export type Cells = Record<string, Cell>;

const clampN = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/**
 * Snap a pixel box to a cell, honouring a per-card minimum (in cells) and the column count so a card
 * can never be narrower than its floor nor hang off the right edge of the board.
 */
export function boxToCell(box: Box, minW: number, minH: number, cols: number): Cell {
  const gw = clampN(Math.round(box.w / GRID), minW, Math.max(minW, cols));
  const gh = Math.max(minH, Math.round(box.h / GRID));
  const gx = clampN(Math.round(box.x / GRID), 0, Math.max(0, cols - gw));
  const gy = Math.max(0, Math.round(box.y / GRID));
  return { gx, gy, gw, gh };
}

export const cellPos = (c: Cell) => ({ x: c.gx * GRID, y: c.gy * GRID });
export const cellSize = (c: Cell) => ({ w: c.gw * GRID, h: c.gh * GRID });

/** Do two cells overlap (share any area)? */
const overlaps = (a: Cell, b: Cell) =>
  a.gx < b.gx + b.gw && b.gx < a.gx + a.gw && a.gy < b.gy + b.gh && b.gy < a.gy + a.gh;

/**
 * Top-left-most free cell where a `gw×gh` box fits among `placed`, within `cols` columns.
 *
 * The best top-left position always aligns to a "corner" — its left edge on x=0 or a placed card's
 * left/right edge, its top edge on y=0 or a placed card's top/bottom edge. We scan those candidate
 * lines top-to-bottom then left-to-right and take the first that collides with nothing, so a box
 * fills the highest hole it can reach and, within that, hugs the left.
 */
function firstFit(gw: number, gh: number, placed: Cell[], cols: number): { gx: number; gy: number } {
  const w = Math.min(gw, Math.max(1, cols));
  const xs = new Set<number>([0]);
  const ys = new Set<number>([0]);
  for (const p of placed) {
    xs.add(p.gx); xs.add(p.gx + p.gw);
    ys.add(p.gy); ys.add(p.gy + p.gh);
  }
  const candX = [...xs].filter((x) => x + w <= cols).sort((a, b) => a - b);
  const candY = [...ys].sort((a, b) => a - b);
  for (const gy of candY) {
    for (const gx of candX) {
      if (!placed.some((p) => overlaps(p, { gx, gy, gw: w, gh }))) return { gx, gy };
    }
  }
  // Nothing fit against a corner (box wider than any hole) — drop it below everything, hugging left.
  let maxB = 0;
  for (const p of placed) maxB = Math.max(maxB, p.gy + p.gh);
  return { gx: 0, gy: maxB };
}

/**
 * Top-left pack `cells` into a gap-free, overlap-free layout, returning a new layout.
 *
 * `pinned` ids keep their exact cell — the card the reader is actively dragging/resizing stays under
 * the cursor while everything else flows around it. All other cards are placed in PRIORITY ORDER
 * (their current reading order: top-to-bottom, left-to-right), each dropping into the top-left-most
 * hole it fits. Priority order is what a drag rewrites: drop a card higher/further left and it packs
 * earlier, i.e. more prominently.
 */
export function packTopLeft(cells: Cells, pinned: string[] = [], cols = 1_000): Cells {
  const pinnedSet = new Set(pinned);
  const placed: Cell[] = [];
  const out: Cells = {};

  // Pinned cards anchor the board first, at their exact cells.
  for (const id of pinned) {
    const c = cells[id];
    if (!c) continue;
    out[id] = c;
    placed.push(c);
  }

  // Everyone else packs top-left, in priority (reading) order.
  const others = Object.keys(cells)
    .filter((id) => !pinnedSet.has(id))
    .sort((a, b) => cells[a].gy - cells[b].gy || cells[a].gx - cells[b].gx);
  for (const id of others) {
    const c = cells[id];
    const gw = Math.min(c.gw, Math.max(1, cols));
    const { gx, gy } = firstFit(gw, c.gh, placed, cols);
    const nc: Cell = { gx, gy, gw, gh: c.gh };
    out[id] = nc;
    placed.push(nc);
  }
  return out;
}

/** Bottom-most occupied row (in cells) — where a freshly-added card starts before it packs up. */
export function bottomRow(cells: Cells): number {
  let b = 0;
  for (const id in cells) b = Math.max(b, cells[id].gy + cells[id].gh);
  return b;
}
