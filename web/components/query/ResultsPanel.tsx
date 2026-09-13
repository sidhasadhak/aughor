"use client";

/**
 * SE-1 — the results panel: the grid plus the facts about the run.
 * SE-4 I — plus filters over the returned rows, a chart view, and the ways out
 * (pin, schedule, share).
 * SE-8B — restructured into Databricks' output pane: a statement pager on the left
 * («Results N of M» — "Run all" keeps EVERY statement's rows now, not just the last),
 * a tab strip (Table, one tab per visualization, «+»), and the grid tools as a
 * right-aligned icon cluster on the header instead of buttons in the footer.
 *
 * Errors render INLINE here, never as a toast. A failed query is the primary content
 * of this pane at that moment — a toast would put the one thing the user needs to read
 * on a timer, next to the editor they need to fix. It also keeps the failure visible
 * while they edit, which is when it is actually useful.
 *
 * The footer states what the run cost and whether it is complete. `truncated` is the
 * load-bearing one: the server's n+1 probe row is what makes it honest, so "first 500"
 * means there provably are more, not that we stopped counting.
 *
 * **The chart is `ResultChartCard`, not a new builder** — the one chart surface the
 * whole platform shares. SE-8B mounts one per visualization TAB, each seeded with its
 * own config and KEPT MOUNTED behind `hidden` on tab switch: the card captures its
 * seed once at mount, so unmounting a tab would discard the chart the user just built.
 * Visualization tabs describe the CURRENT rows — paging to another statement's result
 * re-draws them over that set, and an incompatible pick degrades rather than throws
 * (the card's own rule).
 */
import { useDeferredValue, useMemo, useState } from "react";
import { formatCount } from "@/lib/format";
import { ResultsGrid } from "@/components/query/ResultsGrid";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { type VizConfig } from "@/components/charts/vizConfig";
import { ResultFilterBar, type ActiveFilter } from "@/components/query/ResultFilterBar";
import { QuickFixPanel } from "@/components/query/QuickFixPanel";
import { SchedulePopover } from "@/components/query/SchedulePopover";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { csvFilename, downloadText } from "@/lib/query/csv";
import { EXTRACTORS, extractorById, guessTableName } from "@/lib/query/extractors";
import { applyFilters } from "@/lib/query/resultFilter";
import type { TypedQueryResult } from "@/lib/api";

const noteStyle: React.CSSProperties = { fontSize: 13, color: "var(--t3)" };

// Module-level constants, not inline `[]`: a fresh array each render would be a new
// dependency for the filter memo, so it would recompute on every parent render.
const EMPTY_COLS: string[] = [];
const EMPTY_ROWS: TypedQueryResult["rows"] = [];

/** A card title from the SQL — the first table named, else a generic label. Cheap and
 *  deterministic; the user can rename the card on the dashboard. */
function pinTitle(sql: string): string {
  const m = /\bfrom\s+([a-zA-Z_][\w.]*)/i.exec(sql);
  return m ? `Query — ${m[1]}` : "Query result";
}

/** One visualization tab. The config is written back by the card's own editor, so
 *  Duplicate copies the chart as it stands, not as it started. */
interface VizTab { id: string; name: string; config: VizConfig }

function newVizId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `viz-${Math.random().toString(36).slice(2)}`;
}

export function ResultsPanel({
  results,
  resultIdx,
  onResultIdx,
  error,
  running,
  connId,
  onSchedule,
  onShare,
  failedSql,
  onApplyFix,
  maximized,
  onToggleMaximize,
}: {
  /** SE-8B — every statement's result, in run order. One entry for a single run. */
  results: TypedQueryResult[];
  resultIdx: number;
  onResultIdx: (i: number) => void;
  error: string;
  running: boolean;
  connId?: string;
  /** Opens a custom-SQL monitor prefilled from this result's SQL. */
  onSchedule?: (sql: string) => void;
  /** Copies a deep link back to this query. */
  onShare?: () => void;
  /** SE-5a — the statement that produced `error`. Passed separately because a failed run
   *  leaves no usable result, so the SQL is not otherwise reachable from here. */
  failedSql?: string;
  /** SE-5a — put an accepted proposal into the editor. Never called without a click. */
  onApplyFix?: (sql: string) => void;
  /** SE-8B — the ⤢ button: the editor collapses and the results take the column. */
  maximized?: boolean;
  onToggleMaximize?: () => void;
}) {
  // "" | "ok" | "fail" — a click must always produce a visible outcome.
  const [copyState, setCopyState] = useState<"" | "ok" | "fail">("");
  const [showExport, setShowExport] = useState(false);
  const [filters, setFilters] = useState<ActiveFilter[]>([]);
  const [showFilters, setShowFilters] = useState(false);
  const [pinState, setPinState] = useState<"" | "busy" | "ok" | "fail">("");
  // SE-8B — the tab strip: "table" or a visualization's id.
  const [vizTabs, setVizTabs] = useState<VizTab[]>([]);
  const [activeView, setActiveView] = useState("table");
  const [vizMenu, setVizMenu] = useState("");        // viz id whose ⌄ menu is open
  const [renaming, setRenaming] = useState("");      // viz id being renamed
  const [renameDraft, setRenameDraft] = useState("");

  const result = results[resultIdx] ?? null;
  const columns = result?.columns ?? EMPTY_COLS;
  const rawRows = result?.rows ?? EMPTY_ROWS;
  // Filtering runs over every returned row on each keystroke. Deferred so typing stays
  // responsive on a full-limit result — the grid catching up a frame late is a far
  // better trade than the input stuttering.
  const deferredFilters = useDeferredValue(filters);
  const rows = useMemo(() => {
    if (!deferredFilters.length) return rawRows;
    return applyFilters(
      rawRows,
      deferredFilters.map((f) => f.clause).filter((c): c is NonNullable<typeof c> => !!c),
      deferredFilters.map((f) => f.rank).filter((r): r is NonNullable<typeof r> => !!r),
    );
  }, [rawRows, deferredFilters]);

  if (running && !result) {
    return <div style={{ ...noteStyle, padding: "12px 14px" }}>Running…</div>;
  }

  if (error) {
    return (
      <div style={{ padding: "12px 14px", overflow: "auto" }}>
        {/* `aug-label` stays on the TEXT, never on a row that contains the Quick Fix
            panel: the class carries `text-transform: uppercase`, and nesting the panel
            inside it rendered the proposed SQL as `SELECT BRAND_NAEM …`. A diff exists to
            be read literally — and SQL identifiers can be case-sensitive, so an
            upper-cased diff is not merely ugly, it shows text the document does not
            contain. */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <span className="aug-label" style={{ color: "var(--red4)" }}>Query failed</span>
        </div>

        {/* SE-5a — offered only when there is a statement AND a connection to repair it
            against. It sits with the error because that is the moment it means something,
            and as a BLOCK rather than inside the heading row: the ready state is a diff,
            and a diff squeezed into a flex row beside a label wraps every line. It
            proposes; it never applies on its own. */}
        {connId && failedSql && onApplyFix && (
          <div style={{ marginBottom: 8 }}>
            <QuickFixPanel
              connId={connId} sql={failedSql} error={error} onApply={onApplyFix} />
          </div>
        )}
        <pre
          style={{
            margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word",
            fontFamily: "var(--font-code, monospace)", fontSize: 13,
            color: "var(--t2)", background: "var(--bg-1)",
            border: "1px solid var(--b1)", borderRadius: "var(--r2)", padding: 10,
          }}
        >
          {error}
        </pre>
      </div>
    );
  }

  if (!result) {
    return (
      <div style={{ ...noteStyle, padding: "12px 14px" }}>
        Results appear here. ⌘↵ runs the statement under the cursor.
      </div>
    );
  }

  // A statement that returned no grid (DDL, or a genuinely empty result) still has a
  // footer worth reading — how long it took, and that it really did return nothing.
  const empty = result.row_count === 0;
  // Filtered everything away is NOT the same as "the query returned nothing", and saying
  // "No rows returned" for it would blame the warehouse for the user's own chip.
  const filteredOut = !empty && rows.length === 0;

  /** Render the CURRENT rows — filtered, if filters are on — through one extractor.
   *  Filters narrow what is on screen, and exporting what is not on screen would be a
   *  different result set wearing the same button. */
  const renderAs = (id: string) =>
    extractorById(id).render(columns, rows, guessTableName(result?.sql ?? ""));

  const copyAs = (id: string) => {
    const settle = (s: "ok" | "fail") => { setCopyState(s); setTimeout(() => setCopyState(""), 1600); };
    // The clipboard API rejects on an insecure origin, without focus, or when
    // permission is denied. Swallowing that leaves the user clicking a button that
    // does nothing and says nothing — so the failure is SHOWN, and the download
    // (which needs no permission) sits beside every format.
    const write = navigator.clipboard?.writeText(renderAs(id));
    if (write) write.then(() => settle("ok")).catch(() => settle("fail"));
    else settle("fail");
  };

  const downloadAs = (id: string) => {
    const x = extractorById(id);
    downloadText(csvFilename("result").replace(/\.csv$/, `.${x.ext}`), renderAs(id), x.mime);
  };

  const addViz = () => {
    const v: VizTab = { id: newVizId(), name: `Visualization ${vizTabs.length + 1}`, config: {} };
    setVizTabs(prev => [...prev, v]);
    setActiveView(v.id);
  };

  const patchViz = (id: string, patch: Partial<VizTab>) =>
    setVizTabs(prev => prev.map(v => v.id === id ? { ...v, ...patch } : v));

  const removeViz = (id: string) => {
    setVizTabs(prev => prev.filter(v => v.id !== id));
    if (activeView === id) setActiveView("table");
    setVizMenu("");
  };

  const duplicateViz = (id: string) => {
    const src = vizTabs.find(v => v.id === id);
    if (!src) return;
    const copy: VizTab = { id: newVizId(), name: `${src.name} copy`, config: { ...src.config } };
    setVizTabs(prev => [...prev, copy]);
    setActiveView(copy.id);
    setVizMenu("");
  };

  const filtersVisible = showFilters || filters.length > 0;
  const headerIcon = (name: Parameters<typeof Icon>[0]["name"], title: string,
    onClick: () => void, active = false, testid?: string) => (
    <Button variant={active ? "secondary" : "ghost"} size="xs" title={title}
      onClick={onClick} data-testid={testid}>
      <Icon name={name} size={14} />
    </Button>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}>
      {/* SE-8B — the output header: pager · view tabs · tool cluster, Databricks'
          own top row of the results pane. */}
      <div style={{
        display: "flex", alignItems: "center", gap: 2, padding: "3px 8px",
        borderBottom: "1px solid var(--b0)", flexShrink: 0,
      }}>
        {results.length > 1 && (
          <span style={{ display: "flex", alignItems: "center", gap: 2, marginRight: 4, flexShrink: 0 }}>
            <Button variant="ghost" size="xs" title="Previous statement's result"
              disabled={resultIdx === 0} onClick={() => onResultIdx(resultIdx - 1)}>
              <Icon name="chevl" size={13} />
            </Button>
            <span className="aug-fs-ui" style={{ color: "var(--t3)", whiteSpace: "nowrap" }}>
              Results {resultIdx + 1} of {results.length}
            </span>
            <Button variant="ghost" size="xs" title="Next statement's result"
              disabled={resultIdx >= results.length - 1} onClick={() => onResultIdx(resultIdx + 1)}>
              <Icon name="chevr" size={13} />
            </Button>
          </span>
        )}

        <Button variant={activeView === "table" ? "secondary" : "ghost"} size="xs"
          className="aug-fs-ui" onClick={() => setActiveView("table")}>
          Table
        </Button>
        {vizTabs.map(v => (
          <span key={v.id} style={{ position: "relative", display: "flex", alignItems: "center", flexShrink: 0 }}>
            {renaming === v.id ? (
              <input
                className="aug-input aug-fs-ui" autoFocus value={renameDraft}
                onChange={e => setRenameDraft(e.target.value)}
                onBlur={() => { if (renameDraft.trim()) patchViz(v.id, { name: renameDraft.trim() }); setRenaming(""); }}
                onKeyDown={e => {
                  if (e.key === "Enter") { if (renameDraft.trim()) patchViz(v.id, { name: renameDraft.trim() }); setRenaming(""); }
                  if (e.key === "Escape") setRenaming("");
                }}
                style={{ width: 120 }}
              />
            ) : (
              <Button variant={activeView === v.id ? "secondary" : "ghost"} size="xs"
                className="aug-fs-ui"
                onClick={() => setActiveView(v.id)}
                onDoubleClick={() => { setRenaming(v.id); setRenameDraft(v.name); }}
                title="Double-click to rename">
                {v.name}
              </Button>
            )}
            {activeView === v.id && renaming !== v.id && (
              <Button variant="ghost" size="xs" title="Visualization options"
                aria-label="Visualization options"
                onClick={() => setVizMenu(m => m === v.id ? "" : v.id)}
                style={{ paddingLeft: 2, paddingRight: 2 }}>
                <Icon name="chevd" size={12} />
              </Button>
            )}
            {vizMenu === v.id && (
              <>
                <div style={{ position: "fixed", inset: 0, zIndex: 40 }} onClick={() => setVizMenu("")} />
                <div className="aug-fs-ui" style={{
                  position: "absolute", top: "100%", left: 0, zIndex: 41, marginTop: 4,
                  minWidth: 150, padding: 5, background: "var(--bg-2)",
                  border: "1px solid var(--b2)", borderRadius: "var(--r2)", boxShadow: "var(--shadow-md)",
                }}>
                  <Button variant="ghost" size="xs" className="aug-fs-ui"
                    style={{ width: "100%", justifyContent: "flex-start" }}
                    onClick={() => { setRenaming(v.id); setRenameDraft(v.name); setVizMenu(""); }}>
                    Rename
                  </Button>
                  <Button variant="ghost" size="xs" className="aug-fs-ui"
                    style={{ width: "100%", justifyContent: "flex-start" }}
                    onClick={() => duplicateViz(v.id)}>
                    Duplicate
                  </Button>
                  <Button variant="ghost" size="xs" className="aug-fs-ui"
                    style={{ width: "100%", justifyContent: "flex-start", color: "var(--red4)" }}
                    onClick={() => removeViz(v.id)}>
                    Remove
                  </Button>
                </div>
              </>
            )}
          </span>
        ))}
        {!empty && (
          <Button variant="ghost" size="xs" title="Add a visualization of these rows"
            aria-label="Add a visualization" onClick={addViz} data-testid="results-add-viz">
            <Icon name="plus" size={13} />
          </Button>
        )}

        <div style={{ flex: 1, minWidth: 8 }} />

        {/* The tool cluster, right-aligned like the reference pane: filter · export ·
            maximize. Find-in-results stays ⌘F inside the grid, which owns the rows. */}
        {!empty && headerIcon("filter",
          filtersVisible ? "Hide the filter bar" : "Filter these rows — plain phrases, chips, OR",
          () => setShowFilters(v => !v), filtersVisible, "results-filter-toggle")}
        {!empty && (
          <span style={{ position: "relative" }}>
            {headerIcon("download",
              filters.length ? "Copy or download the FILTERED rows" : "Copy or download these rows",
              () => setShowExport(v => !v), showExport, "results-export")}
            {copyState && (
              <span className="aug-fs-xs" style={{
                position: "absolute", top: "100%", right: 0, marginTop: 2, whiteSpace: "nowrap",
                color: copyState === "ok" ? "var(--grn4)" : "var(--red4)",
              }}>
                {copyState === "ok" ? "Copied" : "Copy failed"}
              </span>
            )}
            {showExport && (
              <>
                <div style={{ position: "fixed", inset: 0, zIndex: 20 }} onClick={() => setShowExport(false)} />
                <div className="aug-fs-sm" style={{
                  position: "absolute", top: "100%", right: 0, zIndex: 21, marginTop: 4,
                  minWidth: 230, padding: 5, background: "var(--bg-2)",
                  border: "1px solid var(--b2)", borderRadius: "var(--r2)", boxShadow: "var(--shadow-md)",
                }}>
                  {EXTRACTORS.map(x => (
                    <div key={x.id} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <span style={{ flex: 1, padding: "3px 7px", color: "var(--t2)" }}>{x.label}</span>
                      <Button variant="ghost" size="xs" title={`Copy as ${x.label}`}
                        onClick={() => { copyAs(x.id); setShowExport(false); }}>Copy</Button>
                      <Button variant="ghost" size="xs" title={`Download as ${x.label}`}
                        onClick={() => { downloadAs(x.id); setShowExport(false); }}>File</Button>
                    </div>
                  ))}
                </div>
              </>
            )}
          </span>
        )}
        {onToggleMaximize && headerIcon("expand",
          maximized ? "Bring the editor back" : "Give the results the whole column",
          onToggleMaximize, !!maximized, "results-maximize")}
      </div>

      {!empty && filtersVisible && (
        <ResultFilterBar
          columns={columns}
          filters={filters}
          onChange={setFilters}
          shown={rows.length}
          total={rawRows.length}
        />
      )}

      {/* The GRID scrolls, not this wrapper: a second scroll container above a
          virtualized list is what makes the virtualizer mount every row. */}
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        {empty ? (
          <div style={{ ...noteStyle, padding: "12px 14px" }}>
            No rows returned.
          </div>
        ) : filteredOut ? (
          <div style={{ ...noteStyle, padding: "12px 14px" }}>
            No rows match these filters — {formatCount(rawRows.length)} returned by the query.
          </div>
        ) : (
          <>
            <div style={{ flex: 1, minHeight: 0, display: activeView === "table" ? "flex" : "none", flexDirection: "column" }}>
              <ResultsGrid
                columns={columns}
                columnsTyped={result.columns_typed}
                rows={rows}
              />
            </div>
            {/* Every viz stays MOUNTED — the card seeds its controls once, so an
                unmounted tab would come back as a default chart. `display:none`, the
                same trick the workbench plays with its mode panes. */}
            {vizTabs.map(v => (
              <div key={v.id} style={{
                flex: 1, minHeight: 0, overflow: "auto", padding: "8px 12px",
                display: activeView === v.id ? "block" : "none",
              }}>
                {/* No `fillHeight`: it is a PIXEL height, not a boolean, and this pane is
                    resizable — pinning a number here would fight the splitter. The wrapper
                    scrolls instead, so the chart keeps its natural size at any pane height. */}
                <ResultChartCard
                  columns={columns} rows={rows}
                  config={v.config}
                  onConfigChange={cfg => patchViz(v.id, { config: cfg })}
                />
              </div>
            ))}
          </>
        )}
      </div>

      {(result.caveats?.length ?? 0) > 0 && (
        <div
          style={{
            ...noteStyle, padding: "6px 14px", color: "var(--amb4)",
            borderTop: "1px solid var(--b0)",
          }}
        >
          {result.caveats!.length === 1
            ? result.caveats![0]
            : `Checked — ${result.caveats!.length} notes: ${result.caveats!.join(" · ")}`}
        </div>
      )}

      <div
        style={{
          ...noteStyle, display: "flex", alignItems: "center", gap: 10,
          padding: "6px 14px", borderTop: "1px solid var(--b1)", flexShrink: 0,
        }}
      >
        {/* When a filter is active the footer must not still report the RUN's row count:
            it sits directly under the grid, so "4 rows" above two visible rows reads as a
            description of what you are looking at. The run's own count stays reachable as
            the "of N" — nothing is hidden, it just stops contradicting the grid. */}
        <span>
          {rows.length === rawRows.length
            ? `${formatCount(result.row_count)} ${result.row_count === 1 ? "row" : "rows"}`
            : `${formatCount(rows.length)} of ${formatCount(rawRows.length)} rows`}
        </span>
        <span>·</span>
        <span>{Math.round(result.duration_ms)} ms</span>
        {result.truncated && (
          <>
            <span>·</span>
            <span style={{ color: "var(--amb4)" }}>
              truncated — more rows exist beyond this limit
            </span>
          </>
        )}
        {result.cached && (<><span>·</span><span>cached</span></>)}
        <div style={{ flex: 1 }} />

        {!empty && connId && (
          <Button
            variant="ghost" size="xs" className="aug-fs-ui"
            disabled={pinState === "busy"}
            title="Pin this query to the dashboard as a card"
            onClick={async () => {
              setPinState("busy");
              try {
                const { pinQueryToDashboard } = await import("@/lib/api");
                await pinQueryToDashboard(connId, result.sql, pinTitle(result.sql));
                setPinState("ok");
              } catch {
                setPinState("fail");
              }
              setTimeout(() => setPinState(""), 1600);
            }}
          >
            {pinState === "ok" ? "Pinned" : pinState === "fail" ? "Pin failed" : "Pin"}
          </Button>
        )}
        {/* SE-8D — schedules are created HERE now; onSchedule survives as the
            "Open in Monitors" path for thresholds and anomaly rules. */}
        {connId && (
          <SchedulePopover connId={connId} sql={result.sql} onOpenMonitors={onSchedule} />
        )}
        {onShare && (
          <Button
            variant="ghost" size="xs" className="aug-fs-ui"
            title="Copy a link that reopens this query"
            onClick={onShare}
          >
            Share
          </Button>
        )}
        {result.receipt_id && (
          <a
            href={`/receipt/${encodeURIComponent(result.receipt_id)}`}
            target="_blank"
            rel="noreferrer"
            style={{ color: "var(--t3)", textDecoration: "underline" }}
            title="The signed provenance record for this run"
          >
            receipt
          </a>
        )}
      </div>
    </div>
  );
}
