"use client";

/**
 * The North Star, at the head of Decisions (Track G5; the user chose the place, 2026-11-06).
 *
 * One line — loops closed this quarter · calibration error, each with its n, as the 2027 study (§X) reports
 * it: a pair, never one figure. "Why" opens, in place, what kept each outcome from closing (by rule) and the
 * calibration table by metric. The numbers are the server's (`record/north_star.py`); nothing is computed here.
 */
import { useState } from "react";

import { SqlResultTable } from "@/components/AugTable";
import { useLoad } from "@/components/record/kit";
import { Button } from "@/components/ui/button";
import { countNoun, formatCount } from "@/lib/format";
import { getNorthStar, type NorthStar } from "@/lib/record";

/** The reasons, one line per rule, most frequent first. */
export function reasonsByRule(s: NorthStar): { rule: string; n: number }[] {
  const n = new Map<string, number>();
  for (const r of s.not_closed) {
    const rule = r.rule || r.not_closed || "not closed";
    n.set(rule, (n.get(rule) ?? 0) + 1);
  }
  return [...n.entries()].map(([rule, k]) => ({ rule, n: k })).sort((a, b) => b.n - a.n || a.rule.localeCompare(b.rule));
}

export function NorthStarLine() {
  const load = useLoad(() => getNorthStar(), []);
  const [open, setOpen] = useState(false);
  if (load.loading && !load.data) return null;
  if (load.error) {
    return <p className="aug-fs-sm" style={{ color: "var(--t3)", margin: 0 }} data-testid="north-star-error">
      The North Star could not be read: {load.error}</p>;
  }
  const s = load.data;
  if (!s) return null;
  const cal = s.calibration;
  // Worst-calibrated first: the classes a reader should distrust lead the table.
  const classes = cal.classes.filter(c => c.gap !== null).sort((a, b) => (b.gap ?? 0) - (a.gap ?? 0) || b.judged - a.judged);
  const two = (v: number | null | undefined) => (v == null ? null : Math.round(v * 100) / 100);
  return (
    <section aria-label="North Star" data-testid="north-star" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <span className="aug-fs-xs" style={{ color: "var(--t3)", letterSpacing: "0.04em" }}>NORTH STAR · {s.quarter}</span>
        <span className="aug-text-ui" data-testid="north-star-sentence">
          <strong>{formatCount(s.loops_closed)}</strong> {s.loops_closed === 1 ? "loop" : "loops"} closed
          of {countNoun(s.outcomes_written, "outcome")} written
          <span style={{ color: "var(--t3)" }}> · </span>
          {cal.n
            ? <>calibration error <strong>{cal.error?.toFixed(2)}</strong> over {countNoun(cal.n, "settled prediction")}</>
            : <>calibration error: no prediction settled this quarter</>}
        </span>
        <Button size="xs" variant="secondary" aria-expanded={open} onClick={() => setOpen(v => !v)}
          title="What kept each outcome from closing, and how each metric's intervals held">
          Why {open ? "▴" : "▾"}
        </Button>
      </div>
      {open && (
        <div data-testid="north-star-why" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <ul className="aug-fs-sm" style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
            {s.outcomes_written === 0 && <li>No outcome was written this quarter, so no loop could close.</li>}
            {reasonsByRule(s).map(r => (
              <li key={r.rule} data-testid="north-star-reason">{formatCount(r.n)} not closed — {r.rule}</li>
            ))}
            {s.reliance_without_expectation > 0 && (
              <li>{countNoun(s.reliance_without_expectation, "decision")} with an outcome booked no expectation: reliance
                recorded, not a loop that can close</li>
            )}
            <li style={{ color: "var(--t3)" }}>
              A loop closes when its decision has an owner, a prediction booked with it, an outcome written on or after
              the review date that says both verdicts (or why it cannot tell), and the write-back ran.
            </li>
          </ul>
          {classes.length > 0 && (
            <SqlResultTable
              columns={["metric", "method", "stated coverage", "observed coverage", "gap", "judged", "cannot tell"]}
              rows={classes.map(c => [c.metric, c.method, two(c.stated), two(c.observed), two(c.gap), c.judged, c.cannot_tell])}
              maxHeight={320} />
          )}
        </div>
      )}
    </section>
  );
}
