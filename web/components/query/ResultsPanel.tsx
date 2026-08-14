"use client";

/**
 * SE-1 — the results panel: the grid plus the facts about the run.
 * SE-4 I — plus filters over the returned rows, a chart view, and the ways out
 * (pin, schedule, share).
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
 * **The chart is `ResultChartCard`, not a new builder.** The roadmap called for "an
 * ECharts builder seeded with the result columns"; that component already exists, is
 * the chart surface for chat, deep-analysis reports, the briefing cockpit and pinned
 * cards, and already carries chart-type inference, the chart/table/pivot switch, the
 * viz editor panel, and the `/query/postproc` transforms. The workbench was the ONE
 * result surface without it. Building a second one would have split the vocabulary in
 * exactly the way PR E just finished un-splitting for highlighters and exporters.
 */
import { useDeferredValue, useMemo, useState } from "react";
import { formatCount } from "@/lib/format";
import { ResultsGrid } from "@/components/query/ResultsGrid";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { ResultFilterBar, type ActiveFilter } from "@/components/query/ResultFilterBar";
import { Button } from "@/components/ui/button";
import { toCsv, toTsv, csvFilename, downloadCsv } from "@/lib/query/csv";
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

export function ResultsPanel({
  result,
  error,
  running,
  connId,
  onSchedule,
  onShare,
}: {
  result: TypedQueryResult | null;
  error: string;
  running: boolean;
  connId?: string;
  /** Opens a custom-SQL monitor prefilled from this result's SQL. */
  onSchedule?: (sql: string) => void;
  /** Copies a deep link back to this query. */
  onShare?: () => void;
}) {
  // "" | "ok" | "fail" — a click must always produce a visible outcome.
  const [copyState, setCopyState] = useState<"" | "ok" | "fail">("");
  const [view, setView] = useState<"grid" | "chart">("grid");
  const [filters, setFilters] = useState<ActiveFilter[]>([]);
  const [pinState, setPinState] = useState<"" | "busy" | "ok" | "fail">("");

  const columns = result?.columns ?? EMPTY_COLS;
  const rawRows = result?.rows ?? EMPTY_ROWS;
  // Filtering runs over every returned row on each keystroke. Deferred so typing stays
  // responsive on a full 500-row result — the grid catching up a frame late is a far
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
        <div className="aug-label" style={{ color: "var(--red4)", marginBottom: 6 }}>
          Query failed
        </div>
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

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}>
      {!empty && (
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
        ) : view === "chart" ? (
          <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "8px 12px" }}>
            {/* No `fillHeight`: it is a PIXEL height, not a boolean, and this pane is
                resizable — pinning a number here would fight the splitter. The wrapper
                scrolls instead, so the chart keeps its natural size at any pane height. */}
            <ResultChartCard columns={columns} rows={rows} />
          </div>
        ) : (
          <ResultsGrid
            columns={columns}
            columnsTyped={result.columns_typed}
            rows={rows}
          />
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

        {!empty && (
          <Button
            variant="ghost" size="xs" className="aug-fs-ui"
            title={view === "grid" ? "Chart these rows" : "Back to the grid"}
            onClick={() => setView(view === "grid" ? "chart" : "grid")}
          >
            {view === "grid" ? "Chart" : "Grid"}
          </Button>
        )}
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
        {onSchedule && (
          <Button
            variant="ghost" size="xs" className="aug-fs-ui"
            title="Watch this query on a schedule — opens a monitor prefilled with this SQL"
            onClick={() => onSchedule(result.sql)}
          >
            Schedule
          </Button>
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
        <Button
          variant="ghost" size="xs" className="aug-fs-ui"
          title={filters.length
            ? "Download the FILTERED rows as CSV"
            : "Download these rows as CSV"}
          onClick={() => downloadCsv(csvFilename(), toCsv(columns, rows))}
        >
          CSV
        </Button>
        <Button
          variant="ghost" size="xs" className="aug-fs-ui"
          title="Copy these rows to the clipboard, tab-separated (pastes into a spreadsheet)"
          onClick={() => {
            const tsv = toTsv(columns, rows);
            const settle = (s: "ok" | "fail") => {
              setCopyState(s);
              setTimeout(() => setCopyState(""), 1600);
            };
            // The clipboard API rejects on an insecure origin, without focus, or when
            // permission is denied. Swallowing that leaves the user clicking a button
            // that does nothing and says nothing — so the failure is SHOWN, and CSV
            // (which needs no permission) stays available beside it.
            const write = navigator.clipboard?.writeText(tsv);
            if (write) write.then(() => settle("ok")).catch(() => settle("fail"));
            else settle("fail");
          }}
        >
          {copyState === "ok" ? "Copied" : copyState === "fail" ? "Copy failed" : "Copy"}
        </Button>
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
