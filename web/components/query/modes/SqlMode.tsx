"use client";

/**
 * SE-1/SE-2 — SQL mode: editor over results, history on the right.
 *
 * The catalog rail used to be this file's too. PR E moved it up to the workbench, where
 * ONE rail serves both modes; what remains here is the insertion point it targets,
 * published through `onInsertReady`. The rail decides WHAT to insert (a qualified table,
 * a bare column); this file still owns WHERE, because the cursor is the editor's.
 *
 * This component owns the one decision the editor deliberately does not: **what runs**.
 * The rule is selection-if-any, else the statement under the cursor, else the whole
 * buffer. Keeping it here rather than in `SqlEditorPane` means the editor stays a text
 * surface and the workbench stays the thing that knows about connections and queries.
 *
 * SE-2 adds tabs. Each tab is a document with its own SQL, name and last-run status,
 * persisted per connection. The EDITOR is mounted once and its document swapped on tab
 * change rather than mounted per tab: a CM6 view per tab would multiply the parser
 * worker and the linter by the tab count, and 20 tabs is an allowed state.
 *
 * Drafts persist per connection so a layer switch or a reload does not lose work in
 * progress. Two rules from this codebase apply and both are load-bearing: storage is
 * NEVER read in a `useState` initializer (that reads during render and breaks
 * hydration), and every access is wrapped — a disabled-storage browser degrades to a
 * working editor with no persistence, not to a blank screen.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ResizableSplit } from "@/components/ResizableSplit";
import { SqlEditorPane } from "@/components/query/editor/SqlEditorPane";
import { ResultsPanel } from "@/components/query/ResultsPanel";
import { HistoryRail } from "@/components/query/HistoryRail";
import { Icon } from "@/components/ui/icon";
import { ParamBar } from "@/components/query/ParamBar";
import { type SavedQueryBinding } from "@/components/query/SavedQueryBar";
import {
  TabsBar, newTab, readTabs, writeTabs, type EditorTab,
} from "@/components/query/TabsBar";
import { sqlDiagnostics } from "@/components/query/editor/diagnostics";
import { splitStatements, statementAt, findParams } from "@/lib/query/parserClient";
import { cmDialect, engineFamily, type EngineHint } from "@/lib/query/dialect";
import { formatSql } from "@/lib/query/format";
import {
  runWorkbenchQuery, QueryCancelled, type QueryValidation, type TypedQueryResult,
} from "@/lib/api";
import { Button } from "@/components/ui/button";

type EditorApi = { insert: (text: string) => void; focus: () => void; relint: () => void };

/** Stable identity — a fresh `{}` each render would re-fire every memo below it. */
const EMPTY_PARAMS: Record<string, string> = {};

/** SE-1's single-draft key, read once when a connection has no tabs yet. Left in place
 *  rather than deleted after reading: a user who downgrades mid-session should still
 *  find their text, and an orphaned key costs a few hundred bytes. */
function readLegacyDraft(connId: string): string {
  try {
    const raw = localStorage.getItem(`aug.sqledit.draft:${connId}`);
    if (!raw) return "";
    const d = JSON.parse(raw) as { v?: number; sql?: string };
    return typeof d?.sql === "string" ? d.sql : "";
  } catch { return ""; }
}

export function SqlMode({
  connId,
  engine,
  schema,
  defaultSchema,
  onInsertReady,
  onSavedBinding,
  onSavableChange,
  onSchedule,
  onShare,
  toolbar,
}: {
  connId: string;
  engine: EngineHint | null;
  /** `{ "table": ["col", …] }` for completion — owned by the workbench. */
  schema?: Record<string, string[]>;
  defaultSchema?: string;
  /** Hands the workbench's catalog rail a way to insert at this editor's cursor. */
  onInsertReady?: (insert: (text: string) => void) => void;
  /** Published ONCE; reads through refs so a keystroke never re-renders the workbench. */
  onSavedBinding?: (binding: SavedQueryBinding) => void;
  onSavableChange?: (savable: boolean) => void;
  /** SE-4 I — hand this result's SQL to a custom-SQL monitor. */
  onSchedule?: (sql: string) => void;
  /** SE-4 I — copy a link that reopens this query. */
  onShare?: () => void;
  /** Controls the WORKBENCH owns (connection, saved state, panel toggle) rendered
   *  on the tab strip instead of in a bar of their own — see TabsBar's `trailing`. */
  toolbar?: React.ReactNode;
}) {
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activeId, setActiveId] = useState("");
  const [result, setResult] = useState<TypedQueryResult | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [verdict, setVerdict] = useState<QueryValidation | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [historyKey, setHistoryKey] = useState(0);
  // SE-3 F — the in-flight run's abort handle and when it started.
  const abort = useRef<AbortController | null>(null);
  const [startedAt, setStartedAt] = useState(0);
  const [runAllSummary, setRunAllSummary] = useState("");
  // SE-5a — the statement that produced the current error. NOT `sqlText`: a run can be
  // a selection, or one statement of several, and repairing the whole document would
  // hand the model a different query from the one that failed.
  const [failedSql, setFailedSql] = useState("");
  const [statementCount, setStatementCount] = useState(1);
  const cursor = useRef(0);
  const selection = useRef<{ from: number; to: number } | null>(null);
  const editorApi = useRef<EditorApi | null>(null);
  const relint = useRef<(() => void) | null>(null);

  const active = tabs.find(t => t.id === activeId) ?? null;
  const sqlText = active?.sql ?? "";

  // SE-4 H — the `:name` parameters of the CURRENT document, and this tab's values.
  const paramNames = useMemo(() => findParams(sqlText), [sqlText]);

  // The parser runs in a worker, so the count arrives asynchronously; it only drives
  // whether a button is offered, never what runs.
  useEffect(() => {
    let alive = true;
    void splitStatements(sqlText).then(r => {
      if (alive) setStatementCount(r.filter(x => x.text.trim()).length || 1);
    }).catch(() => { if (alive) setStatementCount(1); });
    return () => { alive = false; };
  }, [sqlText]);
  const paramValues = active?.params ?? EMPTY_PARAMS;
  // Only the names still present in the SQL, so a value left behind by a deleted
  // parameter is not silently sent (the server would reject an unknown bind name).
  const boundParams = useMemo(() => {
    const out: Record<string, string> = {};
    for (const n of paramNames) if ((paramValues[n] ?? "").trim()) out[n] = paramValues[n];
    return out;
  }, [paramNames, paramValues]);

  // Built ONCE and read through getters, so a connection or dialect change reaches the
  // linter without rebuilding the editor (which would drop undo history and cursor).
  const connRef = useRef(connId);
  const engineRef = useRef(engine);
  const paramsRef = useRef<Record<string, string>>(EMPTY_PARAMS);
  connRef.current = connId;
  engineRef.current = engine;
  paramsRef.current = boundParams;
  // Params changed but the document did not, so nothing would re-trigger the linter
  // on its own. `relint` is published by the editor pane for exactly this.
  useEffect(() => { relint.current?.(); }, [boundParams]);

  const diagnostics = useMemo(
    () => sqlDiagnostics({
      getConn: () => connRef.current,
      getDialect: () => engineFamily(engineRef.current),
      getParams: () => paramsRef.current,
      onVerdict: setVerdict,
    }),
    [],
  );

  // Tab restore — in an EFFECT, never a useState initializer (hydration rule).
  // Keyed on connId so switching connections swaps tab sets rather than merging them.
  useEffect(() => {
    if (!connId) { setTabs([]); setActiveId(""); return; }
    const stored = readTabs(connId);
    if (stored?.tabs.length) {
      setTabs(stored.tabs);
      setActiveId(stored.activeId && stored.tabs.some(t => t.id === stored.activeId)
        ? stored.activeId : stored.tabs[0].id);
    } else {
      // One-time migration: SE-1 stored a single draft per connection; SE-2 stores
      // tabs. Without this the editor would come up blank for anyone mid-query when
      // the tabs landed — the work is still on disk, just under the old key, which is
      // the worst kind of data loss because it looks like deletion.
      const t = { ...newTab(), sql: readLegacyDraft(connId) };
      setTabs([t]);
      setActiveId(t.id);
    }
    setResult(null);
    setError("");
  }, [connId]);

  // Debounced persist — the editor fires onChange per keystroke.
  useEffect(() => {
    if (!connId || !tabs.length) return;
    const t = setTimeout(() => writeTabs(connId, tabs, activeId), 400);
    return () => clearTimeout(t);
  }, [connId, tabs, activeId]);

  const patchActive = useCallback((patch: Partial<EditorTab>) => {
    setTabs(prev => prev.map(t =>
      t.id === activeId ? { ...t, ...patch, touched: Date.now() } : t));
  }, [activeId]);

  const setSql = useCallback((sql: string) => patchActive({ sql }), [patchActive]);

  const openInNewTab = useCallback((sql: string, name = "Query") => {
    const t = { ...newTab(name), sql };
    setTabs(prev => [...prev, t]);
    setActiveId(t.id);
  }, []);

  const run = useCallback(async () => {
    if (!connId || running) return;
    // Selection wins — an explicit highlight is the user saying "this, exactly".
    let toRun = "";
    const sel = selection.current;
    if (sel && sel.to > sel.from) {
      toRun = sqlText.slice(sel.from, sel.to);
    } else {
      const ranges = await splitStatements(sqlText);
      toRun = statementAt(ranges, cursor.current)?.text ?? sqlText;
    }
    toRun = toRun.trim().replace(/;\s*$/, "");
    if (!toRun) return;

    const ac = new AbortController();
    abort.current = ac;
    setRunning(true);
    setError("");
    setRunAllSummary("");
    setFailedSql("");
    setStartedAt(Date.now());
    try {
      const res = await runWorkbenchQuery(connId, toRun, 500, boundParams, ac.signal);
      setResult(res);
      if (res.error) setFailedSql(toRun);
      // A query that RAN and reported an error is a value, not an exception — the
      // panel shows the engine's own message rather than a generic failure.
      setError(res.error ?? "");
      patchActive({ status: res.error ? "error" : "ok" });
    } catch (e) {
      setResult(null);
      // A cancellation is the user's own decision arriving back at them. Reporting it
      // as a failure would make the button they just pressed look like a malfunction,
      // so the panel returns to its resting state and says nothing.
      if (e instanceof QueryCancelled) {
        patchActive({ status: undefined });
      } else {
        setError(e instanceof Error ? e.message : "Query failed");
        setFailedSql(toRun);
        patchActive({ status: "error" });
      }
    } finally {
      abort.current = null;
      setRunning(false);
      setStartedAt(0);
      // The rail reads the audit log this run just wrote to.
      setHistoryKey(k => k + 1);
    }
  }, [connId, running, sqlText, patchActive, boundParams]);

  /** SE-4 H — run every statement in the buffer, in order, keeping the LAST result.
   *
   *  Sequential and stop-on-error, not parallel: statements in one buffer are written
   *  to be read top-down and often depend on each other, and firing them together
   *  would make the order of a temp table and its use a race. Stopping on the first
   *  failure is the same reasoning — continuing past a broken statement produces
   *  results whose meaning depends on a failure the user has not seen yet.
   *
   *  The roadmap asks for one results TAB per statement (LRU 5). That is a results-
   *  surface change; this ships the execution half and shows the last result plus a
   *  per-statement summary, so "Run all" is usable without pre-empting the tabbed
   *  results design that PR I revisits. */
  const runAll = useCallback(async () => {
    if (!connId || running) return;
    const ranges = await splitStatements(sqlText);
    const statements = ranges
      .map(r => r.text.trim().replace(/;\s*$/, ""))
      .filter(Boolean);
    if (statements.length < 2) { void run(); return; }

    const ac = new AbortController();
    abort.current = ac;
    setRunning(true);
    setError("");
    setFailedSql("");
    setStartedAt(Date.now());
    const done: string[] = [];
    // Which statement is in flight — so a failure hands Quick Fix THAT statement rather
    // than the whole multi-statement document, which is a different query.
    let inFlight = "";
    try {
      for (const [i, stmt] of statements.entries()) {
        inFlight = stmt;
        const res = await runWorkbenchQuery(connId, stmt, 500, boundParams, ac.signal);
        setResult(res);
        if (res.error) {
          setError(`Statement ${i + 1} of ${statements.length} failed: ${res.error}`);
          setFailedSql(stmt);
          patchActive({ status: "error" });
          return;
        }
        done.push(`${i + 1}: ${res.row_count} ${res.row_count === 1 ? "row" : "rows"}`);
        setError("");
      }
      setRunAllSummary(`Ran ${statements.length} statements — ${done.join(" · ")}`);
      patchActive({ status: "ok" });
    } catch (e) {
      if (e instanceof QueryCancelled) {
        setError(`Cancelled after ${done.length} of ${statements.length} statements.`);
        patchActive({ status: undefined });
      } else {
        setError(e instanceof Error ? e.message : "Query failed");
        setFailedSql(inFlight);
        patchActive({ status: "error" });
      }
    } finally {
      abort.current = null;
      setRunning(false);
      setStartedAt(0);
      setHistoryKey(k => k + 1);
    }
  }, [connId, running, sqlText, boundParams, patchActive, run]);

  /** Abort the in-flight fetch. Closing the socket is what reaches the server, which
   *  interrupts the engine — so this stops the QUERY, not just the waiting. */
  const cancel = useCallback(() => abort.current?.abort(), []);

  // The elapsed ticker. It exists because a long query with no clock is
  // indistinguishable from a hung one, and that ambiguity is what makes people
  // reload the page. Only ticks while a run is in flight, and only past a second —
  // a counter that flashes "0s" on every fast query is noise, not information.
  const [elapsed, setElapsed] = useState("");
  useEffect(() => {
    if (!startedAt) { setElapsed(""); return; }
    const tick = () => {
      const s = (Date.now() - startedAt) / 1000;
      setElapsed(s < 1 ? "" : s < 60 ? `${s.toFixed(0)}s` : `${Math.floor(s / 60)}m ${(s % 60).toFixed(0)}s`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  // The run command must see the CURRENT text and cursor. `run` is rebuilt when those
  // change, and the editor calls through this ref, so ⌘↵ never fires a stale closure.
  const runRef = useRef(run);
  runRef.current = run;

  // ── The saved-query bar's binding ───────────────────────────────────────────
  //
  // A SQL-mode save writes `sql` with an EMPTY spec. That is not a lesser save: this
  // mode's query IS its text, and inventing a builder spec for it would claim the
  // composer could reproduce a statement it may not be able to decompile. The empty
  // spec is what routes the query back here when it is loaded.
  const captureRef = useRef<() => { sql: string; spec: Record<string, unknown> } | null>(null);
  const loadRef = useRef<(q: { sql: string; name: string }) => void>(() => {});
  const nameRef = useRef<() => string>(() => "Untitled query");
  captureRef.current = () => (sqlText.trim() ? { sql: sqlText, spec: {} } : null);
  loadRef.current = q => openInNewTab(q.sql, q.name);
  // A tab the user renamed is a name they chose — better than anything derived. Only
  // an untouched tab falls back to reading the query's own FROM clause.
  nameRef.current = () => {
    if (active && active.name && active.name !== "Query") return active.name;
    const m = /\bfrom\s+([A-Za-z_][\w.$"]*)/i.exec(sqlText);
    return m ? `${m[1].replace(/"/g, "")} query` : "Untitled query";
  };

  const savedBinding = useMemo<SavedQueryBinding>(() => ({
    capture: () => captureRef.current?.() ?? null,
    load: q => loadRef.current(q),
    suggestName: () => nameRef.current(),
  }), []);
  useEffect(() => { onSavedBinding?.(savedBinding); }, [onSavedBinding, savedBinding]);

  const savable = !!sqlText.trim();
  useEffect(() => { onSavableChange?.(savable); }, [savable, onSavableChange]);

  // The editor column — tabs, toolbar, and the editor-over-results split.
  const editorPane = (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0 }}>
        <TabsBar
          tabs={tabs}
          activeId={activeId}
          onSelect={setActiveId}
          onNew={() => openInNewTab("")}
          onClose={id => setTabs(prev => {
            const next = prev.filter(t => t.id !== id);
            if (id === activeId && next.length) setActiveId(next[next.length - 1].id);
            return next;
          })}
          onRename={(id, name) => setTabs(prev => prev.map(t => t.id === id ? { ...t, name } : t))}
        />

        <ParamBar
          names={paramNames}
          values={paramValues}
          onChange={next => patchActive({ params: next })}
        />

        <div
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "5px 10px", borderBottom: "1px solid var(--b0)", flexShrink: 0,
          }}
        >
          {/* One control, two states. A separate always-visible Cancel would be dead
              most of the time, and a disabled "Running…" leaves the user watching a
              query they cannot stop — which is the thing this wave exists to fix. */}
          {running ? (
            <Button variant="secondary" size="xs" className="aug-fs-ui"
              title="Stop this query — the engine is interrupted, not just the wait"
              onClick={cancel}>
              Cancel{elapsed && <span style={{ marginLeft: 6, fontVariantNumeric: "tabular-nums" }}>{elapsed}</span>}
            </Button>
          ) : (
            <Button variant="default" size="xs" className="aug-fs-ui"
              title="Runs the selection, or the statement under the cursor (⌘↵)"
              onClick={() => void run()} disabled={!connId}>
              Run  ⌘↵
            </Button>
          )}
          {/* Only offered when there IS more than one statement — a "Run all" beside a
              single statement is a second button for the thing the first one does. */}
          {!running && statementCount > 1 && (
            <Button variant="ghost" size="xs" className="aug-fs-ui"
              title={`Run all ${statementCount} statements in order, stopping at the first error`}
              onClick={() => void runAll()} disabled={!connId}>
              Run all ({statementCount})
            </Button>
          )}
          <Button
            variant="ghost"
            size="xs"
            className="aug-fs-ui"
            title="Format the selection, or the whole query (⌘⇧F)"
            onClick={() => setSql(formatSql(sqlText, engine))}
            disabled={!sqlText.trim()}
          >
            <Icon name="sql" size={14} />
          </Button>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setShowHistory(s => !s)}
            title={showHistory ? "Hide recent queries" : "Recent queries run from this workbench"}
          >
            <Icon name="clock" size={14} />
          </Button>
          {runAllSummary && !error && (
            <span className="aug-fs-ui" style={{ color: "var(--t4)", whiteSpace: "nowrap" }}>
              {runAllSummary}
            </span>
          )}
          <div style={{ flex: 1, minWidth: 0 }} />
          {toolbar}
          {/* The guard battery's own verdict, stated plainly. */}
          {verdict && (
            <span
              style={{
                fontSize: 13, flexShrink: 0, whiteSpace: "nowrap",
                color: verdict.passed ? "var(--t4)" : "var(--amb4)",
              }}
              title={verdict.unchecked
                ? (verdict.note || "The guards cannot read a parameterised query without values.")
                : verdict.passed
                  ? "Fan-out, join and filter value-domain, grain and trust checks all passed"
                  : "Findings are shown in the editor gutter"}
            >
              {/* "Guards clean" rather than "Checked — clean": this endpoint judges
                  fan-out, value-domain, grain and trust — never syntax. */}
              {verdict.unchecked
                ? "Not checked — fill parameters"
                : verdict.passed
                  ? "Guards clean"
                  : `Checked — ${verdict.issue_count} ${verdict.issue_count === 1 ? "note" : "notes"}`}
            </span>
          )}
        </div>

        <ResizableSplit
          storageKey="sqlmode"
          direction="vertical"
          initial={260}
          min={120}
          max={720}
          style={{ flex: 1, minHeight: 0 }}
          left={
            <SqlEditorPane
              value={sqlText}
              onChange={setSql}
              onRun={() => void runRef.current()}
              onFormat={(text) => formatSql(text, engineRef.current)}
              onCursor={(pos, sel) => { cursor.current = pos; selection.current = sel; }}
              onReady={api => {
                editorApi.current = api;
                relint.current = api.relint;
                onInsertReady?.(api.insert);
              }}
              schema={schema}
              defaultSchema={defaultSchema}
              dialect={cmDialect(engine)}
              diagnostics={diagnostics}
            />
          }
          right={
            <ResultsPanel
              result={result}
              error={error}
              running={running}
              connId={connId}
              onSchedule={onSchedule}
              onShare={onShare}
              failedSql={failedSql}
              onApplyFix={(fixed) => {
                // Into the document, never into a run. Applying is the user accepting a
                // proposal to EDIT; whether it executes is still their next decision.
                // `setSql` is enough on its own — SqlEditorPane reconciles an externally
                // changed `value` back into the CM6 document, the same path a tab switch
                // and a restored draft take.
                setSql(fixed);
                setError("");
                setFailedSql("");
              }}
            />
          }
        />
    </div>
  );

  // `resizePane="second"` because history sits on the RIGHT: sizing the left pane
  // would make the rail's width whatever was left over, so it would drift every time
  // the window changed rather than staying where the user put it.
  //
  // `collapsed` rather than rendering the split only when history is open: the
  // conditional form changed the element tree, so every toggle remounted the editor
  // beside it and took the undo history and cursor with it.
  return (
    <ResizableSplit
      storageKey="sqlmode.history"
      resizePane="second"
      initial={280}
      min={200}
      max={560}
      collapsed={!showHistory}
      style={{ flex: 1, minWidth: 0, minHeight: 0 }}
      left={editorPane}
      right={
        <HistoryRail
          connId={connId}
          refreshKey={historyKey}
          onRestore={sql => openInNewTab(sql, "History")}
        />
      }
    />
  );
}
