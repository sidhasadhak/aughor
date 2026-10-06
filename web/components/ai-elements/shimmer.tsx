"use client";
/**
 * B1 (Track B, roadmap 2026-08-01) — `Shimmer`, hand-vendored.
 *
 * The Elements component API on OUR substrate: this file mirrors the surface of
 * Vercel AI Elements' `Shimmer` (a text label that moves while something
 * streams) but is written against the repo's design tokens and CSS —
 * NEVER `npx ai-elements add` (stock Elements carries its own styling and fails
 * the css-var/token/raw-element gates).
 *
 * CSS only — `.aug-shimmer-text` (globals.css): solid text breathing between
 * two grey steps, beside the `aug-shimmer` sweep the skeleton blocks use. A plain
 * `<span>`: nothing here needs a library (Base UI left the web 2026-10-06).
 */
import { cn } from "@/lib/utils";

export function Shimmer({
  className,
  active = true,
  style,
  ...props
}: React.ComponentProps<"span"> & {
  /** Sweep only while true — a finished label settles into plain muted text. */
  active?: boolean;
}) {
  return (
    <span
      className={cn(active ? "aug-shimmer-text" : undefined, className)}
      style={active ? style : { color: "var(--t3)", ...style }}
      {...props}
    />
  );
}
