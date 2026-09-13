"use client";

/**
 * Motion primitives, held to the Instrument motion spec (INSTRUMENT.md §8).
 *
 * There are no spinners anywhere in the product. A control that is working keeps its rest
 * state and gains the ◐ mark (<Pending/>); a region waiting on data shows a skeleton the
 * shape of what it replaces — same row height, same column widths. Timing and each
 * animation's reduced-motion resting frame live in the aug-* classes (app/globals.css).
 */
import React from "react";

/** The pending mark: ◐ in mono at .8 opacity. Static on purpose — presence, not a spinner.
 *  Pass `label` when nothing beside the mark says what is pending; it then announces as a
 *  status. Without one it is decoration beside text that already says it ("Running…"). */
export function Pending({ label, className = "", style }: {
  label?: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  return label
    ? <span role="status" aria-label={label} className={`aug-pending ${className}`} style={style}>◐</span>
    : <span aria-hidden className={`aug-pending ${className}`} style={style}>◐</span>;
}

export function Skeleton({ width = "100%", height = 11, radius = "var(--r1)", style }: {
  width?: number | string; height?: number | string; radius?: number | string;
  style?: React.CSSProperties;
}) {
  return <div className="aug-skeleton" style={{ width, height, borderRadius: radius, flexShrink: 0, ...style }} />;
}

/** The "panel is fetching" placeholder: dense 24px rows ruled in --b0 — a dot, a label
 *  and two short figures, the shape of the list and table rows it stands in for. */
export function SkeletonRows({ rows = 4, gap = 6 }: { rows?: number; gap?: number }) {
  return (
    <div aria-hidden style={{ display: "flex", flexDirection: "column", gap, padding: "4px 0" }}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, height: 24, borderBottom: "1px solid var(--b0)" }}>
          <Skeleton width={7} height={7} radius="50%" />
          <Skeleton width={`${44 - (i % 3) * 8}%`} />
          <Skeleton width={46} />
          <Skeleton width={30} />
        </div>
      ))}
    </div>
  );
}
