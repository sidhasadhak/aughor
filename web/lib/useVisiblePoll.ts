"use client";

/**
 * Poll only what a person can see (PENDING · Agent Ops: "opening any layer fires the whole
 * workspace's fetch set").
 *
 * A workspace keeps every layer it has shown MOUNTED, so switching back is instant — and every
 * mounted panel kept its interval. Measured 2026-10-04 on the live dev server: sitting on the
 * Roster, which polls nothing, the page made 33 API calls in 30 s — the hidden Overview
 * reloading four endpoints every 15 s (and again on every kernel job event), the hidden
 * Attention list every 10 s, the badges every 20 s. A background browser tab polled the same.
 *
 * `useLayerActive()` is true while the panel's layer is showing AND the document is visible;
 * `useVisiblePoll(fn, ms)` runs `fn` every `ms` only while active, and once at the moment it
 * becomes active again, so a layer shown after a pause is current, not stale. Outside a
 * Workspace a panel counts as showing.
 */
import { createContext, useContext, useEffect, useRef, useState } from "react";

/** Set by `Workspace` around each layer: is that layer the one on screen? */
export const LayerVisibleContext = createContext(true);

function documentVisible(): boolean {
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

export function useLayerActive(): boolean {
  const layerVisible = useContext(LayerVisibleContext);
  const [docVisible, setDocVisible] = useState(documentVisible);
  useEffect(() => {
    const onChange = () => setDocVisible(documentVisible());
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
  return layerVisible && docVisible;
}

export function useVisiblePoll(fn: () => void, ms: number): boolean {
  const active = useLayerActive();
  const fnRef = useRef(fn);
  useEffect(() => { fnRef.current = fn; }, [fn]);

  useEffect(() => {
    if (!active) return;
    const iv = setInterval(() => fnRef.current(), ms);
    return () => clearInterval(iv);
  }, [active, ms]);

  // Shown again after a pause: refresh at once rather than wait out a whole interval.
  const wasActive = useRef(active);
  useEffect(() => {
    if (active && !wasActive.current) fnRef.current();
    wasActive.current = active;
  }, [active]);
  return active;
}
