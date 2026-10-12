"use client";

/**
 * The few pieces the Semantic Layer's tabs share beyond the CLARITY kit (`components/clarity/kit.tsx`): the one Tools
 * menu a view has, a block of SQL, the small heading over a group of rows, and a row of a list that opens in place.
 *
 * The Tools menu is the Catalog's (`catalog/CatalogTools.tsx`), drawn here without that file's imports — it carries
 * the sample grid and the connector tools, which this screen never shows — and with an item that can be shown
 * disabled, saying why.
 */
import { DropdownMenu } from "@radix-ui/themes";
import type { CSSProperties, ReactNode } from "react";

import { MUTED, NUM, RULE } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";

export interface ToolItem {
  label: string;
  onSelect: () => void;
  title?: string;
  danger?: boolean;
  /** A rule above it — the destructive one sits apart. */
  apart?: boolean;
  hidden?: boolean;
  /** Shown, but not offered: the label says why. */
  disabled?: boolean;
  testId?: string;
}

/** Every tool a view has, in one menu (CLARITY §3: "Tools in one menu"). */
export function ToolsMenu({ items, testId, label = "Tools" }: { items: ToolItem[]; testId?: string; label?: string }) {
  const shown = items.filter(i => !i.hidden);
  if (!shown.length) return null;
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        <Button variant="ghost" size="xs" data-testid={testId}>
          {label} <Icon name="chevd" size={12} />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Content size="1" align="end">
        {shown.map((i, n) => (
          <span key={`${n}-${i.label}`} style={{ display: "contents" }}>
            {i.apart && n > 0 && <DropdownMenu.Separator />}
            <DropdownMenu.Item onSelect={i.onSelect} title={i.title} color={i.danger ? "red" : undefined}
              disabled={i.disabled} data-testid={i.testId}>
              {i.label}
            </DropdownMenu.Item>
          </span>
        ))}
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  );
}

/** A metric's SQL, or any statement, as code: mono, wrapped, on the panel below the card. */
export function Sql({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <pre className="aug-fs-xs" data-testid={testId} style={{ margin: 0, padding: "8px 10px", borderRadius: "var(--r2)",
      background: "var(--code-bg)", color: "var(--t2)", fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap",
      wordBreak: "break-word", maxHeight: 280, overflow: "auto" }}>
      {children}
    </pre>
  );
}

/** The heading over a group of rows inside a card: its name, then how many. Sentence case, so it reads below the
 *  card's own uppercase label and above the rows. */
export function GroupHead({ name, count, right, first }: { name: ReactNode; count: number; right?: ReactNode; first?: boolean }) {
  return (
    <div className="aug-fs-sm" style={{ display: "flex", alignItems: "baseline", gap: 8, padding: first ? "4px 0 6px" : "16px 0 6px",
      color: "var(--t2)", fontWeight: 600 }}>
      {name}
      <span style={{ ...MUTED, ...NUM, fontWeight: 400 }}>{count}</span>
      {right != null && <span style={{ marginLeft: "auto", fontWeight: 400 }}>{right}</span>}
    </div>
  );
}

/** A row that opens in place: the whole row is the door, tinted while it is open. */
export function rowButtonStyle(open: boolean, grid: CSSProperties): CSSProperties {
  return {
    ...grid, ...RULE, width: "100%", height: "auto", margin: 0, padding: "8px 6px", borderRadius: 0, textAlign: "left",
    whiteSpace: "normal", fontWeight: 400, color: "var(--t1)", alignItems: "center",
    background: open ? "var(--bg-sel)" : undefined,
  };
}

/** A line that opens a folded group or list — "Retired · 2 ›". */
export function FoldLine({ open, onToggle, children, testId }: {
  open: boolean; onToggle: () => void; children: ReactNode; testId?: string;
}) {
  return (
    <Button variant="ghost" size="xs" onClick={onToggle} aria-expanded={open} data-testid={testId}
      style={{ marginTop: 10, color: "var(--t2)" }}>
      {children} <Icon name={open ? "chevd" : "chevr"} size={12} />
    </Button>
  );
}
