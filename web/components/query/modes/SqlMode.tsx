"use client";

/**
 * SE-1 — SQL mode: the editor over the results, and the run logic between them.
 *
 * This component owns the one decision the editor deliberately does not: **what runs**.
 * The rule is selection-if-any, else the statement under the cursor, else the whole
 * buffer. Keeping it here rather than in `SqlEditorPane` means the editor stays a text
 * surface and the workbench stays the thing that knows about connections and queries.
 *
 * Drafts persist per connection so a layer switch or a reload does not lose work in
 * progress. Two rules from this codebase apply and both are load-bearing: the draft is
 * NEVER read in a `useState` initializer (that reads localStorage during render and
 * breaks hydration), and every access is wrapped — a disabled-storage browser must
 * degrade to a working editor with no persistence, not to a blank screen.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ResizableSplit } from "@/components/ResizableSplit";
import { SqlEditorPane } from "@/components/query/editor/SqlEditorPane";
import { ResultsPanel } from "@/components/query/ResultsPanel";
import { sqlDiagnostics } from "@/components/query/editor/diagnostics";
import { splitStatements, statementAt } from "@/lib/query/parserClient";
import { cmDialect, engineFamily, type EngineHint } from "@/lib/query/dialect";
import { formatSql } from "@/lib/query/format";
import { runWorkbenchQuery, type QueryValidation, type TypedQueryResult } from "@/lib/api";
import { Button } from "@/components/ui/button";

/** Versioned so a future shape change can be detected and discarded rather than
 *  mis-parsed into a broken editor. */
const DRAFT_VERSION = 1;
interface Draft { v: number; sql: string; cursor: number }

function draftKey(connId: string): string {
  return `aug.sqledit.draft:${connId}`;
}

function readDraft(connId: string): Draft | null {
  try {
    const raw = localStorage.getItem(draftKey(connId));
    if (!raw) return null;
    const d = JSON.parse(raw) as Draft;
    return d && d.v === DRAFT_VERSION && typeof d.sql === "string" ? d : null;
  } catch { return null; }
}

function writeDraft(connId: string, sql: string, cursor: number): void {
  try {
    localStorage.setItem(draftKey(connId), JSON.stringify({ v: DRAFT_VERSION, sql, cursor }));
  } catch { /* storage disabled — the editor still works, it just won't persist */ }
}

export function SqlMode({
  connId,
  engine,
  schema,
  defaultSchema,
}: {
  connId: string;
  engine: EngineHint | null;
  /** `{ "table": ["col", …] }` for completion — owned by the workbench. */
  schema?: Record<string, string[]>;
  defaultSchema?: string;
}) {
  const [sqlText, setSqlText] = useState("");
  const [result, setResult] = useState<TypedQueryResult | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [verdict, setVerdict] = useState<QueryValidation | null>(null);
  const cursor = useRef(0);
  const selection = useRef<{ from: number; to: number } | null>(null);

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

  // Draft restore — in an EFFECT, never a useState initializer (hydration rule).
  // Keyed on connId so switching connections swaps drafts rather than merging them.
  useEffect(() => {
    if (!connId) return;
    const d = readDraft(connId);
    setSqlText(d?.sql ?? "");
    setResult(null);
    setError("");
  }, [connId]);

  // Debounced persist. The editor fires onChange per keystroke; writing localStorage
  // that often is wasteful and, on a large buffer, visibly janky.
  useEffect(() => {
    if (!connId) return;
    const t = setTimeout(() => writeDraft(connId, sqlText, cursor.current), 400);
    return () => clearTimeout(t);
  }, [connId, sqlText]);

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
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : "Query failed");
    } finally {
      setRunning(false);
    }
  }, [connId, running, sqlText]);

  // The run command must see the CURRENT text and cursor. `run` is rebuilt when those
  // change, and the editor calls through this ref, so ⌘↵ never fires a stale closure.
  const runRef = useRef(run);
  runRef.current = run;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div
        style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "6px 10px", borderBottom: "1px solid var(--b0)", flexShrink: 0,
        }}
      >
        <Button variant="default" size="xs" onClick={() => void run()} disabled={!connId || running}>
          {running ? "Running…" : "Run  ⌘↵"}
        </Button>
        <Button
          variant="ghost"
          size="xs"
          title="Format the selection, or the whole query (⌘⇧F)"
          onClick={() => setSqlText(prev => formatSql(prev, engine))}
          disabled={!sqlText.trim()}
        >
          Format
        </Button>
        <span style={{ fontSize: 11, color: "var(--t4)" }}>
          Runs the selection, or the statement under the cursor.
        </span>
        <div style={{ flex: 1 }} />
        {/* The guard battery's own verdict, stated plainly. "Checked — clean" is worth
            as much as a warning count: it says the checks RAN, which silence never does. */}
        {verdict && (
          <span
            style={{
              fontSize: 11,
              color: verdict.passed ? "var(--t4)" : "var(--amb4)",
            }}
            title={verdict.passed
              ? "Fan-out, join and filter value-domain, grain and trust checks all passed"
              : "Findings are shown in the editor gutter"}
          >
            {/* "Guards clean" rather than "Checked — clean": this endpoint judges
                fan-out, value-domain, grain and trust — never syntax. Claiming the
                query is fine when only the guards passed is the kind of overclaim
                the receipts exist to prevent. */}
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
            onChange={setSqlText}
            onRun={() => void runRef.current()}
            onFormat={(text) => formatSql(text, engineRef.current)}
            onCursor={(pos, sel) => { cursor.current = pos; selection.current = sel; }}
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
}
