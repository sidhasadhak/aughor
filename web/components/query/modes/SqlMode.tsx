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
import {
  TabsBar, newTab, readTabs, writeTabs, type EditorTab,
} from "@/components/query/TabsBar";
import { sqlDiagnostics } from "@/components/query/editor/diagnostics";
import { splitStatements, statementAt } from "@/lib/query/parserClient";
import { cmDialect, engineFamily, type EngineHint } from "@/lib/query/dialect";
import { formatSql } from "@/lib/query/format";
import { runWorkbenchQuery, type QueryValidation, type TypedQueryResult } from "@/lib/api";
import { Button } from "@/components/ui/button";

type EditorApi = { insert: (text: string) => void; focus: () => void };

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
}: {
  connId: string;
  engine: EngineHint | null;
  /** `{ "table": ["col", …] }` for completion — owned by the workbench. */
  schema?: Record<string, string[]>;
  defaultSchema?: string;
  /** Hands the workbench's catalog rail a way to insert at this editor's cursor. */
  onInsertReady?: (insert: (text: string) => void) => void;
}) {
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activeId, setActiveId] = useState("");
  const [result, setResult] = useState<TypedQueryResult | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [verdict, setVerdict] = useState<QueryValidation | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [historyKey, setHistoryKey] = useState(0);
  const cursor = useRef(0);
  const selection = useRef<{ from: number; to: number } | null>(null);
  const editorApi = useRef<EditorApi | null>(null);

  const active = tabs.find(t => t.id === activeId) ?? null;
  const sqlText = active?.sql ?? "";

  // Built ONCE and read through getters, so a connection or dialect change reaches the
  // linter without rebuilding the editor (which would drop undo history and cursor).
  const connRef = useRef(connId);
  const engineRef = useRef(engine);
  connRef.current = connId;
  engineRef.current = engine;
  const diagnostics = useMemo(
    () => sqlDiagnostics({
      getConn: () => connRef.current,
      getDialect: () => engineFamily(engineRef.current),
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

    setRunning(true);
    setError("");
    try {
      const res = await runWorkbenchQuery(connId, toRun);
      setResult(res);
      // A query that RAN and reported an error is a value, not an exception — the
      // panel shows the engine's own message rather than a generic failure.
      setError(res.error ?? "");
      patchActive({ status: res.error ? "error" : "ok" });
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : "Query failed");
      patchActive({ status: "error" });
    } finally {
      setRunning(false);
      // The rail reads the audit log this run just wrote to.
      setHistoryKey(k => k + 1);
    }
  }, [connId, running, sqlText, patchActive]);

  // The run command must see the CURRENT text and cursor. `run` is rebuilt when those
  // change, and the editor calls through this ref, so ⌘↵ never fires a stale closure.
  const runRef = useRef(run);
  runRef.current = run;

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

        <div
          style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "6px 10px", borderBottom: "1px solid var(--b0)", flexShrink: 0,
          }}
        >
          <Button variant="default" size="xs" className="aug-fs-ui"
            title="Runs the selection, or the statement under the cursor (⌘↵)"
            onClick={() => void run()} disabled={!connId || running}>
            {running ? "Running…" : "Run  ⌘↵"}
          </Button>
          <Button
            variant="ghost"
            size="xs"
            className="aug-fs-ui"
            title="Format the selection, or the whole query (⌘⇧F)"
            onClick={() => setSql(formatSql(sqlText, engine))}
            disabled={!sqlText.trim()}
          >
            Format
          </Button>
          <Button
            variant="ghost"
            size="xs"
            className="aug-fs-ui"
            onClick={() => setShowHistory(s => !s)}
            title="Recent queries run from this workbench"
          >
            {showHistory ? "Hide history" : "History"}
          </Button>
          <div style={{ flex: 1, minWidth: 0 }} />
          {/* The guard battery's own verdict, stated plainly. */}
          {verdict && (
            <span
              style={{
                fontSize: 13, flexShrink: 0, whiteSpace: "nowrap",
                color: verdict.passed ? "var(--t4)" : "var(--amb4)",
              }}
              title={verdict.passed
                ? "Fan-out, join and filter value-domain, grain and trust checks all passed"
                : "Findings are shown in the editor gutter"}
            >
              {/* "Guards clean" rather than "Checked — clean": this endpoint judges
                  fan-out, value-domain, grain and trust — never syntax. */}
              {verdict.passed
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
              onReady={api => { editorApi.current = api; onInsertReady?.(api.insert); }}
              schema={schema}
              defaultSchema={defaultSchema}
              dialect={cmDialect(engine)}
              diagnostics={diagnostics}
            />
          }
          right={<ResultsPanel result={result} error={error} running={running} />}
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
