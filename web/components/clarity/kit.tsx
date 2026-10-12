"use client";

/**
 * The one kit a screen redone to CLARITY is built from (`aughor-v2/CLARITY.md`): the page, a card on the ground, a
 * small uppercase section label with its meta at the right, a fact as a chip, a figure (label · value · one muted
 * line), the amber "Needs you" card and its rows, a bar, bars by category, columns over time, and the one muted line
 * an empty section is.
 *
 * Home drew these first, inside `home/HomeDesk.tsx`. Security & Audit, Monitors, Agent Ops' Overview, Now and the
 * Inbox share them from here, so they read as one product and like Home (two kits were made the same day and are
 * one here). Nothing here fetches or decides — it only lays out.
 */
import { Children, type CSSProperties, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";

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
export function Page({ children, testId }: { children: ReactNode; testId?: string }) {
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

const HUE: Record<"green" | "amber" | "red" | "grey" | "blue", string> = {
  green: "var(--grn3)", amber: "var(--amb3)", red: "var(--red3)", grey: "var(--chart-deemph)", blue: "var(--blue3)",
};

/** A small round mark before a name: running, paused, proposed — a state by its `hue` (INSTRUMENT §3), or a series by
 *  its `color`. Colour carries the state; the title names it. */
export function Dot({ color, hue, title }: { color?: string; hue?: keyof typeof HUE; title?: string }) {
  color = color ?? HUE[hue ?? "grey"];
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
      <span className="aug-fs-display" data-slot="figure-value" data-testid={testId ? `${testId}-value` : undefined} style={{ display: "block",
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
 * Hand it rows and the `empty` line (it is waiting when a row is there), or its body and whether it is `waiting`.
 */
export function NeedsYou({ right, children, testId, waiting, empty }: {
  right?: ReactNode; children: ReactNode; testId?: string; waiting?: boolean; empty?: ReactNode;
}) {
  const rows = empty !== undefined ? Children.toArray(children).filter(Boolean) : null;
  const on = rows ? rows.length > 0 : waiting ?? true;
  return (
    <section aria-label="Needs you" data-testid={testId} data-waiting={on ? "true" : "false"}
      style={on ? { ...CARD, background: "var(--amb1)", borderColor: "var(--amb2)" } : CARD}>
      <Label tone={on ? "amber" : undefined} right={right}>Needs you</Label>
      {rows ? (rows.length ? rows : <Empty>{empty}</Empty>) : children}
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

/** One thing that needs a person, with its buttons on the row — inside the amber "Needs you" card, so it wears none of
 *  its own. */
export function NeedsRow({ title, detail, actions, testId }: {
  title: ReactNode;
  detail?: ReactNode;
  actions?: ReactNode;
  testId?: string;
}) {
  return (
    <div data-testid={testId} style={{ display: "flex", alignItems: "center", gap: 12, padding: "6px 0", flexWrap: "wrap" }}>
      <div style={{ flex: "1 1 260px", minWidth: 0 }}>
        <div className="aug-fs-chrome" style={{ color: "var(--t1)", fontWeight: 500 }}>{title}</div>
        {detail != null && <div className="aug-fs-sm" style={{ color: "var(--t2)", ...ONE_LINE }}>{detail}</div>}
      </div>
      {actions != null && <div style={{ ...ROW, flexWrap: "nowrap" }}>{actions}</div>}
    </div>
  );
}

export interface HBar {
  key: string;
  name: ReactNode;
  /** One muted line under the name. */
  meta?: ReactNode;
  value: number;
  /** What the value reads as: "1.2K". */
  shown: string;
  /** The tooltip on the mark: every bar says what it is. */
  tip: string;
}

/** Counts by category as horizontal bars — one series, one hue, no legend; the figure at the bar's end. */
export function HBars({ bars, testId }: { bars: HBar[]; testId?: string }) {
  const max = Math.max(1, ...bars.map(b => b.value));
  return (
    <div data-testid={testId} style={{ display: "grid", gridTemplateColumns: "minmax(110px, 190px) minmax(0, 1fr) 56px",
      gap: "8px 10px", alignItems: "center" }}>
      {bars.map(b => (
        <div key={b.key} style={{ display: "contents" }}>
          <div className="aug-fs-sm" style={{ minWidth: 0 }}>
            <div style={{ ...ONE_LINE, color: "var(--t1)" }}>{b.name}</div>
            {b.meta != null && <div className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }}>{b.meta}</div>}
          </div>
          <Tooltip content={b.tip}>
            <div role="img" aria-label={b.tip} style={{ height: 10, borderRadius: 5, background: "var(--bg-3)", overflow: "hidden" }}>
              <div style={{ width: `${Math.max(1.5, (b.value / max) * 100)}%`, height: "100%", borderRadius: 5,
                background: "var(--chart-1)" }} />
            </div>
          </Tooltip>
          <div className="aug-fs-sm" style={{ textAlign: "right", color: "var(--t2)", ...NUM }}>{b.shown}</div>
        </div>
      ))}
    </div>
  );
}

export interface Column {
  key: string;
  value: number;
  /** The label under the column; shown for the first, the middle and the last only. */
  label: string;
  tip: string;
}

/** Change over time as columns — one series, a recessive base line, a label on the first, middle and last column. */
export function Columns({ columns, height = 72, testId }: { columns: Column[]; height?: number; testId?: string }) {
  const max = Math.max(1, ...columns.map(c => c.value));
  const shown = new Set([0, Math.floor((columns.length - 1) / 2), columns.length - 1]);
  return (
    <div data-testid={testId}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height, borderBottom: "1px solid var(--chart-grid)" }}>
        {columns.map(c => (
          <Tooltip key={c.key} content={c.tip}>
            <div role="img" aria-label={c.tip} style={{ flex: 1, height: "100%", display: "flex", alignItems: "flex-end" }}>
              <div style={{ width: "100%", height: c.value ? `${Math.max(4, (c.value / max) * 100)}%` : 0,
                borderRadius: "3px 3px 0 0", background: "var(--chart-1)" }} />
            </div>
          </Tooltip>
        ))}
      </div>
      <div className="aug-fs-xs" style={{ display: "flex", gap: 4, marginTop: 4, ...MUTED }}>
        {columns.map((c, i) => (
          <span key={c.key} style={{ flex: 1, textAlign: "center", whiteSpace: "nowrap", visibility: shown.has(i) ? "visible" : "hidden" }}>
            {c.label}
          </span>
        ))}
      </div>
    </div>
  );
}
