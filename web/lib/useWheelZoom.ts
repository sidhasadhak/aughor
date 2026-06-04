import { useEffect, useRef } from "react";

/**
 * useWheelZoom — touchpad pinch-zoom + ⌘/Ctrl-wheel zoom-to-cursor for any
 * scroll viewport that holds a `transform: scale(zoom)` child.
 *
 * A plain two-finger scroll (no modifier) falls through to the browser's
 * native overflow pan.  Only the zoom gesture (which arrives as a `wheel`
 * event with ctrlKey set — that's how trackpad pinch surfaces in the DOM —
 * or an explicit ⌘/Ctrl-wheel) calls preventDefault and rescales.
 *
 * The handler keeps the point under the cursor fixed while scaling, then
 * corrects scrollLeft/scrollTop on the next frame once the spacer has resized.
 */
export function useWheelZoom(
  scrollRef: React.RefObject<HTMLDivElement | null>,
  zoom: number,
  setZoom: (z: number) => void,
  opts: { min?: number; max?: number } = {},
) {
  const { min = 0.15, max = 2.5 } = opts;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    function onWheel(e: WheelEvent) {
      if (!e.ctrlKey && !e.metaKey) return;   // not a zoom gesture — let it pan
      e.preventDefault();
      const node = el as HTMLDivElement;
      const prev = zoomRef.current;
      const d    = Math.max(-50, Math.min(50, e.deltaY));   // clamp mouse-wheel jumps
      const next = Math.min(max, Math.max(min, +(prev * Math.exp(-d * 0.0025)).toFixed(3)));
      if (next === prev) return;

      const rect = node.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const cx = (node.scrollLeft + px) / prev;
      const cy = (node.scrollTop  + py) / prev;
      setZoom(next);
      requestAnimationFrame(() => {
        node.scrollLeft = cx * next - px;
        node.scrollTop  = cy * next - py;
      });
    }
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [scrollRef, setZoom, min, max]);
}
