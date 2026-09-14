"use client";

/**
 * toast — a tiny module-level notification store + a single global <Toaster/>.
 *
 * Mirrors the vizEditorStore idiom (module state + useSyncExternalStore + a <body>
 * portal): any code can call `toast.success(...)` / `toast.error(...)` without a
 * provider to mount or context to thread. One <Toaster/> lives in the root layout
 * and renders every toast, wherever it was raised.
 *
 * Design language: a toast is one of the three things allowed to float (.aug-toast):
 * --bg-1, a 3px left rule in its hue, radius 6, --shadow-md; a mono glyph, the title at
 * 12px, the detail at 11px. It enters with step-in. Auto-dismisses (errors linger
 * longest); hover and a hidden tab pause the timer; manual × dismiss. Announced via a stable aria-live
 * region.
 */

import { useEffect, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/button";

export type ToastKind = "success" | "error" | "info" | "warning";

export interface ToastData {
  id: string;
  kind: ToastKind;
  title: string;
  description?: string;
  /** ms until auto-dismiss; 0 keeps it until dismissed. */
  duration: number;
}

interface ToastOpts {
  description?: string;
  duration?: number;
}

// ── module store ──────────────────────────────────────────────────────────────
let items: ToastData[] = [];
const listeners = new Set<() => void>();
let seq = 0;
const MAX_VISIBLE = 4;

const DEFAULT_DURATION: Record<ToastKind, number> = {
  success: 3500,
  info: 4000,
  warning: 5000,
  error: 6500,
};

function emit() {
  for (const l of listeners) l();
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

function push(kind: ToastKind, title: string, opts?: ToastOpts): string {
  const id = `toast-${++seq}`;
  const duration = opts?.duration ?? DEFAULT_DURATION[kind];
  // Keep only the most-recent MAX_VISIBLE so a burst can't paper over the screen.
  items = [...items, { id, kind, title, description: opts?.description, duration }].slice(-MAX_VISIBLE);
  emit();
  return id;
}

export function dismissToast(id: string) {
  if (!items.some((t) => t.id === id)) return;
  items = items.filter((t) => t.id !== id);
  emit();
}

/** Raise a notification. Returns the id so a caller can dismiss it early. */
export const toast = {
  success: (title: string, opts?: ToastOpts) => push("success", title, opts),
  error: (title: string, opts?: ToastOpts) => push("error", title, opts),
  info: (title: string, opts?: ToastOpts) => push("info", title, opts),
  warning: (title: string, opts?: ToastOpts) => push("warning", title, opts),
};

function useToasts(): ToastData[] {
  return useSyncExternalStore(subscribe, () => items, () => items);
}

// getServerSnapshot returns false, so the server AND the client's first (hydration)
// render both see `false` → the client-only portal stays unrendered until after
// hydration, with no server/client HTML mismatch. Canonical, effect-free.
const noopSubscribe = () => () => {};
function useHydrated(): boolean {
  return useSyncExternalStore(noopSubscribe, () => true, () => false);
}

// A background tab holds every timer: a toast raised while the reader is in another tab is still
// there when they come back, and one already showing waits for them.
function subscribeVisibility(cb: () => void) {
  document.addEventListener("visibilitychange", cb);
  return () => document.removeEventListener("visibilitychange", cb);
}
function useTabHidden(): boolean {
  return useSyncExternalStore(subscribeVisibility, () => document.visibilityState === "hidden", () => false);
}

// ── presentation ──────────────────────────────────────────────────────────────
// The glyphs are the guard vocabulary — ✓ passed, ◈ warned, ✕ refused — so a toast and a
// guard chip say the same thing the same way.
const KIND: Record<ToastKind, { glyph: string; color: string }> = {
  success: { glyph: "✓", color: "var(--grn4)" },
  error: { glyph: "✕", color: "var(--red4)" },
  warning: { glyph: "◈", color: "var(--amb4)" },
  info: { glyph: "●", color: "var(--blue4)" },
};

function ToastRow({ t, tabHidden }: { t: ToastData; tabHidden: boolean }) {
  const [paused, setPaused] = useState(false);

  // Each row owns its own dismiss timer; hover pauses it so a reader can finish, and so does a
  // hidden tab. A pause restarts the full duration.
  useEffect(() => {
    if (t.duration <= 0 || paused || tabHidden) return;
    const timer = setTimeout(() => dismissToast(t.id), t.duration);
    return () => clearTimeout(timer);
  }, [t.id, t.duration, paused, tabHidden]);

  const k = KIND[t.kind];

  return (
    <div
      className={`aug-toast aug-toast-${t.kind} aug-anim-up`}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      style={{
        pointerEvents: "auto",
        width: 340,
        maxWidth: "calc(100vw - 32px)",
      }}
    >
      <span
        aria-hidden
        className="aug-fs-xs"
        style={{ color: k.color, lineHeight: "18px", fontFamily: "var(--font-mono)", flex: "0 0 auto" }}
      >
        {k.glyph}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="aug-fs-sm" style={{ color: "var(--t1)", lineHeight: "18px", overflowWrap: "anywhere" }}>
          {t.title}
        </div>
        {t.description && (
          <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2, overflowWrap: "anywhere" }}>
            {t.description}
          </div>
        )}
      </div>
      <Button
        variant="ghost"
        size="icon-xs"
        aria-label="Dismiss notification"
        onClick={() => dismissToast(t.id)}
        className="aug-fs-sm"
        style={{ flex: "0 0 auto", marginTop: -2, marginRight: -2, color: "var(--t3)", lineHeight: 1 }}
      >
        ✕
      </Button>
    </div>
  );
}

/** The single global notification stack. Mount once (root layout). */
export function Toaster() {
  const list = useToasts();
  const hydrated = useHydrated();
  const tabHidden = useTabHidden();
  if (!hydrated || typeof document === "undefined") return null;
  return createPortal(
    <div
      aria-live="polite"
      aria-atomic="false"
      aria-label="Notifications"
      style={{
        position: "fixed",
        right: 16,
        bottom: 16,
        zIndex: 400,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        pointerEvents: "none",
      }}
    >
      {list.map((t) => (
        <ToastRow key={t.id} t={t} tabHidden={tabHidden} />
      ))}
    </div>,
    document.body,
  );
}
