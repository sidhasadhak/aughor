"use client";

/**
 * DE-5b (ROADMAP §3.51) — the right-click menu on a result cell.
 *
 * Every entry does one of three things, and says which: puts a phrase into the filter chips
 * (the same chips a typed phrase makes — removable, chainable, honest about the rows it hides),
 * copies the value in a stated form, or opens the value in the viewer. Nothing here re-runs
 * the query, and nothing filters silently: a click lands as a chip the person can see.
 */
import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { NULL_GLYPH, filterPhrase, jsonLiteral, sqlLiteral, type FilterKind } from "@/lib/query/cellMenu";
import type { Cell } from "@/lib/query/resultFilter";

export interface CellMenuTarget {
  x: number;
  y: number;
  /** The VISIBLE column index the menu is about — what the value picker is keyed by. */
  col: number;
  column: string;
  value: Cell;
  /** A header was clicked: the value entries do not apply, the column ones do. */
  header?: boolean;
}

/** A value as the menu names it: short, quoted, never a paragraph. */
function brief(v: Cell): string {
  if (v === null) return NULL_GLYPH;
  const s = String(v);
  return s.length > 24 ? `"${s.slice(0, 23)}…"` : `"${s}"`;
}

export function CellMenu({
  target,
  canFilter,
  onFilter,
  onPickValues,
  onOpenValue,
  onClose,
}: {
  target: CellMenuTarget;
  /** False when the grid is transposed: its columns are not the result's, so a filter on them
   *  would name a column the chip bar does not have. */
  canFilter: boolean;
  onFilter: (phrase: string) => void;
  onPickValues: () => void;
  onOpenValue: () => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const copy = (text: string) => {
    navigator.clipboard?.writeText(text).catch(() => {});
    onClose();
  };
  const filter = (kind: FilterKind) => { onFilter(filterPhrase(target.column, target.value, kind)); onClose(); };
  const item = (label: string, onClick: () => void, icon?: Parameters<typeof Icon>[0]["name"], testid?: string) => (
    <Button variant="ghost" size="xs" className="aug-fs-ui" data-testid={testid}
      style={{ width: "100%", justifyContent: "flex-start" }} onClick={onClick}>
      {icon && <Icon name={icon} size={12} />}{label}
    </Button>
  );
  const rule = <div style={{ borderTop: "1px solid var(--b0)", margin: "3px 0" }} />;
  const isNull = target.value === null;

  // Kept inside the viewport: a menu opened near the right or bottom edge is moved in, not clipped.
  const left = Math.min(target.x, (typeof window !== "undefined" ? window.innerWidth : 1e9) - 260);
  const top = Math.min(target.y, (typeof window !== "undefined" ? window.innerHeight : 1e9) - 320);

  return (
    <>
      <div style={{ position: "fixed", inset: 0, zIndex: 30 }} onClick={onClose} onContextMenu={e => { e.preventDefault(); onClose(); }} />
      <div role="menu" data-testid="cell-menu" className="aug-fs-ui" style={{
        position: "fixed", left, top, zIndex: 31, minWidth: 240, padding: 5,
        background: "var(--bg-2)", border: "1px solid var(--b2)", borderRadius: "var(--r2)",
        boxShadow: "var(--shadow-md)",
      }}>
        <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "2px 8px 4px", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {target.column}{target.header ? "" : ` · ${brief(target.value)}`}
        </div>
        {canFilter && !target.header && (
          <>
            {item(isNull ? "Only null rows" : "Filter to this value", () => filter("is"), "filter", "cell-filter-is")}
            {item(isNull ? "Only non-null rows" : "Exclude this value", () => filter("isnot"), "filter", "cell-filter-isnot")}
            {!isNull && item("Only null rows", () => filter("null"), undefined, "cell-filter-null")}
            {!isNull && item("Only non-null rows", () => filter("notnull"), undefined, "cell-filter-notnull")}
          </>
        )}
        {canFilter && item(`Pick values in ${target.column}…`, () => { onPickValues(); onClose(); }, "list", "cell-pick-values")}
        {canFilter && rule}
        {!target.header && (
          <>
            {item("Copy value", () => copy(target.value === null ? "" : String(target.value)), "copy", "cell-copy")}
            {item("Copy as SQL literal", () => copy(sqlLiteral(target.value)), "sql", "cell-copy-sql")}
            {item("Copy as JSON", () => copy(jsonLiteral(target.value)), "json", "cell-copy-json")}
            {rule}
            {item("Open value", () => { onOpenValue(); onClose(); }, "text", "cell-open")}
          </>
        )}
      </div>
    </>
  );
}
