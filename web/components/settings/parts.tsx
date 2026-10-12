"use client";

/**
 * What Settings' sections share, on top of the one kit (`clarity/kit.tsx`, which this file only uses): the column a
 * section's cards stand in, two related cards on one row, a labelled field, the *Details* fold, the line a Save button
 * stands on, and the one Tools menu. A settings form is still a form — these lay its controls out the way CLARITY
 * says a screen is laid out; none of them fetches or writes.
 */
import { DropdownMenu } from "@radix-ui/themes";
import { useState, type CSSProperties, type ReactNode } from "react";

import { MUTED, ROW } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { formatCount } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";

/** The column a section's cards stand in, 14px apart, across the whole width (the Settings screen scrolls and pads
 *  it already, so this is not the kit's `Page`). */
export function Stack({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} style={{ display: "flex", flexDirection: "column", gap: 14, width: "100%", minWidth: 0 }}>
      {children}
    </div>
  );
}

/** Two related cards side by side; one column when the screen is narrow. */
export function Pair({ children, min = 340 }: { children: ReactNode; min?: number }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fit, minmax(min(100%, ${min}px), 1fr))`, gap: 14,
      alignItems: "start" }}>
      {children}
    </div>
  );
}

/** Fields two (or more) to a row. */
export const FIELDS: CSSProperties = {
  display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 200px), 1fr))", gap: 12,
};

/** A field's muted label above its control. */
export function Field({ label, htmlFor, children, meta }: {
  label: ReactNode; htmlFor?: string; children: ReactNode; meta?: ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
      <label className="aug-fs-xs" htmlFor={htmlFor} style={{ ...MUTED, ...ROW, gap: 6 }}>{label}{meta}</label>
      {children}
    </div>
  );
}

/** One muted line under a card's controls. */
export function Note({ children, tone, testId }: { children: ReactNode; tone?: "amber" | "red" | "green"; testId?: string }) {
  const color = tone === "amber" ? "var(--amb4)" : tone === "red" ? "var(--red4)" : tone === "green" ? "var(--grn4)" : "var(--t3)";
  return <div className="aug-fs-xs" data-testid={testId} style={{ color, lineHeight: 1.5, marginTop: 8 }}>{children}</div>;
}

/** Long help behind *Details*: a quiet button that opens what most readers do not need. */
export function Details({ children, label = "Details", testId }: { children: ReactNode; label?: string; testId?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="xs" variant="ghost" aria-expanded={open} data-testid={testId} onClick={() => setOpen(o => !o)}
        style={{ alignSelf: "flex-start" }}>
        {label} <Icon name={open ? "chevu" : "chevd"} size={12} />
      </Button>
      {open && (
        <div className="aug-fs-xs" style={{ color: "var(--t2)", lineHeight: 1.55, marginTop: 4, paddingLeft: 8,
          borderLeft: "1px solid var(--b1)" }}>
          {children}
        </div>
      )}
    </>
  );
}

/** The line a Save button stands on: the button, what it saved or why it could not. */
export function SaveLine({ children, saved, error, savedText = "Saved ✓", testId, errorTestId }: {
  children: ReactNode; saved?: boolean; error?: string; savedText?: ReactNode; testId?: string; errorTestId?: string;
}) {
  return (
    <div data-testid={testId} style={{ ...ROW, gap: 10, marginTop: 12 }}>
      {children}
      {saved && <span className="aug-fs-xs" style={{ color: "var(--grn4)" }}>{savedText}</span>}
      {error && <span className="aug-fs-xs" role="alert" data-testid={errorTestId} style={{ color: "var(--red4)" }}>{error}</span>}
    </div>
  );
}

export interface Tool {
  label: string;
  onSelect: () => void;
  title?: string;
  disabled?: boolean;
  testId?: string;
}

/** Every tool a card has, in one menu (CLARITY §3: "Tools in one menu"). */
export function ToolsMenu({ tools, testId }: { tools: Tool[]; testId?: string }) {
  if (!tools.length) return null;
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        <Button variant="ghost" size="xs" data-testid={testId}>Tools <Icon name="chevd" size={12} /></Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Content size="1" align="end">
        {withUniqueKeys(tools, t => t.label).map(([key, t]) => (
          <DropdownMenu.Item key={key} onSelect={t.onSelect} title={t.title} disabled={t.disabled} data-testid={t.testId}>
            {t.label}
          </DropdownMenu.Item>
        ))}
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  );
}

/** Bring a card into view and put the cursor in its first matching field — a "Needs you" row's button uses it to
 *  take a person to the one control that resolves the row, which lives once, in its card. */
export function goTo(cardId: string, focus?: string): void {
  if (typeof document === "undefined") return;
  const card = document.getElementById(cardId);
  card?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  const target = focus ? card?.querySelector<HTMLElement>(focus) : null;
  target?.focus?.({ preventScroll: true });
}

/** "1 thing" / "2 things". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${formatCount(n)} ${n === 1 ? one : many}`;
}
