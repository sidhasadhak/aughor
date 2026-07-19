"use client";

/**
 * commandRegistry — a tiny module-level store of executable commands for the ⌘K
 * command palette. Mirrors the vizEditorStore / toast idiom (module state +
 * useSyncExternalStore; no provider).
 *
 * Commands are registered per SCOPE so a view can contribute CONTEXTUAL commands
 * while it is mounted (e.g. Briefing → "Regenerate brief"; Query Builder → "Run
 * query") and withdraw them on unmount — exactly the context-aware behaviour of a
 * real command palette. Global commands register once under a stable scope.
 *
 * Callers pass a STABLE (useMemo'd) command array to useRegisterCommands so the
 * scope isn't churned every render; run() closures should reach current handlers
 * via refs where the handler identity isn't stable.
 */

import { useEffect, useSyncExternalStore } from "react";

export interface Command {
  id: string;
  label: string;
  sublabel?: string;
  icon?: string;        // ICONS key in CommandPalette (defaults to "spark")
  accent?: string;      // CSS colour for the icon (defaults to violet)
  keywords?: string;    // extra fuzzy-match terms, not displayed
  run: () => void;
}

let scopes: Record<string, Command[]> = {};
let flat: Command[] = [];                 // memoised flat list; stable ref until a change
const listeners = new Set<() => void>();

function recompute() {
  flat = Object.values(scopes).flat();
}
function emit() {
  for (const l of listeners) l();
}

export function registerCommands(scopeId: string, commands: Command[]) {
  scopes = { ...scopes, [scopeId]: commands };
  recompute();
  emit();
}

export function unregisterCommands(scopeId: string) {
  if (!(scopeId in scopes)) return;
  const next = { ...scopes };
  delete next[scopeId];
  scopes = next;
  recompute();
  emit();
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

/** All currently-registered commands, flattened across scopes. */
export function useCommands(): Command[] {
  return useSyncExternalStore(subscribe, () => flat, () => flat);
}

/** Register a scope's commands for the mounting component's lifetime. Pass a
 *  STABLE (useMemo'd) `commands` array to avoid re-registering every render. */
export function useRegisterCommands(scopeId: string, commands: Command[]) {
  useEffect(() => {
    registerCommands(scopeId, commands);
    return () => unregisterCommands(scopeId);
  }, [scopeId, commands]);
}
