"use client";

/**
 * The pieces a screen redone to `aughor-v2/CLARITY.md` is built from: cards on the ground, a row of figures, a
 * "Needs you" band, small uppercase section labels, facts as chips, and bars for a distribution. Home drew its own
 * copies first (`components/home/HomeDesk.tsx`); the Operations screens share these.
 */
import type { CSSProperties, ReactNode } from "react";

import { Tooltip } from "@/components/ui/tooltip";

/** A card on the ground: the panel fill, no shadow, the hairline only in light (where a white card would vanish). */
export const CARD: CSSProperties = {
  background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "12px 14px", minWidth: 0,
};
export const MUTED: CSSProperties = { color: "var(--t3)" };
export const ONE_LINE: CSSProperties = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 };
export const ROW: CSSProperties = { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" };
const NUM: CSSProperties = { fontVariantNumeric: "tabular-nums" };

/** The page a redone screen scrolls: figures, Needs you, the picture, the list — 14px apart. */
export function Page({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
      <div style={{ padding: "14px 20px 28px", display: "flex", flexDirection: "column", gap: 14, maxWidth: 1180 }}>
        {children}
      </div>
    </div>
  );
}

/** A section's small uppercase label, with what it says about itself at its right end. */
export function Label({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, color: "var(--t3)",
      textTransform: "uppercase", letterSpacing: ".06em", minHeight: 18 }}>
      {children}
      {right != null && right !== false && (
        <span style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0, display: "inline-flex", alignItems: "center",
          gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>{right}</span>
      )}
    </div>
  );
}

export type Tone = "plain" | "up" | "down" | "amber";
const TONE: Record<Tone, CSSProperties> = {
  plain: { background: "var(--bg-3)", color: "var(--t2)", border: "1px solid var(--b1)" },
  up: { background: "var(--grn1)", color: "var(--grn4)", border: "1px solid transparent" },
  down: { background: "var(--red1)", color: "var(--red4)", border: "1px solid transparent" },
  amber: { background: "var(--amb1)", color: "var(--amb4)", border: "1px solid transparent" },
};

/** A fact as a chip: a schedule, a channel, a caveat — a few words, the long form on hover. */
export function Chip({ tone = "plain", title, children, testId }: { tone?: Tone; title?: string; children: ReactNode; testId?: string }) {
  return (
    <span className="aug-fs-xs" title={title} data-testid={testId} style={{ ...TONE[tone], display: "inline-flex", alignItems: "center",
      gap: 5, padding: "1px 8px", borderRadius: "var(--r-pill)", whiteSpace: "nowrap", ...NUM }}>
      {children}
    </span>
  );
}

/** One figure: a muted label, the value large and tabular, one muted line under it. */
export function Figure({ label, value, sub, tone, title, testId }: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  /** Amber when the figure needs a person, red when it is an adverse one; plain otherwise. */
  tone?: "amber" | "red";
  title?: string;
  testId?: string;
}) {
  const color = tone === "amber" ? "var(--amb4)" : tone === "red" ? "var(--red4)" : "var(--t1)";
  return (
    <div style={CARD} data-testid={testId} title={title}>
      <div className="aug-fs-xs" style={MUTED}>{label}</div>
      <div className="aug-fs-display" data-slot="figure-value"
        style={{ color, fontWeight: 600, margin: "4px 0 2px", lineHeight: 1.2, ...NUM }}>{value}</div>
      {sub != null && <div className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }}>{sub}</div>}
    </div>
  );
}

/** The row of three or four figures a screen opens with. */
export function Figures({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 14 }}>
      {children}
    </div>
  );
}

/** One thing that needs a person, in amber, with its buttons on the row. */
export function NeedsRow({ title, detail, actions, testId }: {
  title: ReactNode;
  detail?: ReactNode;
  actions?: ReactNode;
  testId?: string;
}) {
  return (
    <div data-testid={testId} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
      borderRadius: "var(--r3)", background: "var(--amb1)", flexWrap: "wrap" }}>
      <div style={{ flex: "1 1 260px", minWidth: 0 }}>
        <div className="aug-fs-chrome" style={{ color: "var(--t1)", fontWeight: 500 }}>{title}</div>
        {detail != null && <div className="aug-fs-sm" style={{ color: "var(--t2)", ...ONE_LINE }}>{detail}</div>}
      </div>
      {actions != null && <div style={{ ...ROW, flexWrap: "nowrap" }}>{actions}</div>}
    </div>
  );
}

/** "Needs you": its rows together, or — when nothing does — one muted line in a card. */
export function NeedsYou({ children, empty, testId }: { children: ReactNode[]; empty: ReactNode; testId?: string }) {
  const rows = children.filter(Boolean);
  if (rows.length === 0) {
    return (
      <section aria-label="Needs you" data-testid={testId} style={CARD}>
        <Label>Needs you</Label>
        <div className="aug-fs-sm" style={MUTED}>{empty}</div>
      </section>
    );
  }
  return (
    <section aria-label="Needs you" data-testid={testId} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {rows}
    </section>
  );
}

/** A small dot that names a state by its hue (INSTRUMENT §3): passed, needs a person, adverse, or plain noise. */
export function Dot({ hue, title }: { hue: "green" | "amber" | "red" | "grey" | "blue"; title?: string }) {
  const bg = hue === "green" ? "var(--grn3)" : hue === "amber" ? "var(--amb3)" : hue === "red" ? "var(--red3)"
    : hue === "blue" ? "var(--blue3)" : "var(--chart-deemph)";
  return <span title={title} aria-hidden style={{ width: 7, height: 7, borderRadius: "var(--r-pill)", background: bg, flex: "none",
    display: "inline-block" }} />;
}

export interface Bar {
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
export function HBars({ bars, testId }: { bars: Bar[]; testId?: string }) {
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
