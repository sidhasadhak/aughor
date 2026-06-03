"use client";

/**
 * ResizableSplit — a two-pane horizontal split with a draggable divider.
 *
 * The LEFT pane has a controlled width (px) that the user can drag; the RIGHT
 * pane flexes to fill the rest. Width persists per `storageKey` in localStorage.
 * Double-click the handle to reset to `initial`.
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
  className,
  style,
}: {
  storageKey: string;
  initial?: number;
  min?: number;
  max?: number;
  left: React.ReactNode;
  right: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
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
    const startX = e.clientX;
    const startW = width;
    const move = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const next = Math.min(max, Math.max(min, startW + (ev.clientX - startX)));
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
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  const reset = () => { setWidth(initial); persist(initial); };

  return (
    <div className={className} style={{ display: "flex", minHeight: 0, minWidth: 0, ...style }}>
      <div style={{ width, flexShrink: 0, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {left}
      </div>
      {/* Divider */}
      <div
        onMouseDown={onDown}
        onDoubleClick={reset}
        title="Drag to resize · double-click to reset"
        style={{
          width: 6, marginLeft: -3, marginRight: -3, cursor: "col-resize",
          zIndex: 5, flexShrink: 0, position: "relative",
          display: "flex", alignItems: "stretch", justifyContent: "center",
        }}
      >
        <span style={{ width: 1, background: "var(--border-0, #2a2a2a)", transition: "background .1s" }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "var(--blue4, #60a5fa)"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "var(--border-0, #2a2a2a)"; }}
        />
      </div>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {right}
      </div>
    </div>
  );
}
