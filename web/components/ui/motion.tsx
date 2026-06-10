"use client";

/**
 * WCH-15 — shared motion primitives. ONE spinner / skeleton / async-button
 * instead of the three hand-rolled spinner definitions and ten text-only
 * pending buttons the audit found. All timing comes from the motion tokens
 * (--dur-*, --ease-*); reduced-motion is handled by the aug-* classes.
 */
import React from "react";

export function Spinner({ size = 14, color = "var(--blue3)" }: { size?: number; color?: string }) {
  return (
    <span
      className="aug-anim-spin"
      style={{
        display: "inline-block", width: size, height: size,
        border: `2px solid color-mix(in srgb, ${color} 25%, transparent)`,
        borderTopColor: color, borderRadius: "50%", flexShrink: 0,
      }}
      aria-label="loading"
    />
  );
}

export function Skeleton({ width = "100%", height = 12, radius = 4, style }: {
  width?: number | string; height?: number | string; radius?: number;
  style?: React.CSSProperties;
}) {
  return <div className="aug-shimmer" style={{ width, height, borderRadius: radius, ...style }} />;
}

/** A block of skeleton rows — the "panel is fetching" placeholder. */
export function SkeletonRows({ rows = 4, gap = 10 }: { rows?: number; gap?: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap, padding: "4px 0" }}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} width={`${88 - (i % 3) * 14}%`} />
      ))}
    </div>
  );
}

/** Entrance wrapper — keyed remounts get a fade+rise instead of a snap. */
export function FadeIn({ children, delayMs = 0 }: { children: React.ReactNode; delayMs?: number }) {
  return (
    <div className="aug-anim-up" style={delayMs ? { animationDelay: `${delayMs}ms` } : undefined}>
      {children}
    </div>
  );
}

/** Button with a real pending state — spinner + disabled, not a text "…". */
export function AsyncButton({ pending, children, disabled, style, ...rest }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { pending?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || pending}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        opacity: pending ? 0.75 : undefined,
        transition: "opacity var(--dur-fast) var(--ease-out)",
        ...style,
      }}
    >
      {pending && <Spinner size={11} color="currentColor" />}
      {children}
    </button>
  );
}
