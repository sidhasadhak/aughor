"use client";

/**
 * SE-4 I — the filter chips above the results grid.
 *
 * Every chip narrows the IN-MEMORY result; nothing here re-runs the query. That is the
 * whole point: exploring 500 returned rows should cost a keystroke, not a round trip to
 * the warehouse. Chips AND together and can be removed in any order, so a chain is
 * something you back out of rather than rebuild.
 *
 * A phrase that names a column we don't have gets an ERROR chip, not silence — it stays
 * visible, is excluded from the predicate chain, and says which name failed. The
 * alternative (dropping it, or matching nothing) shows an empty grid and leaves the user
 * to guess whether the data or the typo is at fault.
 */
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { parseFilter, type FilterClause, type RankSpec } from "@/lib/query/resultFilter";

export interface ActiveFilter {
  id: string;
  clause: FilterClause | null;
  rank: RankSpec | null;
  label: string;
}

let seq = 0;

export function ResultFilterBar({
  columns,
  filters,
  onChange,
  shown,
  total,
}: {
  columns: string[];
  filters: ActiveFilter[];
  onChange: (next: ActiveFilter[]) => void;
  shown: number;
  total: number;
}) {
  const [draft, setDraft] = useState("");

  function add() {
    const text = draft.trim();
    if (!text) return;
    const { clause, rank } = parseFilter(text, columns);
    if (!clause && !rank) return;
    onChange([...filters, { id: `f${++seq}`, clause, rank, label: text }]);
    setDraft("");
  }

  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap",
        padding: "5px 14px", borderBottom: "1px solid var(--b0)", flexShrink: 0,
      }}
    >
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); add(); }
          // Backspace on an empty box removes the last chip — the convention every
          // tag input has, and the fastest way to undo a filter you just typed.
          if (e.key === "Backspace" && !draft && filters.length) {
            onChange(filters.slice(0, -1));
          }
        }}
        placeholder={
          columns.length
            ? `Filter these rows — e.g. "${columns[0]} contains a", "top 10"`
            : "Filter these rows"
        }
        aria-label="Filter the returned rows"
        className="aug-fs-ui"
        style={{
          flex: "1 1 200px", minWidth: 160, background: "var(--bg-1)",
          border: "1px solid var(--b1)", borderRadius: "var(--r2)",
          padding: "3px 8px", color: "var(--t1)", outline: "none",
        }}
      />
      {filters.map((f) => {
        const bad = !!f.clause?.error;
        return (
          <span
            key={f.id}
            title={bad ? f.clause!.error : (f.clause?.describe ?? rankLabel(f.rank, columns))}
            className="aug-fs-ui"
            style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              padding: "2px 6px", borderRadius: "var(--r2)",
              border: `1px solid ${bad ? "var(--red4)" : "var(--b1)"}`,
              background: "var(--bg-1)",
              color: bad ? "var(--red4)" : "var(--t2)",
            }}
          >
            {f.label}
            <button
              onClick={() => onChange(filters.filter((x) => x.id !== f.id))}
              aria-label={`Remove filter ${f.label}`}
              style={{
                border: "none", background: "none", cursor: "pointer",
                color: "inherit", padding: 0, lineHeight: 1,
              }}
            >
              ×
            </button>
          </span>
        );
      })}
      {filters.length > 0 && (
        <>
          <span className="aug-fs-ui" style={{ color: "var(--t3)" }}>
            {shown === total ? `${total} rows` : `${shown} of ${total} rows`}
          </span>
          <Button variant="ghost" size="xs" className="aug-fs-ui" onClick={() => onChange([])}>
            Clear
          </Button>
        </>
      )}
    </div>
  );
}

function rankLabel(rank: RankSpec | null, columns: string[]): string {
  if (!rank) return "";
  return `${rank.kind} ${rank.n} by ${columns[rank.columnIndex] ?? "?"}`;
}
