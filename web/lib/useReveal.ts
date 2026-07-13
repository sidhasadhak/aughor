"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Typewriter reveal for text that arrives all at once.
 *
 * The backend sends an answer's headline as a single complete event, so there
 * is no token stream to ride — this reveals the finished string
 * character-by-character on the client so an answer feels written rather than
 * pasted, then settles to the full text.
 *
 * Pass `enabled: false` for restored/historical text (renders instantly).
 * Respects `prefers-reduced-motion` (also instant).
 */
export function useReveal(text: string, opts: { enabled?: boolean } = {}) {
  const { enabled = true } = opts;
  const full = text || "";
  const reduce =
    typeof window !== "undefined" &&
    !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const animate = enabled && !reduce && full.length > 0;

  // Lazy init avoids a flash of the full string before the effect starts.
  const [count, setCount] = useState(() => (animate ? 0 : full.length));
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!animate) {
      setCount(full.length);
      return;
    }
    setCount(0);
    const total = full.length;
    const durationMs = Math.min(1100, Math.max(280, total * 13));
    const t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / durationMs);
      setCount(Math.round(p * total));
      if (p < 1) rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [full, animate]);

  return { shown: full.slice(0, count), revealing: count < full.length };
}

/**
 * Close a dangling `**` so a half-revealed string never leaks literal
 * asterisks or breaks emphasis parsing mid-typewriter.
 */
export function safePartial(s: string): string {
  const marks = (s.match(/\*\*/g) || []).length;
  return marks % 2 === 1 ? s + "**" : s;
}
