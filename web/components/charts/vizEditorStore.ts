"use client";

/**
 * vizEditorStore — a tiny module-level store so the Databricks-style viz editor
 * (VizEditorPanel) is a SINGLE-INSTANCE right-docked drawer across the whole app.
 *
 * Every clean chart surface (ResultChartCard) owns its own control state and portals
 * its own <VizEditorPanel> to <body> only while it is the open one. This store holds
 * just the id of the card whose editor is open, so opening one pencil closes any other
 * — no provider to mount, no context to thread. Subscribed via useSyncExternalStore, so
 * a card re-renders exactly when it opens or closes.
 */

import { useSyncExternalStore } from "react";

let openId: string | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

export function openVizEditor(id: string) {
  if (openId === id) return;
  openId = id;
  emit();
}

export function closeVizEditor(id?: string) {
  // A stale close (a card closing after another already opened) must not clobber the
  // newly-open one — only clear when we still own the slot (or an unconditional close).
  if (id != null && openId !== id) return;
  if (openId === null) return;
  openId = null;
  emit();
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

/** True when THIS card's viz editor is the one currently open. */
export function useVizEditorOpen(id: string): boolean {
  const get = () => openId === id;
  // Server snapshot is always closed (the drawer is client-only).
  return useSyncExternalStore(subscribe, get, () => false);
}
