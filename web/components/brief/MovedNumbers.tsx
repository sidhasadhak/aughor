"use client";

/**
 * §1 of the Briefing — the numbers that moved (Aughor Intelligence · 01 Briefing).
 *
 * Receipts are columns, not badges: each row is scanned across — the latest bucket, the one
 * before it, the move, its trend, the receipt of the query behind them — so the verdict above
 * never has to carry the evidence.
 *
 * What is NOT drawn, and why: the design ranks rows by contribution and prints a contribution
 * column. Nothing computes a metric's contribution to the verdict, so the column is left out
 * rather than filled, and rows keep the business profile's order. A row still computing says
 * so; a metric whose query failed keeps its row and its reason, never a figure.
 */
import { useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";

import { GroundedNumber } from "@/components/brief/GroundedNumber";
import type { MoveRow } from "@/components/brief/moves";
import { Sparkline } from "@/components/brief/Sparkline";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { Button } from "@/components/ui/button";
import { ReceiptRef } from "@/components/WhyThisNumber";
import { useVizConfigs } from "@/lib/useVizConfigs";

type Tone = "good" | "bad" | "flat";

const toneOf = (row: MoveRow): Tone =>
  row.delta?.favorable === true ? "good" : row.delta?.favorable === false ? "bad" : "flat";

const SPARK: Record<Tone, string> = { good: "var(--grn3)", bad: "var(--red3)", flat: "var(--chart-deemph)" };

/** A click inside a cell that has its own door must not also open the row. */
const own = (e: MouseEvent) => e.stopPropagation();

/** The overall figure answers "why this number" with the value query and its cell. */
function Overall({ row }: { row: MoveRow }): ReactNode {
  if (!row.overall) return "—";
  return (
    <span onClick={own}>
      <GroundedNumber
        token={row.overall}
        resolve={async () => ({
          sql: row.valueSql, grounded: true, matchedCell: row.overallRaw ?? null,
          note: "The metric's value query, run live.",
        })}
      />
    </span>
  );
}

export function MovedNumbers({ rows, scopeKey }: {
  rows: MoveRow[];
  /** Scope for persisting a trend chart's display (keyed `kpi:<name>`, as the KPI tiles did). */
  scopeKey?: string;
}) {
  const [openName, setOpenName] = useState<string | null>(null);
  const { configFor, save } = useVizConfigs(scopeKey ?? "");
  const open = rows.find(r => r.name === openName && r.chart && r.chart.rows.length >= 2) ?? null;

  return (
    <>
      <div className="aug-moves-wrap">
        <table className="aug-dt aug-moves">
          <thead>
            <tr>
              <th>metric</th>
              <th className="num">now</th>
              <th className="num">prior</th>
              <th className="num">Δ</th>
              <th>trend</th>
              <th className="num">receipt</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              if (r.state === "pending") {
                return (
                  <tr key={r.name} aria-busy="true">
                    <td className="aug-moves-metric">{r.name}</td>
                    <td className="num aug-moves-prior">—</td>
                    <td className="num aug-moves-prior">—</td>
                    <td className="num aug-moves-writing">computing</td>
                    <td><span className="aug-skeleton aug-moves-spark-skel" /></td>
                    <td className="num aug-moves-prior">pending</td>
                  </tr>
                );
              }
              if (r.state === "dropped") {
                return (
                  <tr key={r.name} className="aug-moves-dropped">
                    <td className="aug-moves-metric">{r.name}</td>
                    <td className="num">—</td>
                    <td className="num">—</td>
                    <td className="num" title={r.reason}>no value</td>
                    <td />
                    <td className="num">—</td>
                  </tr>
                );
              }
              const tone = toneOf(r);
              const expandable = !!(r.chart && r.chart.rows.length >= 2);
              const isOpen = open?.name === r.name;
              const toggle = () => setOpenName(isOpen ? null : r.name);
              return (
                <tr key={r.name}
                  aria-selected={isOpen || undefined}
                  className={expandable ? "aug-moves-expandable" : undefined}
                  tabIndex={expandable ? 0 : undefined}
                  onClick={expandable ? toggle : undefined}
                  onKeyDown={expandable ? (e: KeyboardEvent) => {
                    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
                  } : undefined}
                  title={expandable ? (isOpen ? "Close the trend" : "Open the trend") : undefined}>
                  <td className="aug-moves-metric">
                    {r.name}
                    {r.series && r.overall && (
                      <span className="aug-moves-overall"><Overall row={r} /> overall</span>
                    )}
                  </td>
                  <td className="num" title={r.nowLabel}>{r.series ? r.now : <Overall row={r} />}</td>
                  <td className="num aug-moves-prior" title={r.priorLabel}>{r.series ? r.prior : "—"}</td>
                  <td className={`num aug-moves-${tone}`}>{r.delta?.text ?? "—"}</td>
                  <td>
                    {r.series
                      ? <Sparkline values={r.series} width={76} height={14} color={SPARK[tone]} showDot={false} />
                      : <span className="aug-moves-prior">not a time series</span>}
                  </td>
                  <td className="num" onClick={own}>
                    {r.receiptId ? <ReceiptRef receiptId={r.receiptId} /> : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {open?.chart && (
        <div className="aug-moves-detail aug-anim-up">
          <div className="aug-moves-detail-head">
            <span>{open.name}</span>
            <Button variant="ghost" size="xs" onClick={() => setOpenName(null)}>Close</Button>
          </div>
          <ResultChartCard columns={open.chart.columns} rows={open.chart.rows} title={open.name}
            config={configFor(`kpi:${open.name}`)}
            onConfigChange={scopeKey ? c => save(`kpi:${open.name}`, c) : undefined} />
        </div>
      )}
    </>
  );
}
