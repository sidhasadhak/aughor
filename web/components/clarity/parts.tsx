"use client";

/**
 * The parts a screen redone to CLARITY is built from (`aughor-v2/CLARITY.md`): a card on the ground, a small
 * uppercase section label with its meta at the right, a fact as a chip, a figure (label · value · one muted line),
 * the amber "Needs you" card, a bar, and the one muted line an empty section is.
 *
 * Home drew these first, inside `home/HomeDesk.tsx`; Agent Ops' Overview, Now and the Inbox share them from here
 * so the three look like one product and like Home. Nothing here fetches or decides — it only lays out.
 */
import type { CSSProperties, ReactNode } from "react";

import { Button } from "@/components/ui/button";

/** A card on the ground: the panel fill, no shadow, the edge only where the skin needs one (light). */
export const CARD: CSSProperties = {
  background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "12px 14px",
  minWidth: 0,
};

export const MUTED: CSSProperties = { color: "var(--t3)" };
export const ONE_LINE: CSSProperties = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 };
export const ROW: CSSProperties = { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" };
export const NUM: CSSProperties = { fontVariantNumeric: "tabular-nums" };

/** The page a redone screen sits on: a column of cards, 14px apart, at the mockups' width. */
export function Desk({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: "auto", background: "var(--bg-0)" }}>
      <div data-testid={testId} style={{ display: "flex", flexDirection: "column", gap: 14, padding: "16px 22px 28px",
        maxWidth: 1180 }}>
        {children}
      </div>
    </div>
  );
}

/** A section's small uppercase label, with what it counts (or its one tool) at its right end. */
export function Label({ children, right, tone }: { children: ReactNode; right?: ReactNode; tone?: "amber" }) {
  return (
    <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, minHeight: 20,
      color: tone === "amber" ? "var(--amb4)" : "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>
      {children}
      {right != null && right !== false && (
        <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 8, textTransform: "none",
          letterSpacing: 0, color: "var(--t3)" }}>{right}</span>
      )}
    </div>
  );
}

/** A card with its label — the shape nearly every section takes. */
export function Card({ label, right, children, testId, style, ariaLabel }: {
  label: ReactNode; right?: ReactNode; children: ReactNode; testId?: string; style?: CSSProperties; ariaLabel?: string;
}) {
  return (
    <section aria-label={ariaLabel ?? (typeof label === "string" ? label : undefined)} data-testid={testId}
      style={{ ...CARD, ...style }}>
      <Label right={right}>{label}</Label>
      {children}
    </section>
  );
}

export type Tone = "plain" | "up" | "down" | "amber" | "violet" | "accent";
const TONE: Record<Tone, CSSProperties> = {
  plain: { background: "var(--bg-3)", color: "var(--t2)", border: "1px solid var(--b1)" },
  up: { background: "var(--grn1)", color: "var(--grn4)", border: "1px solid transparent" },
  down: { background: "var(--red1)", color: "var(--red4)", border: "1px solid transparent" },
  amber: { background: "var(--amb1)", color: "var(--amb4)", border: "1px solid transparent" },
  violet: { background: "var(--vio1)", color: "var(--vio4)", border: "1px solid transparent" },
  accent: { background: "var(--blue1)", color: "var(--blue4)", border: "1px solid transparent" },
};

/** A fact as a chip: a caveat, a state, a count — said in a few words. */
export function Chip({ tone = "plain", title, children, testId }: {
  tone?: Tone; title?: string; children: ReactNode; testId?: string;
}) {
  return (
    <span className="aug-fs-xs" title={title} data-testid={testId} style={{ ...TONE[tone], display: "inline-flex",
      alignItems: "center", gap: 5, padding: "1px 8px", borderRadius: "var(--r-pill)", whiteSpace: "nowrap", ...NUM }}>
      {children}
    </span>
  );
}

/** A small round mark before a name: running, paused, proposed. Colour carries the state; the title names it. */
export function Dot({ color, title }: { color: string; title?: string }) {
  return (
    <span aria-hidden={title ? undefined : true} role={title ? "img" : undefined} aria-label={title} title={title}
      style={{ width: 7, height: 7, borderRadius: "var(--r-pill)", background: color, flex: "0 0 auto",
        display: "inline-block" }} />
  );
}

/** The row of three or four figures a screen opens on. */
export function Figures({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
      gap: 14 }}>
      {children}
    </div>
  );
}

/**
 * One figure: its label, the value, one muted line. `onOpen` makes the whole card the door to where the number
 * comes from (the label's `title` says so on hover). `tone` colours the value only when it means something:
 * amber — it needs a person; red — an adverse figure.
 */
export function Figure({ label, value, sub, tone, title, onOpen, testId }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: "amber" | "red"; title?: string;
  onOpen?: () => void; testId?: string;
}) {
  const body = (
    <>
      <span className="aug-fs-xs" style={{ ...MUTED, display: "block" }}>{label}</span>
      <span className="aug-fs-display" data-testid={testId ? `${testId}-value` : undefined} style={{ display: "block",
        color: tone === "amber" ? "var(--amb4)" : tone === "red" ? "var(--red4)" : "var(--t1)", fontWeight: 600,
        lineHeight: 1.25, margin: "2px 0", ...NUM }}>{value}</span>
      {sub != null && sub !== false && (
        <span className="aug-fs-xs" style={{ ...MUTED, ...ROW, gap: 6, lineHeight: 1.5 }}>{sub}</span>
      )}
    </>
  );
  if (!onOpen) return <div data-testid={testId} title={title} style={CARD}>{body}</div>;
  return (
    <Button variant="ghost" data-testid={testId} title={title} onClick={onOpen}
      style={{ ...CARD, display: "block", height: "auto", margin: 0, textAlign: "left", whiteSpace: "normal",
        width: "100%", fontWeight: 400, cursor: "pointer" }}>
      {body}
    </Button>
  );
}

/**
 * What needs a person, together, in amber — its buttons sit on the row each one acts on. With nothing waiting it is
 * an ordinary card holding one muted line: amber means a person is needed, so an empty section does not wear it.
 */
export function NeedsYou({ right, children, testId, waiting = true }: {
  right?: ReactNode; children: ReactNode; testId?: string; waiting?: boolean;
}) {
  return (
    <section aria-label="Needs you" data-testid={testId} data-waiting={waiting ? "true" : "false"}
      style={waiting ? { ...CARD, background: "var(--amb1)", borderColor: "var(--amb2)" } : CARD}>
      <Label tone={waiting ? "amber" : undefined} right={right}>Needs you</Label>
      {children}
    </section>
  );
}

/** An empty section: one muted line, in the place the rows would be. */
export function Empty({ children, title }: { children: ReactNode; title?: string }) {
  return <div className="aug-fs-sm" title={title} style={{ ...MUTED, padding: "2px 0" }}>{children}</div>;
}

/** A horizontal bar: a share of a whole, drawn 8px high with a rounded data end. */
export function Bar({ value, max, color = "var(--chart-1)", hatched = false }: {
  value: number; max: number; color?: string; hatched?: boolean;
}) {
  const w = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <span aria-hidden style={{ display: "block", height: 8, borderRadius: 4, background: "var(--bg-3)", overflow: "hidden",
      minWidth: 40 }}>
      <i style={{ display: "block", height: "100%", width: `${w}%`, borderRadius: 4,
        background: hatched ? "repeating-linear-gradient(135deg, var(--chart-deemph) 0 4px, transparent 4px 7px)" : color }} />
    </span>
  );
}

/** A rule between rows of a list. */
export const RULE: CSSProperties = { borderTop: "1px solid var(--b0)" };
