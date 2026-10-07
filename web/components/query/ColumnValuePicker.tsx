"use client";

/**
 * DE-5c (ROADMAP §3.51) — the distinct values of one column, to pick a filter from.
 *
 * Two sources, and the panel SAYS which (the repo's rule: withheld is said, never implied):
 *
 *  * the rows on screen — exact counts, and complete when the result was not cut;
 *  * the table itself, read live through the door, when the result WAS cut and the statement
 *    reads exactly one table — then the rows on screen are a sample, and a value absent from
 *    them may still be in the data. The live read has no counts, and says so by showing none.
 *
 * When the result was cut and the table cannot be read (a join, a computed column, a refusal),
 * the panel shows the rows' values and says that more may exist. A pick becomes a chip through
 * the filter grammar, like every other filter.
 */
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { formatCount } from "@/lib/format";
import { NULL_GLYPH, distinctFromRows, pickedPhrase, type DistinctValue } from "@/lib/query/cellMenu";
import type { Cell } from "@/lib/query/resultFilter";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";

/** What a live read of the table answers. `source` names the table. DE-5d: `error` is the route's typed
 *  refusal, in the engine's words — the table was asked and could not be read, which is not "no values". */
export interface LiveDistinct { values: (string | null)[]; truncated: boolean; source: string; error?: string }

/** How many values the list shows before it says "and N more". */
const SHOWN = 200;

export function ColumnValuePicker({
  column,
  rows,
  columnIndex,
  truncated,
  fetchDistinct,
  onApply,
  onClose,
  style,
}: {
  column: string;
  rows: readonly Cell[][];
  columnIndex: number;
  /** The result was cut at its row limit: the rows on screen are a sample of the column. */
  truncated: boolean;
  /** Read the column's distinct values from the table itself; undefined when no table can be
   *  named for this result. Resolves null when the table could not be read. */
  fetchDistinct?: (column: string) => Promise<LiveDistinct | null>;
  onApply: (phrase: string) => void;
  onClose: () => void;
  style?: React.CSSProperties;
}) {
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [search, setSearch] = useState("");
  const [live, setLive] = useState<LiveDistinct | null | "loading">(truncated && fetchDistinct ? "loading" : null);

  useEffect(() => {
    if (!truncated || !fetchDistinct) return;
    let stale = false;
    setLive("loading");
    fetchDistinct(column)
      .then(r => { if (!stale) setLive(r && (r.values.length || r.error) ? r : null); })
      .catch(() => { if (!stale) setLive(null); });
    return () => { stale = true; };
  }, [column, truncated, fetchDistinct]);

  const fromRows = useMemo(() => distinctFromRows(rows, columnIndex), [rows, columnIndex]);
  // DE-5d: the table's answer, once it has one — a list, or a refusal. A refusal is said, and the
  // values then come from the rows.
  const answer: LiveDistinct | null = live && live !== "loading" ? live : null;
  const refused = !!answer?.error;
  const liveRead = !!answer && !answer.error;
  const values: DistinctValue[] = useMemo(() => {
    if (liveRead && answer) return answer.values.map(v => ({ value: v, count: 0 }));
    return fromRows;
  }, [answer, liveRead, fromRows]);

  const source = live === "loading"
    ? "Reading the table's values…"
    : liveRead && answer
      // The live read is the route's `SELECT DISTINCT … WHERE … IS NOT NULL`: NULL is never in the
      // list, so the line says so rather than letting its absence read as "the column has none".
      ? `From the table ${answer.source}, read live${answer.truncated ? ` — the first ${formatCount(answer.values.length)},` : " —"} NULL not listed`
      : refused && answer
        ? `The table ${answer.source} could not be read live (${answer.error}) — from the ${formatCount(rows.length)} rows shown; the result was cut, so more values may exist`
        : truncated
          ? `From the ${formatCount(rows.length)} rows shown — the result was cut, so more values may exist`
          : `From the ${formatCount(rows.length)} rows shown`;

  const q = search.trim().toLowerCase();
  const shown = values.filter(v => !q || String(v.value ?? NULL_GLYPH).toLowerCase().includes(q));
  const keyOf = (v: Cell) => (v === null ? "\u0000null" : `${typeof v}:${String(v)}`);
  const toggle = (v: Cell) => setPicked(prev => {
    const next = new Set(prev);
    const k = keyOf(v);
    if (next.has(k)) next.delete(k); else next.add(k);
    return next;
  });
  const apply = () => {
    const chosen = values.filter(v => picked.has(keyOf(v.value))).map(v => v.value);
    if (chosen.length) onApply(pickedPhrase(column, chosen));
    onClose();
  };

  return (
    <div data-testid="column-value-picker" className="aug-fs-ui" style={{
      position: "absolute", zIndex: 12, width: 300, maxHeight: 360, display: "flex", flexDirection: "column",
      background: "var(--bg-2)", border: "1px solid var(--b2)", borderRadius: "var(--r2)",
      boxShadow: "var(--shadow-md)", ...style,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 8px 2px" }}>
        <span style={{ color: "var(--t2)", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap", flex: 1 }}>{column}</span>
        <Button variant="ghost" size="xs" aria-label="Close" onClick={onClose}><Icon name="close" size={12} /></Button>
      </div>
      <div className="aug-fs-xs" data-testid="picker-source" style={{ color: liveRead ? "var(--t3)" : truncated ? "var(--amb4)" : "var(--t3)",
        padding: "0 8px 6px" }}>
        {source}
      </div>
      <Input bespoke
        className="aug-fs-sm"
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder={`Search ${formatCount(values.length)} values`}
        aria-label={`Search values of ${column}`}
        style={{ margin: "0 8px 6px", background: "var(--bg-0)", border: "1px solid var(--b1)",
          borderRadius: "var(--r1)", color: "var(--t1)", padding: "2px 7px", outline: "none" }}
      />
      <div style={{ overflowY: "auto", flex: 1, minHeight: 0, padding: "0 4px" }}>
        {shown.slice(0, SHOWN).map(v => {
          const k = keyOf(v.value);
          return (
            <label key={k} style={{ display: "flex", alignItems: "center", gap: 7, padding: "2px 6px",
              cursor: "pointer", color: v.value === null ? "var(--t3)" : "var(--t2)" }}>
              <Checkbox checked={picked.has(k)} onChange={() => toggle(v.value)} />
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                fontFamily: "var(--font-code, monospace)" }}>{v.value === null ? NULL_GLYPH : String(v.value)}</span>
              {v.count > 0 && (
                <span className="aug-fs-xs" style={{ color: "var(--t3)", fontVariantNumeric: "tabular-nums" }}>
                  {formatCount(v.count)}
                </span>
              )}
            </label>
          );
        })}
        {shown.length > SHOWN && (
          <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "4px 6px" }}>
            and {formatCount(shown.length - SHOWN)} more — search to narrow
          </div>
        )}
        {!shown.length && (
          <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "4px 6px" }}>
            {live === "loading" ? "" : "No value matches"}
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 6, padding: 8, borderTop: "1px solid var(--b0)" }}>
        <Button size="xs" variant="secondary" disabled={!picked.size} onClick={apply} data-testid="picker-apply">
          <Icon name="filter" size={12} /> Filter to {picked.size ? formatCount(picked.size) : ""} {picked.size === 1 ? "value" : "values"}
        </Button>
        <Button size="xs" variant="ghost" onClick={onClose}>Cancel</Button>
      </div>
    </div>
  );
}
