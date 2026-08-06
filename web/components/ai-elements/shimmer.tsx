"use client";
/**
 * B1 (Track B, roadmap 2026-08-01) — `Shimmer`, hand-vendored.
 *
 * The Elements component API on OUR substrate: this file mirrors the surface of
 * Vercel AI Elements' `Shimmer` (a text label whose gradient sweeps while
 * something streams) but is written against the repo's design tokens and CSS —
 * NEVER `npx ai-elements add` (stock Elements is Radix-flavoured and fails the
 * css-var/token/raw-element gates; web/ is `base-nova` on @base-ui/react).
 *
 * CSS only — the sweep is `.aug-shimmer-text` (globals.css), the same
 * `aug-shimmer` keyframes the skeleton blocks use. No framer-motion.
 */
import { mergeProps } from "@base-ui/react/merge-props";
import { useRender } from "@base-ui/react/use-render";

import { cn } from "@/lib/utils";

export function Shimmer({
  className,
  active = true,
  render,
  ...props
}: useRender.ComponentProps<"span"> & {
  /** Sweep only while true — a finished label settles into plain muted text. */
  active?: boolean;
}) {
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(
          active ? "aug-shimmer-text" : undefined,
          className,
        ),
        style: active ? undefined : { color: "var(--t3)" },
      },
      props,
    ),
    render,
  });
}
