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
import { describeStatements, getQueryHistory, type AuditRecord, type SavedQuery } from "@/lib/api";
import { formatCount, relTime } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { recentRuns, runMark, runMeta, startTables } from "@/lib/query/workbench";
import { isVisualQuery } from "@/components/query/SavedQueryBar";

// The recent runs across the whole width, two lines a run — what the statement does, in words, then the statement as
// it is — and the largest tables beside the saved queries under them (the user, 2026-10-12: "expand the recent runs
// module full width … two lines each"). Below ~640px of pane the two lower cards stack.
const STACK: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 14 };
const PAIR: React.CSSProperties = { display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-start" };
const HALF: React.CSSProperties = { flex: "1 1 300px", minWidth: 0 };
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
  // What each run does, in words — read from the statement on the server, no query and no model. Until it arrives,
  // or for a statement that does not say, the row is the statement alone.
  const [titles, setTitles] = useState<Record<string, string>>({});
  const runKey = runs.map(r => r.sql).join("\u0000");
  useEffect(() => {
    if (!connId || !runs.length) return;
    let alive = true;
    describeStatements(connId, runs.map(r => r.sql))
      .then(t => { if (alive) setTitles(Object.fromEntries(runs.map((r, i) => [r.sql, t[i] ?? ""]))); })
      .catch(() => { /* the statements still show; only their words are missing */ });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connId, runKey]);
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
      <div style={STACK}>
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
              const words = titles[r.sql];
              return (
                // Two lines a run: what it does, in words, with what it returned at the right; then the statement.
                <Button key={r.last.id} variant="ghost" className={ROW_BTN} style={i ? RULE : undefined}
                  title="Open this statement in a new tab" onClick={() => onOpenRun(r.sql)}>
                  <span style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                    <span className="aug-fs-ui" data-testid="query-start-run-words"
                      style={{ ...ONE_LINE, flex: "1 1 0%", color: "var(--t1)",
                        ...(words ? {} : { fontFamily: "var(--font-mono)" }) }}>
                      {words || r.preview}
                    </span>
                    {mark && <Chip tone={mark.tone === "red" ? "down" : "amber"}
                      title={r.last.error ?? undefined}>{mark.word}</Chip>}
                    <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, flexShrink: 0, whiteSpace: "nowrap" }}>
                      {[runMeta(r.last), r.last.ts ? `${relTime(r.last.ts)} ago` : ""].filter(Boolean).join(" · ")}
                      {r.times > 1 && <span title={`Run ${r.times} times among the latest`}> · ×{r.times}</span>}
                    </span>
                  </span>
                  {words && (
                    <span className="aug-fs-xs" data-testid="query-start-run-sql"
                      style={{ ...ONE_LINE, display: "block", marginTop: 2, fontFamily: "var(--font-mono)", color: "var(--t3)" }}>
                      {r.preview}
                    </span>
                  )}
                </Button>
              );
            })}
        </Card>

        <div style={PAIR}>
          <div style={HALF}>
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
          </div>

          <div style={HALF}>
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
    </div>
  );
}
