"use client";

/**
 * ResizableSplit — a two-pane split with a draggable divider, on either axis.
 *
 * The FIRST pane (`left`) has a controlled size (px) the user can drag; the second
 * (`right`) flexes to fill the rest. Size persists per `storageKey` in localStorage.
 * Double-click the handle to reset to `initial`.
 *
 * `direction` defaults to "horizontal" — the original behaviour, so every existing
 * caller is untouched. "vertical" stacks the panes (first above, second below) and
 * drags on Y, which is what an editor-over-results layout needs (SE-1's SQL mode).
 * One component rather than a near-copy: the drag/persist/reset logic is the part
 * worth not having twice, and the axis is genuinely the only difference.
 *
 * Used to make internal panels resizable (everything except the app's fixed
 * left nav and top bar). Keep both children as plain flex containers.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";

export function ResizableSplit({
  storageKey,
  initial = 280,
  min = 180,
  max = 640,
  left,
  right,
  direction = "horizontal",
  className,
  style,
}: {
  storageKey: string;
  initial?: number;
  min?: number;
  max?: number;
  left: React.ReactNode;
  right: React.ReactNode;
  /** Axis of the split. "horizontal" (default) = side by side, drag on X. */
  direction?: "horizontal" | "vertical";
  className?: string;
  style?: React.CSSProperties;
}) {
  const vertical = direction === "vertical";
  const [width, setWidth] = useState<number>(initial);
  const dragging = useRef(false);

  // Restore persisted width
  useEffect(() => {
    try {
      const raw = localStorage.getItem(`split:${storageKey}`);
      if (raw) {
        const n = parseInt(raw, 10);
        if (!Number.isNaN(n)) setWidth(Math.min(max, Math.max(min, n)));
      }
    } catch { /* ignore */ }
  }, [storageKey, min, max]);

  const persist = useCallback((w: number) => {
    try { localStorage.setItem(`split:${storageKey}`, String(Math.round(w))); } catch { /* ignore */ }
  }, [storageKey]);

  const onDown = (e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    const start = vertical ? e.clientY : e.clientX;
    const startW = width;
    const move = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const now = vertical ? ev.clientY : ev.clientX;
      const next = Math.min(max, Math.max(min, startW + (now - start)));
      setWidth(next);
    };
    const up = () => {
      dragging.current = false;
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      setWidth(w => { persist(w); return w; });
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
    document.body.style.cursor = vertical ? "row-resize" : "col-resize";
    document.body.style.userSelect = "none";
  };

  const reset = () => { setWidth(initial); persist(initial); };

  return (
    <div
      className={className}
      style={{
        display: "flex", flexDirection: vertical ? "column" : "row",
        minHeight: 0, minWidth: 0, ...style,
      }}
    >
      <div
        style={vertical
          ? { height: width, flexShrink: 0, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }
          : { width, flexShrink: 0, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}
      >
        {left}
      </div>
      {/* Divider */}
      <div
        onMouseDown={onDown}
        onDoubleClick={reset}
        title="Drag to resize · double-click to reset"
        style={vertical
          ? {
              height: 6, marginTop: -3, marginBottom: -3, cursor: "row-resize",
              zIndex: 5, flexShrink: 0, position: "relative",
              display: "flex", justifyContent: "stretch", alignItems: "center",
            }
          : {
              width: 6, marginLeft: -3, marginRight: -3, cursor: "col-resize",
              zIndex: 5, flexShrink: 0, position: "relative",
              display: "flex", alignItems: "stretch", justifyContent: "center",
            }}
      >
        <span
          style={vertical
            ? { height: 1, width: "100%", background: "var(--b0)", transition: "background .1s" }
            : { width: 1, background: "var(--b0)", transition: "background .1s" }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "var(--blue4, #60a5fa)"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "var(--b0)"; }}
        />
      </div>
      <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {right}
      </div>
    </div>
  );
}
