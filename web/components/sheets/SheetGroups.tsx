"use client";

/**
 * A grid grouped by a column (SH-2's grouping, SH-3's group totals; mockup screen 7): the largest group first, each
 * under a head saying its value, how many rows it holds and — with `sheets.views` on — its totals over its own rows,
 * placed under the columns they total. A group shows its first rows in the view's order and opens further on asking;
 * the first three groups open, the rest closed. A grouping with more groups than it lists says how many it left out.
 *
 * Every count here is the grid's own: a group holds exactly the rows the grid shows filtered to its value.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { MUTED, NUM } from "@/components/clarity/kit";
import {
  CellValue, GridFoot, GridHeader, NUMBER_WIDTH, ROW_HEIGHT, RowNumber, useCellWork, width, type EditResult,
} from "@/components/sheets/SheetGrid";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Loading, ReadFailed } from "@/components/ui/states";
import { formatCount } from "@/lib/format";
import {
  readGroups, readRows, rowsWord, totalWords, valueCondition, type Changed, type GroupsPage, type RowsQuery, type Sheet,
  type SheetColumn, type Versions,
} from "@/lib/sheets";

/** Rows read at a time when a group is opened further. */
const MORE = 50;
/** Groups open when the grouping is first shown. */
const OPEN_FIRST = 3;

const keyOf = (v: unknown) => JSON.stringify(v ?? null);

export function SheetGroups({ sheet, query, group, hidden, editable, tick, onEdit, onOpenRow }: {
  sheet: Sheet; query: RowsQuery; group: string; hidden: Set<string>; editable: boolean; tick: number;
  onEdit: (row: number, column: SheetColumn, value: unknown, version: number) => Promise<EditResult>;
  onOpenRow: (row: number) => void;
}) {
  const [page, setPage] = useState<GroupsPage | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [more, setMore] = useState<Record<string, { rows: unknown[][]; changed: Changed; versions: Versions;
    marks: Record<string, string[]> }>>({});
  const frameRef = useRef<HTMLDivElement>(null);
  const qKey = JSON.stringify(query);

  const read = useCallback(() => {
    readGroups(sheet.id, query, group).then(p => {
      setPage(p);
      setFailed(null);
      setOpen(o => (Object.keys(o).length ? o
        : Object.fromEntries(p.groups.slice(0, OPEN_FIRST).map(g => [keyOf(g.value), true]))));
    }).catch(e => setFailed(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- read again when the view's reading changes, by its key
  }, [sheet.id, qKey, group]);

  useEffect(() => { setOpen({}); setMore({}); }, [qKey, group]);
  useEffect(() => { read(); }, [read, tick]);

  const gcol = sheet.columns.find(c => c.id === group);
  const shown = sheet.columns.filter(c => !hidden.has(c.id));
  const index = useMemo(() => Object.fromEntries((page?.columns ?? []).map((id, i) => [id, i + 1])), [page]);

  const rowsOf = (value: unknown) => [...(page?.groups.find(g => keyOf(g.value) === keyOf(value))?.shown ?? []),
    ...(more[keyOf(value)]?.rows ?? [])];
  const changedOf = (row: number, column: string) =>
    page?.changed[String(row)]?.[column] ?? Object.values(more).find(m => m.changed[String(row)]?.[column])?.changed[String(row)][column];
  const versionOf = (row: number, column: string) => page?.versions?.[String(row)]?.[column]
    ?? Object.values(more).find(m => m.versions[String(row)]?.[column] !== undefined)?.versions[String(row)][column]
    ?? changedOf(row, column)?.version ?? 0;
  const marksOf = (row: number) => page?.marks?.[String(row)] ?? Object.values(more).find(m => m.marks[String(row)])?.marks[String(row)] ?? [];
  const rowByNumber = (row: number) => {
    for (const g of page?.groups ?? []) {
      const r = rowsOf(g.value).find(x => Number(x[0]) === row);
      if (r) return r;
    }
    return undefined;
  };

  const work = useCellWork({
    sheet, editable, onEdit, onOpenRow,
    valueOf: (row, column) => rowByNumber(row)?.[index[column]],
    changedOf,
    versionOf,
    focus: () => frameRef.current?.focus({ preventScroll: true }),
  });

  if (failed) return <ReadFailed what="the groups" error={failed} onRetry={read} />;
  if (!page || !gcol) return <Loading what="the groups" />;

  const readMore = (value: unknown) => {
    const have = rowsOf(value).length;
    readRows(sheet.id, { ...query, group: undefined, filter: [...(query.filter ?? []), valueCondition(gcol, value)],
      offset: have, limit: MORE })
      .then(p => setMore(m => {
        const k = keyOf(value);
        const was = m[k] ?? { rows: [], changed: {}, versions: {}, marks: {} };
        return { ...m, [k]: { rows: [...was.rows, ...p.rows], changed: { ...was.changed, ...p.changed },
          versions: { ...was.versions, ...(p.versions ?? {}) }, marks: { ...was.marks, ...(p.marks ?? {}) } } };
      }))
      .catch(e => setFailed(e instanceof Error ? e.message : String(e)));
  };

  // the head's first block spans the columns before the first one it totals, so each total sits under its column
  const totalled = (c: SheetColumn) => ["number", "money", "date", "datetime", "yesno"].includes(c.kind);
  const lead = Math.max(1, shown.findIndex(totalled) === -1 ? shown.length : shown.findIndex(totalled));
  const leadWidth = NUMBER_WIDTH + shown.slice(0, lead).reduce((n, c) => n + width(c), 0);
  const span = shown.reduce((n, c) => n + width(c), 0) + NUMBER_WIDTH;

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      {work.bar}
      <div ref={frameRef} role="grid" aria-label={`${sheet.name}, grouped by ${gcol.name}`} tabIndex={0}
        onKeyDown={e => work.keys(e)}
        style={{ flex: 1, minHeight: 0, overflow: "auto", background: "var(--bg-0)", outline: "none" }}>
        <div style={{ width: span, minWidth: "100%", position: "relative" }}>
          <GridHeader sheet={sheet} shown={shown} />
          {page.groups.map(g => {
            const k = keyOf(g.value);
            const isOpen = !!open[k];
            const rows = rowsOf(g.value);
            const left = g.rows - rows.length;
            return (
              <div key={k} role="rowgroup">
                <div role="row" className="aug-fs-sm" style={{ display: "flex", height: ROW_HEIGHT + 4,
                  background: "var(--bg-1)", borderBottom: "1px solid var(--b0)", alignItems: "center" }}>
                  <div style={{ width: leadWidth, minWidth: leadWidth, display: "flex", alignItems: "center", gap: 8,
                    padding: "0 8px", overflow: "hidden" }}>
                    <Button variant="ghost" size="icon-xs" aria-expanded={isOpen}
                      aria-label={`${isOpen ? "Close" : "Open"} ${String(g.value ?? "empty")}`}
                      onClick={() => setOpen({ ...open, [k]: !isOpen })}>
                      <Icon name={isOpen ? "chevd" : "chevr"} size={12} />
                    </Button>
                    {g.value === null || g.value === undefined || g.value === ""
                      ? <span style={MUTED}>empty</span> : <CellValue column={gcol} value={g.value} />}
                    <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, whiteSpace: "nowrap" }}>{rowsWord(g.rows, sheet.name)}</span>
                  </div>
                  {shown.slice(lead).map(c => (
                    <div key={c.id} className="aug-fs-xs" style={{ width: width(c), minWidth: width(c), padding: "0 8px",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--t2)", ...NUM,
                      textAlign: c.kind === "number" || c.kind === "money" ? "right" : "left" }}>
                      {totalled(c) && g.totals[c.id] ? totalWords(g.totals[c.id], c, g.rows) : ""}
                    </div>
                  ))}
                </div>
                {isOpen && rows.map(r => {
                  const rowNo = Number(r[0]);
                  return (
                    <div key={rowNo} role="row" className="aug-fs-sm" style={{ display: "flex", width: span,
                      minWidth: "100%", borderBottom: "1px solid var(--b0)" }}>
                      <RowNumber row={rowNo} marks={marksOf(rowNo)} rules={sheet.rules} onOpen={() => onOpenRow(rowNo)} />
                      {shown.map(c => work.cell(rowNo, c, r[index[c.id]], !!changedOf(rowNo, c.id)))}
                    </div>
                  );
                })}
                {isOpen && left > 0 && (
                  <div style={{ padding: "2px 8px 2px 36px", borderBottom: "1px solid var(--b0)" }}>
                    <Button variant="ghost" size="xs" onClick={() => readMore(g.value)} style={MUTED}>
                      + {formatCount(left)} more in {String(g.value ?? "empty")}
                      {left > MORE ? ` — show ${formatCount(MORE)}` : ""}
                    </Button>
                  </div>
                )}
              </div>
            );
          })}
          <GridFoot shown={shown} totals={page.totals} rows={page.total} />
        </div>
      </div>
      <div className="aug-fs-xs" style={{ ...MUTED, ...NUM, padding: "4px 12px", borderTop: "1px solid var(--b0)",
        background: "var(--bg-1)" }}>
        {rowsWord(page.total, sheet.name)} in {formatCount(page.groups_total)} group{page.groups_total === 1 ? "" : "s"} ·
        grouped by {gcol.name}{Object.values(page.groups[0]?.totals ?? {}).length ? " · a group's totals are over its own rows" : ""}
        {page.groups_not_listed > 0 && ` · the largest ${formatCount(page.groups.length)} listed, `
          + `${formatCount(page.groups_not_listed)} more not`}
      </div>
    </div>
  );
}
