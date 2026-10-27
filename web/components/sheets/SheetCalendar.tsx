"use client";

/**
 * A calendar (SH-3; mockup screen 9): the view's rows placed by a date column, a month at a time, Monday first. A day
 * says how many rows fall on it, and opens its rows as cards. It opens on the month where the rows end — the latest
 * holding at least one in a hundred of them, never a lone straggler — and says how many rows have no date and so are on
 * no day.
 */
import { useCallback, useEffect, useState } from "react";

import { MUTED, NUM } from "@/components/clarity/kit";
import { cardColumns, titleColumn } from "@/components/sheets/SheetBoard";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Loading, ReadFailed } from "@/components/ui/states";
import { formatCount } from "@/lib/format";
import {
  monthWeeks, monthWords, readCalendar, readRows, rowsWord, shiftMonth, showDate, showValue, type CalendarPage,
  type RowsPage, type RowsQuery, type Sheet,
} from "@/lib/sheets";

const DAY_ROWS = 50;
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function SheetCalendar({ sheet, query, column, card, tick, onOpenRow }: {
  sheet: Sheet; query: RowsQuery; column: string; card: string[]; tick: number; onOpenRow: (row: number) => void;
}) {
  const [month, setMonth] = useState("");
  const [page, setPage] = useState<CalendarPage | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [day, setDay] = useState<string>("");
  const [dayRows, setDayRows] = useState<RowsPage | null>(null);
  const qKey = JSON.stringify(query);

  const read = useCallback(() => {
    readCalendar(sheet.id, query, column, month).then(p => { setPage(p); setFailed(null); })
      .catch(e => setFailed(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- read again when the view's reading changes, by its key
  }, [sheet.id, qKey, column, month]);
  useEffect(() => { read(); }, [read, tick]);
  useEffect(() => { setDay(""); setDayRows(null); }, [qKey, column, month]);

  useEffect(() => {
    if (!day) return;
    let live = true;
    readRows(sheet.id, { ...query, group: undefined, filter: [...(query.filter ?? []), { column, op: "on", value: day }],
      limit: DAY_ROWS }).then(p => { if (live) setDayRows(p); }).catch(e => { if (live) setFailed(String(e)); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the day's rows, read again with the view
  }, [day, qKey, column, sheet.id, tick]);

  const dateCol = sheet.columns.find(c => c.id === column);
  if (failed) return <ReadFailed what="the calendar" error={failed} onRetry={read} />;
  if (!page || !dateCol) return <Loading what="the calendar" />;

  const counts = Object.fromEntries(page.days.map(d => [d.day, d.rows]));
  const busiest = Math.max(1, ...page.days.map(d => d.rows));
  const title = titleColumn(sheet);
  const fields = cardColumns(sheet, card, column);
  const index = dayRows ? Object.fromEntries(dayRows.columns.map((id, i) => [id, i + 1])) : {};
  const at = (m: string) => setMonth(m);

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "10px 16px", background: "var(--bg-0)",
        display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Button variant="ghost" size="icon-sm" aria-label="The month before" onClick={() => at(shiftMonth(page.month, -1))}>
            <Icon name="back" />
          </Button>
          <b className="aug-fs-ui" style={{ minWidth: 150, textAlign: "center" }}>{monthWords(page.month)}</b>
          <Button variant="ghost" size="icon-sm" aria-label="The month after" onClick={() => at(shiftMonth(page.month, 1))}>
            <Icon name="next" />
          </Button>
          {page.where_rows_end !== page.month && (
            <Button variant="ghost" size="xs" onClick={() => at(page.where_rows_end)}>
              To where the rows end · {monthWords(page.where_rows_end)}
            </Button>
          )}
          {page.earliest && page.latest && (
            <span className="aug-fs-xs" style={{ ...MUTED, marginLeft: "auto" }}>
              {showDate(page.earliest, false)} to {showDate(page.latest, false)}
            </span>
          )}
        </div>
        <div role="grid" aria-label={`${monthWords(page.month)} by ${dateCol.name}`}
          style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(64px, 1fr))", gap: 4 }}>
          {WEEKDAYS.map(w => (
            <div key={w} role="columnheader" className="aug-fs-xs" style={{ ...MUTED, padding: "0 6px" }}>{w}</div>
          ))}
          {monthWeeks(page.month).flat().map((d, i) => {
            if (!d) return <div key={`blank-${i}`} aria-hidden style={{ minHeight: 64 }} />;
            const n = counts[d] ?? 0;
            const chosen = d === day;
            return (
              <Button key={d} variant="ghost" role="gridcell" aria-selected={chosen} disabled={n === 0}
                aria-label={`${showDate(d, false)}: ${rowsWord(n, sheet.name)}`}
                onClick={() => setDay(chosen ? "" : d)}
                style={{ minHeight: 64, height: "auto", display: "flex", flexDirection: "column", alignItems: "flex-start",
                  justifyContent: "space-between", padding: "6px 8px", borderRadius: "var(--r2)", fontWeight: 400,
                  border: `1px solid ${chosen ? "var(--blue3)" : "var(--b0)"}`,
                  background: n ? `color-mix(in srgb, var(--blue2) ${Math.round(12 + 40 * (n / busiest))}%, var(--bg-1))`
                    : "var(--bg-1)" }}>
                <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>{Number(d.slice(8))}</span>
                {n > 0 ? <span className="aug-fs-sm" style={{ ...NUM, color: "var(--t1)", fontWeight: 600 }}>{formatCount(n)}</span>
                  : <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>—</span>}
              </Button>
            );
          })}
        </div>
        {day && (
          <section aria-label={`Rows on ${showDate(day, false)}`} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span className="aug-label">{showDate(day, false)} · {rowsWord(counts[day] ?? 0, sheet.name)}</span>
            {!dayRows ? <Loading what="the day's rows" /> : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gap: 6 }}>
                {dayRows.rows.map(r => {
                  const rowNo = Number(r[0]);
                  return (
                    <Button key={rowNo} variant="ghost" onClick={() => onOpenRow(rowNo)}
                      style={{ height: "auto", display: "flex", flexDirection: "column", alignItems: "stretch", gap: 2,
                        padding: "7px 9px", textAlign: "left", fontWeight: 400, background: "var(--bg-2)",
                        border: "1px solid var(--card-edge)", borderRadius: "var(--r2)" }}>
                      <span className="aug-mono aug-fs-sm" style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis",
                        whiteSpace: "nowrap" }}>{title ? String(r[index[title.id]] ?? `row ${rowNo}`) : `row ${rowNo}`}</span>
                      {fields.map(c => (
                        <span key={c.id} className="aug-fs-xs" style={{ display: "flex", gap: 6 }}>
                          <span style={MUTED}>{c.name}</span>
                          <span style={NUM}>{showValue(r[index[c.id]], c) || "—"}</span>
                        </span>
                      ))}
                    </Button>
                  );
                })}
              </div>
            )}
            {dayRows && dayRows.total > dayRows.rows.length && (
              <span className="aug-fs-xs" style={MUTED}>The first {formatCount(dayRows.rows.length)} of{" "}
                {formatCount(dayRows.total)}; the grid filtered to this day shows them all.</span>
            )}
          </section>
        )}
      </div>
      <div className="aug-fs-xs" style={{ ...MUTED, ...NUM, padding: "4px 12px", borderTop: "1px solid var(--b0)",
        background: "var(--bg-1)" }}>
        {rowsWord(page.month_rows, sheet.name)} in {monthWords(page.month)} on {formatCount(page.days.length)} day
        {page.days.length === 1 ? "" : "s"} by {dateCol.name}
        {page.undated > 0 && ` · ${rowsWord(page.undated, sheet.name)} have no ${dateCol.name} and are on no day`}
        {" "}· a day opens its rows
      </div>
    </div>
  );
}
