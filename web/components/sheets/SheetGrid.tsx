"use client";

/**
 * A sheet's grid (SH-2; mockup screens 3, 4 and 6): 30px rows, each column headed by its kind and what it holds, a
 * cell edited in place by its kind, every cell's story one click away and opened beside the cell (imported from file
 * row N, or set by whom and when), the row opened as a record, and the totals of the rows shown at the foot.
 *
 * Built on TanStack Virtual, the house grid's own windowing (`components/query/ResultsGrid.tsx`): only the rows in
 * sight are mounted, and they are read a block at a time as they come into sight (`useRowBlocks`), so the scroll bar is
 * the whole view. Sorting, filtering and the totals are the server's — over the whole view — so the grid only lays out
 * and edits. The cells, the header, the foot and a cell's story are shared with the grouped grid (`SheetGroups`).
 */
import { useVirtualizer } from "@tanstack/react-virtual";
import { type CSSProperties, Fragment, type ReactNode, type RefObject, useEffect, useRef, useState } from "react";

import { Chip, MUTED, NUM } from "@/components/clarity/kit";
import type { RowBlocks } from "@/components/sheets/useRowBlocks";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon, type IconName } from "@/components/ui/icon";
import { formatCount, formatTimestamp } from "@/lib/format";
import {
  KIND_LABEL, readCell, showValue, totalWords, typedValue, who, type CellStory, type ColumnTotals, type Kind,
  type RuleTone, type Sheet, type SheetColumn, type SheetRule,
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

export function cellStyle(c: SheetColumn): CSSProperties {
  const numeric = c.kind === "number" || c.kind === "money";
  return {
    width: width(c), minWidth: width(c), maxWidth: width(c), padding: "0 8px", overflow: "hidden",
    borderRight: "1px solid var(--b0)", display: "flex", alignItems: "center",
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

/** The header: each column's kind, name and marks — and what a derived or described column is, a click away. */
export function GridHeader({ sheet, shown }: { sheet: Sheet; shown: SheetColumn[] }) {
  const [about, setAbout] = useState("");
  const at = (id: string) => NUMBER_WIDTH + shown.slice(0, shown.findIndex(c => c.id === id)).reduce((n, c) => n + width(c), 0);
  const open = shown.find(c => c.id === about);
  const span = NUMBER_WIDTH + shown.reduce((n, c) => n + width(c), 0);
  return (
    <div role="row" className="aug-fs-xs" style={{ display: "flex", position: "sticky", top: 0, zIndex: 3,
      background: "var(--bg-2)", borderBottom: "1px solid var(--b1)", color: "var(--t2)" }}>
      <div style={{ width: NUMBER_WIDTH, minWidth: NUMBER_WIDTH, height: ROW_HEIGHT, borderRight: "1px solid var(--b0)" }} />
      {shown.map(c => (
        <div key={c.id} role="columnheader" aria-label={`${c.name} · ${KIND_LABEL[c.kind]}`}
          style={{ ...cellStyle(c), justifyContent: "flex-start", gap: 6, fontWeight: 600 }}>
          <span style={MUTED}><Icon name={KIND_ICON[c.kind]} size={12} /></span>
          <span style={{ ...ELLIPSIS, color: c.role === "lookup" ? "var(--blue4)" : undefined }} title={c.name}>{c.name}</span>
          {mark(c) && <Chip tone="accent">{mark(c)}</Chip>}
          {c.made_by && <Chip tone="violet" title="Proposed by the assistant, applied by a person">proposed</Chip>}
          {(c.description || c.role !== "stored") && (
            <Button variant="ghost" size="icon-xs" aria-label={`What ${c.name} is`} aria-expanded={about === c.id}
              onClick={() => setAbout(about === c.id ? "" : c.id)} style={{ marginLeft: "auto", ...MUTED }}>
              <Icon name="info" size={11} />
            </Button>
          )}
        </div>
      ))}
      {open && (
        <div role="dialog" aria-label={`What ${open.name} is`} className="aug-fs-sm" style={{ position: "absolute",
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
        alignItems: "center", borderRight: "1px solid var(--b0)", ...MUTED }}>{label}</div>
      {shown.map(c => (
        <div key={c.id} style={{ ...cellStyle(c), justifyContent: "flex-start" }}>
          <span style={ELLIPSIS} title={totalWords(totals[c.id], c, rows)}>{totalWords(totals[c.id], c, rows)}</span>
        </div>
      ))}
    </div>
  );
}

export interface EditResult { ok: boolean; error?: string }

/** A row's number, with the rules marking it as a bar at its start, and the button that opens it as a record. */
export function RowNumber({ row, marks, rules, onOpen }: {
  row: number; marks: string[]; rules: SheetRule[]; onOpen: () => void;
}) {
  const marking = rules.filter(r => marks.includes(r.id));
  return (
    <div className="aug-fs-xs" style={{ width: NUMBER_WIDTH, minWidth: NUMBER_WIDTH, height: ROW_HEIGHT, display: "flex",
      alignItems: "center", justifyContent: "space-between", padding: "0 4px 0 8px", ...MUTED, ...NUM,
      borderRight: "1px solid var(--b0)", position: "relative",
      boxShadow: marking.length ? `inset 3px 0 0 ${RULE_COLOR[marking[0].tone]}` : undefined }}
      title={marking.length ? `row ${row} · marked: ${marking.map(r => r.name).join(", ")}` : `row ${row} of the sheet`}>
      {row}
      <Button variant="ghost" size="icon-xs" aria-label={`Open row ${row}`} onClick={onOpen}>
        <Icon name="expand" size={11} />
      </Button>
    </div>
  );
}

/**
 * Selecting a cell, editing it, and its story — the same in the flat grid and the grouped one. A cell's story opens
 * under the cell (above it near the foot), and closes when the grid scrolls.
 */
export function useCellWork({ sheet, editable, onEdit, onOpenRow, valueOf, versionOf, frame }: {
  sheet: Sheet; editable: boolean;
  onEdit: (row: number, column: SheetColumn, value: unknown, version: number) => Promise<EditResult>;
  onOpenRow: (row: number) => void;
  valueOf: (row: number, column: string) => unknown;
  versionOf: (row: number, column: string) => number;
  frame: RefObject<HTMLDivElement | null>;
}) {
  const [selected, setSelected] = useState<{ row: number; column: string; top: number; left: number } | null>(null);
  const [editing, setEditing] = useState<{ row: number; column: string; text: string; original: string } | null>(null);
  const [story, setStory] = useState<CellStory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const place = (el: HTMLElement) => {
    const box = frame.current?.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    if (!box) return { top: 40, left: 16 };
    const POP_W = 320;
    const POP_H = 180;
    let top = r.bottom - box.top + 4;
    if (top + POP_H > box.height) top = Math.max(4, r.top - box.top - POP_H - 4);
    return { top, left: Math.max(8, Math.min(r.left - box.left, box.width - POP_W - 8)) };
  };

  const openStory = (row: number, column: string, el: HTMLElement) => {
    setSelected({ row, column, ...place(el) });
    setError(null);
    setStory(null);
    readCell(sheet.id, row, column).then(setStory).catch(e => setError(e instanceof Error ? e.message : String(e)));
  };

  const save = async (row: number, c: SheetColumn, value: unknown) => {
    setSaving(true);
    const out = await onEdit(row, c, value, versionOf(row, c.id));
    setSaving(false);
    setEditing(null);
    if (out.ok) setError(null);
    else { setSelected(s => s ?? { row, column: c.id, top: 40, left: 16 }); setError(out.error ?? "The change was not made."); }
  };

  const startEdit = (row: number, c: SheetColumn) => {
    const v = valueOf(row, c.id);
    if (c.kind === "yesno") { void save(row, c, !(v === true || v === "true")); return; }
    const text = v === null || v === undefined ? "" : String(v);
    setEditing({ row, column: c.id, text, original: text });
  };

  const cell = (row: number, c: SheetColumn, v: unknown, set: boolean) => {
    const isSel = selected?.row === row && selected.column === c.id;
    const isEdit = editing?.row === row && editing.column === c.id;
    return (
      <div key={c.id} role="gridcell" tabIndex={-1} aria-selected={isSel}
        onClick={e => openStory(row, c.id, e.currentTarget)}
        onDoubleClick={() => { if (editable && c.role === "stored") startEdit(row, c); }}
        style={{ ...cellStyle(c), cursor: "default",
          background: isSel ? "var(--bg-sel)" : set ? "var(--blue1)" : undefined,
          outline: isSel ? "1px solid var(--blue3)" : undefined, outlineOffset: -1 }}>
        {isEdit ? (
          <CellEditor column={c} text={editing.text} original={editing.original} saving={saving}
            onChange={text => setEditing({ ...editing, text })}
            onCancel={() => { setEditing(null); setError(null); }}
            onSave={() => void save(row, c, typedValue(editing.text, c.kind))} />
        ) : <CellValue column={c} value={v} />}
      </div>
    );
  };

  const close = () => { setSelected(null); setStory(null); setError(null); };
  const column = selected ? sheet.columns.find(c => c.id === selected.column) : undefined;
  const pop: ReactNode = selected && column && (story || error) ? (
    <CellPop sheet={sheet} story={story} error={error} editable={editable} column={column} at={selected}
      value={valueOf(selected.row, selected.column)}
      onChange={() => startEdit(selected.row, column)}
      onOpenRow={() => { const r = selected.row; close(); onOpenRow(r); }}
      onClose={close} />
  ) : null;
  return { cell, pop, close, reset: () => { close(); setEditing(null); } };
}

/** The flat grid: every row of the view in one scroll, read a block at a time as it comes into sight. */
export function SheetGrid({ sheet, rows, hidden, editable, onEdit, onOpenRow, footer }: {
  sheet: Sheet;
  rows: RowBlocks;
  hidden: Set<string>;
  editable: boolean;
  /** Set a cell; the version is the one read (0 for a cell never set). */
  onEdit: (row: number, column: SheetColumn, value: unknown, version: number) => Promise<EditResult>;
  onOpenRow: (row: number) => void;
  /** Said after the rows in sight: the view, its order. */
  footer?: string;
}) {
  const shown = sheet.columns.filter(c => !hidden.has(c.id));
  const index = Object.fromEntries(rows.columns.map((id, i) => [id, i + 1]));
  const scrollRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const total = rows.total ?? 0;

  const work = useCellWork({
    sheet, editable, onEdit, onOpenRow, frame: frameRef,
    valueOf: (row, column) => rows.rowByNumber(row)?.[index[column]],
    versionOf: (row, column) => rows.changedOf(row, column)?.version ?? 0,
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

  return (
    <div ref={frameRef} style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", position: "relative" }}>
      <div ref={scrollRef} role="grid" aria-label={sheet.name} aria-rowcount={total} onScroll={work.close}
        style={{ flex: 1, minHeight: 0, overflow: "auto", background: "var(--bg-0)" }}>
        <div style={{ width: span, minWidth: "100%", position: "relative" }}>
          <GridHeader sheet={sheet} shown={shown} />
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {items.map(item => {
              const r = rows.rowAt(item.index);
              if (!r) {
                return (
                  <div key={`wait-${item.index}`} aria-busy="true" style={{ position: "absolute", top: item.start, left: 0,
                    width: span, minWidth: "100%", height: ROW_HEIGHT, borderBottom: "1px solid var(--b0)",
                    background: "var(--bg-1)" }} />
                );
              }
              const rowNo = Number(r[0]);
              return (
                <div key={rowNo} role="row" className="aug-fs-sm" style={{ position: "absolute", top: item.start, left: 0,
                  display: "flex", width: span, minWidth: "100%", borderBottom: "1px solid var(--b0)",
                  background: "var(--bg-0)" }}>
                  <RowNumber row={rowNo} marks={rows.marksOf(rowNo)} rules={sheet.rules}
                    onOpen={() => { work.close(); onOpenRow(rowNo); }} />
                  {shown.map(c => work.cell(rowNo, c, r[index[c.id]], !!rows.changedOf(rowNo, c.id)))}
                </div>
              );
            })}
          </div>
          <GridFoot shown={shown} totals={rows.totals} rows={total} />
        </div>
      </div>
      {work.pop}
      <div className="aug-fs-xs" style={{ ...MUTED, ...NUM, padding: "4px 12px", borderTop: "1px solid var(--b0)",
        background: "var(--bg-1)" }}>
        Rows {formatCount(total === 0 ? 0 : (sight?.startIndex ?? 0) + 1)}–{formatCount(Math.min(total, (sight?.endIndex ?? 0) + 1))} of{" "}
        {formatCount(total)}{footer ? ` · ${footer}` : ""}
      </div>
    </div>
  );
}

/** A cell's editor: Enter keeps the value, Escape leaves it as it was, and moving away keeps a value that changed. */
function CellEditor({ column, text, original, saving, onChange, onSave, onCancel }: {
  column: SheetColumn; text: string; original: string; saving: boolean; onChange: (t: string) => void;
  onSave: () => void; onCancel: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  // Enter or Escape decides once; the blur that follows (the field is disabled while it saves) must not decide again,
  // or a value would be sent twice and the second refused as stale.
  const decided = useRef(false);
  useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);
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

/** A cell's story, under the cell: where its value came from and every change since — and the two things to do next. */
function CellPop({ sheet, story, error, column, value, editable, at, onChange, onOpenRow, onClose }: {
  sheet: Sheet; story: CellStory | null; error: string | null; column: SheetColumn; value: unknown; editable: boolean;
  at: { top: number; left: number }; onChange: () => void; onOpenRow: () => void; onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div role="dialog" aria-label={`${column.name}, row ${story?.row ?? ""}`} className="aug-fs-sm"
      style={{ position: "absolute", top: at.top, left: at.left, zIndex: 10, width: 320, background: "var(--bg-2)",
        border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "10px 12px", display: "flex",
        flexDirection: "column", gap: 6, boxShadow: "var(--shadow-md)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span className="aug-fs-xs" style={MUTED}>{column.name} · row {story?.row}</span>
        <Button variant="ghost" size="icon-xs" aria-label="Close" onClick={onClose} style={{ marginLeft: "auto" }}>
          <Icon name="close" size={12} />
        </Button>
      </div>
      {error && <span role="alert" style={{ color: "var(--red4)" }}>{error}</span>}
      {story && (
        <>
          <div>{value === null || value === undefined || value === "" ? <span style={MUTED}>empty</span> : showValue(value, column)}</div>
          <div className="aug-fs-xs">{story.came_from.replace(/^imported from/, "Imported from")}</div>
          {story.events.length === 0 ? (
            <div className="aug-fs-xs" style={MUTED}>Not changed since {column.role === "stored" ? "it was imported" : "it was made"}.</div>
          ) : (
            <div className="aug-fs-xs" style={{ display: "flex", flexDirection: "column", gap: 2, maxHeight: 120, overflowY: "auto" }}>
              {story.events.map(e => (
                <Fragment key={`${e.version}-${e.at}`}>
                  <span>
                    {e.event === "set"
                      ? <>Set to <b>{showValue(e.value, column) || "empty"}</b></>
                      : <>Back to the {sheet.source.kind === "file" ? "file's" : "source's"} value</>}
                    {" "}by {who(e.by)} · {formatTimestamp(e.at, "short")}
                    {e.origin.startsWith("proposal:") && " · proposed by the assistant"}
                    {e.origin.startsWith("undo:") && " · an undo"}
                    {e.origin === "merge" && " · from a newer file"}
                  </span>
                </Fragment>
              ))}
            </div>
          )}
          <div style={{ display: "flex", gap: 6 }}>
            {editable && column.role === "stored" && (
              <Button variant="outline" size="xs" onClick={onChange}>{column.kind === "yesno" ? "Switch" : "Change…"}</Button>
            )}
            <Button variant="ghost" size="xs" onClick={onOpenRow}>Open row</Button>
          </div>
        </>
      )}
    </div>
  );
}
