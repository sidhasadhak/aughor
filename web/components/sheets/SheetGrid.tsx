"use client";

/**
 * A sheet's grid (SH-2; mockup screens 3, 4 and 6): 30px rows, each column headed by its kind and its description, a
 * cell edited in place by its kind, every cell's story one click away (imported from file row N, or set by whom and
 * when), the row opened as a record, and the totals of the rows shown at the foot.
 *
 * Built on TanStack Virtual, the house grid's own windowing (`components/query/ResultsGrid.tsx`): only the visible
 * rows are mounted, so a page of 2,000 rows costs what the viewport shows. Sorting, filtering, grouping and the totals
 * are the server's — over the whole view, not the page — so the grid itself only lays out and edits.
 */
import { useVirtualizer } from "@tanstack/react-virtual";
import { type CSSProperties, Fragment, useEffect, useMemo, useRef, useState } from "react";

import { Chip, MUTED, NUM } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon, type IconName } from "@/components/ui/icon";
import { formatCount, formatTimestamp } from "@/lib/format";
import {
  KIND_LABEL, readCell, showValue, totalWords, typedValue, who, type CellStory, type Kind, type RowsPage, type Sheet,
  type SheetColumn,
} from "@/lib/sheets";

export const ROW_HEIGHT = 30;

const KIND_ICON: Record<Kind, IconName> = {
  text: "text", number: "num", money: "num", date: "date", datetime: "time", choice: "list", yesno: "bool",
  email: "message", link: "link",
};

const WIDTH: Record<Kind, number> = {
  text: 180, number: 110, money: 130, date: 130, datetime: 170, choice: 140, yesno: 90, email: 200, link: 170,
};

/** A choice's chip colour, from its place among the column's values — the same value, the same colour, every time. */
const CHIP_TONES = ["accent", "up", "amber", "violet", "down", "plain"] as const;

function width(c: SheetColumn): number {
  return Math.max(WIDTH[c.kind] ?? 160, Math.min(260, c.name.length * 8 + 44));
}

function mark(c: SheetColumn): string {
  if (c.role === "computed") return "computed";
  if (c.role === "lookup") return "linked";
  if (c.role === "total") return "total";
  return "";
}

export interface EditResult { ok: boolean; error?: string }

export function SheetGrid({ sheet, page, hidden, editable, groupBy, onEdit, onOpenRow, rowStart }: {
  sheet: Sheet;
  page: RowsPage;
  hidden: Set<string>;
  editable: boolean;
  groupBy?: string;
  /** Set a cell; the version is the one read (0 for a cell never set). */
  onEdit: (row: number, column: SheetColumn, value: unknown, version: number) => Promise<EditResult>;
  onOpenRow: (row: number) => void;
  /** The number of the first row on this page, among the view's rows. */
  rowStart: number;
}) {
  const shown = useMemo(() => sheet.columns.filter(c => !hidden.has(c.id)), [sheet.columns, hidden]);
  const index = useMemo(() => Object.fromEntries(page.columns.map((id, i) => [id, i + 1])), [page.columns]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<{ row: number; column: string } | null>(null);
  const [editing, setEditing] = useState<{ row: number; column: string; text: string; original: string } | null>(null);
  const [story, setStory] = useState<CellStory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // A group's head is a row of its own, placed where its value changes.
  const lines = useMemo(() => {
    const out: ({ kind: "row"; at: number } | { kind: "group"; value: unknown; rows: number })[] = [];
    const gi = groupBy ? index[groupBy] : undefined;
    let last: unknown = Symbol("none");
    page.rows.forEach((r, at) => {
      if (gi !== undefined && r[gi] !== last) {
        last = r[gi];
        const g = page.groups.find(x => x.value === r[gi]);
        out.push({ kind: "group", value: r[gi], rows: g?.rows ?? 0 });
      }
      out.push({ kind: "row", at });
    });
    return out;
  }, [page.rows, page.groups, groupBy, index]);

  const virtualizer = useVirtualizer({
    count: lines.length, getScrollElement: () => scrollRef.current, estimateSize: () => ROW_HEIGHT, overscan: 12,
  });

  useEffect(() => { setStory(null); setSelected(null); setEditing(null); }, [page]);

  const total = shown.reduce((n, c) => n + width(c), 0) + 64;
  const groupCol = groupBy ? sheet.columns.find(c => c.id === groupBy) : undefined;

  const versionOf = (row: number, column: string) => page.changed[String(row)]?.[column]?.version ?? 0;

  const openStory = (row: number, column: string) => {
    setSelected({ row, column });
    setError(null);
    readCell(sheet.id, row, column).then(setStory).catch(e => setError(e instanceof Error ? e.message : String(e)));
  };

  const save = async (row: number, c: SheetColumn, value: unknown) => {
    setSaving(true);
    const out = await onEdit(row, c, value, versionOf(row, c.id));
    setSaving(false);
    setEditing(null);
    if (out.ok) setError(null);
    else { setSelected({ row, column: c.id }); setError(out.error ?? "The change was not made."); }
  };

  const cellStyle = (c: SheetColumn): CSSProperties => ({
    width: width(c), minWidth: width(c), maxWidth: width(c), padding: "0 8px", overflow: "hidden",
    textOverflow: "ellipsis", whiteSpace: "nowrap", borderRight: "1px solid var(--b0)", display: "flex",
    alignItems: "center", justifyContent: c.kind === "number" || c.kind === "money" ? "flex-end" : "flex-start",
    height: ROW_HEIGHT, ...(c.kind === "number" || c.kind === "money" ? NUM : {}),
  });

  const renderValue = (c: SheetColumn, v: unknown) => {
    if (v === null || v === undefined || v === "") return <span style={{ color: "var(--t4)" }}>—</span>;
    if (c.kind === "choice") {
      const at = Math.max(0, c.choices.indexOf(String(v)));
      return <Chip tone={CHIP_TONES[at % CHIP_TONES.length]}>{String(v)}</Chip>;
    }
    if (c.kind === "yesno") return <Checkbox checked={v === true || v === "true"} disabled aria-label={c.name} />;
    if (c.kind === "link") return <span style={{ color: "var(--blue4)" }}>{String(v)}</span>;
    return <span title={String(v)}>{showValue(v, c)}</span>;
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", position: "relative" }}>
      <div ref={scrollRef} role="grid" aria-label={sheet.name} aria-rowcount={page.total}
        style={{ flex: 1, minHeight: 0, overflow: "auto", background: "var(--bg-0)" }}>
        <div style={{ width: total, minWidth: "100%" }}>
          {/* the header */}
          <div role="row" className="aug-fs-xs" style={{ display: "flex", position: "sticky", top: 0, zIndex: 3,
            background: "var(--bg-2)", borderBottom: "1px solid var(--b1)", color: "var(--t2)" }}>
            <div style={{ width: 64, minWidth: 64, height: ROW_HEIGHT, borderRight: "1px solid var(--b0)" }} />
            {shown.map(c => (
              <div key={c.id} role="columnheader" title={`${c.name} · ${KIND_LABEL[c.kind]}${c.description ? ` — ${c.description}` : ""}`}
                style={{ ...cellStyle(c), justifyContent: "flex-start", gap: 6, fontWeight: 600 }}>
                <span style={MUTED}><Icon name={KIND_ICON[c.kind]} size={12} /></span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{c.name}</span>
                {c.description && <span style={MUTED}><Icon name="info" size={11} /></span>}
                {mark(c) && <Chip tone="accent">{mark(c)}</Chip>}
                {c.made_by && <Chip tone="violet" title="Proposed by the assistant, applied by a person">proposed</Chip>}
              </div>
            ))}
          </div>

          {/* the rows */}
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {virtualizer.getVirtualItems().map(item => {
              const line = lines[item.index];
              if (line.kind === "group") {
                return (
                  <div key={`g${item.index}`} className="aug-fs-sm" style={{ position: "absolute", top: item.start,
                    left: 0, right: 0, height: ROW_HEIGHT, display: "flex", alignItems: "center", gap: 8,
                    padding: "0 12px", background: "var(--bg-1)", borderBottom: "1px solid var(--b0)", fontWeight: 600 }}>
                    <Icon name="chevd" size={12} />
                    {groupCol ? renderValue(groupCol, line.value) : String(line.value)}
                    <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>{formatCount(line.rows)} rows</span>
                  </div>
                );
              }
              const r = page.rows[line.at];
              const rowNo = Number(r[0]);
              return (
                <div key={rowNo} role="row" style={{ position: "absolute", top: item.start, left: 0, display: "flex",
                  width: total, minWidth: "100%", borderBottom: "1px solid var(--b0)", background: "var(--bg-0)" }}
                  className="aug-fs-sm">
                  <div className="aug-fs-xs" style={{ width: 64, minWidth: 64, height: ROW_HEIGHT, display: "flex",
                    alignItems: "center", justifyContent: "space-between", padding: "0 4px 0 8px", ...MUTED, ...NUM,
                    borderRight: "1px solid var(--b0)" }} title={`row ${rowNo} of the sheet`}>
                    {rowNo}
                    <Button variant="ghost" size="icon-xs" aria-label={`Open row ${rowNo}`}
                      onClick={() => { setSelected(null); setStory(null); onOpenRow(rowNo); }}>
                      <Icon name="expand" size={11} />
                    </Button>
                  </div>
                  {shown.map(c => {
                    const v = r[index[c.id]];
                    const isSel = selected?.row === rowNo && selected.column === c.id;
                    const set = page.changed[String(rowNo)]?.[c.id];
                    const isEdit = editing?.row === rowNo && editing.column === c.id;
                    return (
                      <div key={c.id} role="gridcell" tabIndex={-1} aria-selected={isSel}
                        onClick={() => openStory(rowNo, c.id)}
                        onDoubleClick={() => {
                          if (!editable || c.role !== "stored") return;
                          if (c.kind === "yesno") { void save(rowNo, c, !(v === true || v === "true")); return; }
                          const text = v === null || v === undefined ? "" : String(v);
                          setEditing({ row: rowNo, column: c.id, text, original: text });
                        }}
                        style={{ ...cellStyle(c), cursor: "default",
                          background: isSel ? "var(--bg-sel)" : set ? "var(--blue1)" : undefined,
                          outline: isSel ? "1px solid var(--blue3)" : undefined, outlineOffset: -1 }}>
                        {isEdit ? (
                          <CellEditor column={c} text={editing.text} original={editing.original} saving={saving}
                            onChange={text => setEditing({ ...editing, text })}
                            onCancel={() => { setEditing(null); setError(null); }}
                            onSave={() => void save(rowNo, c, typedValue(editing.text, c.kind))} />
                        ) : renderValue(c, v)}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>

          {/* the totals of the rows the view shows */}
          <div role="row" className="aug-fs-xs" style={{ display: "flex", position: "sticky", bottom: 0, zIndex: 2,
            background: "var(--bg-2)", borderTop: "1px solid var(--b1)", color: "var(--t2)" }}
            title="Totals are over every row this view shows, not only the rows on this page">
            <div style={{ width: 64, minWidth: 64, height: ROW_HEIGHT, padding: "0 8px", display: "flex",
              alignItems: "center", borderRight: "1px solid var(--b0)", ...MUTED }}>total</div>
            {shown.map(c => (
              <div key={c.id} style={{ ...cellStyle(c), justifyContent: "flex-start" }}>
                {totalWords(page.totals[c.id], c, page.total)}
              </div>
            ))}
          </div>
        </div>
      </div>

      {selected && (story || error) && (
        <CellPop sheet={sheet} story={story} error={error} editable={editable}
          column={sheet.columns.find(c => c.id === selected.column)!}
          value={page.rows.find(r => Number(r[0]) === selected.row)?.[index[selected.column]]}
          onChange={() => {
            const c = sheet.columns.find(x => x.id === selected.column)!;
            const v = page.rows.find(r => Number(r[0]) === selected.row)?.[index[selected.column]];
            if (c.kind === "yesno") void save(selected.row, c, !(v === true || v === "true"));
            else {
              const text = v === null || v === undefined ? "" : String(v);
              setEditing({ row: selected.row, column: selected.column, text, original: text });
            }
          }}
          onOpenRow={() => { const r = selected.row; setSelected(null); setStory(null); onOpenRow(r); }}
          onClose={() => { setSelected(null); setStory(null); setError(null); }} />
      )}
      <div className="aug-fs-xs" style={{ ...MUTED, ...NUM, padding: "4px 12px", borderTop: "1px solid var(--b0)",
        background: "var(--bg-1)" }}>
        Rows {page.total === 0 ? 0 : rowStart + 1}–{rowStart + page.rows.length} of {formatCount(page.total)}
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

/** A cell's story, beside it: where its value came from and every change since — and the two things to do next. */
function CellPop({ sheet, story, error, column, value, editable, onChange, onOpenRow, onClose }: {
  sheet: Sheet; story: CellStory | null; error: string | null; column: SheetColumn; value: unknown; editable: boolean;
  onChange: () => void; onOpenRow: () => void; onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div role="dialog" aria-label={`${column.name}, row ${story?.row ?? ""}`} className="aug-fs-sm"
      style={{ position: "absolute", right: 16, bottom: 40, zIndex: 10, width: 320, background: "var(--bg-2)",
        border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "10px 12px", display: "flex",
        flexDirection: "column", gap: 6 }}>
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
