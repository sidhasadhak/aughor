"use client";

/**
 * The drawer a page opens beside itself, and the pieces its content is made of.
 *
 * The inspector reads a cited record in it (`Inspector.tsx`); a measured figure opens to its
 * trend in it (`brief/MetricDetail.tsx`). One shell, so the two read as the same thing: a small
 * label above each part, every cited thing a bordered box of its own, the page left where it was.
 */
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";

export function Beside({ kind, top = 0, onClose, focusKey, testId, foot, children }: {
  /** What is open, in one word: "Claim", "Metric". */
  kind: string;
  /** How far down the drawer starts — under a workspace's tabs, so they stay in reach. */
  top?: number;
  onClose: () => void;
  /** The drawer takes the keyboard as it opens, and again when this changes. */
  focusKey: string;
  testId: string;
  foot: React.ReactNode;
  children: React.ReactNode;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { closeRef.current?.focus(); }, [focusKey]);
  return (
    <aside className="aug-beside" role="complementary" aria-label={`${kind}, opened beside the page`}
      data-testid={testId} style={{ top }}>
      <div className="aug-beside-head">
        <span className="aug-label">{kind}</span>
        <span style={{ flex: 1 }} />
        <Button ref={closeRef} size="xs" variant="ghost" onClick={onClose} aria-label="Close" title="Close (Esc)">
          <Icon name="close" size={14} />
        </Button>
      </div>
      <div className="aug-beside-body">{children}</div>
      <div className="aug-beside-foot">{foot}</div>
    </aside>
  );
}

/** Esc puts the drawer away while it is open. */
export function useEscape(open: boolean, close: () => void) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);
}

export function Part({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="aug-beside-part">
      <div className="aug-label">{label}</div>
      {children}
    </div>
  );
}

/** A cited thing as a box of its own; with `onOpen`, the whole box opens it. */
export function Box({ children, foot, onOpen, chosen }: {
  children: React.ReactNode; foot?: React.ReactNode; onOpen?: () => void; chosen?: boolean;
}) {
  const body = (
    <>
      <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>{children}</span>
      {foot && <span className="aug-item-foot aug-fs-sm">{foot}</span>}
    </>
  );
  return onOpen
    ? <Button variant="ghost" className="aug-beside-box aug-beside-link" onClick={onOpen}>{body}</Button>
    : <div className="aug-beside-box" data-chosen={chosen || undefined}>{body}</div>;
}

export function Title({ children, marks }: { children: React.ReactNode; marks?: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <p className="aug-beside-title">{children}</p>
      {marks && <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>{marks}</div>}
    </div>
  );
}
