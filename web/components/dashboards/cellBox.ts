/**
 * The box a cockpit element is drawn in, said to what it draws (Arc AP-1, sizes one grade at a time).
 *
 * On a section's grid an element is given an exact room — `w` columns by `h` rows — and what it draws fills that room:
 * a chart draws at the box's height, a table lists as many rows as the box holds, an image fits it. Off the grid an
 * element is as tall as what it draws, as it was before, and says so with `onGrid: false`.
 */
import { createContext, useContext, useEffect, useState } from "react";

export interface CellBox {
  /** Whether the element stands on a section's grid, in a box of fixed height. */
  onGrid: boolean;
  /** Columns across and rows down, on the grid; 0 off it. */
  w: number;
  h: number;
}

export const OFF_GRID: CellBox = { onGrid: false, w: 0, h: 0 };

export const CellBoxContext = createContext<CellBox>(OFF_GRID);

export function useCellBox(): CellBox {
  return useContext(CellBoxContext);
}

/** How much the builder's canvas scales the cockpit it draws (Arc AP-1): 1 at 100%, less where it fits a narrower
 *  screen. A pointer's pixels are the scaled ones, so a handle divides by it to count grades. */
export const CanvasScale = createContext(1);

/** The drawn size of an element, in px, followed as it changes. 0 × 0 until measured (and in a test's DOM). The ref
 *  is a callback: a piece that draws "Reading…" first and its chart after hands it two elements, and the second is
 *  the one followed. */
export function useMeasured<T extends HTMLElement>(): [(el: T | null) => void, { width: number; height: number }] {
  const [el, setEl] = useState<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const read = () => setSize(prev => (prev.width === el.clientWidth && prev.height === el.clientHeight
      ? prev : { width: el.clientWidth, height: el.clientHeight }));
    const ro = new ResizeObserver(read);
    ro.observe(el);
    read();
    return () => ro.disconnect();
  }, [el]);
  return [setEl, size];
}

/** A value that follows `value` once it has stopped changing for `ms` — and is `value` at first. A box being resized
 *  grade by grade settles before what it reads is read again: one read when the drag or the keys stop, not one a grade. */
export function useSettled<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    if (Object.is(value, settled)) return;
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms, settled]);
  return settled;
}
