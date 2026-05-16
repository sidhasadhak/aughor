"use client";

import { useEffect, useRef, useState } from "react";
import { ChatTurn } from "@/lib/useChat";

// ── Shared helpers (mirrors ReportView/InvestigationChart) ────────────────────

const DATE_COL = /(_date|_at|_time|created_at|updated_at|timestamp)$/i;
const SHARE_COL = /(share|pct|percent|rate|ratio|proportion)/i;
const ORDINAL_COL = /(year|month|day|week|rank|_id$|^id$)/i;

function isNumeric(v: unknown): boolean {
  return v !== null && v !== "" && !isNaN(Number(v));
}

function fmt(col: string, val: unknown): string {
  if (val === null || val === "NULL") return "—";
  const s = String(val);
  if (ORDINAL_COL.test(col)) return s;
  const n = Number(val);
  if (!isNaN(n)) {
    if (SHARE_COL.test(col) && n >= 0 && n <= 1) return `${(n * 100).toFixed(2)}%`;
    if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    if (!Number.isInteger(n)) return n.toFixed(2);
    return n.toLocaleString();
  }
  return s;
}

// ── KPI cards (single-row numeric result) ────────────────────────────────────
function KPICards({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  const row = rows[0];
  const numericCols = columns.filter(
    (c, i) => isNumeric(row[i]) && !ORDINAL_COL.test(c)
  );
  if (!numericCols.length) return null;
  return (
    <div className="flex flex-wrap gap-3 mt-2">
      {numericCols.slice(0, 3).map((col) => {
        const idx = columns.indexOf(col);
        return (
          <div key={col} className="bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-3 min-w-[100px]">
            <p className="text-xs text-zinc-500 mb-1">{col}</p>
            <p className="text-xl font-semibold text-zinc-100 tabular-nums">{fmt(col, row[idx])}</p>
          </div>
        );
      })}
    </div>
  );
}

// ── Mini table ───────────────────────────────────────────────────────────────
function MiniTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  return (
    <div className="mt-2 overflow-x-auto rounded-lg border border-zinc-800">
      <table className="text-xs w-full">
        <thead>
          <tr className="border-b border-zinc-800 bg-zinc-900">
            {columns.map((c) => (
              <th key={c} className="px-3 py-2 text-left font-medium text-zinc-400 whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 20).map((row, i) => (
            <tr key={i} className="border-b border-zinc-800/50 last:border-0 hover:bg-zinc-900/50 transition-colors">
              {columns.map((col, j) => (
                <td key={j} className="px-3 py-1.5 text-zinc-300 font-mono whitespace-nowrap">
                  {fmt(col, (row as unknown[])[j])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 20 && (
        <p className="text-[10px] text-zinc-600 px-3 py-1.5 border-t border-zinc-800">
          Showing 20 of {rows.length} rows
        </p>
      )}
    </div>
  );
}

// ── Inline chart (Observable Plot) ───────────────────────────────────────────
function InlineChart({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || !rows.length) return;
    ref.current.innerHTML = "";

    const dateCol = columns.find((c) => DATE_COL.test(c));
    const numCol = columns.find((c, i) => !DATE_COL.test(c) && isNumeric(rows[0]?.[i]));
    const catCol = !dateCol ? columns.find((c, i) => !isNumeric(rows[0]?.[i])) : undefined;

    if (!numCol) return;
    const numIdx = columns.indexOf(numCol);

    import("@observablehq/plot").then((Plot) => {
      let chart: Element | null = null;
      const data = rows.map((r) => {
        const obj: Record<string, unknown> = {};
        columns.forEach((c, i) => { obj[c] = (r as unknown[])[i]; });
        return obj;
      });

      if (dateCol) {
        const dateIdx = columns.indexOf(dateCol);
        const parsed = data.map((d) => ({ ...d, [dateCol]: new Date(d[dateCol] as string), [numCol]: Number(d[numCol]) }));
        chart = Plot.plot({
          height: 160,
          marginLeft: 48,
          style: { background: "transparent", color: "#a1a1aa" },
          x: { type: "time" },
          y: { grid: true, tickFormat: (v: number) => Math.abs(v) >= 1e6 ? `${(v/1e6).toFixed(1)}M` : Math.abs(v) >= 1e3 ? `${(v/1e3).toFixed(0)}k` : String(v) },
          marks: [
            Plot.areaY(parsed, { x: dateCol, y: numCol, fill: "#10b981", fillOpacity: 0.08 }),
            Plot.lineY(parsed, { x: dateCol, y: numCol, stroke: "#10b981", strokeWidth: 1.5 }),
          ],
        });
      } else if (catCol) {
        const catIdx = columns.indexOf(catCol);
        const agg = new Map<string, number>();
        data.forEach((d) => {
          const k = String(d[catCol]);
          agg.set(k, (agg.get(k) ?? 0) + Number(d[numCol]));
        });
        const sorted = [...agg.entries()].sort((a, b) => b[1] - a[1]).slice(0, 15);
        chart = Plot.plot({
          height: Math.max(100, sorted.length * 22),
          marginLeft: 120,
          style: { background: "transparent", color: "#a1a1aa" },
          x: { grid: true, tickFormat: (v: number) => Math.abs(v) >= 1e6 ? `${(v/1e6).toFixed(1)}M` : Math.abs(v) >= 1e3 ? `${(v/1e3).toFixed(0)}k` : String(v) },
          marks: [
            Plot.barX(sorted.map(([k, v]) => ({ cat: k, val: v })), { x: "val", y: "cat", fill: "#818cf8", sort: { y: "-x" } }),
          ],
        });
      }

      if (chart && ref.current) ref.current.appendChild(chart);
    });
  }, [columns, rows]);

  return <div ref={ref} className="mt-2 overflow-x-auto" />;
}

// ── Result body ───────────────────────────────────────────────────────────────
function ResultBody({ turn }: { turn: ChatTurn }) {
  const { columns, rows } = turn;
  if (!columns.length) return null;

  const isSingleRow = rows.length === 1;
  const hasDate = columns.some((c) => DATE_COL.test(c));
  const hasCat = columns.some((c, i) => !isNumeric(rows[0]?.[i]));
  const hasNum = columns.some((c, i) => isNumeric(rows[0]?.[i]) && !ORDINAL_COL.test(c));
  const showChart = rows.length >= 3 && hasNum && (hasDate || hasCat);

  return (
    <>
      {isSingleRow && hasNum ? (
        <KPICards columns={columns} rows={rows} />
      ) : showChart ? (
        <InlineChart columns={columns} rows={rows} />
      ) : (
        <MiniTable columns={columns} rows={rows} />
      )}
      {!isSingleRow && (
        <p className="text-[10px] text-zinc-600 mt-1">{rows.length} rows</p>
      )}
    </>
  );
}

// ── SQL collapsible ───────────────────────────────────────────────────────────
function SQLCollapsible({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors flex items-center gap-1"
      >
        <span>{open ? "▲" : "▼"}</span> SQL
      </button>
      {open && (
        <pre className="mt-1 text-[10px] font-mono text-zinc-500 bg-zinc-900 rounded p-2 overflow-x-auto whitespace-pre-wrap">
          {sql}
        </pre>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export function ChatMessage({ turn }: { turn: ChatTurn }) {
  return (
    <div className="space-y-2">
      {/* Question bubble — right */}
      <div className="flex justify-end">
        <div className="max-w-[80%] bg-zinc-800 rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm text-zinc-100">
          {turn.question}
        </div>
      </div>

      {/* Answer bubble — left */}
      <div className="flex justify-start">
        <div className="max-w-[90%] min-w-[200px]">
          {turn.status === "loading" && (
            <div className="flex items-center gap-2 px-4 py-3 bg-zinc-900 border border-zinc-800 rounded-2xl rounded-tl-sm">
              <span className="flex gap-1">
                {[0, 150, 300].map((d) => (
                  <span
                    key={d}
                    className="w-1.5 h-1.5 rounded-full bg-zinc-600 animate-bounce"
                    style={{ animationDelay: `${d}ms` }}
                  />
                ))}
              </span>
            </div>
          )}

          {turn.status === "error" && (
            <div className="px-4 py-3 bg-red-500/5 border border-red-500/20 rounded-2xl rounded-tl-sm">
              <p className="text-xs text-red-400">{turn.error}</p>
              {turn.sql && <SQLCollapsible sql={turn.sql} />}
            </div>
          )}

          {turn.status === "done" && (
            <div className="px-4 py-3 bg-zinc-900 border border-zinc-800 rounded-2xl rounded-tl-sm">
              {turn.headline && (
                <p className="text-sm text-zinc-300 mb-1">{turn.headline}</p>
              )}
              <ResultBody turn={turn} />
              {turn.sql && <SQLCollapsible sql={turn.sql} />}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
