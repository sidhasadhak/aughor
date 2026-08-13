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
import { useState } from "react";
import { formatCount } from "@/lib/format";
import { ResultsGrid } from "@/components/query/ResultsGrid";
import { Button } from "@/components/ui/button";
import type { TypedQueryResult } from "@/lib/api";

/** RFC-4180 escaping. A result set is arbitrary user data: a cell containing a comma,
 *  a quote or a newline must survive the round trip, or the export silently corrupts
 *  the rows it was meant to preserve. NULL exports as an EMPTY field rather than the
 *  `∅` display glyph — the glyph is for reading, and a spreadsheet should see a blank,
 *  not a symbol it would treat as text. */
function toCsv(columns: string[], rows: (string | number | boolean | null)[][]): string {
  const cell = (v: string | number | boolean | null) => {
    if (v === null) return "";
    const s = String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map(cell).join(","), ...rows.map(r => r.map(cell).join(","))].join("\r\n");
}

function download(name: string, body: string): void {
  try {
    const url = URL.createObjectURL(new Blob([body], { type: "text/csv;charset=utf-8;" }));
    const a = document.createElement("a");
    a.href = url; a.download = name;
    a.click();
    // Revoked on the next tick rather than immediately: some browsers have not yet
    // read the blob when click() returns, and revoking early yields an empty file.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch { /* a blocked download must not take the panel down */ }
}

const noteStyle: React.CSSProperties = { fontSize: 13, color: "var(--t3)" };

export function ResultsPanel({
  result,
  error,
  running,
}: {
  result: TypedQueryResult | null;
  error: string;
  running: boolean;
}) {
  // "" | "ok" | "fail" — a click must always produce a visible outcome.
  const [copyState, setCopyState] = useState<"" | "ok" | "fail">("");

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
        <Button
          variant="ghost" size="xs" className="aug-fs-ui"
          title="Download these rows as CSV"
          onClick={() => download(
            `query-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.csv`,
            toCsv(result.columns, result.rows),
          )}
        >
          CSV
        </Button>
        <Button
          variant="ghost" size="xs" className="aug-fs-ui"
          title="Copy these rows to the clipboard, tab-separated (pastes into a spreadsheet)"
          onClick={() => {
            // TSV, not CSV, for the clipboard: spreadsheets paste tab-separated text
            // straight into cells, while CSV lands in a single column.
            const tsv = [result.columns.join("\t"),
              ...result.rows.map(r => r.map(v => (v === null ? "" : String(v))).join("\t"))].join("\n");
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
