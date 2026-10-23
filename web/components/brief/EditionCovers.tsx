/**
 * What each of the Briefing's six editions covers, when the data has ENDED (the Olist run, 2026-10-22;
 * design-mockups/briefing-data-ended.html, approved 2026-10-23). Every edition reads as if today were
 * the day after the data's last row, so the reader checks here where each one landed, what it is
 * compared with, and the lead approved metric's figure for each. A comparison whose earlier range
 * starts before the data does is withheld, and the row says why. Measured when shown: warehouse
 * queries, no model call.
 */
import { useEffect, useState } from "react";

import { Ledger, type LedgerColumn } from "@/components/record/kit";
import { readEditionCovers, type EditionCover, type EditionCovers as Covers } from "@/lib/api";
import { formatVariance, spanWords } from "@/lib/format";

/** The table's anchor: the notice under the dateline scrolls here. */
export const COVERS_ANCHOR = "briefing-edition-covers";

export function scrollToCovers(): void {
  document.getElementById(COVERS_ANCHOR)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

/** What a row says beside its figure: why it is not compared, or why it has no figure. */
export function besideWords(r: EditionCover): string {
  if (r.compare_withheld) return `Not compared: ${r.compare_withheld}.`;
  if (!r.current_text && r.why) return r.why[0].toUpperCase() + r.why.slice(1) + ".";
  return "";
}

export function EditionCovers({ connectionId, schema, workspaceId, current }: {
  connectionId: string;
  schema?: string;
  workspaceId?: string;
  /** The edition on screen, marked in the table. */
  current?: string;
}) {
  const [got, setGot] = useState<{ key: string; data?: Covers; error?: string } | null>(null);
  const key = `${connectionId}|${schema ?? ""}|${workspaceId ?? ""}`;
  useEffect(() => {
    let alive = true;
    readEditionCovers(connectionId, schema, workspaceId)
      .then(data => { if (alive) setGot({ key, data }); })
      .catch(e => { if (alive) setGot({ key, error: e instanceof Error ? e.message : String(e) }); });
    return () => { alive = false; };
  }, [connectionId, schema, workspaceId, key]);
  const mine = got && got.key === key ? got : null;
  const data = mine?.data ?? null;
  // Short cells, the full sentence as a title: the ledger sizes to its content and never wraps, so the
  // server's phrases ("the year to the data's last day, 2018-01-01 to 2018-10-17") pushed Change and
  // the reasons out of sight (measured 1,780px in a 1,133px column on Olist, 2026-10-23).
  const columns: LedgerColumn<EditionCover>[] = [
    { head: "Edition", cell: r => r.label, width: 120 },
    { head: "Covers", cell: r => <span title={r.covers}>{spanWords(r.start, r.last_day)}</span> },
    { head: "Compared with", cell: r => r.compare_withheld
        ? <span style={{ color: "var(--t3)" }}>not compared</span>
        : <span title={r.compared_with}>{spanWords(r.previous_start, r.previous_last_day)}</span> },
    { head: "Figure", cell: r => r.current_text ?? "", num: true, width: 130 },
    { head: "Change", cell: r => formatVariance(r.rel), num: true, width: 90 },
    { head: "Said beside it", cell: r => (
        <span style={{ display: "inline-block", whiteSpace: "normal", maxWidth: 420, color: "var(--t2)" }}>{besideWords(r)}</span>
      ) },
  ];
  return (
    <div id={COVERS_ANCHOR} data-testid="edition-covers" style={{ padding: "16px 0", borderBottom: "1px solid var(--b1)" }}>
      <h3 className="aug-fs-h1" style={{ fontFamily: "var(--font-serif)", fontWeight: 600, margin: "0 0 8px" }}>
        What each edition covers
      </h3>
      {mine?.error ? (
        <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>{mine.error}</div>
      ) : !data ? (
        <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Reading where each edition lands…</div>
      ) : (
        <>
          {data.metric && (
            <div className="aug-fs-sm" style={{ color: "var(--t3)", marginBottom: 6 }}>
              Each figure is {data.metric.label}, the lead approved metric, read for that edition&apos;s days.
            </div>
          )}
          <Ledger name="edition-covers" columns={columns} rows={data.editions} rowKey={r => r.preset}
            selected={current} empty="No edition could be read." />
          {!data.metric && (
            <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 6 }}>
              No metric is approved yet, so no edition has a figure.
            </div>
          )}
        </>
      )}
    </div>
  );
}
