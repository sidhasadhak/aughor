"use client";

/**
 * SE-2 PR D — the history rail: what this connection has actually run.
 *
 * A filtered read of the AUDIT LOG, not a second store. Every workbench run already
 * writes an audit row tagged `query_workbench` (SE-0 added both the tag and the
 * `label` filter for exactly this), so history is a view over the record that has to
 * exist anyway. A dedicated history table would be a second source of truth that could
 * disagree with the audit — and the audit is the one with the compliance claim on it.
 *
 * That inheritance is why each row shows the VERDICT alongside duration and rows: the
 * log's purpose is to record what the guards decided, and a history that showed only
 * "ran, 5 rows" would drop the most interesting fact about a query that was blocked.
 */
import { useCallback, useEffect, useState } from "react";
import { getQueryHistory, type AuditRecord } from "@/lib/api";
import { relTime } from "@/lib/format";
import { Button } from "@/components/ui/button";

const VERDICT_COLOR: Record<string, string> = {
  safe: "var(--grn4)",
  blocked: "var(--red4)",
  suspicious: "var(--amb4)",
};

/** One line of SQL for the rail, collapsed from whatever the user wrote. */
function preview(sql: string): string {
  return (sql || "").replace(/\s+/g, " ").trim().slice(0, 90);
}

export function HistoryRail({
  connId,
  refreshKey,
  onRestore,
}: {
  connId: string;
  /** Bump to re-read after a run — the rail is a read of a log this surface writes. */
  refreshKey: number;
  onRestore: (sql: string) => void;
}) {
  const [rows, setRows] = useState<AuditRecord[]>([]);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(() => {
    if (!connId) { setRows([]); setLoaded(true); return; }
    getQueryHistory(connId)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoaded(true));
  }, [connId]);

  useEffect(() => { load(); }, [load, refreshKey]);

  return (
    <div
      style={{
        width: 260, flexShrink: 0, display: "flex", flexDirection: "column",
        borderLeft: "1px solid var(--b1)", background: "var(--bg-1)", overflow: "hidden",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "8px 10px 6px", flexShrink: 0 }}>
        <span className="aug-label">History</span>
        <Button variant="ghost" size="xs" onClick={load} title="Refresh">↻</Button>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "0 6px 8px" }}>
        {loaded && rows.length === 0 && (
          <div style={{ fontSize: 11, color: "var(--t4)", padding: "6px 4px", lineHeight: 1.5 }}>
            Queries you run here appear in this list.
          </div>
        )}
        {rows.map(r => (
          <Button
            key={r.id}
            variant="ghost"
            onClick={() => onRestore(r.sql_full || r.sql_digest)}
            title="Open this query in a new tab"
            className="mb-0.5 block h-auto w-full whitespace-normal px-2 py-1.5 text-left font-normal"
          >
            <span
              style={{
                display: "block", fontFamily: "var(--font-code, monospace)", fontSize: 10,
                color: "var(--t2)", overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {preview(r.sql_full || r.sql_digest)}
            </span>
            <span style={{ display: "block", fontSize: 10, color: "var(--t4)", marginTop: 2 }}>
              <span style={{ color: VERDICT_COLOR[r.verdict] ?? "var(--t4)" }}>{r.verdict}</span>
              {r.row_count != null && ` · ${r.row_count} rows`}
              {r.duration_ms != null && ` · ${Math.round(r.duration_ms)} ms`}
              {r.ts && ` · ${relTime(r.ts)} ago`}
            </span>
          </Button>
        ))}
      </div>
    </div>
  );
}
