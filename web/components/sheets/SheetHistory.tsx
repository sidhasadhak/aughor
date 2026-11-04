"use client";

/**
 * A sheet's history: what changed, value by value, and the way back for any one of them.
 *
 * Each change says which cells and rows it touched, what each held before and after, and what it holds now. Put back
 * returns that one cell or row to what the change replaced and touches nothing else — a new change in this same history,
 * so it can be undone, and every value it replaced stays here. Narrowed to a cell or a row, this is its whole story, from
 * where it came from to what it holds now, so any state it has held can be gone back to. It sits beside the grid, never
 * over it.
 */
import { useCallback, useEffect, useState } from "react";

import { MUTED } from "@/components/clarity/kit";
import { PANEL, PanelHead } from "@/components/sheets/SheetRecord";
import { Button } from "@/components/ui/button";
import { Loading, ReadFailed } from "@/components/ui/states";
import { formatCount, formatTimestamp } from "@/lib/format";
import {
  changeOriginWords, readChangeLines, readHistory, valueWords, who,
  type HistoryChange, type HistoryLine, type HistoryRead, type HistoryScope, type PutBackRequest, type Sheet,
} from "@/lib/sheets";

const RULE = "1px solid var(--b0)";

/** A row's key, cut to fit the line that names it. */
const short = (title: string) => (title.length > 18 ? `${title.slice(0, 16)}…` : title);

const capitalised = (words: string) => words.charAt(0).toUpperCase() + words.slice(1);

export function SheetHistory({ sheet, tick, editable, scope, canUndo, onScope, onClose, onUndo, onPutBack }: {
  sheet: Sheet; tick: number; editable: boolean;
  /** One row's or one cell's story; null, every change to the sheet. */
  scope: HistoryScope | null;
  /** What undo would take back for this person, in words. */
  canUndo: string;
  onScope: (scope: HistoryScope | null) => void;
  onClose: () => void; onUndo: () => void;
  onPutBack: (request: PutBackRequest) => Promise<void>;
}) {
  const [read, setRead] = useState<HistoryRead | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  /** The changes whose every line was asked for. */
  const [whole, setWhole] = useState<Record<string, { lines: HistoryLine[]; total: number }>>({});
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    setWhole({});
    readHistory(sheet.id, scope ?? undefined).then(r => { setRead(r); setFailed(null); })
      .catch(e => setFailed(e instanceof Error ? e.message : String(e)));
  }, [sheet.id, scope]);
  useEffect(() => { load(); }, [load, tick]);

  const putBack = async (key: string, request: PutBackRequest) => {
    setBusy(key);
    try { await onPutBack(request); } finally { setBusy(""); }
  };

  const showAll = (change: string) => {
    readChangeLines(sheet.id, change).then(got => setWhole(w => ({ ...w, [change]: got })))
      .catch(e => setFailed(e instanceof Error ? e.message : String(e)));
  };

  const told = read?.scope ?? null;
  const told_column = told?.column ? sheet.columns.find(c => c.id === told.column) : undefined;
  const count = read ? `${formatCount(read.changes.length)}${read.more ? "+" : ""} change${read.changes.length === 1 ? "" : "s"}` : undefined;
  return (
    <aside aria-label={`History of ${sheet.name}`} style={PANEL}>
      <PanelHead title="History" chip={count} onClose={onClose} />
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "10px 14px" }}>
        {failed ? <ReadFailed what="the history" error={failed} onRetry={load} /> : !read ? <Loading what="the history" /> : (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {told && (
              <div data-testid="history-scope" style={{ display: "flex", flexDirection: "column", gap: 4, paddingBottom: 10, borderBottom: RULE }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <b className="aug-fs-sm" style={{ minWidth: 0, overflowWrap: "anywhere" }}>
                    {told.name ? `${told.name} · row ${formatCount(told.row)}` : `Row ${formatCount(told.row)}`}
                  </b>
                  {told.title && <span className="aug-fs-xs" style={{ ...MUTED, whiteSpace: "nowrap" }}>{short(told.title)}</span>}
                  <Button variant="ghost" size="xs" onClick={() => onScope(null)} style={{ marginLeft: "auto", flex: "0 0 auto" }}>All changes</Button>
                </div>
                <span className="aug-fs-xs" style={MUTED}>
                  {told.removed ? "This row has been removed from the sheet."
                    : told.column ? <>Holds <b style={{ color: "var(--t1)", fontWeight: 500 }}>{valueWords(told.now, told_column)}</b> now.</>
                      : "Every change to this row, its cells included."}
                </span>
              </div>
            )}
            {!told && canUndo && editable && (
              <Button variant="ghost" size="xs" onClick={onUndo} style={{ alignSelf: "flex-start", marginBottom: 8 }}>
                Undo your last: {canUndo.slice(0, 50)}
              </Button>
            )}
            {read.changes.map(c => (
              <Change key={c.id} change={c} sheet={sheet} editable={editable} scoped={told} whole={whole[c.id]} busy={busy}
                onScope={onScope} onShowAll={() => showAll(c.id)} onPutBack={putBack} />
            ))}
            {told && (
              <div className="aug-fs-xs" style={{ ...MUTED, padding: "8px 0" }}>
                {capitalised(told.came_from)}{read.changes.length ? "" : " · not changed since"}
              </div>
            )}
            {!told && read.changes.length === 0 && <div className="aug-fs-xs" style={MUTED}>Nothing has changed here yet.</div>}
            {read.more && (
              <div className="aug-fs-xs" style={{ ...MUTED, padding: "8px 0" }}>
                The latest {formatCount(read.changes.length)} are listed; older changes are kept too. Open a cell or a row to read its whole story.
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

function Change({ change, sheet, editable, scoped, whole, busy, onScope, onShowAll, onPutBack }: {
  change: HistoryChange; sheet: Sheet; editable: boolean; scoped: HistoryRead["scope"];
  whole?: { lines: HistoryLine[]; total: number }; busy: string;
  onScope: (scope: HistoryScope) => void; onShowAll: () => void;
  onPutBack: (key: string, request: PutBackRequest) => Promise<void>;
}) {
  const lines = whole?.lines ?? change.lines;
  const total = whole?.total ?? change.lines_total;
  // one line says all a change did; a change of many, or one that changed the sheet's definition too, says it first
  const head = total !== 1 || change.definition > 0;
  const allKey = `${change.id}:all`;
  return (
    <section data-testid="history-change" aria-label={change.what || undefined} style={{ padding: "8px 0", borderBottom: RULE, display: "flex", flexDirection: "column", gap: 6 }}>
      {head && (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="aug-fs-sm" style={{ minWidth: 0, overflowWrap: "anywhere" }}>{change.what}</span>
          {editable && !scoped && total > 1 && (
            <Button variant="ghost" size="xs" disabled={!!busy} style={{ marginLeft: "auto", flex: "0 0 auto" }}
              title="Puts back every value of this change that still stands. A value changed since is left as it is, and named."
              onClick={() => void onPutBack(allKey, { change: change.id })}>
              {busy === allKey ? "Putting back…" : `Put back all ${formatCount(total)}`}
            </Button>
          )}
        </div>
      )}
      {lines.map(line => (
        <Line key={`${line.row}:${line.column}`} change={change.id} line={line} sheet={sheet} editable={editable} scoped={scoped}
          busy={busy} onScope={onScope} onPutBack={onPutBack} />
      ))}
      {total > lines.length && (
        whole ? <span className="aug-fs-xs" style={MUTED}>The first {formatCount(lines.length)} of {formatCount(total)} are listed. Open a cell or a row to read its story.</span>
          : <Button variant="ghost" size="xs" style={{ alignSelf: "flex-start" }} onClick={onShowAll}>Show all {formatCount(total)}</Button>
      )}
      <div className="aug-fs-xs" style={MUTED}>
        {who(change.by, sheet.me)} · {formatTimestamp(change.at, "short")}{changeOriginWords(change.origin)}
      </div>
    </section>
  );
}

function Line({ change, line, sheet, editable, scoped, busy, onScope, onPutBack }: {
  change: string; line: HistoryLine; sheet: Sheet; editable: boolean; scoped: HistoryRead["scope"]; busy: string;
  onScope: (scope: HistoryScope) => void;
  onPutBack: (key: string, request: PutBackRequest) => Promise<void>;
}) {
  const column = sheet.columns.find(c => c.id === line.column);
  const words = (v: unknown) => valueWords(v, column);
  const key = `${change}:${line.row}:${line.column}`;
  const request: PutBackRequest = { change, row: line.row, column: line.column, current: line.current };
  const coming = line.kind === "row" && line.what === "added";
  // this cell's own story says its name and what it holds now once, at its head
  const named = !(scoped?.column && scoped.column === line.column);
  // a cell's button names the state it goes back to; a row's has only one way to go
  const label = coming ? "Take out" : line.kind === "cell" ? `Put back ${short(words(line.from))}` : "Put back";
  const title = line.kind === "cell"
    ? `Puts ${line.name} in row ${formatCount(line.row)} back to ${words(line.from)}. Nothing else changes.`
    : `${coming ? "Takes" : "Puts"} row ${formatCount(line.row)} ${coming ? "out of" : "back in"} the sheet. Nothing else changes.`;
  return (
    <div data-testid="history-line" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: "2px 8px", alignItems: "start" }}>
      <div style={{ minWidth: 0 }}>
        {line.kind === "cell" ? (
          <>
            {named && (
              <div className="aug-fs-xs" style={{ ...MUTED, display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
                {column ? (
                  <Button variant="link" size="xs" title="Every value this cell has held" style={{ padding: 0, height: "auto" }}
                    onClick={() => onScope({ row: line.row, column: line.column })}>
                    {line.name} · row {formatCount(line.row)}
                  </Button>
                ) : <span>{line.name} · row {formatCount(line.row)}</span>}
                {line.title && <span>· {short(line.title)}</span>}
              </div>
            )}
            <div className="aug-fs-sm" style={{ overflowWrap: "anywhere" }}>
              <span style={MUTED}>{words(line.from)}</span> → {words(line.to)}
              {named && !line.stands && !line.blocked && <span className="aug-fs-xs" style={MUTED}> · now {words(line.now)}</span>}
            </div>
          </>
        ) : (
          <>
            <div className="aug-fs-sm" style={{ overflowWrap: "anywhere" }}>
              Row {formatCount(line.row)} {line.what || "changed"}
              {line.title && <span className="aug-fs-xs" style={MUTED}> · {short(line.title)}</span>}
            </div>
            {line.values && Object.keys(line.values).length > 0 && (
              <div className="aug-fs-xs" style={{ ...MUTED, overflowWrap: "anywhere" }}>
                {Object.entries(line.values).map(([name, value]) => `${name} ${String(value)}`).join(" · ")}
              </div>
            )}
          </>
        )}
        {line.blocked && <div className="aug-fs-xs" style={MUTED}>Cannot be put back: {line.blocked}.</div>}
      </div>
      {editable && !line.blocked && (line.same
        ? <span className="aug-fs-xs" style={{ ...MUTED, whiteSpace: "nowrap", paddingTop: 2 }}>{coming ? "Already out" : "Already back"}</span>
        : (
          <Button variant="ghost" size="xs" disabled={!!busy} title={title} onClick={() => void onPutBack(key, request)}>
            {busy === key ? "Putting back…" : label}
          </Button>
        ))}
    </div>
  );
}
