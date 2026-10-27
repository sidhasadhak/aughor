"use client";

/**
 * A sheet's grid (SH-2; mockup screens 3, 4 and 6): 30px rows, each column headed by its kind and what it holds, a
 * cell edited in place by its kind, the selected cell's story in the bar above the grid (imported from file row N, or
 * set by whom and when — a click selects, nothing opens over the rows), the row opened as a record, and the totals of
 * the rows shown at the foot.
 *
 * Built on TanStack Virtual, the house grid's own windowing (`components/query/ResultsGrid.tsx`): only the rows in
 * sight are mounted, and they are read a block at a time as they come into sight (`useRowBlocks`), so the scroll bar is
 * the whole view. Sorting, filtering and the totals are the server's — over the whole view — so the grid only lays out
 * and edits. The cells, the header, the foot and a cell's story are shared with the grouped grid (`SheetGroups`).
 */
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, useCallback, useEffect, useRef, useState,
} from "react";

import { Chip, MUTED, NUM } from "@/components/clarity/kit";
import { useCloseOutside } from "@/components/sheets/useCloseOutside";
import type { RowBlocks } from "@/components/sheets/useRowBlocks";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon, type IconName } from "@/components/ui/icon";
import { formatCount, formatTimestamp } from "@/lib/format";
import {
  KIND_LABEL, showValue, totalWords, typedValue, who, type ColumnTotals, type Kind, type RuleTone, type Sheet,
  type SheetColumn, type SheetRule,
} from "@/lib/sheets";

export const ROW_HEIGHT = 30;
export const NUMBER_WIDTH = 64;

export const KIND_ICON: Record<Kind, IconName> = {
  text: "text", number: "num", money: "num", date: "date", datetime: "time", choice: "list", yesno: "bool",
  email: "message", link: "link",
};

const WIDTH: Record<Kind, number> = {
  text: 160, number: 110, money: 130, date: 130, datetime: 170, choice: 140, yesno: 90, email: 200, link: 150,
};

/** A choice's chip colour, from its place among the column's values — the same value, the same colour, every time. */
export const CHIP_TONES = ["accent", "up", "amber", "violet", "down", "plain"] as const;

/** A rule's mark, at the start of each row it marks. */
export const RULE_COLOR: Record<RuleTone, string> = {
  amber: "var(--amb3)", red: "var(--red3)", green: "var(--grn3)", blue: "var(--blue3)", violet: "var(--vio3)",
};

export function choiceTone(column: Pick<SheetColumn, "choices">, value: unknown): (typeof CHIP_TONES)[number] {
  const at = Math.max(0, column.choices.indexOf(String(value)));
  return CHIP_TONES[at % CHIP_TONES.length];
}

/** A column's width: its kind's, or its name's — with room for the tag a derived column carries and its ⓘ. */
export function width(c: SheetColumn): number {
  const extra = (c.role !== "stored" ? 58 : 0) + (c.description || c.role !== "stored" ? 20 : 0) + (c.made_by ? 66 : 0);
  return Math.min(320, Math.max(WIDTH[c.kind] ?? 160, Math.min(260, c.name.length * 8 + 44)) + extra);
}

function mark(c: SheetColumn): string {
  if (c.role === "computed") return "computed";
  if (c.role === "lookup") return "linked";
  if (c.role === "total") return "total";
  return "";
}

const ELLIPSIS: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 };

/** The grid's lines. Each cell draws its own right and bottom line inside its 30px: a row drawn with a line below it
 *  would be 31px tall in a 30px place, and the next row would paint over the line. */
export const LINE = "1px solid var(--b2)";

export function cellStyle(c: SheetColumn): CSSProperties {
  const numeric = c.kind === "number" || c.kind === "money";
  return {
    width: width(c), minWidth: width(c), maxWidth: width(c), padding: "0 8px", overflow: "hidden",
    borderRight: LINE, borderBottom: LINE, display: "flex", alignItems: "center",
    justifyContent: numeric ? "flex-end" : "flex-start", height: ROW_HEIGHT, ...(numeric ? NUM : {}),
  };
}

/** A value as its column shows it; a long one ends in "…" and is whole on hover. */
export function CellValue({ column, value }: { column: SheetColumn; value: unknown }) {
  if (value === null || value === undefined || value === "") return <span style={{ color: "var(--t4)" }}>—</span>;
  if (column.kind === "choice") return <Chip tone={choiceTone(column, value)}>{String(value)}</Chip>;
  if (column.kind === "yesno") return <Checkbox checked={value === true || value === "true"} disabled aria-label={column.name} />;
  const text = column.kind === "link" ? String(value) : showValue(value, column);
  return (
    <span title={String(value)} style={{ ...ELLIPSIS, color: column.kind === "link" ? "var(--blue4)" : undefined }}>
      {text}
    </span>
  );
}

/** What a derived or described column is, said where its header is. */
export function aboutColumn(sheet: Sheet, c: SheetColumn): string[] {
  const nameOf = (id: string) => sheet.columns.find(x => x.id === id)?.name ?? id;
  const lines = [`${KIND_LABEL[c.kind]}${c.role !== "stored" ? ` · ${mark(c)}` : ""}`];
  if (c.role === "computed") lines.push(`Computed from ${c.expression}.`);
  if (c.role === "lookup") lines.push(`Read from another sheet through ${nameOf(c.via)}; it follows that sheet.`);
  if (c.role === "total" && !c.description) lines.push(`The ${c.how} of another sheet's rows per ${nameOf(c.by)}.`);
  if (c.description) lines.push(c.description.charAt(0).toUpperCase() + c.description.slice(1)
    + (c.description.endsWith(".") ? "" : "."));
  if (c.made_by) lines.push("Proposed by the assistant, applied by a person.");
  return lines;
}

/** The header: each column's kind, name and marks — and what a derived or described column is, a click away. A click on
 *  a column's name sorts by it: lowest first, then highest first, then back to the sheet's own order. */
export function GridHeader({ sheet, shown, sort = [], onSort }: {
  sheet: Sheet; shown: SheetColumn[]; sort?: { column: string; desc: boolean }[]; onSort?: (column: string) => void;
}) {
  const [about, setAbout] = useState("");
  const aboutRef = useRef<HTMLDivElement>(null);
  const closeAbout = useCallback(() => setAbout(""), []);
  useCloseOutside(aboutRef, closeAbout);
  const at = (id: string) => NUMBER_WIDTH + shown.slice(0, shown.findIndex(c => c.id === id)).reduce((n, c) => n + width(c), 0);
  const open = shown.find(c => c.id === about);
  const span = NUMBER_WIDTH + shown.reduce((n, c) => n + width(c), 0);
  return (
    <div role="row" className="aug-fs-xs" style={{ display: "flex", position: "sticky", top: 0, zIndex: 3,
      background: "var(--bg-2)", color: "var(--t2)" }}>
      <div style={{ width: NUMBER_WIDTH, minWidth: NUMBER_WIDTH, height: ROW_HEIGHT, borderRight: LINE, borderBottom: LINE }} />
      {shown.map(c => {
        const by = sort[0]?.column === c.id ? sort[0] : undefined;
        return (
        <div key={c.id} role="columnheader" aria-label={`${c.name} · ${KIND_LABEL[c.kind]}`}
          aria-sort={by ? (by.desc ? "descending" : "ascending") : "none"}
          style={{ ...cellStyle(c), justifyContent: "flex-start", gap: 6, fontWeight: 600 }}>
          <Button variant="ghost" size="xs" disabled={!onSort} onClick={() => onSort?.(c.id)} className="group"
            title={by ? (by.desc ? "Highest first — click for the sheet's order" : "Lowest first — click for highest first")
              : "Sort by this column"}
            // the whole header sorts, as a spreadsheet's does — not only its name (the user: "I still cant sort the
            // sheet"); what explains the column keeps its own button beside it
            style={{ display: "flex", alignItems: "center", justifyContent: "flex-start", gap: 6, minWidth: 0,
              flex: "1 1 auto", alignSelf: "stretch", padding: 0, height: "auto", borderRadius: 0, fontWeight: 600,
              color: c.role === "lookup" ? "var(--blue4)" : "var(--t2)" }}>
            <span style={MUTED}><Icon name={KIND_ICON[c.kind]} size={12} /></span>
            <span style={ELLIPSIS}>{c.name}</span>
            {/* the sort, at the header's end: the bars widest first for highest first, narrowest first for lowest first —
                a column not sorted by shows it faintly where the pointer is, so it is seen to sort */}
            <span className={by ? undefined : "opacity-0 group-hover:opacity-60 transition-opacity"}
              style={{ marginLeft: "auto", display: "flex", color: by ? "var(--blue4)" : "var(--t3)" }}>
              <Icon name={by?.desc ? "sortdesc" : "sortasc"} size={14} />
            </span>
          </Button>
          {mark(c) && <Chip tone="accent">{mark(c)}</Chip>}
          {c.made_by && <Chip tone="violet" title="Proposed by the assistant, applied by a person">proposed</Chip>}
          {(c.description || c.role !== "stored") && (
            <Button variant="ghost" size="icon-xs" aria-label={`What ${c.name} is`} aria-expanded={about === c.id}
              onClick={() => setAbout(about === c.id ? "" : c.id)} style={{ marginLeft: "auto", ...MUTED }}>
              <Icon name="info" size={11} />
            </Button>
          )}
        </div>
        );
      })}
      {open && (
        <div ref={aboutRef} role="dialog" aria-label={`What ${open.name} is`} className="aug-fs-sm" style={{ position: "absolute",
          top: ROW_HEIGHT + 2, left: Math.max(0, Math.min(at(open.id) - 40, span - 304)), width: 300, zIndex: 12,
          background: "var(--bg-2)",
          border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "8px 10px", display: "flex",
          flexDirection: "column", gap: 4, fontWeight: 400, color: "var(--t1)" }}>
          <b>{open.name}</b>
          {aboutColumn(sheet, open).map((line, i) => (
            // the lines of one column's account, in their order
            <span key={i} className={i === 0 ? "aug-fs-xs" : undefined} style={i === 0 ? MUTED : undefined}>{line}</span>
          ))}
        </div>
      )}
    </div>
  );
}

/** The foot: each column's totals over every row the view shows — never only the rows in sight. */
export function GridFoot({ shown, totals, rows, label = "total" }: {
  shown: SheetColumn[]; totals: Record<string, ColumnTotals>; rows: number; label?: string;
}) {
  return (
    <div role="row" className="aug-fs-xs" style={{ display: "flex", position: "sticky", bottom: 0, zIndex: 2,
      background: "var(--bg-2)", borderTop: "1px solid var(--b1)", color: "var(--t2)" }}
      title="Totals are over every row this view shows, not only the rows in sight">
      <div style={{ width: NUMBER_WIDTH, minWidth: NUMBER_WIDTH, height: ROW_HEIGHT, padding: "0 8px", display: "flex",
        alignItems: "center", borderRight: LINE, ...MUTED }}>{label}</div>
      {shown.map(c => (
        <div key={c.id} style={{ ...cellStyle(c), justifyContent: "flex-start" }}>
          <span style={ELLIPSIS} title={totalWords(totals[c.id], c, rows)}>{totalWords(totals[c.id], c, rows)}</span>
        </div>
      ))}
    </div>
  );
}

/** A row's number, with the rules marking it as a bar at its start, and the button that opens it as a record. */
export function RowNumber({ row, marks, rules, onOpen }: {
  row: number; marks: string[]; rules: SheetRule[]; onOpen: () => void;
}) {
  const marking = rules.filter(r => marks.includes(r.id));
  return (
    <div className="aug-fs-xs" style={{ width: NUMBER_WIDTH, minWidth: NUMBER_WIDTH, height: ROW_HEIGHT, display: "flex",
      alignItems: "center", justifyContent: "space-between", padding: "0 4px 0 8px", ...MUTED, ...NUM,
      borderRight: LINE, borderBottom: LINE, position: "relative",
      boxShadow: marking.length ? `inset 3px 0 0 ${RULE_COLOR[marking[0].tone]}` : undefined }}
      title={marking.length ? `row ${row} · marked: ${marking.map(r => r.name).join(", ")}` : `row ${row} of the sheet`}>
      {row}
      <Button variant="ghost" size="icon-xs" aria-label={`Open row ${row}`} onClick={onOpen}>
        <Icon name="expand" size={11} />
      </Button>
    </div>
  );
}

/** Where a cell's value came from, said from what the grid already holds — never a read per click. The whole history
 *  of a row's values is its record's (Open row). */
export function cellOrigin(sheet: Sheet, c: SheetColumn, row: number,
  set?: { by: string; at: string; version: number }): string {
  if (set) {
    return `Set by ${who(set.by, sheet.me)} · ${formatTimestamp(set.at, "short")}`
      + (set.version > 1 ? ` · changed ${formatCount(set.version)} times` : "");
  }
  if (c.role === "computed") return `Computed from ${c.expression}`;
  if (c.role === "lookup") return `Read from another sheet through ${sheet.columns.find(x => x.id === c.via)?.name ?? "a link"}`;
  if (c.role === "total") {
    return c.description ? c.description.charAt(0).toUpperCase() + c.description.slice(1) : "A total of another sheet's rows";
  }
  if (row <= sheet.source.rows && c.source) {
    return sheet.source.kind === "file" ? `Imported from ${sheet.source.file}, row ${formatCount(row)} · not changed since`
      : `Kept from a query's rows, row ${formatCount(row)} · not changed since`;
  }
  return row > sheet.source.rows ? "Typed in" : "A column added in the sheet";
}

export interface EditResult { ok: boolean; error?: string }

/** A selected cell: its row, its column, and — in the flat grid — its place among the view's rows. */
export interface Selected { row: number; column: string; index?: number }

/** A range of cells: from where Shift began to the active cell, in the view's rows and the columns shown. */
export interface Range { rows: [number, number]; cols: [number, number] }

const ARROWS: Record<string, [number, number]> = {
  ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1],
};

/** The range from an anchor to the active cell — null when they are one cell, or when the grid cannot place rows (the
 *  grouped grid, where a range is never more than a cell). */
export function rangeOf(anchor: Selected | null, at: Selected | null, columns: string[]): Range | null {
  if (!anchor || !at || anchor.index === undefined || at.index === undefined) return null;
  const a = columns.indexOf(anchor.column);
  const b = columns.indexOf(at.column);
  if (a < 0 || b < 0) return null;
  const r: Range = { rows: [Math.min(anchor.index, at.index), Math.max(anchor.index, at.index)],
    cols: [Math.min(a, b), Math.max(a, b)] };
  return r.rows[0] === r.rows[1] && r.cols[0] === r.cols[1] ? null : r;
}

/**
 * Selecting cells, editing one, and the cell bar — the same in the flat grid and the grouped one. A click selects one
 * cell, drawn by its border alone; Shift with a click or an arrow selects a range, drawn filled, and the bar counts it
 * (and sums it, where it holds numbers). The bar above the grid says the active cell's value and where it came from,
 * with Change and Open row beside it; nothing opens over the rows. Double-click, Enter or typing edits; Escape leaves;
 * the arrows move (the flat grid); Cmd or Ctrl+C copies the cell or the range.
 */
export function useCellWork({ sheet, editable, columns, onEdit, onOpenRow, valueOf, changedOf, versionOf, rowAt, focus }: {
  sheet: Sheet; editable: boolean;
  /** The columns shown, in order — what a range spans. */
  columns: string[];
  onEdit: (row: number, column: SheetColumn, value: unknown, version: number) => Promise<EditResult>;
  onOpenRow: (row: number) => void;
  valueOf: (row: number, column: string) => unknown;
  changedOf: (row: number, column: string) => { by: string; at: string; version: number } | undefined;
  /** The version a change must name: set, or put back by an undo — never only the cells holding an edit. */
  versionOf: (row: number, column: string) => number;
  /** The flat grid's row at a place in the view, where it has been read — what a range copies and sums. */
  rowAt?: (index: number) => unknown[] | undefined;
  /** Put the keyboard back on the grid — after a click, and once an edit is kept or left. */
  focus: () => void;
}) {
  const [selected, setSelected] = useState<Selected | null>(null);
  const [anchor, setAnchor] = useState<Selected | null>(null);
  const [editing, setEditing] = useState<{ row: number; column: string; text: string; original: string; typed: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [said, setSaid] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  /** Select a cell; with `extend`, keep where the range began and move its other end here. */
  const select = (s: Selected | null, extend = false) => {
    setSelected(s);
    if (!extend || !anchor) setAnchor(s);
    setError(null);
    setSaid(null);
  };
  const range = rangeOf(anchor, selected, columns);
  const inRange = (index: number | undefined, column: string) => {
    if (!range || index === undefined) return false;
    const ci = columns.indexOf(column);
    return index >= range.rows[0] && index <= range.rows[1] && ci >= range.cols[0] && ci <= range.cols[1];
  };

  const save = async (row: number, c: SheetColumn, value: unknown) => {
    setSaving(true);
    const out = await onEdit(row, c, value, versionOf(row, c.id));
    setSaving(false);
    setEditing(null);
    setError(out.ok ? null : out.error ?? "The change was not made.");
    focus();
  };

  const startEdit = (row: number, c: SheetColumn, typed?: string) => {
    if (!editable || c.role !== "stored") return;
    const v = valueOf(row, c.id);
    if (c.kind === "yesno") { void save(row, c, !(v === true || v === "true")); return; }
    const text = v === null || v === undefined ? "" : String(v);
    setAnchor(selected);
    setEditing({ row, column: c.id, text: typed ?? text, original: text, typed: typed !== undefined });
  };

  const cell = (row: number, c: SheetColumn, v: unknown, set: boolean, index?: number) => {
    const isSel = selected?.row === row && selected.column === c.id;
    const filled = !isSel && inRange(index, c.id);
    const isEdit = editing?.row === row && editing.column === c.id;
    return (
      <div key={c.id} role="gridcell" aria-selected={isSel || filled}
        onClick={e => { if (!isEdit) { select({ row, column: c.id, index }, e.shiftKey); focus(); } }}
        onDoubleClick={() => { select({ row, column: c.id, index }); startEdit(row, c); }}
        style={{ ...cellStyle(c), cursor: "default",
          background: filled ? "var(--bg-sel)" : set ? "var(--blue1)" : undefined,
          // the active cell is its border alone; a fill is for a range of more than one
          boxShadow: isSel ? "inset 0 0 0 2px var(--blue3)" : undefined }}>
        {isEdit ? (
          <CellEditor column={c} text={editing.text} original={editing.original} saving={saving} typed={editing.typed}
            onChange={text => setEditing({ ...editing, text })}
            onCancel={() => { setEditing(null); setError(null); focus(); }}
            onSave={() => void save(row, c, typedValue(editing.text, c.kind))} />
        ) : <CellValue column={c} value={v} />}
      </div>
    );
  };

  /** The cells a range holds, as the grid shows them — from the rows it has read; how many it has not. */
  const rangeCells = (r: Range) => {
    const cols = columns.slice(r.cols[0], r.cols[1] + 1).map(id => sheet.columns.find(c => c.id === id)!).filter(Boolean);
    const rows: unknown[][] = [];
    let unread = 0;
    for (let i = r.rows[0]; i <= r.rows[1]; i++) {
      const got = rowAt?.(i);
      if (!got) { unread += 1; continue; }
      rows.push(cols.map(c => valueOf(Number(got[0]), c.id)));
    }
    return { cols, rows, unread };
  };

  /** Writes the text and says so — or says the browser refused, never "copied" for a copy that did not happen. */
  const toClipboard = (text: string, done: string) => {
    if (!navigator.clipboard) { setSaid("Not copied — this browser gives the page no clipboard"); return; }
    navigator.clipboard.writeText(text).then(() => setSaid(done),
      () => setSaid("Not copied — the browser refused the page its clipboard"));
  };

  const copy = () => {
    if (!selected) return;
    const c = sheet.columns.find(x => x.id === selected.column);
    if (!range) {
      if (!c) return;
      toClipboard(showValue(valueOf(selected.row, selected.column), c), "Copied the cell");
      return;
    }
    const { cols, rows, unread } = rangeCells(range);
    const lines = rows.map(r => r.map((v, j) => showValue(v, cols[j])).join("\t"));
    toClipboard(lines.join("\n"),
      `Copied ${formatCount(rows.length * cols.length)} cells${unread ? ` — ${formatCount(unread)} rows not read yet were left out` : ""}`);
  };

  /** The grid's keys: the arrows (Shift extends), Enter or F2 to change, a character to type over, Cmd or Ctrl+C to copy,
   *  Escape. */
  const keys = (e: ReactKeyboardEvent<HTMLElement>, move?: (dRow: number, dCol: number, extend: boolean) => void) => {
    if (editing) return;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "c" && selected) { e.preventDefault(); copy(); return; }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const arrow = ARROWS[e.key];
    if (arrow && move) { e.preventDefault(); move(arrow[0], arrow[1], e.shiftKey); return; }
    if (!selected) return;
    const c = sheet.columns.find(x => x.id === selected.column);
    if (!c) return;
    if (e.key === "Escape") { e.preventDefault(); select(null); return; }
    if (e.key === "Enter" || e.key === "F2") { e.preventDefault(); startEdit(selected.row, c); return; }
    if (e.key.length === 1 && editable && c.role === "stored" && c.kind !== "yesno") {
      e.preventDefault();
      startEdit(selected.row, c, e.key);
    }
  };

  const column = selected ? sheet.columns.find(c => c.id === selected.column) : undefined;
  const bar: ReactNode = (
    <CellBar sheet={sheet} selected={selected} column={column} editable={editable} error={error} said={said}
      range={range ? rangeWords(range, rangeCells(range)) : null}
      value={selected ? valueOf(selected.row, selected.column) : undefined}
      set={selected ? changedOf(selected.row, selected.column) : undefined}
      onChange={() => { if (selected && column) startEdit(selected.row, column); }}
      onOpenRow={() => { if (selected) onOpenRow(selected.row); }} />
  );
  return { cell, bar, keys, selected, select };
}

/** A range in words for the bar: its size, and — where every column in it holds numbers — their sum over the rows read. */
export function rangeWords(r: Range, got: { cols: SheetColumn[]; rows: unknown[][]; unread: number }): string {
  const height = r.rows[1] - r.rows[0] + 1;
  const width = r.cols[1] - r.cols[0] + 1;
  const parts = [`${formatCount(height)} row${height === 1 ? "" : "s"} × ${formatCount(width)} column${width === 1 ? "" : "s"}`,
    `${formatCount(height * width)} cells`];
  const numeric = got.cols.length > 0 && got.cols.every(c => c.kind === "number" || c.kind === "money");
  if (numeric && got.rows.length) {
    let sum = 0;
    let n = 0;
    for (const row of got.rows) {
      for (const v of row) {
        const x = Number(v);
        if (v !== null && v !== undefined && v !== "" && !isNaN(x)) { sum += x; n += 1; }
      }
    }
    const one = got.cols.length === 1 || got.cols.every(c => c.kind === got.cols[0].kind && c.currency === got.cols[0].currency);
    if (n) parts.push(`sum ${one ? showValue(Math.round(sum * 100) / 100, got.cols[0]) : formatCount(sum)} of `
      + `${formatCount(n)} value${n === 1 ? "" : "s"}`
      + (got.unread ? ` in the ${formatCount(got.rows.length)} row${got.rows.length === 1 ? "" : "s"} read` : ""));
  }
  return parts.join(" · ");
}

/** The flat grid: every row of the view in one scroll, read a block at a time as it comes into sight. */
export function SheetGrid({ sheet, rows, hidden, editable, onEdit, onOpenRow, footer, sort, onSort }: {
  sheet: Sheet;
  rows: RowBlocks;
  hidden: Set<string>;
  editable: boolean;
  /** The view's sort as it stands, and what a click on a column's header does with it. */
  sort?: { column: string; desc: boolean }[];
  onSort?: (column: string) => void;
  /** Set a cell; the version is the one read (0 for a cell never set). */
  onEdit: (row: number, column: SheetColumn, value: unknown, version: number) => Promise<EditResult>;
  onOpenRow: (row: number) => void;
  /** Said after the rows in sight: the view, its order. */
  footer?: string;
}) {
  const shown = sheet.columns.filter(c => !hidden.has(c.id));
  const index = Object.fromEntries(rows.columns.map((id, i) => [id, i + 1]));
  const scrollRef = useRef<HTMLDivElement>(null);
  const total = rows.total ?? 0;

  const work = useCellWork({
    sheet, editable, onEdit, onOpenRow, columns: shown.map(c => c.id), rowAt: rows.rowAt,
    valueOf: (row, column) => rows.rowByNumber(row)?.[index[column]],
    changedOf: (row, column) => rows.changedOf(row, column),
    versionOf: (row, column) => rows.versionOf(row, column),
    focus: () => scrollRef.current?.focus({ preventScroll: true }),
  });

  const virtualizer = useVirtualizer({
    count: total, getScrollElement: () => scrollRef.current, estimateSize: () => ROW_HEIGHT, overscan: 12,
  });
  const items = virtualizer.getVirtualItems();
  const first = items.length ? items[0].index : 0;
  const last = items.length ? items[items.length - 1].index : 0;
  const { onVisible } = rows;
  useEffect(() => { if (total) onVisible(first, last); }, [first, last, total, onVisible]);

  const span = shown.reduce((n, c) => n + width(c), 0) + NUMBER_WIDTH;
  const sight = virtualizer.range;

  /** The arrows: the next row in the view, or the next column shown — scrolled into sight; with Shift, the range grows. */
  const move = (dRow: number, dCol: number, extend: boolean) => {
    const cols = shown.map(c => c.id);
    if (!cols.length || !total) return;
    const at = work.selected;
    const i = at?.index === undefined ? (sight?.startIndex ?? 0) : Math.max(0, Math.min(total - 1, at.index + dRow));
    const ci = at ? Math.max(0, Math.min(cols.length - 1, cols.indexOf(at.column) + dCol)) : 0;
    const r = rows.rowAt(i);
    if (!r) return;
    work.select({ row: Number(r[0]), column: cols[ci], index: i }, extend);
    virtualizer.scrollToIndex(i, { align: "auto" });
    const el = scrollRef.current;
    if (el) {
      const left = NUMBER_WIDTH + shown.slice(0, ci).reduce((n, c) => n + width(c), 0);
      const right = left + width(shown[ci]);
      if (left - NUMBER_WIDTH < el.scrollLeft) el.scrollLeft = left - NUMBER_WIDTH;
      else if (right > el.scrollLeft + el.clientWidth) el.scrollLeft = right - el.clientWidth;
    }
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      {work.bar}
      <div ref={scrollRef} role="grid" aria-label={sheet.name} aria-rowcount={total} aria-busy={rows.stale} tabIndex={0}
        onKeyDown={e => work.keys(e, move)}
        style={{ flex: 1, minHeight: 0, overflow: "auto", background: "var(--bg-0)", outline: "none" }}>
        <div style={{ width: span, minWidth: "100%", position: "relative" }}>
          <GridHeader sheet={sheet} shown={shown} sort={sort} onSort={onSort} />
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {items.map(item => {
              const r = rows.rowAt(item.index);
              if (!r) {
                return (
                  <div key={`wait-${item.index}`} aria-busy="true" style={{ position: "absolute", top: item.start, left: 0,
                    width: span, minWidth: "100%", height: ROW_HEIGHT, borderBottom: LINE,
                    background: "var(--bg-1)" }} />
                );
              }
              const rowNo = Number(r[0]);
              return (
                <div key={rowNo} role="row" className="aug-fs-sm" style={{ position: "absolute", top: item.start, left: 0,
                  display: "flex", width: span, minWidth: "100%", height: ROW_HEIGHT, background: "var(--bg-0)" }}>
                  <RowNumber row={rowNo} marks={rows.marksOf(rowNo)} rules={sheet.rules} onOpen={() => onOpenRow(rowNo)} />
                  {shown.map(c => work.cell(rowNo, c, r[index[c.id]], !!rows.changedOf(rowNo, c.id), item.index))}
                </div>
              );
            })}
          </div>
          <GridFoot shown={shown} totals={rows.totals} rows={total} />
        </div>
      </div>
      <div className="aug-fs-xs" style={{ ...MUTED, ...NUM, padding: "4px 12px", borderTop: "1px solid var(--b0)",
        background: "var(--bg-1)" }}>
        Rows {formatCount(total === 0 ? 0 : (sight?.startIndex ?? 0) + 1)}–{formatCount(Math.min(total, (sight?.endIndex ?? 0) + 1))} of{" "}
        {formatCount(total)}{footer ? ` · ${footer}` : ""}
      </div>
    </div>
  );
}

/** A cell's editor: Enter keeps the value, Escape leaves it as it was, and moving away keeps a value that changed. An
 *  edit begun by typing keeps the typed character and goes on from it; one begun on purpose selects the value. */
function CellEditor({ column, text, original, saving, typed, onChange, onSave, onCancel }: {
  column: SheetColumn; text: string; original: string; saving: boolean; typed: boolean; onChange: (t: string) => void;
  onSave: () => void; onCancel: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  // Enter or Escape decides once; the blur that follows (the field is disabled while it saves) must not decide again,
  // or a value would be sent twice and the second refused as stale.
  const decided = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    if (typed) el.setSelectionRange(el.value.length, el.value.length);
    else el.select();
  }, [typed]);
  const decide = (keep: boolean) => {
    if (decided.current) return;
    decided.current = true;
    if (keep) onSave(); else onCancel();
  };
  const listId = column.kind === "choice" ? `choices-${column.id}` : undefined;
  const placeholder = column.kind === "date" ? "2018-10-17" : column.kind === "datetime" ? "2018-10-17 14:30" : "";
  return (
    <>
      <input ref={ref} value={text} disabled={saving} list={listId} placeholder={placeholder}
        aria-label={`New value for ${column.name}`} className="aug-fs-sm"
        onChange={e => onChange(e.target.value)} onBlur={() => decide(text !== original)}
        onKeyDown={e => {
          e.stopPropagation();
          if (e.key === "Enter") { e.preventDefault(); decide(true); }
          if (e.key === "Escape") { e.preventDefault(); decide(false); }
        }}
        style={{ width: "100%", height: ROW_HEIGHT - 6, background: "var(--bg-1)", color: "var(--t1)",
          border: "1px solid var(--blue3)", borderRadius: "var(--r1)", padding: "0 6px",
          textAlign: column.kind === "number" || column.kind === "money" ? "right" : "left" }} />
      {listId && (
        <datalist id={listId}>{column.choices.map(v => <option key={v} value={v} />)}</datalist>
      )}
    </>
  );
}

/**
 * The cell bar, above the grid where a spreadsheet keeps its formula bar: the selected cell's column and row, its value,
 * and where it came from — a file's row, who set it and when, what it is computed from — with Change and Open row. One
 * line that is always there, so selecting a cell never moves the grid and nothing opens over the rows.
 */
function CellBar({ sheet, selected, column, value, set, editable, error, said, range, onChange, onOpenRow }: {
  sheet: Sheet; selected: Selected | null; column?: SheetColumn; value: unknown;
  set?: { by: string; at: string; version: number }; editable: boolean; error: string | null;
  /** What was just done here — a copy. */
  said: string | null;
  /** A range selected, in words — its size, and its sum where it holds numbers. */
  range: string | null;
  onChange: () => void; onOpenRow: () => void;
}) {
  const empty = value === null || value === undefined || value === "";
  return (
    <div role="status" aria-live="polite" aria-label="The selected cell" className="aug-fs-xs" style={{ height: 30,
      flex: "0 0 auto", display: "flex", alignItems: "center", gap: 10, padding: "0 12px", minWidth: 0,
      borderBottom: "1px solid var(--b0)", background: "var(--bg-1)", color: "var(--t3)" }}>
      {!selected || !column ? (
        <span style={ELLIPSIS}>Select a cell to see where its value came from · double-click, Enter or type to change it ·
          the arrows move · Shift selects a range</span>
      ) : range ? (
        <>
          <span className="aug-fs-sm" style={{ ...ELLIPSIS, ...NUM, color: "var(--t1)", fontWeight: 600 }} title={range}>{range}</span>
          <span style={{ ...ELLIPSIS, color: said ? "var(--grn4)" : undefined }}>{said ?? "Cmd or Ctrl+C copies it"}</span>
        </>
      ) : (
        <>
          <span style={{ ...NUM, whiteSpace: "nowrap" }}>{column.name} · row {formatCount(selected.row)}</span>
          <span className="aug-fs-sm" title={empty ? undefined : String(value)}
            style={{ ...ELLIPSIS, maxWidth: 360, color: empty ? "var(--t4)" : "var(--t1)", fontWeight: 600 }}>
            {empty ? "empty" : showValue(value, column) || String(value)}
          </span>
          {error ? <span role="alert" style={{ ...ELLIPSIS, color: "var(--red4)" }} title={error}>{error}</span>
            : said ? <span style={{ ...ELLIPSIS, color: "var(--grn4)" }}>{said}</span>
              : <span style={ELLIPSIS} title={cellOrigin(sheet, column, selected.row, set)}>{cellOrigin(sheet, column, selected.row, set)}</span>}
          <span style={{ marginLeft: "auto", display: "flex", gap: 2, flex: "0 0 auto" }}>
            {editable && column.role === "stored" && (
              <Button variant="ghost" size="xs" onClick={onChange}>{column.kind === "yesno" ? "Switch" : "Change"}</Button>
            )}
            <Button variant="ghost" size="xs" onClick={onOpenRow}>Open row</Button>
          </span>
        </>
      )}
    </div>
  );
}
