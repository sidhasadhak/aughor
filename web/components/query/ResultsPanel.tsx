"use client";

/**
 * SE-1 — the results panel: the grid plus the facts about the run.
 *
 * Errors render INLINE here, never as a toast. A failed query is the primary content
 * of this pane at that moment — a toast would put the one thing the user needs to read
 * on a timer, next to the editor they need to fix. It also keeps the failure visible
 * while they edit, which is when it is actually useful.
 *
 * The footer states what the run cost and whether it is complete. `truncated` is the
 * load-bearing one: the server's n+1 probe row is what makes it honest, so "first 500"
 * means there provably are more, not that we stopped counting.
 */
import { formatCount } from "@/lib/format";
import { ResultsGrid } from "@/components/query/ResultsGrid";
import type { TypedQueryResult } from "@/lib/api";

const noteStyle: React.CSSProperties = { fontSize: 11, color: "var(--t3)" };

export function ResultsPanel({
  result,
  error,
  running,
}: {
  result: TypedQueryResult | null;
  error: string;
  running: boolean;
}) {
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
            fontFamily: "var(--font-code, monospace)", fontSize: 12,
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

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}>
      <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
        {empty ? (
          <div style={{ ...noteStyle, padding: "12px 14px" }}>
            No rows returned.
          </div>
        ) : (
          <ResultsGrid
            columns={result.columns}
            columnsTyped={result.columns_typed}
            rows={result.rows}
            maxHeight={100000}
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
        <span>{formatCount(result.row_count)} {result.row_count === 1 ? "row" : "rows"}</span>
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
