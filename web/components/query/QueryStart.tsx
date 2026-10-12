"use client";

/**
 * The SQL editor's results pane before anything has run — a starting point, not a sentence (`aughor-v2/CLARITY.md`):
 * the statements run here lately (a repeat folded into "×3", never listed again), the queries saved for this
 * connection, and its largest tables. Each row is a way to act: a run or a saved query opens, a table goes in at the
 * cursor — the same three things the history rail, the Saved menu and the catalog rail already do.
 *
 * Read from what the screen already holds: the Saved menu's list and the catalog's tables arrive as props; the recent
 * runs are the audit log's workbench rows, the read the history rail makes. Nothing here runs a statement.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { Bar, Card, Chip, Empty, MUTED, NUM, ONE_LINE, RULE } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Loading, ReadFailed } from "@/components/ui/states";
import { getQueryHistory, type AuditRecord, type SavedQuery } from "@/lib/api";
import { formatCount, relTime } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { recentRuns, runMark, runMeta, startTables } from "@/lib/query/workbench";
import { isVisualQuery } from "@/components/query/SavedQueryBar";

// Two columns, 3 : 2 — the recent runs, which a person reaches for most and whose statements need the width, on the
// left; the largest tables over the saved queries on the right. Three equal cards side by side cut every statement at
// ~45 characters and left the short cards floating (the user, 2026-10-12: "arrange it better"). Below ~760px of pane
// the right column wraps under the left.
const COLUMNS: React.CSSProperties = { display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-start" };
const LEFT: React.CSSProperties = { flex: "3 1 440px", minWidth: 0 };
const RIGHT: React.CSSProperties = { flex: "2 1 300px", minWidth: 0, display: "flex", flexDirection: "column", gap: 14 };
const ROW_BTN = "block h-auto w-full whitespace-normal px-1 py-1.5 text-left font-normal";
/** How many distinct recent statements the left column lists before "All N". */
const RECENT = 8;

export function QueryStart({
  connId, connectionName, refreshKey, saved, tables, tablesLoading, onOpenRun, onOpenSaved, onInsert, onShowRuns,
}: {
  connId: string;
  connectionName?: string;
  /** Bumped after every run — the recent list is a read of the log a run writes. */
  refreshKey: number;
  /** The Saved menu's list for this connection; undefined while it is read, null when the read failed. */
  saved: SavedQuery[] | null | undefined;
  tables: Array<{ name: string; rowCount?: string | number | null }>;
  tablesLoading?: boolean;
  /** Open a statement in a new tab — the history rail's restore. */
  onOpenRun: (sql: string) => void;
  /** Open a saved query the way the Saved menu does: in the mode it was written in, Save updating it. */
  onOpenSaved: (q: SavedQuery) => void;
  /** Put a table's name at the editor's cursor — the catalog rail's ». */
  onInsert: (name: string) => void;
  /** Open the history rail, for every run rather than the latest few. */
  onShowRuns?: () => void;
}) {
  const [records, setRecords] = useState<AuditRecord[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!connId) { setRecords([]); setFailed(null); return; }
    getQueryHistory(connId, 30)
      .then(r => { setRecords(r); setFailed(null); })
      .catch(e => { setRecords([]); setFailed(e instanceof Error ? e.message : String(e)); });
  }, [connId]);
  useEffect(() => { load(); }, [load, refreshKey]);

  const runs = useMemo(() => recentRuns(records ?? [], RECENT), [records]);
  const distinct = useMemo(() => recentRuns(records ?? [], Number.MAX_SAFE_INTEGER).length, [records]);
  const top = useMemo(() => startTables(tables, 6), [tables]);
  const maxRows = Math.max(1, ...top.map(t => t.rows ?? 0));

  if (!connId) {
    return (
      <div data-testid="query-start" style={{ padding: "12px 14px" }}>
        <Empty>Choose a connection to start.</Empty>
      </div>
    );
  }

  return (
    <div data-testid="query-start" style={{ flex: 1, minHeight: 0, overflowY: "auto", background: "var(--bg-0)",
      padding: "12px 14px 16px" }}>
      <div className="aug-fs-sm" style={{ ...MUTED, marginBottom: 10 }}>
        ⌘↵ runs the statement under the cursor · <span style={{ fontFamily: "var(--font-mono)", color: "var(--t2)" }}>/ask</span> and
        say what you want, and the SQL is written for you — or start from one of these.
      </div>
      <div style={COLUMNS}>
        <div style={LEFT}>
          <Card label="Recent runs" testId="query-start-runs"
            right={distinct > runs.length && onShowRuns ? (
              <Button variant="link" size="xs" onClick={onShowRuns} title="Every run, in the history rail">
                All {formatCount(distinct)}
              </Button>
            ) : records && distinct ? formatCount(distinct) : null}>
            {records === null ? <Loading what="recent runs" />
              : failed !== null ? <ReadFailed what="the recent runs" error={failed} onRetry={load} />
              : runs.length === 0 ? <Empty>Nothing has run on this connection yet.</Empty>
              : runs.map((r, i) => {
                const mark = runMark(r.last);
                return (
                  // One line a run: the statement takes the width, what it returned sits at the right.
                  <Button key={r.last.id} variant="ghost" className={ROW_BTN} style={i ? RULE : undefined}
                    title="Open this statement in a new tab" onClick={() => onOpenRun(r.sql)}>
                    <span style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                      <span className="aug-fs-sm" style={{ ...ONE_LINE, flex: "1 1 0%", fontFamily: "var(--font-mono)",
                        color: "var(--t1)" }}>{r.preview}</span>
                      {mark && <Chip tone={mark.tone === "red" ? "down" : "amber"}
                        title={r.last.error ?? undefined}>{mark.word}</Chip>}
                      <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, flexShrink: 0, whiteSpace: "nowrap" }}>
                        {[runMeta(r.last), r.last.ts ? `${relTime(r.last.ts)} ago` : ""].filter(Boolean).join(" · ")}
                        {r.times > 1 && <span title={`Run ${r.times} times among the latest`}> · ×{r.times}</span>}
                      </span>
                    </span>
                  </Button>
                );
              })}
          </Card>
        </div>

        <div style={RIGHT}>
          <Card label="Largest tables" testId="query-start-tables"
            right={tables.length ? `${formatCount(tables.length)}${connectionName ? ` in ${connectionName}` : ""}` : null}>
            {tables.length === 0 ? (tablesLoading ? <Loading what="tables" /> : <Empty>No tables in this connection.</Empty>)
              : (
                <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(48px, 90px) auto",
                  gap: "4px 10px", alignItems: "center" }}>
                  {withUniqueKeys(top, t => t.name).map(([key, t]) => (
                    <div key={key} style={{ display: "contents" }}>
                      <Button variant="ghost" size="xs" className="justify-start px-1 font-normal"
                        title={`Insert ${t.name} at the cursor`} onClick={() => onInsert(t.name)}
                        style={{ minWidth: 0 }}>
                        <span className="aug-fs-sm" style={{ ...ONE_LINE, fontFamily: "var(--font-mono)", color: "var(--t1)" }}>
                          {t.name}
                        </span>
                      </Button>
                      <span title={t.rows == null ? `${t.name}: rows not counted` : `${t.name}: ${formatCount(t.rows)} rows`}>
                        <Bar value={t.rows ?? maxRows} max={maxRows} hatched={t.rows == null} />
                      </span>
                      <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, textAlign: "right", whiteSpace: "nowrap" }}>
                        {t.shown}
                      </span>
                    </div>
                  ))}
                </div>
              )}
          </Card>

          <Card label="Saved" testId="query-start-saved" right={saved?.length ? formatCount(saved.length) : null}>
            {saved === undefined ? <Loading what="saved queries" />
              : saved === null ? <Empty>The saved queries could not be read.</Empty>
              : saved.length === 0 ? <Empty>None saved for this connection yet.</Empty>
              : saved.slice(0, 5).map((q, i) => (
                <Button key={q.id} variant="ghost" className={ROW_BTN} style={i ? RULE : undefined}
                  title="Open this saved query — Save updates it" onClick={() => onOpenSaved(q)}>
                  <span style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                    <span className="aug-fs-sm" style={{ ...ONE_LINE, flex: "1 1 0%", color: "var(--t1)" }}>{q.name}</span>
                    <span className="aug-fs-xs" style={{ ...MUTED, flexShrink: 0, whiteSpace: "nowrap" }}>
                      {isVisualQuery(q) ? "visual" : "sql"}{q.updated_at ? ` · ${relTime(q.updated_at)} ago` : ""}
                    </span>
                  </span>
                </Button>
              ))}
            {saved && saved.length > 5 && (
              <div className="aug-fs-xs" style={{ ...MUTED, paddingTop: 4 }}>{formatCount(saved.length - 5)} more under Saved</div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
