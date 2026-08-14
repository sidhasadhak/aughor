"use client";

/**
 * SE-4 I — asking the shell to change screens, from anywhere in the tree.
 *
 * `page.tsx` owns which tab is up. Until now nothing below it could ask to move: the URL
 * is written FROM that state, never read back into it after the initial load, so pushing
 * a URL from a nested component changes the address bar and nothing else — the worst
 * kind of broken, because it looks like it worked.
 *
 * An event rather than prop-drilling or a context provider: the shell is a single
 * long-lived listener, the senders are leaves several layers down and in dynamically
 * imported chunks, and threading a callback through every intermediate component would
 * put a navigation concern in files that have no other reason to know about tabs.
 *
 * Deliberately NOT a router. It carries a tab id and the query params that address a
 * thing inside it; anything richer belongs in a store the destination reads.
 */

export const NAVIGATE_EVENT = "aughor:navigate";

export interface NavigateRequest {
  /** A NavTab id, validated by the shell — an unknown one is ignored, not guessed at. */
  tab: string;
  /** Search params to apply on arrival, e.g. `{ conn }`. */
  params?: Record<string, string>;
}

export function requestTab(tab: string, params?: Record<string, string>): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<NavigateRequest>(NAVIGATE_EVENT, { detail: { tab, params } }),
  );
}
