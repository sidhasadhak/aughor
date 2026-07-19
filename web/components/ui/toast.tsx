"use client";

/**
 * toast — a tiny module-level notification store + a single global <Toaster/>.
 *
 * Mirrors the vizEditorStore idiom (module state + useSyncExternalStore + a <body>
 * portal): any code can call `toast.success(...)` / `toast.error(...)` without a
 * provider to mount or context to thread. One <Toaster/> lives in the root layout
 * and renders every toast, wherever it was raised.
 *
 * Design language: flat aug-panel surface (bg-1 lifted over content), a kind-coloured
 * left accent + glyph, DM Sans title / mono glyph, the shared type scale. Dark-only,
 * like the rest of the app. Auto-dismisses (errors linger longest); hover pauses the
 * timer; manual × dismiss. Announced via a stable aria-live region.
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

// ── presentation ──────────────────────────────────────────────────────────────
const KIND: Record<ToastKind, { glyph: string; color: string }> = {
  success: { glyph: "✓", color: "var(--grn5)" },
  error: { glyph: "✗", color: "var(--red5)" },
  warning: { glyph: "⚠", color: "var(--amb5)" },
  info: { glyph: "●", color: "var(--blue5)" },
};

function ToastRow({ t }: { t: ToastData }) {
  const [paused, setPaused] = useState(false);

  // Each row owns its own dismiss timer; hover pauses it so a reader can finish.
  useEffect(() => {
    if (t.duration <= 0 || paused) return;
    const timer = setTimeout(() => dismissToast(t.id), t.duration);
    return () => clearTimeout(timer);
  }, [t.id, t.duration, paused]);

  const k = KIND[t.kind];

  return (
    <div
      className="aug-anim-fade"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      style={{
        pointerEvents: "auto",
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
        width: 340,
        maxWidth: "calc(100vw - 32px)",
        padding: "11px 10px 11px 12px",
        background: "var(--bg-1)",
        border: "1px solid var(--b2)",
        borderLeft: `2px solid ${k.color}`,
        borderRadius: "var(--r3)",
        boxShadow: "0 8px 24px rgba(0,0,0,.28)",
      }}
    >
      <span
        aria-hidden
        style={{ color: k.color, fontSize: 13, lineHeight: "18px", fontFamily: "var(--font-mono)", flex: "0 0 auto" }}
      >
        {k.glyph}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="aug-fs-sm" style={{ color: "var(--t2)", fontWeight: 500, overflowWrap: "anywhere" }}>
          {t.title}
        </div>
        {t.description && (
          <div className="aug-fs-xs" style={{ color: "var(--t4)", marginTop: 2, overflowWrap: "anywhere" }}>
            {t.description}
          </div>
        )}
      </div>
      <Button
        variant="ghost"
        size="icon-xs"
        aria-label="Dismiss notification"
        onClick={() => dismissToast(t.id)}
        style={{ flex: "0 0 auto", marginTop: -2, marginRight: -2, color: "var(--t4)", fontSize: 12, lineHeight: 1 }}
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
        <ToastRow key={t.id} t={t} />
      ))}
    </div>,
    document.body,
  );
}
