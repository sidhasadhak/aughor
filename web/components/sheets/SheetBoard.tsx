"use client";

/**
 * A board (SH-3; mockup screen 8): the view's rows as cards in lanes, a lane per value of a choice or yes/no column.
 *
 * Moving a card to another lane is an edit of that column — the same edit the grid makes, kept with who and when, a
 * stale one refused — and a card opens its row as a record. A card moves by dragging, or by the keyboard: on a card,
 * ← and → move it to the lane beside and Enter opens it, and its "Move to" button lists the lanes for whoever does not
 * know the keys; the card keeps the focus as it lands. A value the view's filter leaves out is not a lane; it is said
 * under the board with its rows. A choice no row holds yet is an empty lane, so a card can be moved into it.
 */
import { type DragEvent, type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";

import { MUTED, NUM } from "@/components/clarity/kit";
import { CellValue, RULE_COLOR } from "@/components/sheets/SheetGrid";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Loading, ReadFailed } from "@/components/ui/states";
import { formatCount } from "@/lib/format";
import {
  isStale, readBoard, rowsWord, setCells, showValue, valueWords, type BoardPage, type RowsQuery, type Sheet,
  type SheetColumn,
} from "@/lib/sheets";

const LANE_WIDTH = 272;
const MORE = 20;
const MOST = 100;

/** The columns a card shows under its title when its view names none: the first dates, money and numbers. */
export function cardColumns(sheet: Sheet, chosen: string[], lane: string): SheetColumn[] {
  const named = chosen.map(id => sheet.columns.find(c => c.id === id)).filter((c): c is SheetColumn => !!c);
  if (named.length) return named;
  const title = titleColumn(sheet);
  return sheet.columns.filter(c => c.id !== lane && c.id !== title?.id
    && ["date", "datetime", "money", "number"].includes(c.kind)).slice(0, 3);
}

/** What a card is called: the sheet's key, or its first text column. */
export function titleColumn(sheet: Sheet): SheetColumn | undefined {
  return sheet.columns.find(c => c.id === sheet.key) ?? sheet.columns.find(c => ["text", "email", "link"].includes(c.kind));
}

export function SheetBoard({ sheet, query, column, card, editable, tick, onOpenRow, onMoved }: {
  sheet: Sheet; query: RowsQuery; column: string; card: string[]; editable: boolean; tick: number;
  onOpenRow: (row: number) => void; onMoved: (words: string) => void;
}) {
  const [page, setPage] = useState<BoardPage | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [perLane, setPerLane] = useState(MORE);
  const [over, setOver] = useState<string | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  // the card whose "Move to" list is open, and the card the focus returns to once the board is read after a move
  const [moving, setMoving] = useState<number | null>(null);
  const landed = useRef<number | null>(null);
  const boardRef = useRef<HTMLDivElement>(null);
  const qKey = JSON.stringify(query);

  const read = useCallback(() => {
    readBoard(sheet.id, query, column, perLane).then(p => { setPage(p); setFailed(null); })
      .catch(e => setFailed(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- read again when the view's reading changes, by its key
  }, [sheet.id, qKey, column, perLane]);
  useEffect(() => { read(); }, [read, tick]);
  useEffect(() => {
    if (landed.current === null) return;
    const card = boardRef.current?.querySelector<HTMLElement>(`[data-row="${landed.current}"]`);
    if (card) { card.focus(); landed.current = null; }
  }, [page]);

  const lane = sheet.columns.find(c => c.id === column);
  if (failed) return <ReadFailed what="the board" error={failed} onRetry={read} />;
  if (!page || !lane) return <Loading what="the board" />;

  const index = Object.fromEntries(page.columns.map((id, i) => [id, i + 1]));
  const title = titleColumn(sheet);
  const fields = cardColumns(sheet, card, column);
  const movable = editable && page.movable;

  /** Move a card to a lane: the column's edit, at the version the board read. */
  const move = (row: number, value: unknown, keepFocus = false) => {
    // the cell's version as it stands — an undo leaves a version behind a cell that holds no edit
    const version = page.versions?.[String(row)]?.[column] ?? page.changed[String(row)]?.[column]?.version ?? 0;
    setRefused(null);
    setMoving(null);
    if (keepFocus) landed.current = row;
    setCells(sheet.id, [{ row, column, value, version }])
      .then(() => onMoved(`Row ${row} moved to ${valueWords(value, lane)}`))
      .catch(err => {
        landed.current = null;
        setRefused(err instanceof Error ? err.message : String(err));
        if (isStale(err)) read();                       // moved by someone since: show where they put it
      });
  };

  const drop = (e: DragEvent, value: unknown) => {
    e.preventDefault();
    setOver(null);
    const row = Number(e.dataTransfer.getData("text/x-sheet-row"));
    const from = e.dataTransfer.getData("text/x-sheet-lane");
    if (!row || from === JSON.stringify(value)) return;
    move(row, value);
  };

  /** On a card: ← and → move it to the lane beside, Enter opens it. */
  const keys = (e: KeyboardEvent, row: number, at: number) => {
    if (e.target !== e.currentTarget) return;
    if (e.key === "Enter") { e.preventDefault(); onOpenRow(row); return; }
    if (!movable || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    const to = page.lanes[at + (e.key === "ArrowLeft" ? -1 : 1)];
    if (!to) return;
    e.preventDefault();
    move(row, to.value, true);
  };

  const lanesWithRows = page.lanes.filter(l => l.rows > 0).length;
  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      {refused && <div role="alert" className="aug-fs-sm" style={{ padding: "6px 16px", color: "var(--red4)" }}>{refused}</div>}
      <div ref={boardRef} style={{ flex: 1, minHeight: 0, overflow: "auto", display: "flex", gap: 10, padding: "12px 16px",
        background: "var(--bg-0)", alignItems: "flex-start" }}>
        {page.lanes.map((l, at) => {
          const k = JSON.stringify(l.value);
          return (
            <section key={k} aria-label={`${valueWords(l.value, lane)} · ${formatCount(l.rows)}`}
              onDragOver={e => { if (movable) { e.preventDefault(); setOver(k); } }}
              onDragLeave={() => setOver(o => (o === k ? null : o))}
              onDrop={e => { if (movable) drop(e, l.value); }}
              style={{ width: LANE_WIDTH, minWidth: LANE_WIDTH, display: "flex", flexDirection: "column", gap: 6,
                background: over === k ? "var(--bg-sel)" : "var(--bg-1)", border: "1px solid var(--b1)",
                borderRadius: "var(--r3)", padding: 8, maxHeight: "100%", overflowY: "auto" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 2px 4px" }}>
                {l.value === null ? <span style={MUTED}>empty</span> : <CellValue column={lane} value={l.value} />}
                <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, marginLeft: "auto" }}>{formatCount(l.rows)}</span>
              </div>
              {l.cards.map(r => {
                const rowNo = Number(r[0]);
                const marks = sheet.rules.filter(x => page.marks[String(rowNo)]?.includes(x.id));
                return (
                  <div key={rowNo} draggable={movable} role="group" tabIndex={0} data-row={rowNo}
                    aria-label={`Row ${rowNo}, in ${valueWords(l.value, lane)}`}
                    aria-keyshortcuts={movable ? "ArrowLeft ArrowRight Enter" : "Enter"}
                    onKeyDown={e => keys(e, rowNo, at)}
                    onDragStart={e => {
                      e.dataTransfer.setData("text/x-sheet-row", String(rowNo));
                      e.dataTransfer.setData("text/x-sheet-lane", k);
                      e.dataTransfer.effectAllowed = "move";
                    }}
                    style={{ background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r2)",
                      padding: "7px 9px", display: "flex", flexDirection: "column", gap: 3, cursor: movable ? "grab" : "default",
                      boxShadow: marks.length ? `inset 3px 0 0 ${RULE_COLOR[marks[0].tone]}` : undefined }}
                    title={marks.length ? `marked: ${marks.map(m => m.name).join(", ")}` : undefined}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, minWidth: 0 }}>
                      <Button variant="ghost" size="xs" onClick={() => onOpenRow(rowNo)}
                        style={{ justifyContent: "flex-start", padding: 0, height: "auto", fontWeight: 600, color: "var(--t1)",
                          minWidth: 0, flex: 1 }}>
                        <span className="aug-mono" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {title ? String(r[index[title.id]] ?? `row ${rowNo}`) : `row ${rowNo}`}
                        </span>
                      </Button>
                      {movable && page.lanes.length > 1 && (
                        <Button variant="ghost" size="icon-xs" aria-expanded={moving === rowNo}
                          aria-label={`Move row ${rowNo} to another lane`} title="Move to another lane (or ← →)"
                          onClick={() => setMoving(moving === rowNo ? null : rowNo)}>
                          <Icon name="morev" size={12} />
                        </Button>
                      )}
                    </div>
                    {moving === rowNo && (
                      <div role="group" aria-label={`Move row ${rowNo} to`} style={{ display: "flex", flexWrap: "wrap", gap: 4,
                        padding: "4px 0", borderTop: "1px solid var(--b0)", borderBottom: "1px solid var(--b0)" }}>
                        <span className="aug-fs-xs" style={{ ...MUTED, width: "100%" }}>Move to</span>
                        {page.lanes.filter(o => o !== l).map(o => (
                          <Button key={JSON.stringify(o.value)} variant="outline" size="xs" onClick={() => move(rowNo, o.value, true)}>
                            {valueWords(o.value, lane)}
                          </Button>
                        ))}
                      </div>
                    )}
                    {fields.map(c => {
                      const v = r[index[c.id]];
                      return (
                        <span key={c.id} className="aug-fs-xs" style={{ display: "flex", gap: 6, minWidth: 0 }}>
                          <span style={{ ...MUTED, flex: "0 0 auto", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis",
                            whiteSpace: "nowrap" }}>{c.name}</span>
                          <span style={{ ...NUM, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {v === null || v === undefined || v === "" ? "—" : showValue(v, c)}
                          </span>
                        </span>
                      );
                    })}
                  </div>
                );
              })}
              {l.rows > l.cards.length && (
                <Button variant="ghost" size="xs" style={MUTED} disabled={perLane >= MOST}
                  title={perLane >= MOST ? `A lane shows at most ${MOST} cards; filter the view, or read it as a grid` : undefined}
                  onClick={() => setPerLane(Math.min(MOST, perLane + MORE))}>
                  + {formatCount(l.rows - l.cards.length)} more
                </Button>
              )}
              {l.rows === 0 && <span className="aug-fs-xs" style={MUTED}>No row yet{movable ? " — drop a card here" : ""}.</span>}
            </section>
          );
        })}
      </div>
      <div className="aug-fs-xs" style={{ ...MUTED, ...NUM, padding: "4px 12px", borderTop: "1px solid var(--b0)",
        background: "var(--bg-1)" }}>
        {rowsWord(page.total, sheet.name)} in {formatCount(lanesWithRows)} lane{lanesWithRows === 1 ? "" : "s"} by {lane.name}
        {page.not_shown.length > 0 && ` · not in this view: ${page.not_shown.map(x =>
          `${valueWords(x.value, lane)} ${formatCount(x.rows)}`).join(" · ")}`}
        {movable ? ` · moving a card changes its ${lane.name}, kept as an edit`
          : page.movable ? "" : ` · ${lane.name} is read from elsewhere, so its cards stay where they are`}
      </div>
    </div>
  );
}
