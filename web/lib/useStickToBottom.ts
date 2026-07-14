"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Stick-to-bottom scroll behaviour for a streaming transcript.
 *
 * The container follows the newest content while the user is parked at the
 * bottom, but *releases* the instant they scroll up to read something — and
 * re-attaches when they scroll back down. `pinned` is false whenever the user
 * has scrolled away from the bottom; the caller uses it to show a
 * "jump to latest" affordance.
 *
 * Attach the returned `scrollRef` (a callback ref) to the scroll container. A
 * callback ref — rather than an object ref passed in — is deliberate: the
 * container often mounts *after* the hook first runs (e.g. an empty state gives
 * way to the transcript), and a callback ref re-attaches the scroll listener
 * the moment the element actually appears.
 *
 * `contentKey` should change on every streamed update (e.g. a hash of the
 * streaming turns). The hook re-follows the bottom on each change *only* while
 * pinned and active, so a user reading scrollback is never yanked down.
 *
 * Respects `prefers-reduced-motion`: falls back to an instant jump.
 */
export function useStickToBottom(
  contentKey: string | number,
  opts: { threshold?: number; active?: boolean } = {},
) {
  const { threshold = 80, active = true } = opts;
  const [el, setEl] = useState<HTMLElement | null>(null);
  const scrollRef = useCallback((node: HTMLElement | null) => setEl(node), []);

  const [pinned, setPinned] = useState(true);
  // Mirror `pinned` into a ref so the scroll listener and follow-effect read the
  // latest value without re-subscribing on every pin/unpin.
  const pinnedRef = useRef(true);
  useEffect(() => { pinnedRef.current = pinned; }, [pinned]);

  const prefersReduced = () =>
    typeof window !== "undefined" &&
    !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  const distanceFromBottom = (node: HTMLElement) =>
    node.scrollHeight - node.scrollTop - node.clientHeight;

  // Recompute `pinned` from the real scroll position on every user scroll.
  useEffect(() => {
    if (!el) return;
    const onScroll = () => {
      const atBottom = distanceFromBottom(el) <= threshold;
      if (atBottom !== pinnedRef.current) setPinned(atBottom);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [el, threshold]);

  const scrollToBottom = useCallback(
    (behavior: ScrollBehavior = "smooth") => {
      if (!el) return;
      el.scrollTo({ top: el.scrollHeight, behavior: prefersReduced() ? "auto" : behavior });
      setPinned(true);
    },
    [el],
  );

  // Follow the bottom as content streams in — but only while pinned & active.
  useEffect(() => {
    if (!active || !pinnedRef.current || !el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: prefersReduced() ? "auto" : "smooth" });
  }, [contentKey, active, el]);

  return { scrollRef, pinned, scrollToBottom };
}
